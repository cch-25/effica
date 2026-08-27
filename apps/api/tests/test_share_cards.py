from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.main import app
from apps.api.app.state import PlatformState


def test_memory_share_snapshot_preserves_unmeasured_self_reported_axis() -> None:
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
        "active": True,
        "created_at": created_at,
    }

    card = state.create_share_card(user_id, "default", "Member")
    snapshot = card["snapshot"]

    assert snapshot["sensationalism"] is None
    assert snapshot["coordinate"]["sensationalism"] is None
    assert snapshot["activity"] == snapshot["credit_total"] == 0
    assert snapshot["tier"] == "Explorer"


def test_memory_share_snapshot_uses_newest_behavioral_profile_and_numeric_axis() -> None:
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

    assert snapshot["x"] == snapshot["coordinate"]["x"] == 12
    assert snapshot["sensationalism"] == snapshot["coordinate"]["sensationalism"] == 64.0
    assert snapshot["tier"] == "Bridge Builder"


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
