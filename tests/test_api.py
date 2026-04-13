from __future__ import annotations

import uuid

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


def test_explore_returns_up_to_twenty_seven_direct_posting_candidates(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/explore",
        json={
            "industry": "IT·플랫폼",
            "job_family": "개발",
            "job_role": "백엔드 개발자",
            "experience_level": "주니어(1~3년)",
            "preferences": "원격·하이브리드, 데이터 중심 문화",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["queries"]
    assert payload["source_cards"]
    assert len(payload["posting_candidates"]) == 27
    assert all(
        any(
            domain in candidate["source_url"]
            for domain in [
                "jobkorea.co.kr",
                "saramin.co.kr",
                "wanted.co.kr",
                "work24.go.kr",
                "jasoseol.com",
                "jumpit.saramin.co.kr",
                "catch.co.kr",
            ]
        )
        for candidate in payload["posting_candidates"]
    )
    assert all("/Search/" not in candidate["source_url"] for candidate in payload["posting_candidates"])
    assert all("jobplanet.co.kr" not in candidate["source_url"] for candidate in payload["posting_candidates"])
    assert all(
        payload["posting_candidates"][index]["confidence"] >= payload["posting_candidates"][index + 1]["confidence"]
        for index in range(len(payload["posting_candidates"]) - 1)
    )


def test_prepare_summary_returns_warning_when_selection_missing(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/prepare-summary",
        json={
            "user_background": "백엔드 프로젝트 경험이 있습니다.",
            "notes": "데이터 처리 경험을 강조하고 싶습니다.",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["preparation_summary"]
    assert payload["warnings"]
    assert "지원 대상 후보" in payload["warnings"][0]
    assert "checklist" not in payload


def test_prepare_summary_returns_detailed_content(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()

    response = client.post(
        "/prepare-summary",
        json={
            "run_id": "test-run",
            "selected_target": {
                "name": "예시 백엔드 개발자 공고",
                "kind": "posting",
                "summary": "Python API 개발과 데이터 처리 경험을 요구합니다.",
                "source_url": "https://example.com/jobs/1",
            },
            "user_background": "FastAPI 기반 프로젝트를 수행했고, 운영 자동화와 데이터 파이프라인 개선 경험이 있습니다.",
            "notes": "지원 동기와 정량 성과를 더 선명하게 만들고 싶습니다.",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert len(payload["preparation_summary"]) >= 180
    assert payload["preparation_summary"].count("\n") >= 2
    assert len(payload["preparation_points"]) >= 4
    assert len(payload["skill_gaps"]) >= 3


def test_prep_artifacts_returns_question_aligned_frames(monkeypatch) -> None:
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
    assert len(payload["interview_questions"]) == len(payload["answer_frames"])
    assert all("핵심 메시지" in frame or "직무 연결" in frame for frame in payload["answer_frames"])
    assert "document_guidance" not in payload
    assert "prep_missions" not in payload
    assert "schedule_items" not in payload


def test_coach_chat_stores_and_returns_history(monkeypatch) -> None:
    _configure_fixture_mode(monkeypatch)
    client = _build_client()
    run_id = f"chat-run-{uuid.uuid4().hex}"

    response = client.post(
        "/coach-chat",
        json={
            "run_id": run_id,
            "question": "이 공고 기준으로 지원 동기를 어떻게 준비하면 좋을까요?",
            "selected_target": {
                "name": "예시 백엔드 개발자 공고",
                "kind": "posting",
                "summary": "Python API와 데이터 처리 경험을 요구합니다.",
                "source_url": "https://example.com/jobs/1",
            },
            "user_background": "FastAPI와 데이터 처리 프로젝트 경험이 있습니다.",
            "notes": "지원 동기를 더 설득력 있게 만들고 싶습니다.",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["answer"]
    assert payload["preparation_tips"]
    assert payload["messages"]
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-1]["role"] == "assistant"

    history_response = client.get(f"/coach-chat/history/{run_id}")
    history_payload = history_response.json()
    assert history_response.status_code == 200
    assert history_payload["messages"]
    assert history_payload["messages"][-2]["role"] == "user"
    assert history_payload["messages"][-1]["role"] == "assistant"
