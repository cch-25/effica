from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.main import app
from apps.api.app.state import STATE, PlatformState, new_id


def _comparison_url(issue_id: str, article_ids: list[str]) -> str:
    query = "&".join(f"article_ids={article_id}" for article_id in article_ids)
    return f"/api/v1/issues/{issue_id}/comparison?{query}"


def test_public_issue_comparison_is_reviewed_strict_and_provenanced() -> None:
    client = TestClient(app)
    issue = next(iter(STATE.issues.values()))
    article_ids = issue["article_ids"][:3]
    response = client.get(_comparison_url(issue["id"], article_ids))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["etag"].startswith('"')
    body = response.json()
    assert body["issue"]["source_count"] >= 3
    assert len(body["articles"]) == 3
    assert body["common_facts"][0]["article_ids"]
    assert body["reviewed_at"]
    assert all(row["assessment"]["provider"] == "openai" for row in body["articles"])
    assert all(row["frame"]["headline_frame"] for row in body["articles"])
    assert all("vote_aggregate" in row for row in body["articles"])


def test_issue_comparison_validation_and_readiness_errors_are_stable() -> None:
    client = TestClient(app)
    issue = next(iter(STATE.issues.values()))
    article_ids = issue["article_ids"]

    duplicate = client.get(_comparison_url(issue["id"], [article_ids[0], article_ids[0]]))
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "COMPARE_DUPLICATE_ARTICLE"

    outside = client.get(_comparison_url(issue["id"], [article_ids[0], new_id()]))
    assert outside.status_code == 400
    assert outside.json()["error"]["code"] == "COMPARE_ARTICLE_OUTSIDE_ISSUE"

    too_many = client.get(_comparison_url(issue["id"], article_ids + [new_id(), new_id()]))
    assert too_many.status_code == 422
    assert too_many.json()["error"]["code"] == "VALIDATION_ERROR"

    snapshot = STATE.comparison_snapshots[issue["id"]]
    original_status = snapshot["status"]
    try:
        snapshot["status"] = "PENDING"
        pending = client.get(_comparison_url(issue["id"], article_ids[:2]))
        assert pending.status_code == 409
        assert pending.json()["error"]["code"] == "COMPARISON_NOT_READY"
    finally:
        snapshot["status"] = original_status

    article = STATE.articles[article_ids[0]]
    original_version_id = article["current_version_id"]
    try:
        article["current_version_id"] = new_id()
        stale = client.get(_comparison_url(issue["id"], article_ids[:2]))
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "COMPARISON_NOT_READY"
    finally:
        article["current_version_id"] = original_version_id


def test_admin_comparison_review_is_explicit_provenanced_and_idempotent() -> None:
    state = PlatformState()
    issue = next(iter(state.issues.values()))
    snapshot = state.comparison_snapshots[issue["id"]]
    snapshot["reviewed_at"] = None
    snapshot["reviewed_by"] = None
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            preview = client.get(
                f"/api/v1/admin/issues/{issue['id']}/comparison",
                headers={"X-Debug-Role": "ANALYST"},
            )
            assert preview.status_code == 200
            assert preview.json()["snapshot_id"] == snapshot["id"]
            assert preview.json()["reviewed_at"] is None

            forbidden = client.post(
                f"/api/v1/admin/issues/{issue['id']}/comparison",
                json={"reason": "reviewed against the current sources"},
                headers={
                    "X-Debug-Role": "REVIEWER",
                    "X-CSRF-Token": "local-csrf",
                    "Idempotency-Key": "comparison-review-forbidden",
                    "If-Match": snapshot["id"],
                },
            )
            assert forbidden.status_code == 403

            headers = {
                "X-Debug-Role": "ADMIN",
                "X-CSRF-Token": "local-csrf",
                "Idempotency-Key": "comparison-review-success",
                "If-Match": snapshot["id"],
            }
            reviewed = client.post(
                f"/api/v1/admin/issues/{issue['id']}/comparison",
                json={"reason": "reviewed against the current sources"},
                headers=headers,
            )
            replay = client.post(
                f"/api/v1/admin/issues/{issue['id']}/comparison",
                json={"reason": "reviewed against the current sources"},
                headers=headers,
            )
            assert reviewed.status_code == 200
            assert replay.status_code == 200
            assert replay.json() == reviewed.json()
            assert reviewed.json()["reviewed_by"]

            public = client.get(
                _comparison_url(issue["id"], issue["article_ids"][:2])
            )
            assert public.status_code == 200
    finally:
        app.dependency_overrides.clear()
