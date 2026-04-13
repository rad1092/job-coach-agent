from __future__ import annotations

import uuid
from urllib.parse import urlparse

from backend.app.clients.page_fetcher import fetch_page_text
from backend.app.clients.search_client import FixtureSearchClient, SearchHit, build_search_client
from backend.app.core.settings import Settings
from backend.app.core.taxonomy import (
    BLOCKED_TEXT_KEYWORDS,
    BLOCKED_URL_KEYWORDS,
    EXCLUDED_SEARCH_DOMAINS,
    is_direct_posting_url,
    job_board_domains_for_retry,
    job_board_label_for_url,
)
from backend.app.schemas.api import CandidateCard, ExploreRequest, ExploreResponse, SourceCard

MAX_POSTING_CANDIDATES = 27
MAX_COMPANY_CANDIDATES = 6
MAX_SOURCE_CARDS = 36


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    compact = " ".join(str(value).replace(",", " ").split())
    return compact or None


def _compose_query(*parts: str | None) -> str:
    return " ".join(part for part in (_normalize_text(value) for value in parts) if part)


def _request_tokens(request: ExploreRequest) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for value in [
        request.industry,
        request.job_family,
        request.job_role,
        request.experience_level,
        request.preferences,
    ]:
        normalized = _normalize_text(value)
        if not normalized:
            continue
        for token in normalized.split():
            lowered = token.lower()
            if len(lowered) < 2 or lowered in seen:
                continue
            seen.add(lowered)
            tokens.append(lowered)
    return tokens


def build_queries(request: ExploreRequest, retry_count: int = 0) -> list[str]:
    industry = _normalize_text(request.industry) or request.industry
    job_family = _normalize_text(request.job_family) or request.job_family
    job_role = _normalize_text(request.job_role) or request.job_role
    experience_level = _normalize_text(request.experience_level)
    preferences = _normalize_text(request.preferences)

    if retry_count > 0:
        raw_queries = [
            _compose_query(industry, job_role, experience_level, preferences, "채용 공고"),
            _compose_query(job_family, job_role, preferences, "채용"),
            _compose_query(job_role, experience_level, "채용"),
            _compose_query(industry, job_role, "상세 채용"),
        ]
    else:
        raw_queries = [
            _compose_query(industry, job_family, job_role, experience_level, preferences, "채용"),
            _compose_query(industry, job_role, experience_level, preferences, "채용 공고"),
            _compose_query(job_family, job_role, preferences, "채용"),
            _compose_query(job_role, industry, "공고"),
        ]

    deduped: list[str] = []
    seen: set[str] = set()
    for query in raw_queries:
        compact = " ".join(query.split())
        if compact and compact not in seen:
            seen.add(compact)
            deduped.append(compact)
    return deduped[:4]


def _domain_for_url(url: str) -> str:
    return urlparse(url).netloc.lower()


def _domain_matches(domain: str, candidate: str) -> bool:
    return domain == candidate or domain.endswith(f".{candidate}")


def _is_allowed_job_board(url: str, allowed_domains: list[str]) -> bool:
    domain = _domain_for_url(url)
    return any(_domain_matches(domain, candidate) for candidate in allowed_domains)


def _should_skip_hit(hit: SearchHit, allowed_domains: list[str]) -> bool:
    if not hit.url or not _is_allowed_job_board(hit.url, allowed_domains):
        return True

    lowered_url = hit.url.lower()
    lowered_text = f"{hit.title} {hit.snippet}".lower()
    if any(keyword in lowered_url for keyword in BLOCKED_URL_KEYWORDS):
        return True
    if any(keyword in lowered_text for keyword in BLOCKED_TEXT_KEYWORDS):
        return True
    return False


def classify_source(hit: SearchHit, allowed_domains: list[str] | None = None) -> str:
    if allowed_domains and _is_allowed_job_board(hit.url, allowed_domains) and is_direct_posting_url(hit.url):
        return "posting"

    haystack = f"{hit.title} {hit.url} {hit.snippet}".lower()
    posting_markers = ["채용", "careers", "career", "job", "jobs", "recruit", "hiring", "position"]
    if any(marker in haystack for marker in posting_markers):
        return "posting"
    company_markers = ["about", "company", "culture", "team", "기업", "회사", "about-us"]
    if any(marker in haystack for marker in company_markers):
        return "company"
    return "general"


def build_relevance_reason(request: ExploreRequest, hit: SearchHit) -> str:
    tokens: list[str] = []
    for token in [request.industry, request.job_family, request.job_role, request.experience_level, request.preferences]:
        normalized = _normalize_text(token)
        if normalized:
            tokens.extend(normalized.split())

    haystack = f"{hit.title} {hit.snippet}".lower()
    matched = list(dict.fromkeys(token for token in tokens if token.lower() in haystack))
    if not matched:
        matched = list(dict.fromkeys(tokens))
    visible_keywords = matched[:5]
    if not visible_keywords:
        visible_keywords = ["관련 키워드 확인 필요"]
    return f"키워드 : {', '.join(visible_keywords)}"


def estimate_confidence(request: ExploreRequest, hit: SearchHit, page_text: str | None = None) -> float:
    haystack = f"{hit.title} {hit.snippet} {page_text or ''}".lower()
    tokens = _request_tokens(request)
    matched_tokens = sum(1 for token in tokens if token in haystack)
    coverage = matched_tokens / max(len(tokens), 1)

    confidence = 0.44
    if is_direct_posting_url(hit.url):
        confidence += 0.18
    if page_text:
        confidence += 0.12
    confidence += coverage * 0.2

    normalized_job_role = _normalize_text(request.job_role)
    normalized_experience = _normalize_text(request.experience_level)
    if normalized_job_role and normalized_job_role.lower() in haystack:
        confidence += 0.08
    if normalized_experience and normalized_experience.lower() in haystack:
        confidence += 0.04

    return round(min(confidence, 0.99), 2)


def summarize_text(*parts: str) -> str:
    for part in parts:
        if part:
            compact = " ".join(part.split())
            if compact:
                return compact[:240]
    return "요약 가능한 본문을 찾지 못했습니다."


async def collect_candidates(
    settings: Settings,
    request: ExploreRequest,
    queries: list[str],
    retry_count: int = 0,
) -> dict[str, list[CandidateCard] | list[SourceCard] | list[str]]:
    def _ensure_fixture_fallback_note(existing_notes: list[str]) -> None:
        note = "실시간 검색 연결에 문제가 있어 로컬 샘플 결과로 대체했습니다."
        if note not in existing_notes:
            existing_notes.append(note)

    notes: list[str] = []
    try:
        client = build_search_client(settings)
    except Exception:
        client = FixtureSearchClient(settings.data_dir)
        if settings.search_provider != "fixture":
            _ensure_fixture_fallback_note(notes)

    allowed_domains = job_board_domains_for_retry(retry_count)
    seen_urls: set[str] = set()
    source_cards: list[SourceCard] = []
    company_candidates: list[CandidateCard] = []
    posting_candidates: list[CandidateCard] = []
    search_max_results = 30 if settings.search_provider == "fixture" else 20

    for query in queries:
        try:
            hits = client.search(
                query,
                max_results=search_max_results,
                include_domains=allowed_domains,
                exclude_domains=list(EXCLUDED_SEARCH_DOMAINS),
                country="south korea",
            )
        except Exception:
            if not isinstance(client, FixtureSearchClient):
                client = FixtureSearchClient(settings.data_dir)
                _ensure_fixture_fallback_note(notes)
                hits = client.search(
                    query,
                    max_results=search_max_results,
                    include_domains=allowed_domains,
                    exclude_domains=list(EXCLUDED_SEARCH_DOMAINS),
                    country="south korea",
                )
            else:
                raise
        for hit in hits:
            if hit.url in seen_urls or _should_skip_hit(hit, allowed_domains):
                continue
            seen_urls.add(hit.url)

            if not is_direct_posting_url(hit.url):
                continue

            page_text = hit.content
            if not page_text and settings.search_provider != "fixture":
                try:
                    page_text = await fetch_page_text(hit.url)
                except Exception:
                    notes.append(f"본문 수집에 실패해 검색 결과 요약만 사용했습니다. URL: {hit.url}")

            source_type = classify_source(hit, allowed_domains)
            summary = summarize_text(hit.snippet, page_text or "")
            reason = build_relevance_reason(request, hit)
            confidence = estimate_confidence(request, hit, page_text)

            source_cards.append(
                SourceCard(
                    title=hit.title or hit.url,
                    url=hit.url,
                    source_type=source_type,
                    claim=summary,
                    confidence=confidence,
                )
            )

            posting_candidates.append(
                CandidateCard(
                    name=hit.title or hit.url,
                    kind="posting",
                    summary=summary,
                    why_relevant=reason,
                    source_url=hit.url,
                    confidence=confidence,
                )
            )

        if len(posting_candidates) >= MAX_POSTING_CANDIDATES:
            break

    if not posting_candidates:
        notes.append("조건에 맞는 진행 중인 채용공고를 충분히 찾지 못했습니다. 경력 수준이나 선호 조건을 조금 넓혀 다시 탐색해 보세요.")

    posting_candidates.sort(key=lambda candidate: (-candidate.confidence, candidate.name))
    source_cards.sort(key=lambda card: (-card.confidence, card.title))

    return {
        "company_candidates": company_candidates[:MAX_COMPANY_CANDIDATES],
        "posting_candidates": posting_candidates[:MAX_POSTING_CANDIDATES],
        "source_cards": source_cards[:MAX_SOURCE_CARDS],
        "notes": notes,
    }


async def build_explore_response(settings: Settings, request: ExploreRequest) -> ExploreResponse:
    queries = build_queries(request)
    collected = await collect_candidates(settings, request, queries)
    return ExploreResponse(
        run_id=uuid.uuid4().hex,
        queries=queries,
        company_candidates=collected["company_candidates"],
        posting_candidates=collected["posting_candidates"],
        source_cards=collected["source_cards"],
        notes=collected["notes"],
    )
