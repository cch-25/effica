"""Queue records and MariaDB/memory repository implementations.

The queue is deliberately a small repository boundary.  API code may enqueue
through ``apps.api.app.jobs.producer`` while the worker owns claiming and
lease transitions here.  No SQLAlchemy model is imported; the SQL refers only
to the documented ``jobs`` table columns.

Claim semantics:

* On MariaDB versions with ``SKIP LOCKED`` support, a row is selected with a
  row lock and transitioned to ``LEASED`` in the same transaction.
* On older versions, a candidate is read without a lock and won with a
  conditional ``UPDATE ... WHERE``.  Only the transaction whose update affects
  one row may execute the handler.  A race therefore sacrifices throughput,
  never safety.
* Leases expire back into the claimable set.  Attempts increment exactly when
  a worker wins a claim, so a crashed worker cannot reset the retry budget.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import random
import re
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import (
    Any,
    Protocol,
)

try:
    from apps.api.app.jobs.types import JobStatus, utc_now
except ImportError:  # pragma: no cover - supports ``PYTHONPATH=apps/worker``.
    from api.app.jobs.types import JobStatus, utc_now  # type: ignore


class JobQueueError(RuntimeError):
    """Base class for queue/repository failures."""


class JobNotFound(JobQueueError):
    """Raised when a requested transition references an unknown job."""


@dataclass
class Job:
    """Worker-facing persisted job record."""

    id: str
    job_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    dedupe_key: str | None = None
    priority: int = 0
    available_at: datetime = field(default_factory=utc_now)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 3
    last_error: dict[str, Any] | None = None
    # Memory/test projection of the durable result-applier output.  The
    # MariaDB queue keeps the canonical result in the applier's audit/result
    # service because the immutable 0001 jobs table has no result column.
    result: Any = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.status = _as_status(self.status)
        self.payload = dict(self.payload or {})
        self.available_at = _aware_utc(self.available_at)
        self.created_at = _aware_utc(self.created_at)
        self.updated_at = _aware_utc(self.updated_at)
        if self.lease_expires_at is not None:
            self.lease_expires_at = _aware_utc(self.lease_expires_at)
        if self.attempts < 0:
            raise ValueError("attempts must be non-negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


JobRecord = Job


def _aware_utc(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_status(value: JobStatus | str) -> JobStatus:
    if isinstance(value, JobStatus):
        return value
    try:
        return JobStatus(str(value))
    except ValueError:
        # Some early local migrations used lowercase enum values while the
        # public contract is upper-case.  Reading either representation keeps
        # workers safe during a rolling migration; writes remain canonical.
        return JobStatus(str(value).upper())


def _json_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {"message": value}
        return dict(parsed) if isinstance(parsed, Mapping) else {"value": parsed}
    return {"value": value}


def _json_payload(value: Any) -> dict[str, Any]:
    result = _json_object(value)
    return {} if result is None else result


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


def _job_from_row(row: Any) -> Job:
    now = utc_now()
    return Job(
        id=str(_row_value(row, "id")),
        job_type=str(_row_value(row, "job_type")),
        payload=_json_payload(_row_value(row, "payload_json", {})),
        status=_as_status(_row_value(row, "status", JobStatus.PENDING.value)),
        dedupe_key=_row_value(row, "dedupe_key"),
        priority=int(_row_value(row, "priority", 0) or 0),
        available_at=_row_value(row, "available_at", now) or now,
        lease_owner=_row_value(row, "lease_owner"),
        lease_expires_at=_row_value(row, "lease_expires_at"),
        attempts=int(_row_value(row, "attempts", 0) or 0),
        max_attempts=int(_row_value(row, "max_attempts", 3) or 3),
        last_error=_json_object(_row_value(row, "last_error_json")),
        created_at=_row_value(row, "created_at", now) or now,
        updated_at=_row_value(row, "updated_at", now) or now,
    )


def _sql(statement: str) -> Any:
    try:
        from sqlalchemy import text

        return text(statement)
    except ImportError:
        return statement


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@asynccontextmanager
async def _session_scope(factory: Callable[[], Any]) -> AsyncIterator[Any]:
    session = await _maybe_await(factory())
    if hasattr(session, "__aenter__"):
        async with session as entered:
            yield entered
        return
    try:
        yield session
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            await _maybe_await(close())


@asynccontextmanager
async def _transaction(session: Any) -> AsyncIterator[Any]:
    begin = getattr(session, "begin", None)
    if begin is None:
        yield session
        return
    # SQLAlchemy's AsyncSessionTransaction is both awaitable and an async
    # context manager.  Awaiting it and then entering it starts the same
    # transaction twice ("A transaction is already begun").  Prefer the
    # context-manager protocol before awaiting custom/fake begin methods.
    context = begin()
    if not hasattr(context, "__aenter__"):
        context = await _maybe_await(context)
    if hasattr(context, "__aenter__"):
        async with context:
            yield session
    else:
        try:
            yield session
        except BaseException:
            rollback = getattr(session, "rollback", None)
            if rollback is not None:
                await _maybe_await(rollback())
            raise
        else:
            commit = getattr(session, "commit", None)
            if commit is not None:
                await _maybe_await(commit())


def _result_rows(result: Any) -> list[Any]:
    mappings = getattr(result, "mappings", None)
    if mappings is not None:
        mapped = mappings()
        all_rows = getattr(mapped, "all", None)
        if all_rows is not None:
            return list(all_rows())
        first = getattr(mapped, "first", None)
        if first is not None:
            value = first()
            return [] if value is None else [value]
    all_rows = getattr(result, "all", None)
    if all_rows is not None:
        return list(all_rows())
    first = getattr(result, "first", None)
    if first is not None:
        value = first()
        return [] if value is None else [value]
    if isinstance(result, (list, tuple)):
        return list(result)
    return []


def _rowcount(result: Any) -> int:
    value = getattr(result, "rowcount", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class QueueRepository(Protocol):
    """Repository operations required by :class:`WorkerRuntime`."""

    async def enqueue(self, job: Job) -> Job: ...

    async def claim(
        self, worker_id: str, *, lease_seconds: float = 60.0, now: datetime | None = None
    ) -> Job | None: ...

    async def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        lease_seconds: float = 60.0,
        now: datetime | None = None,
    ) -> bool: ...

    async def complete(
        self, job_id: str, worker_id: str, *, result: Any = None, now: datetime | None = None
    ) -> bool: ...

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        error: Mapping[str, Any],
        *,
        retryable: bool = True,
        now: datetime | None = None,
        backoff_seconds: float = 0.0,
    ) -> JobStatus: ...

    async def retry(self, job_id: str, *, now: datetime | None = None) -> bool: ...

    async def cancel(self, job_id: str, *, now: datetime | None = None) -> bool: ...

    async def release_leases(self, worker_id: str, *, now: datetime | None = None) -> int: ...


class ExponentialBackoff:
    """Exponential delay with injectable jitter for deterministic tests."""

    def __init__(
        self,
        *,
        base_seconds: float = 1.0,
        max_seconds: float = 300.0,
        jitter_ratio: float = 0.2,
        random_fn: Callable[[], float] | None = None,
    ) -> None:
        if base_seconds < 0 or max_seconds < 0:
            raise ValueError("backoff bounds must be non-negative")
        if max_seconds < base_seconds:
            raise ValueError("max_seconds must be >= base_seconds")
        if jitter_ratio < 0 or jitter_ratio > 1:
            raise ValueError("jitter_ratio must be between 0 and 1")
        self.base_seconds = float(base_seconds)
        self.max_seconds = float(max_seconds)
        self.jitter_ratio = float(jitter_ratio)
        self.random_fn = random_fn or random.random

    def delay(self, attempt: int) -> float:
        """Return delay after a failed attempt (attempts are one-based)."""

        exponent = max(0, int(attempt) - 1)
        nominal = min(self.max_seconds, self.base_seconds * (2**exponent))
        if nominal == 0 or self.jitter_ratio == 0:
            return nominal
        # Symmetric jitter avoids systematic delay inflation while retaining a
        # non-zero randomized spread for concurrent workers.
        spread = nominal * self.jitter_ratio
        jitter = (float(self.random_fn()) * 2.0) - 1.0
        return max(0.0, min(self.max_seconds, nominal + (spread * jitter)))

    __call__ = delay


def calculate_backoff(
    attempt: int,
    *,
    base_seconds: float = 1.0,
    max_seconds: float = 300.0,
    jitter_ratio: float = 0.2,
    random_fn: Callable[[], float] | None = None,
) -> float:
    return ExponentialBackoff(
        base_seconds=base_seconds,
        max_seconds=max_seconds,
        jitter_ratio=jitter_ratio,
        random_fn=random_fn,
    ).delay(attempt)


class MemoryQueueRepository:
    """Concurrency-safe repository test double.

    It models the same state transitions as MariaDB and is intentionally
    useful to local worker tests and deterministic development runs.  The
    lock represents a database transaction; handlers execute outside it.
    """

    def __init__(
        self, jobs: Iterable[Job] | None = None, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self.clock = clock
        self.claim_history: list[tuple[str, str]] = []
        self.transition_history: list[tuple[str, JobStatus]] = []
        self.side_effect_keys: set[str] = set()
        for job in jobs or ():
            self._jobs[job.id] = replace(job)

    @property
    def jobs(self) -> dict[str, Job]:
        return self._jobs

    async def enqueue(
        self,
        job: Job | str,
        payload: Mapping[str, Any] | None = None,
        *,
        job_id: str | None = None,
        dedupe_key: str | None = None,
        priority: int = 0,
        available_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> Job:
        if not isinstance(job, Job):
            job = Job(
                id=job_id or uuid.uuid4().hex,
                job_type=str(job),
                payload=dict(payload or {}),
                dedupe_key=dedupe_key,
                priority=priority,
                available_at=available_at or self.clock(),
                max_attempts=max_attempts,
            )
        async with self._lock:
            for existing in self._jobs.values():
                if (
                    job.dedupe_key is not None
                    and existing.job_type == job.job_type
                    and existing.dedupe_key == job.dedupe_key
                ):
                    return replace(existing)
            if job.id in self._jobs:
                return replace(self._jobs[job.id])
            self._jobs[job.id] = replace(job)
            return replace(job)

    async def add(self, job: Job) -> Job:
        return await self.enqueue(job)

    put = enqueue

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else replace(job)

    async def list_jobs(self) -> list[Job]:
        async with self._lock:
            return [replace(job) for job in self._jobs.values()]

    async def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 60.0,
        now: datetime | None = None,
    ) -> Job | None:
        moment = _aware_utc(now or self.clock())
        async with self._lock:
            # A worker that disappeared after taking its final lease must not
            # receive an extra execution when the lease expires.  Marking it
            # DEAD here preserves the max-attempts invariant and leaves a
            # structured terminal state for an operator retry.
            for expired in self._jobs.values():
                lease_expired = (
                    expired.status == JobStatus.LEASED
                    and expired.lease_expires_at is not None
                    and expired.lease_expires_at <= moment
                )
                pending_exhausted = (
                    expired.status == JobStatus.PENDING and expired.attempts >= expired.max_attempts
                )
                if (
                    lease_expired and expired.attempts >= expired.max_attempts
                ) or pending_exhausted:
                    expired.status = JobStatus.DEAD
                    expired.lease_owner = None
                    expired.lease_expires_at = None
                    expired.last_error = {
                        "code": "MAX_ATTEMPTS_EXHAUSTED",
                        "message": "job lease expired after max attempts",
                        "retryable": False,
                    }
                    expired.updated_at = moment
                    self.transition_history.append((expired.id, JobStatus.DEAD))
            candidates = [
                job
                for job in self._jobs.values()
                if (job.status == JobStatus.PENDING and job.available_at <= moment)
                or (
                    job.status == JobStatus.LEASED
                    and job.lease_expires_at is not None
                    and job.lease_expires_at <= moment
                )
            ]
            candidates.sort(key=lambda job: (-job.priority, job.available_at, job.id))
            if not candidates:
                return None
            selected = candidates[0]
            # A lease may expire at max_attempts; allowing one final claim lets
            # the worker record a structured DEAD transition rather than lose
            # the job silently.
            selected.status = JobStatus.LEASED
            selected.lease_owner = worker_id
            selected.lease_expires_at = moment + timedelta(seconds=lease_seconds)
            selected.attempts += 1
            selected.updated_at = moment
            self.claim_history.append((selected.id, worker_id))
            self.transition_history.append((selected.id, JobStatus.LEASED))
            return replace(selected)

    async def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        lease_seconds: float = 60.0,
        now: datetime | None = None,
    ) -> bool:
        moment = _aware_utc(now or self.clock())
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.LEASED or job.lease_owner != worker_id:
                return False
            job.lease_expires_at = moment + timedelta(seconds=lease_seconds)
            job.updated_at = moment
            return True

    async def complete(
        self,
        job_id: str,
        worker_id: str,
        *,
        result: Any = None,
        now: datetime | None = None,
    ) -> bool:
        moment = _aware_utc(now or self.clock())
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.LEASED or job.lease_owner != worker_id:
                return False
            job.status = JobStatus.SUCCEEDED
            job.lease_owner = None
            job.lease_expires_at = None
            job.last_error = None
            job.result = result
            job.updated_at = moment
            self.transition_history.append((job.id, JobStatus.SUCCEEDED))
            return True

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        error: Mapping[str, Any],
        *,
        retryable: bool = True,
        now: datetime | None = None,
        backoff_seconds: float = 0.0,
    ) -> JobStatus:
        moment = _aware_utc(now or self.clock())
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.status != JobStatus.LEASED or job.lease_owner != worker_id:
                return job.status
            job.last_error = dict(error)
            job.lease_owner = None
            job.lease_expires_at = None
            if retryable and job.attempts < job.max_attempts:
                job.status = JobStatus.PENDING
                job.available_at = moment + timedelta(seconds=max(0.0, backoff_seconds))
            elif retryable:
                job.status = JobStatus.DEAD
            else:
                job.status = JobStatus.FAILED
            job.updated_at = moment
            self.transition_history.append((job.id, job.status))
            return job.status

    async def retry(self, job_id: str, *, now: datetime | None = None) -> bool:
        moment = _aware_utc(now or self.clock())
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in (JobStatus.PENDING, JobStatus.LEASED):
                return True
            if job.status not in (JobStatus.FAILED, JobStatus.DEAD, JobStatus.CANCELLED):
                return False
            job.status = JobStatus.PENDING
            job.attempts = 0
            job.available_at = moment
            job.lease_owner = None
            job.lease_expires_at = None
            job.last_error = None
            job.updated_at = moment
            self.transition_history.append((job.id, JobStatus.PENDING))
            return True

    async def cancel(self, job_id: str, *, now: datetime | None = None) -> bool:
        moment = _aware_utc(now or self.clock())
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.PENDING:
                return False
            job.status = JobStatus.CANCELLED
            job.updated_at = moment
            self.transition_history.append((job.id, JobStatus.CANCELLED))
            return True

    async def release_leases(self, worker_id: str, *, now: datetime | None = None) -> int:
        moment = _aware_utc(now or self.clock())
        released = 0
        async with self._lock:
            for job in self._jobs.values():
                if job.status == JobStatus.LEASED and job.lease_owner == worker_id:
                    job.status = JobStatus.PENDING
                    job.available_at = moment
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.updated_at = moment
                    self.transition_history.append((job.id, JobStatus.PENDING))
                    released += 1
        return released

    # Useful aliases for service/admin code.
    requeue = retry
    release_worker_leases = release_leases


class MariaDBQueueRepository:
    """MariaDB implementation of :class:`QueueRepository`.

    ``supports_skip_locked`` can be supplied from configuration or a startup
    capability check.  If omitted, :meth:`detect_skip_locked` performs a
    conservative version query; unknown versions use the conditional-update
    fallback.  An explicit ``True`` is never silently downgraded except when a
    syntax error is observed, after which the instance stays in fallback mode.
    """

    _SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    _SELECT_COLUMNS = (
        "id, job_type, dedupe_key, status, priority, available_at, "
        "lease_owner, lease_expires_at, attempts, max_attempts, payload_json, "
        "last_error_json, created_at, updated_at"
    )

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        table_name: str = "jobs",
        supports_skip_locked: bool | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not self._SAFE_IDENTIFIER.fullmatch(table_name):
            raise ValueError("unsafe jobs table name")
        self.session_factory = session_factory
        self.table_name = table_name
        self.supports_skip_locked = supports_skip_locked
        self.clock = clock

    async def detect_skip_locked(self) -> bool:
        """Detect support without changing queue state.

        MariaDB introduced ``SKIP LOCKED`` in 10.6.  MySQL 8 is also accepted;
        any unknown or malformed response conservatively selects fallback.
        """

        if self.supports_skip_locked is not None:
            return self.supports_skip_locked
        try:
            async with _session_scope(self.session_factory) as session:
                result = await _maybe_await(session.execute(_sql("SELECT VERSION() AS version")))
                rows = _result_rows(result)
                version = str(_row_value(rows[0], "version", "")) if rows else ""
            numbers = re.search(r"(\d+)\.(\d+)", version)
            if numbers is None:
                self.supports_skip_locked = False
            else:
                major, minor = int(numbers.group(1)), int(numbers.group(2))
                if "mariadb" in version.lower():
                    self.supports_skip_locked = (major, minor) >= (10, 6)
                else:
                    self.supports_skip_locked = (major, minor) >= (8, 0)
        except Exception:
            self.supports_skip_locked = False
        return bool(self.supports_skip_locked)

    async def enqueue(self, job: Job) -> Job:
        """Insert through the shared API producer and return the stored row."""

        if job.status != JobStatus.PENDING:
            raise ValueError("only PENDING jobs may be enqueued")
        try:
            from apps.api.app.jobs.producer import MariaDBJobProducer
        except ImportError:  # pragma: no cover - ``PYTHONPATH=apps/worker``.
            from api.app.jobs.producer import MariaDBJobProducer  # type: ignore

        producer = MariaDBJobProducer(self.session_factory, table_name=self.table_name)
        submission = await producer.enqueue(
            job.job_type,
            job.payload,
            dedupe_key=job.dedupe_key,
            priority=job.priority,
            available_at=job.available_at,
            max_attempts=job.max_attempts,
            job_id=job.id,
        )
        stored = await self.get(submission.job_id)
        if stored is None:
            raise JobQueueError(f"enqueued job could not be read: {submission.job_id}")
        return stored

    add = enqueue
    put = enqueue

    async def _mark_exhausted_crawl_runs(
        self,
        session: Any,
        *,
        moment: datetime,
        last_error_json: str,
    ) -> None:
        """Close crawl runs when claim-time exhaustion makes a job DEAD.

        Crawl runs normally reuse the queue job ID (see the result applier),
        but older/proxy producers may carry the durable run identifier in
        ``payload_json.crawl_run_id`` instead.  Match both identifiers while
        restricting the update to PENDING/RUNNING rows so successful runs are
        preserved and repeated claim scans remain idempotent.
        """

        await _maybe_await(
            session.execute(
                _sql(
                    f"""
                    UPDATE crawl_runs
                    SET status = 'FAILED', finished_at = :now,
                        error_json = :last_error_json
                    WHERE status IN ('PENDING', 'RUNNING')
                      AND (
                        id IN (
                            SELECT id FROM {self.table_name}
                            WHERE job_type = 'crawl'
                              AND status = 'DEAD'
                              AND updated_at = :now
                        )
                        OR id IN (
                            SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.crawl_run_id'))
                            FROM {self.table_name}
                            WHERE job_type = 'crawl'
                              AND status = 'DEAD'
                              AND updated_at = :now
                              AND JSON_EXTRACT(payload_json, '$.crawl_run_id') IS NOT NULL
                        )
                      )
                    """.strip()
                ),
                {"now": moment, "last_error_json": last_error_json},
            )
        )

    async def _reap_exhausted_jobs(self, moment: datetime) -> None:
        """Run the global expiry transition once across all worker processes.

        Claiming is intentionally parallel, but expiry is a table-wide
        maintenance operation.  Running the same range UPDATE in every claim
        transaction lets two MariaDB processes deadlock before either reaches
        ``SKIP LOCKED``.  A connection-scoped advisory lock elects one reaper;
        other workers immediately continue to row-level claiming.
        """

        exhausted_error = json.dumps(
            {
                "code": "MAX_ATTEMPTS_EXHAUSTED",
                "message": "job lease expired after max attempts",
                "retryable": False,
            },
            sort_keys=True,
        )
        # Reaping and claiming both touch the same ordered job range.  They
        # therefore share one advisory lock; separate locks merely serialized
        # reapers while still allowing a reaper to deadlock with a claimant.
        lock_name = f"effica:{self.table_name}:claim"[:64]
        statement = _sql(
            f"""
            UPDATE {self.table_name}
            SET status = 'DEAD', lease_owner = NULL, lease_expires_at = NULL,
                last_error_json = :last_error_json, updated_at = :now
            WHERE attempts >= max_attempts
              AND (
                (status = 'PENDING' AND available_at <= :now)
                OR (status = 'LEASED' AND lease_expires_at IS NOT NULL AND lease_expires_at <= :now)
              )
            ORDER BY id
            """.strip()
        )
        # The advisory lock must outlive the write transaction's COMMIT.
        # Releasing it from inside ``_transaction`` lets the next worker enter
        # while InnoDB still owns the range locks, producing an intermittent
        # 1213 deadlock.  Keep it on a dedicated connection and release only
        # after the separate mutation transaction has fully exited.
        async with _session_scope(self.session_factory) as lock_session:
            acquired_result = await _maybe_await(
                lock_session.execute(
                    _sql("SELECT GET_LOCK(:lock_name, 5) AS acquired"),
                    {"lock_name": lock_name},
                )
            )
            acquired_rows = _result_rows(acquired_result)
            acquired = bool(
                acquired_rows and int(_row_value(acquired_rows[0], "acquired", 0) or 0) == 1
            )
            if not acquired:
                return
            try:
                async with _session_scope(self.session_factory) as session:
                    async with _transaction(session):
                        await _maybe_await(
                            session.execute(
                                statement,
                                {"last_error_json": exhausted_error, "now": moment},
                            )
                        )
                        await self._mark_exhausted_crawl_runs(
                            session, moment=moment, last_error_json=exhausted_error
                        )
            finally:
                try:
                    await _maybe_await(
                        lock_session.execute(
                            _sql("SELECT RELEASE_LOCK(:lock_name)"),
                            {"lock_name": lock_name},
                        )
                    )
                except Exception:
                    # Closing the dedicated connection also releases the
                    # advisory lock; preserve the original DB exception.
                    pass

    async def _claim_with_skip_locked(
        self, worker_id: str, lease_seconds: float, moment: datetime
    ) -> Job | None:
        table = self.table_name
        select = _sql(
            f"""
            SELECT {self._SELECT_COLUMNS} FROM {table}
            WHERE (
                (status = 'PENDING' AND available_at <= :now)
                OR (status = 'LEASED' AND lease_expires_at IS NOT NULL AND lease_expires_at <= :now)
              )
              AND attempts < max_attempts
            ORDER BY priority DESC, available_at ASC, id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """.strip()
        )
        update = _sql(
            f"""
            UPDATE {table}
            SET status = 'LEASED', lease_owner = :worker_id,
                lease_expires_at = :lease_expires_at,
                attempts = attempts + 1, updated_at = :now
            WHERE id = :id
            """.strip()
        )
        await self._reap_exhausted_jobs(moment)
        # Keep the advisory lock on its own checked-out connection.  A
        # SQLAlchemy commit may return a transaction connection to the pool;
        # releasing the named lock through that session afterwards can then
        # run on a different connection and leak the lock.
        async with _session_scope(self.session_factory) as lock_session:
            claim_lock = f"effica:{self.table_name}:claim"[:64]
            lock_result = await _maybe_await(
                lock_session.execute(
                    _sql("SELECT GET_LOCK(:lock_name, 5) AS acquired"),
                    {"lock_name": claim_lock},
                )
            )
            lock_rows = _result_rows(lock_result)
            acquired = bool(lock_rows and int(_row_value(lock_rows[0], "acquired", 0) or 0) == 1)
            if not acquired:
                return None
            try:
                candidate: Job | None = None
                async with _session_scope(self.session_factory) as session:
                    async with _transaction(session):
                        result = await _maybe_await(session.execute(select, {"now": moment}))
                        rows = _result_rows(result)
                        if rows:
                            candidate = _job_from_row(rows[0])
                            await _maybe_await(
                                session.execute(
                                    update,
                                    {
                                        "id": candidate.id,
                                        "worker_id": worker_id,
                                        "lease_expires_at": moment
                                        + timedelta(seconds=lease_seconds),
                                        "now": moment,
                                    },
                                )
                            )
                            candidate.status = JobStatus.LEASED
                            candidate.lease_owner = worker_id
                            candidate.lease_expires_at = moment + timedelta(seconds=lease_seconds)
                            candidate.attempts += 1
                            candidate.updated_at = moment
                return candidate
            finally:
                try:
                    await _maybe_await(
                        lock_session.execute(
                            _sql("SELECT RELEASE_LOCK(:lock_name)"),
                            {"lock_name": claim_lock},
                        )
                    )
                except Exception:
                    pass

    async def _claim_with_conditional_update(
        self,
        worker_id: str,
        lease_seconds: float,
        moment: datetime,
    ) -> Job | None:
        table = self.table_name
        select = _sql(
            f"""
            SELECT {self._SELECT_COLUMNS} FROM {table}
            WHERE (
                (status = 'PENDING' AND available_at <= :now)
                OR (status = 'LEASED' AND lease_expires_at IS NOT NULL AND lease_expires_at <= :now)
              )
              AND attempts < max_attempts
            ORDER BY priority DESC, available_at ASC, id ASC
            LIMIT 25
            """.strip()
        )
        update = _sql(
            f"""
            UPDATE {table}
            SET status = 'LEASED', lease_owner = :worker_id,
                lease_expires_at = :lease_expires_at,
                attempts = attempts + 1, updated_at = :now
            WHERE id = :id
              AND (
                (status = 'PENDING' AND available_at <= :now)
                OR (status = 'LEASED' AND lease_expires_at IS NOT NULL AND lease_expires_at <= :now)
              )
            """.strip()
        )
        await self._reap_exhausted_jobs(moment)
        async with _session_scope(self.session_factory) as lock_session:
            claim_lock = f"effica:{self.table_name}:claim"[:64]
            lock_result = await _maybe_await(
                lock_session.execute(
                    _sql("SELECT GET_LOCK(:lock_name, 5) AS acquired"),
                    {"lock_name": claim_lock},
                )
            )
            lock_rows = _result_rows(lock_result)
            acquired = bool(lock_rows and int(_row_value(lock_rows[0], "acquired", 0) or 0) == 1)
            if not acquired:
                return None
            try:
                claimed: Job | None = None
                async with _session_scope(self.session_factory) as session:
                    async with _transaction(session):
                        result = await _maybe_await(session.execute(select, {"now": moment}))
                        candidates = _result_rows(result)
                        for row in candidates:
                            job = _job_from_row(row)
                            params = {
                                "id": job.id,
                                "worker_id": worker_id,
                                "lease_expires_at": moment + timedelta(seconds=lease_seconds),
                                "now": moment,
                            }
                            updated = await _maybe_await(session.execute(update, params))
                            if _rowcount(updated) != 1:
                                continue
                            job.status = JobStatus.LEASED
                            job.lease_owner = worker_id
                            job.lease_expires_at = moment + timedelta(seconds=lease_seconds)
                            job.attempts += 1
                            job.updated_at = moment
                            claimed = job
                            break
                return claimed
            finally:
                try:
                    await _maybe_await(
                        lock_session.execute(
                            _sql("SELECT RELEASE_LOCK(:lock_name)"),
                            {"lock_name": claim_lock},
                        )
                    )
                except Exception:
                    pass

    async def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 60.0,
        now: datetime | None = None,
    ) -> Job | None:
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        moment = _aware_utc(now or self.clock())
        supports = await self.detect_skip_locked()
        if supports:
            try:
                return await self._claim_with_skip_locked(worker_id, lease_seconds, moment)
            except Exception as exc:
                # A rolling MariaDB upgrade or proxy may report a capability
                # different from startup detection.  Downgrade only for a
                # syntax/capability error, never for connection/data errors.
                if not _looks_like_skip_locked_error(exc):
                    raise
                self.supports_skip_locked = False
        return await self._claim_with_conditional_update(worker_id, lease_seconds, moment)

    async def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        lease_seconds: float = 60.0,
        now: datetime | None = None,
    ) -> bool:
        moment = _aware_utc(now or self.clock())
        table = self.table_name
        statement = _sql(
            f"""
            UPDATE {table}
            SET lease_expires_at = :lease_expires_at, updated_at = :now
            WHERE id = :id AND status = 'LEASED' AND lease_owner = :worker_id
            """.strip()
        )
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                result = await _maybe_await(
                    session.execute(
                        statement,
                        {
                            "id": job_id,
                            "worker_id": worker_id,
                            "lease_expires_at": moment + timedelta(seconds=lease_seconds),
                            "now": moment,
                        },
                    )
                )
                return _rowcount(result) == 1

    async def complete(
        self,
        job_id: str,
        worker_id: str,
        *,
        result: Any = None,
        now: datetime | None = None,
    ) -> bool:
        del result
        moment = _aware_utc(now or self.clock())
        table = self.table_name
        statement = _sql(
            f"""
            UPDATE {table}
            SET status = 'SUCCEEDED', lease_owner = NULL,
                lease_expires_at = NULL, last_error_json = NULL, updated_at = :now
            WHERE id = :id AND status = 'LEASED' AND lease_owner = :worker_id
            """.strip()
        )
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                updated = await _maybe_await(
                    session.execute(
                        statement, {"id": job_id, "worker_id": worker_id, "now": moment}
                    )
                )
                return _rowcount(updated) == 1

    async def _owned_job(self, session: Any, job_id: str, worker_id: str) -> Job | None:
        statement = _sql(
            f"""
            SELECT {self._SELECT_COLUMNS} FROM {self.table_name}
            WHERE id = :id AND status = 'LEASED' AND lease_owner = :worker_id
            FOR UPDATE
            """.strip()
        )
        result = await _maybe_await(
            session.execute(statement, {"id": job_id, "worker_id": worker_id})
        )
        rows = _result_rows(result)
        return None if not rows else _job_from_row(rows[0])

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        error: Mapping[str, Any],
        *,
        retryable: bool = True,
        now: datetime | None = None,
        backoff_seconds: float = 0.0,
    ) -> JobStatus:
        moment = _aware_utc(now or self.clock())
        table = self.table_name
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                job = await self._owned_job(session, job_id, worker_id)
                if job is None:
                    existing_query = _sql(f"SELECT status FROM {table} WHERE id = :id LIMIT 1")
                    existing_result = await _maybe_await(
                        session.execute(existing_query, {"id": job_id})
                    )
                    existing_rows = _result_rows(existing_result)
                    if not existing_rows:
                        raise JobNotFound(job_id)
                    return _as_status(_row_value(existing_rows[0], "status"))
                if retryable and job.attempts < job.max_attempts:
                    status = JobStatus.PENDING
                    available = moment + timedelta(seconds=max(0.0, backoff_seconds))
                elif retryable:
                    status = JobStatus.DEAD
                    available = moment
                else:
                    status = JobStatus.FAILED
                    available = moment
                statement = _sql(
                    f"""
                    UPDATE {table}
                    SET status = :status, available_at = :available_at,
                        lease_owner = NULL, lease_expires_at = NULL,
                        last_error_json = :last_error_json, updated_at = :now
                    WHERE id = :id AND status = 'LEASED' AND lease_owner = :worker_id
                    """.strip()
                )
                updated = await _maybe_await(
                    session.execute(
                        statement,
                        {
                            "id": job_id,
                            "worker_id": worker_id,
                            "status": status.value,
                            "available_at": available,
                            "last_error_json": json.dumps(dict(error), sort_keys=True, default=str),
                            "now": moment,
                        },
                    )
                )
                if _rowcount(updated) == 1:
                    if job.job_type == "crawl" and status in {
                        JobStatus.FAILED,
                        JobStatus.DEAD,
                    }:
                        await _maybe_await(
                            session.execute(
                                _sql(
                                    """
                                    UPDATE crawl_runs
                                    SET status = 'FAILED', finished_at = :now,
                                        error_json = :last_error_json
                                    WHERE id = :id
                                       OR (
                                           :crawl_run_id IS NOT NULL
                                           AND id = :crawl_run_id
                                       )
                                    """.strip()
                                ),
                                {
                                    "id": job_id,
                                    "crawl_run_id": job.payload.get("crawl_run_id"),
                                    "now": moment,
                                    "last_error_json": json.dumps(
                                        dict(error), sort_keys=True, default=str
                                    ),
                                },
                            )
                        )
                    return status
                # Another transition won the conditional update.  Read the
                # canonical state in this transaction rather than opening a
                # second session while the row lock is held.
                existing_result = await _maybe_await(
                    session.execute(
                        _sql(f"SELECT status FROM {table} WHERE id = :id LIMIT 1"),
                        {"id": job_id},
                    )
                )
                rows = _result_rows(existing_result)
                return status if not rows else _as_status(_row_value(rows[0], "status"))

    async def get(self, job_id: str) -> Job | None:
        statement = _sql(
            f"SELECT {self._SELECT_COLUMNS} FROM {self.table_name} WHERE id = :id LIMIT 1"
        )
        async with _session_scope(self.session_factory) as session:
            result = await _maybe_await(session.execute(statement, {"id": job_id}))
            rows = _result_rows(result)
            return None if not rows else _job_from_row(rows[0])

    async def retry(self, job_id: str, *, now: datetime | None = None) -> bool:
        moment = _aware_utc(now or self.clock())
        statement = _sql(
            f"""
            UPDATE {self.table_name}
            SET status = 'PENDING', attempts = 0, available_at = :now,
                lease_owner = NULL, lease_expires_at = NULL,
                last_error_json = NULL, updated_at = :now
            WHERE id = :id AND status IN ('FAILED', 'DEAD', 'CANCELLED')
            """.strip()
        )
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                updated = await _maybe_await(
                    session.execute(statement, {"id": job_id, "now": moment})
                )
                return _rowcount(updated) == 1

    async def cancel(self, job_id: str, *, now: datetime | None = None) -> bool:
        moment = _aware_utc(now or self.clock())
        statement = _sql(
            f"""
            UPDATE {self.table_name}
            SET status = 'CANCELLED', updated_at = :now
            WHERE id = :id AND status = 'PENDING'
            """.strip()
        )
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                updated = await _maybe_await(
                    session.execute(statement, {"id": job_id, "now": moment})
                )
                return _rowcount(updated) == 1

    async def release_leases(self, worker_id: str, *, now: datetime | None = None) -> int:
        moment = _aware_utc(now or self.clock())
        statement = _sql(
            f"""
            UPDATE {self.table_name}
            SET status = 'PENDING', available_at = :now,
                lease_owner = NULL, lease_expires_at = NULL, updated_at = :now
            WHERE status = 'LEASED' AND lease_owner = :worker_id
            """.strip()
        )
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                updated = await _maybe_await(
                    session.execute(statement, {"worker_id": worker_id, "now": moment})
                )
                return _rowcount(updated)

    # Common aliases used by shutdown/admin integrations.
    requeue = retry
    release_worker_leases = release_leases


def _looks_like_skip_locked_error(error: BaseException) -> bool:
    text = str(error).lower()
    markers = (
        "skip locked",
        "syntax error",
        "1064",
        "unsupported",
        "not supported",
        "42000",
    )
    return any(marker in text for marker in markers)
