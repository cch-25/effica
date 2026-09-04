"""Async worker runtime and graceful shutdown orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, cast

from .handlers.base import (
    HandlerContext,
    HandlerError,
    invoke_handler,
)
from .handlers.registry import HandlerRegistry, build_default_registry
from .queue import ExponentialBackoff, Job, JobStatus, MariaDBQueueRepository, QueueRepository
from .services import (
    MariaDBCrawlScheduler,
    MariaDBIdempotencyStore,
    MariaDBResultApplier,
    MariaDBWorkerService,
    MemoryResultApplier,
    ResultApplicationError,
    ResultApplier,
)

logger = logging.getLogger(__name__)


def _reasoning_effort_for_attempt(configured: str, attempt: int) -> str:
    if attempt >= 4 and configured in {"xhigh", "max"}:
        return "high"
    return configured


class HeartbeatError(HandlerError):
    """Lease renewal failed while a handler was still executing."""

    retryable = True
    code = "LEASE_HEARTBEAT_FAILED"


@dataclass
class WorkerConfig:
    """Runtime timing and concurrency controls."""

    worker_id: str = field(default_factory=lambda: f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    lease_seconds: float = 60.0
    heartbeat_seconds: float | None = None
    poll_interval_seconds: float = 1.0
    shutdown_grace_seconds: float = 30.0
    max_concurrency: int = 1
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 300.0
    backoff_jitter_ratio: float = 0.2
    queue_error_backoff_base_seconds: float = 1.0
    queue_error_backoff_max_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise ValueError("worker_id must not be empty")
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if self.heartbeat_seconds is not None and self.heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if self.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        if self.shutdown_grace_seconds < 0:
            raise ValueError("shutdown_grace_seconds must be non-negative")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if self.heartbeat_interval >= self.lease_seconds / 2:
            raise ValueError("heartbeat interval must be less than half the lease")
        if self.queue_error_backoff_base_seconds <= 0:
            raise ValueError("queue error backoff base must be positive")
        if self.queue_error_backoff_max_seconds < self.queue_error_backoff_base_seconds:
            raise ValueError("queue error backoff maximum must be at least the base")

    @property
    def heartbeat_interval(self) -> float:
        # Heartbeat comfortably before lease expiry.  A caller may override it
        # for tests or for a deployment with a known DB round-trip latency.
        return self.heartbeat_seconds or max(0.01, self.lease_seconds / 3.0)


class IdempotencyStore(Protocol):
    """Optional guard for side effects that outlive a lease."""

    async def begin(self, key: str) -> tuple[str, Any]:
        """Return ``(owner_token, None)`` or ``(token, cached_result)``."""
        ...

    async def complete(self, key: str, owner_token: str, result: Any) -> None: ...

    async def abandon(self, key: str, owner_token: str) -> None: ...


class CrawlScheduler(Protocol):
    """One bounded, distributed-safe source scheduling tick."""

    interval_seconds: float

    async def tick(self, worker_id: str) -> int: ...


class MemoryIdempotencyStore:
    """Small in-process idempotency store for tests and one-process workers.

    A second execution waits for an in-flight owner and receives the cached
    result.  This closes the lease-expiry race for side effects performed by
    handlers that opt into the store.  Production deployments can provide a
    durable implementation keyed by ``(job_type, dedupe_key)``.
    """

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._condition = asyncio.Condition()

    async def begin(self, key: str) -> tuple[str, Any]:
        token = uuid.uuid4().hex
        async with self._condition:
            while True:
                record = self._records.get(key)
                if record is None:
                    self._records[key] = {"state": "RUNNING", "owner": token, "result": None}
                    return token, None
                if record["state"] == "SUCCEEDED":
                    return "cached", record["result"]
                await self._condition.wait()

    async def complete(self, key: str, owner_token: str, result: Any) -> None:
        async with self._condition:
            record = self._records.get(key)
            if record is None or record.get("owner") != owner_token:
                return
            record["state"] = "SUCCEEDED"
            record["result"] = result
            self._condition.notify_all()

    async def abandon(self, key: str, owner_token: str) -> None:
        async with self._condition:
            record = self._records.get(key)
            if record is not None and record.get("owner") == owner_token:
                self._records.pop(key, None)
                self._condition.notify_all()

    async def get(self, key: str) -> Any:
        async with self._condition:
            record = self._records.get(key)
            return None if record is None else record.get("result")


class WorkerRuntime:
    """Claim, execute, and transition jobs until shutdown is requested."""

    def __init__(
        self,
        repository: QueueRepository,
        *,
        registry: HandlerRegistry | None = None,
        config: WorkerConfig | None = None,
        idempotency_store: IdempotencyStore | None = None,
        result_applier: ResultApplier | None = None,
        crawl_scheduler: CrawlScheduler | None = None,
        services: Mapping[str, Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry or build_default_registry()
        self.config = config or WorkerConfig()
        self.idempotency_store = idempotency_store
        # A result sink is always present.  In-memory workers get a
        # deterministic test sink; production construction below injects the
        # MariaDB implementation.  This prevents a handler's value from ever
        # being silently discarded before SUCCEEDED.
        self.result_applier = result_applier or MemoryResultApplier()
        self.crawl_scheduler = crawl_scheduler
        self.services = dict(services or {})
        self.clock = clock
        self.stop_event = asyncio.Event()
        self._active: set[asyncio.Task[Any]] = set()
        self._shutdown_started = False
        self._signals_installed = False
        self._scheduler_task: asyncio.Task[Any] | None = None
        self._claimed_count = 0
        self._succeeded_count = 0
        self._failed_count = 0
        self._queue_error_count = 0
        self._last_job_id: str | None = None
        self._last_queue_error: str | None = None
        self.backoff = ExponentialBackoff(
            base_seconds=self.config.backoff_base_seconds,
            max_seconds=self.config.backoff_max_seconds,
            jitter_ratio=self.config.backoff_jitter_ratio,
        )
        self.queue_error_backoff = ExponentialBackoff(
            base_seconds=self.config.queue_error_backoff_base_seconds,
            max_seconds=self.config.queue_error_backoff_max_seconds,
            jitter_ratio=self.config.backoff_jitter_ratio,
        )

    @property
    def worker_id(self) -> str:
        return self.config.worker_id

    def health_snapshot(self) -> dict[str, Any]:
        """Return a secret-free runtime snapshot for logs and supervisors."""

        return {
            "worker_id": self.worker_id,
            "stopping": self.stop_event.is_set(),
            "active_jobs": len(self._active),
            "claimed": self._claimed_count,
            "succeeded": self._succeeded_count,
            "failed": self._failed_count,
            "queue_errors": self._queue_error_count,
            "last_job_id": self._last_job_id,
            "last_queue_error": self._last_queue_error,
            "scheduler_enabled": self.crawl_scheduler is not None,
        }

    def request_stop(self, *_signals: Any) -> None:
        """Signal-safe stop request; active handlers finish within grace."""

        self.stop_event.set()

    async def stop(self) -> int:
        """Release this worker's leases and prevent new claims."""

        self.request_stop()
        if self._shutdown_started:
            return 0
        return await self._graceful_shutdown()

    shutdown = stop

    def install_signal_handlers(self) -> None:
        if self._signals_installed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for signum in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError, RuntimeError, ValueError):
                loop.add_signal_handler(signum, self.request_stop, signum)
        self._signals_installed = True

    async def process_one(self) -> bool:
        """Claim and process at most one available job."""

        if self.stop_event.is_set():
            return False
        job = await self.repository.claim(
            self.worker_id,
            lease_seconds=self.config.lease_seconds,
        )
        if job is None:
            return False
        self._record_claim(job)
        await self._process_claimed(job)
        return True

    async def _process_claimed(self, job: Job) -> None:
        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._heartbeat(job, heartbeat_stop))
        idempotency_key = self._idempotency_key(job)
        owner_token: str | None = None
        idempotency_completed = False
        context = HandlerContext(
            job_id=job.id,
            job_type=job.job_type,
            worker_id=self.worker_id,
            idempotency_key=idempotency_key,
            attempt=job.attempts,
            now=self.clock() if self.clock else None,
            services=self.services,
        )
        try:
            async def operation() -> None:
                nonlocal owner_token, idempotency_completed
                if self.idempotency_store is not None:
                    owner_token, cached = await self.idempotency_store.begin(idempotency_key)
                    if owner_token == "cached":
                        applied = await self._apply_result(job, cached, context)
                        completed = await self.repository.complete(
                            job.id, self.worker_id, result=applied
                        )
                        if not completed:
                            logger.warning("job lease lost before cached completion: %s", job.id)
                        else:
                            self._record_success(job, cached=True)
                        return
                handler = self.registry.get(job.job_type)
                if handler is None:
                    raise HandlerError(
                        f"no handler registered for {job.job_type}",
                        code="UNKNOWN_JOB_TYPE",
                        details={"job_type": job.job_type},
                        retryable=False,
                    )
                result = await invoke_handler(handler, job.payload, context)
                # The durable side effect must commit before the queue
                # transition; a lost lease can then safely replay an
                # idempotent application.
                applied = await self._apply_result(job, result, context)
                if self.idempotency_store is not None and owner_token is not None:
                    await self.idempotency_store.complete(idempotency_key, owner_token, applied)
                    idempotency_completed = True
                completed = await self.repository.complete(job.id, self.worker_id, result=applied)
                if not completed:
                    # The lease may have expired between handler completion and
                    # the update.  Durable idempotency still prevents a
                    # second side effect; leave the row for reconciliation.
                    logger.warning("job lease lost before completion: %s", job.id)
                else:
                    self._record_success(job)

            await self._run_with_heartbeat(operation(), heartbeat_task)
        except asyncio.CancelledError:
            if (
                self.idempotency_store is not None
                and owner_token not in (None, "cached")
                and not idempotency_completed
            ):
                await self.idempotency_store.abandon(idempotency_key, owner_token)
            raise
        except HandlerError as exc:
            if (
                self.idempotency_store is not None
                and owner_token not in (None, "cached")
                and not idempotency_completed
            ):
                await self.idempotency_store.abandon(idempotency_key, owner_token)
            await self._fail(job, exc.as_error(), retryable=bool(exc.retryable))
        except ResultApplicationError as exc:
            if (
                self.idempotency_store is not None
                and owner_token not in (None, "cached")
                and not idempotency_completed
            ):
                await self.idempotency_store.abandon(idempotency_key, owner_token)
            await self._fail(
                job,
                {
                    "code": "RESULT_APPLICATION_FAILED",
                    "message": str(exc) or exc.__class__.__name__,
                    "retryable": bool(exc.retryable),
                    "details": {"exception": exc.__class__.__name__},
                },
                retryable=bool(exc.retryable),
            )
        except Exception as exc:  # pragma: no cover - defensive final boundary
            if (
                self.idempotency_store is not None
                and owner_token not in (None, "cached")
                and not idempotency_completed
            ):
                await self.idempotency_store.abandon(idempotency_key, owner_token)
            await self._fail(
                job,
                {
                    "code": "WORKER_EXCEPTION",
                    "message": str(exc) or exc.__class__.__name__,
                    "retryable": True,
                    "details": {"exception": exc.__class__.__name__},
                },
                retryable=True,
            )
        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError, HandlerError):
                await heartbeat_task

    async def _run_with_heartbeat(
        self,
        operation: Any,
        heartbeat_task: asyncio.Task[Any],
    ) -> Any:
        """Run an operation while observing lease renewal failures.

        A background task's exception is otherwise only logged by asyncio and
        the handler can continue after losing its lease.  Make the heartbeat
        a first-class completion boundary and cancel the operation as soon as
        ownership cannot be established.
        """

        operation_task = asyncio.create_task(operation)
        done, _ = await asyncio.wait(
            {operation_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat_task in done:
            heartbeat_error = heartbeat_task.exception()
            if heartbeat_error is not None:
                operation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await operation_task
                raise heartbeat_error
        result = await operation_task
        # A heartbeat can fail in the same event-loop turn that the operation
        # finishes.  Prefer the lease error so the result is not acknowledged
        # as a successful execution without ownership.
        if heartbeat_task.done():
            heartbeat_error = heartbeat_task.exception()
            if heartbeat_error is not None:
                raise heartbeat_error
        return result

    async def _apply_result(
        self,
        job: Job,
        result: Any,
        context: HandlerContext,
    ) -> Any:
        try:
            applier = cast(
                Callable[..., Any],
                getattr(self.result_applier, "apply", self.result_applier),
            )
            try:
                applied = applier(job, result, context=context)
            except TypeError:
                applied = applier(job, result)
            if asyncio.iscoroutine(applied) or hasattr(applied, "__await__"):
                applied = await applied
            return applied
        except ResultApplicationError:
            raise
        except Exception as exc:
            raise ResultApplicationError(
                str(exc) or exc.__class__.__name__, retryable=True
            ) from exc

    async def _heartbeat(self, job: Job, stop_event: asyncio.Event) -> None:
        interval = self.config.heartbeat_interval
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                try:
                    renewed = await self.repository.heartbeat(
                        job.id,
                        self.worker_id,
                        lease_seconds=self.config.lease_seconds,
                    )
                except Exception as exc:
                    raise HeartbeatError(
                        "job lease heartbeat failed",
                        details={"exception": exc.__class__.__name__},
                    ) from exc
                if not renewed:
                    raise HeartbeatError("job lease is no longer owned") from None

    def _idempotency_key(self, job: Job) -> str:
        return f"{job.job_type}:{job.dedupe_key or job.id}"

    async def _fail(self, job: Job, error: Mapping[str, Any], *, retryable: bool) -> JobStatus:
        # ResultApplicationError defaults to retryable=False so apply conflicts
        # (0 share rows, stale aggregates) become FAILED instead of PENDING.
        delay = self.backoff.delay(job.attempts) if retryable else 0.0
        status = await self.repository.fail(
            job.id,
            self.worker_id,
            error,
            retryable=retryable,
            backoff_seconds=delay,
        )
        self._failed_count += 1
        self._last_job_id = job.id
        logger.warning(
            "job_failed",
            extra={
                "event": "job_failed",
                "worker_id": self.worker_id,
                "job_id": job.id,
                "job_type": job.job_type,
                "attempt": job.attempts,
                "max_attempts": job.max_attempts,
                "status": status.value,
                "retryable": retryable,
                "retry_delay_seconds": round(delay, 3),
                "error_code": str(error.get("code") or "UNKNOWN"),
            },
        )
        return status

    def _record_claim(self, job: Job) -> None:
        self._claimed_count += 1
        self._last_job_id = job.id
        logger.info(
            "job_claimed",
            extra={
                "event": "job_claimed",
                "worker_id": self.worker_id,
                "job_id": job.id,
                "job_type": job.job_type,
                "attempt": job.attempts,
                "max_attempts": job.max_attempts,
            },
        )

    def _record_success(self, job: Job, *, cached: bool = False) -> None:
        self._succeeded_count += 1
        self._last_job_id = job.id
        logger.info(
            "job_succeeded",
            extra={
                "event": "job_succeeded",
                "worker_id": self.worker_id,
                "job_id": job.id,
                "job_type": job.job_type,
                "attempt": job.attempts,
                "idempotent_replay": cached,
            },
        )

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._active.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "job_task_crashed",
                exc_info=(type(error), error, error.__traceback__),
                extra={
                    "event": "job_task_crashed",
                    "worker_id": self.worker_id,
                    **self.health_snapshot(),
                },
            )

    async def _crawl_scheduler_loop(self) -> None:
        assert self.crawl_scheduler is not None
        interval = float(self.crawl_scheduler.interval_seconds)
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                created = await self.crawl_scheduler.tick(self.worker_id)
                logger.info(
                    "crawl_schedule_tick",
                    extra={
                        "event": "crawl_schedule_tick",
                        "worker_id": self.worker_id,
                        "jobs_created": created,
                        "interval_seconds": interval,
                    },
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "crawl_schedule_failed",
                    exc_info=True,
                    extra={
                        "event": "crawl_schedule_failed",
                        "worker_id": self.worker_id,
                        "exception_type": exc.__class__.__name__,
                    },
                )
            remaining = max(0.0, interval - (time.monotonic() - started))
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=remaining)
            except TimeoutError:
                pass

    async def retry_job(self, job_id: str) -> bool:
        return await self.repository.retry(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        return await self.repository.cancel(job_id)

    async def run_forever(self) -> None:
        """Run until SIGTERM/Ctrl-C or :meth:`request_stop`."""

        self.install_signal_handlers()
        self._shutdown_started = False
        queue_error_attempt = 0
        if self.crawl_scheduler is not None:
            # Tick immediately at process startup; the scheduler's advisory
            # lock and interval-bucket dedupe make this fleet-safe.
            self._scheduler_task = asyncio.create_task(self._crawl_scheduler_loop())
        logger.info(
            "worker_started",
            extra={
                "event": "worker_started",
                "worker_id": self.worker_id,
                "max_concurrency": self.config.max_concurrency,
                "lease_seconds": self.config.lease_seconds,
                "scheduler_enabled": self.crawl_scheduler is not None,
            },
        )
        try:
            while not self.stop_event.is_set():
                # Fill the bounded worker pool.  Claims are short DB
                # transactions; handlers run concurrently outside them.
                claim_error = False
                while (
                    len(self._active) < self.config.max_concurrency and not self.stop_event.is_set()
                ):
                    try:
                        job = await self.repository.claim(
                            self.worker_id,
                            lease_seconds=self.config.lease_seconds,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        queue_error_attempt += 1
                        self._queue_error_count += 1
                        self._last_queue_error = exc.__class__.__name__
                        delay = self.queue_error_backoff.delay(queue_error_attempt)
                        logger.error(
                            "queue_claim_failed",
                            exc_info=True,
                            extra={
                                "event": "queue_claim_failed",
                                "worker_id": self.worker_id,
                                "consecutive_errors": queue_error_attempt,
                                "retry_delay_seconds": round(delay, 3),
                                "active_jobs": len(self._active),
                            },
                        )
                        claim_error = True
                        if self._active:
                            await asyncio.wait(
                                tuple(self._active),
                                timeout=delay,
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                        else:
                            try:
                                await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
                            except TimeoutError:
                                pass
                        break
                    queue_error_attempt = 0
                    self._last_queue_error = None
                    if job is None:
                        break
                    self._record_claim(job)
                    task = asyncio.create_task(self._process_claimed(job))
                    self._active.add(task)
                    task.add_done_callback(self._task_done)

                if claim_error:
                    continue
                if self._active:
                    # Waiting on a snapshot avoids mutating the set while
                    # callbacks discard completed tasks.
                    await asyncio.wait(
                        tuple(self._active),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                elif not self.stop_event.is_set():
                    if self.config.poll_interval_seconds:
                        try:
                            await asyncio.wait_for(
                                self.stop_event.wait(),
                                timeout=self.config.poll_interval_seconds,
                            )
                        except TimeoutError:
                            pass
                    else:
                        await asyncio.sleep(0)
        finally:
            await self._graceful_shutdown()

    async def run(self) -> None:
        await self.run_forever()

    async def _graceful_shutdown(self) -> int:
        self.request_stop()
        if self._shutdown_started:
            return 0
        self._shutdown_started = True
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None
        if self._active:
            _, pending = await asyncio.wait(
                self._active,
                timeout=self.config.shutdown_grace_seconds,
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
        released = await self.repository.release_leases(self.worker_id)
        logger.info(
            "worker_stopped",
            extra={
                "event": "worker_stopped",
                "worker_id": self.worker_id,
                "released_leases": released,
                **self.health_snapshot(),
            },
        )
        return released


async def run_worker(
    repository: QueueRepository,
    *,
    registry: HandlerRegistry | None = None,
    config: WorkerConfig | None = None,
    idempotency_store: IdempotencyStore | None = None,
    result_applier: ResultApplier | None = None,
    crawl_scheduler: CrawlScheduler | None = None,
    services: Mapping[str, Any] | None = None,
) -> None:
    """Convenience entry point for process supervisors."""

    runtime = WorkerRuntime(
        repository,
        registry=registry,
        config=config,
        idempotency_store=idempotency_store,
        result_applier=result_applier,
        crawl_scheduler=crawl_scheduler,
        services=services,
    )
    await runtime.run_forever()


def build_mariadb_runtime(
    session_factory: Callable[[], Any] | None = None,
    *,
    config: WorkerConfig | None = None,
    registry: HandlerRegistry | None = None,
    idempotency_store: IdempotencyStore | None = None,
    result_applier: ResultApplier | None = None,
    crawl_scheduler: CrawlScheduler | None = None,
    services: Mapping[str, Any] | None = None,
) -> WorkerRuntime:
    """Build the executable runtime using the API's shared session factory."""

    from apps.api.app.core.config import get_settings

    settings = get_settings()
    settings.assert_safe_runtime()
    if config is None:
        config = WorkerConfig(
            lease_seconds=settings.worker_lease_seconds,
            heartbeat_seconds=settings.worker_heartbeat_seconds,
            poll_interval_seconds=settings.worker_poll_interval_seconds,
            shutdown_grace_seconds=settings.worker_shutdown_grace_seconds,
            max_concurrency=settings.worker_max_concurrency,
            queue_error_backoff_base_seconds=(
                settings.worker_queue_error_backoff_base_seconds
            ),
            queue_error_backoff_max_seconds=(
                settings.worker_queue_error_backoff_max_seconds
            ),
        )
    if session_factory is None:
        from apps.api.app.db.session import session_factory as api_session_factory

        session_factory = api_session_factory()
    repository = MariaDBQueueRepository(session_factory)
    if idempotency_store is None:
        idempotency_store = MariaDBIdempotencyStore(session_factory)
    if result_applier is None:
        result_applier = MariaDBResultApplier(session_factory)
    if crawl_scheduler is None and settings.worker_crawl_scheduler_enabled:
        crawl_scheduler = MariaDBCrawlScheduler(
            session_factory,
            interval_seconds=settings.worker_crawl_interval_seconds,
            batch_size=settings.worker_crawl_batch_size,
            max_attempts=settings.worker_crawl_max_attempts,
        )
    if services is None:
        services = _default_services(session_factory)
    return WorkerRuntime(
        repository,
        registry=registry,
        config=config,
        idempotency_store=idempotency_store,
        result_applier=result_applier,
        crawl_scheduler=crawl_scheduler,
        services=services,
    )


def _default_services(session_factory: Callable[[], Any]) -> dict[str, Any]:
    from apps.api.app.core.config import get_settings
    from apps.worker.worker.lookups import MariaDBWorkerLookups
    from apps.worker.worker.source_fetcher import SourceFetchService

    settings = get_settings()
    settings.assert_safe_runtime()
    lookups = MariaDBWorkerLookups(session_factory, encryption_secret=settings.session_secret)
    services = lookups.as_services()
    services["source_fetcher"] = SourceFetchService()
    if not settings.live_llm_enabled:
        return services
    from apps.api.app.domains.analysis import (
        HttpLLMProvider,
        ProviderConfig,
        ProviderError,
    )

    async def analysis_provider_factory(*, attempt: int = 1) -> HttpLLMProvider:
        configured = await lookups.analysis_model_lookup()
        reasoning_effort = str(
            (configured or {}).get("reasoning_effort")
            or settings.llm_reasoning_effort
        )
        # Preserve the highest configured quality for normal requests. After
        # three durable attempts, trade only the excess reasoning budget for
        # completion so one pathological article cannot remain permanently
        # unassessed after repeatedly reaching the request timeout.
        reasoning_effort = _reasoning_effort_for_attempt(reasoning_effort, attempt)
        return HttpLLMProvider(
            ProviderConfig(
                alias=str((configured or {}).get("alias") or settings.llm_model_alias),
                actual_model_id=str(
                    (configured or {}).get("actual_model_id") or settings.llm_model
                ),
                reasoning_effort=reasoning_effort,
                timeout_seconds=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
                model_alias_id=(configured or {}).get("model_alias_id"),
                endpoint=settings.openai_endpoint,
                api_key=settings.openai_api_key,
            )
        )

    services["analysis_provider_factory"] = analysis_provider_factory

    async def issue_comparison_analysis(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        version_ids = value.get("article_version_ids")
        if not isinstance(version_ids, (list, tuple)):
            return None
        articles = await lookups.issue_comparison_inputs(version_ids)
        if len(articles) != len(version_ids):
            # Comparison work carries immutable article-version identities.
            # A later crawl may make one of those versions non-current before
            # the job is leased.  That is expected queue staleness, not an AI
            # or data-quality failure, and must not consume terminal retries.
            return {
                "status": "SKIPPED",
                "skip_reason": "STALE_ARTICLE_VERSIONS",
                "expected_article_versions": len(version_ids),
                "current_article_versions": len(articles),
            }
        provider = await analysis_provider_factory()
        try:
            try:
                result = await asyncio.to_thread(
                    provider.analyze_issue_comparison,
                    articles,
                    str(value.get("prompt_version") or "issue-comparison-v1"),
                )
            except ProviderError as exc:
                raise HandlerError(
                    "issue comparison provider request failed",
                    code=exc.code,
                    details={
                        "model_alias": provider.config.alias,
                        "provider_message": str(exc)[:240],
                    },
                    # Strict structured output still needs domain checks for
                    # cross-article identities and evidence support. A model
                    # can miss one of those constraints transiently, so let
                    # the durable queue retry instead of terminally stranding
                    # an otherwise current comparison.
                    retryable=True,
                ) from exc
            result["model_alias_id"] = provider.config.model_alias_id
            result["article_version_ids"] = {
                str(article["article_id"]): str(article["article_version_id"])
                for article in articles
            }
            return result
        finally:
            provider.close()

    services["issue_comparison_analysis"] = issue_comparison_analysis
    return services


async def main() -> None:
    """Run the MariaDB worker when invoked by ``run.sh worker`` or systemd."""

    from apps.api.app.core.config import get_settings
    from apps.api.app.core.logging import configure_logging

    settings = get_settings()
    configure_logging(level=settings.log_level, logger_name=__name__)
    runtime = build_mariadb_runtime()
    await runtime.run_forever()


__all__ = [
    "HandlerRegistry",
    "CrawlScheduler",
    "IdempotencyStore",
    "MariaDBIdempotencyStore",
    "MariaDBResultApplier",
    "MemoryIdempotencyStore",
    "MemoryResultApplier",
    "ResultApplier",
    "ResultApplicationError",
    "WorkerConfig",
    "WorkerRuntime",
    "build_default_registry",
    "build_mariadb_runtime",
    "main",
    "run_worker",
]


if __name__ == "__main__":  # pragma: no cover - exercised by process supervisors.
    asyncio.run(main())
