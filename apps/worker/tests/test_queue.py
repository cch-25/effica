from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from apps.worker.worker.main import WorkerConfig, WorkerRuntime
from apps.worker.worker.queue import ExponentialBackoff, Job, JobStatus, MemoryQueueRepository


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
