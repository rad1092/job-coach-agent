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
    CORE_JOB_BOARD_DOMAINS,
    CUSTOM_OPTION,
    EXPERIENCE_LEVEL_OPTIONS,
    EXTENDED_JOB_BOARD_DOMAINS,
    PREFERENCE_OPTIONS,
    industry_options,
    job_board_label_for_url,
    job_families_for_industry,
    job_roles_for_family,
)

st.set_page_config(
    page_title="취업 코치형 에이전트",
    page_icon=":briefcase:",
    layout="wide",
)

SETTINGS = get_settings()
BACKEND_BASE_URL = SETTINGS.backend_base_url.rstrip("/")
REQUEST_TIMEOUT = 60.0
CANDIDATES_PER_PAGE = 9
MAX_VISIBLE_CANDIDATES = 27
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
        summary=_truncate_text(str(candidate.get("summary", "")), 120),
        why_relevant=_truncate_text(str(candidate.get("why_relevant", "")), 110),
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
            "experience_level": "",
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
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_flow() -> None:
    for key in [
        "explore_result",
        "candidate_click_ts",
        "selected_target_index",
        "selected_target_source",
        "candidate_page_index",
        "prepare_summary_result",
        "prep_artifacts_result",
        "coach_chat_history",
        "coach_chat_run_id",
    ]:
        if key.endswith("_index"):
            st.session_state[key] = 0
        elif key == "candidate_click_ts":
            st.session_state[key] = 0.0
        elif key == "coach_chat_history":
            st.session_state[key] = []
        elif key == "coach_chat_run_id":
            st.session_state[key] = ""
        elif key == "selected_target_source":
            st.session_state[key] = "posting"
        else:
            st.session_state[key] = None


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


def _render_string_list(title: str, values: list[str]) -> None:
    st.markdown(f"#### {title}")
    if not values:
        st.write("아직 내용이 없습니다.")
        return
    for item in values:
        st.markdown(f"- {item}")


def _render_preparation_card_list(title: str, values: list[str]) -> None:
    st.markdown(f"#### {title}")
    if not values:
        st.write("아직 내용이 없습니다.")
        return

    for index, item in enumerate(values, start=1):
        st.markdown(
            dedent(
                f"""
                <div class="prep-card">
                    <div class="prep-label">준비 포인트 {index:02d}</div>
                    <div class="prep-body">{html.escape(str(item))}</div>
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
    st.markdown(f"#### {title}")
    if not values:
        st.write("아직 내용이 없습니다.")
        return

    for item in values:
        weakness, compensation = _parse_gap_item(item)
        if weakness or compensation:
            st.markdown(
                dedent(
                    f"""
                    <div class="gap-card">
                        <div class="gap-label">보완 포인트</div>
                        <div class="gap-body">{html.escape(weakness or '확인 필요')}</div>
                        <div class="gap-label">보완 방법</div>
                        <div class="gap-body">{html.escape(compensation or '추가 보완 계획을 정리해 주세요.')}</div>
                    </div>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"- {item}")


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

    st.markdown("## 4단계. 준비 코치에게 질문하기")
    st.caption("지금까지 생성된 요약, 준비 포인트, 보완 포인트, 실행 항목, 면접 질문을 바탕으로 질문에 답해드립니다.")

    history = st.session_state.coach_chat_history
    if not history:
        st.info("예: 이 공고 기준으로 지원 동기를 어떻게 말하면 좋을까요?, 예상 꼬리 질문은 무엇일까요?")

    for message in history:
        role = "assistant" if message.get("role") == "assistant" else "user"
        with st.chat_message(role):
            st.markdown(message.get("content", ""))
            preparation_tips = message.get("preparation_tips", [])
            suggested_questions = message.get("suggested_questions", [])
            if role == "assistant" and preparation_tips:
                st.markdown("**준비 팁**")
                for item in preparation_tips:
                    st.markdown(f"- {item}")
            if role == "assistant" and suggested_questions:
                st.markdown("**다음에 물어보면 좋은 질문**")
                for item in suggested_questions:
                    st.markdown(f"- {item}")

    with st.form("coach_chat_form", clear_on_submit=True):
        question = st.text_input(
            "준비 코치에게 질문",
            placeholder="예: 이 공고 기준으로 제 강점을 어떻게 말하면 좋을까요?",
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
        with st.spinner("준비 코치가 질문을 정리하고 있습니다..."):
            result = _call_api("/coach-chat", payload)
        if result:
            for warning in result.get("warnings", []):
                st.warning(warning)
            st.session_state.coach_chat_run_id = run_id
            st.session_state.coach_chat_history = result.get("messages", [])
            st.rerun()


def _render_interview_guides(questions: list[str], answer_guides: list[str]) -> None:
    st.markdown("#### 예상 면접 질문과 답변 가이드")
    if not questions:
        st.write("아직 준비된 질문이 없습니다.")
        return

    for index, question in enumerate(questions, start=1):
        st.markdown(f"**Q{index}. {question}**")
        if index - 1 < len(answer_guides):
            st.markdown(f"- 답변 가이드: {answer_guides[index - 1]}")
        st.divider()


def _render_source_cards(source_cards: list[dict[str, Any]]) -> None:
    with st.expander("탐색 근거 및 참고 정보", expanded=False):
        for card in source_cards:
            board_label = job_board_label_for_url(str(card.get("url", "")))
            st.markdown(f"**[{board_label}] {card['title']}**")
            st.caption(f"{card['source_type']} | 신뢰도 {card['confidence']:.2f} | {card['url']}")
            st.write(card["claim"])
            st.divider()


def _primary_candidates(explore_result: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
    posting_candidates = explore_result.get("posting_candidates", [])
    if posting_candidates:
        return posting_candidates, "posting", "채용공고"
    company_candidates = explore_result.get("company_candidates", [])
    return company_candidates, "company", "회사"


def _render_supporting_company_cards(company_candidates: list[dict[str, Any]]) -> None:
    if not company_candidates:
        return

    with st.expander("참고용 회사 정보", expanded=False):
        for candidate in company_candidates:
            st.markdown(f"**{candidate['name']}**")
            st.caption(candidate["source_url"])
            st.write(candidate["summary"])
            st.divider()


def _render_candidate_grid(candidates: list[dict[str, Any]]) -> None:
    key_prefix = str((st.session_state.explore_result or {}).get("run_id", "adhoc"))
    page_candidates, page_index, total_pages, start_index = _candidate_page_info(
        candidates,
        st.session_state.candidate_page_index,
    )
    st.session_state.candidate_page_index = page_index

    for row_start in range(0, len(page_candidates), 3):
        columns = st.columns(3)
        for offset, column in enumerate(columns):
            local_index = row_start + offset
            if local_index >= len(page_candidates):
                continue

            global_index = start_index + local_index
            candidate = dict(page_candidates[local_index])
            is_selected = global_index == st.session_state.selected_target_index
            candidate["_selected"] = is_selected

            with column:
                click_ts = _render_candidate_card_component(candidate, global_index + 1, global_index, key_prefix)
                if click_ts > st.session_state.get("candidate_click_ts", 0.0):
                    st.session_state.candidate_click_ts = click_ts
                    st.session_state.selected_target_index = global_index
                    st.rerun()

    footer_left, footer_center, footer_right = st.columns([1, 2.2, 1])
    with footer_left:
        if st.button("❮", key="candidate_page_prev", disabled=page_index == 0, use_container_width=True, help="이전 9개"):
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
        if st.button("❯", key="candidate_page_next", disabled=page_index >= total_pages - 1, use_container_width=True, help="다음 9개"):
            st.session_state.candidate_page_index = min(page_index + 1, total_pages - 1)
            st.rerun()


def _inject_styles() -> None:
    st.markdown(
        dedent(
            """
            <style>
            .stApp {
                background:
                    radial-gradient(circle at top left, #fff2df 0%, transparent 35%),
                    linear-gradient(180deg, #f6f1e7 0%, #fbfaf6 45%, #f0f4f2 100%);
            }
            .block-container {
                max-width: 1160px;
                padding-top: 2rem;
                padding-bottom: 3rem;
            }
            .hero-card, .candidate-card {
                border: 1px solid rgba(27, 55, 34, 0.12);
                border-radius: 20px;
                background: rgba(255, 255, 255, 0.86);
                box-shadow: 0 18px 40px rgba(38, 52, 37, 0.08);
                backdrop-filter: blur(8px);
            }
            .hero-card {
                padding: 1.5rem 1.6rem;
                margin-bottom: 1.25rem;
            }
            .candidate-card {
                padding: 1rem 1.1rem;
                margin: 0.4rem 0 0.65rem 0;
            }
            .candidate-grid-card {
                aspect-ratio: 1 / 1;
                min-height: 20rem;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }
            .candidate-grid-card.is-selected {
                background: linear-gradient(180deg, rgba(227, 239, 255, 0.98) 0%, rgba(208, 228, 255, 0.92) 100%);
                border: 1.5px solid rgba(50, 108, 197, 0.42);
                box-shadow: 0 20px 44px rgba(64, 119, 198, 0.18);
            }
            .eyebrow {
                letter-spacing: 0.08em;
                text-transform: uppercase;
                font-size: 0.8rem;
                color: #5a6b5f;
                margin-bottom: 0.35rem;
            }
            .hero-title {
                font-size: 2rem;
                line-height: 1.15;
                font-weight: 700;
                color: #193022;
                margin-bottom: 0.65rem;
            }
            .hero-copy {
                color: #36463e;
                line-height: 1.6;
            }
            .candidate-meta-row,
            .candidate-grid-meta {
                display: flex;
                gap: 0.6rem;
                align-items: center;
                flex-wrap: wrap;
                margin-bottom: 0.55rem;
            }
            .candidate-badge {
                display: inline-block;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                background: #e6efe8;
                color: #20442d;
                font-weight: 700;
                font-size: 0.78rem;
            }
            .candidate-selected-badge {
                display: inline-block;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                background: #2f6fd6;
                color: #ffffff;
                font-weight: 700;
                font-size: 0.76rem;
            }
            .candidate-rank,
            .candidate-url,
            .candidate-grid-confidence {
                color: #66756b;
                font-size: 0.82rem;
            }
            .candidate-title,
            .candidate-grid-title {
                color: #193022;
                font-size: 1.12rem;
                font-weight: 700;
                margin-bottom: 0.45rem;
                line-height: 1.35;
            }
            .candidate-title a,
            .candidate-grid-title a {
                color: inherit;
                text-decoration: none;
            }
            .candidate-title a:hover,
            .candidate-grid-title a:hover {
                text-decoration: underline;
            }
            .candidate-summary,
            .candidate-grid-copy {
                color: #36463e;
                line-height: 1.55;
                margin-bottom: 0.5rem;
            }
            .candidate-grid-copy {
                display: -webkit-box;
                -webkit-line-clamp: 4;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }
            .candidate-reason,
            .candidate-grid-reason {
                color: #5d6c62;
                font-size: 0.92rem;
                line-height: 1.5;
            }
            .candidate-grid-reason {
                display: -webkit-box;
                -webkit-line-clamp: 3;
                -webkit-box-orient: vertical;
                overflow: hidden;
                margin-top: auto;
            }
            .candidate-grid-pagination {
                margin-top: 0.55rem;
                padding: 0.8rem 1rem;
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.75);
                border: 1px solid rgba(27, 55, 34, 0.12);
                color: #4a5e54;
                font-size: 0.92rem;
                text-align: center;
            }
            .prep-card {
                border: 1px solid rgba(27, 55, 34, 0.1);
                border-radius: 18px;
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.92) 0%, rgba(243, 247, 244, 0.92) 100%);
                box-shadow: 0 14px 30px rgba(38, 52, 37, 0.06);
                padding: 1rem 1.05rem;
                margin-bottom: 0.85rem;
            }
            .prep-label {
                font-size: 0.8rem;
                font-weight: 700;
                color: #4d5f55;
                letter-spacing: 0.02em;
                margin-bottom: 0.28rem;
            }
            .prep-body {
                color: #26362d;
                line-height: 1.6;
            }
            .gap-card {
                border: 1px solid rgba(27, 55, 34, 0.1);
                border-radius: 18px;
                background: rgba(255, 255, 255, 0.82);
                box-shadow: 0 14px 30px rgba(38, 52, 37, 0.06);
                padding: 1rem 1.05rem;
                margin-bottom: 0.85rem;
            }
            .gap-label {
                font-size: 0.8rem;
                font-weight: 700;
                color: #4d5f55;
                letter-spacing: 0.02em;
                margin-bottom: 0.28rem;
            }
            .gap-body {
                color: #26362d;
                line-height: 1.6;
                margin-bottom: 0.8rem;
            }
            .gap-card .gap-body:last-child {
                margin-bottom: 0;
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
            <div class="hero-card">
                <div class="eyebrow">Job Coach Runtime</div>
                <div class="hero-title">희망 산업·직군·직무에서 지원 준비 흐름까지</div>
                <div class="hero-copy">
                    입력한 목표를 기준으로 관련 채용공고를 찾고, 지원 준비 요약과 실행 항목,
                    예상 면접 질문까지 한 번에 정리합니다.
                </div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 실행 환경")
        st.write(f"- 백엔드: `{BACKEND_BASE_URL}`")
        st.write(f"- 검색: `{SETTINGS.search_provider}`")
        st.write(f"- 생성: `{SETTINGS.llm_provider}` / `{SETTINGS.openai_model}`")
        st.write("- 핵심 채용 보드: " + " / ".join(job_board_label_for_url(f"https://{domain}") for domain in CORE_JOB_BOARD_DOMAINS))
        st.write("- 확장 채용 보드: " + " / ".join(job_board_label_for_url(f"https://{domain}") for domain in EXTENDED_JOB_BOARD_DOMAINS))
        if st.button("현재 흐름 초기화", use_container_width=True):
            _reset_flow()
            st.rerun()


def _render_input_stage() -> None:
    st.markdown("## 1단계. 목표 입력")
    saved_payload = st.session_state.input_payload
    saved_preferences, saved_custom_preferences = _split_preferences(saved_payload["preferences"])

    with st.form("explore_form", clear_on_submit=False):
        st.caption("대형 채용 사이트를 먼저 탐색하고, 결과가 부족하면 확장 보드까지 넓혀서 공고를 찾습니다.")

        industry_base_options = industry_options()
        industry_options_with_custom = [*industry_base_options, CUSTOM_OPTION]

        col1, col2, col3 = st.columns(3)
        with col1:
            selected_industry = st.selectbox(
                "산업",
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
                "직군",
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
                "직무",
                options=role_options_with_custom,
                index=_option_index(role_options_with_custom, saved_payload["job_role"], role_base_options[0]),
            )
            custom_job_role = ""
            if selected_job_role == CUSTOM_OPTION:
                custom_job_role = st.text_input("직무 직접 입력", value=_custom_value(saved_payload["job_role"], role_base_options))
            job_role = _resolve_selected_value(selected_job_role, custom_job_role)

        col4, col5 = st.columns(2)
        with col4:
            experience_level = st.selectbox(
                "경력 수준",
                options=list(EXPERIENCE_LEVEL_OPTIONS),
                index=_option_index(list(EXPERIENCE_LEVEL_OPTIONS), saved_payload["experience_level"], EXPERIENCE_LEVEL_OPTIONS[0]),
            )
        with col5:
            selected_preferences = st.multiselect("선호 조건", options=list(PREFERENCE_OPTIONS), default=saved_preferences)
            custom_preferences = st.text_input(
                "추가 선호 조건",
                value=saved_custom_preferences,
                placeholder="예: B2B SaaS, 데이터 파이프라인, 글로벌 협업",
            )
            preferences = _join_preferences(selected_preferences, custom_preferences)

        user_background = st.text_area(
            "사용자 배경",
            value=saved_payload["user_background"],
            placeholder="프로젝트 경험, 강점, 보완하고 싶은 부분을 적어두면 이후 요약과 면접 준비에 반영됩니다.",
            height=120,
        )
        notes = st.text_area(
            "메모",
            value=saved_payload["notes"],
            placeholder="이번 탐색에서 특히 보고 싶은 기업 조건이나 메모를 적어두세요.",
            height=100,
        )

        submitted = st.form_submit_button("지원 후보 정보 탐색", use_container_width=True)

    if submitted:
        missing_fields = [label for label, value in [("산업", industry), ("직군", job_family), ("직무", job_role)] if not value]
        if missing_fields:
            st.error(f"다음 항목을 먼저 선택하거나 입력해 주세요: {', '.join(missing_fields)}")
            return

        normalized_experience_level = None if experience_level == "무관" else experience_level
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
            "experience_level": normalized_experience_level or "",
            "preferences": normalized_preferences or "",
            "user_background": user_background,
            "notes": notes,
        }
        st.session_state.prepare_summary_result = None
        st.session_state.prep_artifacts_result = None
        st.session_state.coach_chat_history = []
        st.session_state.coach_chat_run_id = ""
        st.session_state.candidate_click_ts = 0.0
        st.session_state.selected_target_index = 0
        st.session_state.selected_target_source = "posting"
        st.session_state.candidate_page_index = 0
        with st.spinner("관련 채용공고와 참고 정보를 탐색하고 있습니다..."):
            result = _call_api("/explore", payload)
        if result:
            st.session_state.explore_result = result
            st.rerun()


def _render_explore_stage() -> None:
    explore_result = st.session_state.explore_result
    if not explore_result:
        return

    st.markdown("## 2단계. 지원 후보 탐색")
    if explore_result.get("notes"):
        for note in explore_result["notes"]:
            st.warning(note)

    query_text = " / ".join(explore_result.get("queries", []))
    if query_text:
        st.caption(f"탐색 쿼리: {query_text}")

    company_candidates = explore_result.get("company_candidates", [])
    primary_candidates, primary_source, primary_label = _primary_candidates(explore_result)

    if st.session_state.selected_target_source != primary_source:
        st.session_state.selected_target_source = primary_source
        st.session_state.candidate_click_ts = 0.0
        st.session_state.selected_target_index = 0
        st.session_state.candidate_page_index = 0

    if not primary_candidates:
        st.warning("선택 가능한 지원 후보가 아직 없습니다. 입력 조건을 조정한 뒤 다시 탐색해 보세요.")
        _render_source_cards(explore_result.get("source_cards", []))
        return

    _sync_candidate_state(primary_candidates)

    candidate_count = len(primary_candidates)
    visible_count = min(candidate_count, MAX_VISIBLE_CANDIDATES)
    st.markdown(f"### {primary_label} 기반 지원 후보")
    st.caption(f"신뢰도 높은 순으로 최대 {visible_count}건을 보여주며, 한 페이지에 9건씩 3x3 형태로 확인할 수 있습니다.")
    selected_target = _selected_candidate_from_index(primary_candidates, st.session_state.selected_target_index)
    if selected_target:
        st.caption(f"현재 선택 공고: {_clean_candidate_title(selected_target)}")
    if primary_source == "company":
        st.caption("공고 후보가 충분하지 않아 회사 중심 후보를 우선 보여주고 있습니다.")

    _render_candidate_grid(primary_candidates)

    if primary_source == "posting":
        _render_supporting_company_cards(company_candidates)
    _render_source_cards(explore_result.get("source_cards", []))

    if st.button("지원 준비 요약서 만들기", use_container_width=True):
        payload = {
            "run_id": explore_result.get("run_id"),
            "selected_target": _build_selected_candidate(selected_target),
            "user_background": st.session_state.input_payload.get("user_background") or None,
            "notes": st.session_state.input_payload.get("notes") or None,
        }
        with st.spinner("지원 준비 요약서를 정리하고 있습니다..."):
            result = _call_api("/prepare-summary", payload)
        if result:
            st.session_state.prepare_summary_result = result
            st.session_state.prep_artifacts_result = None
            st.rerun()


def _render_result_stage() -> None:
    prepare_summary = st.session_state.prepare_summary_result
    if not prepare_summary:
        return

    st.markdown("## 3단계. 지원 준비 결과")
    for warning in prepare_summary.get("warnings", []):
        st.warning(warning)

    st.markdown("### 지원 준비 요약")
    st.markdown(prepare_summary.get("preparation_summary", ""))

    col1, col2 = st.columns(2)
    with col1:
        _render_preparation_card_list("준비 포인트", prepare_summary.get("preparation_points", []))
    with col2:
        _render_gap_list("보완이 필요한 부분", prepare_summary.get("skill_gaps", []))

    if st.button("실행 항목과 면접 준비 자료 만들기", use_container_width=True):
        explore_result = st.session_state.explore_result or {}
        primary_candidates, _, _ = _primary_candidates(explore_result)
        selected_target = _selected_candidate_from_index(primary_candidates, st.session_state.selected_target_index)
        payload = {
            "run_id": prepare_summary.get("run_id") or explore_result.get("run_id"),
            "selected_target": _build_selected_candidate(selected_target),
            "preparation_summary": prepare_summary.get("preparation_summary", ""),
            "user_background": st.session_state.input_payload.get("user_background") or None,
            "notes": st.session_state.input_payload.get("notes") or None,
        }
        with st.spinner("실행 항목과 면접 자료를 만들고 있습니다..."):
            result = _call_api("/prep-artifacts", payload)
        if result:
            st.session_state.prep_artifacts_result = result
            st.rerun()

    explore_result = st.session_state.explore_result or {}
    primary_candidates, _, _ = _primary_candidates(explore_result)
    selected_target = _selected_candidate_from_index(primary_candidates, st.session_state.selected_target_index)

    artifacts = st.session_state.prep_artifacts_result
    if not artifacts:
        _render_coach_chat_section(_current_run_id(), selected_target)
        return

    for warning in artifacts.get("warnings", []):
        st.warning(warning)

    left, right = st.columns(2)
    with left:
        _render_string_list("실행 항목", artifacts.get("action_items", []))
    with right:
        _render_interview_guides(
            artifacts.get("interview_questions", []),
            artifacts.get("answer_frames", []),
        )

    _render_coach_chat_section(_current_run_id(), selected_target)


def main() -> None:
    _init_state()
    _inject_styles()
    _render_sidebar()
    _render_header()
    _render_input_stage()
    _render_explore_stage()
    _render_result_stage()


if __name__ == "__main__":
    main()
