from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ULID_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{26}$"
Axis = int


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Role(StrEnum):
    MEMBER = "MEMBER"
    ANALYST = "ANALYST"
    REVIEWER = "REVIEWER"
    ADMIN = "ADMIN"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD = "DEAD"
    CANCELLED = "CANCELLED"


class Coordinate(ContractModel):
    x: int = Field(ge=-100, le=100)
    y: int = Field(ge=-100, le=100)
    z: int = Field(ge=-100, le=100)
    sensationalism: int | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(default=0.0, ge=0, le=1)


class Page(ContractModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class StatusResponse(ContractModel):
    status: str
    id: str | None = None
    version: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class JobAccepted(ContractModel):
    job_id: str = Field(pattern=ULID_PATTERN)
    status: Literal["PENDING"] = "PENDING"


class AuthStartResponse(ContractModel):
    authorization_url: str
    state: str


class UserView(ContractModel):
    id: str = Field(pattern=ULID_PATTERN)
    display_name: str
    role: Role
    consent_complete: bool
    onboarding_complete: bool
    behavioral_profile_active: bool = False


class ConsentView(ContractModel):
    id: str = Field(pattern=ULID_PATTERN)
    purpose: str
    version: str
    body_hash: str
    granted: bool
    sensitive: bool


class ConsentSubmission(ContractModel):
    consent_version_id: str = Field(pattern=ULID_PATTERN)
    granted: bool


class QuestionnaireSubmission(ContractModel):
    questionnaire_version_id: str = Field(pattern=ULID_PATTERN)
    answers: dict[str, int | float | str | bool]


class ProfileView(Coordinate):
    profile_id: str = Field(pattern=ULID_PATTERN)
    kind: Literal["SELF_REPORTED", "BEHAVIORAL"]
    source_version: str
    active: bool


class DemographicsPatch(ContractModel):
    age_band: str | None = None
    gender_response: str | None = None


class DeleteAccountRequest(ContractModel):
    confirmation: Literal["DELETE MY ACCOUNT"]


class FeedItem(ContractModel):
    article_id: str
    issue_id: str
    title: str
    source: str
    coordinate: Coordinate
    reason_code: str
    rank: int


class FeedPage(ContractModel):
    items: list[FeedItem]
    next_cursor: str | None = None
    personalized: bool


class ReadSessionCreate(ContractModel):
    return_path: str = Field(pattern=r"^/.*")

    @field_validator("return_path")
    @classmethod
    def local_path_only(cls, value: str) -> str:
        if value.startswith("//"):
            raise ValueError("return_path must be a local absolute path")
        return value


class ReadSessionView(ContractModel):
    read_session_id: str = Field(pattern=ULID_PATTERN)
    redirect_url: str
    expires_at: datetime


class ReadReturn(ContractModel):
    client_elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class ReadResult(ContractModel):
    status: Literal["eligible", "rejected", "expired"]
    reason_code: str
    server_elapsed_ms: int
    credit_delta: int


class VoteInput(ContractModel):
    x: int = Field(ge=-100, le=100)
    y: int = Field(ge=-100, le=100)
    z: int = Field(ge=-100, le=100)
    sensationalism: int = Field(ge=0, le=100)


class VoteView(VoteInput):
    revision: int
    quality_status: str
    active: bool


class EfficacySubmission(QuestionnaireSubmission):
    pass


class EfficacyView(ContractModel):
    normalized_score: float = Field(ge=0, le=100)
    baseline_delta: float | None
    due_survey: bool


class ShareCardCreate(ContractModel):
    template: str = Field(min_length=1, max_length=40)
    display_name: str | None = Field(default=None, max_length=80)
    political_data_publication_confirmed: Literal[True]


class ShareCardView(ContractModel):
    id: str = Field(pattern=ULID_PATTERN)
    status: Literal["queued", "rendering", "ready", "failed", "revoked"]
    public_token: str | None = None
    etag: str | None = None
    snapshot: dict[str, Any]


class SourceCreate(ContractModel):
    name: str
    source_type: Literal["API", "RSS", "CRAWLER"]
    canonical_url: str
    policy_status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    robots_status: Literal["UNKNOWN", "APPROVED", "REJECTED"] = "UNKNOWN"
    terms_status: Literal["UNKNOWN", "APPROVED", "REJECTED"] = "UNKNOWN"
    active: bool = True


class PatchDocument(ContractModel):
    values: dict[str, Any]
    reason: str = Field(min_length=1, max_length=500)


class ModelCreate(ContractModel):
    alias: str
    provider: str
    actual_model_id: str
    secret_env_name: str | None = None
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"

    @field_validator("secret_env_name")
    @classmethod
    def env_name_only(cls, value: str | None) -> str | None:
        if value is not None and (not value.replace("_", "").isalnum() or value.upper() != value):
            raise ValueError("secret_env_name must be an uppercase environment variable name")
        return value


class WeightCreate(ContractModel):
    weights: dict[str, float]
    guardrails: dict[str, float]
    based_on_revision_id: str | None = None


class ReasonRequest(ContractModel):
    reason: str = Field(min_length=1, max_length=500)


class RollbackRequest(ReasonRequest):
    target_revision_id: str


class SimulationRequest(ContractModel):
    windows: list[Literal[7, 30]] = Field(default_factory=lambda: [7, 30])


class RecommendationGenerate(ContractModel):
    evidence_window_days: int = Field(ge=7, le=365)


class AutopilotSettingsPut(ContractModel):
    mode: Literal["OFF", "RECOMMEND", "LIMITED_AUTO"]
    guardrails: dict[str, float]
    manual_locks: list[str] = Field(default_factory=list)
    reason: str


class MergeIssueRequest(ContractModel):
    target_issue_id: str


class SplitIssueRequest(ContractModel):
    article_ids: list[str] = Field(min_length=1)


class RetryCancelResponse(ContractModel):
    job_id: str
    status: JobStatus


class HealthResponse(ContractModel):
    status: Literal["live", "ready", "not_ready"]
    checks: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
