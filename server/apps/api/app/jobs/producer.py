"""MariaDB-backed job producer.

The producer uses SQL text instead of importing an API DB model.  It accepts
an ``async_sessionmaker``-like callable, which keeps it usable from the API
and straightforward to exercise with a fake session in unit tests.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Protocol

from .types import (
    DEFAULT_MAX_ATTEMPTS,
    JobEnvelope,
    JobSubmission,
    canonical_payload_json,
    generate_job_id,
    normalize_job_type,
    utc_now,
)


class JobProducer(Protocol):
    """Minimal producer contract API services should depend on."""

    async def enqueue(
        self,
        job_type: str,
        payload: Mapping[str, Any],
        *,
        dedupe_key: str | None = None,
        priority: int = 0,
        available_at: datetime | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        job_id: str | None = None,
    ) -> JobSubmission:
        ...


SessionFactory = Callable[[], Any]


def _sql(statement: str) -> Any:
    """Create SQLAlchemy text lazily, preserving importability without it."""

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
async def _session_scope(factory: SessionFactory) -> AsyncIterator[Any]:
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
    # context manager.  Awaiting ``begin()`` before entering it starts the
    # same transaction twice and raises ``InvalidRequestError`` on a real
    # AsyncSession.  Enter the context first; only await custom/fake begin
    # implementations that do not expose the async context protocol.
    context = begin()
    if not hasattr(context, "__aenter__"):
        context = await _maybe_await(context)
    if hasattr(context, "__aenter__"):
        async with context:
            yield session
        return
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


def _first_mapping(result: Any) -> Mapping[str, Any] | None:
    """Read the first row from SQLAlchemy or small fake result objects."""

    mappings = getattr(result, "mappings", None)
    if mappings is not None:
        mapped = mappings()
        first = getattr(mapped, "first", None)
        if first is not None:
            row = first()
            if row is not None:
                return row
        all_rows = getattr(mapped, "all", None)
        if all_rows is not None:
            rows = all_rows()
            if rows:
                return rows[0]
    first = getattr(result, "first", None)
    if first is not None:
        row = first()
        if row is not None:
            return row
    rows = getattr(result, "all", None)
    if rows is not None:
        values = rows()
        if values:
            return values[0]
    if isinstance(result, (list, tuple)) and result:
        row = result[0]
        return row if isinstance(row, Mapping) else None
    return None


class MariaDBJobProducer:
    """Insert jobs using the shared MariaDB ``jobs`` table.

    A unique ``(job_type, dedupe_key)`` constraint is the final authority for
    idempotency.  ``ON DUPLICATE KEY UPDATE`` deliberately performs a no-op;
    the subsequent select returns the pre-existing job id to every caller.
    """

    _SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(self, session_factory: SessionFactory, *, table_name: str = "jobs") -> None:
        if not self._SAFE_IDENTIFIER.fullmatch(table_name):
            raise ValueError("unsafe jobs table name")
        self.session_factory = session_factory
        self.table_name = table_name

    async def enqueue(
        self,
        job_type: str | JobEnvelope,
        payload: Mapping[str, Any] | None = None,
        *,
        dedupe_key: str | None = None,
        priority: int = 0,
        available_at: datetime | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        job_id: str | None = None,
    ) -> JobSubmission:
        if isinstance(job_type, JobEnvelope):
            envelope = job_type
        else:
            envelope = JobEnvelope(
                job_type=normalize_job_type(job_type),
                payload=dict(payload or {}),
                id=job_id,
                dedupe_key=dedupe_key,
                priority=priority,
                available_at=available_at,
                max_attempts=max_attempts,
            )

        resolved_id = envelope.id or generate_job_id()
        # The physical schema keeps dedupe_key non-null because the unique
        # constraint is the queue's idempotency boundary.  Callers that do not
        # need semantic dedupe still receive a unique key, so they do not
        # accidentally collide with another job of the same type.
        stored_dedupe_key = envelope.dedupe_key or resolved_id
        available = envelope.available_at or utc_now()
        created_at = utc_now()
        table = self.table_name
        insert = _sql(
            f"""
            INSERT INTO {table}
              (id, job_type, dedupe_key, status, priority, available_at,
               lease_owner, lease_expires_at, attempts, max_attempts,
               payload_json, last_error_json, created_at, updated_at)
            VALUES
              (:id, :job_type, :dedupe_key, 'PENDING', :priority, :available_at,
               NULL, NULL, 0, :max_attempts, :payload_json, NULL,
               :created_at, :updated_at)
            ON DUPLICATE KEY UPDATE id = id
            """.strip()
        )
        params = {
            "id": resolved_id,
            "job_type": normalize_job_type(envelope.job_type),
            "dedupe_key": stored_dedupe_key,
            "priority": int(envelope.priority),
            "available_at": available,
            "max_attempts": int(envelope.max_attempts),
            "payload_json": canonical_payload_json(envelope.payload),
            "created_at": created_at,
            "updated_at": created_at,
        }

        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                await _maybe_await(session.execute(insert, params))
                existing_query = _sql(
                    f"""
                    SELECT id FROM {table}
                    WHERE job_type = :job_type
                      AND dedupe_key <=> :dedupe_key
                    ORDER BY created_at ASC, id ASC
                    LIMIT 1
                    """.strip()
                )
                result = await _maybe_await(
                    session.execute(
                        existing_query,
                        {"job_type": normalize_job_type(envelope.job_type), "dedupe_key": stored_dedupe_key},
                    )
                )
                row = _first_mapping(result)
                existing_id = None if row is None else row.get("id")
                return JobSubmission(
                    job_id=str(existing_id or resolved_id),
                    job_type=normalize_job_type(envelope.job_type),
                    dedupe_key=stored_dedupe_key,
                    created=str(existing_id or resolved_id) == resolved_id,
                )

    # Common naming used by API services and tests.
    publish = enqueue
    submit = enqueue
