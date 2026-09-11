"""Seven-day, 300-article inventory with proportional dates and diverse sources.

Online enforcement and ingestion share a transaction-scoped inventory lock.
Activity rows and awarded credits survive article deletion.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.app.db.session import create_engine, dispose_engine
from apps.api.app.domains.content.retention import MAX_ARTICLES, RETENTION_DAYS, expired, utc
from apps.api.app.domains.issues.editorial_policy import is_current_article, publisher_identity
from apps.api.app.domains.issues.topics import infer_issue_topic


def strings(value: Any) -> set[str]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return {value}
        return strings(decoded) if not isinstance(decoded, str) else {decoded}
    if isinstance(value, dict):
        return set(value) | set().union(*(strings(v) for v in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(strings(v) for v in value))
    return set()


async def rows(session, sql: str, **params) -> list[dict]:
    return list((await session.execute(text(sql), params)).mappings())


async def in_query(session, sql: str, ids: set[str] | list[str]):
    return await session.execute(text(sql).bindparams(bindparam("ids", expanding=True)), {"ids": sorted(ids)})


def inventory_plan(articles: list[dict], now: datetime, protected_issues: list[dict] | None = None) -> dict:
    """Protect current editions, then apportion other articles by date/source.

    All quotas are computed from the same pre-deletion snapshot. Recomputing
    them after every deletion would compound rounding and distort date ratios.
    """
    stale = {a["id"] for a in articles if expired(a["published_at"], a["created_at"], now)}
    current = {a["id"]: a for a in articles if a["id"] not in stale}
    protected: set[str] = set()
    for issue in protected_issues or []:
        members = set(issue["article_ids"]) & current.keys()
        publishers = {publisher_identity(current[aid].get("canonical_url", "")) for aid in members
                      if is_current_article(current[aid]["published_at"], now)} - {None}
        if len(publishers) >= 3 and len(protected | members) <= MAX_ARTICLES:
            protected.update(members)
    by_day: dict[str, list[dict]] = defaultdict(list)
    for article in articles:
        if article["id"] not in stale:
            effective = min(value for value in (utc(article["published_at"]), utc(article["created_at"])) if value is not None)
            date = effective.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
            by_day[date].append(article)
    total = sum(map(len, by_day.values()))
    remaining = {day: [a for a in items if a["id"] not in protected] for day, items in by_day.items()}
    remaining_total = total - len(protected)
    budget = min(MAX_ARTICLES - len(protected), remaining_total)
    quotas = {day: len(items) * budget // remaining_total for day, items in remaining.items()} if remaining_total else dict.fromkeys(by_day, 0)
    remainder_order = sorted(by_day, key=lambda day: (len(remaining[day]) * budget % remaining_total, day), reverse=True) if remaining_total else []
    for day in remainder_order[:budget - sum(quotas.values())]:
        quotas[day] += 1
    kept: set[str] = set(protected)
    for day, items in sorted(by_day.items()):
        source_counts = Counter(a["source_id"] for a in items if a["id"] in protected)
        topic_counts = Counter(infer_issue_topic(a.get("title") or "") for a in items if a["id"] in protected)
        pool = {a["id"]: {**a, "topic": infer_issue_topic(a.get("title") or "")} for a in remaining[day]}
        for _ in range(quotas[day]):
            choice = min(pool.values(), key=lambda a: (
                source_counts[a["source_id"]], topic_counts[a["topic"]],
                not a.get("assessed", False), a["id"],
            ))
            kept.add(choice["id"])
            source_counts[choice["source_id"]] += 1
            topic_counts[choice["topic"]] += 1
            del pool[choice["id"]]
        quotas[day] += sum(a["id"] in protected for a in items)
    targets = {a["id"] for a in articles} - kept
    return {
        "checked_at": now.isoformat(),
        "cutoff": (now - timedelta(days=RETENTION_DAYS)).isoformat(),
        "max_articles": MAX_ARTICLES,
        "total": len(articles), "expired": len(stale),
        "overflow": max(0, total - MAX_ARTICLES),
        "protected_expired": 0,
        "protected_current": len(protected),
        "delete_count": len(targets), "remaining": len(articles) - len(targets),
        "by_date": {day: {"before": len(items), "keep": quotas[day], "delete": len(items) - quotas[day]} for day, items in sorted(by_day.items())},
        "sources_before": dict(Counter(a["source_id"] for a in articles)),
        "sources_after": dict(Counter(a["source_id"] for a in articles if a["id"] in kept)),
        "article_ids": sorted(targets),
    }


async def lock_inventory(session) -> None:
    await session.execute(text("SELECT id FROM article_inventory_guard WHERE id = 1 FOR UPDATE"))


async def plan(session, now: datetime) -> dict:
    articles = await rows(session, """SELECT a.id, a.source_id, a.title, a.canonical_url, a.published_at, a.created_at,
        EXISTS (SELECT 1 FROM model_assessments m WHERE m.article_version_id = a.current_version_id
                AND m.status = 'SUCCEEDED') AS assessed FROM articles a""")
    memberships = await rows(session, """
        SELECT i.id AS issue_id, a.id AS article_id
        FROM issues i JOIN issue_memberships im ON im.issue_id = i.id
        JOIN articles a ON a.id = im.article_id
        JOIN article_versions av ON av.id = a.current_version_id AND av.article_id = a.id
        JOIN sources s ON s.id = a.source_id
        WHERE i.status = 'active' AND i.issue_kind = 'EVENT'
          AND i.editorial_key LIKE 'daily-issue:%' AND i.topic IN ('정치','경제','사회')
          AND LENGTH(TRIM(i.summary)) > 0 AND a.status = 'active'
          AND s.active = 1 AND s.policy_status = 'approved'
        ORDER BY i.editorial_priority IS NULL, i.editorial_priority, i.id
    """)
    groups: dict[str, dict] = {}
    for member in memberships:
        groups.setdefault(member["issue_id"], {"article_ids": []})["article_ids"].append(member["article_id"])
    return inventory_plan(articles, now, list(groups.values())[:5])


async def delete_batch(session, ids: set[str], now: datetime, *, online: bool = False) -> dict:
    versions = list((await in_query(session,
        "SELECT id, normalized_text_ref FROM article_versions WHERE article_id IN :ids", ids)).mappings())
    version_ids = {v["id"] for v in versions}
    blobs = {v["normalized_text_ref"] for v in versions if v["normalized_text_ref"]}
    issues = set((await in_query(session, "SELECT DISTINCT issue_id FROM issue_memberships WHERE article_id IN :ids", ids)).scalars())
    refs = ids | version_ids
    snapshot_ids = set()
    if issues:
        snapshots = await in_query(session, "SELECT id, article_frames_json FROM issue_comparison_snapshots WHERE issue_id IN :ids", issues)
        for snapshot in snapshots.mappings():
            if strings(snapshot["article_frames_json"]) & refs:
                snapshot_ids.add(snapshot["id"])
    job_ids = set()
    # Stream JSON to avoid loading the entire job history into worker memory.
    stream = await session.stream(text("SELECT id, job_type, payload_json, status, lease_expires_at FROM jobs"), execution_options={"yield_per": 50})
    async for job in stream.mappings():
        if job["job_type"] in {"crawl", "analyze", "cluster", "calculate_score", "aggregate_votes", "build_issue_comparison", "merge_issue", "split_issue"}:
            if strings(job["payload_json"]) & refs:
                if not online and job["status"] == "LEASED" and (not job["lease_expires_at"] or utc(job["lease_expires_at"]) > now):
                    raise RuntimeError("referencing job is leased; stop writers and retry after its lease expires")
                job_ids.add(job["id"])
    await stream.close()
    # Record minimal URL hashes before deletion; no article body is retained.
    await in_query(session,
        "INSERT INTO article_retention_tombstones (canonical_url_hash, retired_at) "
        "SELECT canonical_url_hash, CURRENT_TIMESTAMP FROM articles WHERE id IN :ids "
        "AND NOT EXISTS (SELECT 1 FROM article_retention_tombstones t "
        "WHERE t.canonical_url_hash = articles.canonical_url_hash)", ids)
    if job_ids:
        await in_query(session, "DELETE FROM jobs WHERE id IN :ids", job_ids)
    if snapshot_ids:
        await in_query(session, "DELETE FROM issue_comparison_snapshots WHERE id IN :ids", snapshot_ids)
    # Activity and awarded credits survive expiry; they no longer keep the
    # article, its bodies, or its analysis alive through restrictive FKs.
    await in_query(session, "UPDATE read_sessions SET article_key = COALESCE(article_key, article_id), article_id = NULL WHERE article_id IN :ids", ids)
    await in_query(session, "UPDATE votes SET article_id = NULL WHERE article_id IN :ids", ids)
    await in_query(session, "DELETE FROM feed_impressions WHERE article_id IN :ids", ids)
    for table in ("vote_aggregate_snapshots", "fact_check_references", "issue_memberships"):
        await in_query(session, f"DELETE FROM {table} WHERE article_id IN :ids", ids)
    await in_query(session, "UPDATE articles SET current_version_id = NULL WHERE id IN :ids", ids)
    if version_ids:
        for table in ("score_versions", "model_assessments"):
            await in_query(session, f"DELETE FROM {table} WHERE article_version_id IN :ids", version_ids)
        await in_query(session, "DELETE FROM article_versions WHERE id IN :ids", version_ids)
    await in_query(session, "DELETE FROM articles WHERE id IN :ids", ids)
    if issues:
        await in_query(session,
            "DELETE FROM issue_comparison_snapshots WHERE issue_id IN :ids "
            "AND NOT EXISTS (SELECT 1 FROM issue_memberships m WHERE m.issue_id = issue_comparison_snapshots.issue_id)", issues)
        await in_query(session,
            "UPDATE issues SET status = 'archived' WHERE id IN :ids "
            "AND NOT EXISTS (SELECT 1 FROM issue_memberships m WHERE m.issue_id = issues.id)", issues)
    deleted_blobs = 0
    if blobs:
        result = await in_query(session,
            "DELETE FROM stored_blobs WHERE id IN :ids "
            "AND NOT EXISTS (SELECT 1 FROM article_versions v WHERE v.normalized_text_ref = stored_blobs.id) "
            "AND NOT EXISTS (SELECT 1 FROM share_cards s WHERE s.blob_id = stored_blobs.id)", blobs)
        deleted_blobs = result.rowcount
    return {"articles": len(ids), "versions": len(versions), "blobs": deleted_blobs, "jobs": len(job_ids)}


async def enforce_inventory(session, now: datetime, *, lock: bool = True) -> dict:
    """Trim in the caller's transaction; the caller owns commit and rollback."""
    if lock:
        await lock_inventory(session)
    current = await plan(session, now)
    totals = {"articles": 0, "versions": 0, "blobs": 0, "jobs": 0}
    for offset in range(0, len(current["article_ids"]), 100):
        result = await delete_batch(session, set(current["article_ids"][offset:offset + 100]), now, online=True)
        for key, value in result.items():
            totals[key] += value
    return totals


async def ensure_current_inventory(session, now: datetime) -> None:
    """Cheap expiry fence used before API requests and by the expiry daemon."""
    summary = (await session.execute(text("""SELECT COUNT(*) AS n,
        MIN(LEAST(COALESCE(published_at, created_at), created_at)) AS oldest
        FROM articles"""))).mappings().one()
    if summary["n"] > MAX_ARTICLES or expired(summary["oldest"], summary["oldest"], now):
        await enforce_inventory(session, now)


async def watch() -> None:
    engine = create_engine()
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        while True:
            async with factory() as session, session.begin():
                await ensure_current_inventory(session, datetime.now(UTC))
            await asyncio.sleep(1)
    finally:
        await dispose_engine()


async def run(*, apply: bool = False, check: bool = False) -> dict:
    engine = create_engine()
    now = datetime.now(UTC)
    totals = {"articles": 0, "versions": 0, "blobs": 0, "jobs": 0}
    try:
        async with engine.connect() as connection, async_sessionmaker(connection, expire_on_commit=False)() as session:
            # Connection-scoped lock also excludes a concurrently started timer.
            locked = (await session.execute(text("SELECT GET_LOCK('effica-article-retention', 0)"))).scalar()
            if locked != 1:
                raise RuntimeError("another retention run is active")
            try:
                initial = await plan(session, now)
                await session.rollback()
                if check and initial["article_ids"]:
                    try:
                        await delete_batch(session, set(initial["article_ids"][:100]), now)
                    finally:
                        await session.rollback()
                    verified = await plan(session, now)
                    if verified != initial:
                        raise RuntimeError("rollback check changed the retention plan")
                    await session.rollback()
                if apply:
                    async with session.begin():
                        totals = await enforce_inventory(session, datetime.now(UTC))
                    final = await plan(session, now)
                else:
                    final = initial
                return {"applied": apply, "rollback_checked": check, "before": initial, "after": final, "deleted": totals}
            finally:
                await session.execute(text("SELECT RELEASE_LOCK('effica-article-retention')"))
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true", help="exercise one deletion batch then roll it back")
    parser.add_argument("--watch", action="store_true", help="continuously expire articles while writers are online")
    args = parser.parse_args()
    if args.watch:
        asyncio.run(watch())
        return
    if (args.apply or args.check) and os.environ.get("ARTICLE_RETENTION_WRITERS_STOPPED") != "1":
        parser.error("apply/check must run through the maintenance service with writers stopped")
    result = asyncio.run(run(apply=args.apply, check=args.check))
    # The operational log contains counts, not identifiers or user content.
    for key in ("before", "after"):
        result[key].pop("article_ids", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
