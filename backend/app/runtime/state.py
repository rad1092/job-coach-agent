from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from backend.app.schemas.api import CandidateCard, SelectedCandidate, SourceCard


class AgentRuntimeState(TypedDict, total=False):
    session_id: str
    phase: str
    run_id: str
    industry: str
    job_family: str
    job_role: str | None
    experience_level: str | None
    preferences: str | None
    user_background: str | None
    notes: list[str]
    queries: list[str]
    source_cards: list[SourceCard]
    company_candidates: list[CandidateCard]
    posting_candidates: list[CandidateCard]
    selected_target: SelectedCandidate | None
    preparation_summary: str
    preparation_points: list[str]
    skill_gaps: list[str]
    action_items: list[str]
    interview_questions: list[str]
    answer_frames: list[str]
    warnings: list[str]
    next_action: Literal["continue", "retry_search", "regenerate_artifacts", "finalize"]
    retry_count: int
    max_retries: int
    selection_required: NotRequired[bool]
