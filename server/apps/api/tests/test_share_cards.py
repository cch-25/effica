from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.domains.sharing import NEWS_CONSUMPTION_SNAPSHOT_VERSION
from apps.api.app.domains.users import POLITICAL_QUESTIONNAIRE_VERSION
from apps.api.app.main import app
from apps.api.app.state import PlatformState


def test_memory_share_snapshot_uses_only_current_questionnaire_ideology() -> None:
    state = PlatformState()
    user_id = state.default_users["MEMBER"]
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    state.profiles["self-reported"] = {
        "user_id": user_id,
        "kind": "SELF_REPORTED",
        "x": -15,
        "y": 20,
        "z": 5,
        "sensationalism": None,
        "confidence": 0.65,
        "source_version": POLITICAL_QUESTIONNAIRE_VERSION,
        "active": True,
        "created_at": created_at,
    }

    card = state.create_share_card(user_id, "default", "Member")
    snapshot = card["snapshot"]

    assert snapshot["snapshot_schema_version"] == NEWS_CONSUMPTION_SNAPSHOT_VERSION
    assert snapshot["ideology"] == {
        "completed": True,
        "x": -15,
        "y": 20,
        "z": 5,
        "confidence": 0.65,
        "questionnaire_version": POLITICAL_QUESTIONNAIRE_VERSION,
        "questionnaire_status": "beta",
    }
    assert "sensationalism" not in snapshot
    assert "coordinate" not in snapshot
    assert "credit_total" not in snapshot
    assert "activity" not in snapshot
    assert "actor_id" not in snapshot["publication_consent"]


def test_memory_share_snapshot_never_reinterprets_behavioral_profile_as_ideology() -> None:
    state = PlatformState()
    user_id = state.default_users["MEMBER"]
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    state.profiles["self-reported"] = {
        "user_id": user_id,
        "kind": "SELF_REPORTED",
        "x": -15,
        "y": 20,
        "z": 5,
        "sensationalism": None,
        "confidence": 0.65,
        "source_version": POLITICAL_QUESTIONNAIRE_VERSION,
        "active": True,
        "created_at": created_at,
    }
    state.profiles["behavioral"] = {
        "user_id": user_id,
        "kind": "BEHAVIORAL",
        "x": 12,
        "y": 0,
        "z": 0,
        "sensationalism": 64,
        "confidence": 0.5,
        "active": True,
        "created_at": created_at + timedelta(seconds=1),
    }
    state.credits[user_id] = [{"delta": 200}]

    card = state.create_share_card(user_id, "default", "Member")
    snapshot = card["snapshot"]

    assert snapshot["ideology"]["x"] == -15
    assert snapshot["ideology"]["y"] == 20
    assert snapshot["ideology"]["z"] == 5
    assert "sensationalism" not in snapshot
    assert "credit_total" not in snapshot


def test_owner_can_retry_failed_memory_share_card() -> None:
    state = PlatformState()
    user_id = state.default_users["MEMBER"]
    card = state.create_share_card(user_id, "default", "Member")
    job = next(
        row
        for row in state.jobs.values()
        if row["job_type"] == "render_share_card" and row["dedupe_key"] == card["id"]
    )
    card["status"] = "failed"
    job["status"] = "DEAD"
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/share-cards/{card['id']}/retry",
                headers={
                    "X-Debug-Role": "MEMBER",
                    "X-Debug-Token": "local-debug-token",
                    "X-CSRF-Token": "local-csrf",
                },
            )
        assert response.status_code == 202
        assert response.json() == {
            "job_id": job["id"],
            "status": "PENDING",
            "share_card_id": card["id"],
        }
        assert card["status"] == "queued"
        assert job["attempts"] == 0
    finally:
        app.dependency_overrides.clear()


def test_legacy_memory_share_card_image_is_unavailable() -> None:
    state = PlatformState()
    user_id = state.default_users["MEMBER"]
    card = state.create_share_card(user_id, "default", "Member")
    card["snapshot"] = {
        "x": -70,
        "sensationalism": 90,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    card["png"] = b"legacy behavioral profile image"
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/public/share/{card['public_token']}/image")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PUBLIC_SHARE_IMAGE_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()
