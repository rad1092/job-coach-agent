from __future__ import annotations

from typing import Any

import httpx
import streamlit as st

from backend.app.core.settings import get_settings

st.set_page_config(
    page_title="취업 코치형 에이전트",
    page_icon=":briefcase:",
    layout="wide",
)

SETTINGS = get_settings()
BACKEND_BASE_URL = SETTINGS.backend_base_url.rstrip("/")
REQUEST_TIMEOUT = 60.0


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
        "selected_target_index": 0,
        "selected_target_source": "posting",
        "prepare_summary_result": None,
        "prep_artifacts_result": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_flow() -> None:
    for key in [
        "explore_result",
        "selected_target_index",
        "selected_target_source",
        "prepare_summary_result",
        "prep_artifacts_result",
    ]:
        if key.endswith("_index"):
            st.session_state[key] = 0
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
        detail = exc.response.text
        st.error(f"백엔드 응답 오류: {detail}")
    except httpx.RequestError as exc:
        st.error(f"백엔드 연결 오류: {exc}")
    return {}


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
        .hero-card, .panel-card {
            border: 1px solid rgba(27, 55, 34, 0.12);
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.82);
            box-shadow: 0 18px 40px rgba(38, 52, 37, 0.08);
            backdrop-filter: blur(8px);
        }
        .hero-card {
            padding: 1.5rem 1.6rem;
            margin-bottom: 1.25rem;
        }
        .panel-card {
            padding: 1rem 1.1rem;
            margin-bottom: 1rem;
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
            <div class="hero-title">희망 산업·직군·직무에서 지원 준비 흐름까지</div>
            <div class="hero-copy">
                입력한 목표를 기준으로 관련 기업과 공고를 탐색하고, 지원 준비 요약서와 실행 항목, 면접 자료를 한 흐름으로 정리합니다.
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
        if st.button("현재 흐름 초기화", use_container_width=True):
            _reset_flow()
            st.rerun()


def _render_input_stage() -> None:
    st.markdown("## 1단계. 목표 입력")
    with st.form("explore_form", clear_on_submit=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            industry = st.text_input("산업", value=st.session_state.input_payload["industry"])
        with col2:
            job_family = st.text_input("직군", value=st.session_state.input_payload["job_family"])
        with col3:
            job_role = st.text_input("직무", value=st.session_state.input_payload["job_role"])

        col4, col5 = st.columns(2)
        with col4:
            experience_level = st.text_input(
                "경력 수준",
                value=st.session_state.input_payload["experience_level"],
                placeholder="예: 신입, 주니어, 2년차",
            )
        with col5:
            preferences = st.text_input(
                "선호 조건",
                value=st.session_state.input_payload["preferences"],
                placeholder="예: 원격 근무, 데이터 중심, B2B",
            )

        user_background = st.text_area(
            "사용자 배경",
            value=st.session_state.input_payload["user_background"],
            placeholder="프로젝트 경험, 강점, 부족하다고 느끼는 부분을 적습니다.",
            height=120,
        )
        notes = st.text_area(
            "메모",
            value=st.session_state.input_payload["notes"],
            placeholder="이번 탐색에서 특별히 보고 싶은 조건이나 메모를 적습니다.",
            height=100,
        )

        submitted = st.form_submit_button("지원 대상 후보 탐색", use_container_width=True)

    if submitted:
        payload = {
            "industry": industry,
            "job_family": job_family,
            "job_role": job_role,
            "experience_level": experience_level or None,
            "preferences": preferences or None,
            "user_background": user_background or None,
        }
        st.session_state.input_payload = {
            "industry": industry,
            "job_family": job_family,
            "job_role": job_role,
            "experience_level": experience_level,
            "preferences": preferences,
            "user_background": user_background,
            "notes": notes,
        }
        st.session_state.prepare_summary_result = None
        st.session_state.prep_artifacts_result = None
        st.session_state.selected_target_index = 0
        st.session_state.selected_target_source = "posting"
        with st.spinner("관련 공고와 참고 정보를 탐색하고 있습니다..."):
            result = _call_api("/explore", payload)
        if result:
            st.session_state.explore_result = result
            st.rerun()


def _render_explore_stage() -> None:
    explore_result = st.session_state.explore_result
    if not explore_result:
        return

    st.markdown("## 2단계. 지원 대상 후보 선택")
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
        st.session_state.selected_target_index = 0

    if not primary_candidates:
        st.warning("아직 선택할 수 있는 지원 대상 후보가 없습니다. 입력 조건을 조정해 다시 탐색해 보세요.")
        _render_source_cards(explore_result.get("source_cards", []))
        return

    primary_options = _candidate_options(primary_candidates)
    st.markdown(f"### {primary_label} 기준 지원 대상 후보")
    if primary_source == "company":
        st.caption("공고 후보가 충분하지 않아 회사 기준으로 임시 선택합니다.")

    st.session_state.selected_target_index = st.selectbox(
        "지원 대상 후보 선택",
        options=list(range(len(primary_options))),
        index=min(st.session_state.selected_target_index, len(primary_options) - 1),
        format_func=lambda idx: _candidate_label(primary_options[idx]),
        key="target_select",
    )
    selected_target = _selected_candidate_from_index(primary_candidates, st.session_state.selected_target_index)
    if selected_target:
        _render_candidate_card(selected_target)

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

    st.markdown("### 지원 준비 요약서")
    st.write(prepare_summary.get("preparation_summary", ""))

    col1, col2 = st.columns(2)
    with col1:
        _render_string_list("준비 포인트", prepare_summary.get("preparation_points", []))
    with col2:
        _render_string_list("부족 역량과 보완 포인트", prepare_summary.get("skill_gaps", []))

    if st.button("실행 항목과 면접 자료 만들기", use_container_width=True):
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

    artifacts = st.session_state.prep_artifacts_result
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
    _inject_styles()
    _render_sidebar()
    _render_header()
    _render_input_stage()
    _render_explore_stage()
    _render_result_stage()


if __name__ == "__main__":
    main()
