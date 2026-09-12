"""One durable topic-first collection per Korean calendar day."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .services import (
    MariaDBCrawlScheduler,
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


class MariaDBCollectionScheduler:
    """Run issue discovery and bounded general-news collection independently.

    Issue discovery keeps its KST daily identity and publisher-diversity rules.
    The general scheduler separately refreshes every explicitly scheduled,
    approved source, so storing and analyzing an article no longer depends on
    that article being selected for an editorial issue.
    """

    interval_seconds = 60.0

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        general_interval_seconds: float = 86400.0,
        general_batch_size: int = 50,
        general_max_attempts: int = 1,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.daily_issues = MariaDBDailyIssueScheduler(session_factory, clock=clock)
        self.general_articles = MariaDBCrawlScheduler(
            session_factory,
            interval_seconds=general_interval_seconds,
            batch_size=general_batch_size,
            max_attempts=general_max_attempts,
            clock=clock,
        )

    async def tick(self, worker_id: str) -> int:
        issue_jobs = await self.daily_issues.tick(worker_id)
        article_jobs = await self.general_articles.tick(worker_id)
        return issue_jobs + article_jobs


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
                    SELECT :id, 'discover_issues', :key, 'PENDING', 20, :now,
                           NULL, NULL, 0, 1, :payload, NULL, :now, :now
                    FROM DUAL
                    WHERE NOT EXISTS (
                        SELECT 1 FROM jobs
                        WHERE job_type = 'discover_issues' AND dedupe_key = :key
                    )
                    ON DUPLICATE KEY UPDATE id = id
                """), {
                    "id": _stable_id(f"job:discover_issues:{key}"),
                    "key": key,
                    "now": _database_timestamp(now),
                    "payload": _json({"run_date": day, "as_of": now.isoformat()}),
                }))
        return int(getattr(result, "rowcount", 0) == 1)
