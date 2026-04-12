from __future__ import annotations

from typing import Any

import httpx
import streamlit as st

from backend.app.core.settings import get_settings
from backend.app.core.taxonomy import (
    CUSTOM_JOB_ROLE,
    EXPERIENCE_LEVELS,
    INDUSTRIES,
    JOB_FAMILIES,
    PREFERENCE_TAGS,
    UNDECIDED_JOB_ROLE,
    build_preferences_text,
    compact_text,
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


def _blank_draft_input() -> dict[str, Any]:
    return {
        "industry": None,
        "job_family": None,
        "job_role_select": None,
        "custom_job_role": "",
        "experience_level": None,
        "preference_tags": [],
        "preference_note": "",
        "user_background": "",
        "notes": "",
    }


def _widget_state_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "draft_industry": draft.get("industry"),
        "draft_job_family": draft.get("job_family"),
        "draft_job_role_select": draft.get("job_role_select"),
        "draft_custom_job_role": draft.get("custom_job_role", ""),
        "draft_experience_level": draft.get("experience_level"),
        "draft_preference_tags": list(draft.get("preference_tags", [])),
        "draft_preference_note": draft.get("preference_note", ""),
        "draft_user_background": draft.get("user_background", ""),
        "draft_notes": draft.get("notes", ""),
    }


def _set_widget_state_from_draft(draft: dict[str, Any]) -> None:
    for key, value in _widget_state_from_draft(draft).items():
        st.session_state[key] = value


def _capture_draft_input() -> dict[str, Any]:
    return {
        "industry": st.session_state.get("draft_industry"),
        "job_family": st.session_state.get("draft_job_family"),
        "job_role_select": st.session_state.get("draft_job_role_select"),
        "custom_job_role": st.session_state.get("draft_custom_job_role", ""),
        "experience_level": st.session_state.get("draft_experience_level"),
        "preference_tags": list(st.session_state.get("draft_preference_tags", [])),
        "preference_note": st.session_state.get("draft_preference_note", ""),
        "user_background": st.session_state.get("draft_user_background", ""),
        "notes": st.session_state.get("draft_notes", ""),
    }


def _sync_draft_state() -> None:
    st.session_state["draft_input"] = _capture_draft_input()


def _init_state() -> None:
    st.session_state.setdefault("draft_input", _blank_draft_input())
    st.session_state.setdefault("submitted_input", None)
    st.session_state.setdefault("explore_result", None)
    st.session_state.setdefault("selected_target_index", 0)
    st.session_state.setdefault("selected_target_source", "posting")
    st.session_state.setdefault("prepare_summary_result", None)
    st.session_state.setdefault("prep_artifacts_result", None)

    for key, value in _widget_state_from_draft(st.session_state["draft_input"]).items():
        st.session_state.setdefault(key, value)


def _clear_selection_state() -> None:
    st.session_state["selected_target_index"] = 0
    st.session_state["selected_target_source"] = "posting"


def _clear_explore_outputs(clear_submitted: bool = True) -> None:
    if clear_submitted:
        st.session_state["submitted_input"] = None
    st.session_state["explore_result"] = None
    st.session_state["prepare_summary_result"] = None
    st.session_state["prep_artifacts_result"] = None
    _clear_selection_state()


def _clear_summary_outputs() -> None:
    st.session_state["prepare_summary_result"] = None
    st.session_state["prep_artifacts_result"] = None


def _reset_all_state() -> None:
    blank = _blank_draft_input()
    st.session_state["draft_input"] = blank
    st.session_state["submitted_input"] = None
    _set_widget_state_from_draft(blank)
    _clear_explore_outputs()


def _on_industry_change() -> None:
    st.session_state["draft_job_family"] = None
    st.session_state["draft_job_role_select"] = None
    st.session_state["draft_custom_job_role"] = ""
    _clear_explore_outputs()


def _on_job_family_change() -> None:
    st.session_state["draft_job_role_select"] = None
    st.session_state["draft_custom_job_role"] = ""
    _clear_explore_outputs()


def _on_job_role_select_change() -> None:
    if st.session_state.get("draft_job_role_select") != CUSTOM_JOB_ROLE:
        st.session_state["draft_custom_job_role"] = ""
    _clear_explore_outputs()


def _on_search_filter_change() -> None:
    _clear_explore_outputs()


def _on_summary_context_change() -> None:
    _clear_summary_outputs()


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
        detail = exc.response.text
        st.error(f"백엔드 응답 오류: {detail}")
    except httpx.RequestError as exc:
        st.error(f"백엔드 연결 오류: {exc}")
    return {}


def _resolve_job_role(draft: dict[str, Any]) -> str | None:
    selected_role = draft.get("job_role_select")
    if selected_role in {None, UNDECIDED_JOB_ROLE}:
        return None
    if selected_role == CUSTOM_JOB_ROLE:
        return compact_text(draft.get("custom_job_role"))
    return selected_role


def _build_search_preferences(draft: dict[str, Any]) -> str | None:
    return build_preferences_text(
        draft.get("preference_tags", []),
        draft.get("preference_note"),
    )


def _build_explore_payload(draft: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    industry = draft.get("industry")
    job_family = draft.get("job_family")
    selected_role = draft.get("job_role_select")
    job_role = _resolve_job_role(draft)

    if not industry:
        return None, "산업을 먼저 선택해 주세요."
    if not job_family:
        return None, "직군을 먼저 선택해 주세요."
    if selected_role is None:
        return None, "직무를 선택하거나 `미정`을 골라 주세요."
    if selected_role == CUSTOM_JOB_ROLE and not job_role:
        return None, "직접 입력 직무를 비워둘 수는 없습니다."

    payload = {
        "industry": industry,
        "job_family": job_family,
        "job_role": job_role,
        "experience_level": draft.get("experience_level"),
        "preferences": _build_search_preferences(draft),
        "user_background": compact_text(draft.get("user_background")),
    }
    return payload, None


def _candidate_options(candidates: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    return [None, *candidates]


def _candidate_label(candidate: dict[str, Any] | None) -> str:
    if candidate is None:
        return "선택 안 함"
    summary = candidate.get("summary", "")
    clipped = summary[:70] + ("..." if len(summary) > 70 else "")
    return f"{candidate.get('name', '이름 없음')} | {clipped}"


def _selected_candidate_from_index(
    candidates: list[dict[str, Any]],
    selected_index: int,
) -> dict[str, Any] | None:
    options = _candidate_options(candidates)
    if 0 <= selected_index < len(options):
        return options[selected_index]
    return None


def _build_selected_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "name": candidate["name"],
        "kind": candidate["kind"],
        "summary": candidate["summary"],
        "source_url": candidate["source_url"],
    }


def _render_candidate_card(candidate: dict[str, Any]) -> None:
    st.markdown(f"### {candidate['name']}")
    st.caption(candidate["source_url"])
    st.write(candidate["summary"])
    st.caption(candidate["why_relevant"])


def _render_string_list(title: str, values: list[str]) -> None:
    st.markdown(f"#### {title}")
    if not values:
        st.write("아직 내용이 없습니다.")
        return
    for item in values:
        st.markdown(f"- {item}")


def _render_source_cards(source_cards: list[dict[str, Any]]) -> None:
    with st.expander("탐색 근거 및 참고 정보", expanded=False):
        for card in source_cards:
            st.markdown(f"**{card['title']}**")
            st.caption(f"{card['source_type']} | 신뢰도 {card['confidence']:.1f} | {card['url']}")
            st.write(card["claim"])
            st.divider()


def _primary_candidates(explore_result: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
    posting_candidates = explore_result.get("posting_candidates", [])
    if posting_candidates:
        return posting_candidates, "posting", "공고"
    company_candidates = explore_result.get("company_candidates", [])
    return company_candidates, "company", "회사"


def _render_supporting_company_cards(company_candidates: list[dict[str, Any]]) -> None:
    if not company_candidates:
        return

    with st.expander("관련 기업 참고 정보", expanded=False):
        for candidate in company_candidates:
            st.markdown(f"**{candidate['name']}**")
            st.caption(candidate["source_url"])
            st.write(candidate["summary"])
            st.divider()


def _inject_styles() -> None:
    st.markdown(
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
        .hero-card {
            border: 1px solid rgba(27, 55, 34, 0.12);
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.82);
            box-shadow: 0 18px 40px rgba(38, 52, 37, 0.08);
            backdrop-filter: blur(8px);
            padding: 1.5rem 1.6rem;
            margin-bottom: 1.25rem;
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
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.markdown(
        """
        <div class="hero-card">
            <div class="eyebrow">Job Coach Runtime</div>
            <div class="hero-title">취업 코치</div>
            <div class="hero-copy">
                탐색은 산업·직군·직무를 기준으로 시작하고, 사용자 배경과 메모는 이후 요약서와 면접 자료에 반영합니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 실행 환경")
        st.write(f"- 백엔드: `{BACKEND_BASE_URL}`")
        st.write(f"- 검색: `{SETTINGS.search_provider}`")
        st.write(f"- 생성: `{SETTINGS.llm_provider}` / `{SETTINGS.openai_model}`")
        if st.button("전체 입력 초기화", use_container_width=True):
            _reset_all_state()
            st.rerun()


def _submitted_search_summary(submitted_input: dict[str, Any] | None) -> str | None:
    if not submitted_input:
        return None

    parts = [
        submitted_input.get("industry"),
        submitted_input.get("job_family"),
        submitted_input.get("job_role") or UNDECIDED_JOB_ROLE,
    ]
    if submitted_input.get("experience_level"):
        parts.append(submitted_input["experience_level"])
    if submitted_input.get("preferences"):
        parts.append(submitted_input["preferences"])
    return " / ".join(part for part in parts if part)


def _render_input_stage() -> None:
    st.markdown("## 목표를 입력해주세요")

    current_draft = st.session_state["draft_input"]
    submitted_summary = _submitted_search_summary(st.session_state.get("submitted_input"))
    role_options = [None, *job_roles_for_family(current_draft.get("job_family"))]

    st.caption("산업과 직군은 필수입니다. 직무는 세부 선택 또는 `미정`/`직접 입력`으로 좁혀 주세요.")

    left, right = st.columns(2)
    with left:
        st.selectbox(
            "산업",
            options=[None, *INDUSTRIES],
            key="draft_industry",
            format_func=lambda value: value or "산업을 선택하세요",
            on_change=_on_industry_change,
        )
    with right:
        st.selectbox(
            "직군",
            options=[None, *JOB_FAMILIES],
            key="draft_job_family",
            format_func=lambda value: value or "직군을 선택하세요",
            on_change=_on_job_family_change,
        )

    st.selectbox(
        "직무",
        options=role_options,
        key="draft_job_role_select",
        format_func=lambda value: value or "직군을 먼저 선택한 뒤 직무를 선택하세요",
        disabled=not current_draft.get("job_family"),
        on_change=_on_job_role_select_change,
    )

    if st.session_state.get("draft_job_role_select") == CUSTOM_JOB_ROLE:
        st.text_input(
            "직접 입력 직무",
            key="draft_custom_job_role",
            placeholder="예: 개발자 플랫폼 엔지니어",
            on_change=_on_search_filter_change,
        )

    filter_col, preference_col = st.columns((1, 2))
    with filter_col:
        st.radio(
            "경력 수준",
            options=[None, *EXPERIENCE_LEVELS],
            key="draft_experience_level",
            format_func=lambda value: value or "선택 안 함",
            horizontal=True,
            on_change=_on_search_filter_change,
        )
    with preference_col:
        st.multiselect(
            "선호 조건",
            options=PREFERENCE_TAGS,
            key="draft_preference_tags",
            placeholder="근무 형태, 지역, 기업 규모 등을 고르세요",
            on_change=_on_search_filter_change,
        )

    st.text_input(
        "기타 선호",
        key="draft_preference_note",
        placeholder="예: B2B 서비스, 데이터 중심 조직",
        on_change=_on_search_filter_change,
    )

    with st.expander("추가 정보", expanded=False):
        st.text_area(
            "사용자 배경",
            key="draft_user_background",
            placeholder="프로젝트 경험, 강점, 부족하다고 느끼는 부분을 적습니다.",
            height=120,
            on_change=_on_summary_context_change,
        )
        st.text_area(
            "메모",
            key="draft_notes",
            placeholder="이번 탐색에서 특별히 보고 싶은 조건이나 메모를 적습니다.",
            height=100,
            on_change=_on_summary_context_change,
        )

    if submitted_summary:
        st.caption(f"마지막 탐색 기준: {submitted_summary}")

    if st.button("지원 대상 후보 탐색", use_container_width=True):
        _sync_draft_state()
        draft = st.session_state["draft_input"]
        payload, error = _build_explore_payload(draft)
        if error:
            st.error(error)
            return

        _clear_explore_outputs(clear_submitted=False)
        st.session_state["submitted_input"] = payload
        with st.spinner("관련 공고와 참고 정보를 탐색하고 있습니다..."):
            result = _call_api("/explore", payload)
        if result:
            st.session_state["explore_result"] = result
            st.rerun()


def _render_explore_stage() -> None:
    explore_result = st.session_state.get("explore_result")
    if not explore_result:
        return

    st.markdown("## 후보 탐색 결과")
    if explore_result.get("notes"):
        for note in explore_result["notes"]:
            st.warning(note)

    query_text = " / ".join(explore_result.get("queries", []))
    if query_text:
        st.caption(f"탐색 쿼리: {query_text}")

    company_candidates = explore_result.get("company_candidates", [])
    primary_candidates, primary_source, primary_label = _primary_candidates(explore_result)

    if st.session_state["selected_target_source"] != primary_source:
        st.session_state["selected_target_source"] = primary_source
        st.session_state["selected_target_index"] = 0

    if not primary_candidates:
        st.warning("아직 선택할 수 있는 지원 대상 후보가 없습니다. 입력 조건을 조정해 다시 탐색해 보세요.")
        _render_source_cards(explore_result.get("source_cards", []))
        return

    primary_options = _candidate_options(primary_candidates)
    st.markdown(f"### {primary_label} 기준 지원 대상 후보")
    if primary_source == "company":
        st.caption("공고 후보가 충분하지 않아 회사 기준으로 임시 선택합니다.")

    st.session_state["selected_target_index"] = st.selectbox(
        "지원 대상 후보 선택",
        options=list(range(len(primary_options))),
        index=min(st.session_state["selected_target_index"], len(primary_options) - 1),
        format_func=lambda idx: _candidate_label(primary_options[idx]),
        key="target_select",
    )
    selected_target = _selected_candidate_from_index(primary_candidates, st.session_state["selected_target_index"])
    if selected_target:
        _render_candidate_card(selected_target)

    if primary_source == "posting":
        _render_supporting_company_cards(company_candidates)
    _render_source_cards(explore_result.get("source_cards", []))

    if st.button("지원 준비 요약서 만들기", use_container_width=True):
        draft = st.session_state["draft_input"]
        payload = {
            "run_id": explore_result.get("run_id"),
            "selected_target": _build_selected_candidate(selected_target),
            "user_background": compact_text(draft.get("user_background")),
            "notes": compact_text(draft.get("notes")),
        }
        with st.spinner("지원 준비 요약서를 정리하고 있습니다..."):
            result = _call_api("/prepare-summary", payload)
        if result:
            st.session_state["prepare_summary_result"] = result
            st.session_state["prep_artifacts_result"] = None
            st.rerun()


def _render_result_stage() -> None:
    prepare_summary = st.session_state.get("prepare_summary_result")
    if not prepare_summary:
        return

    st.markdown("## 지원 준비")
    for warning in prepare_summary.get("warnings", []):
        st.warning(warning)

    st.markdown("### 지원 준비 요약서")
    st.write(prepare_summary.get("preparation_summary", ""))

    col1, col2 = st.columns(2)
    with col1:
        _render_string_list("준비 포인트", prepare_summary.get("preparation_points", []))
    with col2:
        _render_string_list("부족 역량과 보완 포인트", prepare_summary.get("skill_gaps", []))

    if st.button("실행 항목과 면접 자료 만들기", use_container_width=True):
        explore_result = st.session_state.get("explore_result") or {}
        primary_candidates, _, _ = _primary_candidates(explore_result)
        selected_target = _selected_candidate_from_index(primary_candidates, st.session_state["selected_target_index"])
        draft = st.session_state["draft_input"]
        payload = {
            "run_id": prepare_summary.get("run_id") or explore_result.get("run_id"),
            "selected_target": _build_selected_candidate(selected_target),
            "preparation_summary": prepare_summary.get("preparation_summary", ""),
            "user_background": compact_text(draft.get("user_background")),
            "notes": compact_text(draft.get("notes")),
        }
        with st.spinner("실행 항목과 면접 자료를 만들고 있습니다..."):
            result = _call_api("/prep-artifacts", payload)
        if result:
            st.session_state["prep_artifacts_result"] = result
            st.rerun()

    artifacts = st.session_state.get("prep_artifacts_result")
    if not artifacts:
        return

    for warning in artifacts.get("warnings", []):
        st.warning(warning)

    left, right = st.columns(2)
    with left:
        _render_string_list("실행 항목", artifacts.get("action_items", []))
    with right:
        _render_string_list("예상 면접 질문", artifacts.get("interview_questions", []))
        _render_string_list("답변 구조", artifacts.get("answer_frames", []))


def main() -> None:
    _init_state()
    _sync_draft_state()
    _inject_styles()
    _render_sidebar()
    _render_header()
    _render_input_stage()
    _render_explore_stage()
    _render_result_stage()


if __name__ == "__main__":
    main()
