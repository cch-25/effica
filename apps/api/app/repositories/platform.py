from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select, update
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
from apps.api.app.repositories.admin import AdminRepositoryMixin
from apps.api.app.repositories.product import ProductRepositoryMixin


def _digest(value: str | bytes) -> bytes:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).digest()


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


class MariaDBPlatformRepository(AdminRepositoryMixin, ProductRepositoryMixin):
    """Request-scoped SQLAlchemy repository for user/security/product state.

    Domain calculation remains in pure modules; this layer owns transactions,
    hashes/encryption and immutable row transitions.
    """

    def __init__(self, session: AsyncSession, *, encryption_secret: str):
        self.session = session
        self._encryption_key = hashlib.sha256(encryption_secret.encode()).digest()

    async def bootstrap_policy_records(self) -> None:
        """Install mandatory versioned policy records when a fresh DB is empty."""

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
        if not (await self.session.scalar(select(func.count()).select_from(QuestionnaireVersion))):
            self.session.add_all(
                [
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
                    ),
                    QuestionnaireVersion(
                        id=new_ulid(),
                        kind=QuestionnaireKind.EFFICACY,
                        version="1.0",
                        schema_json={"scale": {"minimum": 0, "maximum": 100}},
                        scoring_json={"method": "mean", "reverse_items": []},
                        active_from=utc_now(),
                    ),
                ]
            )
        await self.session.commit()

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
                raise RuntimeError("OAuth account references a missing user")
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
        self.session.add(
            OAuthAccount(
                id=new_ulid(),
                user_id=user.id,
                provider=OAuthProvider(provider),
                provider_subject=subject,
                created_at=utc_now(),
            )
        )
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
            "status": _enum_value(user.status),
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
        versions = list(
            (await self.session.scalars(select(ConsentVersion).order_by(ConsentVersion.active_from))).all()
        )
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

    async def set_consent(
        self, user_id: str, consent_version_id: str, granted: bool
    ) -> dict[str, Any] | None:
        version = await self.session.get(ConsentVersion, consent_version_id)
        if version is None:
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
                axis: max(-100, min(100, int(answers[question])))
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
        await self.session.execute(
            update(UserProfile)
            .where(
                UserProfile.user_id == user_id,
                UserProfile.kind == ProfileKind.SELF_REPORTED,
                UserProfile.active.is_(True),
            )
            .values(active=False)
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
        existing = await self.session.scalar(
            select(Job).where(Job.job_type == job_type, Job.dedupe_key == dedupe_key)
        )
        if existing:
            return {"id": existing.id, "status": _enum_value(existing.status)}
        row = Job(
            id=new_ulid(),
            job_type=job_type,
            dedupe_key=dedupe_key,
            status=JobStatus.PENDING,
            priority=0,
            available_at=utc_now(),
            lease_owner=None,
            lease_expires_at=None,
            attempts=0,
            max_attempts=5,
            payload_json=payload,
            last_error_json=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(row)
        await self.session.commit()
        return {"id": row.id, "status": JobStatus.PENDING.value}

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
