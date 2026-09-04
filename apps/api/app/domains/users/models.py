"""Domain value objects for users, consent, onboarding, and privacy jobs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ...core.security import Role, new_identifier, utc_now


class UserStatus(str, Enum):
    ACTIVE = "active"
    DELETION_PENDING = "deletion_pending"
    DELETED = "deleted"


class ConsentPurpose(str, Enum):
    SERVICE = "service"
    SENSITIVE_POLITICAL = "sensitive_political"
    # Compatibility spelling used by the API contract's public purpose name.
    POLITICAL_PROFILE = "sensitive_political"
    SENSITIVE = "sensitive_political"
    BEHAVIORAL_PROFILE = "behavioral_profile"
    DEMOGRAPHICS = "demographics"


class ProfileKind(str, Enum):
    SELF_REPORTED = "self_reported_profile"
    BEHAVIORAL = "behavioral_profile"


class JobKind(str, Enum):
    EXPORT = "export_user"
    DELETE = "delete_user"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class User:
    id: str = field(default_factory=new_identifier)
    role: Role = Role.MEMBER
    status: UserStatus = UserStatus.ACTIVE
    display_name: str | None = None
    email: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None
    personalization_enabled: bool = False
    behavioral_profile_enabled: bool = False

    @property
    def active(self) -> bool:
        return self.status is UserStatus.ACTIVE


@dataclass(frozen=True)
class OAuthAccount:
    id: str
    user_id: str
    provider: str
    provider_subject: str
    created_at: datetime


@dataclass(frozen=True)
class ConsentVersion:
    id: str
    purpose: ConsentPurpose
    version: str
    body_hash: str
    active_from: datetime


@dataclass
class UserConsent:
    id: str
    user_id: str
    consent_version_id: str
    purpose: ConsentPurpose
    granted_at: datetime | None = None
    withdrawn_at: datetime | None = None

    @property
    def granted(self) -> bool:
        return self.granted_at is not None and self.withdrawn_at is None


@dataclass(frozen=True)
class QuestionSpec:
    """Versioned question-to-axis scoring definition."""

    id: str
    axis: str
    required: bool = True
    scale_min: float = 1.0
    scale_max: float = 5.0
    weight: float = 1.0
    reverse: bool = False
    options: Mapping[str, float] | None = None

    def validate(self) -> None:
        if self.axis not in {"x", "y", "z"}:
            raise ValueError("question axis must be x, y, or z")
        try:
            scale_min = float(self.scale_min)
            scale_max = float(self.scale_max)
            weight = float(self.weight)
        except (TypeError, ValueError) as exc:
            raise ValueError("question scale and weight must be numeric") from exc
        if not all(math.isfinite(value) for value in (scale_min, scale_max, weight)):
            raise ValueError("question scale and weight must be finite")
        if scale_max <= scale_min:
            raise ValueError("question scale_max must be greater than scale_min")
        if weight <= 0:
            raise ValueError("question weight must be positive")
        if self.options is not None:
            if not self.options:
                raise ValueError("question options cannot be empty")
            for option_value in self.options.values():
                try:
                    numeric = float(option_value)
                except (TypeError, ValueError) as exc:
                    raise ValueError("question options must be numeric") from exc
                if isinstance(option_value, bool) or not math.isfinite(numeric):
                    raise ValueError("question options must be finite numeric values")


@dataclass(frozen=True)
class QuestionnaireVersion:
    id: str
    kind: str
    version: str
    questions: tuple[QuestionSpec, ...]
    active_from: datetime = field(default_factory=utc_now)
    active: bool = True

    def validate(self) -> None:
        if not self.questions:
            raise ValueError("questionnaire must contain at least one question")
        ids: set[str] = set()
        for question in self.questions:
            question.validate()
            if question.id in ids:
                raise ValueError("questionnaire question IDs must be unique")
            ids.add(question.id)


@dataclass(frozen=True)
class QuestionnaireScore:
    x: float
    y: float
    z: float
    confidence: float
    answered_count: int
    question_count: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "confidence": self.confidence,
            "answered_count": self.answered_count,
            "question_count": self.question_count,
        }


@dataclass(frozen=True)
class QuestionnaireResponse:
    id: str
    user_id: str
    questionnaire_version_id: str
    # The repository should encrypt this mapping before persistence.  It is
    # retained in memory only so local tests can exercise export/withdrawal.
    answers: Mapping[str, Any]
    score: QuestionnaireScore
    submitted_at: datetime


@dataclass
class UserProfile:
    id: str
    user_id: str
    kind: ProfileKind
    x: float
    y: float
    z: float
    confidence: float
    source_version: str
    active: bool
    created_at: datetime

    def coordinates(self) -> tuple[float, float, float]:
        return self.x, self.y, self.z


@dataclass
class UserDemographics:
    user_id: str
    age_band: str | None = None
    gender_response: str | None = None
    consent_version_id: str | None = None
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class PrivacyJob:
    id: str
    user_id: str
    kind: JobKind
    status: JobStatus
    requested_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    result: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class OnboardingState:
    service_consent_granted: bool
    sensitive_consent_granted: bool
    questionnaire_completed: bool
    demographics_submitted: bool
    self_reported_profile_active: bool
    behavioral_profile_active: bool


__all__ = [
    "ConsentPurpose",
    "ConsentVersion",
    "JobKind",
    "JobStatus",
    "OAuthAccount",
    "OnboardingState",
    "PrivacyJob",
    "ProfileKind",
    "QuestionSpec",
    "QuestionnaireResponse",
    "QuestionnaireScore",
    "QuestionnaireVersion",
    "User",
    "UserConsent",
    "UserDemographics",
    "UserProfile",
    "UserStatus",
]
