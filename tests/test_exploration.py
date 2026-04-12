from __future__ import annotations

from backend.app.clients.search_client import SearchHit
from backend.app.schemas.api import ExploreRequest
from backend.app.services.exploration import build_queries, build_relevance_reason


def test_build_queries_adds_role_specific_queries_when_role_exists() -> None:
    request = ExploreRequest(
        industry="IT/소프트웨어",
        job_family="개발",
        job_role="백엔드",
        experience_level="신입",
        preferences="근무형태: 원격",
    )

    queries = build_queries(request)

    assert "IT/소프트웨어 개발 백엔드 채용" in queries
    assert "백엔드 직무 역량 IT/소프트웨어" in queries
    assert sum("신입" in query for query in queries) == 1
    assert sum("근무형태: 원격" in query for query in queries) == 1


def test_build_queries_omits_placeholder_when_role_is_missing() -> None:
    request = ExploreRequest(
        industry="IT/소프트웨어",
        job_family="개발",
        job_role=None,
        experience_level="경력무관",
        preferences="기업규모: 성장기업",
    )

    queries = build_queries(request)

    assert "IT/소프트웨어 개발 채용" in queries
    assert "IT/소프트웨어 개발 직무 역량" in queries
    assert all("미정" not in query for query in queries)
    assert sum("경력무관" in query for query in queries) == 1
    assert sum("기업규모: 성장기업" in query for query in queries) == 1


def test_build_relevance_reason_falls_back_to_industry_and_family_without_role() -> None:
    request = ExploreRequest(
        industry="IT/소프트웨어",
        job_family="개발",
        job_role=None,
    )
    hit = SearchHit(
        title="플랫폼 서비스 백엔드 채용",
        url="https://example.com/jobs/1",
        snippet="개발 조직에서 API를 다룹니다.",
    )

    reason = build_relevance_reason(request, hit)

    assert "산업·직군" in reason or "목표" in reason
