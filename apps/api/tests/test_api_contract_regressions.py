"""Regression coverage for the API auth, contract, and persistence fixes."""

from __future__ import annotations

from datetime import timedelta
from math import inf, nan

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.api.v1.schemas import JobAccepted, QuestionnaireSubmission, UserView
from apps.api.app.core.config import Settings, get_settings
from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    ArticleStatus,
    SourcePolicyStatus,
    SourceType,
    UserRole,
    UserStatus,
)
from apps.api.app.db.models import Article, Job, Source, User
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.jobs.payloads import JobPayloadError
from apps.api.app.main import app
from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.state import PlatformState


def test_oauth_nonce_return_path_and_provider_contract() -> None:
    state = PlatformState()
    app.dependency_overrides[get_state] = lambda: state
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        app_env="test",
        app_backend="memory",
        oauth_redirect_allowlist="http://localhost:3000/auth/callback",
        google_client_id="test-google-client",
        google_client_secret="test-google-secret",
    )
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/auth/providers").json() == ["google"]
            start = client.get(
                "/api/v1/auth/mock/start",
                params={
                    "redirect_uri": "http://localhost:3000/auth/callback",
                    "returnTo": "/articles/article-1?tab=history",
                },
                follow_redirects=False,
            )
            assert start.status_code == 302
            state_cookie = start.cookies["oauth_state"]

            # A fresh client has no nonce cookie and must not complete login.
            with TestClient(app) as fresh_client:
                missing_nonce = fresh_client.get(
                    "/api/v1/auth/mock/callback",
                    params={"state": state_cookie, "code": "missing-nonce"},
                    headers={"X-OAuth-State": state_cookie, "Cookie": f"oauth_state={state_cookie}"},
                    follow_redirects=False,
                )
            assert missing_nonce.status_code == 400

            # The failed callback consumes its challenge, so issue a fresh
            # one for the successful path.
            start = client.get(
                "/api/v1/auth/mock/start",
                params={
                    "redirect_uri": "http://localhost:3000/auth/callback",
                    "returnTo": "/articles/article-1?tab=history",
                },
                follow_redirects=False,
            )
            state_cookie = start.cookies["oauth_state"]
            callback = client.get(
                "/api/v1/auth/mock/callback",
                params={"state": state_cookie, "code": "mock-valid-code"},
                headers={"X-OAuth-State": state_cookie},
                follow_redirects=False,
            )
            assert callback.status_code == 302
            assert callback.headers["location"] == "http://localhost:3000/articles/article-1?tab=history"

            failed_start = client.get(
                "/api/v1/auth/mock/start",
                params={
                    "redirect_uri": "http://localhost:3000/auth/callback",
                    "returnTo": "/articles/article-1",
                },
                follow_redirects=False,
            )
            failed_state = failed_start.cookies["oauth_state"]
            failed = client.get(
                "/api/v1/auth/mock/callback",
                params={"state": failed_state, "code": "wrong-code"},
                follow_redirects=False,
            )
            assert failed.status_code == 302
            assert failed.headers["location"] == (
                "http://localhost:3000/login?oauthError=failed&returnTo=%2Farticles%2Farticle-1"
            )

            state.users[state.default_users["MEMBER"]]["onboarding_complete"] = False
            onboarding_start = client.get(
                "/api/v1/auth/mock/start",
                params={
                    "redirect_uri": "http://localhost:3000/auth/callback",
                    "returnTo": "/articles/article-1?tab=history",
                },
                follow_redirects=False,
            )
            onboarding_state = onboarding_start.cookies["oauth_state"]
            onboarding = client.get(
                "/api/v1/auth/mock/callback",
                params={"state": onboarding_state, "code": "mock-valid-code"},
                follow_redirects=False,
            )
            assert onboarding.headers["location"] == (
                "http://localhost:3000/onboarding/consent?"
                "returnTo=%2Farticles%2Farticle-1%3Ftab%3Dhistory"
            )
            assert (
                client.get(
                    "/api/v1/auth/mock/start",
                    params={
                        "redirect_uri": "http://localhost:3000/auth/callback",
                        "returnTo": "https://evil.example/steal",
                    },
                    follow_redirects=False,
                ).status_code
                == 400
            )
    finally:
        app.dependency_overrides.clear()


def test_admin_autopilot_settings_is_authenticated_and_authoritative() -> None:
    state = PlatformState()
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/admin/autopilot/settings").status_code == 401
            response = client.get(
                "/api/v1/admin/autopilot/settings", headers={"X-Debug-Role": "ADMIN"}
            )
            assert response.status_code == 200
            assert response.json()["version"] == state.autopilot["version"]
            weights = client.get("/api/v1/admin/weights", headers={"X-Debug-Role": "ADMIN"})
            assert weights.status_code == 200
            assert weights.json()["items"][0]["profile_version"] == state.autopilot["version"]
    finally:
        app.dependency_overrides.clear()


def test_admin_llm_usage_is_fail_closed_and_cancels_queued_work() -> None:
    state = PlatformState()
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/admin/runtime/llm-usage").status_code == 401
            initial = client.get(
                "/api/v1/admin/runtime/llm-usage",
                headers={"X-Debug-Role": "ANALYST"},
            )
            assert initial.status_code == 200
            assert initial.json()["status"] == "STOPPED"

            forbidden = client.put(
                "/api/v1/admin/runtime/llm-usage",
                json={"enabled": True, "reason": "analyst cannot start processing"},
                headers={
                    "X-Debug-Role": "ANALYST",
                    "X-CSRF-Token": "local-csrf",
                    "Idempotency-Key": "llm-analyst-forbidden",
                    "If-Match": "1",
                },
            )
            assert forbidden.status_code == 403

            started = client.put(
                "/api/v1/admin/runtime/llm-usage",
                json={"enabled": True, "reason": "operator start"},
                headers={
                    "X-Debug-Role": "ADMIN",
                    "X-CSRF-Token": "local-csrf",
                    "Idempotency-Key": "llm-admin-start",
                    "If-Match": "1",
                },
            )
            assert started.status_code == 200
            assert started.json()["status"] == "RUNNING"

            job = state.enqueue("export_user", "runtime-stop-job", {"user_id": "runtime-user"})
            stopped = client.put(
                "/api/v1/admin/runtime/llm-usage",
                json={"enabled": False, "reason": "operator stop"},
                headers={
                    "X-Debug-Role": "ADMIN",
                    "X-CSRF-Token": "local-csrf",
                    "Idempotency-Key": "llm-admin-stop",
                    "If-Match": "2",
                },
            )
            assert stopped.status_code == 200
            assert stopped.json()["status"] == "STOPPED"
            assert stopped.json()["cancelled_jobs"] == 1
            assert state.jobs[job["id"]]["status"] == "CANCELLED"
    finally:
        app.dependency_overrides.clear()


def test_memory_enqueue_contract_and_retry_reset_attempt_budget() -> None:
    state = PlatformState()
    with pytest.raises(JobPayloadError):
        state.enqueue("export_user", "malformed", {})

    job = state.enqueue("export_user", "retry-user", {"user_id": "retry-user"})
    job.update(
        {
            "status": "DEAD",
            "attempts": 5,
            "available_at": utc_now() - timedelta(minutes=1),
            "lease_owner": "worker-1",
            "lease_expires_at": utc_now() + timedelta(minutes=1),
            "last_error": {"code": "MAX_ATTEMPTS"},
        }
    )
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/admin/jobs/{job['id']}/retry",
                headers={
                    "X-Debug-Role": "REVIEWER",
                    "X-CSRF-Token": "local-csrf",
                    "Idempotency-Key": "retry-key-1",
                },
            )
        assert response.status_code == 200
        assert job["status"] == "PENDING"
        assert job["attempts"] == 0
        assert job["last_error"] is None
        assert job["lease_owner"] is None
        assert job["lease_expires_at"] is None
        assert job["available_at"] > utc_now() - timedelta(seconds=1)
    finally:
        app.dependency_overrides.clear()


def test_questionnaire_api_rejects_nonfinite_and_non_numeric_answers() -> None:
    version_id = "01H00000000000000000000001"
    for answer in ("3", True, nan, inf, -inf):
        with pytest.raises(ValidationError):
            QuestionnaireSubmission.model_validate(
                {"questionnaire_version_id": version_id, "answers": {"x": answer}}
            )


def test_memory_vote_revisions_are_article_global_through_delete() -> None:
    state = PlatformState()
    member_id = state.default_users["MEMBER"]
    second_user_id = state.default_users["ANALYST"]
    state.users[second_user_id]["consent_complete"] = True
    article_id = next(iter(state.articles))
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            def put(user_id: str, value: int) -> None:
                response = client.put(
                    f"/api/v1/articles/{article_id}/vote",
                    headers={
                        "X-Debug-Role": "MEMBER",
                        "X-Debug-User": user_id,
                        "X-CSRF-Token": "local-csrf",
                    },
                    json={
                        "x": value,
                        "y": value,
                        "z": value,
                        "sensationalism": value,
                    },
                )
                assert response.status_code == 200

            put(member_id, 1)
            put(second_user_id, 2)
            put(member_id, 3)
            deleted = client.delete(
                f"/api/v1/articles/{article_id}/vote",
                headers={
                    "X-Debug-Role": "MEMBER",
                    "X-Debug-User": second_user_id,
                    "X-CSRF-Token": "local-csrf",
                },
            )
            assert deleted.status_code == 204
            put(member_id, 4)
        aggregate_jobs = [
            job for job in state.jobs.values() if job["job_type"] == "aggregate_votes"
        ]
        assert [job["payload"]["version"] for job in aggregate_jobs] == [1, 2, 3, 4, 5]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_durable_oauth_challenge_contract_job_dedupe_and_share_projection() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        challenge = {
            "provider": "mock",
            "nonce": "nonce-1",
            "redirect_uri": "http://localhost:3000/auth/callback",
            "return_to": "/articles/a",
            "expires_at": utc_now() + timedelta(minutes=5),
        }
        await repository.create_oauth_challenge(state="state-1", challenge=challenge)
        consumed = await repository.consume_oauth_challenge("state-1")
        assert consumed and consumed["return_to"] == "/articles/a"
        assert await repository.consume_oauth_challenge("state-1") is None

        first = await repository.enqueue("export_user", "user-1", {"user_id": "user-1"})
        second = await repository.enqueue("export_user", "user-1", {"user_id": "other"})
        assert first == second
        with pytest.raises(JobPayloadError):
            await repository.enqueue("export_user", "malformed", {})
        assert JobAccepted.model_validate({"job_id": first["id"], "status": second["status"]})
        jobs = list((await session.scalars(select(Job))).all())
        assert len([row for row in jobs if row.job_type == "export_user"]) == 1

        user = await repository.create_or_get_oauth_user(
            provider="mock", subject="subject-1", display_name="Tester"
        )
        assert UserView.model_validate(await repository.get_user(user["id"]))

    await engine.dispose()


@pytest.mark.asyncio
async def test_vote_revision_payload_is_monotonic_and_share_snapshot_records_confirmation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        user_id, second_user_id, source_id, article_id = (new_ulid() for _ in range(4))
        now = utc_now()
        session.add_all(
            [
                User(
                    id=user_id,
                    role=UserRole.MEMBER,
                    status=UserStatus.ACTIVE,
                    display_name="Tester",
                    created_at=now,
                    deleted_at=None,
                ),
                User(
                    id=second_user_id,
                    role=UserRole.MEMBER,
                    status=UserStatus.ACTIVE,
                    display_name="Second tester",
                    created_at=now,
                    deleted_at=None,
                ),
                Source(
                    id=source_id,
                    name="Source",
                    source_type=SourceType.RSS,
                    canonical_url="https://example.test",
                    policy_status=SourcePolicyStatus.APPROVED,
                    robots_status=SourcePolicyStatus.APPROVED,
                    terms_status=SourcePolicyStatus.APPROVED,
                    active=True,
                ),
                Article(
                    id=article_id,
                    source_id=source_id,
                    canonical_url="https://example.test/article",
                    canonical_url_hash=b"a" * 32,
                    title="Article",
                    author=None,
                    published_at=now,
                    current_version_id=None,
                    status=ArticleStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.commit()
        first = await repository.put_vote_row(
            user_id=user_id,
            article_id=article_id,
            values={"x": 1, "y": 2, "z": 3, "sensationalism": 4},
        )
        second = await repository.put_vote_row(
            user_id=second_user_id,
            article_id=article_id,
            values={"x": 5, "y": 6, "z": 7, "sensationalism": 8},
        )
        third = await repository.put_vote_row(
            user_id=user_id,
            article_id=article_id,
            values={"x": 9, "y": 10, "z": 11, "sensationalism": 12},
        )
        assert first and second and third
        assert [first["revision"], second["revision"], third["revision"]] == [1, 2, 3]
        assert await repository.delete_vote_row(
            user_id=second_user_id, article_id=article_id
        )
        fourth = await repository.put_vote_row(
            user_id=user_id,
            article_id=article_id,
            values={"x": 13, "y": 14, "z": 15, "sensationalism": 16},
        )
        assert fourth and fourth["revision"] == 5
        aggregate_jobs = list(
            (
                await session.scalars(
                    select(Job).where(Job.job_type == "aggregate_votes").order_by(Job.created_at)
                )
            ).all()
        )
        assert [job.payload_json["version"] for job in aggregate_jobs] == [1, 2, 3, 4, 5]

    await engine.dispose()
