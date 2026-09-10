from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from apps.worker.worker.main import WorkerConfig, WorkerRuntime
from apps.worker.worker.queue import (
    ExponentialBackoff,
    Job,
    JobStatus,
    MariaDBQueueRepository,
    MemoryQueueRepository,
)


def _run(coro):
    return asyncio.run(coro)


def test_concurrent_claim_has_one_winner():
    async def scenario():
        repo = MemoryQueueRepository([Job(id="01JOB", job_type="noop")])

        claims = await asyncio.gather(
            *(repo.claim(f"worker-{index}", lease_seconds=30) for index in range(24))
        )
        winners = [claim for claim in claims if claim is not None]
        assert len(winners) == 1
        assert winners[0].id == "01JOB"
        assert (await repo.get("01JOB")).status == JobStatus.LEASED

    _run(scenario())


def test_user_jobs_preempt_existing_background_queue_rows():
    async def scenario():
        now = datetime(2026, 1, 1, tzinfo=UTC)
        repo = MemoryQueueRepository(
            [
                Job(id="crawl", job_type="crawl", priority=10, available_at=now),
                Job(id="analyze", job_type="analyze", priority=10, available_at=now),
                # Models a row created before producer-side user priority was added.
                Job(id="export", job_type="export_user", priority=0, available_at=now),
            ],
            clock=lambda: now,
        )

        claimed = await repo.claim("worker", now=now)

        assert claimed is not None
        assert claimed.id == "export"

    _run(scenario())


def test_mariadb_claim_order_prioritizes_user_jobs_before_pipeline_work():
    order = MariaDBQueueRepository(lambda: None)._claim_order()

    assert order.index(
        "job_type IN ('render_share_card', 'export_user', 'delete_user')"
    ) < order.index(
        "job_type = 'cluster'"
    )


def test_concurrent_workers_execute_one_side_effect():
    async def scenario():
        repo = MemoryQueueRepository([Job(id="01SIDE", job_type="side_effect")])
        calls = []

        async def side_effect(payload, context):
            calls.append(context.job_id)
            await asyncio.sleep(0)
            return {"ok": True}

        from apps.worker.worker.handlers.registry import HandlerRegistry

        registry = HandlerRegistry({"side_effect": side_effect})
        workers = [
            WorkerRuntime(repo, registry=registry, config=WorkerConfig(worker_id=f"w-{index}"))
            for index in range(12)
        ]
        await asyncio.gather(*(worker.process_one() for worker in workers))
        assert calls == ["01SIDE"]
        assert (await repo.get("01SIDE")).status == JobStatus.SUCCEEDED

    _run(scenario())


def test_runtime_control_blocks_claims_while_stopped():
    async def scenario():
        class StoppedControl:
            async def is_enabled(self) -> bool:
                return False

        repo = MemoryQueueRepository([Job(id="01STOPPED", job_type="side_effect")])
        calls: list[str] = []

        async def side_effect(payload, context):
            calls.append(context.job_id)
            return {"ok": True}

        from apps.worker.worker.handlers.registry import HandlerRegistry

        runtime = WorkerRuntime(
            repo,
            registry=HandlerRegistry({"side_effect": side_effect}),
            runtime_control=StoppedControl(),
        )
        assert await runtime.process_one() is False
        assert calls == []
        assert (await repo.get("01STOPPED")).status == JobStatus.PENDING

    _run(scenario())


def test_retry_backoff_and_dead_after_max_attempts():
    async def scenario():
        repo = MemoryQueueRepository([Job(id="01RETRY", job_type="missing", max_attempts=2)])
        runtime = WorkerRuntime(
            repo,
            config=WorkerConfig(
                worker_id="worker",
                backoff_base_seconds=0,
                backoff_max_seconds=0,
                backoff_jitter_ratio=0,
            ),
        )

        assert await runtime.process_one()
        first = await repo.get("01RETRY")
        assert first.status == JobStatus.FAILED  # unknown handlers are not retryable

        assert await runtime.retry_job("01RETRY")
        assert await runtime.process_one()
        second = await repo.get("01RETRY")
        assert second.status == JobStatus.FAILED

    _run(scenario())


def test_retryable_failure_reaches_dead():
    async def scenario():
        repo = MemoryQueueRepository([Job(id="01DEAD", job_type="failing", max_attempts=2)])

        async def failing(payload, context):
            raise RuntimeError("provider unavailable")

        from apps.worker.worker.handlers.registry import HandlerRegistry

        runtime = WorkerRuntime(
            repo,
            registry=HandlerRegistry({"failing": failing}),
            config=WorkerConfig(
                worker_id="worker",
                backoff_base_seconds=0,
                backoff_max_seconds=0,
                backoff_jitter_ratio=0,
            ),
        )
        assert await runtime.process_one()
        assert (await repo.get("01DEAD")).status == JobStatus.PENDING
        assert await runtime.process_one()
        assert (await repo.get("01DEAD")).status == JobStatus.DEAD

    _run(scenario())


def test_durable_apply_conflict_is_not_retried():
    async def scenario():
        from apps.worker.worker.handlers.registry import HandlerRegistry
        from apps.worker.worker.services import ResultApplicationError

        assert ResultApplicationError("conflict").retryable is False

        repo = MemoryQueueRepository([Job(id="01SHAREFAIL", job_type="noop", max_attempts=5)])

        class RejectingApplier:
            async def apply(self, job, result, *, context=None):
                raise ResultApplicationError("share card could not be updated")

        runtime = WorkerRuntime(
            repo,
            registry=HandlerRegistry({"noop": lambda payload, context: {"ok": True}}),
            result_applier=RejectingApplier(),
            config=WorkerConfig(worker_id="worker", backoff_base_seconds=0, backoff_max_seconds=0),
        )
        assert await runtime.process_one()
        stored = await repo.get("01SHAREFAIL")
        assert stored.status == JobStatus.FAILED
        assert stored.attempts == 1

    _run(scenario())


def test_non_retryable_fail_is_terminal_while_attempts_remain():
    async def scenario():
        now = datetime(2026, 1, 1, tzinfo=UTC)
        repo = MemoryQueueRepository(
            [Job(id="01TERM", job_type="noop", max_attempts=5, available_at=now)],
            clock=lambda: now,
        )
        claimed = await repo.claim("worker", lease_seconds=30, now=now)
        assert claimed is not None
        status = await repo.fail(
            "01TERM",
            "worker",
            {"code": "RESULT_APPLICATION_FAILED"},
            retryable=False,
            now=now,
        )
        stored = await repo.get("01TERM")
        assert status == JobStatus.FAILED
        assert stored.status == JobStatus.FAILED
        assert stored.attempts == 1

    _run(scenario())


def test_heartbeat_and_graceful_release():
    async def scenario():
        now = datetime(2026, 1, 1, tzinfo=UTC)
        repo = MemoryQueueRepository([Job(id="01LEASE", job_type="noop", available_at=now)], clock=lambda: now)
        claimed = await repo.claim("worker", lease_seconds=1, now=now)
        assert claimed is not None
        assert await repo.heartbeat("01LEASE", "worker", lease_seconds=10, now=now)
        assert (await repo.get("01LEASE")).lease_expires_at == now + timedelta(seconds=10)
        assert await repo.release_leases("worker", now=now) == 1
        released = await repo.get("01LEASE")
        assert released.status == JobStatus.PENDING
        assert released.lease_owner is None

    _run(scenario())


def test_stale_attempt_cannot_mutate_new_lease_owned_by_same_worker():
    async def scenario():
        now = datetime(2026, 1, 1, tzinfo=UTC)
        repo = MemoryQueueRepository(
            [Job(id="01FENCE", job_type="export_user", max_attempts=1, available_at=now)],
            clock=lambda: now,
        )
        stale = await repo.claim("worker", lease_seconds=1, now=now)
        assert stale is not None and stale.attempts == 1

        # Model an export request reopening the terminal row while preserving
        # its attempt counter as a generation fence.
        assert await repo.claim("reaper", now=now + timedelta(seconds=1)) is None
        reopened = repo.jobs[stale.id]
        assert reopened.status == JobStatus.DEAD
        reopened.status = JobStatus.PENDING
        reopened.available_at = now + timedelta(seconds=1)
        reopened.max_attempts = reopened.attempts + 5
        reopened.last_error = None

        current = await repo.claim("worker", lease_seconds=30, now=now + timedelta(seconds=1))
        assert current is not None and current.attempts == 2
        current_expiry = current.lease_expires_at

        assert not await repo.heartbeat(
            current.id,
            "worker",
            attempt=stale.attempts,
            lease_seconds=90,
            now=now + timedelta(seconds=2),
        )
        assert not await repo.complete(current.id, "worker", attempt=stale.attempts)
        assert (
            await repo.fail(
                current.id,
                "worker",
                {"code": "STALE_WORKER"},
                attempt=stale.attempts,
                retryable=False,
            )
            == JobStatus.LEASED
        )
        still_current = await repo.get(current.id)
        assert still_current is not None
        assert still_current.status == JobStatus.LEASED
        assert still_current.lease_expires_at == current_expiry
        assert still_current.last_error is None

        assert await repo.complete(current.id, "worker", attempt=current.attempts)
        assert (await repo.get(current.id)).status == JobStatus.SUCCEEDED

    _run(scenario())


def test_mariadb_lease_transitions_bind_attempt_generation():
    class Result:
        def __init__(self, rows=None, *, rowcount=0):
            self._rows = list(rows or [])
            self.rowcount = rowcount

        def mappings(self):
            return self

        def all(self):
            return list(self._rows)

    class Session:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, params):
            query = str(statement)
            self.calls.append((query, dict(params)))
            if "SELECT status FROM jobs" in query:
                return Result([{"status": "LEASED"}])
            return Result()

        async def close(self):
            return None

    async def scenario():
        session = Session()
        repo = MariaDBQueueRepository(lambda: session, table_name="jobs")

        assert not await repo.heartbeat("01FENCE", "worker", attempt=4)
        assert not await repo.complete("01FENCE", "worker", attempt=4)
        assert (
            await repo.fail(
                "01FENCE",
                "worker",
                {"code": "STALE_WORKER"},
                attempt=4,
                retryable=False,
            )
            == JobStatus.LEASED
        )

        guarded = [
            (query, params)
            for query, params in session.calls
            if "lease_expires_at = :lease_expires_at" in query
            or "SET status = 'SUCCEEDED'" in query
            or "FOR UPDATE" in query
        ]
        assert len(guarded) == 3
        assert all("attempts = :attempt" in query for query, _ in guarded)
        assert all(params["attempt"] == 4 for _, params in guarded)
        assert not any("SET status = :status" in query for query, _ in session.calls)

    _run(scenario())


def test_pending_cancel_is_idempotently_retryable():
    async def scenario():
        repo = MemoryQueueRepository([Job(id="01CANCEL", job_type="noop")])
        assert await repo.cancel("01CANCEL")
        assert not await repo.cancel("01CANCEL")
        assert (await repo.get("01CANCEL")).status == JobStatus.CANCELLED
        assert await repo.retry("01CANCEL")
        assert (await repo.get("01CANCEL")).status == JobStatus.PENDING

    _run(scenario())


def test_backoff_is_bounded_and_increases():
    backoff = ExponentialBackoff(base_seconds=2, max_seconds=10, jitter_ratio=0, random_fn=lambda: 0.5)
    assert [backoff.delay(attempt) for attempt in range(1, 5)] == [2, 4, 8, 10]


def test_heartbeat_failure_cancels_handler_and_requeues_job() -> None:
    async def scenario() -> None:
        class FailingHeartbeatRepository(MemoryQueueRepository):
            async def heartbeat(self, *args, **kwargs):
                raise RuntimeError("database unavailable")

        repository = FailingHeartbeatRepository([Job(id="01HEARTBEAT", job_type="slow")])
        calls: list[str] = []

        async def slow_handler(payload, context):
            calls.append("started")
            await asyncio.sleep(0.05)
            calls.append("finished")
            return {"ok": True}

        from apps.worker.worker.handlers.registry import HandlerRegistry

        runtime = WorkerRuntime(
            repository,
            registry=HandlerRegistry({"slow": slow_handler}),
            config=WorkerConfig(
                worker_id="heartbeat-worker",
                heartbeat_seconds=0.001,
                backoff_base_seconds=0,
                backoff_max_seconds=0,
                backoff_jitter_ratio=0,
            ),
        )
        assert await runtime.process_one()
        stored = await repository.get("01HEARTBEAT")
        assert stored is not None
        assert stored.status == JobStatus.PENDING
        assert stored.last_error is not None
        assert stored.last_error["code"] == "LEASE_HEARTBEAT_FAILED"
        assert calls == ["started"]

    _run(scenario())
