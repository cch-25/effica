"""One durable topic-first collection per Korean calendar day."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .services import (
    _database_timestamp,
    _json,
    _maybe_await,
    _session_scope,
    _sql,
    _stable_id,
    _transaction,
    _utc,
    utc_now,
)


class MariaDBDailyIssueScheduler:
    """Unique job keys survive restarts and concurrent scheduler processes.

    A failed day is retained as failed, rather than issuing another potentially
    billed search. Provider request receipts allow safe recovery by operators.
    """

    # WorkerRuntime polls this interface. The durable KST key still permits
    # only one job per day; polling catches midnight without a process restart.
    interval_seconds = 60.0

    def __init__(self, session_factory: Callable[[], Any], *,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def tick(self, worker_id: str) -> int:
        now = _utc(self.clock())
        day = now.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
        key = f"daily-issues:{day}"
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                result = await _maybe_await(session.execute(_sql("""
                    INSERT INTO jobs
                      (id, job_type, dedupe_key, status, priority, available_at,
                       lease_owner, lease_expires_at, attempts, max_attempts,
                       payload_json, last_error_json, created_at, updated_at)
                    VALUES (:id, 'discover_issues', :key, 'PENDING', 20, :now,
                            NULL, NULL, 0, 1, :payload, NULL, :now, :now)
                    ON DUPLICATE KEY UPDATE id = id
                """), {
                    "id": _stable_id(f"job:discover_issues:{key}"),
                    "key": key,
                    "now": _database_timestamp(now),
                    "payload": _json({"run_date": day, "as_of": now.isoformat()}),
                }))
        return int(getattr(result, "rowcount", 0) == 1)
