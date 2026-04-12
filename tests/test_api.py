from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.settings import get_settings
from backend.app.main import app


def _build_client() -> TestClient:
    return TestClient(app)


def _configure_fixture_mode(monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "fixture")
    monkeypatch.setenv("LLM_PROVIDER", "fixture")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health() -> None:
    client = _build_client()
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_explore_returns_candidates(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/explore",
        json={
            "industry": "IT/소프트웨어",
            "job_family": "개발",
            "job_role": "백엔드",
            "experience_level": "신입",
            "preferences": "근무형태: 원격",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["queries"]
    assert payload["source_cards"]
    assert payload["company_candidates"] or payload["posting_candidates"]


def test_explore_accepts_null_job_role(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/explore",
        json={
            "industry": "IT/소프트웨어",
            "job_family": "개발",
            "job_role": None,
            "experience_level": "경력무관",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["queries"]
    assert all("미정" not in query for query in payload["queries"])


def test_explore_rejects_invalid_job_family(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/explore",
        json={
            "industry": "IT/소프트웨어",
            "job_family": "콘텐츠",
            "job_role": "백엔드",
        },
    )

    assert response.status_code == 422


def test_explore_rejects_missing_industry(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/explore",
        json={
            "job_family": "개발",
            "job_role": "백엔드",
        },
    )

    assert response.status_code == 422


def test_prepare_summary_returns_warning_when_selection_missing(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/prepare-summary",
        json={
            "user_background": "웹 백엔드 프로젝트 경험이 있습니다.",
            "notes": "데이터 처리 경험을 강조하고 싶습니다.",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["preparation_summary"]
    assert payload["warnings"]
    assert "지원 대상 후보" in payload["warnings"][0]
    assert "checklist" not in payload


def test_prep_artifacts_returns_fallback_artifacts(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/prep-artifacts",
        json={
            "selected_target": {
                "name": "예시 백엔드 개발자 공고",
                "kind": "posting",
                "summary": "Python API와 데이터 처리 경험을 요구합니다.",
                "source_url": "https://example.com/jobs/1",
            },
            "preparation_summary": "예시 백엔드 개발자 공고 준비 요약",
            "user_background": "FastAPI와 데이터 처리 프로젝트 경험이 있습니다.",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["action_items"]
    assert payload["interview_questions"]
    assert payload["answer_frames"]
    assert "document_guidance" not in payload
    assert "prep_missions" not in payload
    assert "schedule_items" not in payload
