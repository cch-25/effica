from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.main import app
from apps.api.app.state import STATE, PlatformState, new_id, utcnow


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


def test_public_issue_comparison_suppresses_one_voter_and_reveals_five() -> None:
    state = PlatformState()
    issue = next(iter(state.issues.values()))
    article_ids = issue["article_ids"][:2]
    target_article_id = article_ids[0]

    def add_vote(index: int) -> None:
        state.votes[(f"comparison-user-{index}", target_article_id)] = [
            {
                "x": 20,
                "y": -10,
                "z": 5,
                "sensationalism": 25,
                "revision": index,
                "quality_status": "QUALIFIED",
                "active": True,
                "updated_at": utcnow(),
            }
        ]

    add_vote(1)
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            one_voter = client.get(_comparison_url(issue["id"], article_ids))
            for index in range(2, 6):
                add_vote(index)
            five_voters = client.get(_comparison_url(issue["id"], article_ids))
    finally:
        app.dependency_overrides.clear()

    one_aggregate = one_voter.json()["articles"][0]["vote_aggregate"]
    assert one_aggregate["qualified_count"] == 1
    assert one_aggregate["small_segments_suppressed"] is True
    assert one_aggregate["qualified"] == {
        "x": None, "y": None, "z": None, "sensationalism": None,
    }
    five_aggregate = five_voters.json()["articles"][0]["vote_aggregate"]
    assert five_aggregate["qualified_count"] == 5
    assert five_aggregate["small_segments_suppressed"] is False
    assert five_aggregate["qualified"] == {
        "x": 20.0, "y": -10.0, "z": 5.0, "sensationalism": 25.0,
    }


def test_admin_can_exclude_unsupported_fact_without_erasing_generated_evidence() -> None:
    state = PlatformState()
    issue = next(iter(state.issues.values()))
    snapshot = state.comparison_snapshots[issue["id"]]
    snapshot["reviewed_at"] = None
    original = deepcopy(snapshot["common_facts"])
    excluded_id = original[0]["id"]
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            headers = {"X-Debug-Role": "ADMIN", "X-CSRF-Token": "local-csrf", "If-Match": snapshot["id"]}
            invalid = client.post(
                f"/api/v1/admin/issues/{issue['id']}/comparison",
                headers={**headers, "Idempotency-Key": "unknown-fact"},
                json={"reason": "근거를 대조했습니다.", "excluded_fact_ids": ["unknown"]},
            )
            assert invalid.status_code == 400
            assert snapshot["reviewed_at"] is None
            result = client.post(
                f"/api/v1/admin/issues/{issue['id']}/comparison",
                headers={**headers, "Idempotency-Key": "exclude-unsupported-fact"},
                json={"reason": "수치가 한 기사에만 있어 공통 사실에서 제외합니다.", "excluded_fact_ids": [excluded_id]},
            )
            assert result.status_code == 200
            public = client.get(_comparison_url(issue["id"], issue["article_ids"][:2]))
            assert public.status_code == 200
            assert excluded_id not in {fact["id"] for fact in public.json()["common_facts"]}
            assert snapshot["generated_common_facts"] == original
    finally:
        app.dependency_overrides.clear()

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


@pytest.mark.parametrize("article_count", [3, 5, 8])
def test_admin_comparison_review_is_explicit_provenanced_and_idempotent(article_count: int) -> None:
    state = PlatformState()
    issue = next(iter(state.issues.values()))
    snapshot = state.comparison_snapshots[issue["id"]]
    template_id = issue["article_ids"][0]
    while len(snapshot["article_frames"]) < article_count:
        article_id = new_id()
        article = deepcopy(state.articles[template_id])
        article["id"] = article_id
        article["current_version_id"] = new_id()
        state.articles[article_id] = article
        issue["article_ids"].append(article_id)
        snapshot["article_frames"][article_id] = deepcopy(snapshot["article_frames"][template_id])
        snapshot["article_version_ids"][article_id] = article["current_version_id"]
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
