from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.settings import get_settings
from backend.app.runtime.graphs import (
    run_explore_graph,
    run_prep_artifacts_graph,
    run_prepare_summary_graph,
)
from backend.app.schemas.api import (
    CoachChatHistoryResponse,
    CoachChatMessage,
    CoachChatRequest,
    CoachChatResponse,
    ExploreRequest,
    ExploreResponse,
    PrepArtifactsRequest,
    PrepArtifactsResponse,
    PrepareSummaryRequest,
    PrepareSummaryResponse,
)
from backend.app.services.coach_chat import build_coach_chat_response
from backend.app.storage.session_store import load_chat_messages, persist_run_artifact, persist_stage_snapshot

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/explore", response_model=ExploreResponse)
async def explore(request: ExploreRequest) -> ExploreResponse:
    settings = get_settings()
    try:
        response = await run_explore_graph(settings, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    response_payload = response.model_dump()
    persist_run_artifact(settings.data_dir, response.run_id, "explore", response_payload)
    persist_stage_snapshot(
        settings.data_dir,
        response.run_id,
        "explore",
        request.model_dump(),
        response_payload,
    )
    return response


@router.post("/prepare-summary", response_model=PrepareSummaryResponse)
async def prepare_summary(request: PrepareSummaryRequest) -> PrepareSummaryResponse:
    settings = get_settings()
    try:
        response = await run_prepare_summary_graph(settings, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    run_id = response.run_id or request.run_id or "adhoc"
    response.run_id = run_id
    response_payload = response.model_dump()
    persist_run_artifact(settings.data_dir, run_id, "prepare_summary", response_payload)
    persist_stage_snapshot(
        settings.data_dir,
        run_id,
        "prepare_summary",
        request.model_dump(),
        response_payload,
        selected_target=request.selected_target.model_dump() if request.selected_target else None,
    )
    return response


@router.post("/prep-artifacts", response_model=PrepArtifactsResponse)
async def prep_artifacts(request: PrepArtifactsRequest) -> PrepArtifactsResponse:
    settings = get_settings()
    try:
        response = await run_prep_artifacts_graph(settings, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    run_id = request.run_id or "adhoc"
    response.run_id = run_id
    response_payload = response.model_dump()
    persist_run_artifact(settings.data_dir, run_id, "prep_artifacts", response_payload)
    persist_stage_snapshot(
        settings.data_dir,
        run_id,
        "prep_artifacts",
        request.model_dump(),
        response_payload,
        selected_target=request.selected_target.model_dump() if request.selected_target else None,
    )
    return response


@router.get("/coach-chat/history/{run_id}", response_model=CoachChatHistoryResponse)
async def coach_chat_history(run_id: str) -> CoachChatHistoryResponse:
    settings = get_settings()
    messages = [CoachChatMessage.model_validate(message) for message in load_chat_messages(settings.data_dir, run_id)]
    return CoachChatHistoryResponse(run_id=run_id, messages=messages)


@router.post("/coach-chat", response_model=CoachChatResponse)
async def coach_chat(request: CoachChatRequest) -> CoachChatResponse:
    settings = get_settings()
    try:
        response = build_coach_chat_response(settings, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return response
