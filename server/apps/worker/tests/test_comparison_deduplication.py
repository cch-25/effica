from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apps.worker.worker.queue import Job
from apps.worker.worker.services import (
    MariaDBResultApplier,
    _comparison_input_fingerprint,
)


class Rows:
    def __init__(self, rows=()):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)


ARTICLES = [
    {"article_id": "a", "article_version_id": "va", "title": "First"},
    {"article_id": "b", "article_version_id": "vb", "title": "Second"},
]
MODEL = {"actual_model_id": "gpt-5.6-luna", "reasoning_effort": "none"}
NOW = datetime(2026, 9, 6, tzinfo=UTC)


class ComparisonSession:
    def __init__(self):
        self.version = 1
        self.articles = [dict(row) for row in ARTICLES]
        self.snapshots = []
        self.writes = []

    async def execute(self, statement, params):
        sql = " ".join(str(statement).split())
        if sql.startswith("SELECT i.id, i.version"):
            return Rows([{"id": "issue", "version": self.version}])
        if sql.startswith("SELECT version FROM issues"):
            return Rows([{"version": self.version}])
        if sql.startswith("SELECT a.id AS article_id"):
            return Rows(self.articles)
        if sql.startswith("SELECT id, actual_model_id"):
            return Rows([{"id": "model", "actual_model_id": MODEL["actual_model_id"], "config_json": MODEL}])
        if sql.startswith("SELECT id, issue_version, article_frames_json"):
            return Rows(self.snapshots)
        if sql.startswith("SELECT article_frames_json FROM issue_comparison_snapshots"):
            return Rows(self.snapshots)
        self.writes.append((sql, dict(params)))
        return Rows()


def test_comparison_job_identity_ignores_issue_revision_but_tracks_real_inputs():
    async def scenario():
        session = ComparisonSession()
        applier = MariaDBResultApplier(lambda: None)
        jobs = []

        async def enqueue(_session, _kind, payload, **kwargs):
            jobs.append((dict(payload), kwargs["dedupe_key"]))

        applier._enqueue_job = enqueue
        for revision in (1, 2, 99):
            session.version = revision
            await applier._enqueue_issue_comparisons_for_article(
                session, article_id="a", request_id=None, now=NOW
            )
        assert len({key for _, key in jobs}) == 1
        session.articles[0]["article_version_id"] = "updated"
        await applier._enqueue_issue_comparisons_for_article(
            session, article_id="a", request_id=None, now=NOW
        )
        assert jobs[-1][1] != jobs[0][1]
        session.articles[0]["title"] = "Corrected headline"
        await applier._enqueue_issue_comparisons_for_article(
            session, article_id="a", request_id=None, now=NOW
        )
        assert jobs[-1][1] != jobs[-2][1]

    asyncio.run(scenario())


def test_same_comparison_is_reused_for_new_issue_revision_without_provider_job():
    async def scenario():
        session = ComparisonSession()
        session.version = 8
        session.snapshots = [{
            "id": "old", "issue_version": 1, "status": "SUCCEEDED",
            "article_frames_json": {
                "input_fingerprint": _comparison_input_fingerprint(ARTICLES, "issue-comparison-v1"),
                "comparison_model_identity": MODEL,
            },
        }]
        applier = MariaDBResultApplier(lambda: None)
        await applier._enqueue_issue_comparisons_for_article(
            session, article_id="a", request_id=None, now=NOW
        )
        assert len(session.writes) == 1
        sql, params = session.writes[0]
        assert "INSERT INTO issue_comparison_snapshots" in sql
        assert "NULL, NULL" in sql  # Do not carry editorial approval forward.
        assert params["issue_version"] == 8

        session.writes.clear()
        session.snapshots[0]["issue_version"] = 8
        await applier._enqueue_issue_comparisons_for_article(
            session, article_id="a", request_id=None, now=NOW
        )
        assert not session.writes  # Existing current review is untouched.

    asyncio.run(scenario())


def test_stale_comparison_completion_never_supersedes_current_snapshot():
    async def scenario():
        session = ComparisonSession()
        session.version = 8
        applier = MariaDBResultApplier(lambda: None)
        job = Job(id="compare", job_type="build_issue_comparison", payload={
            "issue_id": "issue", "issue_version": 1, "prompt_version": "issue-comparison-v1",
        })
        result = {"article_version_ids": {"a": "old-version", "b": "vb"}}
        await applier._apply_issue_comparison(session, job, result, NOW)
        assert not session.writes
        result["article_version_ids"]["a"] = "va"
        await applier._apply_issue_comparison(session, job, result, NOW)
        assert len(session.writes) == 2
        assert all(params["issue_version"] == 8 for _, params in session.writes)

    asyncio.run(scenario())


def test_duplicate_comparison_completion_preserves_existing_review():
    async def scenario():
        session = ComparisonSession()
        fingerprint = _comparison_input_fingerprint(ARTICLES, "issue-comparison-v1")
        session.snapshots = [{"article_frames_json": {
            "input_fingerprint": fingerprint,
            "comparison_model_identity": MODEL,
        }}]
        applier = MariaDBResultApplier(lambda: None)
        await applier._apply_issue_comparison(
            session,
            Job(id="compare", job_type="build_issue_comparison", payload={
                "issue_id": "issue", "issue_version": 1, "prompt_version": "issue-comparison-v1",
            }),
            {"article_version_ids": {"a": "va", "b": "vb"},
             "input_fingerprint": fingerprint, "comparison_model_identity": MODEL},
            NOW,
        )
        assert not session.writes

    asyncio.run(scenario())


def test_cluster_replay_does_not_increment_issue_version():
    async def scenario():
        class Session:
            def __init__(self):
                self.members = {"a", "b", "c"}
                self.updates = []

            async def execute(self, statement, params):
                sql = " ".join(str(statement).split())
                if sql.startswith("SELECT id, title, summary, topic, status, version"):
                    return Rows([{"id": "issue", "title": "Story", "summary": "Summary",
                                  "topic": "정치", "status": "active", "version": 7}])
                if sql.startswith("SELECT article_id FROM issue_memberships"):
                    return Rows([{"article_id": value} for value in self.members])
                if sql.startswith("INSERT INTO issues"):
                    self.updates.append(dict(params))
                return Rows()

        session = Session()
        applier = MariaDBResultApplier(lambda: None)
        candidate = {"issue_id": "issue", "article_ids": ["a", "b", "c"],
                     "source_count": 3, "title": "Story", "summary": "Summary", "topic": "정치"}
        job = Job(id="cluster", job_type="cluster")
        await applier._apply_cluster(session, job, {"candidates": [candidate]}, NOW)
        assert session.updates[-1]["version_increment"] == 0
        assert session.updates[-1]["changed"] is False
        candidate["article_ids"].append("d")
        await applier._apply_cluster(session, job, {"candidates": [candidate]}, NOW)
        assert session.updates[-1]["version_increment"] == 1

    asyncio.run(scenario())
