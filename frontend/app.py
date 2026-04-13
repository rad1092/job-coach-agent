from __future__ import annotations

import html
import math
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
    EXPERIENCE_LEVEL_OPTIONS,
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
RESULT_TABS = ("분석 리포트", "자소서 초안", "면접 대비", "합격 로드맵")

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


def _format_experience_level(level: str, years: str) -> str | None:
    normalized_level = " ".join(level.split())
    normalized_years = " ".join(years.split())
    if normalized_level == "무관" and normalized_years == "미정":
        return None
    if normalized_level == "무관":
        return normalized_years
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
        "candidate_panel_open": False,
        "download_report_html": "",
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
    st.session_state.candidate_panel_open = False
    st.session_state.download_report_html = ""


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


def _interview_html(questions: list[str], answer_frames: list[str]) -> str:
    if not questions:
        return "<p class='report-empty'>아직 생성된 내용이 없습니다.</p>"

    blocks: list[str] = []
    for index, question in enumerate(questions, start=1):
        guide = answer_frames[index - 1] if index - 1 < len(answer_frames) else ""
        blocks.append(
            dedent(
                f"""
                <div class="report-interview-item">
                    <h3>Q{index}. {html.escape(question)}</h3>
                    <p>{html.escape(guide or '답변 가이드가 아직 없습니다.')}</p>
                </div>
                """
            ).strip()
        )
    return "".join(blocks)


def _safe_slug(value: str) -> str:
    compact = "".join(char.lower() if char.isalnum() else "-" for char in value)
    slug = "-".join(segment for segment in compact.split("-") if segment)
    return slug[:60] or "job-coach-report"


def _build_download_report_html(
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

    return dedent(
        f"""
        <!doctype html>
        <html lang="ko">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>{html.escape(title)} · Job Coach Report</title>
          <style>
            body {{ margin: 0; padding: 40px 28px; background: linear-gradient(180deg, #eef5ff 0%, #f7fbff 100%); color: #18344d; font-family: "Pretendard", "Noto Sans KR", "Apple SD Gothic Neo", "Segoe UI", sans-serif; }}
            .report {{ max-width: 960px; margin: 0 auto; }}
            .hero, .section {{ background: rgba(255, 255, 255, 0.92); border: 1px solid rgba(87, 123, 163, 0.18); border-radius: 24px; box-shadow: 0 18px 40px rgba(34, 70, 118, 0.10); padding: 24px 28px; margin-bottom: 20px; }}
            .eyebrow {{ color: #4f6f91; font-size: 13px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 10px; }}
            h1 {{ margin: 0 0 10px 0; font-size: 30px; line-height: 1.25; }}
            h2 {{ margin: 0 0 12px 0; font-size: 22px; color: #21527d; }}
            h3 {{ margin: 0 0 8px 0; font-size: 16px; color: #21527d; }}
            p, li {{ font-size: 15px; line-height: 1.7; }}
            ul, ol {{ margin: 0; padding-left: 22px; }}
            .meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }}
            .pill {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 6px 12px; font-size: 13px; font-weight: 600; background: #eef5ff; color: #335679; }}
            .report-empty {{ color: #6a8098; font-style: italic; }}
            .report-interview-item {{ padding: 14px 16px; border-radius: 18px; border: 1px solid rgba(87, 123, 163, 0.16); background: #f8fbff; margin-bottom: 12px; }}
            a {{ color: #1d64b0; }}
          </style>
        </head>
        <body>
          <div class="report">
            <section class="hero">
              <div class="eyebrow">Job Coach Report</div>
              <h1>{html.escape(title)}</h1>
              <p>{html.escape(str(target.get("summary", "선택한 지원 대상 정보가 없습니다.")))}</p>
              <div class="meta">
                <span class="pill">탐색 기준 · {html.escape(_search_summary_line())}</span>
                <span class="pill">출처 · {html.escape(source_label)}</span>
                <span class="pill">링크 · {html.escape(source_url or '없음')}</span>
              </div>
            </section>
            <section class="section">
              <h2>분석 리포트</h2>
              {_paragraphs_html(str(prepare_summary.get("preparation_summary", "")))}
              <h3>준비 포인트</h3>
              {_list_html(list(prepare_summary.get("preparation_points", [])))}
              <h3>보완 포인트</h3>
              {_list_html(list(prepare_summary.get("skill_gaps", [])))}
            </section>
            <section class="section">
              <h2>자소서 초안</h2>
              {_paragraphs_html(str(artifacts.get("self_intro_draft", "")))}
            </section>
            <section class="section">
              <h2>합격 로드맵</h2>
              {_list_html(list(artifacts.get("action_items", [])), numbered=True)}
            </section>
            <section class="section">
              <h2>면접 대비</h2>
              {_interview_html(list(artifacts.get("interview_questions", [])), list(artifacts.get("answer_frames", [])))}
            </section>
          </div>
        </body>
        </html>
        """
    ).strip()


def _generate_dashboard_outputs(selected_target: dict[str, Any] | None, *, spinner_text: str) -> None:
    if selected_target is None:
        st.session_state.prepare_summary_result = None
        st.session_state.prep_artifacts_result = None
        st.session_state.download_report_html = ""
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
    st.session_state.download_report_html = ""
    if prepare_summary:
        st.session_state.download_report_html = _build_download_report_html(selected_target, prepare_summary, prep_artifacts)


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
        st.session_state.candidate_panel_open = False
        st.session_state.download_report_html = ""

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
                    <div class="result-card__body">{html.escape(str(item))}</div>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )


def _parse_gap_item(text: str) -> tuple[str, str]:
    weakness = ""
    compensation = ""
    for raw_line in str(text).splitlines():
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
    return weakness, compensation


def _render_gap_list(title: str, values: list[str]) -> None:
    st.markdown(f"### {title}")
    if not values:
        st.info("아직 내용이 없습니다.")
        return

    for item in values:
        weakness, compensation = _parse_gap_item(item)
        st.markdown(
            dedent(
                f"""
                <div class="result-card result-card--warning">
                    <div class="result-card__eyebrow">보완 포인트</div>
                    <div class="result-card__body">{html.escape(weakness or str(item))}</div>
                    <div class="result-card__eyebrow result-card__eyebrow--spaced">보완 방법</div>
                    <div class="result-card__body">{html.escape(compensation or '추가 보완 계획을 구체화해 주세요.')}</div>
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
                    <div class="result-card__body">{html.escape(str(item))}</div>
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
        guide = answer_guides[index - 1] if index - 1 < len(answer_guides) else "답변 가이드가 아직 없습니다."
        st.markdown(
            dedent(
                f"""
                <div class="interview-card">
                    <div class="interview-card__question">Q{index}. {html.escape(question)}</div>
                    <div class="interview-card__answer">{html.escape(guide)}</div>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )


def _render_self_intro_draft(text: str) -> None:
    paragraphs = [" ".join(paragraph.split()) for paragraph in str(text).split("\n\n")]
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
        return

    _sync_coach_chat_history(run_id)

    with st.expander("준비 코치에게 이어서 물어보기", expanded=False):
        st.caption("현재 생성된 분석 리포트, 자소서 초안, 로드맵, 면접 질문을 바탕으로 이어서 질문할 수 있습니다.")

        history = st.session_state.coach_chat_history
        if not history:
            st.info("예: 이 공고 기준으로 제 강점을 어떻게 말하면 좋을까요?")

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
                    st.warning(warning)
                st.session_state.coach_chat_run_id = run_id
                st.session_state.coach_chat_history = result.get("messages", [])
                st.rerun()


def _render_source_cards(source_cards: list[dict[str, Any]]) -> None:
    with st.expander("탐색 근거 및 참고 정보", expanded=False):
        for card in source_cards:
            board_label = job_board_label_for_url(str(card.get("url", "")))
            st.markdown(f"**[{board_label}] {card['title']}**")
            st.caption(f"{card['source_type']} · 신뢰도 {card['confidence']:.2f} · {card['url']}")
            st.write(card["claim"])
            st.divider()


def _render_supporting_company_cards(company_candidates: list[dict[str, Any]]) -> None:
    if not company_candidates:
        return

    with st.expander("참고용 회사 정보", expanded=False):
        for candidate in company_candidates:
            st.markdown(f"**{candidate['name']}**")
            st.caption(candidate["source_url"])
            st.write(candidate["summary"])
            st.divider()


def _render_candidate_grid(candidates: list[dict[str, Any]]) -> bool:
    key_prefix = str((st.session_state.explore_result or {}).get("run_id", "adhoc"))
    page_candidates, page_index, total_pages, start_index = _candidate_page_info(
        candidates,
        st.session_state.candidate_page_index,
    )
    st.session_state.candidate_page_index = page_index

    selection_changed = False
    new_selection_index = st.session_state.selected_target_index

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
                    if global_index != st.session_state.selected_target_index:
                        new_selection_index = global_index
                        selection_changed = True

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

    if selection_changed:
        st.session_state.selected_target_index = new_selection_index
    return selection_changed


def _inject_styles() -> None:
    st.markdown(
        dedent(
            """
            <style>
            @import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css");

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

            .stApp, .stApp * {
                font-family: "Pretendard", "Noto Sans KR", "Apple SD Gothic Neo", "Segoe UI", sans-serif;
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
            .self-intro-card {
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
    saved_preferences, saved_custom_preferences = _split_preferences(saved_payload["preferences"])

    with st.form("explore_form", clear_on_submit=False):
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
                options=list(EXPERIENCE_LEVEL_OPTIONS),
                index=_option_index(list(EXPERIENCE_LEVEL_OPTIONS), saved_payload["experience_level"], EXPERIENCE_LEVEL_OPTIONS[0]),
                horizontal=True,
            )
        with col5:
            experience_years = st.selectbox(
                "연차 (Years)",
                options=list(YEARS_OPTIONS),
                index=_option_index(list(YEARS_OPTIONS), saved_payload["experience_years"], YEARS_OPTIONS[0]),
            )

        selected_preferences = st.multiselect("선호 조건", options=list(PREFERENCE_OPTIONS), default=saved_preferences)
        custom_preferences = st.text_input(
            "추가 선호 조건",
            value=saved_custom_preferences,
            placeholder="예: 수도권, 정규직, B2B SaaS, 데이터 중심 문화",
        )
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

        submitted = st.form_submit_button("🚀 지원 대상 후보 탐색 및 전략 생성", use_container_width=True)

    if submitted:
        missing_fields = [label for label, value in [("산업", industry), ("직군", job_family), ("직무", job_role)] if not value]
        if missing_fields:
            st.error(f"다음 항목을 먼저 입력해 주세요: {', '.join(missing_fields)}")
            return

        normalized_experience_level = _format_experience_level(experience_level, experience_years)
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
            "experience_years": experience_years,
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
        st.warning(note)

    explore_result, primary_candidates, company_candidates, primary_source, primary_label, selected_target = _current_candidate_context()
    if not primary_candidates or selected_target is None:
        st.info("조건에 맞는 지원 후보를 찾지 못했습니다. 입력 조건을 조금 넓혀 다시 시도해 보세요.")
        _render_source_cards(explore_result.get("source_cards", []))
        return

    selected_title = _clean_candidate_title(selected_target)
    selected_summary = _truncate_text(str(selected_target.get("summary", "")), 230)
    board_label = job_board_label_for_url(str(selected_target.get("source_url", "")))
    confidence = _candidate_confidence(selected_target)
    query_text = " / ".join(explore_result.get("queries", []))

    st.markdown(
        dedent(
            f"""
            <div class="summary-hero">
                <div class="result-card__eyebrow">Current Target</div>
                <div class="summary-hero__title">{html.escape(selected_title)}</div>
                <div class="summary-hero__copy">{html.escape(selected_summary)}</div>
                <div class="summary-hero__meta">
                    <span class="summary-pill">자동 선택된 1순위 후보</span>
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
            data=st.session_state.download_report_html or "",
            file_name=f"{_safe_slug(selected_title)}-report.html",
            mime="text/html",
            use_container_width=True,
            disabled=not bool(st.session_state.download_report_html),
        )

    st.markdown("<div class='dashboard-note'>지원 대상 변경 패널에서 다른 후보를 누르면 해당 후보 기준으로 결과를 다시 생성합니다.</div>", unsafe_allow_html=True)

    if st.session_state.candidate_panel_open:
        st.markdown(
            dedent(
                """
                <div class="section-title">
                    <div class="section-title__eyebrow">Selection Panel</div>
                    <div class="section-title__label">지원 대상 변경</div>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )
        selection_changed = _render_candidate_grid(primary_candidates)
        if selection_changed:
            _, primary_candidates, _, _, _, updated_target = _current_candidate_context()
            st.session_state.candidate_panel_open = False
            _generate_dashboard_outputs(updated_target, spinner_text="선택한 지원 대상으로 결과를 다시 만들고 있습니다...")
            st.rerun()

    _render_supporting_company_cards(company_candidates)
    _render_source_cards(explore_result.get("source_cards", []))

    prepare_summary = st.session_state.prepare_summary_result or {}
    prep_artifacts = st.session_state.prep_artifacts_result or {}

    for warning in prepare_summary.get("warnings", []):
        st.warning(warning)
    for warning in prep_artifacts.get("warnings", []):
        st.warning(warning)

    st.markdown("<div class='dashboard-segment-label'>Dashboard Results</div>", unsafe_allow_html=True)
    active_tab = st.radio(
        "결과 보기",
        options=list(RESULT_TABS),
        horizontal=True,
        label_visibility="collapsed",
        key="dashboard_active_tab",
    )

    if active_tab == "분석 리포트":
        st.markdown("## 오늘의 분석 리포트")
        st.markdown(prepare_summary.get("preparation_summary", "아직 분석 리포트가 없습니다."))
        col1, col2 = st.columns(2)
        with col1:
            _render_preparation_card_list("준비 포인트", prepare_summary.get("preparation_points", []))
        with col2:
            _render_gap_list("보완 포인트", prepare_summary.get("skill_gaps", []))
    elif active_tab == "자소서 초안":
        st.markdown("## 자소서 초안")
        _render_self_intro_draft(str(prep_artifacts.get("self_intro_draft", "")))
    elif active_tab == "면접 대비":
        st.markdown("## 면접 대비")
        _render_interview_guides(
            list(prep_artifacts.get("interview_questions", [])),
            list(prep_artifacts.get("answer_frames", [])),
        )
    else:
        st.markdown("## 오늘의 합격 로드맵")
        _render_action_items(list(prep_artifacts.get("action_items", [])))

    _render_coach_chat_section(_current_run_id(), selected_target)


def main() -> None:
    _init_state()
    _inject_styles()
    _render_header()
    _render_input_stage()
    _render_dashboard_results()


if __name__ == "__main__":
    main()
