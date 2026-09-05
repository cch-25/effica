from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator

ULID_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{26}$"
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


class AnalysisStatus(StrEnum):
    READY = "READY"
    PROCESSING = "PROCESSING"
    PARTIAL = "PARTIAL"
    UNTRUSTED = "UNTRUSTED"


class IssueKind(StrEnum):
    EVENT = "EVENT"
    TOPIC = "TOPIC"


class FreshnessStatus(StrEnum):
    CURRENT = "CURRENT"
    UPDATE_NEEDED = "UPDATE_NEEDED"


class Coordinate(ContractModel):
    x: int = Field(ge=-100, le=100)
    y: int = Field(ge=-100, le=100)
    z: int = Field(ge=-100, le=100)
    sensationalism: int | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(default=0.0, ge=0, le=1)


class Page(ContractModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class JobAccepted(ContractModel):
    job_id: str = Field(pattern=ULID_PATTERN)
    # A replay of an idempotent request can legitimately return a terminal
    # status.  Keep the accepted envelope stable while allowing the durable
    # queue's complete lifecycle rather than validating only first enqueue.
    status: JobStatus = JobStatus.PENDING


class ShareCardJobAccepted(JobAccepted):
    share_card_id: str = Field(pattern=ULID_PATTERN)


class AuthStartResponse(ContractModel):
    authorization_url: str
    state: str


class AdminLoginRequest(ContractModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class UserView(ContractModel):
    id: str = Field(pattern=ULID_PATTERN)
    display_name: str
    role: Role
    consent_complete: bool
    onboarding_complete: bool
    behavioral_profile_active: bool = False


class QuestionnaireVersionView(ContractModel):
    id: str = Field(pattern=ULID_PATTERN)
    kind: Literal["onboarding", "efficacy"]
    version: str
    # Use an internal name to avoid shadowing BaseModel.schema while retaining
    # the stable wire property consumed by generated clients.
    questionnaire_definition: dict[str, Any] = Field(alias="schema_json")
    scoring_json: dict[str, Any]
    active_from: datetime
    # ``keys`` is a compact compatibility projection for local clients.  DB
    # definitions carry the richer schema_json object and may omit it.
    keys: list[str] = Field(default_factory=list)


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
    answers: dict[str, StrictInt | StrictFloat]

    @field_validator("answers")
    @classmethod
    def finite_numeric_answers(
        cls, answers: dict[str, StrictInt | StrictFloat]
    ) -> dict[str, StrictInt | StrictFloat]:
        for key, value in answers.items():
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"answer for {key} must be a finite number")
        return answers


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
    published_at: datetime | None
    analysis_provider: Literal["openai"]
    analysis_status: Literal[AnalysisStatus.READY]
    score_version_id: str
    reason_code: str
    rank: int


class FeedPage(ContractModel):
    items: list[FeedItem]
    next_cursor: str | None = None
    personalized: bool


class ArticleView(ContractModel):
    id: str
    source_id: str
    source: str
    issue_id: str | None = None
    canonical_url: str
    title: str
    author: str | None = None
    summary: str = ""
    published_at: datetime | None = None
    current_version_id: str | None = None
    analysis_status: AnalysisStatus = AnalysisStatus.PROCESSING
    analysis_provider: Literal["openai"] | None = None
    status: str


class ArticleWithCoordinate(ArticleView):
    coordinate: Coordinate | None = None


class ArticlePage(ContractModel):
    items: list[ArticleWithCoordinate]
    next_cursor: str | None = None


class ScoreView(Coordinate):
    id: str
    score_version_id: str | None = None
    article_version_id: str
    weight_revision_id: str | None = None
    version: int | None = None
    components: dict[str, Any]
    components_json: dict[str, Any] | None = None
    status: str
    analysis_provider: Literal["openai"] = "openai"
    analysis_status: Literal[AnalysisStatus.READY] = AnalysisStatus.READY
    created_at: datetime


class IssueView(ContractModel):
    id: str
    title: str
    summary: str
    topic: str = Field(min_length=1, max_length=40)
    status: str
    kind: IssueKind = IssueKind.TOPIC
    source_count: int = Field(default=0, ge=0)
    analysis_status: AnalysisStatus = AnalysisStatus.PROCESSING
    data_as_of: datetime | None = None
    freshness_status: FreshnessStatus = FreshnessStatus.CURRENT
    editorial_priority: int | None = Field(default=None, gt=0)
    version: int
    article_ids: list[str]
    opened_at: datetime
    last_activity_at: datetime


class IssueDistribution(ContractModel):
    minimum_x: int | None = None
    maximum_x: int | None = None
    count: int


class IssueDetailView(IssueView):
    distribution: IssueDistribution


class IssuePage(ContractModel):
    items: list[IssueView]
    next_cursor: str | None = None


class PublicAssessment(ContractModel):
    id: str
    model_alias: str
    actual_model_id: str
    prompt_version: str
    summary: str
    evidence: list[dict[str, Any]]
    confidence: float = Field(ge=0, le=1)
    provider: Literal["openai"]
    created_at: datetime
    synthetic: Literal[False]


class AssessmentPage(ContractModel):
    article_version_id: str | None
    assessments: list[PublicAssessment]


class CommonFactView(ContractModel):
    id: str
    text: str
    article_ids: list[str]
    evidence_refs: list[str] = Field(default_factory=list)


class FramingDimensionView(ContractModel):
    key: str
    label: str


class ArticleFrameView(ContractModel):
    headline_frame: str | None = None
    emphasis: list[str] = Field(default_factory=list)
    omissions_note: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class VoteAxisAggregateView(ContractModel):
    x: float | None = Field(default=None, ge=-100, le=100)
    y: float | None = Field(default=None, ge=-100, le=100)
    z: float | None = Field(default=None, ge=-100, le=100)
    sensationalism: float | None = Field(default=None, ge=0, le=100)


class VoteAggregateView(ContractModel):
    qualified: VoteAxisAggregateView
    qualified_count: int = Field(ge=0)
    small_segments_suppressed: bool
    snapshot_version: int | None = Field(default=None, ge=1)
    generated_at: datetime | None = None
    status: Literal["ready", "pending"]


class ArticleComparisonView(ContractModel):
    article: ArticleView
    score: ScoreView
    assessment: PublicAssessment
    frame: ArticleFrameView
    vote_aggregate: VoteAggregateView


class IssueComparisonIssueView(ContractModel):
    id: str
    version: int = Field(gt=0)
    title: str
    summary: str
    data_as_of: datetime | None
    article_count: int = Field(ge=0)
    source_count: int = Field(ge=0)


class IssueComparisonView(ContractModel):
    issue: IssueComparisonIssueView
    common_facts: list[CommonFactView]
    dimensions: list[FramingDimensionView]
    articles: list[ArticleComparisonView] = Field(min_length=2, max_length=4)
    comparison_version: str
    prompt_version: str
    model_alias: str
    actual_model_id: str
    confidence: float = Field(ge=0, le=1)
    created_at: datetime
    reviewed_at: datetime


class IssueComparisonReviewPreview(ContractModel):
    snapshot_id: str
    issue_id: str
    issue_version: int = Field(gt=0)
    status: str
    prompt_version: str
    model_alias: str
    actual_model_id: str
    common_facts: list[CommonFactView]
    dimensions: list[FramingDimensionView]
    article_frames: dict[str, ArticleFrameView]
    article_version_ids: dict[str, str]
    confidence: float = Field(ge=0, le=1)
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None


class IssueComparisonReviewView(ContractModel):
    snapshot_id: str
    issue_id: str
    issue_version: int = Field(gt=0)
    reviewed_at: datetime
    reviewed_by: str


class VisualizationPoint(ContractModel):
    entity_type: Literal["article", "source", "user"]
    entity_id: str
    label: str
    x: float = Field(ge=-100, le=100)
    y: float = Field(ge=-100, le=100)
    z: float = Field(ge=-100, le=100)
    sensationalism: float | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(ge=0, le=1)


class VisualizationPointPage(ContractModel):
    items: list[VisualizationPoint]
    next_cursor: str | None = None


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


class ProgressView(ContractModel):
    credit_total: int
    level: int = Field(ge=1)
    tier: str
    policy_version: str
    read_article_count: int = Field(ge=0)
    compared_issue_count: int = Field(ge=0)
    source_diversity_count: int = Field(ge=0)
    self_reported_profile: Coordinate | None = None
    behavioral_profile: Coordinate | None = None


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
    # Adapter settings are optional for backward compatibility.  When
    # supplied, the worker receives them through source_adapters.config_json
    # rather than guessing from the source URL.
    adapter_type: Literal["API", "RSS", "CRAWLER"] | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    rate_limit: int | None = Field(default=None, gt=0)
    adapter_active: bool = True
    policy_status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    robots_status: Literal["UNKNOWN", "APPROVED", "REJECTED"] = "UNKNOWN"
    terms_status: Literal["UNKNOWN", "APPROVED", "REJECTED"] = "UNKNOWN"
    active: bool = True
    reason: str = Field(min_length=1, max_length=500)


class PatchDocument(ContractModel):
    values: dict[str, Any]
    reason: str = Field(min_length=1, max_length=500)


class ModelCreate(ContractModel):
    alias: str = "openai-default"
    provider: Literal["openai"] = "openai"
    actual_model_id: str = "gpt-5.6-luna"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "high"
    secret_env_name: Literal["OPENAI_API_KEY"] | None = "OPENAI_API_KEY"
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"

    @field_validator("actual_model_id")
    @classmethod
    def gpt_model_only(cls, value: str) -> str:
        if not value.strip().startswith("gpt-"):
            raise ValueError("actual_model_id must be an OpenAI GPT model ID")
        return value.strip()

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


class SimulationRequest(ReasonRequest):
    windows: list[Literal[7, 30]] = Field(default_factory=lambda: [7, 30])


class RecommendationGenerate(ContractModel):
    evidence_window_days: int = Field(ge=7, le=365)


class AutopilotSettingsPut(ContractModel):
    mode: Literal["OFF", "RECOMMEND", "LIMITED_AUTO"]
    guardrails: dict[str, float]
    manual_locks: list[str] = Field(default_factory=list)
    reason: str


class AutopilotSettingsView(ContractModel):
    mode: Literal["OFF", "RECOMMEND", "LIMITED_AUTO"]
    guardrails: dict[str, float]
    manual_locks: list[str] = Field(default_factory=list)
    version: int
    updated_by: str | None = None
    updated_at: datetime | None = None


class LLMUsagePut(ContractModel):
    enabled: bool
    reason: str = Field(min_length=1, max_length=500)


class LLMUsageView(ContractModel):
    enabled: bool
    status: Literal["RUNNING", "STOPPED"]
    version: int
    cancelled_jobs: int = 0
    updated_by: str | None = None
    updated_at: datetime | None = None


class MergeIssueRequest(ReasonRequest):
    target_issue_id: str


class SplitIssueRequest(ReasonRequest):
    article_ids: list[str] = Field(min_length=1)


class RetryCancelResponse(ContractModel):
    job_id: str
    status: JobStatus


class HealthResponse(ContractModel):
    status: Literal["live", "ready", "not_ready"]
    checks: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
