from __future__ import annotations

import ast
from typing import Any

from backend.app.clients.llm_client import build_llm_client
from backend.app.core.settings import Settings
from backend.app.schemas.api import (
    PrepArtifactsRequest,
    PrepArtifactsResponse,
    PrepareSummaryRequest,
    PrepareSummaryResponse,
    SelectedCandidate,
)


def _select_target_name(target: SelectedCandidate | None) -> str:
    if target:
        return target.name
    return "선택한 지원 대상"


def _select_target_summary(target: SelectedCandidate | None) -> str:
    if target:
        return target.summary
    return "요약 정보가 아직 없습니다."


def _coerce_string_list(value: Any, *, limit: int) -> list[str]:
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


ANSWER_FRAME_LABEL_ORDER = (
    "핵심 메시지",
    "근거 경험",
    "공고 요구사항",
    "내 경험",
    "상황",
    "문제",
    "문제 정의",
    "현재 상태",
    "역할",
    "행동",
    "접근 방식",
    "보완 행동",
    "진행 상황",
    "결과",
    "성과/수치",
    "배운 점",
    "직무 연결",
    "실무 연결",
    "보완 계획",
    "재사용 포인트",
    "마무리",
)

ANSWER_FRAME_LABEL_ALIASES = {
    "key message": "핵심 메시지",
    "key_message": "핵심 메시지",
    "main message": "핵심 메시지",
    "main_message": "핵심 메시지",
    "message": "핵심 메시지",
    "evidence": "근거 경험",
    "experience": "근거 경험",
    "requirement": "공고 요구사항",
    "requirements": "공고 요구사항",
    "job requirement": "공고 요구사항",
    "job_requirements": "공고 요구사항",
    "my experience": "내 경험",
    "my_experience": "내 경험",
    "problem": "문제",
    "problem definition": "문제 정의",
    "problem_definition": "문제 정의",
    "current status": "현재 상태",
    "current_status": "현재 상태",
    "role": "역할",
    "action": "행동",
    "actions": "행동",
    "approach": "접근 방식",
    "plan": "보완 계획",
    "improvement plan": "보완 계획",
    "improvement_plan": "보완 계획",
    "result": "결과",
    "results": "결과",
    "metrics": "성과/수치",
    "metric": "성과/수치",
    "achievement": "성과/수치",
    "achievements": "성과/수치",
    "role fit": "직무 연결",
    "role_fit": "직무 연결",
    "job fit": "직무 연결",
    "job_fit": "직무 연결",
    "job connection": "직무 연결",
    "job_connection": "직무 연결",
    "closing": "마무리",
}


def _normalize_answer_frame_label(value: Any) -> str:
    label = _compact_text(str(value)).strip().strip(":")
    label = label.strip("'\"")
    alias_key = label.casefold().replace("-", " ").replace("_", " ")
    return ANSWER_FRAME_LABEL_ALIASES.get(alias_key, label)


def _answer_frame_sort_key(label: str) -> int:
    try:
        return ANSWER_FRAME_LABEL_ORDER.index(label)
    except ValueError:
        return len(ANSWER_FRAME_LABEL_ORDER)


def _coerce_answer_frame_text(raw_item: Any) -> str:
    if isinstance(raw_item, dict):
        pairs: list[tuple[str, str]] = []
        for key, value in raw_item.items():
            label = _normalize_answer_frame_label(key)
            if isinstance(value, (dict, list)):
                content = _coerce_answer_frame_text(value)
            else:
                content = _compact_text(str(value))
            if not content:
                continue
            pairs.append((label, content))
        pairs.sort(key=lambda item: _answer_frame_sort_key(item[0]))
        return " | ".join(f"{label}: {content}" for label, content in pairs)

    if isinstance(raw_item, list):
        blocks = [_coerce_answer_frame_text(item) for item in raw_item]
        return " | ".join(block for block in blocks if block)

    text = _compact_text(str(raw_item))
    if not text:
        return ""

    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return _coerce_answer_frame_text(parsed)

    cleaned = (
        text.replace("{", "")
        .replace("}", "")
        .replace("[", "")
        .replace("]", "")
        .replace('"', "")
        .replace("'", "")
    )
    return _compact_text(cleaned)


def _coerce_answer_frame_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []

    items: list[str] = []
    seen: set[str] = set()
    for raw_item in value:
        text = _coerce_answer_frame_text(raw_item)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _coerce_gap_text(raw_item: Any) -> str:
    if isinstance(raw_item, str):
        compact = _compact_text(raw_item)
        if compact[:1] in "{[":
            try:
                parsed = ast.literal_eval(compact)
            except (SyntaxError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                return _coerce_gap_text(parsed)
        raw_item = (
            compact.replace("{", "")
            .replace("}", "")
            .replace("[", "")
            .replace("]", "")
            .replace('"', "")
            .replace("'", "")
        )

    if isinstance(raw_item, dict):
        weakness = " ".join(
            str(
                raw_item.get("weakness")
                or raw_item.get("보완 포인트")
                or raw_item.get("risk")
                or ""
            ).split()
        )
        compensation = " ".join(
            str(
                raw_item.get("compensation")
                or raw_item.get("보완 방법")
                or raw_item.get("plan")
                or ""
            ).split()
        )

        if weakness and compensation:
            return f"보완 포인트: {weakness}\n보완 방법: {compensation}"
        if weakness:
            return f"보완 포인트: {weakness}"
        if compensation:
            return f"보완 방법: {compensation}"

    return " ".join(str(raw_item).split())


def _coerce_gap_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []

    items: list[str] = []
    seen: set[str] = set()
    for raw_item in value:
        text = _coerce_gap_text(raw_item)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _is_detailed_summary(text: str) -> bool:
    return len(" ".join(text.split())) >= 180 and text.count("\n") >= 2


def _compact_text(value: str | None) -> str:
    return " ".join(str(value or "").split())


def _clip_text(value: str | None, limit: int = 90) -> str:
    compact = _compact_text(value)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _is_useful_self_intro_draft(text: str) -> bool:
    return len(_compact_text(text)) >= 240


def _fallback_self_intro_draft(request: PrepArtifactsRequest) -> str:
    target_name = _select_target_name(request.selected_target)
    target_summary = _clip_text(_select_target_summary(request.selected_target), limit=110)
    background = _clip_text(request.user_background or request.preparation_summary, limit=110)
    focus = _clip_text(request.notes or request.preparation_summary, limit=110)

    if not background:
        background = "실무와 프로젝트 경험을 바탕으로 문제를 구조화하고 실행으로 연결해 온 경험"
    if not focus:
        focus = "직무 적합성과 빠른 기여 가능성을 설득력 있게 보여주는 것"

    return (
        f"저는 {background}을 바탕으로 {target_name}에 지원했습니다. "
        f"특히 {target_summary}와 맞닿는 과제에서 목표를 다시 정의하고, 필요한 기능과 데이터를 연결해 실제 결과로 이어 온 경험이 있습니다. "
        "이전 프로젝트에서는 단순히 맡은 일을 처리하는 데 그치지 않고 우선순위를 정리하고 협업 포인트를 맞추며, "
        "사용자 반응이나 운영 효율처럼 결과를 설명할 수 있는 지점까지 끝까지 챙겨 왔습니다. "
        f"그래서 이번 지원에서도 {focus}를 중심으로, 제가 이미 보여 준 실행력과 학습 속도가 해당 직무에서 빠르게 성과로 이어질 수 있다는 점을 말씀드리고 싶습니다. "
        "입사 후에는 업무 맥락을 빠르게 익히고 작은 과제라도 근거 있는 판단과 안정적인 실행으로 완성해, 팀이 신뢰할 수 있는 구성원으로 기여하겠습니다."
    )


def _question_specific_frame(question: str, target_name: str) -> str:
    lowered = question.lower()
    base = f"{target_name} 직무 맥락과 연결해 마무리합니다."

    if any(keyword in lowered for keyword in ["지원 동기", "지원동기", "선택한 이유", "왜 지원", "왜 이 직무"]):
        return (
            f"핵심 메시지: 왜 {target_name}와 이 직무를 선택했는지 한 문장으로 제시 | "
            "근거 경험: 관련 프로젝트나 실무 경험 1개를 바로 연결 | "
            "성과/수치: 결과나 개선 지표를 짧게 제시 | "
            "직무 연결: 입사 후 바로 기여할 업무를 언급 | "
            f"마무리: {base}"
        )

    if any(keyword in lowered for keyword in ["강점", "적합", "요구사항", "역량", "잘 맞", "뽑아야 하는 이유"]):
        return (
            "핵심 메시지: 질문에서 묻는 역량 중 내가 가장 강한 포인트를 먼저 제시 | "
            "공고 요구사항: 어떤 역량을 기준으로 답하는지 짚기 | "
            "내 경험: 같은 역량을 보여준 사례 1개 설명 | "
            "성과/수치: 결과, 개선폭, 재현 가능성 제시 | "
            f"직무 연결: 해당 역량이 {target_name} 업무에 어떻게 바로 쓰이는지 정리"
        )

    if any(keyword in lowered for keyword in ["부족", "보완", "약점", "아쉬운", "없는 경험"]):
        return (
            "핵심 메시지: 부족한 부분을 숨기지 않고 인정하되 보완 속도를 강조 | "
            "현재 상태: 어떤 부분이 약한지 짧게 설명 | "
            "보완 행동: 공부, 프로젝트, 협업, 실습 등 구체 행동 설명 | "
            "진행 상황: 이미 해본 것과 개선된 부분 제시 | "
            "실무 연결: 입사 전후 어떻게 빠르게 메울지 계획으로 마무리"
        )

    if any(keyword in lowered for keyword in ["협업", "갈등", "커뮤니케이션", "조율"]):
        return (
            "핵심 메시지: 협업 방식과 조율 역량을 먼저 한 문장으로 제시 | "
            "상황: 어떤 팀/이해관계자가 있었는지 설명 | "
            "문제: 갈등이나 정렬이 필요했던 포인트 제시 | "
            "행동: 내가 한 조율, 커뮤니케이션, 문서화 방식 설명 | "
            "결과: 협업 효율, 일정, 품질에 미친 영향 제시 | "
            "재사용 포인트: 비슷한 상황에서 반복 가능한 방식으로 정리"
        )

    if any(keyword in lowered for keyword in ["문제", "해결", "성과", "프로젝트", "개선", "성공", "실패"]):
        return (
            "핵심 메시지: 어떤 문제를 해결한 경험인지 먼저 요약 | "
            "상황: 맡았던 과제와 목표를 짧게 설명 | "
            "역할: 본인이 책임진 범위를 명확히 제시 | "
            "행동: 핵심 의사결정과 실행 단계를 설명 | "
            "결과: 수치나 변화 제시 | "
            "배운 점: 다음 업무에 어떻게 적용할지 연결"
        )

    if any(keyword in lowered for keyword in ["데이터", "지표", "분석", "실험", "측정"]):
        return (
            "핵심 메시지: 데이터 기반으로 의사결정한 경험을 먼저 제시 | "
            "문제 정의: 어떤 지표나 현상을 봤는지 설명 | "
            "접근 방식: 분석, 실험, 비교 방법 제시 | "
            "결과: 수치 변화와 인사이트 설명 | "
            "직무 연결: 데이터 기반으로 일하는 방식을 해당 직무와 연결"
        )

    return (
        "핵심 메시지: 질문에 대한 결론을 먼저 한 문장으로 제시 | "
        "상황: 배경과 목표 설명 | "
        "역할: 내가 맡은 책임 명확화 | "
        "행동: 핵심 실행 2~3개 설명 | "
        "결과: 수치나 변화 제시 | "
        f"직무 연결: {target_name} 역할에 어떻게 이어지는지 마무리"
    )


def _align_answer_frames(interview_questions: list[str], answer_frames: list[str], target_name: str) -> list[str]:
    aligned: list[str] = []
    for index, question in enumerate(interview_questions):
        if index < len(answer_frames):
            frame = _coerce_answer_frame_text(answer_frames[index])
            if len(frame) >= 40:
                aligned.append(frame)
                continue
        aligned.append(_question_specific_frame(question, target_name))
    return aligned


def _fallback_prepare_summary(request: PrepareSummaryRequest) -> PrepareSummaryResponse:
    target_name = _select_target_name(request.selected_target)
    target_summary = _select_target_summary(request.selected_target)
    background = request.user_background or "사용자 배경 정보가 아직 충분하지 않습니다."
    notes = request.notes or "추가 메모 없음"
    warnings: list[str] = []

    if request.selected_target is None:
        warnings.append("지원 준비 요약서를 만들려면 지원 대상 후보를 먼저 선택해 주세요.")

    preparation_summary = (
        f"{target_name} 지원 준비에서는 먼저 공고와 후보 요약에서 반복되는 역량을 한 줄 메시지로 고정하는 것이 중요합니다. "
        f"현재 확보된 지원 대상 문맥은 다음과 같습니다: {target_summary}\n\n"
        f"사용자 배경을 보면 {background} 를 중심 경험으로 삼는 것이 좋습니다. "
        "이 경험을 그대로 나열하기보다 문제를 어떻게 정의했고, 어떤 역할을 맡았고, 어떤 결과를 만들었는지까지 이어서 말할 수 있도록 재구성해야 합니다. "
        "특히 사용 기술, 협업 방식, 성과 수치가 보이면 서류와 면접 모두에서 설득력이 높아집니다.\n\n"
        f"추가 메모는 {notes} 입니다. "
        "이를 바탕으로 이번 3단계 결과에서는 강조할 강점, 보완이 필요한 역량, 그리고 예상 질문에 대한 답변 구조를 한 흐름으로 맞춰 준비하는 것이 좋습니다."
    )

    return PrepareSummaryResponse(
        run_id=request.run_id or "",
        preparation_summary=preparation_summary,
        preparation_points=[
            "공고 설명에서 반복되는 핵심 키워드 3개를 뽑고, 각 키워드마다 연결할 내 경험 1개씩을 먼저 정리합니다.",
            "사용자 배경에서 가장 강한 경험 2개를 고르고, 각각 문제 정의 -> 역할 -> 행동 -> 결과 순서로 4문장 안에 설명할 수 있게 압축합니다.",
            "직무 적합성을 말할 때는 기술 스택이나 툴 이름만 나열하지 말고, 실제로 어떤 상황에서 어떻게 사용했는지까지 붙여서 서술합니다.",
            "서류와 면접에서 같은 핵심 메시지를 반복할 수 있도록 지원 동기, 강점, 프로젝트 사례를 한 문장 중심 메시지로 묶어둡니다.",
            "성과를 말할 때는 가능하면 속도, 품질, 운영 효율, 사용자 반응 등 숫자나 변화 지표를 하나라도 포함하도록 정리합니다.",
        ],
        skill_gaps=[
            "직무 요구사항과 직접 맞닿는 경험이 약하면, 가장 유사한 프로젝트를 골라 문제 해결 방식과 재현 가능한 역량 중심으로 보완 근거를 만듭니다.",
            "지원 동기와 회사 이해가 얕아 보일 수 있으니, 왜 이 회사의 업무 맥락이 내 경험과 맞는지 구체적인 연결 문장을 준비하는 것이 필요합니다.",
            "성과 설명이 추상적으로 들릴 가능성이 있어, 결과를 수치나 전후 변화로 바꾸는 작업이 추가로 필요합니다.",
            "질문별 답변 구조를 미리 맞춰두지 않으면 경험은 있어도 전달력이 떨어질 수 있으니, 예상 질문별 핵심 메시지를 선제적으로 정리해야 합니다.",
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
        "You are a Korean job coach preparing a detailed support brief for an applicant. "
        "You write in Korean, stay concrete, and return valid JSON only."
    )
    user_prompt = (
        "Create JSON with keys preparation_summary, preparation_points, skill_gaps.\n"
        "preparation_summary rules:\n"
        "- Korean only\n"
        "- 3 paragraphs separated by blank lines\n"
        "- at least 7 sentences total\n"
        "- explicitly cover role fit, strongest evidence to emphasize, likely risks/gaps, and how to prepare next\n"
        "preparation_points rules:\n"
        "- 4 to 6 items\n"
        "- each item should be detailed enough to act on immediately\n"
        "skill_gaps rules:\n"
        "- 3 to 5 items\n"
        "- each item must explain what feels weak and how to compensate\n"
        f"Target: {target_name}\n"
        f"Target summary: {_select_target_summary(request.selected_target)}\n"
        f"User background: {request.user_background or 'N/A'}\n"
        f"Notes: {request.notes or 'N/A'}"
    )

    try:
        payload: dict[str, Any] = llm_client.generate_json(system_prompt, user_prompt)
        preparation_summary = str(payload.get("preparation_summary") or "").strip()
        preparation_points = _coerce_string_list(payload.get("preparation_points", []), limit=6)
        skill_gaps = _coerce_gap_list(payload.get("skill_gaps", []), limit=5)

        return PrepareSummaryResponse(
            run_id=request.run_id or "",
            preparation_summary=preparation_summary if _is_detailed_summary(preparation_summary) else fallback.preparation_summary,
            preparation_points=preparation_points if len(preparation_points) >= 4 else fallback.preparation_points,
            skill_gaps=skill_gaps if len(skill_gaps) >= 3 else fallback.skill_gaps,
            warnings=fallback.warnings,
        )
    except Exception:
        return fallback


def _fallback_artifacts(request: PrepArtifactsRequest, warnings: list[str] | None = None) -> PrepArtifactsResponse:
    target_name = _select_target_name(request.selected_target)
    interview_questions = [
        f"{target_name}와 이 직무에 지원한 이유를, 본인의 경험과 연결해서 설명해 주세요.",
        "공고에서 요구하는 핵심 역량 중 본인이 가장 잘 맞는 부분은 무엇이며, 어떤 사례로 증명할 수 있나요?",
        "프로젝트나 업무에서 맡은 역할이 분명하게 드러났던 경험을 하나 골라, 문제 해결 과정까지 설명해 주세요.",
        "아직 부족하다고 느끼는 역량이 있다면 무엇이고, 이를 어떻게 보완해 왔는지 말씀해 주세요.",
    ]
    answer_frames = _align_answer_frames(interview_questions, [], target_name)
    self_intro_draft = _fallback_self_intro_draft(request)

    return PrepArtifactsResponse(
        run_id=request.run_id or "",
        action_items=[
            f"{target_name} 지원용 자기소개 문단을 다시 써서, 첫 3문장 안에 직무 적합성·핵심 경험·기여 포인트가 모두 들어가게 정리합니다.",
            "공고 요구사항 3개를 기준으로 내 경험을 다시 매핑하고, 각 항목마다 근거 사례와 결과 수치를 한 줄씩 붙여 정리합니다.",
            "면접 답변용 대표 사례 2~3개를 골라 상황 -> 역할 -> 행동 -> 결과 -> 배운 점 순서로 1분 분량 초안을 만듭니다.",
            "성과가 추상적으로 들리지 않도록 프로젝트 결과를 숫자, 전후 변화, 운영 개선 효과 중 하나로 다시 표현합니다.",
            "지원 동기와 회사 이해를 묻는 질문에 대비해 회사/공고 문맥과 내 경험이 만나는 지점을 한 문장 메시지로 미리 고정합니다.",
        ],
        interview_questions=interview_questions,
        answer_frames=answer_frames,
        self_intro_draft=self_intro_draft,
        warnings=warnings or [],
    )


def build_prep_artifacts(settings: Settings, request: PrepArtifactsRequest) -> PrepArtifactsResponse:
    llm_client = build_llm_client(settings)
    if llm_client is None:
        return _fallback_artifacts(request)

    target_name = _select_target_name(request.selected_target)
    fallback = _fallback_artifacts(request)
    system_prompt = (
        "You are a Korean job coach creating detailed interview prep artifacts. "
        "Keep outputs concrete, role-specific, and return valid JSON only."
    )
    user_prompt = (
        "Create JSON with keys action_items, interview_questions, answer_frames, self_intro_draft.\n"
        "action_items rules:\n"
        "- 5 to 6 items\n"
        "- detailed Korean strings\n"
        "- each item must be an immediately usable action, not a label\n"
        "interview_questions rules:\n"
        "- 4 to 5 tailored Korean interview questions\n"
        "- reflect the target role, likely motivation/fit/project/gap questions\n"
        "answer_frames rules:\n"
        "- same number of items as interview_questions\n"
        "- each item must correspond to the question at the same index\n"
        "- each item should describe an answer structure using elements like 핵심 메시지, 근거 경험, 성과/수치, 직무 연결, 보완 계획 when relevant\n"
        "- each item must be plain Korean text, not a nested dict/object serialized as a string\n"
        "- use labels like 핵심 메시지: ... | 근거 경험: ... | 성과/수치: ...\n"
        "- do not use braces, quotes around labels, or Python/JSON-looking fragments\n"
        "self_intro_draft rules:\n"
        "- Korean only\n"
        "- 1 paragraph\n"
        "- around 450 to 550 characters\n"
        "- write like a polished Korean cover-letter answer, not a memo or checklist\n"
        "- directly usable as a 500자 자기소개서/지원동기 초안\n"
        "- include support motivation, strongest evidence, role fit, and near-term contribution\n"
        "- no bullets, no headings, no JSON-like fragments\n"
        f"Target: {target_name}\n"
        f"Preparation summary: {request.preparation_summary}\n"
        f"User background: {request.user_background or 'N/A'}\n"
        f"Notes: {request.notes or 'N/A'}"
    )

    try:
        payload: dict[str, Any] = llm_client.generate_json(system_prompt, user_prompt)
        action_items = _coerce_string_list(payload.get("action_items", []), limit=6)
        interview_questions = _coerce_string_list(payload.get("interview_questions", []), limit=5)
        answer_frames = _coerce_answer_frame_list(payload.get("answer_frames", []), limit=5)
        self_intro_draft = _compact_text(payload.get("self_intro_draft"))

        if len(action_items) < 5:
            action_items = fallback.action_items
        if len(interview_questions) < 4:
            interview_questions = fallback.interview_questions

        answer_frames = _align_answer_frames(interview_questions, answer_frames, target_name)
        if not _is_useful_self_intro_draft(self_intro_draft):
            self_intro_draft = fallback.self_intro_draft

        return PrepArtifactsResponse(
            run_id=request.run_id or "",
            action_items=action_items,
            interview_questions=interview_questions,
            answer_frames=answer_frames,
            self_intro_draft=self_intro_draft,
            warnings=[],
        )
    except Exception:
        return fallback


def critique_prep_artifacts(
    settings: Settings,
    request: PrepArtifactsRequest,
    response: PrepArtifactsResponse,
) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    target_name = _select_target_name(request.selected_target)

    if not response.action_items or not response.interview_questions or not response.answer_frames:
        warnings.append("준비 자료가 비어 있어 다시 생성하는 편이 안전합니다.")
        return True, warnings

    if len(response.answer_frames) != len(response.interview_questions):
        warnings.append("면접 질문 수와 답변 구조 수가 맞지 않아 질문별 준비가 흐트러질 수 있습니다.")
        return True, warnings

    if not _is_useful_self_intro_draft(response.self_intro_draft):
        warnings.append("자소서 초안이 너무 짧거나 비어 있어 바로 활용하기 어렵습니다.")
        return True, warnings

    if not any(target_name in item for item in response.action_items):
        warnings.append("실행 항목에 선택한 지원 대상의 맥락이 충분히 드러나지 않습니다.")

    llm_client = build_llm_client(settings)
    if llm_client is None:
        return False, warnings

    system_prompt = (
        "You are reviewing Korean interview-prep artifacts for usefulness and specificity. "
        "Return valid JSON only."
    )
    user_prompt = (
        "Return JSON with keys needs_revision and warnings.\n"
        "needs_revision must be true only when the artifacts are clearly generic, inconsistent, or unusable.\n"
        "warnings must be a short array of Korean strings.\n"
        "Pay special attention to whether answer_frames are aligned to interview_questions by index.\n"
        f"Target: {target_name}\n"
        f"Preparation summary: {request.preparation_summary}\n"
        f"Artifacts: action_items={response.action_items}; "
        f"interview_questions={response.interview_questions}; "
        f"answer_frames={response.answer_frames}; "
        f"self_intro_draft={response.self_intro_draft}"
    )

    try:
        payload: dict[str, Any] = llm_client.generate_json(system_prompt, user_prompt)
        llm_warnings = _coerce_string_list(payload.get("warnings", []), limit=4)
        warnings.extend(llm_warnings)
        return bool(payload.get("needs_revision")), warnings
    except Exception:
        return False, warnings
