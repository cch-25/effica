from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    ArticleStatus,
    CreditStatus,
    OAuthProvider,
    ProfileKind,
    QuestionnaireKind,
    ReadSessionStatus,
    ShareCardStatus,
    SourcePolicyStatus,
    SourceType,
    UserRole,
    UserStatus,
    VoteQualityStatus,
)
from apps.api.app.db.models import (
    Article,
    ConsentVersion,
    CreditLedger,
    EfficacyResponse,
    FeedImpression,
    OAuthAccount,
    QuestionnaireResponse,
    QuestionnaireVersion,
    ReadSession,
    ShareCard,
    Source,
    User,
    UserConsent,
    UserDemographics,
    UserProfile,
    Vote,
)
from apps.api.app.db.models import Session as DatabaseSession
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.worker.worker.handlers import export_user
from apps.worker.worker.handlers.base import (
    HandlerContext,
    NonRetryableHandlerError,
    RetryableHandlerError,
)
from apps.worker.worker.lookups import MariaDBWorkerLookups
from apps.worker.worker.queue import Job
from apps.worker.worker.services import MariaDBResultApplier, ResultApplicationError


def test_export_uses_owner_records_and_removes_authentication_material() -> None:
    records = {
        "user": {"id": "user-1", "display_name": "Tester"},
        "oauth_accounts": [
            {
                "provider": "mock",
                "provider_subject": "subject-owned-by-user",
                "access_token": "must-not-be-exported",
            }
        ],
        "sessions": [
            {
                "expires_at": "2026-09-11T00:00:00Z",
                "token_hash": "must-not-be-exported",
                "csrf_hash": "must-not-be-exported",
            }
        ],
        "questionnaire_responses": [
            {"answers": {"q1": 5}, "private_key": "must-not-be-exported"}
        ],
    }

    async def lookup(user_id: str) -> dict[str, object]:
        assert user_id == "user-1"
        return records

    async def scenario() -> None:
        result = await export_user.handle(
            {"user_id": "user-1"},
            HandlerContext(
                idempotency_key="export_user:user-1",
                services={"export_records_lookup": lookup},
            ),
        )
        artifact = result.value["artifact"]
        encoded = json.dumps(artifact, ensure_ascii=False)
        assert artifact["records"]["user"]["id"] == "user-1"
        assert artifact["records"]["oauth_accounts"][0]["provider_subject"] == (
            "subject-owned-by-user"
        )
        assert artifact["records"]["questionnaire_responses"][0]["answers"] == {"q1": 5}
        assert "must-not-be-exported" not in encoded
        assert result.value["status"] == "ready"
        assert result.side_effect_key == "export_user:user-1"

    asyncio.run(scenario())
    # Sanitization builds a copy and cannot damage records used by another
    # retry or audit path.
    assert records["sessions"][0]["token_hash"] == "must-not-be-exported"


@pytest.mark.asyncio
async def test_export_lookup_executes_against_complete_application_schema() -> None:
    """Exercise every export SELECT against real tables and populated rows."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    secret = "schema-backed-export-secret"
    now = utc_now()
    user_id = new_ulid()
    consent_version_id = new_ulid()
    questionnaire_version_id = new_ulid()
    source_id = new_ulid()
    article_id = new_ulid()
    response_id = new_ulid()
    user_consent_id = new_ulid()
    answers = {"economic_01": 4, "social_01": 2}
    encryption_key = hashlib.sha256(secret.encode()).digest()
    nonce = b"n" * 12
    encrypted_answers = nonce + AESGCM(encryption_key).encrypt(
        nonce,
        json.dumps(answers, sort_keys=True, separators=(",", ":")).encode(),
        response_id.encode(),
    )

    try:
        async with factory() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        role=UserRole.MEMBER,
                        status=UserStatus.ACTIVE,
                        display_name="Export tester",
                        created_at=now,
                        deleted_at=None,
                    ),
                    ConsentVersion(
                        id=consent_version_id,
                        purpose="SERVICE",
                        version="export-test",
                        body_hash=b"c" * 32,
                        active_from=now,
                    ),
                    QuestionnaireVersion(
                        id=questionnaire_version_id,
                        kind=QuestionnaireKind.ONBOARDING,
                        version="export-test",
                        schema_json={"questions": []},
                        scoring_json={},
                        active_from=now,
                    ),
                    Source(
                        id=source_id,
                        name="Export source",
                        source_type=SourceType.RSS,
                        canonical_url="https://export.example.test",
                        policy_status=SourcePolicyStatus.APPROVED,
                        robots_status=SourcePolicyStatus.APPROVED,
                        terms_status=SourcePolicyStatus.APPROVED,
                        active=True,
                    ),
                ]
            )
            await session.commit()
            session.add_all(
                [
                    OAuthAccount(
                        id=new_ulid(),
                        user_id=user_id,
                        provider=OAuthProvider.MOCK,
                        provider_subject="export-subject",
                        created_at=now,
                    ),
                    DatabaseSession(
                        id=new_ulid(),
                        user_id=user_id,
                        token_hash=b"t" * 32,
                        csrf_hash=b"s" * 32,
                        expires_at=now + timedelta(hours=1),
                        revoked_at=None,
                    ),
                    UserConsent(
                        id=user_consent_id,
                        user_id=user_id,
                        consent_version_id=consent_version_id,
                        granted_at=now,
                        withdrawn_at=None,
                    ),
                    UserDemographics(
                        user_id=user_id,
                        age_band="30-39",
                        gender_response="self-described",
                        consent_version_id=consent_version_id,
                        updated_at=now,
                    ),
                    UserProfile(
                        id=new_ulid(),
                        user_id=user_id,
                        kind=ProfileKind.SELF_REPORTED,
                        x=10,
                        y=-20,
                        z=30,
                        confidence=Decimal("0.7500"),
                        source_version="export-profile-v1",
                        active=True,
                        created_at=now,
                    ),
                    QuestionnaireResponse(
                        id=response_id,
                        user_id=user_id,
                        questionnaire_version_id=questionnaire_version_id,
                        encrypted_payload=encrypted_answers,
                        submitted_at=now,
                    ),
                    EfficacyResponse(
                        id=new_ulid(),
                        user_id=user_id,
                        questionnaire_version_id=questionnaire_version_id,
                        normalized_score=Decimal("72.5000"),
                        submitted_at=now,
                    ),
                    Article(
                        id=article_id,
                        source_id=source_id,
                        canonical_url="https://export.example.test/article",
                        canonical_url_hash=b"a" * 32,
                        title="Export article",
                        author=None,
                        published_at=now,
                        current_version_id=None,
                        status=ArticleStatus.ACTIVE,
                        created_at=now,
                        updated_at=now,
                    ),
                    ShareCard(
                        id=new_ulid(),
                        user_id=user_id,
                        public_token_hash=b"p" * 32,
                        template="default",
                        display_name="Export tester",
                        snapshot_json={"x": 10, "y": -20, "z": 30},
                        status=ShareCardStatus.READY,
                        blob_id=None,
                        expires_at=now + timedelta(days=1),
                        revoked_at=None,
                        created_at=now,
                    ),
                ]
            )
            await session.commit()
            session.add_all(
                [
                    Vote(
                        id=new_ulid(),
                        user_id=user_id,
                        article_id=article_id,
                        revision=1,
                        x=8,
                        y=-7,
                        z=6,
                        sensationalism=25,
                        quality_status=VoteQualityStatus.QUALIFIED,
                        active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    ReadSession(
                        id=new_ulid(),
                        user_id=user_id,
                        article_id=article_id,
                        token_hash=b"r" * 32,
                        expires_at=now + timedelta(minutes=30),
                        status=ReadSessionStatus.RETURNED,
                        outbound_at=now,
                        returned_at=now + timedelta(minutes=2),
                        client_elapsed_ms=120_000,
                        policy_version="read-v1",
                    ),
                    CreditLedger(
                        id=new_ulid(),
                        user_id=user_id,
                        event_type="QUALIFIED_VOTE",
                        event_key=f"vote:{article_id}",
                        delta=10,
                        policy_version="vote-credit-v1",
                        status=CreditStatus.POSTED,
                        reversed_ledger_id=None,
                        created_at=now,
                    ),
                    FeedImpression(
                        id=new_ulid(),
                        user_id=user_id,
                        article_id=article_id,
                        issue_id=None,
                        reason_code="personalized",
                        rank=1,
                        created_at=now,
                    ),
                ]
            )
            await session.commit()

        lookups = MariaDBWorkerLookups(factory, encryption_secret=secret)
        records = await lookups.export_records_lookup(user_id)
        expected_sections = {
            "user",
            "consents",
            "profiles",
            "demographics",
            "votes",
            "reads",
            "credits",
            "efficacy",
            "share_cards",
            "oauth_accounts",
            "sessions",
            "feed_impressions",
            "questionnaire_responses",
        }
        assert records.keys() == expected_sections
        assert all(records[section] for section in expected_sections)
        assert set(records["user"]) == {
            "id",
            "display_name",
            "role",
            "status",
            "created_at",
            "deleted_at",
        }
        assert bool(records["consents"][0]["granted"]) is True
        assert records["questionnaire_responses"][0]["answers"] == answers

        async with factory() as session:
            consent = await session.get(UserConsent, user_consent_id)
            assert consent is not None
            consent.withdrawn_at = now + timedelta(minutes=5)
            await session.commit()
        withdrawn_records = await lookups.export_records_lookup(user_id)
        assert bool(withdrawn_records["consents"][0]["granted"]) is False

        result = await export_user.handle(
            {"user_id": user_id},
            HandlerContext(services={"export_records_lookup": lookups.export_records_lookup}),
        )
        artifact_text = json.dumps(result.value["artifact"], default=str)
        assert result.value["manifest"]["sections"] == sorted(expected_sections)
        assert "token_hash" not in artifact_text
        assert "csrf_hash" not in artifact_text
        assert "encrypted_payload" not in artifact_text
    finally:
        await engine.dispose()


def test_export_digest_is_stable_across_section_order() -> None:
    async def scenario() -> None:
        first = await export_user.handle(
            {"user_id": "user-1", "records": {"votes": [], "profile": {"x": 1}}}
        )
        second = await export_user.handle(
            {"user_id": "user-1", "records": {"profile": {"x": 1}, "votes": []}}
        )
        assert first.value["export_key"] == second.value["export_key"]
        assert first.value["artifact"] == second.value["artifact"]

    asyncio.run(scenario())


def test_export_fails_explicitly_when_lookup_is_unavailable() -> None:
    async def scenario() -> None:
        with pytest.raises(RetryableHandlerError) as missing:
            await export_user.handle({"user_id": "user-1"})
        assert missing.value.code == "EXPORT_DATA_UNAVAILABLE"

        async def unavailable(_user_id: str) -> None:
            return None

        with pytest.raises(RetryableHandlerError) as empty:
            await export_user.handle(
                {"user_id": "user-1"},
                HandlerContext(services={"export_records_lookup": unavailable}),
            )
        assert empty.value.code == "EXPORT_DATA_UNAVAILABLE"

    asyncio.run(scenario())


def test_export_rejects_missing_or_mismatched_lookup_owner() -> None:
    async def scenario() -> None:
        async def missing_user(_user_id: str) -> dict[str, object]:
            return {"user": None, "votes": []}

        with pytest.raises(NonRetryableHandlerError) as missing:
            await export_user.handle(
                {"user_id": "user-1"},
                HandlerContext(services={"export_records_lookup": missing_user}),
            )
        assert missing.value.code == "EXPORT_USER_NOT_FOUND"

        async def wrong_user(_user_id: str) -> dict[str, object]:
            return {"user": {"id": "user-2"}, "votes": []}

        with pytest.raises(NonRetryableHandlerError) as mismatch:
            await export_user.handle(
                {"user_id": "user-1"},
                HandlerContext(services={"export_records_lookup": wrong_user}),
            )
        assert mismatch.value.code == "EXPORT_OWNER_MISMATCH"

        with pytest.raises(NonRetryableHandlerError) as inline_mismatch:
            await export_user.handle(
                {"user_id": "user-1", "records": {"user": {"id": "user-2"}}}
            )
        assert inline_mismatch.value.code == "EXPORT_OWNER_MISMATCH"

    asyncio.run(scenario())


def test_export_applier_stores_the_complete_archive_then_keeps_only_its_pointer() -> None:
    stored: dict[str, object] = {}

    class Session:
        async def execute(self, statement, params=None):
            stored["expiry_query"] = str(statement)
            stored["expiry_params"] = dict(params or {})
            return []

    async def scenario() -> None:
        handler_result = await export_user.handle(
            {
                "user_id": "user-1",
                "records": {"user": {"id": "user-1"}, "votes": [{"article_id": "a-1"}]},
            }
        )
        result = dict(handler_result.value)
        applier = MariaDBResultApplier(lambda: None)

        async def store_blob(_session, payload: bytes, **metadata: object) -> str:
            stored["payload"] = payload
            stored["metadata"] = metadata
            return "blob-1"

        applier._store_blob = store_blob  # type: ignore[method-assign]
        await applier._apply_export(
            Session(),
            Job(id="export-job", job_type="export_user", payload={"user_id": "user-1"}),
            result,
            datetime(2026, 9, 10, tzinfo=UTC),
        )

        archive = json.loads(stored["payload"])
        assert archive["records"]["votes"] == [{"article_id": "a-1"}]
        assert stored["metadata"] == {
            "mime_type": "application/json",
            "expires_at": datetime(2026, 9, 17, tzinfo=UTC),
        }
        assert "UPDATE stored_blobs" in stored["expiry_query"]
        assert stored["expiry_params"] == {
            "blob_id": "blob-1",
            "expires_at": datetime(2026, 9, 17),
        }
        assert result == {
            "artifact_ref": handler_result.value["export_key"],
            "blob_id": "blob-1",
            "user_id": "user-1",
        }

    asyncio.run(scenario())


def test_export_result_applier_fences_a_worker_from_the_previous_retry_generation() -> None:
    current = {"status": "LEASED", "lease_owner": "worker-new", "attempts": 6}
    writes: list[str] = []

    class Session:
        async def execute(self, statement, params=None):
            query = str(statement)
            if "SELECT status, lease_owner, attempts FROM jobs" in query:
                return [dict(current)]
            if "SELECT result_json FROM job_receipts" in query:
                return []
            raise AssertionError(f"unexpected SQL: {query}")

        async def close(self):
            return None

    async def scenario() -> None:
        applier = MariaDBResultApplier(lambda: Session())

        async def apply_domain(_session, _job, _result, _now):
            writes.append("domain")

        async def persist_result(_session, _job, _result, **_kwargs):
            writes.append("receipt")

        applier._apply_domain = apply_domain  # type: ignore[method-assign]
        applier._persist_result_record = persist_result  # type: ignore[method-assign]
        old_job = Job(
            id="export-job",
            job_type="export_user",
            payload={"user_id": "user-1"},
            attempts=5,
        )
        with pytest.raises(ResultApplicationError, match="generation"):
            await applier.apply(
                old_job,
                {"user_id": "user-1", "artifact": {"records": {}}},
                context=HandlerContext(worker_id="worker-old", attempt=5),
            )
        assert writes == []

        await applier.apply(
            Job(
                id="export-job",
                job_type="export_user",
                payload={"user_id": "user-1"},
                attempts=6,
            ),
            {"user_id": "user-1", "artifact": {"records": {}}},
            context=HandlerContext(worker_id="worker-new", attempt=6),
        )
        assert writes == ["domain", "receipt"]

    asyncio.run(scenario())
