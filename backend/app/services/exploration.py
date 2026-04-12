from __future__ import annotations

import uuid

from backend.app.clients.fetch_models import confidence_for_fetch_result, note_for_fetch_result
from backend.app.clients.page_fetcher import fetch_page_content
from backend.app.clients.search_client import SearchHit, build_search_client
from backend.app.core.settings import Settings
from backend.app.core.taxonomy import normalize_job_role
from backend.app.schemas.api import CandidateCard, ExploreRequest, ExploreResponse, SourceCard


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    return compact or None


def _build_query(*parts: str | None) -> str:
    return " ".join(part for part in (_normalize_text(item) for item in parts) if part)


def build_queries(request: ExploreRequest, retry_count: int = 0) -> list[str]:
    industry = _normalize_text(request.industry) or request.industry
    job_family = _normalize_text(request.job_family) or request.job_family
    job_role = normalize_job_role(request.job_role)
    experience_level = _normalize_text(request.experience_level)
    preferences = _normalize_text(request.preferences)

    raw_queries: list[str] = []
    if retry_count > 0:
        raw_queries.extend(
            [
                _build_query(industry, job_family, "채용"),
                _build_query(job_family, "채용 공고"),
                _build_query(industry, job_family, "관련 기업"),
            ]
        )
        if job_role:
            raw_queries.append(_build_query(industry, job_family, job_role, "채용"))
        else:
            raw_queries.append(_build_query(industry, job_family, "직무 역량"))
    else:
        raw_queries.extend(
            [
                _build_query(industry, job_family, "채용"),
                _build_query(industry, job_family, "기업 채용 공고"),
            ]
        )
        if job_role:
            raw_queries.extend(
                [
                    _build_query(industry, job_family, job_role, "채용"),
                    _build_query(job_role, "직무 역량", industry),
                ]
            )
        else:
            raw_queries.append(_build_query(industry, job_family, "직무 역량"))

    if experience_level:
        raw_queries.append(_build_query(industry, job_family, experience_level, "채용"))

    if preferences:
        raw_queries.append(_build_query(industry, job_family, preferences, "채용"))

    deduped: list[str] = []
    seen: set[str] = set()
    for query in raw_queries:
        compact = " ".join(query.split())
        if compact and compact not in seen:
            seen.add(compact)
            deduped.append(compact)
    return deduped[:6]


def classify_source(hit: SearchHit) -> str:
    haystack = f"{hit.title} {hit.url} {hit.snippet}".lower()
    posting_markers = ["채용", "careers", "career", "job", "jobs", "recruit", "hiring", "position"]
    if any(marker in haystack for marker in posting_markers):
        return "posting"
    company_markers = ["about", "company", "culture", "team", "기업", "회사", "about-us"]
    if any(marker in haystack for marker in company_markers):
        return "company"
    return "general"


def build_relevance_reason(request: ExploreRequest, hit: SearchHit) -> str:
    tokens = [request.industry, request.job_family, normalize_job_role(request.job_role)]
    matched = [token for token in tokens if token and token.lower() in f"{hit.title} {hit.snippet}".lower()]
    if matched:
        return f"입력한 목표와 직접 맞닿는 키워드가 포함됨: {', '.join(matched)}"
    if normalize_job_role(request.job_role):
        return "입력한 산업·직군·직무와 연결되는 공고/기업 문맥을 보강할 수 있음"
    return "입력한 목표와 연결되는 공고/기업 문맥을 보강할 수 있음"


def summarize_text(*parts: str) -> str:
    for part in parts:
        if part:
            compact = " ".join(part.split())
            if compact:
                return compact[:220]
    return "요약할 만한 본문을 찾지 못했습니다."


async def collect_candidates(
    settings: Settings,
    request: ExploreRequest,
    queries: list[str],
) -> dict[str, list[CandidateCard] | list[SourceCard] | list[str]]:
    client = build_search_client(settings)
    seen_urls: set[str] = set()
    source_cards: list[SourceCard] = []
    company_candidates: list[CandidateCard] = []
    posting_candidates: list[CandidateCard] = []
    notes: list[str] = []

    for query in queries:
        hits = client.search(query, max_results=4)
        for hit in hits:
            if not hit.url or hit.url in seen_urls:
                continue
            seen_urls.add(hit.url)

            fetch_result = await fetch_page_content(settings, hit.url, raw_content=hit.content)
            page_text = fetch_result.text
            fetch_note = note_for_fetch_result(fetch_result)
            if fetch_note:
                notes.append(fetch_note)

            source_type = classify_source(hit)
            summary = summarize_text(hit.snippet, page_text or "")
            reason = build_relevance_reason(request, hit)

            source_cards.append(
                SourceCard(
                    title=hit.title or hit.url,
                    url=hit.url,
                    source_type=source_type,
                    claim=summary,
                    confidence=confidence_for_fetch_result(fetch_result),
                )
            )

            card = CandidateCard(
                name=hit.title or hit.url,
                kind="posting" if source_type == "posting" else "company",
                summary=summary,
                why_relevant=reason,
                source_url=hit.url,
            )
            if card.kind == "posting":
                posting_candidates.append(card)
            else:
                company_candidates.append(card)

            if len(company_candidates) >= 4 and len(posting_candidates) >= 4:
                break
        if len(company_candidates) >= 4 and len(posting_candidates) >= 4:
            break

    if not company_candidates and not posting_candidates:
        notes.append("후보를 충분히 찾지 못했습니다. 입력 조건을 조금 더 넓혀 보세요.")

    return {
        "company_candidates": company_candidates[:4],
        "posting_candidates": posting_candidates[:4],
        "source_cards": source_cards[:8],
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
