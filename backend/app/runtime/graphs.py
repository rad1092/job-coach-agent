from __future__ import annotations

import uuid
from typing import Literal, cast

from langgraph.graph import END, START, StateGraph

from backend.app.core.settings import Settings
from backend.app.runtime.state import AgentRuntimeState
from backend.app.schemas.api import (
    CandidateCard,
    ExploreRequest,
    ExploreResponse,
    PrepArtifactsRequest,
    PrepArtifactsResponse,
    PrepareSummaryRequest,
    PrepareSummaryResponse,
    SourceCard,
)
from backend.app.services.exploration import (
    MAX_COMPANY_CANDIDATES,
    MAX_POSTING_CANDIDATES,
    MAX_SOURCE_CARDS,
    build_queries,
    collect_candidates,
)
from backend.app.services.preparation import (
    build_prep_artifacts,
    build_prepare_summary,
    critique_prep_artifacts,
)


def _compact(value: str | None) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    return compact or None


def _merge_messages(*parts: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for items in parts:
        for item in items:
            if item and item not in seen:
                seen.add(item)
                merged.append(item)
    return merged


def _merge_candidate_cards(*parts: list[CandidateCard]) -> list[CandidateCard]:
    merged: dict[str, CandidateCard] = {}
    for items in parts:
        for item in items:
            current = merged.get(item.source_url)
            if current is None or item.confidence > current.confidence:
                merged[item.source_url] = item
    return sorted(merged.values(), key=lambda item: (-item.confidence, item.name))


def _merge_source_cards(*parts: list[SourceCard]) -> list[SourceCard]:
    merged: dict[str, SourceCard] = {}
    for items in parts:
        for item in items:
            current = merged.get(item.url)
            if current is None or item.confidence > current.confidence:
                merged[item.url] = item
    return sorted(merged.values(), key=lambda item: (-item.confidence, item.title))


async def run_explore_graph(settings: Settings, request: ExploreRequest) -> ExploreResponse:
    async def normalize_input(state: AgentRuntimeState) -> AgentRuntimeState:
        return {
            "phase": "normalized",
            "industry": _compact(state.get("industry")) or "",
            "job_family": _compact(state.get("job_family")) or "",
            "job_role": _compact(state.get("job_role")) or "",
            "experience_level": _compact(state.get("experience_level")),
            "preferences": _compact(state.get("preferences")),
            "user_background": _compact(state.get("user_background")),
        }

    def plan_search(state: AgentRuntimeState) -> AgentRuntimeState:
        normalized_request = ExploreRequest(
            industry=state["industry"],
            job_family=state["job_family"],
            job_role=state["job_role"],
            experience_level=state.get("experience_level"),
            preferences=state.get("preferences"),
            user_background=state.get("user_background"),
        )
        return {
            "phase": "search_planned",
            "queries": build_queries(normalized_request, retry_count=state.get("retry_count", 0)),
        }

    async def collect_evidence(state: AgentRuntimeState) -> AgentRuntimeState:
        normalized_request = ExploreRequest(
            industry=state["industry"],
            job_family=state["job_family"],
            job_role=state["job_role"],
            experience_level=state.get("experience_level"),
            preferences=state.get("preferences"),
            user_background=state.get("user_background"),
        )
        collected = await collect_candidates(
            settings,
            normalized_request,
            state.get("queries", []),
            retry_count=state.get("retry_count", 0),
        )
        return {
            "phase": "evidence_collected",
            "company_candidates": _merge_candidate_cards(
                cast(list[CandidateCard], state.get("company_candidates", [])),
                cast(list[CandidateCard], collected["company_candidates"]),
            )[:MAX_COMPANY_CANDIDATES],
            "posting_candidates": _merge_candidate_cards(
                cast(list[CandidateCard], state.get("posting_candidates", [])),
                cast(list[CandidateCard], collected["posting_candidates"]),
            )[:MAX_POSTING_CANDIDATES],
            "source_cards": _merge_source_cards(
                cast(list[SourceCard], state.get("source_cards", [])),
                cast(list[SourceCard], collected["source_cards"]),
            )[:MAX_SOURCE_CARDS],
            "notes": _merge_messages(state.get("notes", []), cast(list[str], collected["notes"])),
        }

    def judge_evidence(state: AgentRuntimeState) -> AgentRuntimeState:
        company_count = len(state.get("company_candidates", []))
        posting_count = len(state.get("posting_candidates", []))
        source_count = len(state.get("source_cards", []))
        retry_count = state.get("retry_count", 0)
        max_retries = state.get("max_retries", 1)
        notes = list(state.get("notes", []))
        next_action: Literal["retry_search", "finalize"] = "finalize"

        if company_count == 0 and posting_count == 0 and retry_count < max_retries:
            notes.append("조건에 맞는 공고가 부족해 확장 채용 보드까지 넓혀 다시 탐색합니다.")
            next_action = "retry_search"
            retry_count += 1
        elif posting_count < MAX_POSTING_CANDIDATES and retry_count < max_retries:
            notes.append(f"후보를 {MAX_POSTING_CANDIDATES}건 가까이 확보하기 위해 확장 채용 보드까지 다시 탐색합니다.")
            next_action = "retry_search"
            retry_count += 1
        elif source_count < 2 and retry_count < max_retries:
            notes.append("탐색 근거가 부족해 한 번 더 검색합니다.")
            next_action = "retry_search"
            retry_count += 1

        return {
            "phase": "evidence_judged",
            "notes": _merge_messages(state.get("notes", []), notes),
            "retry_count": retry_count,
            "next_action": next_action,
        }

    def route_after_judge(state: AgentRuntimeState) -> Literal["plan_search", "finalize_explore"]:
        if state.get("next_action") == "retry_search":
            return "plan_search"
        return "finalize_explore"

    def finalize_explore(state: AgentRuntimeState) -> AgentRuntimeState:
        return {"phase": "finalized"}

    builder = StateGraph(AgentRuntimeState)
    builder.add_node("normalize_input", normalize_input)
    builder.add_node("plan_search", plan_search)
    builder.add_node("collect_evidence", collect_evidence)
    builder.add_node("judge_evidence", judge_evidence)
    builder.add_node("finalize_explore", finalize_explore)
    builder.add_edge(START, "normalize_input")
    builder.add_edge("normalize_input", "plan_search")
    builder.add_edge("plan_search", "collect_evidence")
    builder.add_edge("collect_evidence", "judge_evidence")
    builder.add_conditional_edges(
        "judge_evidence",
        route_after_judge,
        {"plan_search": "plan_search", "finalize_explore": "finalize_explore"},
    )
    builder.add_edge("finalize_explore", END)

    graph = builder.compile()
    initial_state: AgentRuntimeState = {
        "session_id": uuid.uuid4().hex,
        "run_id": uuid.uuid4().hex,
        "phase": "init",
        "industry": request.industry,
        "job_family": request.job_family,
        "job_role": request.job_role,
        "experience_level": request.experience_level,
        "preferences": request.preferences,
        "user_background": request.user_background,
        "notes": [],
        "warnings": [],
        "retry_count": 0,
        "max_retries": 2,
        "next_action": "continue",
    }
    result = cast(AgentRuntimeState, await graph.ainvoke(initial_state))
    return ExploreResponse(
        run_id=result["run_id"],
        queries=result.get("queries", []),
        company_candidates=result.get("company_candidates", []),
        posting_candidates=result.get("posting_candidates", []),
        source_cards=result.get("source_cards", []),
        notes=result.get("notes", []),
    )


async def run_prepare_summary_graph(settings: Settings, request: PrepareSummaryRequest) -> PrepareSummaryResponse:
    def check_selection(state: AgentRuntimeState) -> AgentRuntimeState:
        warnings = list(state.get("warnings", []))
        if state.get("selected_target") is None:
            warnings.append("지원 준비 요약서를 만들려면 지원 대상 후보를 먼저 선택해 주세요.")
            return {
                "phase": "selection_missing",
                "warnings": warnings,
                "selection_required": True,
                "next_action": "finalize",
            }
        return {
            "phase": "selection_ready",
            "warnings": warnings,
            "selection_required": False,
            "next_action": "continue",
        }

    def route_after_selection(state: AgentRuntimeState) -> Literal["synthesize_preparation_summary", "finalize_prepare_summary"]:
        if state.get("selection_required"):
            return "finalize_prepare_summary"
        return "synthesize_preparation_summary"

    def synthesize_preparation_summary(state: AgentRuntimeState) -> AgentRuntimeState:
        response = build_prepare_summary(
            settings,
            PrepareSummaryRequest(
                run_id=state["run_id"],
                selected_target=state.get("selected_target"),
                user_background=state.get("user_background"),
                notes="\n".join(state.get("notes", [])) if state.get("notes") else None,
            ),
        )
        return {
            "phase": "preparation_synthesized",
            "preparation_summary": response.preparation_summary,
            "preparation_points": response.preparation_points,
            "skill_gaps": response.skill_gaps,
            "warnings": _merge_messages(state.get("warnings", []), response.warnings),
        }

    def finalize_prepare_summary(state: AgentRuntimeState) -> AgentRuntimeState:
        if state.get("preparation_summary"):
            return {"phase": "finalized"}

        if state.get("selection_required"):
            return {
                "phase": "finalized",
                "preparation_summary": "지원 준비 요약서를 만들려면 지원 대상 후보를 먼저 선택해 주세요.",
                "preparation_points": [],
                "skill_gaps": [],
            }

        fallback = build_prepare_summary(
            settings,
            PrepareSummaryRequest(
                run_id=state["run_id"],
                selected_target=state.get("selected_target"),
                user_background=state.get("user_background"),
                notes="\n".join(state.get("notes", [])) if state.get("notes") else None,
            ),
        )
        return {
            "phase": "finalized",
            "preparation_summary": fallback.preparation_summary,
            "preparation_points": fallback.preparation_points,
            "skill_gaps": fallback.skill_gaps,
            "warnings": _merge_messages(state.get("warnings", []), fallback.warnings),
        }

    builder = StateGraph(AgentRuntimeState)
    builder.add_node("check_selection", check_selection)
    builder.add_node("synthesize_preparation_summary", synthesize_preparation_summary)
    builder.add_node("finalize_prepare_summary", finalize_prepare_summary)
    builder.add_edge(START, "check_selection")
    builder.add_conditional_edges(
        "check_selection",
        route_after_selection,
        {
            "synthesize_preparation_summary": "synthesize_preparation_summary",
            "finalize_prepare_summary": "finalize_prepare_summary",
        },
    )
    builder.add_edge("synthesize_preparation_summary", "finalize_prepare_summary")
    builder.add_edge("finalize_prepare_summary", END)

    graph = builder.compile()
    initial_state: AgentRuntimeState = {
        "session_id": request.run_id or uuid.uuid4().hex,
        "run_id": request.run_id or "adhoc",
        "phase": "init",
        "selected_target": request.selected_target,
        "user_background": request.user_background,
        "notes": [request.notes] if request.notes else [],
        "warnings": [],
        "retry_count": 0,
        "max_retries": 0,
        "next_action": "continue",
    }
    result = cast(AgentRuntimeState, graph.invoke(initial_state))
    return PrepareSummaryResponse(
        run_id=result["run_id"],
        preparation_summary=result.get("preparation_summary", ""),
        preparation_points=result.get("preparation_points", []),
        skill_gaps=result.get("skill_gaps", []),
        warnings=result.get("warnings", []),
    )


async def run_prep_artifacts_graph(settings: Settings, request: PrepArtifactsRequest) -> PrepArtifactsResponse:
    def generate_artifacts(state: AgentRuntimeState) -> AgentRuntimeState:
        response = build_prep_artifacts(
            settings,
            PrepArtifactsRequest(
                run_id=state["run_id"],
                selected_target=state.get("selected_target"),
                preparation_summary=state.get("preparation_summary", ""),
                user_background=state.get("user_background"),
                notes="\n".join(state.get("notes", [])) if state.get("notes") else None,
            ),
        )
        return {
            "phase": "artifacts_generated",
            "action_items": response.action_items,
            "interview_questions": response.interview_questions,
            "answer_frames": response.answer_frames,
            "warnings": _merge_messages(state.get("warnings", []), response.warnings),
        }

    def critic_artifacts(state: AgentRuntimeState) -> AgentRuntimeState:
        response = PrepArtifactsResponse(
            run_id=state["run_id"],
            action_items=state.get("action_items", []),
            interview_questions=state.get("interview_questions", []),
            answer_frames=state.get("answer_frames", []),
            warnings=state.get("warnings", []),
        )
        needs_revision, warnings = critique_prep_artifacts(
            settings,
            PrepArtifactsRequest(
                run_id=state["run_id"],
                selected_target=state.get("selected_target"),
                preparation_summary=state.get("preparation_summary", ""),
                user_background=state.get("user_background"),
                notes="\n".join(state.get("notes", [])) if state.get("notes") else None,
            ),
            response,
        )
        retry_count = state.get("retry_count", 0)
        next_action: Literal["regenerate_artifacts", "finalize"] = "finalize"
        if needs_revision and retry_count < state.get("max_retries", 1):
            retry_count += 1
            next_action = "regenerate_artifacts"
            warnings = _merge_messages(warnings, ["산출물이 지나치게 일반적이어서 한 번 더 다듬습니다."])
        return {
            "phase": "artifacts_reviewed",
            "warnings": _merge_messages(state.get("warnings", []), warnings),
            "retry_count": retry_count,
            "next_action": next_action,
        }

    def route_after_critic(state: AgentRuntimeState) -> Literal["generate_artifacts", "finalize_artifacts"]:
        if state.get("next_action") == "regenerate_artifacts":
            return "generate_artifacts"
        return "finalize_artifacts"

    def finalize_artifacts(state: AgentRuntimeState) -> AgentRuntimeState:
        return {"phase": "finalized"}

    builder = StateGraph(AgentRuntimeState)
    builder.add_node("generate_artifacts", generate_artifacts)
    builder.add_node("critic_artifacts", critic_artifacts)
    builder.add_node("finalize_artifacts", finalize_artifacts)
    builder.add_edge(START, "generate_artifacts")
    builder.add_edge("generate_artifacts", "critic_artifacts")
    builder.add_conditional_edges(
        "critic_artifacts",
        route_after_critic,
        {"generate_artifacts": "generate_artifacts", "finalize_artifacts": "finalize_artifacts"},
    )
    builder.add_edge("finalize_artifacts", END)

    graph = builder.compile()
    initial_state: AgentRuntimeState = {
        "session_id": request.run_id or uuid.uuid4().hex,
        "run_id": request.run_id or "adhoc",
        "phase": "init",
        "selected_target": request.selected_target,
        "preparation_summary": request.preparation_summary,
        "user_background": request.user_background,
        "notes": [request.notes] if request.notes else [],
        "warnings": [],
        "retry_count": 0,
        "max_retries": 1,
        "next_action": "continue",
    }
    result = cast(AgentRuntimeState, graph.invoke(initial_state))
    return PrepArtifactsResponse(
        run_id=result["run_id"],
        action_items=result.get("action_items", []),
        interview_questions=result.get("interview_questions", []),
        answer_frames=result.get("answer_frames", []),
        warnings=result.get("warnings", []),
    )
