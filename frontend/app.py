from __future__ import annotations

import ast
from datetime import datetime
import html
import math
import re
from pathlib import Path
from textwrap import dedent
from typing import Any
from urllib.parse import urlparse

import httpx
import streamlit as st
import streamlit.components.v1 as components

from backend.app.core.settings import get_settings
from backend.app.core.taxonomy import (
    CUSTOM_OPTION,
    PREFERENCE_OPTIONS,
    industry_options,
    job_board_label_for_url,
    job_families_for_industry,
    job_roles_for_family,
)

st.set_page_config(
    page_title="통합 AI 취업 도우미",
    page_icon="🎯",
    layout="wide",
)

SETTINGS = get_settings()
BACKEND_BASE_URL = SETTINGS.backend_base_url.rstrip("/")
REQUEST_TIMEOUT = 60.0
CANDIDATES_PER_PAGE = 9
YEARS_OPTIONS = ("미정", "1년 미만", "1년", "2년", "3년", "4년", "5년", "6년", "7년", "8년", "9년", "10년+")
EXPERIENCE_LEVEL_UI_OPTIONS = ("무관", "인턴", "신입", "연차")
LEGACY_EXPERIENCE_LEVEL_TO_YEARS = {
    "주니어(1~3년)": "1년",
    "미들(4~8년)": "4년",
    "시니어(9년+)": "10년+",
}
RESULT_TABS = ("분석 리포트", "자소서 초안", "면접 대비", "합격 로드맵", "준비 코치")
ANALYSIS_TABS = ("분석 리포트", "준비·보완 포인트")
MAX_VISIBLE_SOURCE_CARDS = 27

CARD_COMPONENT = components.declare_component(
    "candidate_card_selector",
    path=str(Path(__file__).resolve().parent / "components" / "candidate_card_selector"),
)


def _option_index(options: list[str], current_value: str, default_value: str) -> int:
    if current_value in options:
        return options.index(current_value)
    if current_value and current_value not in options and CUSTOM_OPTION in options:
        return options.index(CUSTOM_OPTION)
    if default_value in options:
        return options.index(default_value)
    return 0


def _custom_value(current_value: str, options: list[str]) -> str:
    if current_value and current_value not in options:
        return current_value
    return ""


def _resolve_selected_value(selected_value: str, custom_value: str) -> str:
    if selected_value == CUSTOM_OPTION:
        return " ".join(custom_value.split())
    return " ".join(selected_value.split())


def _split_preferences(value: str) -> tuple[list[str], str]:
    tokens = [token.strip() for token in value.split(",") if token.strip()]
    selected = [token for token in tokens if token in PREFERENCE_OPTIONS]
    custom_tokens = [token for token in tokens if token not in PREFERENCE_OPTIONS]
    return selected, ", ".join(custom_tokens)


def _join_preferences(selected_values: list[str], custom_value: str) -> str:
    merged = [value.strip() for value in selected_values if value.strip()]
    normalized_custom = " ".join(custom_value.replace(",", " ").split())
    if normalized_custom:
        merged.append(normalized_custom)
    return ", ".join(merged)


def _normalize_experience_ui_state(level: str, years: str) -> tuple[str, str]:
    normalized_level = " ".join(str(level or "").split())
    normalized_years = " ".join(str(years or "").split())

    if normalized_level in {"인턴", "신입"}:
        return normalized_level, YEARS_OPTIONS[0]

    if normalized_level == "연차":
        if normalized_years in YEARS_OPTIONS:
            return normalized_level, normalized_years
        return normalized_level, YEARS_OPTIONS[0]

    if normalized_level == "경력":
        if normalized_years in YEARS_OPTIONS:
            return "연차", normalized_years
        return "연차", YEARS_OPTIONS[0]

    if normalized_level in LEGACY_EXPERIENCE_LEVEL_TO_YEARS:
        fallback_years = LEGACY_EXPERIENCE_LEVEL_TO_YEARS[normalized_level]
        if normalized_years in YEARS_OPTIONS and normalized_years != YEARS_OPTIONS[0]:
            return "연차", normalized_years
        return "연차", fallback_years

    return "무관", YEARS_OPTIONS[0]


def _format_experience_level(level: str, years: str) -> str | None:
    normalized_level, normalized_years = _normalize_experience_ui_state(level, years)

    if normalized_level == "무관":
        return None

    if normalized_level in {"인턴", "신입"}:
        return normalized_level

    if normalized_level == "연차":
        if normalized_years == "미정":
            return "경력"
        return f"경력 {normalized_years}"

    if normalized_years == "미정":
        return normalized_level
    return f"{normalized_level} / {normalized_years}"


def _clean_candidate_title(candidate: dict[str, Any]) -> str:
    name = str(candidate.get("name", "제목 없는 공고")).strip()
    board_label = job_board_label_for_url(str(candidate.get("source_url", "")))
    suffix = f" - {board_label}"
    if name.endswith(suffix):
        return name[: -len(suffix)].strip()
    return name


def _truncate_text(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _source_host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _candidate_confidence(candidate: dict[str, Any]) -> float:
    try:
        return float(candidate.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _candidate_page_info(candidates: list[dict[str, Any]], page_index: int) -> tuple[list[dict[str, Any]], int, int, int]:
    total_pages = max(1, math.ceil(len(candidates) / CANDIDATES_PER_PAGE))
    normalized_page = min(max(page_index, 0), total_pages - 1)
    start = normalized_page * CANDIDATES_PER_PAGE
    end = start + CANDIDATES_PER_PAGE
    return candidates[start:end], normalized_page, total_pages, start


def _sync_candidate_state(candidates: list[dict[str, Any]]) -> None:
    if not candidates:
        st.session_state.selected_target_index = 0
        st.session_state.candidate_page_index = 0
        return

    selected_index = st.session_state.selected_target_index
    page_index = st.session_state.candidate_page_index
    st.session_state.selected_target_index = min(max(selected_index, 0), len(candidates) - 1)
    _, normalized_page, _, _ = _candidate_page_info(candidates, page_index)
    st.session_state.candidate_page_index = normalized_page


def _render_candidate_card_component(candidate: dict[str, Any], rank: int, index: int, key_prefix: str) -> float:
    source_url = str(candidate.get("source_url", ""))
    confidence = _candidate_confidence(candidate)
    selected = bool(candidate.get("_selected"))
    value = CARD_COMPONENT(
        board_label=job_board_label_for_url(source_url),
        title=_clean_candidate_title(candidate),
        summary=_truncate_text(str(candidate.get("summary", "")), 132),
        why_relevant=_truncate_text(str(candidate.get("why_relevant", "")), 116),
        source_url=source_url,
        source_host=_source_host(source_url),
        confidence=f"{confidence:.2f}",
        rank=f"#{rank:02d}",
        selected=selected,
        default=0.0,
        key=f"candidate_card_{key_prefix}_{index}",
    )
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _init_state() -> None:
    defaults = {
        "input_payload": {
            "industry": "",
            "job_family": "",
            "job_role": "",
            "experience_level": "무관",
            "experience_years": "미정",
            "preferences": "",
            "user_background": "",
            "notes": "",
        },
        "explore_result": None,
        "candidate_click_ts": 0.0,
        "selected_target_index": 0,
        "selected_target_source": "posting",
        "candidate_page_index": 0,
        "prepare_summary_result": None,
        "prep_artifacts_result": None,
        "coach_chat_history": [],
        "coach_chat_run_id": "",
        "dashboard_active_tab": RESULT_TABS[0],
        "analysis_active_tab": ANALYSIS_TABS[0],
        "candidate_panel_open": False,
        "download_report_markdown": "",
        "source_card_page_index": 0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_flow() -> None:
    st.session_state.input_payload = {
        "industry": "",
        "job_family": "",
        "job_role": "",
        "experience_level": "무관",
        "experience_years": "미정",
        "preferences": "",
        "user_background": "",
        "notes": "",
    }
    st.session_state.explore_result = None
    st.session_state.candidate_click_ts = 0.0
    st.session_state.selected_target_index = 0
    st.session_state.selected_target_source = "posting"
    st.session_state.candidate_page_index = 0
    st.session_state.prepare_summary_result = None
    st.session_state.prep_artifacts_result = None
    st.session_state.coach_chat_history = []
    st.session_state.coach_chat_run_id = ""
    st.session_state.dashboard_active_tab = RESULT_TABS[0]
    st.session_state.analysis_active_tab = ANALYSIS_TABS[0]
    st.session_state.candidate_panel_open = False
    st.session_state.download_report_markdown = ""
    st.session_state.source_card_page_index = 0


def _call_api(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{BACKEND_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            if payload is None:
                response = client.get(url)
            else:
                response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        st.error(f"백엔드 응답 오류: {exc.response.text}")
    except httpx.RequestError as exc:
        st.error(f"백엔드 연결 오류: {exc}")
    return {}


def _selected_candidate_from_index(candidates: list[dict[str, Any]], selected_index: int) -> dict[str, Any] | None:
    if not candidates:
        return None
    if 0 <= selected_index < len(candidates):
        return candidates[selected_index]
    return candidates[0]


def _build_selected_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "name": candidate["name"],
        "kind": candidate["kind"],
        "summary": candidate["summary"],
        "source_url": candidate["source_url"],
    }


def _primary_candidates(explore_result: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
    posting_candidates = explore_result.get("posting_candidates", [])
    if posting_candidates:
        return posting_candidates, "posting", "채용공고"
    company_candidates = explore_result.get("company_candidates", [])
    return company_candidates, "company", "회사 정보"


def _current_candidate_context() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], str, str, dict[str, Any] | None]:
    explore_result = st.session_state.explore_result or {}
    primary_candidates, primary_source, primary_label = _primary_candidates(explore_result)
    company_candidates = explore_result.get("company_candidates", [])

    if st.session_state.selected_target_source != primary_source:
        st.session_state.selected_target_source = primary_source
        st.session_state.selected_target_index = 0
        st.session_state.candidate_page_index = 0
        st.session_state.candidate_click_ts = 0.0

    _sync_candidate_state(primary_candidates)
    selected_target = _selected_candidate_from_index(primary_candidates, st.session_state.selected_target_index)
    return explore_result, primary_candidates, company_candidates, primary_source, primary_label, selected_target


def _search_summary_line() -> str:
    payload = st.session_state.input_payload
    items = [
        payload.get("industry", ""),
        payload.get("job_family", ""),
        payload.get("job_role", ""),
    ]
    experience_label = _format_experience_level(
        str(payload.get("experience_level", "무관")),
        str(payload.get("experience_years", "미정")),
    )
    if experience_label:
        items.append(experience_label)
    if payload.get("preferences"):
        items.append(str(payload["preferences"]))
    return " / ".join(item for item in items if item) or "아직 탐색 조건이 없습니다."


def _paragraphs_html(text: str) -> str:
    paragraphs = [" ".join(paragraph.split()) for paragraph in str(text).split("\n\n")]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        return "<p class='report-empty'>아직 생성된 내용이 없습니다.</p>"
    return "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)


def _list_html(values: list[str], *, numbered: bool = False) -> str:
    if not values:
        return "<p class='report-empty'>아직 생성된 내용이 없습니다.</p>"
    tag = "ol" if numbered else "ul"
    items = "".join(f"<li>{html.escape(str(value))}</li>" for value in values)
    return f"<{tag}>{items}</{tag}>"


def _naturalize_ui_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""

    replacements = (
        ("interview_questions", "면접 질문"),
        ("interview_question", "면접 질문"),
        ("answer_frames", "답변 가이드"),
        ("answer_frame", "답변 가이드"),
        ("action_items", "실행 항목"),
        ("self_intro_draft", "자소서 초안"),
        ("preparation_summary", "분석 리포트"),
        ("preparation_points", "준비 포인트"),
        ("skill_gaps", "보완 포인트"),
    )

    normalized = text
    for raw_key, korean_label in replacements:
        normalized = re.sub(re.escape(raw_key), korean_label, normalized, flags=re.IGNORECASE)
    return normalized.strip()


def _compact_naturalized_text(value: Any) -> str:
    return " ".join(_naturalize_ui_text(value).split())


def _should_show_explore_note(note: Any) -> bool:
    text = _compact_naturalized_text(note)
    if not text:
        return False
    hidden_prefixes = (
        "본문 수집에 실패해",
        "본문 수집에 실패하여",
    )
    return not text.startswith(hidden_prefixes)


STRUCTURED_FIELD_LABEL_ORDER = (
    "핵심 메시지",
    "근거 경험",
    "공고 요구사항",
    "내 경험",
    "보완 포인트",
    "보완 방법",
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

STRUCTURED_FIELD_LABEL_ALIASES = {
    "point": "",
    "key message": "핵심 메시지",
    "key_message": "핵심 메시지",
    "main message": "핵심 메시지",
    "main_message": "핵심 메시지",
    "message": "핵심 메시지",
    "evidence": "근거 경험",
    "experience": "근거 경험",
    "job requirement": "공고 요구사항",
    "job_requirements": "공고 요구사항",
    "requirements": "공고 요구사항",
    "my experience": "내 경험",
    "my_experience": "내 경험",
    "weakness": "보완 포인트",
    "risk": "보완 포인트",
    "compensation": "보완 방법",
    "plan": "보완 방법",
    "problem": "문제",
    "problem definition": "문제 정의",
    "problem_definition": "문제 정의",
    "current status": "현재 상태",
    "current_status": "현재 상태",
    "role": "역할",
    "action": "행동",
    "actions": "행동",
    "approach": "접근 방식",
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


def _normalize_structured_field_label(value: Any) -> str:
    label = _compact_naturalized_text(value).strip().strip(":")
    label = label.strip("'\"")
    alias_key = label.casefold().replace("-", " ").replace("_", " ")
    return STRUCTURED_FIELD_LABEL_ALIASES.get(alias_key, label)


def _structured_field_sort_key(label: str) -> int:
    try:
        return STRUCTURED_FIELD_LABEL_ORDER.index(label)
    except ValueError:
        return len(STRUCTURED_FIELD_LABEL_ORDER)


def _format_structured_field_text(value: Any) -> str:
    if isinstance(value, dict):
        pairs: list[tuple[str, str]] = []
        for key, raw_content in value.items():
            label = _normalize_structured_field_label(key)
            content = _format_structured_field_text(raw_content)
            if not content:
                continue
            pairs.append((label, content))
        pairs.sort(key=lambda item: _structured_field_sort_key(item[0]))
        return " | ".join(f"{label}: {content}" if label else content for label, content in pairs)

    if isinstance(value, list):
        blocks = [_format_structured_field_text(item) for item in value]
        return " | ".join(block for block in blocks if block)

    text = _compact_naturalized_text(value)
    if not text:
        return ""

    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return _format_structured_field_text(parsed)

    cleaned = (
        text.replace("{", "")
        .replace("}", "")
        .replace("[", "")
        .replace("]", "")
        .replace('"', "")
        .replace("'", "")
    )
    cleaned = re.sub(r"\s*->\s*", ": ", cleaned)
    cleaned = re.sub(r"\s*[:：]\s*", ": ", cleaned)
    cleaned = re.sub(r"\s*\|\s*", " | ", cleaned)
    cleaned = re.sub(r"(?i)(^|\|\s*)point\s*:\s*", r"\1", cleaned)
    cleaned = re.sub(r"(?i)(^|\|\s*)gap\s*:\s*", r"\1보완 포인트: ", cleaned)
    cleaned = re.sub(r"(?i)(^|\|\s*)plan\s*:\s*", r"\1보완 방법: ", cleaned)
    return " ".join(cleaned.split())


def _normalize_generated_field_text(value: Any, *, context: str) -> str:
    text = _format_structured_field_text(value)
    if not text:
        return ""

    replacements = {
        "question": [
            ("면접 질문", "면접 질문"),
        ],
        "guide": [
            ("답변 가이드", "답변 가이드"),
        ],
    }

    normalized = text
    for raw_key, korean_label in replacements.get(context, []):
        normalized = re.sub(
            rf"(?i)\b{re.escape(raw_key)}\b\s*[:：-]?\s*",
            f"{korean_label}: ",
            normalized,
        )

    return normalized.strip()


def _paragraphs_markdown(text: str) -> str:
    normalized_text = _markdown_export_text(text)
    paragraphs = [" ".join(paragraph.split()) for paragraph in normalized_text.split("\n\n")]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        return "_아직 생성된 내용이 없습니다._"
    return "\n\n".join(paragraphs)


def _list_markdown(values: list[str], *, numbered: bool = False) -> str:
    if not values:
        return "_아직 생성된 내용이 없습니다._"

    lines: list[str] = []
    for index, value in enumerate(values, start=1):
        marker = f"{index}." if numbered else "-"
        lines.append(f"{marker} {_markdown_export_inline_text(_format_structured_field_text(value))}")
    return "\n".join(lines)


def _checklist_markdown(values: list[str]) -> str:
    if not values:
        return "_아직 생성된 내용이 없습니다._"

    return "\n".join(f"- [ ] {_markdown_export_inline_text(_format_structured_field_text(value))}" for value in values)


def _markdown_table_cell(value: Any) -> str:
    return _markdown_export_inline_text(value).replace("|", "\\|") or "-"


def _markdown_export_text(value: Any) -> str:
    text = _naturalize_ui_text(value)
    if not text:
        return ""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", normalized)
    normalized = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 <\2>", normalized)
    normalized = re.sub(r"<img[^>]*>", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(^|\n)\s*[.·,;:]+\s+", r"\1", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _markdown_export_inline_text(value: Any) -> str:
    text = _markdown_export_text(value)
    return " ".join(text.split()).strip()


def _markdown_kv_table(rows: list[tuple[str, Any]]) -> str:
    if not rows:
        return "_아직 생성된 내용이 없습니다._"

    lines = ["| 항목 | 내용 |", "| --- | --- |"]
    for label, value in rows:
        lines.append(f"| {label} | {_markdown_table_cell(value)} |")
    return "\n".join(lines)


def _markdown_kv_list(rows: list[tuple[str, Any]]) -> str:
    if not rows:
        return "_아직 생성된 내용이 없습니다._"

    lines: list[str] = []
    for label, value in rows:
        rendered = _markdown_export_inline_text(value) or "없음"
        lines.append(f"- **{label}**: {rendered}")
    return "\n".join(lines)


def _download_report_prompt(title: str) -> str:
    return dedent(
        f"""
        아래 지원 전략 리포트를 바탕으로 Notion 문서 스타일의 마크다운으로 다시 정리해 주세요.
        조건:
        - 문서 제목은 `{_compact_naturalized_text(title)}` 기준으로 유지합니다.
        - 섹션 순서는 지원 대상 요약, 분석 리포트, 자소서 초안, 합격 로드맵, 면접 대비 순서로 유지합니다.
        - 준비 포인트와 보완 포인트는 체크리스트 형식으로 정리합니다.
        - 핵심 메시지는 먼저 보이게 하고, 중복 표현은 줄여 간결한 한국어로 다듬습니다.
        - 공고 링크, 사용자 배경, 직무 적합성 근거는 빠뜨리지 않습니다.
        - 자소서 초안은 자연스러운 문단형 문체를 유지하고, 면접 대비는 질문과 답변 가이드가 한 쌍으로 보이게 정리합니다.
        """
    ).strip()


def _interview_markdown(questions: list[str], answer_frames: list[str]) -> str:
    if not questions:
        return "_아직 생성된 내용이 없습니다._"

    blocks: list[str] = []
    for index, question in enumerate(questions, start=1):
        clean_question = _normalize_generated_field_text(question, context="question")
        guide = answer_frames[index - 1] if index - 1 < len(answer_frames) else ""
        clean_guide = _normalize_generated_field_text(guide, context="guide") or "답변 가이드가 아직 없습니다."
        blocks.append(
            dedent(
                f"""
                ### 면접 질문 {index:02d}
                - 질문: {_markdown_export_inline_text(clean_question or '아직 준비된 질문이 없습니다.')}
                - 답변 가이드: {_markdown_export_inline_text(clean_guide)}
                """
            ).strip()
        )
    return "\n\n".join(blocks)


def _interview_html(questions: list[str], answer_frames: list[str]) -> str:
    if not questions:
        return "<p class='report-empty'>아직 생성된 내용이 없습니다.</p>"

    blocks: list[str] = []
    for index, question in enumerate(questions, start=1):
        clean_question = _normalize_generated_field_text(question, context="question")
        guide = answer_frames[index - 1] if index - 1 < len(answer_frames) else ""
        clean_guide = _normalize_generated_field_text(guide, context="guide")
        blocks.append(
            dedent(
                f"""
                <div class="report-interview-item">
                    <h3>면접 질문 {index:02d}</h3>
                    <p><strong>질문:</strong> {html.escape(clean_question or '아직 준비된 질문이 없습니다.')}</p>
                    <p><strong>답변 가이드:</strong> {html.escape(clean_guide or '답변 가이드가 아직 없습니다.')}</p>
                </div>
                """
            ).strip()
        )
    return "".join(blocks)


def _safe_slug(value: str) -> str:
    compact = "".join(char.lower() if char.isalnum() else "-" for char in value)
    slug = "-".join(segment for segment in compact.split("-") if segment)
    return slug[:60] or "job-coach-report"


def _build_download_report_markdown(
    selected_target: dict[str, Any] | None,
    prepare_summary: dict[str, Any] | None,
    artifacts: dict[str, Any] | None,
) -> str:
    target = selected_target or {}
    prepare_summary = prepare_summary or {}
    artifacts = artifacts or {}
    title = _clean_candidate_title(target) if target else "지원 전략 리포트"
    source_url = str(target.get("source_url", ""))
    source_label = job_board_label_for_url(source_url)
    payload = st.session_state.input_payload or {}
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    experience_level = _compact_naturalized_text(payload.get("experience_level", ""))
    experience_years = _compact_naturalized_text(payload.get("experience_years", ""))
    if experience_level == "연차":
        career_text = f"연차 · {experience_years or '미정'}"
    else:
        career_text = experience_level or "미정"
    link_text = f"[공고 바로가기]({source_url})" if source_url else "없음"
    summary_excerpt = _truncate_text(_markdown_export_inline_text(target.get("summary", "")), 180)

    sections = [
        "# 지원 전략 리포트",
        "",
        "> 지원 공고, 분석 리포트, 자소서 초안, 면접 대비, 실행 로드맵을 한 번에 정리한 노션형 마크다운 문서입니다.",
        ">",
        f"> 생성 시각: {generated_at}",
        "",
        "## 문서 한눈에 보기",
        "",
        _markdown_kv_list(
            [
                ("지원 대상", title),
                ("직무 요약", summary_excerpt or "선택한 지원 대상 정보가 없습니다."),
                ("탐색 기준", _search_summary_line()),
                ("출처", source_label),
                ("원본 링크", source_url or "없음"),
            ]
        ),
        "",
        "## 사용자 입력 요약",
        "",
        _markdown_kv_list(
            [
                ("산업", payload.get("industry", "")),
                ("직군", payload.get("job_family", "")),
                ("직무", payload.get("job_role", "")),
                ("경력 수준", career_text),
                ("선호 조건", payload.get("preferences", "") or "없음"),
                ("배경 설명", payload.get("user_background", "") or "없음"),
                ("추가 메모", payload.get("notes", "") or "없음"),
            ]
        ),
        "",
        "---",
        "",
        "## 1. 지원 대상 요약",
        "",
        f"- **공고명**: {_markdown_export_inline_text(title)}",
        f"- **출처**: {_markdown_export_inline_text(source_label)}",
        f"- **링크**: {link_text}",
        "",
        _paragraphs_markdown(str(target.get("summary", "선택한 지원 대상 정보가 없습니다."))),
        "",
        "---",
        "",
        "## 2. 분석 리포트",
        "",
        "### 핵심 진단",
        "",
        _paragraphs_markdown(str(prepare_summary.get("preparation_summary", ""))),
        "",
        "### 준비 포인트",
        "",
        _checklist_markdown(list(prepare_summary.get("preparation_points", []))),
        "",
        "### 보완 포인트",
        "",
        _checklist_markdown(list(prepare_summary.get("skill_gaps", []))),
        "",
        "---",
        "",
        "## 3. 자소서 초안",
        "",
        "> 바로 복사해 자기소개서 초안으로 다듬기 쉬운 문단형 초안입니다.",
        "",
        _paragraphs_markdown(str(artifacts.get("self_intro_draft", ""))),
        "",
        "---",
        "",
        "## 4. 합격 로드맵",
        "",
        _list_markdown(list(artifacts.get("action_items", [])), numbered=True),
        "",
        "---",
        "",
        "## 5. 면접 대비",
        "",
        _interview_markdown(list(artifacts.get("interview_questions", [])), list(artifacts.get("answer_frames", []))),
        "",
        "---",
        "",
        "## 6. 노션 재정리용 프롬프트",
        "",
        "```text",
        _download_report_prompt(title),
        "```",
    ]
    return "\n".join(sections).strip()


def _generate_dashboard_outputs(selected_target: dict[str, Any] | None, *, spinner_text: str) -> None:
    if selected_target is None:
        st.session_state.prepare_summary_result = None
        st.session_state.prep_artifacts_result = None
        st.session_state.download_report_markdown = ""
        return

    explore_result = st.session_state.explore_result or {}
    prepare_payload = {
        "run_id": explore_result.get("run_id"),
        "selected_target": _build_selected_candidate(selected_target),
        "user_background": st.session_state.input_payload.get("user_background") or None,
        "notes": st.session_state.input_payload.get("notes") or None,
    }
    prepare_summary: dict[str, Any] | None = None
    prep_artifacts: dict[str, Any] | None = None

    with st.spinner(spinner_text):
        prepare_summary = _call_api("/prepare-summary", prepare_payload)
        if prepare_summary:
            artifacts_payload = {
                "run_id": prepare_summary.get("run_id") or explore_result.get("run_id"),
                "selected_target": _build_selected_candidate(selected_target),
                "preparation_summary": prepare_summary.get("preparation_summary", ""),
                "user_background": st.session_state.input_payload.get("user_background") or None,
                "notes": st.session_state.input_payload.get("notes") or None,
            }
            prep_artifacts = _call_api("/prep-artifacts", artifacts_payload)

    st.session_state.prepare_summary_result = prepare_summary or None
    st.session_state.prep_artifacts_result = prep_artifacts or None
    st.session_state.dashboard_active_tab = RESULT_TABS[0]
    st.session_state.analysis_active_tab = ANALYSIS_TABS[0]
    st.session_state.download_report_markdown = ""
    if prepare_summary:
        st.session_state.download_report_markdown = _build_download_report_markdown(selected_target, prepare_summary, prep_artifacts)


def _run_initial_search(payload: dict[str, Any]) -> None:
    with st.spinner("지원 대상 후보를 탐색하고 전략을 생성하고 있습니다..."):
        explore_result = _call_api("/explore", payload)
        if not explore_result:
            return

        st.session_state.explore_result = explore_result
        st.session_state.selected_target_index = 0
        st.session_state.selected_target_source = "posting"
        st.session_state.candidate_page_index = 0
        st.session_state.candidate_click_ts = 0.0
        st.session_state.prepare_summary_result = None
        st.session_state.prep_artifacts_result = None
        st.session_state.coach_chat_history = []
        st.session_state.coach_chat_run_id = ""
        st.session_state.analysis_active_tab = ANALYSIS_TABS[0]
        st.session_state.candidate_panel_open = False
        st.session_state.download_report_markdown = ""
        st.session_state.source_card_page_index = 0

        primary_candidates, _, _ = _primary_candidates(explore_result)
        selected_target = _selected_candidate_from_index(primary_candidates, 0)
        if selected_target is not None:
            _generate_dashboard_outputs(selected_target, spinner_text="선택한 지원 후보 기준으로 결과를 정리하고 있습니다...")


def _render_preparation_card_list(title: str, values: list[str]) -> None:
    st.markdown(f"### {title}")
    if not values:
        st.info("아직 내용이 없습니다.")
        return

    for index, item in enumerate(values, start=1):
        st.markdown(
            dedent(
                f"""
                <div class="result-card result-card--soft">
                    <div class="result-card__eyebrow">준비 포인트 {index:02d}</div>
                    <div class="result-card__body">{html.escape(_format_structured_field_text(item))}</div>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )


def _parse_gap_item(text: str) -> tuple[str, str]:
    weakness = ""
    compensation = ""
    normalized_text = _format_structured_field_text(text)
    for raw_line in re.split(r"\s*\|\s*|\n", normalized_text):
        line = " ".join(raw_line.split())
        if not line:
            continue
        lowered = line.lower()
        if line.startswith("보완 포인트:"):
            weakness = line.split(":", 1)[1].strip()
        elif line.startswith("보완 방법:"):
            compensation = line.split(":", 1)[1].strip()
        elif lowered.startswith("weakness:"):
            weakness = line.split(":", 1)[1].strip()
        elif lowered.startswith("compensation:"):
            compensation = line.split(":", 1)[1].strip()
        elif lowered.startswith("risk:"):
            weakness = line.split(":", 1)[1].strip()
        elif lowered.startswith("plan:"):
            compensation = line.split(":", 1)[1].strip()
        elif lowered.startswith("gap:"):
            weakness = line.split(":", 1)[1].strip()
    return weakness, compensation


def _render_gap_list(title: str, values: list[str]) -> None:
    st.markdown(f"### {title}")
    if not values:
        st.info("아직 내용이 없습니다.")
        return

    for item in values:
        weakness, compensation = _parse_gap_item(item)
        compensation_text = _format_structured_field_text(compensation).strip() if compensation else ""
        show_compensation = bool(
            compensation_text and compensation_text != "추가 보완 계획을 구체화해 주세요."
        )
        compensation_block = ""
        if show_compensation:
            compensation_block = dedent(
                f"""
                <div class="result-card__eyebrow result-card__eyebrow--spaced">보완 방법</div>
                <div class="result-card__body">{html.escape(compensation_text)}</div>
                """
            ).strip()
        st.markdown(
            dedent(
                f"""
                <div class="result-card result-card--warning">
                    <div class="result-card__eyebrow">보완 포인트</div>
                    <div class="result-card__body">{html.escape(_format_structured_field_text(weakness or item))}</div>
                    {compensation_block}
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )


def _render_action_items(values: list[str]) -> None:
    if not values:
        st.info("아직 실행 항목이 없습니다.")
        return

    for index, item in enumerate(values, start=1):
        st.markdown(
            dedent(
                f"""
                <div class="result-card result-card--roadmap">
                    <div class="result-card__eyebrow">로드맵 {index:02d}</div>
                    <div class="result-card__body">{html.escape(_format_structured_field_text(item))}</div>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )


def _render_interview_guides(questions: list[str], answer_guides: list[str]) -> None:
    if not questions:
        st.info("아직 준비된 질문이 없습니다.")
        return

    for index, question in enumerate(questions, start=1):
        clean_question = _normalize_generated_field_text(question, context="question")
        guide = answer_guides[index - 1] if index - 1 < len(answer_guides) else ""
        clean_guide = _normalize_generated_field_text(guide, context="guide") or "답변 가이드가 아직 없습니다."
        st.markdown(
            dedent(
                f"""
                <div class="interview-card">
                    <div class="interview-card__question">면접 질문 {index:02d}</div>
                    <div class="interview-card__answer"><strong>질문:</strong> {html.escape(clean_question or '아직 준비된 질문이 없습니다.')}</div>
                    <div class="interview-card__answer"><strong>답변 가이드:</strong> {html.escape(clean_guide)}</div>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )


def _render_self_intro_draft(text: str) -> None:
    paragraphs = [" ".join(paragraph.split()) for paragraph in _naturalize_ui_text(text).split("\n\n")]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        st.info("아직 자소서 초안이 없습니다.")
        return

    body = "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)
    st.markdown(
        dedent(
            f"""
            <div class="self-intro-card">
                <div class="result-card__eyebrow">짧은 자기소개 초안</div>
                <div class="self-intro-card__body">{body}</div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )


def _render_analysis_report_section(prepare_summary: dict[str, Any]) -> None:
    st.markdown("<div class='dashboard-segment-label'>분석 리포트 세부 보기</div>", unsafe_allow_html=True)
    analysis_tab = st.radio(
        "분석 리포트 세부 보기",
        options=list(ANALYSIS_TABS),
        horizontal=True,
        label_visibility="collapsed",
        key="analysis_active_tab",
    )

    if analysis_tab == ANALYSIS_TABS[0]:
        st.markdown("## 분석 리포트")
        st.markdown(_naturalize_ui_text(prepare_summary.get("preparation_summary", "아직 분석 리포트가 없습니다.")))
        return

    st.markdown("## 준비·보완 포인트")
    col1, col2 = st.columns(2)
    with col1:
        _render_preparation_card_list("준비 포인트", prepare_summary.get("preparation_points", []))
    with col2:
        _render_gap_list("보완 포인트", prepare_summary.get("skill_gaps", []))


def _current_run_id() -> str:
    prepare_summary = st.session_state.prepare_summary_result or {}
    explore_result = st.session_state.explore_result or {}
    return str(prepare_summary.get("run_id") or explore_result.get("run_id") or "")


def _sync_coach_chat_history(run_id: str) -> None:
    if not run_id:
        return
    if st.session_state.coach_chat_run_id == run_id:
        return

    payload = _call_api(f"/coach-chat/history/{run_id}")
    st.session_state.coach_chat_run_id = run_id
    st.session_state.coach_chat_history = payload.get("messages", []) if payload else []


def _render_coach_chat_section(run_id: str, selected_target: dict[str, Any] | None) -> None:
    if not run_id:
        st.info("분석 결과가 준비된 뒤에 코치에게 추가 질문을 할 수 있습니다.")
        return

    _sync_coach_chat_history(run_id)

    st.caption("현재 생성된 분석 리포트, 자소서 초안, 로드맵, 면접 질문을 바탕으로 이어서 질문할 수 있습니다.")
    st.markdown("<div class='dashboard-segment-label'>추가 질문</div>", unsafe_allow_html=True)

    with st.form("coach_chat_form", clear_on_submit=True):
        question = st.text_input(
            "준비 코치에게 질문",
            placeholder="예: 이 후보 기준으로 지원 동기를 어떻게 더 설득력 있게 말하면 좋을까요?",
        )
        submitted = st.form_submit_button("질문 보내기", use_container_width=True)

    if submitted:
        normalized_question = " ".join(question.split())
        if not normalized_question:
            st.warning("질문을 입력해 주세요.")
            return

        payload = {
            "run_id": run_id,
            "question": normalized_question,
            "selected_target": _build_selected_candidate(selected_target),
            "user_background": st.session_state.input_payload.get("user_background") or None,
            "notes": st.session_state.input_payload.get("notes") or None,
        }
        with st.spinner("준비 코치가 답변을 정리하고 있습니다..."):
            result = _call_api("/coach-chat", payload)
        if result:
            for warning in result.get("warnings", []):
                st.warning(_compact_naturalized_text(warning))
            st.session_state.coach_chat_run_id = run_id
            st.session_state.coach_chat_history = result.get("messages", [])
            st.rerun()

    st.markdown("<div class='dashboard-segment-label'>Q&A</div>", unsafe_allow_html=True)
    history = st.session_state.coach_chat_history
    if not history:
        st.info("예: 이 공고 기준으로 제 강점을 어떻게 말하면 좋을까요?")
        return

    for message in history:
        role = "assistant" if message.get("role") == "assistant" else "user"
        with st.chat_message(role):
            st.markdown(message.get("content", ""))
            if role == "assistant" and message.get("preparation_tips"):
                st.markdown("**준비 팁**")
                for item in message["preparation_tips"]:
                    st.markdown(f"- {item}")
            if role == "assistant" and message.get("suggested_questions"):
                st.markdown("**다음에 물어보면 좋은 질문**")
                for item in message["suggested_questions"]:
                    st.markdown(f"- {item}")


def _render_source_cards(source_cards: list[dict[str, Any]]) -> None:
    visible_cards = source_cards[:MAX_VISIBLE_SOURCE_CARDS]

    with st.expander("탐색 근거 및 참고 정보", expanded=False):
        if not visible_cards:
            st.info("아직 탐색 근거 카드가 없습니다.")
            return

        page_cards, page_index, total_pages, start_index = _candidate_page_info(
            visible_cards,
            st.session_state.source_card_page_index,
        )
        st.session_state.source_card_page_index = page_index

        for row_start in range(0, len(page_cards), 3):
            columns = st.columns(3)
            for offset, column in enumerate(columns):
                local_index = row_start + offset
                if local_index >= len(page_cards):
                    continue

                card = page_cards[local_index]
                board_label = job_board_label_for_url(str(card.get("url", "")))
                confidence = float(card.get("confidence", 0.0) or 0.0)
                source_type = str(card.get("source_type", "general"))
                title = str(card.get("title", "제목 없음"))
                claim = _truncate_text(str(card.get("claim", "")), 210)
                url = str(card.get("url", ""))

                with column:
                    st.markdown(
                        dedent(
                            f"""
                            <div class="source-card">
                                <div class="source-card__meta">
                                    <span class="source-card__badge">{html.escape(board_label)}</span>
                                    <span class="source-card__confidence">신뢰도 {confidence:.2f}</span>
                                </div>
                                <div class="source-card__title">
                                    <a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">{html.escape(title)}</a>
                                </div>
                                <div class="source-card__copy">{html.escape(claim or '요약 정보가 없습니다.')}</div>
                                <div class="source-card__footer">{html.escape(source_type)} · {html.escape(_source_host(url) or url)}</div>
                            </div>
                            """
                        ).strip(),
                        unsafe_allow_html=True,
                    )

        footer_left, footer_center, footer_right = st.columns([1, 2.1, 1])
        with footer_left:
            if st.button("<", key="source_card_page_prev", disabled=page_index == 0, use_container_width=True):
                st.session_state.source_card_page_index = max(page_index - 1, 0)
                st.rerun()
        with footer_center:
            st.markdown(
                dedent(
                    f"""
                    <div class="candidate-grid-pagination">
                        {page_index + 1}/{total_pages} 페이지 ·
                        {start_index + 1}-{start_index + len(page_cards)} / {len(visible_cards)} 탐색 근거
                    </div>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )
        with footer_right:
            if st.button(">", key="source_card_page_next", disabled=page_index >= total_pages - 1, use_container_width=True):
                st.session_state.source_card_page_index = min(page_index + 1, total_pages - 1)
                st.rerun()


def _render_supporting_company_cards(company_candidates: list[dict[str, Any]]) -> None:
    if not company_candidates:
        return

    with st.expander("참고용 회사 정보", expanded=False):
        for candidate in company_candidates:
            st.markdown(f"**{candidate['name']}**")
            st.caption(candidate["source_url"])
            st.write(candidate["summary"])
            st.divider()


def _render_candidate_grid(candidates: list[dict[str, Any]]) -> int | None:
    key_prefix = str((st.session_state.explore_result or {}).get("run_id", "adhoc"))
    page_candidates, page_index, total_pages, start_index = _candidate_page_info(
        candidates,
        st.session_state.candidate_page_index,
    )
    st.session_state.candidate_page_index = page_index

    clicked_candidate_index: int | None = None

    for row_start in range(0, len(page_candidates), 3):
        columns = st.columns(3)
        for offset, column in enumerate(columns):
            local_index = row_start + offset
            if local_index >= len(page_candidates):
                continue

            global_index = start_index + local_index
            candidate = dict(page_candidates[local_index])
            candidate["_selected"] = global_index == st.session_state.selected_target_index

            with column:
                click_ts = _render_candidate_card_component(candidate, global_index + 1, global_index, key_prefix)
                if click_ts > st.session_state.get("candidate_click_ts", 0.0):
                    st.session_state.candidate_click_ts = click_ts
                    clicked_candidate_index = global_index

    footer_left, footer_center, footer_right = st.columns([1, 2.1, 1])
    with footer_left:
        if st.button("이전", key="candidate_page_prev", disabled=page_index == 0, use_container_width=True):
            st.session_state.candidate_page_index = max(page_index - 1, 0)
            st.rerun()
    with footer_center:
        st.markdown(
            dedent(
                f"""
                <div class="candidate-grid-pagination">
                    {page_index + 1}/{total_pages} 페이지 ·
                    {start_index + 1}-{start_index + len(page_candidates)} / {len(candidates)} 후보
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )
    with footer_right:
        if st.button("다음", key="candidate_page_next", disabled=page_index >= total_pages - 1, use_container_width=True):
            st.session_state.candidate_page_index = min(page_index + 1, total_pages - 1)
            st.rerun()

    if clicked_candidate_index is not None:
        st.session_state.selected_target_index = clicked_candidate_index
    return clicked_candidate_index


def _inject_styles() -> None:
    st.markdown(
        dedent(
            """
            <style>
            @import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css");
            @import url("https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0,0");

            :root {
                --bg-top: #dfefff;
                --bg-bottom: #f4f9ff;
                --ink: #15344d;
                --muted: #5a7691;
                --line: rgba(74, 114, 156, 0.22);
                --card: rgba(255, 255, 255, 0.78);
                --card-strong: rgba(255, 255, 255, 0.9);
                --accent-soft: #eef5ff;
                --shadow: 0 18px 46px rgba(38, 78, 122, 0.14);
            }

            .stApp {
                font-family: "Pretendard", "Noto Sans KR", "Apple SD Gothic Neo", "Segoe UI", sans-serif;
            }

            .material-symbols-rounded,
            .material-symbols-outlined,
            .material-icons,
            [class*="material-symbols"],
            [data-testid="stIconMaterial"] {
                font-family: "Material Symbols Rounded", "Material Symbols Outlined", "Material Icons" !important;
                font-weight: normal !important;
                font-style: normal !important;
                line-height: 1 !important;
                letter-spacing: normal !important;
                text-transform: none !important;
                white-space: nowrap !important;
                word-wrap: normal !important;
                font-feature-settings: "liga" !important;
                -webkit-font-feature-settings: "liga" !important;
                font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24 !important;
                -webkit-font-smoothing: antialiased;
            }

            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(255, 255, 255, 0.95) 0%, rgba(255, 255, 255, 0) 30%),
                    radial-gradient(circle at bottom right, rgba(255, 255, 255, 0.9) 0%, rgba(255, 255, 255, 0) 20%),
                    linear-gradient(135deg, var(--bg-top) 0%, #d5e7fb 28%, #ebf5ff 58%, var(--bg-bottom) 100%);
                color: var(--ink);
            }

            .block-container {
                max-width: 1080px;
                padding-top: 1.4rem;
                padding-bottom: 3rem;
            }

            [data-testid="stHeader"] {
                background: rgba(0, 0, 0, 0);
            }

            [data-testid="stSidebar"] {
                display: none;
            }

            div[data-testid="stForm"] {
                background: var(--card);
                border: 1px solid var(--line);
                border-radius: 24px;
                padding: 1.25rem 1.3rem 1rem 1.3rem;
                box-shadow: var(--shadow);
                backdrop-filter: blur(14px);
            }

            div[data-baseweb="select"] > div,
            .stTextInput input,
            .stTextArea textarea {
                background: rgba(255, 255, 255, 0.9) !important;
                border: 1px solid rgba(111, 144, 180, 0.26) !important;
                border-radius: 14px !important;
                color: var(--ink) !important;
                box-shadow: none !important;
            }

            .stTextArea textarea {
                min-height: 132px;
            }

            .stMultiSelect [data-baseweb="tag"] {
                background: var(--accent-soft) !important;
                border-radius: 999px !important;
                color: #24517a !important;
            }

            div[role="radiogroup"] {
                gap: 0.55rem;
            }

            div[role="radiogroup"] label {
                background: rgba(255, 255, 255, 0.74);
                border: 1px solid rgba(111, 144, 180, 0.22);
                border-radius: 999px;
                padding: 0.35rem 0.7rem;
            }

            div.stButton > button,
            div.stDownloadButton > button,
            .stForm button {
                border: 0 !important;
                border-radius: 14px !important;
                background: linear-gradient(180deg, #2f8ef2 0%, #176eca 100%) !important;
                color: #ffffff !important;
                font-weight: 700 !important;
                min-height: 2.9rem !important;
                box-shadow: 0 12px 24px rgba(28, 103, 184, 0.22);
                transition: transform 0.16s ease, box-shadow 0.16s ease;
            }

            div.stButton > button:hover,
            div.stDownloadButton > button:hover,
            .stForm button:hover {
                transform: translateY(-1px);
                box-shadow: 0 16px 28px rgba(28, 103, 184, 0.28);
            }

            .dashboard-hero,
            .summary-hero {
                border: 1px solid var(--line);
                border-radius: 24px;
                background: var(--card);
                box-shadow: var(--shadow);
                backdrop-filter: blur(14px);
            }

            .dashboard-hero {
                padding: 1.35rem 1.55rem;
                margin-bottom: 1rem;
            }

            .dashboard-hero__eyebrow,
            .section-title__eyebrow,
            .result-card__eyebrow {
                font-size: 0.78rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: var(--muted);
            }

            .dashboard-hero__title {
                margin: 0.35rem 0 0.55rem 0;
                font-size: 2rem;
                line-height: 1.15;
                font-weight: 800;
                color: #17334d;
            }

            .dashboard-hero__copy {
                font-size: 1rem;
                line-height: 1.7;
                color: #43617c;
            }

            .section-title {
                margin: 0 0 0.75rem 0;
            }

            .section-title__label {
                margin-top: 0.18rem;
                font-size: 1.35rem;
                font-weight: 800;
                color: #17334d;
            }

            .summary-hero {
                padding: 1.25rem 1.35rem;
                margin-top: 1rem;
                margin-bottom: 0.9rem;
            }

            .summary-hero__title {
                margin: 0.4rem 0 0.55rem 0;
                font-size: 1.45rem;
                font-weight: 800;
                line-height: 1.35;
                color: #17334d;
            }

            .summary-hero__copy {
                color: #3f617f;
                line-height: 1.7;
            }

            .summary-hero__meta {
                display: flex;
                flex-wrap: wrap;
                gap: 0.55rem;
                margin-top: 0.9rem;
            }

            .summary-pill {
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                padding: 0.38rem 0.78rem;
                border-radius: 999px;
                background: var(--accent-soft);
                color: #2e587f;
                font-size: 0.85rem;
                font-weight: 700;
            }

            .input-divider {
                width: 100%;
                height: 1px;
                margin: 0.35rem 0 0.9rem 0;
                border-radius: 999px;
                background: linear-gradient(90deg, #174f95 0%, #176eca 100%);
                box-shadow: 0 4px 10px rgba(23, 110, 202, 0.12);
            }

            .dashboard-note {
                margin: 0.45rem 0 0.9rem 0;
                color: #55728d;
                font-size: 0.95rem;
            }

            .candidate-grid-pagination {
                margin-top: 0.55rem;
                padding: 0.85rem 1rem;
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.82);
                border: 1px solid rgba(111, 144, 180, 0.18);
                color: #4a6986;
                font-size: 0.92rem;
                text-align: center;
            }

            .result-card,
            .interview-card,
            .self-intro-card,
            .source-card {
                border-radius: 22px;
                border: 1px solid rgba(111, 144, 180, 0.18);
                box-shadow: 0 14px 32px rgba(38, 78, 122, 0.08);
                padding: 1.05rem 1.15rem;
                margin-bottom: 0.9rem;
                background: var(--card-strong);
            }

            .result-card--soft {
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.95) 0%, rgba(243, 249, 255, 0.96) 100%);
            }

            .result-card--warning {
                background: linear-gradient(180deg, rgba(255, 250, 244, 0.95) 0%, rgba(255, 245, 232, 0.96) 100%);
            }

            .result-card--roadmap {
                background: linear-gradient(180deg, rgba(246, 255, 250, 0.95) 0%, rgba(239, 250, 244, 0.96) 100%);
            }

            .result-card__body,
            .interview-card__answer,
            .self-intro-card__body {
                color: #27435d;
                line-height: 1.7;
                font-size: 0.98rem;
            }

            .result-card__eyebrow--spaced {
                margin-top: 0.8rem;
            }

            .self-intro-card__body p {
                margin: 0 0 0.9rem 0;
            }

            .self-intro-card__body p:last-child {
                margin-bottom: 0;
            }

            .interview-card__question {
                margin-bottom: 0.55rem;
                font-weight: 800;
                color: #1a4671;
                font-size: 1rem;
                line-height: 1.5;
            }

            .source-card {
                box-sizing: border-box;
                width: 100%;
                min-height: 316px;
                height: 316px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(243, 249, 255, 0.95) 100%);
                overflow: hidden;
            }

            .source-card__meta {
                display: flex;
                gap: 0.5rem;
                align-items: center;
                flex-wrap: wrap;
                margin-bottom: 0.65rem;
            }

            .source-card__badge {
                display: inline-flex;
                align-items: center;
                padding: 0.24rem 0.58rem;
                border-radius: 999px;
                background: #edf5ff;
                color: #2c5a86;
                font-size: 0.76rem;
                font-weight: 700;
            }

            .source-card__confidence,
            .source-card__footer {
                color: #5b758f;
                font-size: 0.82rem;
                line-height: 1.5;
            }

            .source-card__title {
                margin-bottom: 0.6rem;
                font-size: 1rem;
                font-weight: 800;
                line-height: 1.45;
            }

            .source-card__title a {
                color: #1a4671;
                text-decoration: none;
            }

            .source-card__title a:hover {
                text-decoration: underline;
            }

            .source-card__copy {
                color: #34506a;
                font-size: 0.93rem;
                line-height: 1.62;
                display: -webkit-box;
                -webkit-line-clamp: 6;
                -webkit-box-orient: vertical;
                overflow: hidden;
                margin-bottom: 0.85rem;
            }

            .dashboard-segment-label {
                margin-top: 1rem;
                margin-bottom: 0.45rem;
                color: var(--muted);
                font-size: 0.86rem;
                font-weight: 700;
                letter-spacing: 0.05em;
                text-transform: uppercase;
            }

            @media (max-width: 900px) {
                .block-container {
                    padding-top: 1rem;
                }
                .dashboard-hero__title {
                    font-size: 1.6rem;
                }
                .summary-hero__title {
                    font-size: 1.2rem;
                }
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.markdown(
        dedent(
            """
            <div class="dashboard-hero">
                <div class="dashboard-hero__eyebrow">AI Job Assistant</div>
                <div class="dashboard-hero__title">🎯 통합 AI 취업 도우미</div>
                <div class="dashboard-hero__copy">
                    한 번의 입력으로 지원 대상을 탐색하고, 분석 리포트부터 자소서 초안, 면접 대비,
                    합격 로드맵까지 한 화면에서 정리합니다.
                </div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )


def _render_input_stage() -> None:
    st.markdown(
        dedent(
            """
            <div class="section-title">
                <div class="section-title__eyebrow">Input Panel</div>
                <div class="section-title__label">📝 정보 입력</div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    saved_payload = st.session_state.input_payload
    saved_experience_level, saved_experience_years = _normalize_experience_ui_state(
        str(saved_payload.get("experience_level", "무관")),
        str(saved_payload.get("experience_years", "미정")),
    )
    saved_payload["experience_level"] = saved_experience_level
    saved_payload["experience_years"] = saved_experience_years
    saved_preferences, saved_custom_preferences = _split_preferences(saved_payload["preferences"])

    industry_base_options = industry_options()
    industry_options_with_custom = [*industry_base_options, CUSTOM_OPTION]

    col1, col2, col3 = st.columns(3)
    with col1:
        selected_industry = st.selectbox(
            "산업 (Industry)",
            options=industry_options_with_custom,
            index=_option_index(industry_options_with_custom, saved_payload["industry"], industry_base_options[0]),
        )
        custom_industry = ""
        if selected_industry == CUSTOM_OPTION:
            custom_industry = st.text_input("산업 직접 입력", value=_custom_value(saved_payload["industry"], industry_base_options))
        industry = _resolve_selected_value(selected_industry, custom_industry)

    family_base_options = job_families_for_industry(industry if industry in industry_base_options else None)
    family_options_with_custom = [*family_base_options, CUSTOM_OPTION]
    with col2:
        selected_job_family = st.selectbox(
            "직군 (Job Group)",
            options=family_options_with_custom,
            index=_option_index(family_options_with_custom, saved_payload["job_family"], family_base_options[0]),
        )
        custom_job_family = ""
        if selected_job_family == CUSTOM_OPTION:
            custom_job_family = st.text_input("직군 직접 입력", value=_custom_value(saved_payload["job_family"], family_base_options))
        job_family = _resolve_selected_value(selected_job_family, custom_job_family)

    role_base_options = job_roles_for_family(job_family if job_family in family_base_options else None)
    role_options_with_custom = [*role_base_options, CUSTOM_OPTION]
    with col3:
        selected_job_role = st.selectbox(
            "직무 (Job Role)",
            options=role_options_with_custom,
            index=_option_index(role_options_with_custom, saved_payload["job_role"], role_base_options[0]),
        )
        custom_job_role = ""
        if selected_job_role == CUSTOM_OPTION:
            custom_job_role = st.text_input("직무 직접 입력", value=_custom_value(saved_payload["job_role"], role_base_options))
        job_role = _resolve_selected_value(selected_job_role, custom_job_role)

    col4, col5 = st.columns([2.2, 1])
    with col4:
        experience_level = st.radio(
            "경력 수준 (Experience Level)",
            options=list(EXPERIENCE_LEVEL_UI_OPTIONS),
            index=_option_index(list(EXPERIENCE_LEVEL_UI_OPTIONS), saved_experience_level, EXPERIENCE_LEVEL_UI_OPTIONS[0]),
            horizontal=True,
        )
    with col5:
        default_years = saved_experience_years if saved_experience_level == "연차" else YEARS_OPTIONS[0]
        experience_years = st.selectbox(
            "연차 (Years)",
            options=list(YEARS_OPTIONS),
            index=_option_index(list(YEARS_OPTIONS), default_years, YEARS_OPTIONS[0]),
            disabled=experience_level != "연차",
        )

    st.markdown("<div class='input-divider'></div>", unsafe_allow_html=True)
    selected_preferences = st.multiselect("선호 조건", options=list(PREFERENCE_OPTIONS), default=saved_preferences)
    custom_preferences = st.text_input(
        "추가 선호 조건",
        value=saved_custom_preferences,
        placeholder="예: 수도권, 정규직, B2B SaaS, 데이터 중심 문화",
    )
    st.markdown("<div class='input-divider'></div>", unsafe_allow_html=True)
    preferences = _join_preferences(selected_preferences, custom_preferences)

    user_background = st.text_area(
        "배경 설명",
        value=saved_payload["user_background"],
        placeholder="프로젝트 경험, 강점, 강조하고 싶은 성과를 적어 두면 결과에 반영됩니다.",
        height=150,
    )
    notes = st.text_area(
        "추가 메모",
        value=saved_payload["notes"],
        placeholder="예: 지원 동기를 더 설득력 있게 만들고 싶음, 회사 이해 강조 필요",
        height=96,
    )

    submitted = st.button("🚀 지원 대상 후보 탐색 및 전략 생성", use_container_width=True)

    if submitted:
        missing_fields = [label for label, value in [("산업", industry), ("직군", job_family), ("직무", job_role)] if not value]
        if missing_fields:
            st.error(f"다음 항목을 먼저 입력해 주세요: {', '.join(missing_fields)}")
            return

        normalized_years = experience_years if experience_level == "연차" else YEARS_OPTIONS[0]
        normalized_experience_level = _format_experience_level(experience_level, normalized_years)
        normalized_preferences = preferences or None
        payload = {
            "industry": industry,
            "job_family": job_family,
            "job_role": job_role,
            "experience_level": normalized_experience_level,
            "preferences": normalized_preferences,
            "user_background": user_background or None,
        }
        st.session_state.input_payload = {
            "industry": industry,
            "job_family": job_family,
            "job_role": job_role,
            "experience_level": experience_level,
            "experience_years": normalized_years,
            "preferences": normalized_preferences or "",
            "user_background": user_background,
            "notes": notes,
        }
        _run_initial_search(payload)
        st.rerun()


def _render_dashboard_results() -> None:
    explore_result = st.session_state.explore_result
    if not explore_result:
        return

    for note in explore_result.get("notes", []):
        if _should_show_explore_note(note):
            st.warning(_compact_naturalized_text(note))

    explore_result, primary_candidates, company_candidates, primary_source, primary_label, selected_target = _current_candidate_context()
    if not primary_candidates or selected_target is None:
        st.info("조건에 맞는 지원 후보를 찾지 못했습니다. 입력 조건을 조금 넓혀 다시 시도해 보세요.")
        return

    selected_title = _clean_candidate_title(selected_target)
    selected_summary = _truncate_text(str(selected_target.get("summary", "")), 230)
    board_label = job_board_label_for_url(str(selected_target.get("source_url", "")))
    confidence = _candidate_confidence(selected_target)
    query_text = " / ".join(explore_result.get("queries", []))
    selection_badge = "직접 선택한 지원 후보" if st.session_state.candidate_click_ts > 0 else "자동 선택된 1순위 후보"

    st.markdown(
        dedent(
            f"""
            <div class="summary-hero">
                <div class="result-card__eyebrow">현재 선택한 지원 대상</div>
                <div class="summary-hero__title">{html.escape(selected_title)}</div>
                <div class="summary-hero__copy">{html.escape(selected_summary)}</div>
                <div class="summary-hero__meta">
                    <span class="summary-pill">{selection_badge}</span>
                    <span class="summary-pill">{html.escape(primary_label)} · {html.escape(board_label)}</span>
                    <span class="summary-pill">신뢰도 {confidence:.2f}</span>
                    <span class="summary-pill">{html.escape(str(selected_target.get("source_url", "")))}</span>
                </div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )
    st.caption(f"마지막 탐색 기준: {_search_summary_line()}")
    if query_text:
        st.caption(f"탐색 쿼리: {query_text}")
    if primary_source == "company":
        st.info("직접 공고가 부족해 회사 정보 중심 후보를 우선 사용하고 있습니다.")

    control_col1, control_col2, control_col3 = st.columns([1.1, 1.1, 1.4])
    with control_col1:
        toggle_label = "지원 대상 변경 닫기" if st.session_state.candidate_panel_open else "지원 대상 변경"
        if st.button(toggle_label, use_container_width=True):
            st.session_state.candidate_panel_open = not st.session_state.candidate_panel_open
            st.rerun()
    with control_col2:
        if st.button("전략 다시 생성", use_container_width=True):
            _generate_dashboard_outputs(selected_target, spinner_text="선택한 지원 대상으로 결과를 다시 만들고 있습니다...")
            st.rerun()
    with control_col3:
        st.download_button(
            "전체 리포트 다운로드",
            data=st.session_state.download_report_markdown or "",
            file_name=f"{_safe_slug(selected_title)}-report.md",
            mime="text/markdown",
            use_container_width=True,
            disabled=not bool(st.session_state.download_report_markdown),
        )

    st.markdown("<div class='dashboard-note'>지원 대상 변경 패널에서 다른 후보를 누르면 해당 후보 기준으로 결과를 다시 생성합니다.</div>", unsafe_allow_html=True)

    if st.session_state.candidate_panel_open:
        st.markdown(
            dedent(
                """
                <div class="section-title">
                    <div class="section-title__eyebrow">지원 대상 선택 패널</div>
                    <div class="section-title__label">지원 대상 변경</div>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )
        clicked_candidate_index = _render_candidate_grid(primary_candidates)
        if clicked_candidate_index is not None:
            _, primary_candidates, _, _, _, updated_target = _current_candidate_context()
            st.session_state.candidate_panel_open = False
            _generate_dashboard_outputs(updated_target, spinner_text="선택한 지원 대상으로 결과를 다시 만들고 있습니다...")
            st.rerun()

    _render_supporting_company_cards(company_candidates)

    prepare_summary = st.session_state.prepare_summary_result or {}
    prep_artifacts = st.session_state.prep_artifacts_result or {}

    for warning in prepare_summary.get("warnings", []):
        st.warning(_compact_naturalized_text(warning))
    for warning in prep_artifacts.get("warnings", []):
        st.warning(_compact_naturalized_text(warning))

    st.markdown("<div class='dashboard-segment-label'>대시보드 결과</div>", unsafe_allow_html=True)
    active_tab = st.radio(
        "결과 보기",
        options=list(RESULT_TABS),
        horizontal=True,
        label_visibility="collapsed",
        key="dashboard_active_tab",
    )

    if active_tab == "분석 리포트":
        _render_analysis_report_section(prepare_summary)
    elif active_tab == "자소서 초안":
        st.markdown("## 자소서 초안")
        _render_self_intro_draft(str(prep_artifacts.get("self_intro_draft", "")))
    elif active_tab == "면접 대비":
        st.markdown("## 면접 대비")
        _render_interview_guides(
            list(prep_artifacts.get("interview_questions", [])),
            list(prep_artifacts.get("answer_frames", [])),
        )
    elif active_tab == "합격 로드맵":
        st.markdown("## 오늘의 합격 로드맵")
        _render_action_items(list(prep_artifacts.get("action_items", [])))
    else:
        st.markdown("## 준비 코치")
        _render_coach_chat_section(_current_run_id(), selected_target)


def main() -> None:
    _init_state()
    _inject_styles()
    _render_header()
    _render_input_stage()
    _render_dashboard_results()


if __name__ == "__main__":
    main()
