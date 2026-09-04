from __future__ import annotations

import asyncio
import hashlib
import json
import math
import secrets
from datetime import datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.enums import (
    JobStatus,
    OAuthProvider,
    ProfileKind,
    QuestionnaireKind,
    UserRole,
    UserStatus,
)
from apps.api.app.db.models import (
    ConsentVersion,
    Job,
    OAuthAccount,
    QuestionnaireResponse,
    QuestionnaireVersion,
    ShareCard,
    User,
    UserConsent,
    UserDemographics,
    UserProfile,
)
from apps.api.app.db.models import (
    Session as DBSession,
)
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.jobs.payloads import validate_job_payload
from apps.api.app.repositories.admin import AdminRepositoryMixin
from apps.api.app.repositories.product import ProductRepositoryMixin


def _digest(value: str | bytes) -> bytes:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).digest()


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _is_deadlock(error: BaseException) -> bool:
    """Identify transient MySQL/MariaDB lock failures safe to retry."""

    original = getattr(error, "orig", error)
    message = str(original).lower()
    return any(
        marker in message
        for marker in ("1213", "1205", "deadlock", "lock wait timeout")
    )


_EFFICACY_QUESTIONNAIRE_VERSION = "1.1"


def _efficacy_questionnaire_schema() -> dict[str, Any]:
    """Return the immutable efficacy schema for the current revision."""

    return {
        "scale": {"minimum": 0, "maximum": 100},
        "questions": [
            {"id": "baseline", "required": True, "minimum": 0, "maximum": 100},
            {"id": "current", "required": True, "minimum": 0, "maximum": 100},
        ],
    }


class MariaDBPlatformRepository(AdminRepositoryMixin, ProductRepositoryMixin):
    """Request-scoped SQLAlchemy repository for user/security/product state.

    Domain calculation remains in pure modules; this layer owns transactions,
    hashes/encryption and immutable row transitions.
    """

    def __init__(self, session: AsyncSession, *, encryption_secret: str):
        self.session = session
        self._encryption_key = hashlib.sha256(encryption_secret.encode()).digest()

    _OAUTH_CHALLENGE_JOB_TYPE = "__oauth_challenge__"

    async def bootstrap_policy_records(self) -> None:
        """Install missing mandatory policy records without rewriting definitions.

        Questionnaire definitions are immutable.  In particular, installations
        that already have the original efficacy ``1.0`` scale-only row receive
        the question-bearing ``1.1`` revision rather than having that row
        rewritten in place.
        """

        if not (await self.session.scalar(select(func.count()).select_from(ConsentVersion))):
            now = utc_now()
            self.session.add_all(
                [
                    ConsentVersion(
                        id=new_ulid(),
                        purpose="SERVICE",
                        version="1.0",
                        body_hash=_digest("service-consent-v1"),
                        active_from=now,
                    ),
                    ConsentVersion(
                        id=new_ulid(),
                        purpose="SENSITIVE_POLITICAL",
                        version="1.0",
                        body_hash=_digest("sensitive-political-consent-v1"),
                        active_from=now,
                    ),
                ]
            )
        # Keep the two questionnaire kinds independent.  A migration may
        # already have inserted efficacy 1.1 into an otherwise empty table;
        # checking one table-wide count in that case would skip onboarding.
        onboarding_current = await self.session.scalar(
            select(QuestionnaireVersion.id)
            .where(QuestionnaireVersion.kind == QuestionnaireKind.ONBOARDING)
            .limit(1)
        )
        if onboarding_current is None:
            self.session.add(
                QuestionnaireVersion(
                    id=new_ulid(),
                    kind=QuestionnaireKind.ONBOARDING,
                    version="1.0",
                    schema_json={
                        "questions": [
                            {"id": "economic", "required": True, "minimum": -100, "maximum": 100},
                            {"id": "social", "required": True, "minimum": -100, "maximum": 100},
                            {"id": "international", "required": True, "minimum": -100, "maximum": 100},
                        ]
                    },
                    scoring_json={
                        "axes": {"x": "economic", "y": "social", "z": "international"},
                        "confidence": 0.65,
                    },
                    active_from=utc_now(),
                )
            )

        # Older installations may already have efficacy 1.0 rows.  Add the
        # new immutable revision when migrations have not yet supplied it;
        # never mutate the old schema in place.
        efficacy_current = await self.session.scalar(
            select(QuestionnaireVersion.id).where(
                QuestionnaireVersion.kind == QuestionnaireKind.EFFICACY,
                QuestionnaireVersion.version == _EFFICACY_QUESTIONNAIRE_VERSION,
            )
        )
        if efficacy_current is None:
            self.session.add(
                QuestionnaireVersion(
                    id=new_ulid(),
                    kind=QuestionnaireKind.EFFICACY,
                    version=_EFFICACY_QUESTIONNAIRE_VERSION,
                    schema_json=_efficacy_questionnaire_schema(),
                    scoring_json={"method": "mean", "reverse_items": []},
                    active_from=utc_now(),
                )
            )
        await self.session.commit()

    async def create_oauth_challenge(
        self, *, state: str, challenge: dict[str, Any]
    ) -> None:
        """Persist an OAuth challenge in the shared DB with one-use state.

        The queue table is already durable and has the required unique key and
        JSON payload columns.  Challenge rows are marked CANCELLED so worker
        claimers never execute them; ``consume_oauth_challenge`` transitions a
        row to DEAD under a row lock before returning its payload.
        """

        expires_at = challenge.get("expires_at")
        if hasattr(expires_at, "isoformat"):
            expires_at = expires_at.isoformat()
        payload = {**challenge, "expires_at": expires_at}
        # Insert/commit the challenge before pruning old rows.  A broad DELETE
        # over the queue table acquires next-key locks in InnoDB; doing it
        # before an INSERT lets two concurrent OAuth starts deadlock even when
        # their state keys are unrelated.  A transient deadlock is retried
        # after rollback with a newly constructed row.
        for attempt in range(3):
            now = utc_now()
            self.session.add(
                Job(
                    id=new_ulid(),
                    job_type=self._OAUTH_CHALLENGE_JOB_TYPE,
                    dedupe_key=state,
                    status=JobStatus.CANCELLED,
                    priority=0,
                    available_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    attempts=0,
                    max_attempts=1,
                    payload_json=payload,
                    last_error_json=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            try:
                await self.session.commit()
                break
            except OperationalError as exc:
                await self.session.rollback()
                if not _is_deadlock(exc) or attempt == 2:
                    raise
                await asyncio.sleep(0.01 * (attempt + 1))

        # Cleanup is deliberately bounded and best-effort.  The plain SELECT
        # is a non-locking consistent read; deleting by primary keys avoids the
        # range locks that caused the start/start deadlock.  Challenge creation
        # has already committed, so a cleanup race must never turn a successful
        # authentication start into a 500.
        for cleanup_attempt in range(2):
            try:
                cutoff = utc_now() - timedelta(minutes=11)
                stale_ids = list(
                    (
                        await self.session.scalars(
                            select(Job.id)
                            .where(
                                Job.job_type == self._OAUTH_CHALLENGE_JOB_TYPE,
                                Job.status == JobStatus.CANCELLED,
                                Job.created_at < cutoff,
                            )
                            .order_by(Job.created_at.asc(), Job.id.asc())
                            .limit(100)
                        )
                    ).all()
                )
                if stale_ids:
                    await self.session.execute(delete(Job).where(Job.id.in_(stale_ids)))
                    await self.session.commit()
                break
            except OperationalError as exc:
                await self.session.rollback()
                if not _is_deadlock(exc) or cleanup_attempt == 1:
                    break
                await asyncio.sleep(0.01 * (cleanup_attempt + 1))
            except SQLAlchemyError:
                await self.session.rollback()
                break

    async def consume_oauth_challenge(self, state: str) -> dict[str, Any] | None:
        """Atomically consume one unexpired OAuth challenge, if present."""

        row = await self.session.scalar(
            select(Job)
            .where(
                Job.job_type == self._OAUTH_CHALLENGE_JOB_TYPE,
                Job.dedupe_key == state,
                Job.status == JobStatus.CANCELLED,
            )
            .with_for_update()
        )
        if row is None:
            return None
        payload = dict(row.payload_json or {})
        row.status = JobStatus.DEAD
        row.updated_at = utc_now()
        await self.session.commit()
        raw_expires = payload.get("expires_at")
        try:
            expires_at = (
                raw_expires
                if isinstance(raw_expires, datetime)
                else datetime.fromisoformat(str(raw_expires))
            )
        except (TypeError, ValueError):
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=utc_now().tzinfo)
        payload["expires_at"] = expires_at
        return payload if expires_at > utc_now() else None

    async def find_session(self, raw_token: str) -> dict[str, Any] | None:
        row = await self.session.scalar(
            select(DBSession).where(DBSession.token_hash == _digest(raw_token))
        )
        if not row or row.revoked_at or row.expires_at <= utc_now():
            return None
        user = await self.session.get(User, row.user_id)
        if not user or _enum_value(user.status) != UserStatus.ACTIVE.value:
            return None
        return {
            "id": row.id,
            "user_id": user.id,
            "role": _enum_value(user.role),
            "csrf_hash": row.csrf_hash,
            "expires_at": row.expires_at,
        }

    async def create_or_get_oauth_user(
        self,
        *,
        provider: str,
        subject: str,
        display_name: str | None,
    ) -> dict[str, Any]:
        account = await self.session.scalar(
            select(OAuthAccount).where(
                OAuthAccount.provider == OAuthProvider(provider),
                OAuthAccount.provider_subject == subject,
            )
        )
        if account:
            user = await self.session.get(User, account.user_id)
            if user is None:
                raise RuntimeError("OAuth account references a missing user") from None
            return self.user_view(user)
        user = User(
            id=new_ulid(),
            role=UserRole.MEMBER,
            status=UserStatus.ACTIVE,
            display_name=(display_name or "Member")[:120],
            created_at=utc_now(),
            deleted_at=None,
        )
        self.session.add(user)
        # OAuthAccount has a real FK to users, but the models intentionally do
        # not declare an ORM relationship.  Flush the parent explicitly so
        # MariaDB cannot order the child INSERT first (error 1452).
        await self.session.flush()
        self.session.add(
            OAuthAccount(
                id=new_ulid(),
                user_id=user.id,
                provider=OAuthProvider(provider),
                provider_subject=subject,
                created_at=utc_now(),
            )
        )
        try:
            await self.session.flush()
        except IntegrityError:
            # Two callback requests may both observe no account.  The unique
            # provider/subject key is the serialization point; reload the
            # winner after rolling back this request's speculative insert.
            rollback = getattr(self.session, "rollback", None)
            if rollback is None:
                raise
            await rollback()
            account = await self.session.scalar(
                select(OAuthAccount).where(
                    OAuthAccount.provider == OAuthProvider(provider),
                    OAuthAccount.provider_subject == subject,
                )
            )
            if account is None:
                raise
            user = await self.session.get(User, account.user_id)
            if user is None:
                raise RuntimeError("OAuth account references a missing user") from None
        return self.user_view(user)

    async def get_or_create_admin_user(self) -> dict[str, Any]:
        """Return the active administrator used by credential sign-in."""

        user = await self.session.scalar(
            select(User)
            .where(User.role == UserRole.ADMIN, User.status == UserStatus.ACTIVE)
            .order_by(User.created_at.asc(), User.id.asc())
            .limit(1)
        )
        if user is None:
            user = User(
                id=new_ulid(),
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
                display_name="EFFICA 관리자",
                created_at=utc_now(),
                deleted_at=None,
            )
            self.session.add(user)
            await self.session.flush()
        return self.user_view(user)

    async def rotate_session(
        self, user_id: str, *, current_token: str | None = None
    ) -> tuple[str, str]:
        if current_token:
            await self.session.execute(
                update(DBSession)
                .where(DBSession.token_hash == _digest(current_token), DBSession.revoked_at.is_(None))
                .values(revoked_at=utc_now())
            )
        raw_token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.session.add(
            DBSession(
                id=new_ulid(),
                user_id=user_id,
                token_hash=_digest(raw_token),
                csrf_hash=_digest(csrf),
                expires_at=utc_now() + timedelta(hours=12),
                revoked_at=None,
            )
        )
        await self.session.commit()
        return raw_token, csrf

    async def revoke_session(self, raw_token: str) -> bool:
        result = await self.session.execute(
            update(DBSession)
            .where(DBSession.token_hash == _digest(raw_token), DBSession.revoked_at.is_(None))
            .values(revoked_at=utc_now())
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        user = await self.session.get(User, user_id)
        return None if user is None else await self.complete_user_view(user)

    @staticmethod
    def user_view(user: User) -> dict[str, Any]:
        return {
            "id": user.id,
            "display_name": user.display_name or "Member",
            "role": _enum_value(user.role),
        }

    async def complete_user_view(self, user: User) -> dict[str, Any]:
        consents = await self.list_consents(user.id)
        consent_complete = bool(consents) and all(item["granted"] for item in consents)
        onboarding_complete = bool(
            await self.session.scalar(
                select(func.count()).select_from(UserProfile).where(
                    UserProfile.user_id == user.id,
                    UserProfile.kind == ProfileKind.SELF_REPORTED,
                    UserProfile.active.is_(True),
                )
            )
        )
        behavioral = bool(
            await self.session.scalar(
                select(func.count()).select_from(UserProfile).where(
                    UserProfile.user_id == user.id,
                    UserProfile.kind == ProfileKind.BEHAVIORAL,
                    UserProfile.active.is_(True),
                )
            )
        )
        return {
            **self.user_view(user),
            "consent_complete": consent_complete,
            "onboarding_complete": onboarding_complete,
            "behavioral_profile_active": behavioral,
        }

    async def list_consents(self, user_id: str) -> list[dict[str, Any]]:
        all_versions = list(
            (
                await self.session.scalars(
                    select(ConsentVersion).order_by(
                        ConsentVersion.active_from.desc(), ConsentVersion.id.desc()
                    )
                )
            ).all()
        )
        # A purpose has one current version in the public contract.  Older
        # immutable documents remain queryable for audit/export but must not
        # keep consent_complete false or be rendered as additional checkboxes.
        latest_by_purpose: dict[str, ConsentVersion] = {}
        for version in all_versions:
            latest_by_purpose.setdefault(version.purpose, version)
        versions = sorted(latest_by_purpose.values(), key=lambda item: item.active_from)
        grants = {
            item.consent_version_id: item
            for item in (
                await self.session.scalars(
                    select(UserConsent).where(UserConsent.user_id == user_id)
                )
            ).all()
        }
        return [
            {
                "id": version.id,
                "purpose": version.purpose,
                "version": version.version,
                "body_hash": version.body_hash.hex(),
                "granted": version.id in grants and grants[version.id].withdrawn_at is None,
                "sensitive": "POLITICAL" in version.purpose.upper(),
            }
            for version in versions
        ]

    async def list_questionnaire_versions(
        self, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """Return the latest active definition for each questionnaire kind."""

        if kind == "political":
            kind = QuestionnaireKind.ONBOARDING.value
        statement = select(QuestionnaireVersion).order_by(
            QuestionnaireVersion.active_from.desc(), QuestionnaireVersion.id.desc()
        )
        if kind is not None:
            statement = statement.where(QuestionnaireVersion.kind == QuestionnaireKind(kind))
        rows = list((await self.session.scalars(statement)).all())
        latest: dict[str, QuestionnaireVersion] = {}
        for row in rows:
            latest.setdefault(str(_enum_value(row.kind)), row)
        result: list[dict[str, Any]] = []
        for row in latest.values():
            schema_json = dict(row.schema_json or {})
            questions = schema_json.get("questions", [])
            keys = [str(item["id"]) for item in questions if isinstance(item, dict) and item.get("id")]
            result.append(
                {
                    "id": row.id,
                    "kind": _enum_value(row.kind),
                    "version": row.version,
                    "schema_json": schema_json,
                    "scoring_json": dict(row.scoring_json or {}),
                    "active_from": row.active_from,
                    "keys": keys,
                }
            )
        return sorted(result, key=lambda item: item["kind"])

    async def set_consent(
        self, user_id: str, consent_version_id: str, granted: bool
    ) -> dict[str, Any] | None:
        version = await self.session.get(ConsentVersion, consent_version_id)
        if version is None:
            return None
        current_id = await self.session.scalar(
            select(ConsentVersion.id)
            .where(ConsentVersion.purpose == version.purpose)
            .order_by(ConsentVersion.active_from.desc(), ConsentVersion.id.desc())
            .limit(1)
        )
        if current_id != consent_version_id:
            return None
        row = await self.session.scalar(
            select(UserConsent).where(
                UserConsent.user_id == user_id,
                UserConsent.consent_version_id == consent_version_id,
            )
        )
        now = utc_now()
        if row is None:
            row = UserConsent(
                id=new_ulid(),
                user_id=user_id,
                consent_version_id=consent_version_id,
                granted_at=now,
                withdrawn_at=None if granted else now,
            )
            self.session.add(row)
        elif granted:
            row.granted_at, row.withdrawn_at = now, None
        else:
            row.withdrawn_at = now
        if not granted and "POLITICAL" in version.purpose.upper():
            await self.session.execute(
                update(UserProfile)
                .where(
                    UserProfile.user_id == user_id,
                    UserProfile.kind == ProfileKind.BEHAVIORAL,
                )
                .values(active=False)
            )
        await self.session.commit()
        return {
            "id": version.id,
            "purpose": version.purpose,
            "version": version.version,
            "body_hash": version.body_hash.hex(),
            "granted": granted,
            "sensitive": "POLITICAL" in version.purpose.upper(),
        }

    def _encrypt_answers(self, answers: dict[str, Any], *, aad: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        encoded = json.dumps(answers, sort_keys=True, separators=(",", ":")).encode()
        return nonce + AESGCM(self._encryption_key).encrypt(nonce, encoded, aad)

    async def submit_questionnaire(
        self, user_id: str, questionnaire_version_id: str, answers: dict[str, Any]
    ) -> dict[str, Any] | None:
        # Serialize repeated submissions on a stable parent row.  Updating an
        # empty active-profile range before inserting causes InnoDB next-key
        # locks to deadlock even for different users.
        user = await self.session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )
        if user is None:
            return None
        existing_profiles = list(
            (
                await self.session.scalars(
                    select(UserProfile).where(
                        UserProfile.user_id == user_id,
                        UserProfile.kind == ProfileKind.SELF_REPORTED,
                        UserProfile.active.is_(True),
                    )
                )
            ).all()
        )
        for existing_profile in existing_profiles:
            existing_profile.active = False
        version = await self.session.get(QuestionnaireVersion, questionnaire_version_id)
        if version is None or _enum_value(version.kind) != QuestionnaireKind.ONBOARDING.value:
            return None
        sensitive = await self.session.scalar(
            select(func.count())
            .select_from(UserConsent)
            .join(ConsentVersion, UserConsent.consent_version_id == ConsentVersion.id)
            .where(
                UserConsent.user_id == user_id,
                UserConsent.withdrawn_at.is_(None),
                ConsentVersion.purpose == "SENSITIVE_POLITICAL",
            )
        )
        if not sensitive:
            raise PermissionError("CONSENT_REQUIRED")
        axes = version.scoring_json.get(
            "axes", {"x": "economic", "y": "social", "z": "international"}
        )
        try:
            coordinates = {
                axis: max(
                    -100,
                    min(100, int(self._strict_numeric_answer(answers[question]))),
                )
                for axis, question in axes.items()
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("QUESTIONNAIRE_ANSWER_INVALID") from exc
        response_id = new_ulid()
        self.session.add(
            QuestionnaireResponse(
                id=response_id,
                user_id=user_id,
                questionnaire_version_id=version.id,
                encrypted_payload=self._encrypt_answers(answers, aad=response_id.encode()),
                submitted_at=utc_now(),
            )
        )
        profile = UserProfile(
            id=new_ulid(),
            user_id=user_id,
            kind=ProfileKind.SELF_REPORTED,
            x=coordinates["x"],
            y=coordinates["y"],
            z=coordinates["z"],
            confidence=version.scoring_json.get("confidence", 0.65),
            source_version=version.version,
            active=True,
            created_at=utc_now(),
        )
        self.session.add(profile)
        await self.session.commit()
        return {
            "profile_id": profile.id,
            "kind": "SELF_REPORTED",
            "x": profile.x,
            "y": profile.y,
            "z": profile.z,
            "sensationalism": None,
            "confidence": float(profile.confidence),
            "source_version": profile.source_version,
            "active": profile.active,
        }

    @staticmethod
    def _strict_numeric_answer(value: Any) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("questionnaire answers must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("questionnaire answers must be finite")
        return value

    async def patch_demographics(
        self,
        user_id: str,
        *,
        age_band: str | None,
        gender_response: str | None,
    ) -> dict[str, Any]:
        row = await self.session.get(UserDemographics, user_id)
        consent_id = await self.session.scalar(
            select(ConsentVersion.id)
            .where(ConsentVersion.purpose == "SERVICE")
            .order_by(ConsentVersion.active_from.desc())
        )
        if row is None:
            row = UserDemographics(
                user_id=user_id,
                age_band=age_band,
                gender_response=gender_response,
                consent_version_id=consent_id,
                updated_at=utc_now(),
            )
            self.session.add(row)
        else:
            row.age_band = age_band
            row.gender_response = gender_response
            row.updated_at = utc_now()
        await self.session.commit()
        return {
            "age_band": row.age_band,
            "gender_response": row.gender_response,
            "updated_at": row.updated_at,
        }

    async def enqueue(
        self, job_type: str, dedupe_key: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        # Keep the live repository on the same producer-side contract boundary
        # as JobEnvelope and the admin enqueue helper.  Validation must happen
        # before constructing/upserting a Job so malformed built-ins can never
        # become durable queue rows.
        payload = validate_job_payload(job_type, payload)
        now = utc_now()
        values = {
            "id": new_ulid(),
            "job_type": job_type,
            "dedupe_key": dedupe_key,
            "status": JobStatus.PENDING,
            "priority": 0,
            "available_at": now,
            "lease_owner": None,
            "lease_expires_at": None,
            "attempts": 0,
            "max_attempts": 5,
            "payload_json": payload,
            "last_error_json": None,
            "created_at": now,
            "updated_at": now,
        }

        # Select-then-insert is not an idempotency boundary: two callbacks can
        # both observe no row and one then loses to the unique key.  Let the
        # database arbitrate with a no-op conflict update and reload the
        # canonical row in the same transaction.
        dialect = getattr(getattr(self.session, "bind", None), "dialect", None)
        if dialect is None and hasattr(self.session, "get_bind"):
            try:
                dialect = getattr(self.session.get_bind(), "dialect", None)
            except Exception:
                dialect = None
        if dialect is None and hasattr(self.session, "_session"):
            dialect = getattr(getattr(self.session._session, "bind", None), "dialect", None)
        dialect_name = getattr(dialect, "name", "")
        if dialect_name in {"mysql", "mariadb"}:
            statement = mysql_insert(Job).values(**values).on_duplicate_key_update(id=Job.id)
            await self.session.execute(statement)
        elif dialect_name == "sqlite":
            statement = sqlite_insert(Job).values(**values).on_conflict_do_nothing(
                index_elements=["job_type", "dedupe_key"]
            )
            await self.session.execute(statement)
        else:
            # Small adapters and future dialects retain a safe fallback.  A
            # conflict is translated into the same canonical reload rather
            # than leaking a 500 to an idempotent caller.
            self.session.add(Job(**values))
            try:
                await self.session.flush()
            except IntegrityError:
                rollback = getattr(self.session, "rollback", None)
                if rollback is None:
                    raise
                await rollback()
        existing = await self.session.scalar(
            select(Job).where(Job.job_type == job_type, Job.dedupe_key == dedupe_key)
        )
        if existing is None:
            raise RuntimeError("job upsert did not produce a durable row")
        await self.session.commit()
        return {"id": existing.id, "status": _enum_value(existing.status)}

    async def request_export(self, user_id: str) -> dict[str, Any]:
        return await self.enqueue("export_user", user_id, {"user_id": user_id})

    async def request_deletion(self, user_id: str) -> dict[str, Any]:
        user = await self.session.get(User, user_id)
        if user is None:
            raise KeyError(user_id)
        user.status = UserStatus.PENDING_DELETION
        await self.session.execute(
            update(DBSession)
            .where(DBSession.user_id == user_id, DBSession.revoked_at.is_(None))
            .values(revoked_at=utc_now())
        )
        await self.session.execute(
            update(ShareCard)
            .where(ShareCard.user_id == user_id, ShareCard.revoked_at.is_(None))
            .values(status="revoked", revoked_at=utc_now())
        )
        await self.session.flush()
        job = await self.enqueue(
            "delete_user",
            user_id,
            {"user_id": user_id, "confirmed": True, "legal_hold_checked": True},
        )
        return job
