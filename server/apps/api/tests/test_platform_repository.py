"""Persistence-focused coverage for the MariaDB platform repository.

The repository is written against ``AsyncSession``.  The test adapter below
executes the same SQLAlchemy statements through an in-memory SQLite
``Session`` while exposing the awaited methods the repository uses.  This
keeps the tests self-contained without adding a database driver just for
tests, and still exercises model constraints, enum conversion, JSON columns,
and transaction boundaries.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    JobStatus,
    ProfileKind,
    QuestionnaireKind,
    ShareCardStatus,
    UserRole,
)
from apps.api.app.db.models import (
    ConsentVersion,
    Job,
    OAuthAccount,
    QuestionnaireResponse,
    QuestionnaireVersion,
    ShareCard,
    User,
    UserDemographics,
    UserProfile,
)
from apps.api.app.db.models import Session as DBSession
from apps.api.app.db.utc import utc_now
from apps.api.app.repositories.platform import MariaDBPlatformRepository


class AsyncSQLiteSession:
    """Small AsyncSession-compatible surface used by the repository tests."""

    def __init__(self, session: Session):
        self._session = session

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def add_all(self, instances: list[Any]) -> None:
        self._session.add_all(instances)

    async def scalar(self, statement: Any) -> Any:
        return self._session.scalar(statement)

    async def scalars(self, statement: Any) -> Any:
        return self._session.scalars(statement)

    async def get(self, entity: Any, identity: Any) -> Any:
        return self._session.get(entity, identity)

    async def execute(self, statement: Any) -> Any:
        return self._session.execute(statement)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()


@pytest.fixture
def session() -> Iterator[AsyncSQLiteSession]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as sync_session:
        yield AsyncSQLiteSession(sync_session)


def repository(session: AsyncSQLiteSession) -> MariaDBPlatformRepository:
    return MariaDBPlatformRepository(session, encryption_secret="test encryption secret")


async def bootstrap(repo: MariaDBPlatformRepository) -> None:
    await repo.bootstrap_policy_records()


async def create_user(repo: MariaDBPlatformRepository) -> dict[str, Any]:
    return await repo.create_or_get_oauth_user(
        provider="mock",
        subject="subject-1",
        display_name="Repository Tester",
    )


async def test_bootstrap_policy_records_is_complete_and_idempotent(
    session: AsyncSQLiteSession,
) -> None:
    repo = repository(session)

    await bootstrap(repo)
    await bootstrap(repo)

    consent_versions = (await session.scalars(select(ConsentVersion))).all()
    questionnaire_versions = (await session.scalars(select(QuestionnaireVersion))).all()
    assert len(consent_versions) == 2
    assert {(row.purpose, row.version) for row in consent_versions} == {
        ("SERVICE", "1.0"),
        ("SENSITIVE_POLITICAL", "1.0"),
    }
    assert len(questionnaire_versions) == 2
    assert {getattr(row.kind, "value", row.kind) for row in questionnaire_versions} == {
        "onboarding",
        "efficacy",
    }
    efficacy = next(
        row
        for row in questionnaire_versions
        if getattr(row.kind, "value", row.kind) == QuestionnaireKind.EFFICACY.value
    )
    assert efficacy.version == "1.1"
    assert [question["id"] for question in efficacy.schema_json["questions"]] == [
        "baseline",
        "current",
    ]


async def test_bootstrap_adds_new_efficacy_revision_without_rewriting_legacy_schema(
    session: AsyncSQLiteSession,
) -> None:
    legacy_schema = {"scale": {"minimum": 0, "maximum": 100}}
    session.add_all(
        [
            QuestionnaireVersion(
                id="01K00000000000000000000101",
                kind=QuestionnaireKind.ONBOARDING,
                version="1.0",
                schema_json={"questions": []},
                scoring_json={},
                active_from=utc_now(),
            ),
            QuestionnaireVersion(
                id="01K00000000000000000000102",
                kind=QuestionnaireKind.EFFICACY,
                version="1.0",
                schema_json=legacy_schema,
                scoring_json={"method": "mean", "reverse_items": []},
                active_from=utc_now(),
            ),
        ]
    )
    await session.commit()

    repo = repository(session)
    await bootstrap(repo)
    await bootstrap(repo)

    questionnaire_versions = (await session.scalars(select(QuestionnaireVersion))).all()
    assert len(questionnaire_versions) == 3
    legacy = await session.get(QuestionnaireVersion, "01K00000000000000000000102")
    assert legacy is not None
    assert legacy.version == "1.0"
    assert legacy.schema_json == legacy_schema
    current = next(row for row in questionnaire_versions if row.version == "1.1")
    assert current.kind == QuestionnaireKind.EFFICACY
    assert [question["id"] for question in current.schema_json["questions"]] == [
        "baseline",
        "current",
    ]


async def test_oauth_user_session_csrf_lookup_rotation_and_revocation(
    session: AsyncSQLiteSession,
) -> None:
    repo = repository(session)
    first = await create_user(repo)
    same_account = await repo.create_or_get_oauth_user(
        provider="mock", subject="subject-1", display_name="Ignored Name"
    )
    assert same_account["id"] == first["id"]
    assert same_account["display_name"] == "Repository Tester"
    assert await session.scalar(select(func.count()).select_from(OAuthAccount)) == 1

    token, csrf = await repo.rotate_session(first["id"])
    found = await repo.find_session(token)
    assert found is not None
    assert found["user_id"] == first["id"]
    assert found["role"] == "MEMBER"
    assert found["csrf_hash"] == hashlib.sha256(csrf.encode()).digest()
    assert await session.scalar(select(func.count()).select_from(DBSession)) == 1

    replacement, replacement_csrf = await repo.rotate_session(
        first["id"], current_token=token
    )
    assert await repo.find_session(token) is None
    replacement_session = await repo.find_session(replacement)
    assert replacement_session is not None
    assert replacement_session["csrf_hash"] == hashlib.sha256(replacement_csrf.encode()).digest()
    assert await repo.revoke_session(replacement)
    assert await repo.find_session(replacement) is None
    assert not await repo.revoke_session(replacement)


async def test_admin_session_provisioning_is_idempotent(
    session: AsyncSQLiteSession,
) -> None:
    repo = repository(session)

    admin = await repo.get_or_create_admin_user()
    same_admin = await repo.get_or_create_admin_user()
    assert same_admin["id"] == admin["id"]
    assert same_admin["role"] == UserRole.ADMIN.value
    assert await session.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
    ) == 1

    token, _ = await repo.rotate_session(admin["id"])
    found = await repo.find_session(token)
    assert found is not None
    assert found["user_id"] == admin["id"]
    assert found["role"] == UserRole.ADMIN.value


async def test_consent_withdrawal_disables_behavioral_profile_and_blocks_sensitive_submit(
    session: AsyncSQLiteSession,
) -> None:
    repo = repository(session)
    await bootstrap(repo)
    user = await create_user(repo)
    sensitive = await session.scalar(
        select(ConsentVersion).where(ConsentVersion.purpose == "SENSITIVE_POLITICAL")
    )
    onboarding = await session.scalar(
        select(QuestionnaireVersion).where(
            QuestionnaireVersion.kind == "onboarding"
        )
    )
    assert sensitive is not None and onboarding is not None
    await repo.set_consent(user["id"], sensitive.id, True)
    await repo.submit_questionnaire(
        user["id"],
        onboarding.id,
        {"economic": 20, "social": -10, "international": 30},
    )

    behavioral = UserProfile(
        user_id=user["id"],
        kind=ProfileKind.BEHAVIORAL,
        x=5,
        y=6,
        z=7,
        confidence=0.5,
        source_version="behavior-v1",
        active=True,
        created_at=utc_now(),
    )
    session.add(behavioral)
    await session.commit()

    withdrawn = await repo.set_consent(user["id"], sensitive.id, False)
    assert withdrawn is not None and withdrawn["granted"] is False
    assert (await session.get(UserProfile, behavioral.id)).active is False
    listed = await repo.list_consents(user["id"])
    sensitive_view = next(item for item in listed if item["id"] == sensitive.id)
    assert sensitive_view["granted"] is False
    with pytest.raises(PermissionError, match="CONSENT_REQUIRED"):
        await repo.submit_questionnaire(
            user["id"], onboarding.id, {"economic": 1, "social": 2, "international": 3}
        )


async def test_questionnaire_answers_are_encrypted_and_profile_is_persisted(
    session: AsyncSQLiteSession,
) -> None:
    repo = repository(session)
    await bootstrap(repo)
    user = await create_user(repo)
    sensitive = await session.scalar(
        select(ConsentVersion).where(ConsentVersion.purpose == "SENSITIVE_POLITICAL")
    )
    onboarding = await session.scalar(
        select(QuestionnaireVersion).where(QuestionnaireVersion.kind == "onboarding")
    )
    assert sensitive is not None and onboarding is not None
    await repo.set_consent(user["id"], sensitive.id, True)

    answers = {"economic": 150, "social": -150, "international": 12}
    profile = await repo.submit_questionnaire(user["id"], onboarding.id, answers)
    assert profile is not None
    assert (profile["x"], profile["y"], profile["z"]) == (100, -100, 12)

    response = await session.scalar(select(QuestionnaireResponse))
    assert response is not None
    plaintext = json.dumps(answers, sort_keys=True, separators=(",", ":")).encode()
    assert plaintext not in response.encrypted_payload
    nonce, ciphertext = response.encrypted_payload[:12], response.encrypted_payload[12:]
    decrypted = AESGCM(repo._encryption_key).decrypt(
        nonce, ciphertext, response.id.encode()
    )
    assert json.loads(decrypted) == answers


async def test_demographics_are_upserted_with_service_consent_version(
    session: AsyncSQLiteSession,
) -> None:
    repo = repository(session)
    await bootstrap(repo)
    user = await create_user(repo)

    first = await repo.patch_demographics(
        user["id"], age_band="30-39", gender_response="nonbinary"
    )
    assert first["age_band"] == "30-39"
    assert first["gender_response"] == "nonbinary"
    second = await repo.patch_demographics(
        user["id"], age_band="40-49", gender_response=None
    )
    assert second["age_band"] == "40-49"
    assert second["gender_response"] is None

    service = await session.scalar(
        select(ConsentVersion).where(ConsentVersion.purpose == "SERVICE")
    )
    assert service is not None
    # The repository uses one row keyed by user_id; a second patch must not
    # create another demographics record.
    persisted = await session.get(UserDemographics, user["id"])
    assert persisted is not None
    assert persisted.consent_version_id == service.id
    assert await session.scalar(
        select(func.count()).select_from(UserDemographics)
    ) == 1


async def test_export_job_is_deduplicated_by_user(
    session: AsyncSQLiteSession,
) -> None:
    repo = repository(session)
    user = await create_user(repo)

    first = await repo.request_export(user["id"])
    second = await repo.request_export(user["id"])
    assert first == second
    assert first["status"] == JobStatus.PENDING.value
    assert await session.scalar(select(func.count()).select_from(Job)) == 1
    job = await session.get(Job, first["id"])
    assert job is not None
    assert job.job_type == "export_user"
    assert job.dedupe_key == user["id"]
    assert job.payload_json == {"user_id": user["id"]}


async def test_deletion_marks_user_revokes_sessions_and_share_cards(
    session: AsyncSQLiteSession,
) -> None:
    repo = repository(session)
    user = await create_user(repo)
    token, _ = await repo.rotate_session(user["id"])
    card = ShareCard(
        user_id=user["id"],
        public_token_hash=hashlib.sha256(b"public-token").digest(),
        template="default",
        display_name="Repository Tester",
        snapshot_json={"x": 1},
        status=ShareCardStatus.QUEUED,
        blob_id=None,
        expires_at=None,
        revoked_at=None,
        created_at=utc_now(),
    )
    session.add(card)
    await session.commit()

    job_view = await repo.request_deletion(user["id"])
    assert job_view["status"] == JobStatus.PENDING.value
    persisted_user = await session.get(User, user["id"])
    assert getattr(persisted_user.status, "value", persisted_user.status) == "PENDING_DELETION"
    assert await repo.find_session(token) is None

    persisted_card = await session.get(ShareCard, card.id)
    assert persisted_card is not None
    assert getattr(persisted_card.status, "value", persisted_card.status) == "revoked"
    assert persisted_card.revoked_at is not None
    deletion_job = await session.get(Job, job_view["id"])
    assert deletion_job is not None
    assert deletion_job.payload_json == {
        "user_id": user["id"],
        "confirmed": True,
        "legal_hold_checked": True,
    }
