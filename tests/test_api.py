from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.core.settings import get_settings
from backend.app.main import app
from backend.app.services import preparation as preparation_service


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
    assert payload["self_intro_draft"]
    assert len(payload["interview_questions"]) == len(payload["answer_frames"])
    assert all("핵심 메시지" in frame or "직무 연결" in frame for frame in payload["answer_frames"])
    assert all("{" not in frame and "}" not in frame for frame in payload["answer_frames"])
    assert all("'핵심 메시지'" not in frame for frame in payload["answer_frames"])
    assert "예시 백엔드 개발자 공고" in payload["self_intro_draft"]
    assert len(payload["self_intro_draft"]) >= 240
    assert "document_guidance" not in payload
    assert "prep_missions" not in payload
    assert "schedule_items" not in payload


def test_prep_artifacts_normalizes_structured_answer_frames_from_llm(monkeypatch) -> None:
    class _FakeClient:
        def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
            return {
                "action_items": [
                    "공고 핵심 키워드와 연결되는 경험 3개를 정리합니다.",
                    "프로젝트 성과를 수치 중심 문장으로 다시 씁니다.",
                    "지원 동기를 한 문장 결론으로 먼저 고정합니다.",
                    "대표 사례 2개를 STAR 흐름으로 재정리합니다.",
                    "직무 적합성을 보여 줄 기술 포인트를 추립니다.",
                ],
                "interview_questions": [
                    "왜 이 직무에 지원했나요?",
                    "가장 강한 역량은 무엇인가요?",
                    "부족한 역량은 어떻게 보완하고 있나요?",
                    "입사 후 어떻게 기여할 수 있나요?",
                ],
                "answer_frames": [
                    {"핵심 메시지": "지원 이유를 먼저 말합니다.", "직무 연결": "빠르게 기여할 포인트를 덧붙입니다."},
                    "{'핵심 메시지': '가장 강한 역량을 먼저 제시합니다.', '근거 경험': '프로젝트 사례를 붙입니다.'}",
                    {"key_message": "부족한 부분을 인정합니다.", "plan": "보완 계획을 구체적으로 설명합니다."},
                    "핵심 메시지 -> 초반 기여 포인트를 먼저 말합니다. | 직무 연결 -> 실행 계획으로 마무리합니다.",
                ],
                "self_intro_draft": (
                    "저는 데이터와 백엔드 경험을 바탕으로 문제를 구조화하고 실제 서비스 개선으로 연결해 온 지원자입니다. "
                    "이전 프로젝트에서는 요구사항을 다시 정리하고 필요한 API와 데이터 흐름을 설계해 운영 효율과 사용자 경험을 함께 개선했습니다. "
                    "이 과정에서 단순 구현을 넘어 우선순위를 조율하고 결과를 수치와 변화로 설명하는 습관을 길렀습니다. "
                    "이러한 강점은 이번 직무가 요구하는 실행력과 협업 역량에 잘 맞는다고 생각하며, 입사 후에도 빠르게 맥락을 익혀 안정적인 성과로 기여하겠습니다."
                ),
            }

    monkeypatch.setattr(preparation_service, "build_llm_client", lambda settings: _FakeClient())
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
    assert all("{" not in frame and "}" not in frame for frame in payload["answer_frames"])
    assert all("'" not in frame for frame in payload["answer_frames"])
    assert payload["answer_frames"][0].startswith("핵심 메시지:")
    assert "직무 연결:" in payload["answer_frames"][0]
    assert "보완 계획:" in payload["answer_frames"][2]


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
