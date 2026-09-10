"""Shrink the pending analysis queue without sacrificing source diversity.

The command is deliberately narrow: it keeps one source-balanced next-day
cohort, cancels only pending analysis jobs outside it, and updates scheduled
source adapters to the bounded collection policy.  It never deletes articles
or touches leased work.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, deque
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.app.db.session import create_engine, dispose_engine

DAILY_ARTICLE_LIMIT = 100
ESSENTIAL_ARTICLE_RESERVE = 9
NEXT_DAY_ANALYSIS_COHORT = DAILY_ARTICLE_LIMIT - ESSENTIAL_ARTICLE_RESERVE
SCHEDULED_MAX_ITEMS = 2
SCHEDULED_INTERVAL_SECONDS = 6 * 60 * 60
KST = ZoneInfo("Asia/Seoul")


def next_kst_midnight(now: datetime) -> datetime:
    """Return the next KST day boundary as a naive UTC database timestamp."""

    local = now.astimezone(KST)
    tomorrow = local.date() + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, KST).astimezone(UTC).replace(tzinfo=None)


def source_balanced_cohort(rows: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Select at most one new version per source on each round.

    ``rows`` must already be sorted newest first within each source.  Repeated
    jobs for the same version are ignored so a source cannot consume the cohort
    through retries or duplicate historical work.
    """

    by_source: dict[str, deque[dict[str, Any]]] = {}
    seen_versions: set[str] = set()
    for row in rows:
        version_id = str(row["article_version_id"])
        source_id = str(row["source_id"])
        if version_id in seen_versions:
            continue
        seen_versions.add(version_id)
        by_source.setdefault(source_id, deque()).append(row)
    selected: list[dict[str, Any]] = []
    while by_source and len(selected) < limit:
        for source_id in sorted(tuple(by_source)):
            if len(selected) >= limit:
                break
            queue = by_source[source_id]
            selected.append(queue.popleft())
            if not queue:
                del by_source[source_id]
    return selected


async def _rows(session, statement: str, **params: Any) -> list[dict[str, Any]]:
    result = await session.execute(text(statement), params)
    return [dict(row) for row in result.mappings()]


async def plan(session, now: datetime, *, cohort_size: int = NEXT_DAY_ANALYSIS_COHORT) -> dict[str, Any]:
    candidates = await _rows(
        session,
        """
        SELECT j.id AS job_id, a.source_id, s.name AS source_name,
               av.id AS article_version_id, a.published_at, a.created_at,
               j.priority, j.available_at
        FROM jobs j
        JOIN article_versions av
          ON av.id = JSON_UNQUOTE(JSON_EXTRACT(j.payload_json, '$.article_version_id'))
        JOIN articles a ON a.id = av.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE j.job_type = 'analyze'
          AND j.status = 'PENDING'
          AND a.status = 'active'
          AND s.active = 1
          AND NOT EXISTS (
              SELECT 1 FROM model_assessments ma
              WHERE ma.article_version_id = av.id AND ma.status = 'SUCCEEDED'
          )
        ORDER BY s.id, a.published_at DESC, a.created_at DESC, j.priority DESC, j.id
        """,
    )
    selected = source_balanced_cohort(candidates, cohort_size)
    selected_ids = {str(row["job_id"]) for row in selected}
    adapter_rows = await _rows(
        session,
        """
        SELECT a.id, a.config_json
        FROM source_adapters a
        WHERE a.active = 1
          AND LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(a.config_json, '$.scheduled')), 'false')) = 'true'
        """,
    )
    counts = Counter(str(row["source_name"]) for row in selected)
    return {
        "checked_at_utc": now.isoformat(),
        "next_analysis_window_utc": next_kst_midnight(now).isoformat(),
        "daily_article_limit": DAILY_ARTICLE_LIMIT,
        "essential_article_reserve": ESSENTIAL_ARTICLE_RESERVE,
        "pending_analyze_before": len(candidates),
        "kept_pending": len(selected_ids),
        "cancel_pending": len(candidates) - len(selected_ids),
        "selected_source_counts": dict(sorted(counts.items())),
        "scheduled_adapter_count": len(adapter_rows),
        "article_items_per_source_refresh": SCHEDULED_MAX_ITEMS,
        "crawl_interval_seconds": SCHEDULED_INTERVAL_SECONDS,
        "selected_job_ids": sorted(selected_ids),
        "scheduled_adapters": adapter_rows,
    }


async def apply(session, current: dict[str, Any], now: datetime) -> dict[str, int]:
    selected_ids = current["selected_job_ids"]
    cancelled = await session.execute(
        text(
            """
            UPDATE jobs
            SET status = 'CANCELLED', lease_owner = NULL, lease_expires_at = NULL,
                last_error_json = :reason, updated_at = :now
            WHERE job_type = 'analyze' AND status = 'PENDING'
              AND id NOT IN :selected_ids
            """
        ).bindparams(bindparam("selected_ids", expanding=True)),
        {
            "selected_ids": selected_ids or ["__no_selected_jobs__"],
            "reason": json.dumps({
                "code": "BACKLOG_SUPERSEDED_BY_DIVERSE_DAILY_COHORT",
                "message": "Superseded by the bounded, source-balanced daily analysis cohort.",
            }),
            "now": now.replace(tzinfo=None),
        },
    )
    scheduled_for = next_kst_midnight(now)
    kept = 0
    if selected_ids:
        kept_result = await session.execute(
            text(
                """
                UPDATE jobs
                SET priority = 100, available_at = :available_at, updated_at = :now
                WHERE job_type = 'analyze' AND status = 'PENDING' AND id IN :selected_ids
                """
            ).bindparams(bindparam("selected_ids", expanding=True)),
            {"selected_ids": selected_ids, "available_at": scheduled_for, "now": now.replace(tzinfo=None)},
        )
        kept = max(0, int(kept_result.rowcount or 0))
    adapters = 0
    for adapter in current["scheduled_adapters"]:
        config = adapter["config_json"]
        if isinstance(config, str):
            config = json.loads(config)
        config = dict(config or {})
        config["max_items"] = SCHEDULED_MAX_ITEMS
        config["max_hydration_fetches"] = SCHEDULED_MAX_ITEMS
        result = await session.execute(
            text("UPDATE source_adapters SET config_json = :config WHERE id = :id"),
            {"id": adapter["id"], "config": json.dumps(config, ensure_ascii=False)},
        )
        adapters += max(0, int(result.rowcount or 0))
    return {"cancelled_pending_analyze": max(0, int(cancelled.rowcount or 0)), "kept_pending_analyze": kept, "updated_scheduled_adapters": adapters}


async def run(*, apply_changes: bool = False) -> dict[str, Any]:
    engine = create_engine()
    now = datetime.now(UTC)
    try:
        async with engine.connect() as connection, async_sessionmaker(connection, expire_on_commit=False)() as session:
            locked = (await session.execute(text("SELECT GET_LOCK('effica-backlog-relief', 0)"))).scalar()
            if locked != 1:
                raise RuntimeError("another backlog relief run is active")
            try:
                before = await plan(session, now)
                await session.rollback()
                if not apply_changes:
                    return {"applied": False, "before": before}
                async with session.begin():
                    current = await plan(session, now)
                    changes = await apply(session, current, now)
                after = await plan(session, now)
                return {"applied": True, "before": before, "changes": changes, "after": after}
            finally:
                await session.execute(text("SELECT RELEASE_LOCK('effica-backlog-relief')"))
    finally:
        await dispose_engine()


def _public(report: dict[str, Any]) -> dict[str, Any]:
    """Never print internal job identifiers in an operational report."""

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key not in {"selected_job_ids", "scheduled_adapters"}}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return strip(report)


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the queue and source-adapter updates")
    args = parser.parse_args()
    print(json.dumps(_public(asyncio.run(run(apply_changes=args.apply))), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
