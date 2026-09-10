from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from apps.worker.worker.handlers import export_user
from apps.worker.worker.handlers.base import (
    HandlerContext,
    NonRetryableHandlerError,
    RetryableHandlerError,
)
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
