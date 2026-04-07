from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.settings import get_settings
from backend.app.runtime.graphs import (
    run_explore_graph,
    run_prep_artifacts_graph,
    run_prepare_summary_graph,
)
from backend.app.schemas.api import (
    ExploreRequest,
    ExploreResponse,
    PrepArtifactsRequest,
    PrepArtifactsResponse,
    PrepareSummaryRequest,
    PrepareSummaryResponse,
)
from backend.app.storage.session_store import persist_run_artifact

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

    persist_run_artifact(settings.data_dir, response.run_id, "explore", response.model_dump())
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
    persist_run_artifact(settings.data_dir, run_id, "prepare_summary", response.model_dump())
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
    persist_run_artifact(settings.data_dir, run_id, "prep_artifacts", response.model_dump())
    return response
