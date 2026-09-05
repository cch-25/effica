"""SQLAlchemy models for every table in specification chapter 5.

The models intentionally keep relationships out of the persistence boundary.
Services can compose rows with explicit queries, which avoids importing one
domain's repository from another and keeps worker imports lightweight.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BINARY,
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..enums import (
    AdapterType,
    ArticleStatus,
    AssessmentStatus,
    AutoPilotMode,
    ComparisonSnapshotStatus,
    CrawlStatus,
    CreditStatus,
    IssueKind,
    IssueStatus,
    JobStatus,
    ModelStatus,
    OAuthProvider,
    ProfileKind,
    QuestionnaireKind,
    ReadSessionStatus,
    RecommendationStatus,
    RevisionStatus,
    ScoreStatus,
    ShareCardStatus,
    SourcePolicyStatus,
    SourceType,
    UserRole,
    UserStatus,
    VoteQualityStatus,
)
from ..types import BlobPayloadType, TinyIntType
from ..ulid import ULIDType, new_ulid
from ..utc import UTCDateTime, utc_now

_HASH = BINARY(32)


def _id() -> Mapped[str]:
    return mapped_column(ULIDType(), primary_key=True, default=new_ulid, nullable=False)


def _fk(
    target: str,
    *,
    ondelete: str | None = None,
    nullable: bool = False,
    name: str | None = None,
) -> Any:
    return mapped_column(
        ULIDType(),
        ForeignKey(target, ondelete=ondelete, name=name),
        nullable=nullable,
    )


def _timestamp(*, nullable: bool = False, default: Any = utc_now) -> Any:
    return mapped_column(UTCDateTime(), nullable=nullable, default=default)


def _enum(
    enum_cls: type[Any],
    *,
    default: Any = None,
    nullable: bool = False,
    length: int = 32,
    constraint_name: str | None = None,
) -> Any:
    values = [member.value for member in enum_cls]
    enum_type = SAEnum(
        *values,
        name=constraint_name or f"ck_{enum_cls.__name__.lower()}",
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=max(length, *(len(value) for value in values)),
    )
    return mapped_column(enum_type, default=default, nullable=nullable)


def _json(*, nullable: bool = False, default: Any = None) -> Any:
    if default is None and not nullable:
        default = dict
    return mapped_column(JSON, nullable=nullable, default=default)


def _json_check(column: str) -> CheckConstraint:
    return CheckConstraint(f"JSON_VALID({column})", name=f"json_valid_{column}")


def _axis_checks(*, prefix: str = "") -> tuple[CheckConstraint, ...]:
    return tuple(
        CheckConstraint(
            f"{column} BETWEEN -100 AND 100",
            name=f"{prefix}{column}_range",
        )
        for column in ("x", "y", "z")
    )


def _confidence_check() -> CheckConstraint:
    return CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = _id()
    role: Mapped[UserRole] = _enum(UserRole, default=UserRole.MEMBER.value)
    status: Mapped[UserStatus] = _enum(UserStatus, default=UserStatus.ACTIVE.value)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = _timestamp()
    deleted_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)

    __table_args__ = (
        CheckConstraint(
            "(status = 'DELETED' AND deleted_at IS NOT NULL) OR (status <> 'DELETED')",
            name="deleted_status_timestamp",
        ),
    )


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    provider: Mapped[OAuthProvider] = _enum(OAuthProvider, length=16)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
        Index("ix_oauth_accounts_user_id", "user_id"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    token_hash: Mapped[bytes] = mapped_column(_HASH, nullable=False)
    csrf_hash: Mapped[bytes] = mapped_column(_HASH, nullable=False)
    expires_at: Mapped[datetime] = _timestamp()
    revoked_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        Index("ix_sessions_user_expires", "user_id", "expires_at"),
    )


class ConsentVersion(Base):
    __tablename__ = "consent_versions"

    id: Mapped[str] = _id()
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    body_hash: Mapped[bytes] = mapped_column(_HASH, nullable=False)
    active_from: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("purpose", "version", name="uq_consent_versions_purpose_version"),
    )


class UserConsent(Base):
    __tablename__ = "user_consents"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    consent_version_id: Mapped[str] = _fk("consent_versions.id", ondelete="RESTRICT")
    granted_at: Mapped[datetime] = _timestamp()
    withdrawn_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "consent_version_id",
            name="uq_user_consents_user_version",
        ),
    )


class QuestionnaireVersion(Base):
    __tablename__ = "questionnaire_versions"

    id: Mapped[str] = _id()
    kind: Mapped[QuestionnaireKind] = _enum(QuestionnaireKind, length=16)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_json: Mapped[dict[str, Any]] = _json()
    scoring_json: Mapped[dict[str, Any]] = _json()
    active_from: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("kind", "version", name="uq_questionnaire_versions_kind_version"),
        _json_check("schema_json"),
        _json_check("scoring_json"),
    )


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    questionnaire_version_id: Mapped[str] = _fk(
        "questionnaire_versions.id",
        ondelete="RESTRICT",
        name="fk_qresponses_qversion",
    )
    # Encrypted sensitive responses are never represented as JSON or plaintext.
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    submitted_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        Index("ix_questionnaire_responses_user_submitted", "user_id", "submitted_at"),
    )


class UserDemographics(Base):
    __tablename__ = "user_demographics"

    user_id: Mapped[str] = mapped_column(
        ULIDType(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    age_band: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gender_response: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_version_id: Mapped[str] = _fk("consent_versions.id", ondelete="RESTRICT", nullable=True)
    updated_at: Mapped[datetime] = _timestamp()


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    kind: Mapped[ProfileKind] = _enum(ProfileKind, length=32)
    x: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    y: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    z: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        *_axis_checks(),
        _confidence_check(),
        Index("ix_user_profiles_user_kind_active", "user_id", "kind", "active"),
    )


class Source(Base):
    __tablename__ = "sources"

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[SourceType] = _enum(SourceType, length=16)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    policy_status: Mapped[SourcePolicyStatus] = _enum(SourcePolicyStatus, length=16)
    # Crawler permission is two-dimensional.  ``policy_status`` remains the
    # aggregate/source lifecycle status; these fields preserve the individual
    # robots.txt and terms decisions used by the crawler guard.
    robots_status: Mapped[SourcePolicyStatus] = _enum(
        SourcePolicyStatus,
        default=SourcePolicyStatus.PENDING.value,
        length=16,
        constraint_name="robots_status",
    )
    terms_status: Mapped[SourcePolicyStatus] = _enum(
        SourcePolicyStatus,
        default=SourcePolicyStatus.PENDING.value,
        length=16,
        constraint_name="terms_status",
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("canonical_url", name="uq_sources_canonical_url"),)


class SourceAdapter(Base):
    __tablename__ = "source_adapters"

    id: Mapped[str] = _id()
    source_id: Mapped[str] = _fk("sources.id", ondelete="CASCADE")
    adapter_type: Mapped[AdapterType] = _enum(AdapterType, length=16)
    config_json: Mapped[dict[str, Any]] = _json()
    rate_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("source_id", "adapter_type", name="uq_source_adapters_source_type"),
        CheckConstraint("rate_limit IS NULL OR rate_limit > 0", name="positive_rate_limit"),
        _json_check("config_json"),
    )


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[str] = _id()
    source_id: Mapped[str] = _fk("sources.id", ondelete="RESTRICT")
    status: Mapped[CrawlStatus] = _enum(CrawlStatus, default=CrawlStatus.PENDING.value, length=16)
    started_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    finished_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    stats_json: Mapped[dict[str, Any] | None] = _json(nullable=True)
    error_json: Mapped[dict[str, Any] | None] = _json(nullable=True)

    __table_args__ = (
        _json_check("stats_json"),
        _json_check("error_json"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="crawl_finished_after_started",
        ),
    )


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[str] = _id()
    source_id: Mapped[str] = _fk("sources.id", ondelete="RESTRICT")
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url_hash: Mapped[bytes] = mapped_column(_HASH, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    current_version_id: Mapped[str | None] = mapped_column(
        ULIDType(),
        ForeignKey("article_versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    status: Mapped[ArticleStatus] = _enum(
        ArticleStatus, default=ArticleStatus.ACTIVE.value, length=16
    )
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("canonical_url_hash", name="uq_articles_canonical_url_hash"),
        Index("ix_articles_source_published", "source_id", "published_at"),
    )


class ArticleRetentionTombstone(Base):
    __tablename__ = "article_retention_tombstones"

    canonical_url_hash: Mapped[bytes] = mapped_column(_HASH, primary_key=True)
    retired_at: Mapped[datetime] = _timestamp()


class ArticleVersion(Base):
    __tablename__ = "article_versions"

    id: Mapped[str] = _id()
    article_id: Mapped[str] = _fk("articles.id", ondelete="RESTRICT")
    content_hash: Mapped[bytes] = mapped_column(_HASH, nullable=False)
    normalized_text_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Raw adapter payloads may be retained in an object/blob store.  Keep a
    # stable reference and the expiry decision alongside the article version;
    # the payload itself is intentionally not duplicated in this table.
    fetched_at: Mapped[datetime] = _timestamp()
    modified_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)

    __table_args__ = (
        UniqueConstraint("article_id", "content_hash", name="uq_article_versions_article_hash"),
        Index("ix_article_versions_article_fetched", "article_id", "fetched_at"),
    )


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[str] = _id()
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str] = mapped_column(String(40), nullable=False, default="일반")
    status: Mapped[IssueStatus] = _enum(IssueStatus, default=IssueStatus.CANDIDATE.value, length=16)
    issue_kind: Mapped[IssueKind] = _enum(
        IssueKind,
        default=IssueKind.TOPIC.value,
        length=16,
        constraint_name="issue_kind",
    )
    editorial_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    editorial_priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editorial_reviewed_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    editorial_data_as_of: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    opened_at: Mapped[datetime] = _timestamp()
    last_activity_at: Mapped[datetime] = _timestamp()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "editorial_priority IS NULL OR editorial_priority > 0",
            name="positive_editorial_priority",
        ),
        UniqueConstraint("editorial_key", name="uq_issues_editorial_key"),
        Index("ix_issues_topic", "topic"),
        Index("ix_issues_editorial_order", "issue_kind", "editorial_priority"),
    )


class IssueMembership(Base):
    __tablename__ = "issue_memberships"

    issue_id: Mapped[str] = mapped_column(
        ULIDType(),
        ForeignKey("issues.id", ondelete="CASCADE"),
        primary_key=True,
    )
    article_id: Mapped[str] = mapped_column(
        ULIDType(),
        ForeignKey("articles.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (_confidence_check(),)


class IssueComparisonSnapshot(Base):
    __tablename__ = "issue_comparison_snapshots"

    id: Mapped[str] = _id()
    issue_id: Mapped[str] = _fk("issues.id", ondelete="CASCADE")
    issue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_alias_id: Mapped[str] = _fk("model_aliases.id", ondelete="RESTRICT")
    common_facts_json: Mapped[dict[str, Any]] = _json()
    framing_dimensions_json: Mapped[dict[str, Any]] = _json()
    article_frames_json: Mapped[dict[str, Any]] = _json()
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[ComparisonSnapshotStatus] = _enum(
        ComparisonSnapshotStatus,
        default=ComparisonSnapshotStatus.PENDING.value,
        length=16,
    )
    reviewed_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    reviewed_by: Mapped[str | None] = _fk("users.id", ondelete="SET NULL", nullable=True)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint(
            "issue_id",
            "issue_version",
            "prompt_version",
            name="uq_issue_comparison_issue_version_prompt",
        ),
        Index(
            "ix_issue_comparison_public",
            "issue_id",
            "status",
            "reviewed_at",
            "created_at",
        ),
        CheckConstraint("issue_version > 0", name="positive_issue_version"),
        _confidence_check(),
        _json_check("common_facts_json"),
        _json_check("framing_dimensions_json"),
        _json_check("article_frames_json"),
    )


class FactCheckReference(Base):
    __tablename__ = "fact_check_references"

    id: Mapped[str] = _id()
    article_id: Mapped[str] = _fk("articles.id", ondelete="CASCADE")
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    published_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)


class ModelAlias(Base):
    __tablename__ = "model_aliases"

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    id: Mapped[str] = _id()
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ModelStatus] = _enum(ModelStatus, default=ModelStatus.ACTIVE.value, length=16)
    config_json: Mapped[dict[str, Any]] = _json()

    __table_args__ = (
        UniqueConstraint("alias", name="uq_model_aliases_alias"),
        _json_check("config_json"),
    )


class ModelAssessment(Base):
    __tablename__ = "model_assessments"

    id: Mapped[str] = _id()
    article_version_id: Mapped[str] = _fk("article_versions.id", ondelete="RESTRICT")
    model_alias_id: Mapped[str] = _fk("model_aliases.id", ondelete="RESTRICT")
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    x: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    y: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    z: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sensationalism: Mapped[int] = mapped_column(TinyIntType(), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    evidence_json: Mapped[dict[str, Any]] = _json()
    token_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[AssessmentStatus] = _enum(
        AssessmentStatus,
        default=AssessmentStatus.PENDING.value,
        length=16,
    )
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint(
            "article_version_id",
            "model_alias_id",
            "prompt_version",
            name="uq_model_assessments_version_model_prompt",
        ),
        *_axis_checks(),
        CheckConstraint(
            "sensationalism BETWEEN 0 AND 100",
            name="sensationalism_range",
        ),
        _confidence_check(),
        CheckConstraint("token_usage IS NULL OR token_usage >= 0", name="nonnegative_token_usage"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="nonnegative_latency_ms"),
        _json_check("evidence_json"),
    )


class WeightProfileRevision(Base):
    __tablename__ = "weight_profile_revisions"

    id: Mapped[str] = _id()
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RevisionStatus] = _enum(
        RevisionStatus, default=RevisionStatus.DRAFT.value, length=16
    )
    weights_json: Mapped[dict[str, Any]] = _json()
    guardrails_json: Mapped[dict[str, Any]] = _json()
    based_on_revision_id: Mapped[str | None] = _fk(
        "weight_profile_revisions.id",
        ondelete="SET NULL",
        nullable=True,
        name="fk_wprev_based_on",
    )
    created_by: Mapped[str | None] = _fk("users.id", ondelete="SET NULL", nullable=True)
    created_at: Mapped[datetime] = _timestamp()
    published_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)

    __table_args__ = (
        UniqueConstraint("revision", name="uq_weight_profile_revisions_revision"),
        CheckConstraint("revision > 0", name="positive_revision"),
        _json_check("weights_json"),
        _json_check("guardrails_json"),
    )


class ScoreVersion(Base):
    __tablename__ = "score_versions"

    id: Mapped[str] = _id()
    article_version_id: Mapped[str] = _fk("article_versions.id", ondelete="RESTRICT")
    weight_revision_id: Mapped[str] = _fk("weight_profile_revisions.id", ondelete="RESTRICT")
    x: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    y: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    z: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sensationalism: Mapped[int] = mapped_column(TinyIntType(), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    components_json: Mapped[dict[str, Any]] = _json()
    status: Mapped[ScoreStatus] = _enum(ScoreStatus, default=ScoreStatus.DRAFT.value, length=16)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        *_axis_checks(),
        CheckConstraint("sensationalism BETWEEN 0 AND 100", name="sensationalism_range"),
        _confidence_check(),
        _json_check("components_json"),
        # Recalculation is a legitimate immutable snapshot for the same
        # article/weight pair; consumers order this history by created_at/id.
        Index(
            "ix_score_versions_article_weight_created",
            "article_version_id",
            "weight_revision_id",
            "created_at",
        ),
    )


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    article_id: Mapped[str] = _fk("articles.id", ondelete="RESTRICT")
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    x: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    y: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    z: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sensationalism: Mapped[int] = mapped_column(TinyIntType(), nullable=False)
    quality_status: Mapped[VoteQualityStatus] = _enum(
        VoteQualityStatus,
        default=VoteQualityStatus.VALID.value,
        length=16,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint(
            "user_id", "article_id", "revision", name="uq_votes_user_article_revision"
        ),
        Index("ix_votes_user_article_active", "user_id", "article_id", "active"),
        CheckConstraint("revision > 0", name="positive_revision"),
        *_axis_checks(),
        CheckConstraint("sensationalism BETWEEN 0 AND 100", name="sensationalism_range"),
    )


class VoteAggregateSnapshot(Base):
    __tablename__ = "vote_aggregate_snapshots"

    id: Mapped[str] = _id()
    article_id: Mapped[str] = _fk("articles.id", ondelete="RESTRICT")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_json: Mapped[dict[str, Any]] = _json()
    segment_json: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("article_id", "version", name="uq_vote_aggregate_article_version"),
        CheckConstraint("version > 0", name="positive_version"),
        _json_check("aggregate_json"),
        _json_check("segment_json"),
    )


class FeedImpression(Base):
    __tablename__ = "feed_impressions"

    id: Mapped[str] = _id()
    user_id: Mapped[str | None] = _fk("users.id", ondelete="CASCADE", nullable=True)
    article_id: Mapped[str] = _fk("articles.id", ondelete="RESTRICT")
    issue_id: Mapped[str | None] = _fk("issues.id", ondelete="SET NULL", nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        CheckConstraint("rank > 0", name="positive_rank"),
        Index("ix_feed_impressions_user_created", "user_id", "created_at"),
    )


class ReadSession(Base):
    __tablename__ = "read_sessions"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    article_id: Mapped[str] = _fk("articles.id", ondelete="RESTRICT")
    token_hash: Mapped[bytes] = mapped_column(_HASH, nullable=False)
    expires_at: Mapped[datetime] = _timestamp()
    status: Mapped[ReadSessionStatus] = _enum(
        ReadSessionStatus,
        default=ReadSessionStatus.CREATED.value,
        length=16,
    )
    outbound_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    returned_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    client_elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_read_sessions_token_hash"),
        Index("ix_read_sessions_user_expires", "user_id", "expires_at"),
        CheckConstraint(
            "client_elapsed_ms IS NULL OR client_elapsed_ms >= 0",
            name="nonnegative_client_elapsed",
        ),
        CheckConstraint(
            "returned_at IS NULL OR outbound_at IS NULL OR returned_at >= outbound_at",
            name="read_return_after_outbound",
        ),
    )


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # The domain ledger is append-only: a reversal is a new REVERSAL event
    # linked through ``reversed_ledger_id``.  ``status`` is retained for the
    # persisted/admin contract and defaults to POSTED for service-created
    # entries whose payload has no separate status field.
    status: Mapped[CreditStatus] = _enum(CreditStatus, default=CreditStatus.POSTED.value, length=16)
    reversed_ledger_id: Mapped[str | None] = _fk(
        "credit_ledger.id", ondelete="RESTRICT", nullable=True
    )
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "event_type",
            "event_key",
            name="uq_credit_ledger_user_event",
        ),
        CheckConstraint(
            "(status = 'reversed' AND reversed_ledger_id IS NOT NULL) OR (status <> 'reversed')",
            name="reversal_reference",
        ),
        # A source ledger entry can be compensated at most once.  NULL values
        # on ordinary posted rows remain reusable under SQL unique semantics.
        UniqueConstraint(
            "reversed_ledger_id",
            name="uq_credit_ledger_reversed_source",
        ),
        Index("ix_credit_ledger_user_created", "user_id", "created_at"),
    )


class TierSnapshot(Base):
    __tablename__ = "tier_snapshots"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    credit_total: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        CheckConstraint("credit_total >= 0", name="nonnegative_credit_total"),
        CheckConstraint("level >= 0", name="nonnegative_level"),
    )


class EfficacyResponse(Base):
    __tablename__ = "efficacy_responses"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    questionnaire_version_id: Mapped[str] = _fk(
        "questionnaire_versions.id",
        ondelete="RESTRICT",
        name="fk_efficacy_qversion",
    )
    normalized_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    submitted_at: Mapped[datetime] = _timestamp()


class EfficacyAggregateSnapshot(Base):
    __tablename__ = "efficacy_aggregate_snapshots"

    id: Mapped[str] = _id()
    cohort_key: Mapped[str] = mapped_column(String(255), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    aggregate_json: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("cohort_key", "period", name="uq_efficacy_aggregate_cohort_period"),
        _json_check("aggregate_json"),
    )


class WeightEvidenceSnapshot(Base):
    """Immutable evidence input captured before a weight recommendation.

    Evidence is kept in its own append-only row so a recommendation can be
    reproduced after source aggregates or model outputs change.  The worker
    owns the immutability convention (rows are never updated or deleted); the
    FK from recommendations also prevents a referenced snapshot from being
    removed accidentally.
    """

    __tablename__ = "weight_evidence_snapshots"

    id: Mapped[str] = _id()
    evidence_json: Mapped[dict[str, Any]] = _json()
    window_start: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    window_end: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        _json_check("evidence_json"),
        CheckConstraint(
            "window_end IS NULL OR window_start IS NULL OR window_end >= window_start",
            name="evidence_window_order",
        ),
    )


class WeightRecommendation(Base):
    __tablename__ = "weight_recommendations"

    id: Mapped[str] = _id()
    base_revision_id: Mapped[str] = _fk(
        "weight_profile_revisions.id",
        ondelete="RESTRICT",
        name="fk_wrecommend_base",
    )
    proposed_weights_json: Mapped[dict[str, Any]] = _json()
    evidence_snapshot_id: Mapped[str | None] = mapped_column(
        ULIDType(),
        ForeignKey(
            "weight_evidence_snapshots.id",
            ondelete="RESTRICT",
            name="fk_weight_recommendations_evidence_snapshot",
        ),
        nullable=True,
    )
    provider_assessment_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[RecommendationStatus] = _enum(
        RecommendationStatus,
        default=RecommendationStatus.PENDING_REVIEW.value,
        length=16,
    )
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (_json_check("proposed_weights_json"),)


class WeightSimulation(Base):
    __tablename__ = "weight_simulations"

    id: Mapped[str] = _id()
    recommendation_id: Mapped[str] = _fk("weight_recommendations.id", ondelete="CASCADE")
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = _json()
    guardrail_result: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        CheckConstraint("window_days > 0", name="positive_window_days"),
        _json_check("metrics_json"),
        _json_check("guardrail_result"),
    )


class AutopilotSetting(Base):
    __tablename__ = "autopilot_settings"

    id: Mapped[str] = _id()
    # There is one mutable settings resource, versioned for If-Match updates.
    # A unique key prevents accidental creation of a second settings row.
    singleton_key: Mapped[str] = mapped_column(
        String(32), nullable=False, default="global", server_default="global"
    )
    mode: Mapped[AutoPilotMode] = _enum(AutoPilotMode, default=AutoPilotMode.OFF.value, length=16)
    guardrails_json: Mapped[dict[str, Any]] = _json()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = _fk("users.id", ondelete="SET NULL", nullable=True)
    updated_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("singleton_key", name="uq_autopilot_settings_singleton_key"),
        CheckConstraint("version > 0", name="positive_version"),
        _json_check("guardrails_json"),
    )


class RuntimeControl(Base):
    __tablename__ = "runtime_controls"

    id: Mapped[str] = _id()
    singleton_key: Mapped[str] = mapped_column(
        String(32), nullable=False, default="global", server_default="global"
    )
    llm_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = _fk("users.id", ondelete="SET NULL", nullable=True)
    updated_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("singleton_key", name="uq_runtime_controls_singleton_key"),
        CheckConstraint("version > 0", name="positive_runtime_control_version"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = _id()
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[JobStatus] = _enum(JobStatus, default=JobStatus.PENDING.value, length=16)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = _timestamp()
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    payload_json: Mapped[dict[str, Any]] = _json()
    last_error_json: Mapped[dict[str, Any] | None] = _json(nullable=True)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("job_type", "dedupe_key", name="uq_jobs_type_dedupe"),
        Index("ix_jobs_status_available_priority", "status", "available_at", "priority"),
        CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
        CheckConstraint("max_attempts > 0", name="positive_max_attempts"),
        _json_check("payload_json"),
        _json_check("last_error_json"),
    )


class JobReceipt(Base):
    __tablename__ = "job_receipts"

    job_id: Mapped[str] = mapped_column(ULIDType(), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    result_json: Mapped[dict[str, Any]] = _json()
    applied_at: Mapped[datetime] = _timestamp()


class AdminRequestReceipt(Base):
    __tablename__ = "admin_request_receipts"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_json: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _timestamp()


class ShareCard(Base):
    __tablename__ = "share_cards"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id", ondelete="CASCADE")
    public_token_hash: Mapped[bytes] = mapped_column(_HASH, nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    snapshot_json: Mapped[dict[str, Any]] = _json()
    status: Mapped[ShareCardStatus] = _enum(
        ShareCardStatus,
        default=ShareCardStatus.QUEUED.value,
        length=16,
    )
    blob_id: Mapped[str | None] = _fk("stored_blobs.id", ondelete="SET NULL", nullable=True)
    expires_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    revoked_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("public_token_hash", name="uq_share_cards_public_token_hash"),
        _json_check("snapshot_json"),
    )


class StoredBlob(Base):
    __tablename__ = "stored_blobs"

    id: Mapped[str] = _id()
    sha256: Mapped[bytes] = mapped_column(_HASH, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[bytes] = mapped_column(BlobPayloadType(), nullable=False)
    expires_at: Mapped[datetime | None] = _timestamp(nullable=True, default=None)
    created_at: Mapped[datetime] = _timestamp()

    __table_args__ = (
        UniqueConstraint("sha256", name="uq_stored_blobs_sha256"),
        CheckConstraint("byte_size >= 0", name="nonnegative_byte_size"),
        CheckConstraint("byte_size <= 10485760", name="blob_size_limit"),
        CheckConstraint(
            "byte_size = OCTET_LENGTH(payload)", name="blob_byte_size_matches_payload"
        ),
    )


# Public aliases used by callers that prefer the table's pluralized domain
# name.  The canonical class names remain singular SQLAlchemy entities.


__all__ = [
    "Article",
    "ArticleVersion",
    "AutopilotSetting",
    "ConsentVersion",
    "CrawlRun",
    "CreditLedger",
    "EfficacyAggregateSnapshot",
    "EfficacyResponse",
    "FactCheckReference",
    "FeedImpression",
    "Issue",
    "IssueComparisonSnapshot",
    "IssueMembership",
    "Job",
    "ModelAlias",
    "ModelAssessment",
    "OAuthAccount",
    "QuestionnaireResponse",
    "QuestionnaireVersion",
    "ReadSession",
    "ScoreVersion",
    "Session",
    "ShareCard",
    "Source",
    "SourceAdapter",
    "StoredBlob",
    "TierSnapshot",
    "User",
    "UserConsent",
    "UserDemographics",
    "UserProfile",
    "Vote",
    "VoteAggregateSnapshot",
    "WeightProfileRevision",
    "WeightEvidenceSnapshot",
    "WeightRecommendation",
    "WeightSimulation",
]
