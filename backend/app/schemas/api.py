from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.core.taxonomy import (
    compact_text,
    is_valid_industry,
    is_valid_job_family,
    validate_job_role,
)

ExperienceLevel = Literal["신입", "경력무관", "경력"]


class ExploreRequest(BaseModel):
    industry: str = Field(..., min_length=1)
    job_family: str = Field(..., min_length=1)
    job_role: str | None = None
    experience_level: ExperienceLevel | None = None
    preferences: str | None = None
    user_background: str | None = None

    @field_validator(
        "industry",
        "job_family",
        "job_role",
        "experience_level",
        "preferences",
        "user_background",
        mode="before",
    )
    @classmethod
    def _compact_input(cls, value: object | None) -> str | None:
        return compact_text(value)

    @model_validator(mode="after")
    def _validate_taxonomy(self) -> "ExploreRequest":
        if not is_valid_industry(self.industry):
            raise ValueError("industry must be one of the shared taxonomy options.")
        if not is_valid_job_family(self.job_family):
            raise ValueError("job_family must be one of the shared taxonomy options.")
        if not validate_job_role(self.job_family, self.job_role):
            raise ValueError("job_role must match the selected job family or be custom text.")
        return self


class CandidateCard(BaseModel):
    name: str
    kind: Literal["company", "posting"]
    summary: str
    why_relevant: str
    source_url: str


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
