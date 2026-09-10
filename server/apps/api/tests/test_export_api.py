from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.api.v1.dependencies import get_repository, get_state
from apps.api.app.db.base import Base
from apps.api.app.db.enums import JobStatus
from apps.api.app.db.models import Job, JobReceipt, StoredBlob
from apps.api.app.db.utc import utc_now
from apps.api.app.main import app
from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.state import PlatformState
from apps.worker.worker.services import MariaDBIdempotencyStore

MEMBER_HEADERS = {
    "X-Debug-Role": "MEMBER",
    "X-Debug-Token": "local-debug-token",
}


class AsyncSQLiteSession:
    def __init__(self, session: Session):
        self._session = session

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    async def scalar(self, statement: Any) -> Any:
        return self._session.scalar(statement)

    async def get(self, entity: Any, identity: Any) -> Any:
        return self._session.get(entity, identity)

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        if params is None:
            return self._session.execute(statement)
        return self._session.execute(statement, params)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()


@pytest.fixture
def sql_session() -> Iterator[AsyncSQLiteSession]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield AsyncSQLiteSession(session)


async def test_terminal_export_is_requeued_and_ready_artifact_is_owner_scoped(
    sql_session: AsyncSQLiteSession,
) -> None:
    repository = MariaDBPlatformRepository(sql_session, encryption_secret="test-secret")
    user = await repository.create_or_get_oauth_user(
        provider="mock", subject="export-subject", display_name="Export Owner"
    )
    accepted = await repository.request_export(user["id"])
    job = await sql_session.get(Job, accepted["id"])
    assert job is not None
    job.status = JobStatus.DEAD
    job.attempts = 5
    job.last_error_json = {"code": "EXPORT_DATA_UNAVAILABLE", "message": "private"}
    await sql_session.commit()

    retried = await repository.request_export(user["id"])
    assert retried == {"id": accepted["id"], "status": "PENDING"}
    assert job.attempts == 5
    assert job.max_attempts == 10
    assert job.last_error_json is None

    now = utc_now()
    payload = json.dumps({"user_id": user["id"], "records": {"votes": []}}).encode()
    blob = StoredBlob(
        sha256=hashlib.sha256(payload).digest(),
        mime_type="application/json",
        byte_size=len(payload),
        payload=payload,
        expires_at=now + timedelta(days=7),
        created_at=now,
    )
    sql_session.add(blob)
    await sql_session.flush()
    sql_session.add(
        JobReceipt(
            job_id=job.id,
            job_type="export_user",
            result_json={"applied": True, "user_id": user["id"], "blob_id": blob.id},
            applied_at=now,
        )
    )
    job.status = JobStatus.SUCCEEDED
    job.updated_at = now
    await sql_session.commit()

    status = await repository.export_status(user["id"])
    assert status is not None
    assert status["status"] == "SUCCEEDED"
    assert status["download_ready"] is True
    assert status["failure_code"] is None
    assert status["download_url"] == f"/api/v1/me/export/{job.id}/download"
    artifact = await repository.export_artifact(user["id"], job.id)
    assert artifact is not None and artifact[1] is blob
    assert await repository.export_artifact("different-user", job.id) is None

    idempotency = MariaDBIdempotencyStore(lambda: sql_session)
    owner_token, cached = await idempotency.begin(f"export_user:{user['id']}")
    assert owner_token == "cached"
    assert cached["blob_id"] == blob.id

    refreshed = await repository.request_export(user["id"])
    assert refreshed == {"id": job.id, "status": "PENDING"}
    assert await sql_session.scalar(select(func.count()).select_from(JobReceipt)) == 0
    owner_token, cached = await idempotency.begin(f"export_user:{user['id']}")
    assert owner_token != "cached"
    assert cached is None


def test_export_status_download_and_failure_contracts() -> None:
    state = PlatformState()
    user_id = state.default_users["MEMBER"]
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            missing = client.get("/api/v1/me/export", headers=MEMBER_HEADERS)
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "EXPORT_NOT_FOUND"

            accepted = client.post(
                "/api/v1/me/export",
                headers={**MEMBER_HEADERS, "X-CSRF-Token": "local-csrf"},
            )
            assert accepted.status_code == 202
            job_id = accepted.json()["job_id"]
            state.jobs[job_id]["status"] = "LEASED"
            replayed = client.post(
                "/api/v1/me/export",
                headers={**MEMBER_HEADERS, "X-CSRF-Token": "local-csrf"},
            )
            assert replayed.json() == {"job_id": job_id, "status": "LEASED"}
            state.jobs[job_id]["status"] = "PENDING"
            pending = client.get("/api/v1/me/export", headers=MEMBER_HEADERS)
            assert pending.json() == {
                "job_id": job_id,
                "status": "PENDING",
                "download_ready": False,
                "download_url": None,
                "expires_at": None,
                "failure_code": None,
                "updated_at": pending.json()["updated_at"],
            }
            pending_download = client.get(
                f"/api/v1/me/export/{job_id}/download", headers=MEMBER_HEADERS
            )
            assert pending_download.status_code == 409
            assert pending_download.json()["error"]["code"] == "EXPORT_NOT_READY"

            job = state.jobs[job_id]
            job["status"] = "SUCCEEDED"
            job["updated_at"] = utc_now()
            job["artifact"] = {"schema_version": "1", "user_id": user_id, "records": {}}
            job["artifact_expires_at"] = utc_now() + timedelta(days=7)
            ready = client.get("/api/v1/me/export", headers=MEMBER_HEADERS)
            assert ready.status_code == 200
            assert ready.json()["download_ready"] is True
            download = client.get(
                f"/api/v1/me/export/{job_id}/download", headers=MEMBER_HEADERS
            )
            assert download.status_code == 200
            assert download.headers["content-type"].startswith("application/json")
            assert download.headers["cache-control"] == "private, no-store"
            assert download.headers["x-content-type-options"] == "nosniff"
            assert download.headers["content-disposition"].endswith(f'{job_id}.json"')
            assert download.json()["user_id"] == user_id

            job["status"] = "DEAD"
            job["last_error"] = {"code": "EXPORT_DATA_UNAVAILABLE", "message": "private"}
            failed = client.get("/api/v1/me/export", headers=MEMBER_HEADERS)
            assert failed.json()["failure_code"] == "EXPORT_DATA_UNAVAILABLE"
            failed_download = client.get(
                f"/api/v1/me/export/{job_id}/download", headers=MEMBER_HEADERS
            )
            assert failed_download.status_code == 409
            assert failed_download.json()["error"] == {
                "code": "EXPORT_FAILED",
                "message": "The data export could not be prepared.",
                "request_id": failed_download.json()["error"]["request_id"],
                "retryable": False,
                "details": {"failure_code": "EXPORT_DATA_UNAVAILABLE"},
            }
            job["attempts"] = 5
            retried = client.post(
                "/api/v1/me/export",
                headers={**MEMBER_HEADERS, "X-CSRF-Token": "local-csrf"},
            )
            assert retried.json() == {"job_id": job_id, "status": "PENDING"}
            assert job["attempts"] == 5
            assert job["max_attempts"] == 10

            foreign_job = state.enqueue(
                "export_user", "different-user", {"user_id": "different-user"}
            )
            hidden = client.get(
                f"/api/v1/me/export/{foreign_job['id']}/download", headers=MEMBER_HEADERS
            )
            assert hidden.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_persisted_export_routes_enforce_owner_and_expiry(
    sql_session: AsyncSQLiteSession,
) -> None:
    state = PlatformState()
    owner_id = state.default_users["MEMBER"]
    other_id = state.default_users["ANALYST"]
    repository = MariaDBPlatformRepository(sql_session, encryption_secret="test-secret")
    accepted = await repository.request_export(owner_id)
    job = await sql_session.get(Job, accepted["id"])
    assert job is not None
    now = utc_now()
    payload = json.dumps({"user_id": owner_id, "records": {}}).encode()
    blob = StoredBlob(
        sha256=hashlib.sha256(payload).digest(),
        mime_type="application/json",
        byte_size=len(payload),
        payload=payload,
        expires_at=now - timedelta(seconds=1),
        created_at=now - timedelta(days=8),
    )
    sql_session.add(blob)
    await sql_session.flush()
    sql_session.add(
        JobReceipt(
            job_id=job.id,
            job_type="export_user",
            result_json={"applied": True, "user_id": owner_id, "blob_id": blob.id},
            applied_at=now,
        )
    )
    job.status = JobStatus.SUCCEEDED
    job.updated_at = now
    await sql_session.commit()

    app.dependency_overrides[get_state] = lambda: state
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            expired_status = client.get("/api/v1/me/export", headers=MEMBER_HEADERS)
            assert expired_status.status_code == 200
            assert expired_status.json()["failure_code"] == "EXPORT_ARTIFACT_EXPIRED"
            expired = client.get(
                f"/api/v1/me/export/{job.id}/download", headers=MEMBER_HEADERS
            )
            assert expired.status_code == 410
            assert expired.json()["error"]["code"] == "EXPORT_EXPIRED"

            blob.expires_at = now + timedelta(days=7)
            await sql_session.commit()
            ready = client.get(
                f"/api/v1/me/export/{job.id}/download", headers=MEMBER_HEADERS
            )
            assert ready.status_code == 200
            assert ready.content == payload

            hidden = client.get(
                f"/api/v1/me/export/{job.id}/download",
                headers={
                    **MEMBER_HEADERS,
                    "X-Debug-User": other_id,
                },
            )
            assert hidden.status_code == 404
    finally:
        app.dependency_overrides.clear()
