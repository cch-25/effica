"""User, consent, onboarding, and data-rights services.

These services use an in-memory repository by default so the mock OAuth
integration flow is deterministic and external-network/database free.  The
repository-shaped methods are intentionally small and can be backed by the
SQLAlchemy models without changing route-level calls.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any

from ...core.security import Role, SessionStore, new_identifier, normalize_role, utc_now
from .models import (
    ConsentPurpose,
    ConsentVersion,
    JobKind,
    JobStatus,
    OAuthAccount,
    OnboardingState,
    PrivacyJob,
    ProfileKind,
    QuestionnaireResponse,
    QuestionnaireScore,
    QuestionnaireVersion,
    QuestionSpec,
    User,
    UserConsent,
    UserDemographics,
    UserProfile,
    UserStatus,
)


class UserDomainError(Exception):
    """Base user-domain error."""


class UserNotFoundError(UserDomainError):
    pass


class UserInactiveError(UserDomainError):
    pass


class ConsentRequiredError(UserDomainError):
    """Raised before processing a sensitive purpose without consent."""


class ConsentVersionNotFoundError(UserDomainError):
    pass


class QuestionnaireValidationError(UserDomainError):
    pass


class QuestionnaireVersionStaleError(UserDomainError):
    pass


class DeletionConfirmationError(UserDomainError):
    pass


class PrivacyJobNotFoundError(UserDomainError):
    pass


def _purpose(value: ConsentPurpose | str) -> ConsentPurpose:
    if isinstance(value, ConsentPurpose):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"political_profile", "political", "sensitive", "sensitive_political"}:
        return ConsentPurpose.SENSITIVE_POLITICAL
    try:
        return ConsentPurpose(normalized)
    except ValueError as exc:
        raise ValueError(f"unknown consent purpose: {value}") from exc


def _clamp(value: float, lower: float = -100.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _consent_sort_time(item: UserConsent) -> datetime:
    """Aware timestamp for consent history ordering; never compare naive min."""

    stamp = item.granted_at
    if stamp is None:
        return datetime.min.replace(tzinfo=UTC)
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=UTC)
    return stamp


def _numeric_answer(question: QuestionSpec, answer: Any) -> float:
    if question.options is not None:
        if isinstance(answer, str) and answer in question.options:
            answer = question.options[answer]
        elif answer not in question.options.values():
            raise QuestionnaireValidationError(f"answer for {question.id} is not a valid option")
    # Numeric strings and booleans are not numeric questionnaire answers. A
    # string is accepted only when it is an explicit option label above.
    if isinstance(answer, (str, bool)) or not isinstance(answer, Real):
        raise QuestionnaireValidationError(f"answer for {question.id} must be numeric")
    try:
        value = float(answer)
    except (TypeError, ValueError) as exc:
        raise QuestionnaireValidationError(f"answer for {question.id} must be numeric") from exc
    if not math.isfinite(value):
        raise QuestionnaireValidationError(f"answer for {question.id} must be finite")
    if value < question.scale_min or value > question.scale_max:
        raise QuestionnaireValidationError(
            f"answer for {question.id} must be between {question.scale_min} "
            f"and {question.scale_max}"
        )
    return value


def score_questionnaire(
    questionnaire: QuestionnaireVersion,
    answers: Mapping[str, Any],
) -> QuestionnaireScore:
    """Validate versioned answers and normalize each axis to ``-100..100``."""

    questionnaire.validate()
    if not isinstance(answers, Mapping):
        raise QuestionnaireValidationError("answers must be an object")
    expected = {question.id for question in questionnaire.questions}
    unknown = set(answers).difference(expected)
    if unknown:
        raise QuestionnaireValidationError(
            "unknown questionnaire answers: {}".format(", ".join(sorted(unknown)))
        )
    totals = {"x": 0.0, "y": 0.0, "z": 0.0}
    weights = {"x": 0.0, "y": 0.0, "z": 0.0}
    answered = 0
    for question in questionnaire.questions:
        present = question.id in answers and answers[question.id] is not None
        if not present:
            if question.required:
                raise QuestionnaireValidationError(f"missing required answer: {question.id}")
            continue
        value = _numeric_answer(question, answers[question.id])
        normalized = (
            (value - question.scale_min) / (question.scale_max - question.scale_min)
        ) * 200.0 - 100.0
        if question.reverse:
            normalized = -normalized
        axis = question.axis
        totals[axis] += normalized * question.weight
        weights[axis] += question.weight
        answered += 1
    if not answered:
        raise QuestionnaireValidationError("at least one questionnaire answer is required")
    coordinates = {
        axis: _clamp(totals[axis] / weights[axis]) if weights[axis] else 0.0 for axis in totals
    }
    # Confidence denotes answer coverage/quality, not certainty about a user's
    # identity.  A complete version scores 1.0; optional omissions lower it.
    confidence = round(answered / len(questionnaire.questions), 6)
    return QuestionnaireScore(
        x=round(coordinates["x"], 6),
        y=round(coordinates["y"], 6),
        z=round(coordinates["z"], 6),
        confidence=confidence,
        answered_count=answered,
        question_count=len(questionnaire.questions),
    )


class InMemoryUserRepository:
    """Thread-safe repository used by local flows and unit tests."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.oauth_accounts: dict[tuple[str, str], OAuthAccount] = {}
        self.consent_versions: dict[str, ConsentVersion] = {}
        self.consents: dict[str, UserConsent] = {}
        self.questionnaires: dict[str, QuestionnaireVersion] = {}
        self.responses: dict[str, QuestionnaireResponse] = {}
        self.profiles: dict[str, UserProfile] = {}
        self.demographics: dict[str, UserDemographics] = {}
        self.jobs: dict[str, PrivacyJob] = {}
        self._lock = threading.RLock()

    def create_user(
        self,
        *,
        display_name: str | None = None,
        email: str | None = None,
        role: Role | str = Role.MEMBER,
    ) -> User:
        user = User(display_name=display_name, email=email, role=normalize_role(role))
        with self._lock:
            self.users[user.id] = user
        return user

    def get_user(self, user_id: str) -> User:
        try:
            return self.users[str(user_id)]
        except KeyError as exc:
            raise UserNotFoundError("user not found") from exc

    def active_user(self, user_id: str) -> User:
        user = self.get_user(user_id)
        if not user.active:
            raise UserInactiveError("user is not active")
        return user

    def find_oauth_account(self, provider: str, subject: str) -> OAuthAccount | None:
        return self.oauth_accounts.get((provider.lower(), subject))

    def link_oauth_account(self, user_id: str, provider: str, subject: str) -> OAuthAccount:
        if not provider or not subject:
            raise ValueError("OAuth provider and subject are required")
        self.active_user(user_id)
        key = (provider.strip().lower(), subject)
        existing = self.oauth_accounts.get(key)
        if existing is not None:
            if existing.user_id != str(user_id):
                raise UserDomainError("OAuth account is already linked")
            return existing
        account = OAuthAccount(
            id=new_identifier(),
            user_id=str(user_id),
            provider=key[0],
            provider_subject=subject,
            created_at=utc_now(),
        )
        with self._lock:
            self.oauth_accounts[key] = account
        return account

    def add_consent_version(
        self,
        *,
        purpose: ConsentPurpose | str,
        version: str,
        body_hash: str,
        active_from: datetime | None = None,
        id: str | None = None,
    ) -> ConsentVersion:
        item = ConsentVersion(
            id=id or new_identifier(),
            purpose=_purpose(purpose),
            version=version,
            body_hash=body_hash,
            active_from=active_from or utc_now(),
        )
        if not version or not body_hash:
            raise ValueError("consent version and body_hash are required")
        with self._lock:
            self.consent_versions[item.id] = item
        return item

    def active_consent_version(
        self,
        purpose: ConsentPurpose | str,
        *,
        now: datetime | None = None,
    ) -> ConsentVersion | None:
        target = _purpose(purpose)
        current = now or utc_now()
        candidates = [
            item
            for item in self.consent_versions.values()
            if item.purpose is target and item.active_from <= current
        ]
        return max(candidates, key=lambda item: item.active_from) if candidates else None

    def add_questionnaire_version(self, item: QuestionnaireVersion) -> QuestionnaireVersion:
        item.validate()
        with self._lock:
            self.questionnaires[item.id] = item
        return item

    def active_questionnaire_version(self, kind: str) -> QuestionnaireVersion | None:
        candidates = [
            item for item in self.questionnaires.values() if item.kind == kind and item.active
        ]
        return max(candidates, key=lambda item: item.active_from) if candidates else None

    def user_consents(
        self,
        user_id: str,
        purpose: ConsentPurpose | None = None,
    ) -> list[UserConsent]:
        return [
            item
            for item in self.consents.values()
            if item.user_id == str(user_id) and (purpose is None or item.purpose is purpose)
        ]

    def add_consent(self, item: UserConsent) -> UserConsent:
        with self._lock:
            self.consents[item.id] = item
        return item

    def latest_granted_consent(
        self,
        user_id: str,
        purpose: ConsentPurpose | str,
    ) -> UserConsent | None:
        target = _purpose(purpose)
        candidates = [item for item in self.user_consents(user_id, target) if item.granted]
        return max(candidates, key=_consent_sort_time) if candidates else None


@dataclass(frozen=True)
class QuestionnaireSubmission:
    response: QuestionnaireResponse
    profile: UserProfile


class UserService:
    def __init__(self, repository: InMemoryUserRepository | None = None):
        self.repository = repository or InMemoryUserRepository()

    def create_user(
        self,
        *,
        display_name: str | None = None,
        email: str | None = None,
        role: Role | str = Role.MEMBER,
    ) -> User:
        return self.repository.create_user(display_name=display_name, email=email, role=role)

    def get_user(self, user_id: str) -> User:
        return self.repository.get_user(user_id)

    def require_active(self, user_id: str) -> User:
        return self.repository.active_user(user_id)

    def find_or_create_oauth_user(
        self,
        *,
        provider: str,
        subject: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> tuple[User, OAuthAccount, bool]:
        existing = self.repository.find_oauth_account(provider, subject)
        if existing:
            user = self.repository.get_user(existing.user_id)
            if not user.active:
                raise UserInactiveError("user is not active")
            if user.email is None and email:
                user.email = email
            if user.display_name is None and display_name:
                user.display_name = display_name
            return user, existing, False
        user = self.create_user(display_name=display_name, email=email)
        account = self.repository.link_oauth_account(user.id, provider, subject)
        return user, account, True

    def onboarding_state(self, user_id: str) -> OnboardingState:
        user = self.require_active(user_id)
        service = self.repository.latest_granted_consent(user.id, ConsentPurpose.SERVICE)
        sensitive = self.repository.latest_granted_consent(
            user.id,
            ConsentPurpose.SENSITIVE_POLITICAL,
        )
        questionnaire = any(
            response.user_id == user.id for response in self.repository.responses.values()
        )
        demographics = user.id in self.repository.demographics
        self_profile = any(
            profile.user_id == user.id
            and profile.kind is ProfileKind.SELF_REPORTED
            and profile.active
            for profile in self.repository.profiles.values()
        )
        behavioral = any(
            profile.user_id == user.id and profile.kind is ProfileKind.BEHAVIORAL and profile.active
            for profile in self.repository.profiles.values()
        )
        return OnboardingState(
            service_consent_granted=service is not None,
            sensitive_consent_granted=sensitive is not None,
            questionnaire_completed=questionnaire,
            demographics_submitted=demographics,
            self_reported_profile_active=self_profile,
            behavioral_profile_active=behavioral,
        )


class ConsentService:
    def __init__(self, repository: InMemoryUserRepository, users: UserService | None = None):
        self.repository = repository
        self.users = users or UserService(repository)

    def _version(self, consent_version_id: str) -> ConsentVersion:
        try:
            return self.repository.consent_versions[consent_version_id]
        except KeyError as exc:
            raise ConsentVersionNotFoundError("consent version not found") from exc

    def grant(self, user_id: str, consent_version_id: str, granted: bool = True) -> UserConsent:
        user = self.users.require_active(user_id)
        version = self._version(consent_version_id)
        if not granted:
            self.withdraw(user.id, version.purpose)
            # Return a clear historical record for route responses.
            history = self.repository.user_consents(user.id, version.purpose)
            if history:
                return max(history, key=_consent_sort_time)
            item = UserConsent(
                id=new_identifier(),
                user_id=user.id,
                consent_version_id=version.id,
                purpose=version.purpose,
                withdrawn_at=utc_now(),
            )
            self.repository.add_consent(item)
            return item
        now = utc_now()
        for prior in self.repository.user_consents(user.id, version.purpose):
            if prior.granted:
                prior.withdrawn_at = now
        item = UserConsent(
            id=new_identifier(),
            user_id=user.id,
            consent_version_id=version.id,
            purpose=version.purpose,
            granted_at=now,
        )
        self.repository.add_consent(item)
        return item

    record = grant

    def withdraw(
        self,
        user_id: str,
        purpose: ConsentPurpose | str,
    ) -> UserConsent | None:
        user = self.users.require_active(user_id)
        target = _purpose(purpose)
        now = utc_now()
        latest: UserConsent | None = None
        for item in self.repository.user_consents(user.id, target):
            if item.granted:
                item.withdrawn_at = now
                latest = item
        self._apply_withdrawal_effects(user, target)
        return latest

    withdraw_consent = withdraw

    def has_consent(
        self,
        user_id: str,
        purpose: ConsentPurpose | str,
        *,
        consent_version_id: str | None = None,
    ) -> bool:
        user = self.users.require_active(user_id)
        target = _purpose(purpose)
        consent = self.repository.latest_granted_consent(user.id, target)
        if consent is None:
            return False
        if consent_version_id is not None and consent.consent_version_id != consent_version_id:
            return False
        return True

    def require_consent(
        self,
        user_id: str,
        purpose: ConsentPurpose | str,
        *,
        consent_version_id: str | None = None,
    ) -> UserConsent:
        if not self.has_consent(user_id, purpose, consent_version_id=consent_version_id):
            raise ConsentRequiredError("consent is required for this purpose")
        consent = self.repository.latest_granted_consent(user_id, _purpose(purpose))
        assert consent is not None  # guarded above
        return consent

    def _apply_withdrawal_effects(self, user: User, purpose: ConsentPurpose) -> None:
        if purpose in {
            ConsentPurpose.SERVICE,
            ConsentPurpose.SENSITIVE_POLITICAL,
            ConsentPurpose.BEHAVIORAL_PROFILE,
        }:
            user.personalization_enabled = False
            user.behavioral_profile_enabled = False
        for profile in self.repository.profiles.values():
            if profile.user_id != user.id:
                continue
            if purpose in {ConsentPurpose.SERVICE, ConsentPurpose.BEHAVIORAL_PROFILE}:
                if profile.kind is ProfileKind.BEHAVIORAL:
                    profile.active = False
            if purpose is ConsentPurpose.SENSITIVE_POLITICAL:
                # Both political coordinate forms are sensitive; withdrawing
                # the dedicated consent removes them from active use.
                profile.active = False


class QuestionnaireService:
    def __init__(
        self,
        repository: InMemoryUserRepository,
        consents: ConsentService,
        users: UserService | None = None,
    ):
        self.repository = repository
        self.consents = consents
        self.users = users or UserService(repository)

    def submit(
        self,
        user_id: str,
        questionnaire_version_id: str,
        answers: Mapping[str, Any],
        *,
        require_sensitive_consent: bool = True,
    ) -> QuestionnaireSubmission:
        user = self.users.require_active(user_id)
        try:
            version = self.repository.questionnaires[questionnaire_version_id]
        except KeyError as exc:
            raise QuestionnaireVersionStaleError("questionnaire version not found") from exc
        current = self.repository.active_questionnaire_version(version.kind)
        if not version.active or current is None or current.id != version.id:
            raise QuestionnaireVersionStaleError("questionnaire version is stale")
        if require_sensitive_consent:
            self.consents.require_consent(user.id, ConsentPurpose.SENSITIVE_POLITICAL)
        score = score_questionnaire(version, answers)
        response = QuestionnaireResponse(
            id=new_identifier(),
            user_id=user.id,
            questionnaire_version_id=version.id,
            answers=dict(answers),
            score=score,
            submitted_at=utc_now(),
        )
        for prior in self.repository.responses.values():
            if prior.user_id == user.id and prior.questionnaire_version_id == version.id:
                # Responses are immutable records; a later submission is a new
                # record and the latest profile points at it.
                pass
        profile = UserProfile(
            id=new_identifier(),
            user_id=user.id,
            kind=ProfileKind.SELF_REPORTED,
            x=score.x,
            y=score.y,
            z=score.z,
            confidence=score.confidence,
            source_version=version.version,
            active=True,
            created_at=utc_now(),
        )
        for prior_profile in self.repository.profiles.values():
            if prior_profile.user_id == user.id and prior_profile.kind is ProfileKind.SELF_REPORTED:
                prior_profile.active = False
        self.repository.responses[response.id] = response
        self.repository.profiles[profile.id] = profile
        return QuestionnaireSubmission(response=response, profile=profile)

    submit_response = submit

    def update_demographics(
        self,
        user_id: str,
        *,
        age_band: str | None = None,
        gender_response: str | None = None,
        consent_version_id: str | None = None,
    ) -> UserDemographics:
        user = self.users.require_active(user_id)
        # Demographics are optional; an explicit consent ID is metadata for the
        # selected version but not a prerequisite for refusing the fields.
        if consent_version_id is not None:
            version = self.repository.consent_versions.get(consent_version_id)
            if version is None or version.purpose is not ConsentPurpose.DEMOGRAPHICS:
                raise ConsentVersionNotFoundError("demographics consent version not found")
        item = self.repository.demographics.get(user.id) or UserDemographics(user_id=user.id)
        item.age_band = age_band
        item.gender_response = gender_response
        item.consent_version_id = consent_version_id
        item.updated_at = utc_now()
        self.repository.demographics[user.id] = item
        return item


class PrivacyService:
    """Asynchronous export/deletion request boundary.

    ``request_*`` only queues a job.  A worker or local test calls
    ``process_job`` to execute it, mirroring the MariaDB job-queue contract.
    """

    DELETE_CONFIRMATION = "DELETE MY ACCOUNT"

    def __init__(
        self,
        repository: InMemoryUserRepository,
        users: UserService | None = None,
        *,
        sessions: SessionStore | None = None,
        revoke_user_sessions: Callable[[str], Any] | None = None,
    ):
        self.repository = repository
        self.users = users or UserService(repository)
        self.sessions = sessions
        self._revoke_user_sessions = revoke_user_sessions

    def _queue(self, user_id: str, kind: JobKind) -> PrivacyJob:
        user = self.users.require_active(user_id)
        job = PrivacyJob(
            id=new_identifier(),
            user_id=user.id,
            kind=kind,
            status=JobStatus.QUEUED,
            requested_at=utc_now(),
        )
        self.repository.jobs[job.id] = job
        return job

    def request_export(self, user_id: str) -> PrivacyJob:
        return self._queue(user_id, JobKind.EXPORT)

    enqueue_export = request_export

    def request_deletion(self, user_id: str, confirmation: str) -> PrivacyJob:
        if confirmation != self.DELETE_CONFIRMATION:
            raise DeletionConfirmationError("account deletion confirmation does not match")
        job = self._queue(user_id, JobKind.DELETE)
        user = self.repository.get_user(user_id)
        user.status = UserStatus.DELETION_PENDING
        if self.sessions:
            self.sessions.revoke_user(user.id)
        if self._revoke_user_sessions:
            self._revoke_user_sessions(user.id)
        return job

    enqueue_deletion = request_deletion

    def get_job(self, job_id: str) -> PrivacyJob:
        try:
            return self.repository.jobs[job_id]
        except KeyError as exc:
            raise PrivacyJobNotFoundError("privacy job not found") from exc

    def process_job(self, job_id: str) -> PrivacyJob:
        job = self.get_job(job_id)
        if job.status is not JobStatus.QUEUED:
            return job
        job.status = JobStatus.RUNNING
        try:
            if job.kind is JobKind.EXPORT:
                job.result = self.export_user(job.user_id)
            else:
                self.delete_user(job.user_id)
            job.status = JobStatus.SUCCEEDED
            job.completed_at = utc_now()
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = type(exc).__name__
            job.completed_at = utc_now()
            raise
        return job

    def export_user(self, user_id: str) -> dict[str, Any]:
        user = self.repository.get_user(user_id)
        # Deliberately omit session/token hashes and other authentication
        # internals.  Provider subject is included as the user's own account
        # linkage data, not as an operational secret.
        return {
            "user": {
                "id": user.id,
                "role": user.role.value,
                "status": user.status.value,
                "display_name": user.display_name,
                "email": user.email,
                "created_at": user.created_at.isoformat(),
            },
            "oauth_accounts": [
                {
                    "provider": account.provider,
                    "provider_subject": account.provider_subject,
                    "created_at": account.created_at.isoformat(),
                }
                for account in self.repository.oauth_accounts.values()
                if account.user_id == user.id
            ],
            "consents": [
                {
                    "purpose": item.purpose.value,
                    "consent_version_id": item.consent_version_id,
                    "granted_at": item.granted_at.isoformat() if item.granted_at else None,
                    "withdrawn_at": item.withdrawn_at.isoformat() if item.withdrawn_at else None,
                }
                for item in self.repository.consents.values()
                if item.user_id == user.id
            ],
            "questionnaire_responses": [
                {
                    "id": response.id,
                    "questionnaire_version_id": response.questionnaire_version_id,
                    "answers": dict(response.answers),
                    "score": response.score.as_dict(),
                    "submitted_at": response.submitted_at.isoformat(),
                }
                for response in self.repository.responses.values()
                if response.user_id == user.id
            ],
            "profiles": [
                {
                    "kind": profile.kind.value,
                    "x": profile.x,
                    "y": profile.y,
                    "z": profile.z,
                    "confidence": profile.confidence,
                    "source_version": profile.source_version,
                    "active": profile.active,
                    "created_at": profile.created_at.isoformat(),
                }
                for profile in self.repository.profiles.values()
                if profile.user_id == user.id
            ],
            "demographics": (
                {
                    "age_band": self.repository.demographics[user.id].age_band,
                    "gender_response": self.repository.demographics[user.id].gender_response,
                    "consent_version_id": self.repository.demographics[user.id].consent_version_id,
                    "updated_at": self.repository.demographics[user.id].updated_at.isoformat(),
                }
                if user.id in self.repository.demographics
                else None
            ),
        }

    build_export = export_user

    def delete_user(self, user_id: str) -> User:
        user = self.repository.get_user(user_id)
        now = utc_now()
        if self.sessions:
            self.sessions.revoke_user(user.id, now=now)
        if self._revoke_user_sessions:
            self._revoke_user_sessions(user.id)
        user.status = UserStatus.DELETED
        user.deleted_at = now
        user.display_name = None
        user.email = None
        user.personalization_enabled = False
        user.behavioral_profile_enabled = False
        # Remove sensitive payloads and account linkage after the deletion job
        # reaches its terminal state.  The user tombstone remains for audit/FK
        # purposes; no secret or questionnaire answer survives here.
        for account_key in [
            account_key
            for account_key, item in self.repository.oauth_accounts.items()
            if item.user_id == user.id
        ]:
            del self.repository.oauth_accounts[account_key]
        for consent_key in [
            consent_key
            for consent_key, item in self.repository.consents.items()
            if item.user_id == user.id
        ]:
            del self.repository.consents[consent_key]
        for response_key in [
            response_key
            for response_key, item in self.repository.responses.items()
            if item.user_id == user.id
        ]:
            del self.repository.responses[response_key]
        for profile_key in [
            profile_key
            for profile_key, item in self.repository.profiles.items()
            if item.user_id == user.id
        ]:
            del self.repository.profiles[profile_key]
        self.repository.demographics.pop(user.id, None)
        return user


class OnboardingService:
    """Convenience facade consumed by the user routes."""

    def __init__(
        self,
        repository: InMemoryUserRepository | None = None,
        *,
        sessions: SessionStore | None = None,
    ):
        self.repository = repository or InMemoryUserRepository()
        self.users = UserService(self.repository)
        self.consents = ConsentService(self.repository, self.users)
        self.questionnaires = QuestionnaireService(self.repository, self.consents, self.users)
        self.privacy = PrivacyService(self.repository, self.users, sessions=sessions)

    def grant_consent(
        self,
        user_id: str,
        consent_version_id: str,
        granted: bool = True,
    ) -> UserConsent:
        return self.consents.grant(user_id, consent_version_id, granted)

    def withdraw_consent(self, user_id: str, purpose: ConsentPurpose | str) -> UserConsent | None:
        return self.consents.withdraw(user_id, purpose)

    def submit_questionnaire(
        self,
        user_id: str,
        questionnaire_version_id: str,
        answers: Mapping[str, Any],
    ) -> QuestionnaireSubmission:
        return self.questionnaires.submit(user_id, questionnaire_version_id, answers)

    def update_demographics(self, user_id: str, **values: str | None) -> UserDemographics:
        return self.questionnaires.update_demographics(user_id, **values)

    def request_export(self, user_id: str) -> PrivacyJob:
        return self.privacy.request_export(user_id)

    def request_deletion(self, user_id: str, confirmation: str) -> PrivacyJob:
        return self.privacy.request_deletion(user_id, confirmation)


__all__ = [
    "ConsentRequiredError",
    "ConsentService",
    "ConsentVersionNotFoundError",
    "DeletionConfirmationError",
    "InMemoryUserRepository",
    "OnboardingService",
    "PrivacyJobNotFoundError",
    "PrivacyService",
    "QuestionnaireService",
    "QuestionnaireSubmission",
    "QuestionnaireValidationError",
    "QuestionnaireVersionStaleError",
    "UserDomainError",
    "UserInactiveError",
    "UserNotFoundError",
    "UserService",
    "score_questionnaire",
]
