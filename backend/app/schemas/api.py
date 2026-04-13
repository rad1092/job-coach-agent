from typing import Literal

from pydantic import BaseModel, Field


class ExploreRequest(BaseModel):
    industry: str = Field(..., min_length=1)
    job_family: str = Field(..., min_length=1)
    job_role: str = Field(..., min_length=1)
    experience_level: str | None = None
    preferences: str | None = None
    user_background: str | None = None


class CandidateCard(BaseModel):
    name: str
    kind: Literal["company", "posting"]
    summary: str
    why_relevant: str
    source_url: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SourceCard(BaseModel):
    title: str
    url: str
    source_type: Literal["company", "posting", "general"]
    claim: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class ExploreResponse(BaseModel):
    run_id: str
    queries: list[str]
    company_candidates: list[CandidateCard]
    posting_candidates: list[CandidateCard]
    source_cards: list[SourceCard]
    notes: list[str] = Field(default_factory=list)


class SelectedCandidate(BaseModel):
    name: str
    kind: Literal["company", "posting"]
    summary: str
    source_url: str


class PrepareSummaryRequest(BaseModel):
    run_id: str | None = None
    selected_target: SelectedCandidate | None = None
    user_background: str | None = None
    notes: str | None = None


class PrepareSummaryResponse(BaseModel):
    run_id: str
    preparation_summary: str
    preparation_points: list[str]
    skill_gaps: list[str]
    warnings: list[str] = Field(default_factory=list)


class PrepArtifactsRequest(BaseModel):
    run_id: str | None = None
    selected_target: SelectedCandidate | None = None
    preparation_summary: str
    user_background: str | None = None
    notes: str | None = None


class PrepArtifactsResponse(BaseModel):
    run_id: str
    action_items: list[str]
    interview_questions: list[str]
    answer_frames: list[str]
    warnings: list[str] = Field(default_factory=list)


class CoachChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    preparation_tips: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)


class CoachChatRequest(BaseModel):
    run_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    selected_target: SelectedCandidate | None = None
    user_background: str | None = None
    notes: str | None = None


class CoachChatResponse(BaseModel):
    run_id: str
    answer: str
    preparation_tips: list[str]
    suggested_questions: list[str]
    messages: list[CoachChatMessage]
    warnings: list[str] = Field(default_factory=list)


class CoachChatHistoryResponse(BaseModel):
    run_id: str
    messages: list[CoachChatMessage]
