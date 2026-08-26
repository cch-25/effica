"""Async worker runtime and graceful shutdown orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
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
    DurableResultApplier,
    MariaDBIdempotencyStore,
    MariaDBResultApplier,
    MariaDBWorkerService,
    MemoryResultApplier,
    MemoryWorkerService,
    ResultApplicationError,
    ResultApplier,
)

logger = logging.getLogger(__name__)


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
        self.services = dict(services or {})
        self.clock = clock
        self.stop_event = asyncio.Event()
        self._active: set[asyncio.Task[Any]] = set()
        self._shutdown_started = False
        self._signals_installed = False
        self.backoff = ExponentialBackoff(
            base_seconds=self.config.backoff_base_seconds,
            max_seconds=self.config.backoff_max_seconds,
            jitter_ratio=self.config.backoff_jitter_ratio,
        )

    @property
    def worker_id(self) -> str:
        return self.config.worker_id

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
        return await self.repository.fail(
            job.id,
            self.worker_id,
            error,
            retryable=retryable,
            backoff_seconds=delay,
        )

    async def retry_job(self, job_id: str) -> bool:
        return await self.repository.retry(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        return await self.repository.cancel(job_id)

    async def run_once(self) -> bool:
        """Alias useful to supervisor loops and tests."""

        return await self.process_one()

    async def process_job(self, job: Job) -> None:
        """Process a record that the caller already claimed."""

        await self._process_claimed(job)

    async def run_forever(self) -> None:
        """Run until SIGTERM/Ctrl-C or :meth:`request_stop`."""

        self.install_signal_handlers()
        self._shutdown_started = False
        try:
            while not self.stop_event.is_set():
                # Fill the bounded worker pool.  Claims are short DB
                # transactions; handlers run concurrently outside them.
                while (
                    len(self._active) < self.config.max_concurrency and not self.stop_event.is_set()
                ):
                    job = await self.repository.claim(
                        self.worker_id,
                        lease_seconds=self.config.lease_seconds,
                    )
                    if job is None:
                        break
                    task = asyncio.create_task(self._process_claimed(job))
                    self._active.add(task)
                    task.add_done_callback(self._active.discard)

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
        return await self.repository.release_leases(self.worker_id)


async def run_worker(
    repository: QueueRepository,
    *,
    registry: HandlerRegistry | None = None,
    config: WorkerConfig | None = None,
    idempotency_store: IdempotencyStore | None = None,
    result_applier: ResultApplier | None = None,
    services: Mapping[str, Any] | None = None,
) -> None:
    """Convenience entry point for process supervisors."""

    runtime = WorkerRuntime(
        repository,
        registry=registry,
        config=config,
        idempotency_store=idempotency_store,
        result_applier=result_applier,
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
    services: Mapping[str, Any] | None = None,
) -> WorkerRuntime:
    """Build the executable runtime using the API's shared session factory."""

    if session_factory is None:
        from apps.api.app.db.session import session_factory as api_session_factory

        session_factory = api_session_factory()
    repository = MariaDBQueueRepository(session_factory)
    if idempotency_store is None:
        idempotency_store = MariaDBIdempotencyStore(session_factory)
    if result_applier is None:
        result_applier = MariaDBResultApplier(session_factory)
    if services is None:
        services = _default_services(session_factory)
    return WorkerRuntime(
        repository,
        registry=registry,
        config=config,
        idempotency_store=idempotency_store,
        result_applier=result_applier,
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
        ProviderSchemaError,
    )

    async def analysis_provider_factory() -> HttpLLMProvider:
        configured = await lookups.analysis_model_lookup()
        return HttpLLMProvider(
            ProviderConfig(
                alias=str((configured or {}).get("alias") or settings.llm_model_alias),
                actual_model_id=str(
                    (configured or {}).get("actual_model_id") or settings.llm_model
                ),
                reasoning_effort=str(
                    (configured or {}).get("reasoning_effort")
                    or settings.llm_reasoning_effort
                ),
                timeout_seconds=settings.llm_timeout_seconds,
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
            return None
        provider = await analysis_provider_factory()
        try:
            try:
                result = provider.analyze_issue_comparison(
                    articles,
                    str(value.get("prompt_version") or "issue-comparison-v1"),
                )
            except ProviderError as exc:
                raise HandlerError(
                    "issue comparison provider request failed",
                    code=exc.code,
                    details={"model_alias": provider.config.alias},
                    retryable=not isinstance(exc, ProviderSchemaError),
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

    runtime = build_mariadb_runtime()
    await runtime.run_forever()


__all__ = [
    "HandlerRegistry",
    "DurableResultApplier",
    "IdempotencyStore",
    "MariaDBIdempotencyStore",
    "MariaDBResultApplier",
    "MariaDBWorkerService",
    "MemoryIdempotencyStore",
    "MemoryResultApplier",
    "MemoryWorkerService",
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
