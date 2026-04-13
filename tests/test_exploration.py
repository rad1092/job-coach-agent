from pathlib import Path

from backend.app.clients.search_client import FixtureSearchClient
from backend.app.core.taxonomy import is_direct_posting_url, job_board_domains_for_retry
from backend.app.schemas.api import ExploreRequest
from backend.app.services.exploration import build_queries


def test_build_queries_reflect_selected_filters() -> None:
    request = ExploreRequest(
        industry="IT·플랫폼",
        job_family="개발",
        job_role="백엔드 개발자",
        experience_level="주니어(1~3년)",
        preferences="원격·하이브리드, 데이터 중심 문화",
    )

    queries = build_queries(request)

    assert queries
    assert any("백엔드 개발자" in query for query in queries)
    assert any("주니어" in query for query in queries)
    assert any("원격·하이브리드" in query or "데이터 중심 문화" in query for query in queries)


def test_fixture_search_respects_domain_filters() -> None:
    client = FixtureSearchClient(Path("data"))

    hits = client.search(
        "백엔드 개발자 채용",
        max_results=10,
        include_domains=job_board_domains_for_retry(0),
        exclude_domains=["jobplanet.co.kr"],
    )

    assert hits
    assert all(any(domain in hit.url for domain in job_board_domains_for_retry(0)) for hit in hits)
    assert all("jobplanet.co.kr" not in hit.url for hit in hits)


def test_direct_posting_url_filters_out_search_pages() -> None:
    assert is_direct_posting_url("https://www.jobkorea.co.kr/Recruit/GI_Read/46990001")
    assert is_direct_posting_url("https://www.wanted.co.kr/wd/245678")
    assert not is_direct_posting_url("https://www.jobkorea.co.kr/Search/?stext=backend")
