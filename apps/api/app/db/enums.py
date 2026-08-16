"""Application enums mirrored by database CHECK constraints."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    MEMBER = "MEMBER"
    ANALYST = "ANALYST"
    REVIEWER = "REVIEWER"
    ADMIN = "ADMIN"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"
    PENDING_DELETION = "PENDING_DELETION"


class OAuthProvider(StrEnum):
    KAKAO = "kakao"
    NAVER = "naver"
    GOOGLE = "google"
    MOCK = "mock"


class QuestionnaireKind(StrEnum):
    ONBOARDING = "onboarding"
    EFFICACY = "efficacy"


class ProfileKind(StrEnum):
    SELF_REPORTED = "self_reported_profile"
    BEHAVIORAL = "behavioral_profile"


class SourceType(StrEnum):
    API = "API"
    RSS = "RSS"
    CRAWLER = "CRAWLER"


class SourcePolicyStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AdapterType(StrEnum):
    API = "API"
    RSS = "RSS"
    CRAWLER = "CRAWLER"


class CrawlStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ArticleStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    REMOVED = "removed"
    BLOCKED = "blocked"


class IssueStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    MERGED = "merged"
    CLOSED = "closed"
    ARCHIVED = "archived"


class ModelStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"


class AssessmentStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class RevisionStatus(StrEnum):
    DRAFT = "draft"
    SIMULATION = "simulation"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ScoreStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"


class VoteQualityStatus(StrEnum):
    VALID = "VALID"
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


class ReadSessionStatus(StrEnum):
    CREATED = "CREATED"
    OUTBOUND = "OUTBOUND"
    RETURNED = "RETURNED"
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class CreditStatus(StrEnum):
    POSTED = "posted"
    REVERSED = "reversed"
    VOIDED = "voided"


class RecommendationStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"


class AutoPilotMode(StrEnum):
    OFF = "OFF"
    RECOMMEND = "RECOMMEND"
    LIMITED_AUTO = "LIMITED_AUTO"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD = "DEAD"
    CANCELLED = "CANCELLED"


class ShareCardStatus(StrEnum):
    QUEUED = "queued"
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"
    REVOKED = "revoked"
