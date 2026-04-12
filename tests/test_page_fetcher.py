from __future__ import annotations

import pytest

from backend.app.clients.fetch_extractors import extract_job_posting_text, extract_visible_text_from_html
from backend.app.clients.fetch_models import FetchResult, confidence_for_fetch_result, note_for_fetch_result
from backend.app.clients.page_fetcher import fetch_page_content
from backend.app.core.settings import Settings
from backend.app.schemas.api import ExploreRequest
from backend.app.services.exploration import collect_candidates

pytestmark = pytest.mark.anyio


def _test_settings(tmp_path) -> Settings:
    return Settings(
        openai_api_key="test",
        tavily_api_key="test",
        search_provider="tavily",
        llm_provider="fixture",
        data_dir=tmp_path,
    )


def test_extract_job_posting_text_prefers_json_ld() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "백엔드 엔지니어",
            "description": "<p>API와 데이터 파이프라인을 담당합니다.</p>",
            "qualifications": "Python, SQL",
            "hiringOrganization": {"name": "NexBridge"}
          }
        </script>
      </head>
      <body><div>화면에 보이는 일반 텍스트</div></body>
    </html>
    """

    text = extract_job_posting_text(html)

    assert text is not None
    assert "직무: 백엔드 엔지니어" in text
    assert "회사: NexBridge" in text
    assert "자격 요건: Python, SQL" in text


def test_extract_visible_text_ignores_script_content() -> None:
    html = """
    <html>
      <body>
        <script>console.log('hello')</script>
        <div>지원자를 위한 안내 문구입니다.</div>
      </body>
    </html>
    """

    text, metrics = extract_visible_text_from_html(html)

    assert "지원자를 위한 안내 문구입니다." in text
    assert "console.log" not in text
    assert metrics["script_count"] == 1


async def test_fetch_page_content_uses_summary_only_policy_without_network(monkeypatch, tmp_path) -> None:
    settings = _test_settings(tmp_path)

    async def _unexpected_static(*args, **kwargs):
        raise AssertionError("static fetch should not run for summary-only domains")

    async def _unexpected_browser(*args, **kwargs):
        raise AssertionError("browser fetch should not run for summary-only domains")

    monkeypatch.setattr("backend.app.clients.page_fetcher.fetch_static_content", _unexpected_static)
    monkeypatch.setattr("backend.app.clients.page_fetcher.fetch_browser_content", _unexpected_browser)

    result = await fetch_page_content(settings, "https://kr.indeed.com/viewjob?jk=123")

    assert result.status == "summary_only"
    assert result.method == "summary_only_policy"
    assert note_for_fetch_result(result) == "사이트 정책상 검색 요약만 사용한 URL: https://kr.indeed.com/viewjob?jk=123"


async def test_fetch_page_content_uses_browser_only_policy_without_static(monkeypatch, tmp_path) -> None:
    settings = _test_settings(tmp_path)

    async def _unexpected_static(*args, **kwargs):
        raise AssertionError("static fetch should not run for browser-only domains")

    async def _browser_result(*args, **kwargs):
        return FetchResult(
            url="https://jobs.myworkdayjobs.com/en-US/Example/job/1",
            final_url="https://jobs.myworkdayjobs.com/en-US/Example/job/1",
            method="browser_render",
            status="success",
            text="브라우저로 렌더링한 채용 공고 본문",
            metadata={},
        )

    monkeypatch.setattr("backend.app.clients.page_fetcher.fetch_static_content", _unexpected_static)
    monkeypatch.setattr("backend.app.clients.page_fetcher.fetch_browser_content", _browser_result)

    result = await fetch_page_content(settings, "https://jobs.myworkdayjobs.com/en-US/Example/job/1")

    assert result.status == "success"
    assert result.method == "browser_render"


async def test_fetch_page_content_returns_cache_hit_on_repeat(monkeypatch, tmp_path) -> None:
    settings = _test_settings(tmp_path)
    calls = {"count": 0}

    async def _static_result(*args, **kwargs):
        calls["count"] += 1
        return FetchResult(
            url="https://example.com/jobs/1",
            final_url="https://example.com/jobs/1",
            method="static_html",
            status="success",
            text="정적 HTML에서 추출한 공고 본문",
            metadata={},
        )

    monkeypatch.setattr("backend.app.clients.page_fetcher.fetch_static_content", _static_result)

    first = await fetch_page_content(settings, "https://example.com/jobs/1")
    second = await fetch_page_content(settings, "https://example.com/jobs/1")

    assert calls["count"] == 1
    assert first.method == "static_html"
    assert second.method == "cache_hit"
    assert second.used_cache is True
    assert second.text == first.text


async def test_fetch_page_content_prefers_raw_content_over_additional_fetch(monkeypatch, tmp_path) -> None:
    settings = _test_settings(tmp_path)

    async def _unexpected_static(*args, **kwargs):
        raise AssertionError("raw_content should bypass static fetch")

    async def _unexpected_browser(*args, **kwargs):
        raise AssertionError("raw_content should bypass browser fetch")

    monkeypatch.setattr("backend.app.clients.page_fetcher.fetch_static_content", _unexpected_static)
    monkeypatch.setattr("backend.app.clients.page_fetcher.fetch_browser_content", _unexpected_browser)

    result = await fetch_page_content(settings, "https://example.com/jobs/1", raw_content="  API 설계 와 데이터 처리 경험  ")

    assert result.status == "success"
    assert result.method == "raw_content"
    assert result.text == "API 설계 와 데이터 처리 경험"


async def test_collect_candidates_uses_fetch_result_notes_and_confidence(monkeypatch, tmp_path) -> None:
    settings = _test_settings(tmp_path)

    class FakeSearchClient:
        def search(self, query: str, max_results: int = 5):
            return [
                type(
                    "Hit",
                    (),
                    {
                        "title": "예시 공고",
                        "url": "https://kr.indeed.com/viewjob?jk=abc",
                        "snippet": "검색 요약입니다.",
                        "content": None,
                    },
                )()
            ]

    async def _fetch_result(*args, **kwargs):
        return FetchResult(
            url="https://kr.indeed.com/viewjob?jk=abc",
            final_url="https://kr.indeed.com/viewjob?jk=abc",
            method="summary_only_policy",
            status="summary_only",
            text="",
            metadata={},
            error_reason="summary_only_policy",
        )

    monkeypatch.setattr("backend.app.services.exploration.build_search_client", lambda settings: FakeSearchClient())
    monkeypatch.setattr("backend.app.services.exploration.fetch_page_content", _fetch_result)

    collected = await collect_candidates(
        settings,
        ExploreRequest(
            industry="IT/소프트웨어",
            job_family="개발",
            job_role="백엔드",
        ),
        ["IT/소프트웨어 개발 백엔드 채용"],
    )

    assert collected["notes"] == ["사이트 정책상 검색 요약만 사용한 URL: https://kr.indeed.com/viewjob?jk=abc"]
    source_card = collected["source_cards"][0]
    assert source_card.confidence == confidence_for_fetch_result(await _fetch_result())
    assert source_card.claim == "검색 요약입니다."
