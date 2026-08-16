import asyncio
import base64
from datetime import timedelta

from fastapi.testclient import TestClient

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.main import app
from apps.api.app.state import PlatformState, utcnow
from apps.worker.worker.handlers.analyze import handle as analyze_article
from apps.worker.worker.handlers.calculate_score import handle as calculate_score
from apps.worker.worker.handlers.render_share_card import handle as render_share_card


def headers(role: str, **extra: str) -> dict[str, str]:
    return {"X-Debug-Role": role, "X-CSRF-Token": "local-csrf", **extra}


def test_external_network_free_full_vertical_slice() -> None:
    state = PlatformState()
    app.dependency_overrides[get_state] = lambda: state
    member = headers("MEMBER")
    analyst = headers("ANALYST")
    reviewer = headers("REVIEWER")
    admin = headers("ADMIN")

    with TestClient(app) as client:
        assert client.get("/health/live").json()["status"] == "live"
        assert client.get("/health/ready").json()["status"] == "ready"

        # Local OAuth adapter is deterministic and never contacts an external provider.
        start = client.get(
            "/api/v1/auth/mock/start",
            params={"redirect_uri": "http://localhost:3000/auth/callback"},
            follow_redirects=False,
        )
        assert start.status_code == 302
        oauth_state = start.cookies["oauth_state"]
        callback = client.get(
            "/api/v1/auth/mock/callback",
            params={
                "state": oauth_state,
                "nonce": "fixture-nonce",
                "redirect_uri": "http://localhost:3000/auth/callback",
            },
            headers={"X-OAuth-State": oauth_state},
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert callback.cookies.get("session")

        consents = client.get("/api/v1/consents", headers=member).json()
        for consent in consents:
            response = client.post(
                "/api/v1/me/consents",
                json={"consent_version_id": consent["id"], "granted": True},
                headers=member,
            )
            assert response.status_code == 200
        questionnaire_id = next(iter(state.questionnaires))
        profile = client.post(
            "/api/v1/me/questionnaire-responses",
            json={
                "questionnaire_version_id": questionnaire_id,
                "answers": {"economic": -15, "social": 20, "international": 5},
            },
            headers=member,
        )
        assert profile.status_code == 200
        assert profile.json()["kind"] == "SELF_REPORTED"

        # Fixture ingestion mirrors the constrained single-model runtime.
        issue_page = client.get("/api/v1/issues").json()
        issue_id = issue_page["items"][0]["id"]
        articles = client.get(f"/api/v1/issues/{issue_id}/articles").json()["items"]
        assert len(articles) == 3
        article_id = articles[0]["id"]
        assert len(client.get(f"/api/v1/articles/{article_id}/assessments").json()["assessments"]) == 1
        score = client.get(f"/api/v1/articles/{article_id}/score").json()
        assert set(score["components"]) == {
            "llm_ensemble",
            "relative_framing",
            "qualified_votes",
            "shrunk_source_prior",
        }
        analysis_result = asyncio.run(
            analyze_article(
                {
                    "article_version_id": articles[0]["current_version_id"],
                    "title": articles[0]["title"],
                    "text": "근거 자료를 바탕으로 정책 변화와 시장 규제를 비교한다.",
                    "source_name": articles[0]["source"],
                }
            )
        ).value
        assert len(analysis_result["assessments"]) == 1
        assert all(item["model_alias"].startswith("stub-") for item in analysis_result["assessments"])
        score_result = asyncio.run(
            calculate_score(
                {
                    "article_version_id": articles[0]["current_version_id"],
                    "components": {
                        "model": {axis: analysis_result["ensemble"][axis] or 0 for axis in ("x", "y", "z")},
                        "relative": {"x": 0, "y": 0, "z": 0},
                        "crowd": {"x": 0, "y": 0, "z": 0},
                        "source": {"x": 0, "y": 0, "z": 0},
                        "model_confidence": analysis_result["ensemble"]["confidence"],
                        "model_spread": analysis_result["ensemble"]["spread"],
                        "sensationalism": analysis_result["ensemble"]["sensationalism"] or 0,
                    },
                    "weights": {"model": 0.65, "relative": 0.15, "crowd": 0.1, "source": 0.1, "version": "fixture-v1"},
                    "fact_check": {"verdict": "UNVERIFIED"},
                }
            )
        ).value
        assert -100 <= score_result["x"] <= 100
        assert len(score_result["canonical_sha256"]) == 64
        feed = client.get("/api/v1/feed", params={"mode": "personalized"}, headers=member).json()
        assert feed["personalized"] is True
        assert all(item["reason_code"] for item in feed["items"])

        read = client.post(
            f"/api/v1/articles/{article_id}/read-sessions",
            json={"return_path": f"/articles/{article_id}"},
            headers=member,
        ).json()
        token = read["redirect_url"].rsplit("/", 1)[-1]
        outbound = client.get(f"/api/v1/r/{token}", headers=member, follow_redirects=False)
        assert outbound.status_code == 302
        state.read_sessions[read["read_session_id"]]["outbound_at"] = utcnow() - timedelta(seconds=20)
        returned = client.post(
            f"/api/v1/read-sessions/{read['read_session_id']}/return",
            json={"client_elapsed_ms": 20_000},
            headers=member,
        ).json()
        assert returned["status"] == "eligible"
        assert returned["credit_delta"] == 10

        vote = client.put(
            f"/api/v1/articles/{article_id}/vote",
            json={"x": -20, "y": 10, "z": 5, "sensationalism": 25},
            headers=member,
        )
        assert vote.json()["revision"] == 1
        aggregate = client.get(f"/api/v1/articles/{article_id}/votes/aggregate").json()
        assert aggregate["qualified_count"] == 1

        efficacy = client.post(
            "/api/v1/me/efficacy-responses",
            json={"questionnaire_version_id": questionnaire_id, "answers": {"q1": 60, "q2": 80}},
            headers=member,
        ).json()
        assert efficacy["normalized_score"] == 70

        share_job = client.post(
            "/api/v1/share-cards",
            json={
                "template": "default",
                "display_name": "Local Member",
                "political_data_publication_confirmed": True,
            },
            headers=member,
        )
        assert share_job.status_code == 202
        card = next(iter(state.share_cards.values()))
        render_job = state.jobs[share_job.json()["job_id"]]
        rendered = asyncio.run(render_share_card(render_job["payload"]))
        png = base64.b64decode(rendered.value["png_base64"])
        assert png.startswith(b"\x89PNG")
        assert rendered.value["byte_size"] <= 10 * 1024 * 1024
        public = client.get(f"/api/v1/public/share/{card['public_token']}")
        assert public.status_code == 200
        image = client.get(f"/api/v1/public/share/{card['public_token']}/image")
        assert image.headers["content-type"] == "image/png"
        assert client.get(
            f"/api/v1/public/share/{card['public_token']}/image",
            headers={"If-None-Match": image.headers["etag"]},
        ).status_code == 304
        assert client.delete(f"/api/v1/share-cards/{card['id']}", headers=member).status_code == 204
        assert client.get(f"/api/v1/public/share/{card['public_token']}").status_code == 404

        # Immutable weight draft -> 7/30 simulations -> guarded publish -> new-revision rollback.
        base_id = next(iter(state.weights))
        created = client.post(
            "/api/v1/admin/weights",
            json={
                "weights": {"model": 0.6, "relative": 0.2, "crowd": 0.1, "source": 0.1},
                "guardrails": {"max_revision_delta": 0.1},
                "based_on_revision_id": base_id,
            },
            headers={**admin, "Idempotency-Key": "create-weight-1"},
        ).json()
        client.post(
            f"/api/v1/admin/weights/{created['id']}/simulate",
            json={"windows": [7, 30]},
            headers={**analyst, "Idempotency-Key": "simulate-weight-1"},
        )
        approval = client.post(
            f"/api/v1/admin/autopilot/recommendations/{created['id']}/approve",
            json={"reason": "fixture review passed"},
            headers={**reviewer, "Idempotency-Key": "approve-weight-1"},
        )
        assert approval.json()["status"] == "APPROVED"
        published = client.post(
            f"/api/v1/admin/weights/{created['id']}/publish",
            json={"reason": "fixture passed guardrails"},
            headers={**admin, "Idempotency-Key": "publish-weight-1", "If-Match": "1"},
        )
        assert published.status_code == 200
        rollback = client.post(
            f"/api/v1/admin/weights/{created['id']}/rollback",
            json={"target_revision_id": base_id, "reason": "fixture rollback"},
            headers={**admin, "Idempotency-Key": "rollback-weight-1", "If-Match": "2"},
        )
        assert rollback.status_code == 200
        assert rollback.json()["id"] not in {base_id, created["id"]}

        generation = client.post(
            "/api/v1/admin/autopilot/recommendations/generate",
            json={"evidence_window_days": 30},
            headers={**reviewer, "Idempotency-Key": "recommendation-generate-1"},
        )
        assert generation.status_code == 202
        recommendation_id = next(
            row["id"]
            for row in state.recommendations.values()
            if row["status"] == "PENDING_REVIEW"
        )
        approved = client.post(
            f"/api/v1/admin/autopilot/recommendations/{recommendation_id}/approve",
            json={"reason": "fixture review"},
            headers={**reviewer, "Idempotency-Key": "recommendation-review-1"},
        )
        assert approved.json()["status"] == "APPROVED"
        assert state.audit

    app.dependency_overrides.clear()
