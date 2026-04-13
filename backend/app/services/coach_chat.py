from __future__ import annotations

import re
from typing import Any

from backend.app.clients.llm_client import build_llm_client
from backend.app.core.settings import Settings
from backend.app.schemas.api import CoachChatMessage, CoachChatRequest, CoachChatResponse
from backend.app.storage.session_store import append_chat_message, load_chat_messages, load_run_context


def _compact(value: str | None) -> str:
    return " ".join(str(value or "").split())


def _coerce_answer_text(value: Any) -> str:
    raw_text = str(value or "").strip()
    if not raw_text:
        return ""

    paragraphs = []
    for paragraph in raw_text.split("\n\n"):
        compact = " ".join(paragraph.split())
        if compact:
            paragraphs.append(compact)
    paragraphs = paragraphs[:2]
    normalized = "\n\n".join(paragraphs).strip()
    if not normalized:
        return ""

    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", normalized) if sentence.strip()]
    if len(sentences) > 5:
        normalized = " ".join(sentences[:5]).strip()
    return normalized


def _coerce_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []

    items: list[str] = []
    seen: set[str] = set()
    for raw_item in value:
        text = " ".join(str(raw_item).split())
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _selected_target_name(run_context: dict[str, Any], request: CoachChatRequest) -> str:
    if request.selected_target:
        return request.selected_target.name
    selected_target = run_context.get("selected_target")
    if isinstance(selected_target, dict) and selected_target.get("name"):
        return str(selected_target["name"])
    return "선택한 지원 공고"


def _selected_target_summary(run_context: dict[str, Any], request: CoachChatRequest) -> str:
    if request.selected_target:
        return request.selected_target.summary
    selected_target = run_context.get("selected_target")
    if isinstance(selected_target, dict) and selected_target.get("summary"):
        return str(selected_target["summary"])
    return "요약 정보가 아직 충분하지 않습니다."


def _recent_history_text(messages: list[dict[str, Any]], limit: int = 6) -> str:
    if not messages:
        return "대화 기록 없음"

    lines: list[str] = []
    for message in messages[-limit:]:
        role = "사용자" if message.get("role") == "user" else "코치"
        lines.append(f"- {role}: {_compact(message.get('content'))}")
    return "\n".join(lines)


def _build_context_summary(run_context: dict[str, Any], request: CoachChatRequest) -> str:
    explore = run_context.get("explore", {})
    prepare_summary = run_context.get("prepare_summary", {})
    prep_artifacts = run_context.get("prep_artifacts", {})

    top_candidates = [
        candidate.get("name", "")
        for candidate in explore.get("posting_candidates", [])[:3]
        if isinstance(candidate, dict)
    ]
    preparation_points = _coerce_list(prepare_summary.get("preparation_points", []), limit=4)
    skill_gaps = _coerce_list(prepare_summary.get("skill_gaps", []), limit=3)
    action_items = _coerce_list(prep_artifacts.get("action_items", []), limit=4)
    interview_questions = _coerce_list(prep_artifacts.get("interview_questions", []), limit=3)

    return (
        f"선택 공고: {_selected_target_name(run_context, request)}\n"
        f"선택 공고 요약: {_selected_target_summary(run_context, request)}\n"
        f"탐색 쿼리: {', '.join(explore.get('queries', [])) or '없음'}\n"
        f"상위 후보: {', '.join(top_candidates) or '없음'}\n"
        f"준비 요약: {_compact(prepare_summary.get('preparation_summary'))}\n"
        f"준비 포인트: {' | '.join(preparation_points) or '없음'}\n"
        f"보완 포인트: {' | '.join(skill_gaps) or '없음'}\n"
        f"실행 항목: {' | '.join(action_items) or '없음'}\n"
        f"예상 질문: {' | '.join(interview_questions) or '없음'}\n"
        f"사용자 배경: {_compact(request.user_background) or '없음'}\n"
        f"사용자 메모: {_compact(request.notes) or '없음'}"
    )


def _fallback_reply(run_context: dict[str, Any], request: CoachChatRequest) -> tuple[str, list[str], list[str], list[str]]:
    prepare_summary = run_context.get("prepare_summary", {})
    prep_artifacts = run_context.get("prep_artifacts", {})
    warnings: list[str] = []

    target_name = _selected_target_name(run_context, request)
    summary_text = _compact(prepare_summary.get("preparation_summary"))
    if not summary_text:
        summary_text = f"{target_name} 기준의 준비 요약이 아직 충분하지 않으니, 먼저 요약서와 실행 항목을 생성한 뒤 질문하면 더 정확한 안내를 드릴 수 있습니다."
        warnings.append("저장된 준비 요약이 부족해 기본 안내를 중심으로 답변했습니다.")

    action_items = _coerce_list(prep_artifacts.get("action_items", []), limit=3)
    if not action_items:
        action_items = _coerce_list(prepare_summary.get("preparation_points", []), limit=3)

    skill_gaps = _coerce_list(prepare_summary.get("skill_gaps", []), limit=2)
    answer = (
        f"핵심은 {target_name}와 내 경험이 왜 맞는지 한 문장 결론부터 분명하게 잡는 것입니다.\n\n"
        f"지금은 {summary_text}를 바탕으로, 질문에 답할 때 관련 경험 1개와 결과 1개만 붙여 짧게 설명해 보세요. "
        "마지막에는 해당 업무에 어떻게 바로 기여할지 한 문장으로 닫으면 훨씬 간결하고 설득력 있게 들립니다."
    )

    preparation_tips = action_items or [
        "선택 공고의 핵심 키워드와 연결되는 경험 2개를 먼저 정리하세요.",
        "결과는 가능한 한 수치나 전후 변화로 바꿔서 설명하세요.",
        "지원 동기와 직무 적합성은 한 문장 결론으로 먼저 말하는 연습을 해두세요.",
    ]
    suggested_questions = skill_gaps or [
        "지원 동기를 더 설득력 있게 말하려면 어떻게 정리하면 좋을까요?",
        "이 공고 기준으로 예상 꼬리 질문은 무엇이 나올까요?",
    ]
    return answer, preparation_tips[:3], suggested_questions[:3], warnings


def build_coach_chat_response(settings: Settings, request: CoachChatRequest) -> CoachChatResponse:
    run_context = load_run_context(settings.data_dir, request.run_id)
    append_chat_message(settings.data_dir, request.run_id, "user", request.question)

    llm_client = build_llm_client(settings)
    answer: str
    preparation_tips: list[str]
    suggested_questions: list[str]
    warnings: list[str]

    if llm_client is None:
        answer, preparation_tips, suggested_questions, warnings = _fallback_reply(run_context, request)
    else:
        fallback_answer, fallback_tips, fallback_questions, warnings = _fallback_reply(run_context, request)
        system_prompt = (
            "You are a Korean job-prep coach agent. "
            "Use the stored run context and prior conversation to answer the user's question concretely. "
            "Return valid JSON only."
        )
        user_prompt = (
            "Create JSON with keys answer, preparation_tips, suggested_questions.\n"
            "answer rules:\n"
            "- Korean only\n"
            "- answer the user's latest question directly\n"
            "- 1 to 2 short paragraphs only\n"
            "- 3 to 5 sentences total\n"
            "- start with a one-sentence conclusion\n"
            "- explicitly explain the single most important next step\n"
            "- keep it concise and do not repeat the full stored context\n"
            "preparation_tips rules:\n"
            "- 2 to 3 Korean strings\n"
            "- immediately usable preparation steps\n"
            "suggested_questions rules:\n"
            "- 2 to 3 Korean strings\n"
            "- suggest useful follow-up questions the user could ask next\n\n"
            f"Current context:\n{_build_context_summary(run_context, request)}\n\n"
            f"Recent conversation:\n{_recent_history_text(run_context.get('messages', []))}\n\n"
            f"Latest user question: {request.question}"
        )

        try:
            payload = llm_client.generate_json(system_prompt, user_prompt)
            answer = _coerce_answer_text(payload.get("answer")) or fallback_answer
            preparation_tips = _coerce_list(payload.get("preparation_tips", []), limit=3) or fallback_tips
            suggested_questions = _coerce_list(payload.get("suggested_questions", []), limit=3) or fallback_questions
        except Exception:
            answer, preparation_tips, suggested_questions = fallback_answer, fallback_tips, fallback_questions
            warnings.append("대화형 코치 응답 생성 중 오류가 있어 저장된 준비 자료를 기준으로 답변했습니다.")

    append_chat_message(
        settings.data_dir,
        request.run_id,
        "assistant",
        answer,
        meta={
            "preparation_tips": preparation_tips,
            "suggested_questions": suggested_questions,
        },
    )
    messages = [CoachChatMessage.model_validate(message) for message in load_chat_messages(settings.data_dir, request.run_id)]
    return CoachChatResponse(
        run_id=request.run_id,
        answer=answer,
        preparation_tips=preparation_tips,
        suggested_questions=suggested_questions,
        messages=messages,
        warnings=warnings,
    )
