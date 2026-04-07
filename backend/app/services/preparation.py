from __future__ import annotations

from typing import Any

from backend.app.clients.llm_client import build_llm_client
from backend.app.core.settings import Settings
from backend.app.schemas.api import PrepArtifactsRequest, PrepArtifactsResponse, PrepareSummaryRequest, PrepareSummaryResponse, SelectedCandidate


def _select_target_name(target: SelectedCandidate | None) -> str:
    if target:
        return target.name
    return "선택한 지원 대상"


def _select_target_summary(target: SelectedCandidate | None) -> str:
    if target:
        return target.summary
    return "요약 정보가 아직 없습니다."


def _fallback_prepare_summary(request: PrepareSummaryRequest) -> PrepareSummaryResponse:
    target_name = _select_target_name(request.selected_target)
    target_summary = _select_target_summary(request.selected_target)
    background = request.user_background or "사용자 배경 정보가 아직 충분하지 않습니다."
    notes = request.notes or "추가 메모 없음"
    warnings: list[str] = []

    if request.selected_target is None:
        warnings.append("지원 준비 요약서를 만들려면 지원 대상 후보를 먼저 선택해 주세요.")

    preparation_summary = (
        f"{target_name} 준비 요약\n"
        f"- 핵심 맥락: {target_summary}\n"
        f"- 사용자 배경: {background}\n"
        f"- 메모: {notes}"
    )

    return PrepareSummaryResponse(
        run_id=request.run_id or "",
        preparation_summary=preparation_summary,
        preparation_points=[
            "공고와 기업 설명에서 반복되는 직무 키워드를 먼저 정리합니다.",
            "사용자 배경에서 직접 연결 가능한 경험 2~3개를 우선 추립니다.",
            "기업 맥락과 직무 요구사항이 만나는 지점을 문서와 면접에서 반복 사용합니다.",
        ],
        skill_gaps=[
            "직무 요구사항과 연결되는 경험이 부족하면 프로젝트 또는 과제 경험을 보완 근거로 정리합니다.",
            "지원 동기와 직무 이해가 약하면 기업 정보와 공고 문장을 다시 묶어 서술 포인트를 만듭니다.",
        ],
        warnings=warnings,
    )


def build_prepare_summary(settings: Settings, request: PrepareSummaryRequest) -> PrepareSummaryResponse:
    llm_client = build_llm_client(settings)
    if llm_client is None:
        return _fallback_prepare_summary(request)

    fallback = _fallback_prepare_summary(request)
    target_name = _select_target_name(request.selected_target)
    system_prompt = (
        "You are helping a Korean job coach product create a concise preparation summary. "
        "Return valid JSON only."
    )
    user_prompt = (
        "Create JSON with keys preparation_summary, preparation_points, skill_gaps. "
        "preparation_summary must be a short Korean paragraph. The other values must be arrays of short Korean strings.\n"
        f"Target: {target_name}\n"
        f"Target summary: {_select_target_summary(request.selected_target)}\n"
        f"User background: {request.user_background or 'N/A'}\n"
        f"Notes: {request.notes or 'N/A'}"
    )

    try:
        payload: dict[str, Any] = llm_client.generate_json(system_prompt, user_prompt)
        return PrepareSummaryResponse(
            run_id=request.run_id or "",
            preparation_summary=str(payload.get("preparation_summary") or fallback.preparation_summary),
            preparation_points=[str(item) for item in payload.get("preparation_points", [])][:5]
            or fallback.preparation_points,
            skill_gaps=[str(item) for item in payload.get("skill_gaps", [])][:5] or fallback.skill_gaps,
            warnings=fallback.warnings,
        )
    except Exception:
        return fallback


def _fallback_artifacts(request: PrepArtifactsRequest, warnings: list[str] | None = None) -> PrepArtifactsResponse:
    target_name = _select_target_name(request.selected_target)
    return PrepArtifactsResponse(
        run_id=request.run_id or "",
        action_items=[
            f"{target_name}와 직무가 연결되는 경험을 첫 단락에서 분명히 드러냅니다.",
            "공고 핵심 요구사항 2~3개를 뽑아 내 경험과 연결되는 근거 문장으로 다시 씁니다.",
            "핵심 경험 3개를 bullet로 정리하고, 각 경험의 결과를 숫자나 변화 중심으로 덧붙입니다.",
            "예상 질문 3개에 대해 1분 답변 초안을 만들고, 부족한 역량 보완 계획을 한 문장으로 정리합니다.",
        ],
        interview_questions=[
            "이 직무를 선택한 이유를 구체적인 경험과 함께 설명해 주세요.",
            "이 공고의 핵심 요구사항 중 본인이 가장 잘 맞는 부분은 무엇인가요?",
            "부족하다고 느끼는 역량을 어떻게 보완하려고 하나요?",
        ],
        answer_frames=[
            "상황 -> 역할 -> 행동 -> 결과 -> 이 직무와의 연결",
            "공고 요구사항 -> 내 경험 근거 -> 성과 -> 다음 확장 가능성",
        ],
        warnings=warnings or [],
    )


def build_prep_artifacts(settings: Settings, request: PrepArtifactsRequest) -> PrepArtifactsResponse:
    llm_client = build_llm_client(settings)
    if llm_client is None:
        return _fallback_artifacts(request)

    target_name = _select_target_name(request.selected_target)
    system_prompt = (
        "You are helping a Korean job coach product create concise preparation artifacts. "
        "Return valid JSON only."
    )
    user_prompt = (
        "Create JSON with keys action_items, interview_questions, answer_frames. "
        "Each value must be an array of short Korean strings. "
        "action_items must contain concrete next actions that combine document revision, preparation tasks, and timing-related checks without using a separate schedule section.\n"
        f"Target: {target_name}\n"
        f"Preparation summary: {request.preparation_summary}\n"
        f"User background: {request.user_background or 'N/A'}\n"
        f"Notes: {request.notes or 'N/A'}"
    )

    try:
        payload: dict[str, Any] = llm_client.generate_json(system_prompt, user_prompt)
        return PrepArtifactsResponse(
            run_id=request.run_id or "",
            action_items=[str(item) for item in payload.get("action_items", [])][:6],
            interview_questions=[str(item) for item in payload.get("interview_questions", [])][:5],
            answer_frames=[str(item) for item in payload.get("answer_frames", [])][:5],
            warnings=[],
        )
    except Exception:
        return _fallback_artifacts(request)


def critique_prep_artifacts(
    settings: Settings,
    request: PrepArtifactsRequest,
    response: PrepArtifactsResponse,
) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    target_name = _select_target_name(request.selected_target)

    if not response.action_items or not response.interview_questions or not response.answer_frames:
        warnings.append("준비 자료가 비어 있어 한 번 더 생성하는 편이 안전합니다.")
        return True, warnings

    if not any(target_name in item for item in response.action_items):
        warnings.append("실행 항목에 선택한 지원 대상이 충분히 드러나지 않습니다.")

    llm_client = build_llm_client(settings)
    if llm_client is None:
        return False, warnings

    system_prompt = (
        "You are reviewing preparation artifacts for a Korean job coach product. "
        "Return valid JSON only."
    )
    user_prompt = (
        "Return JSON with keys needs_revision and warnings. "
        "needs_revision must be true only when the artifacts are clearly generic, inconsistent, or unusable. "
        "warnings must be a short array of Korean strings.\n"
        f"Target: {target_name}\n"
        f"Preparation summary: {request.preparation_summary}\n"
        f"Artifacts: action_items={response.action_items}; "
        f"interview_questions={response.interview_questions}; "
        f"answer_frames={response.answer_frames}"
    )

    try:
        payload: dict[str, Any] = llm_client.generate_json(system_prompt, user_prompt)
        llm_warnings = [str(item) for item in payload.get("warnings", [])][:4]
        warnings.extend(llm_warnings)
        return bool(payload.get("needs_revision")), warnings
    except Exception:
        return False, warnings
