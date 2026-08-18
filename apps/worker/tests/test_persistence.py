from __future__ import annotations

import asyncio
from typing import Any

from apps.api.app.jobs.payloads import JobPayloadError, validate_job_payload
from apps.worker.worker.handlers import build_default_registry
from apps.worker.worker.main import WorkerConfig, WorkerRuntime
from apps.worker.worker.queue import Job, JobStatus, MemoryQueueRepository
from apps.worker.worker.services import (
    MariaDBIdempotencyStore,
    MariaDBResultApplier,
    MemoryResultApplier,
    ResultApplicationError,
)


def test_all_builtin_payload_contracts_accept_identifier_only_producers() -> None:
    values: dict[str, dict[str, Any]] = {
        "crawl": {"source_id": "source-1"},
        "cluster": {"article_ids": ["article-1"]},
        "analyze": {"article_version_id": "version-1"},
        "aggregate_votes": {"article_id": "article-1"},
        "calculate_score": {"article_version_id": "version-1"},
        "recommend_weights": {"recommendation_id": "recommendation-1"},
        "simulate_weights": {"weight_id": "weight-1"},
        "render_share_card": {"share_card_id": "card-1"},
        "export_user": {"user_id": "user-1"},
        "delete_user": {"user_id": "user-1", "confirmed": True},
        "merge_issue": {"source_issue_id": "issue-1", "target_issue_id": "issue-2"},
        "split_issue": {"issue_id": "issue-1", "article_ids": ["article-1"]},
    }
    for job_type, payload in values.items():
        assert validate_job_payload(job_type, payload) == payload


def test_payload_contract_rejects_unsafe_crawler_and_delete_replay() -> None:
    for job_type, payload in (
        ("crawl", {"url": "https://example.test", "source_type": "CRAWLER"}),
        ("delete_user", {"user_id": "user-1"}),
    ):
        try:
            validate_job_payload(job_type, payload)
        except JobPayloadError as exc:
            assert exc.code == "INVALID_JOB_PAYLOAD"
        else:  # pragma: no cover - assertion makes the contract failure clear.
            raise AssertionError(f"{job_type} payload unexpectedly accepted")


def test_runtime_applies_result_before_succeeded_and_keeps_memory_result() -> None:
    async def scenario() -> None:
        repository = MemoryQueueRepository(
            [Job(id="01RESULT", job_type="fixture", payload={"value": 7})]
        )
        applier = MemoryResultApplier()
        registry = build_default_registry()
        registry.register("fixture", lambda payload, context: {"value": payload["value"]})
        runtime = WorkerRuntime(
            repository,
            registry=registry,
            result_applier=applier,
            config=WorkerConfig(worker_id="result-worker"),
        )

        assert await runtime.process_one()
        stored = await repository.get("01RESULT")
        assert stored is not None
        assert stored.status is JobStatus.SUCCEEDED
        assert stored.result == {"value": 7}
        assert applier.results["01RESULT"] == {"value": 7}
        assert applier.contexts["01RESULT"]["job_type"] == "fixture"

    asyncio.run(scenario())


def test_memory_worker_job_chain_has_durable_result_records() -> None:
    async def scenario() -> None:
        jobs = [
            Job("01CHAINCRAWL", "crawl", {"url": "HTTPS://Example.test/a?b=2&a=1"}),
            Job("01CHAINANALYZE", "analyze", {"article_version_id": "version-1", "text": "evidence"}),
            Job(
                "01CHAINVOTES",
                "aggregate_votes",
                {
                    "article_id": "article-1",
                    "votes": [
                        {
                            "vote_id": "vote-1",
                            "user_id": "user-1",
                            "article_id": "article-1",
                            "revision": 1,
                            "x": 1,
                            "y": 2,
                            "z": 3,
                            "sensationalism": 4,
                        }
                    ],
                },
            ),
            Job(
                "01CHAINSCORE",
                "calculate_score",
                {
                    "article_version_id": "version-1",
                    "components": {
                        "model": {"x": 1, "y": 2, "z": 3},
                        "relative": {"x": 0, "y": 0, "z": 0},
                        "crowd": {"x": 0, "y": 0, "z": 0},
                        "source": {"x": 0, "y": 0, "z": 0},
                    },
                    "weights": {"model": 1, "relative": 0, "crowd": 0, "source": 0},
                },
            ),
            Job(
                "01CHAINSPLIT",
                "split_issue",
                {"issue_id": "issue-1", "article_ids": ["article-1"]},
            ),
            Job(
                "01CHAINSHARE",
                "render_share_card",
                {
                    "share_card_id": "card-1",
                    "snapshot": {"coordinate": {"x": 1, "y": 2, "z": 3}, "tier": "Explorer"},
                },
            ),
            Job("01CHAINEXPORT", "export_user", {"user_id": "user-1", "records": {"profile": {}}}),
            Job("01CHAINDELETE", "delete_user", {"user_id": "user-1", "confirmed": True}),
        ]
        repository = MemoryQueueRepository(jobs)
        applier = MemoryResultApplier()
        runtime = WorkerRuntime(
            repository,
            result_applier=applier,
            config=WorkerConfig(worker_id="chain-worker"),
        )
        while await runtime.process_one():
            pass
        rows = await repository.list_jobs()
        assert {row.status for row in rows} == {JobStatus.SUCCEEDED}
        assert set(applier.results) == {row.id for row in jobs}
        assert applier.results["01CHAINANALYZE"]["article_version_id"] == "version-1"
        assert applier.results["01CHAINEXPORT"]["artifact"]["records"] == {"profile": {}}
        assert applier.results["01CHAINDELETE"]["status"] == "scheduled"

    asyncio.run(scenario())


def test_durable_idempotency_read_does_not_fail_open_on_database_error() -> None:
    class FailingSession:
        async def execute(self, statement, params):
            raise RuntimeError("database unavailable")

        async def close(self):
            return None

    async def scenario() -> None:
        store = MariaDBIdempotencyStore(lambda: FailingSession())
        try:
            await store.begin("aggregate_votes:dedupe-1")
        except RuntimeError as exc:
            assert str(exc) == "database unavailable"
        else:  # pragma: no cover - assertion makes fail-open regressions clear.
            raise AssertionError("idempotency read unexpectedly treated DB failure as a cache miss")

    asyncio.run(scenario())


def test_mariadb_applier_allocates_revisioned_snapshots_and_canonical_alias_ids() -> None:
    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Session:
        def __init__(self):
            self.alias_ids: dict[str, str] = {}
            self.snapshots: list[dict[str, Any]] = []
            self.assessment_alias_ids: list[str] = []

        def begin(self):
            return Transaction()

        async def close(self):
            return None

        async def execute(self, statement, params):
            query = str(statement).lower()
            if "select version from vote_aggregate_snapshots" in query:
                rows = sorted(self.snapshots, key=lambda row: row["version"], reverse=True)
                return rows[:1]
            if "insert into vote_aggregate_snapshots" in query:
                self.snapshots.append({"version": params["version"]})
                return []
            if "insert into model_aliases" in query:
                self.alias_ids.setdefault(params["alias"], params["id"])
                return []
            if "select id from model_aliases" in query:
                alias_id = self.alias_ids.get(params["alias"])
                return [] if alias_id is None else [{"id": alias_id}]
            if "insert into model_assessments" in query:
                self.assessment_alias_ids.append(params["alias_id"])
            return []

    async def scenario() -> None:
        session = Session()
        applier = MariaDBResultApplier(lambda: session)
        first = Job(id="01AGGREGATE1", job_type="aggregate_votes", payload={"article_id": "article-1", "vote_revision": 1})
        second = Job(id="01AGGREGATE2", job_type="aggregate_votes", payload={"article_id": "article-1", "vote_revision": 2})
        aggregate = {"article_id": "article-1", "vote_revision": 1, "aggregate": {"count": 1}, "segments": {}}
        await applier.apply(first, aggregate)
        await applier.apply(second, {**aggregate, "vote_revision": 2})
        assert [row["version"] for row in session.snapshots] == [1, 2]
        try:
            await applier.apply(first, aggregate)
        except ResultApplicationError as exc:
            assert "stale" in str(exc)
        else:  # pragma: no cover - assertion makes snapshot overwrite regressions clear.
            raise AssertionError("stale aggregate revision was accepted")

        analysis = {"article_version_id": "version-1", "assessments": [{"model_alias": "shared", "x": 1}]}
        await applier.apply(Job(id="01ANALYSIS1", job_type="analyze"), analysis)
        await applier.apply(Job(id="01ANALYSIS2", job_type="analyze"), analysis)
        assert len(session.assessment_alias_ids) == 2
        assert session.assessment_alias_ids[0] == session.assessment_alias_ids[1]

    asyncio.run(scenario())


def test_share_card_apply_requires_updated_row() -> None:
    from datetime import UTC, datetime

    class Result:
        def __init__(self, rowcount: int) -> None:
            self.rowcount = rowcount

    class Session:
        def __init__(self, rowcount: int) -> None:
            self.rowcount = rowcount

        async def execute(self, statement, params):
            return Result(self.rowcount)

    async def scenario() -> None:
        applier = MariaDBResultApplier(lambda: None)
        job = Job(
            id="01SHARE",
            job_type="render_share_card",
            payload={"share_card_id": "card-1"},
        )
        result = {"share_card_id": "card-1", "blob_id": "blob-1"}
        now = datetime.now(UTC)
        await applier._apply_share_card(Session(1), job, result, now)
        try:
            await applier._apply_share_card(Session(0), job, result, now)
        except ResultApplicationError:
            return
        raise AssertionError("share card apply succeeded without updating a row")

    asyncio.run(scenario())


def test_analysis_result_enqueues_validated_score_and_cluster_jobs_once() -> None:
    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Session:
        def __init__(self) -> None:
            self.jobs: dict[tuple[str, str], dict[str, Any]] = {}
            self.statements: list[tuple[str, dict[str, Any]]] = []
            self.audit: dict[str, Any] | None = None

        def begin(self):
            return Transaction()

        async def close(self):
            return None

        async def execute(self, statement, params=None):
            query = str(statement)
            values = dict(params or {})
            self.statements.append((query, values))
            lowered = query.lower()
            if "select after_json" in lowered:
                return [] if self.audit is None else [{"after_json": self.audit}]
            if "select id from model_aliases" in lowered:
                return [{"id": "alias-1"}]
            if "select article_id from article_versions" in lowered:
                return [{"article_id": "article-1"}]
            if "insert into jobs" in lowered:
                key = (str(values["job_type"]), str(values["dedupe_key"]))
                self.jobs.setdefault(key, {**values, "status": "PENDING"})
            if "insert into audit_logs" in lowered and "job_result_applied" in lowered:
                self.audit = values["after_json"]
            return []

    async def scenario() -> None:
        session = Session()
        applier = MariaDBResultApplier(lambda: session)
        job = Job(
            id="01ANALYZE",
            job_type="analyze",
            payload={"article_version_id": "version-1", "request_id": "request-1"},
        )
        result = {
            "article_version_id": "version-1",
            "assessments": [{"model_alias": "shared", "x": 1}],
        }
        await applier.apply(job, result)
        await applier.apply(job, result)

        downstream = {
            key: value for key, value in session.jobs.items() if key[0] in {"calculate_score", "cluster"}
        }
        assert {key[0] for key in downstream} == {"calculate_score", "cluster"}
        assert all(value["status"] == "PENDING" for value in downstream.values())
        assert all(value["payload_json"] for value in downstream.values())
        assert len(session.jobs) == 2
        job_inserts = [query for query, _ in session.statements if "INSERT INTO jobs" in query]
        assert job_inserts
        assert all("ON DUPLICATE KEY UPDATE" in query for query in job_inserts)

    asyncio.run(scenario())
