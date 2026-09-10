from __future__ import annotations

import math
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.domains.sharing import (
    NEWS_CONSUMPTION_SNAPSHOT_VERSION,
    consumption_diversity,
    public_snapshot_view,
)
from apps.api.app.domains.users import (
    POLITICAL_QUESTIONNAIRE_VERSION,
    political_questionnaire_schema,
    political_questionnaire_scoring,
    score_political_questionnaire,
)
from apps.api.app.main import app
from apps.api.app.state import PlatformState, utcnow


def _answers(value: int = 3) -> dict[str, int]:
    return {
        question["id"]: value for question in political_questionnaire_schema()["questions"]
    }


def _member_headers() -> dict[str, str]:
    return {
        "X-Debug-Role": "MEMBER",
        "X-Debug-Token": "local-debug-token",
        "X-CSRF-Token": "local-csrf",
    }


def test_beta_questionnaire_is_balanced_and_scores_directional_reversals() -> None:
    schema = political_questionnaire_schema()
    scoring = political_questionnaire_scoring()
    questions = schema["questions"]

    assert len(questions) == 30
    assert Counter(question["axis"] for question in questions) == Counter(
        {"x": 10, "y": 10, "z": 10}
    )
    for axis in ("x", "y", "z"):
        assert Counter(
            question["direction"] for question in questions if question["axis"] == axis
        ) == Counter({-1: 5, 1: 5})

    neutral = score_political_questionnaire(
        schema_json=schema,
        scoring_json=scoring,
        answers=_answers(),
    )
    assert (neutral.x, neutral.y, neutral.z, neutral.confidence) == (0, 0, 0, 1.0)

    positive_answers = {
        question["id"]: 5 if question["direction"] == 1 else 1
        for question in questions
    }
    positive = score_political_questionnaire(
        schema_json=schema,
        scoring_json=scoring,
        answers=positive_answers,
    )
    assert (positive.x, positive.y, positive.z) == (100, 100, 100)


@pytest.mark.parametrize("invalid", [True, 3.5, "3", math.nan, math.inf, 0, 6])
def test_beta_questionnaire_rejects_every_invalid_answer_shape(invalid: object) -> None:
    answers: dict[str, object] = _answers()
    answers["economic_01"] = invalid
    with pytest.raises(ValueError, match="QUESTIONNAIRE_ANSWER_INVALID"):
        score_political_questionnaire(
            schema_json=political_questionnaire_schema(),
            scoring_json=political_questionnaire_scoring(),
            answers=answers,
        )

    missing = _answers()
    missing.pop("economic_01")
    with pytest.raises(ValueError, match="QUESTIONNAIRE_ANSWER_INVALID"):
        score_political_questionnaire(
            schema_json=political_questionnaire_schema(),
            scoring_json=political_questionnaire_scoring(),
            answers=missing,
        )


def test_consumption_diversity_requires_both_volume_and_perspective_balance() -> None:
    assert consumption_diversity([])["diversity_score"] == 0
    single_band = consumption_diversity([-60] * 12)
    assert single_band["diversity_score"] == 0
    balanced = consumption_diversity([-60, 0, 60] * 4)
    assert balanced == {
        "diversity_score": 100,
        "diversity_article_count": 12,
        "diversity_perspective_counts": {
            "negative_x": 4,
            "center": 4,
            "positive_x": 4,
        },
        "diversity_policy_version": "consumption-diversity-v1",
    }


def test_vote_response_distinguishes_first_save_and_never_creates_ideology() -> None:
    state = PlatformState()
    article_id = next(iter(state.articles))
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            first = client.put(
                f"/api/v1/articles/{article_id}/vote",
                headers=_member_headers(),
                json={"x": -90, "y": 20, "z": 30, "sensationalism": 40},
            )
            second = client.put(
                f"/api/v1/articles/{article_id}/vote",
                headers=_member_headers(),
                json={"x": 90, "y": -20, "z": -30, "sensationalism": 60},
            )
            progress = client.get("/api/v1/me/progress", headers=_member_headers())
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert first.json()["save_status"] == "created"
    assert first.json()["credit_delta"] == 10
    assert second.status_code == 200
    assert second.json()["save_status"] == "updated"
    assert second.json()["credit_delta"] == 0
    assert sum(item["delta"] for item in state.credits[state.default_users["MEMBER"]]) == 10
    assert progress.json()["ideology"] == {
        "completed": False,
        "x": 0,
        "y": 0,
        "z": 0,
        "confidence": 0.0,
        "questionnaire_version": None,
        "questionnaire_status": "not_completed",
    }
    assert not state.profiles


def test_public_vote_aggregate_suppresses_one_voter_and_reveals_five() -> None:
    state = PlatformState()
    article_id = next(iter(state.articles))

    def add_vote(index: int) -> None:
        state.votes[(f"cohort-user-{index}", article_id)] = [
            {
                "x": 12,
                "y": -8,
                "z": 5,
                "sensationalism": 30,
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
            one_voter = client.get(f"/api/v1/articles/{article_id}/votes/aggregate")
            for index in range(2, 6):
                add_vote(index)
            five_voters = client.get(f"/api/v1/articles/{article_id}/votes/aggregate")
    finally:
        app.dependency_overrides.clear()

    assert one_voter.status_code == 200
    assert one_voter.json()["qualified_count"] == 1
    assert one_voter.json()["small_segments_suppressed"] is True
    assert one_voter.json()["qualified"] == {
        "x": None,
        "y": None,
        "z": None,
        "sensationalism": None,
    }
    assert five_voters.status_code == 200
    assert five_voters.json()["qualified_count"] == 5
    assert five_voters.json()["small_segments_suppressed"] is False
    assert five_voters.json()["qualified"] == {
        "x": 12.0,
        "y": -8.0,
        "z": 5.0,
        "sensationalism": 30.0,
    }


def test_persisted_behavioral_profile_cannot_drive_feed_or_user_coordinates() -> None:
    state = PlatformState()
    user_id = state.default_users["MEMBER"]
    state.profiles["questionnaire"] = {
        "id": "questionnaire",
        "user_id": user_id,
        "kind": "SELF_REPORTED",
        "x": -35,
        "y": 25,
        "z": 15,
        "confidence": 1.0,
        "source_version": POLITICAL_QUESTIONNAIRE_VERSION,
        "active": True,
        "created_at": utcnow(),
    }
    state.profiles["legacy-behavior"] = {
        "id": "legacy-behavior",
        "user_id": user_id,
        "kind": "BEHAVIORAL",
        "x": 100,
        "y": 90,
        "z": 0,
        "confidence": 1.0,
        "source_version": "behavior-v1",
        "active": True,
        "created_at": utcnow(),
    }
    positive_article_id = next(
        article_id
        for article_id, scores in state.scores.items()
        if scores[-1]["x"] > 10
    )
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            before_feed = client.get(
                "/api/v1/feed?mode=personalized", headers=_member_headers()
            )
            vote = client.put(
                f"/api/v1/articles/{positive_article_id}/vote",
                headers=_member_headers(),
                json={"x": 100, "y": 100, "z": 100, "sensationalism": 100},
            )
            after_feed = client.get(
                "/api/v1/feed?mode=personalized", headers=_member_headers()
            )
            points = client.get(
                "/api/v1/visualization/points?type=user", headers=_member_headers()
            )
            progress = client.get("/api/v1/me/progress", headers=_member_headers())
    finally:
        app.dependency_overrides.clear()

    assert before_feed.status_code == after_feed.status_code == 200
    assert before_feed.json()["personalized"] is True
    assert before_feed.json()["items"][0]["coordinate"]["x"] == -35
    assert after_feed.json()["items"] == before_feed.json()["items"]
    assert vote.json()["credit_delta"] == 10
    assert points.json()["items"] == [
        {
            "entity_type": "user",
            "entity_id": "questionnaire",
            "label": "검사 기반 이념 위치",
            "x": -35.0,
            "y": 25.0,
            "z": 15.0,
            "sensationalism": None,
            "confidence": 1.0,
        }
    ]
    assert progress.json()["ideology"]["x"] == -35


def test_share_without_survey_is_neutral_and_contains_only_public_aggregates() -> None:
    state = PlatformState()
    user_id = state.default_users["MEMBER"]
    card = state.create_share_card(user_id, "default", "Member")
    snapshot = card["snapshot"]

    assert snapshot["snapshot_schema_version"] == NEWS_CONSUMPTION_SNAPSHOT_VERSION
    assert snapshot["ideology"]["completed"] is False
    assert (snapshot["ideology"]["x"], snapshot["ideology"]["y"], snapshot["ideology"]["z"]) == (
        0,
        0,
        0,
    )
    assert "answers" not in snapshot
    assert "actor_id" not in snapshot["publication_consent"]
    assert "credit_total" not in snapshot


def test_legacy_public_snapshot_is_marked_and_never_recast_as_ideology() -> None:
    projected = public_snapshot_view(
        {
            "x": -70,
            "y": 50,
            "z": 20,
            "sensationalism": 90,
            "publication_consent": {
                "confirmation_version": "share-card-publication-v1",
                "confirmed_at": "2026-01-01T00:00:00+00:00",
                "actor_id": "private-user-id",
            },
        }
    )
    assert projected["legacy"] is True
    assert projected["ideology"]["completed"] is False
    assert "x" not in projected
    assert "sensationalism" not in projected
    assert "actor_id" not in projected["publication_consent"]


def test_current_public_snapshot_is_strictly_whitelisted() -> None:
    projected = public_snapshot_view(
        {
            "snapshot_schema_version": NEWS_CONSUMPTION_SNAPSHOT_VERSION,
            "diversity_score": 60,
            "diversity_article_count": 9,
            "diversity_perspective_counts": {
                "negative_x": 3,
                "center": 3,
                "positive_x": 3,
                "user_id": "nested-private-user",
            },
            "diversity_policy_version": "consumption-diversity-v1",
            "ideology": {
                "completed": True,
                "x": -20,
                "y": 10,
                "z": 5,
                "confidence": 1,
                "questionnaire_version": POLITICAL_QUESTIONNAIRE_VERSION,
                "questionnaire_status": "beta",
                "raw_answers": {"economic_01": 5},
                "behavioral_profile": {"x": 99},
            },
            "created_at": "2026-09-10T00:00:00+00:00",
            "political_data_publication_confirmed": True,
            "publication_consent": {
                "confirmation_version": "share-card-publication-v1",
                "confirmed_at": "2026-09-10T00:00:00+00:00",
                "actor_id": "private-user",
            },
            "user_id": "private-user",
            "actor_id": "private-user",
            "raw_answers": {"economic_01": 5},
            "credits": [{"delta": 999}],
            "behavioral_profile": {"x": 99},
        }
    )

    assert set(projected) == {
        "snapshot_schema_version",
        "diversity_score",
        "diversity_article_count",
        "diversity_perspective_counts",
        "diversity_policy_version",
        "ideology",
        "created_at",
        "political_data_publication_confirmed",
        "publication_consent",
    }
    assert set(projected["diversity_perspective_counts"]) == {
        "negative_x",
        "center",
        "positive_x",
    }
    assert set(projected["ideology"]) == {
        "completed",
        "x",
        "y",
        "z",
        "confidence",
        "questionnaire_version",
        "questionnaire_status",
    }
    assert set(projected["publication_consent"]) == {
        "confirmation_version",
        "confirmed_at",
    }


def test_beta_questionnaire_api_accepts_raw_likert_answers() -> None:
    state = PlatformState()
    questionnaire_id = next(
        key for key, value in state.questionnaires.items() if value["kind"] == "onboarding"
    )
    app.dependency_overrides[get_state] = lambda: state
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/me/questionnaire-responses",
                headers=_member_headers(),
                json={
                    "questionnaire_version_id": questionnaire_id,
                    "answers": _answers(),
                },
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["source_version"] == POLITICAL_QUESTIONNAIRE_VERSION
    assert (response.json()["x"], response.json()["y"], response.json()["z"]) == (0, 0, 0)
