from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from apps.worker.worker.handlers.registry import HandlerRegistry
from apps.worker.worker.main import WorkerConfig, WorkerRuntime
from apps.worker.worker.queue import Job, JobStatus, MariaDBQueueRepository, MemoryQueueRepository
from apps.worker.worker.services import (
    MariaDBCrawlScheduler,
    MariaDBResultApplier,
    ResultApplicationError,
)


def test_worker_package_does_not_preload_module_entrypoint() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import apps.worker.worker; "
                "assert 'apps.worker.worker.main' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None, *, rowcount: int = 0):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _Transaction:
    def __init__(self, session: Any) -> None:
        self.session = session
        self.snapshot: Any = None

    async def __aenter__(self):
        lock = getattr(self.session, "transaction_lock", None)
        if lock is not None:
            await lock.acquire()
        snapshot = getattr(self.session, "snapshot", None)
        self.snapshot = snapshot() if callable(snapshot) else None
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is not None and self.snapshot is not None:
            self.session.restore(self.snapshot)
        lock = getattr(self.session, "transaction_lock", None)
        if lock is not None:
            lock.release()
        return False


def test_worker_recovers_after_transient_claim_failures() -> None:
    class FlakyQueue(MemoryQueueRepository):
        def __init__(self) -> None:
            super().__init__([Job(id="job-1", job_type="ok")])
            self.failures = 2

        async def claim(self, *args, **kwargs):
            if self.failures:
                self.failures -= 1
                raise RuntimeError("temporary database outage")
            return await super().claim(*args, **kwargs)

    async def scenario() -> None:
        repository = FlakyQueue()
        runtime = WorkerRuntime(
            repository,
            registry=HandlerRegistry({"ok": lambda payload, context: {"ok": True}}),
            config=WorkerConfig(
                worker_id="flaky-worker",
                poll_interval_seconds=0.001,
                queue_error_backoff_base_seconds=0.001,
                queue_error_backoff_max_seconds=0.002,
                backoff_jitter_ratio=0,
            ),
        )
        task = asyncio.create_task(runtime.run_forever())
        try:
            for _ in range(100):
                stored = await repository.get("job-1")
                if stored is not None and stored.status is JobStatus.SUCCEEDED:
                    break
                await asyncio.sleep(0.002)
            else:
                raise AssertionError("worker did not recover after queue outage")
        finally:
            await runtime.stop()
            await task
        health = runtime.health_snapshot()
        assert health["queue_errors"] == 2
        assert health["claimed"] == 1
        assert health["succeeded"] == 1

    asyncio.run(scenario())


def test_scheduler_ticks_immediately_when_worker_starts() -> None:
    class Scheduler:
        interval_seconds = 60.0

        def __init__(self) -> None:
            self.calls: list[str] = []
            self.runtime: WorkerRuntime | None = None

        async def tick(self, worker_id: str) -> int:
            self.calls.append(worker_id)
            assert self.runtime is not None
            self.runtime.request_stop()
            return 3

    async def scenario() -> None:
        scheduler = Scheduler()
        runtime = WorkerRuntime(
            MemoryQueueRepository(),
            crawl_scheduler=scheduler,
            config=WorkerConfig(worker_id="scheduler-worker", poll_interval_seconds=0.001),
        )
        scheduler.runtime = runtime
        await asyncio.wait_for(runtime.run_forever(), timeout=1)
        assert scheduler.calls == ["scheduler-worker"]

    asyncio.run(scenario())


def test_crawl_scheduler_is_leader_safe_bounded_and_interval_deduplicated() -> None:
    now = datetime(2026, 8, 27, 3, 0, tzinfo=UTC)

    class LockSession:
        def __init__(self, state: dict[str, Any]) -> None:
            self.state = state

        async def execute(self, statement, params=None):
            query = str(statement)
            if "GET_LOCK" in query:
                return _Result([{"acquired": self.state.get("lock_available", 1)}])
            return _Result()

        async def close(self):
            return None

    class MutationSession:
        def __init__(self, state: dict[str, Any]) -> None:
            self.state = state

        def begin(self):
            return _Transaction(self)

        async def execute(self, statement, params=None):
            query = str(statement)
            values = dict(params or {})
            self.state["statements"].append((query, values))
            if "FROM sources s" in query:
                return _Result(self.state["sources"][:2])
            if "INSERT INTO jobs" in query:
                key = values["dedupe_key"]
                if key in self.state["jobs"]:
                    return _Result(rowcount=0)
                self.state["jobs"].add(key)
                return _Result(rowcount=1)
            return _Result(rowcount=1)

        async def close(self):
            return None

    state: dict[str, Any] = {
        "lock_available": 1,
        "sources": [
            {
                "id": f"source-{index}",
                "canonical_url": f"https://source-{index}.example/rss",
                "adapter_type": "RSS",
                "config_json": {
                    "scheduled": True,
                    "feed_url": f"https://feeds.example/source-{index}.xml",
                },
                "rate_limit": 12,
                "raw_payload_retention_days": 7,
                "policy_status": "APPROVED",
                "robots_status": "APPROVED",
                "terms_status": "APPROVED",
            }
            for index in range(3)
        ],
        "jobs": set(),
        "statements": [],
    }
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        return LockSession(state) if calls % 2 else MutationSession(state)

    async def scenario() -> None:
        scheduler = MariaDBCrawlScheduler(
            factory,
            interval_seconds=900,
            batch_size=2,
            max_attempts=5,
            clock=lambda: now,
        )
        assert await scheduler.tick("worker-a") == 2
        assert await scheduler.tick("worker-b") == 0
        assert len(state["jobs"]) == 2
        source_queries = [query for query, _ in state["statements"] if "FROM sources s" in query]
        assert source_queries
        assert "s.active = 1" in source_queries[0]
        assert source_queries[0].count("= 'APPROVED'") == 3
        assert "JSON_EXTRACT(a2.config_json, '$.scheduled')" in source_queries[0]
        assert "a2.adapter_type = s.source_type" not in source_queries[0]
        assert "LIMIT 2" in source_queries[0]
        inserted = [
            params
            for query, params in state["statements"]
            if "INSERT INTO jobs" in query
        ]
        assert all(params["max_attempts"] == 5 for params in inserted)
        assert {params["dedupe_key"] for params in inserted} == state["jobs"]
        scheduled_payload = json.loads(inserted[0]["payload_json"])
        assert scheduled_payload["source_type"] == "RSS"
        assert scheduled_payload["url"].startswith("https://feeds.example/")
        assert scheduled_payload["config"]["scheduled"] is True
        assert scheduled_payload["rate_limit"] == 12
        assert scheduled_payload["raw_payload_retention_days"] == 7

        state["lock_available"] = 0
        assert await scheduler.tick("worker-c") == 0

    asyncio.run(scenario())


def test_crawl_claim_projection_becomes_running() -> None:
    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def execute(self, statement, params=None):
            self.calls.append((str(statement), dict(params or {})))
            return _Result(rowcount=1)

    async def scenario() -> None:
        session = Session()
        repository = MariaDBQueueRepository(lambda: None)
        moment = datetime(2026, 8, 27, tzinfo=UTC)
        await repository._mark_crawl_running(
            session,
            Job(
                id="crawl-job",
                job_type="crawl",
                payload={"crawl_run_id": "crawl-run"},
            ),
            moment=moment,
        )
        assert len(session.calls) == 1
        query, params = session.calls[0]
        assert "status = 'RUNNING'" in query
        assert "status = 'PENDING'" in query
        assert params == {"crawl_run_id": "crawl-run", "now": moment}

    asyncio.run(scenario())


def test_score_promotion_is_serialized_active_and_job_replay_is_idempotent() -> None:
    class ScoreSession:
        def __init__(self) -> None:
            self.transaction_lock = asyncio.Lock()
            self.scores: dict[str, dict[str, Any]] = {}
            self.audit: dict[str, str] = {}
            self.domain_writes = 0

        def snapshot(self):
            return copy.deepcopy((self.scores, self.audit, self.domain_writes))

        def restore(self, snapshot):
            self.scores, self.audit, self.domain_writes = snapshot

        def begin(self):
            return _Transaction(self)

        async def close(self):
            return None

        async def execute(self, statement, params=None):
            query = str(statement)
            lowered = query.lower()
            values = dict(params or {})
            if "select id from jobs" in lowered:
                return _Result([{"id": values["job_id"]}])
            if "select after_json from audit_logs" in lowered:
                value = self.audit.get(values["job_id"])
                return _Result([] if value is None else [{"after_json": value}])
            if "select id from article_versions" in lowered:
                return _Result([{"id": values["version_id"]}])
            if "insert into score_versions" in lowered:
                self.domain_writes += 1
                if values["id"] not in self.scores:
                    self.scores[values["id"]] = {
                        "id": values["id"],
                        "version_id": values["version_id"],
                        "weight_id": values["weight_id"],
                        "status": "draft",
                    }
                return _Result(rowcount=1)
            if "from score_versions" in lowered and "weight_revision_id" in lowered:
                row = self.scores.get(values["score_id"])
                return _Result([] if row is None else [{"id": row["id"]}])
            if "set status = 'superseded'" in lowered:
                for row in self.scores.values():
                    if (
                        row["version_id"] == values["version_id"]
                        and row["status"] == "active"
                        and row["id"] != values["score_id"]
                    ):
                        row["status"] = "superseded"
                return _Result(rowcount=1)
            if "set status = 'active'" in lowered:
                row = self.scores.get(values["score_id"])
                if row is None:
                    return _Result(rowcount=0)
                row["status"] = "active"
                return _Result(rowcount=1)
            if "insert into audit_logs" in lowered:
                self.audit[values["target_id"]] = values["after_json"]
                return _Result(rowcount=1)
            return _Result()

    async def scenario() -> None:
        session = ScoreSession()
        applier = MariaDBResultApplier(lambda: session)
        jobs = [
            Job(id="score-job-1", job_type="calculate_score"),
            Job(id="score-job-2", job_type="calculate_score"),
        ]
        results = [
            {"article_version_id": "version-1", "weight_revision_id": "weight-1", "x": 1},
            {"article_version_id": "version-1", "weight_revision_id": "weight-2", "x": 2},
        ]
        await asyncio.gather(
            *(applier.apply(job, result) for job, result in zip(jobs, results, strict=True))
        )
        assert [row["status"] for row in session.scores.values()].count("active") == 1
        assert [row["status"] for row in session.scores.values()].count("superseded") == 1
        await applier.apply(
            Job(id="score-job-3", job_type="calculate_score"),
            {
                "article_version_id": "version-1",
                "weight_revision_id": "weight-2",
                "x": 3,
            },
        )
        assert len(session.scores) == 3
        assert [row["status"] for row in session.scores.values()].count("active") == 1
        assert [row["status"] for row in session.scores.values()].count("superseded") == 2
        writes = session.domain_writes
        await applier.apply(jobs[0], results[0])
        assert session.domain_writes == writes
        assert [row["status"] for row in session.scores.values()].count("active") == 1

    asyncio.run(scenario())


def test_crawl_analysis_dedupe_is_stable_across_crawl_generations() -> None:
    class Session:
        def __init__(self, *, trusted: bool = False) -> None:
            self.trusted = trusted

        async def execute(self, statement, params=None):
            lowered = str(statement).lower()
            if "select id from articles" in lowered:
                return _Result([{"id": "article-1"}])
            if "select id from article_versions" in lowered:
                return _Result([{"id": "version-1"}])
            if "from model_assessments" in lowered and self.trusted:
                return _Result([{"id": "assessment-1"}])
            return _Result(rowcount=1)

    async def scenario() -> None:
        applier = MariaDBResultApplier(lambda: None)
        enqueued: list[tuple[str, str]] = []

        async def store_blob(session, payload, **kwargs):
            return "blob-1"

        async def enqueue_job(session, job_type, payload, *, dedupe_key, **kwargs):
            enqueued.append((job_type, dedupe_key))
            return "downstream-job"

        applier._store_blob = store_blob  # type: ignore[method-assign]
        applier._enqueue_job = enqueue_job  # type: ignore[method-assign]
        result = {
            "source_id": "source-1",
            "articles": [
                {
                    "article_id": "article-1",
                    "article_version_id": "version-1",
                    "url": "https://example.test/article",
                    "title": "Article",
                    "content": "Substantive article body",
                }
            ],
        }
        now = datetime(2026, 8, 27, tzinfo=UTC)
        first = Job(id="crawl-job-1", job_type="crawl", payload={"source_id": "source-1"})
        await applier._apply_crawl(Session(), first, result, now)
        await applier._apply_crawl(Session(), first, result, now)
        await applier._apply_crawl(
            Session(),
            Job(id="crawl-job-2", job_type="crawl", payload={"source_id": "source-1"}),
            result,
            now,
        )
        analyze_keys = [key for job_type, key in enqueued if job_type == "analyze"]
        assert analyze_keys[0] == analyze_keys[1]
        assert analyze_keys == [
            "article-version:version-1:crawl-analysis",
            "article-version:version-1:crawl-analysis",
            "article-version:version-1:crawl-analysis",
        ]
        await applier._apply_crawl(
            Session(trusted=True),
            Job(id="crawl-job-3", job_type="crawl", payload={"source_id": "source-1"}),
            result,
            now,
        )
        assert len([key for job_type, key in enqueued if job_type == "analyze"]) == 3

    asyncio.run(scenario())


def test_failed_score_activation_rolls_back_previous_active_score() -> None:
    class FailingScoreSession:
        def __init__(self) -> None:
            self.scores = {
                "old-score": {
                    "id": "old-score",
                    "version_id": "version-1",
                    "weight_id": "old-weight",
                    "status": "active",
                }
            }

        def snapshot(self):
            return copy.deepcopy(self.scores)

        def restore(self, snapshot):
            self.scores = snapshot

        def begin(self):
            return _Transaction(self)

        async def close(self):
            return None

        async def execute(self, statement, params=None):
            lowered = str(statement).lower()
            values = dict(params or {})
            if "select id from jobs" in lowered:
                return _Result([{"id": values["job_id"]}])
            if "select after_json from audit_logs" in lowered:
                return _Result()
            if "select id from article_versions" in lowered:
                return _Result([{"id": "version-1"}])
            if "insert into score_versions" in lowered:
                self.scores[values["id"]] = {
                    "id": values["id"],
                    "version_id": values["version_id"],
                    "weight_id": values["weight_id"],
                    "status": "draft",
                }
                return _Result(rowcount=1)
            if "from score_versions" in lowered and "weight_revision_id" in lowered:
                return _Result([{"id": next(reversed(self.scores))}])
            if "set status = 'superseded'" in lowered:
                self.scores["old-score"]["status"] = "superseded"
                return _Result(rowcount=1)
            if "set status = 'active'" in lowered:
                return _Result(rowcount=0)
            if "where id = :score_id and status = 'active'" in lowered:
                return _Result()
            return _Result()

    async def scenario() -> None:
        session = FailingScoreSession()
        applier = MariaDBResultApplier(lambda: session)
        try:
            await applier.apply(
                Job(id="failed-score-job", job_type="calculate_score"),
                {
                    "article_version_id": "version-1",
                    "weight_revision_id": "new-weight",
                    "x": 10,
                },
            )
        except ResultApplicationError as exc:
            assert "activation" in str(exc)
        else:
            raise AssertionError("failed score activation unexpectedly committed")
        assert session.scores == {
            "old-score": {
                "id": "old-score",
                "version_id": "version-1",
                "weight_id": "old-weight",
                "status": "active",
            }
        }

    asyncio.run(scenario())
