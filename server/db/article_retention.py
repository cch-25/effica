"""Preview or apply content retention while API and worker writers are stopped.

Only article-owned blobs are collected. User exports and unrelated artifacts
are never swept. References inside share snapshots and credit event keys are
protected as well as ordinary foreign keys. Each batch is independently atomic.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.app.db.session import create_engine, dispose_engine
from apps.api.app.domains.content.retention import RETENTION_DAYS, expired, utc


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


async def plan(session, now: datetime) -> dict:
    articles = await rows(session, "SELECT id, canonical_url_hash, published_at, created_at FROM articles")
    stale = {a["id"]: a for a in articles if expired(a["published_at"], a["created_at"], now)}
    protected = set()
    for table in ("votes", "read_sessions", "feed_impressions"):
        where = " WHERE user_id IS NOT NULL" if table == "feed_impressions" else ""
        protected.update(r["article_id"] for r in await rows(session, f"SELECT DISTINCT article_id FROM {table}{where}"))
    refs = set()
    for card in await rows(session, "SELECT snapshot_json FROM share_cards"):
        refs.update(strings(card["snapshot_json"]))
    for item in await rows(session, "SELECT event_key FROM credit_ledger"):
        refs.update(strings(item["event_key"]))
    # event_key can contain a namespaced article ID, not just the ID itself.
    protected.update(a for a in stale if any(a in ref for ref in refs))
    memberships = await rows(session, "SELECT issue_id, article_id FROM issue_memberships")
    protected.update(m["article_id"] for m in memberships if m["issue_id"] in refs)
    protected.update(v["article_id"] for v in await rows(session, "SELECT id, article_id FROM article_versions") if v["id"] in refs)
    targets = set(stale) - protected
    return {
        "checked_at": now.isoformat(),
        "cutoff": (now - timedelta(days=RETENTION_DAYS)).isoformat(),
        "total": len(articles), "expired": len(stale),
        "protected_expired": len(set(stale) & protected),
        "delete_count": len(targets), "remaining": len(articles) - len(targets),
        "article_ids": sorted(targets),
    }


async def delete_batch(session, ids: set[str], now: datetime) -> dict:
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
                if job["status"] == "LEASED" and (not job["lease_expires_at"] or utc(job["lease_expires_at"]) > now):
                    raise RuntimeError("referencing job is leased; stop writers and retry after its lease expires")
                job_ids.add(job["id"])
    await stream.close()
    # Record minimal URL hashes before deletion; no article body is retained.
    await in_query(session,
        "INSERT INTO article_retention_tombstones (canonical_url_hash, retired_at) "
        "SELECT canonical_url_hash, CURRENT_TIMESTAMP FROM articles WHERE id IN :ids", ids)
    if job_ids:
        await in_query(session, "DELETE FROM jobs WHERE id IN :ids", job_ids)
    if snapshot_ids:
        await in_query(session, "DELETE FROM issue_comparison_snapshots WHERE id IN :ids", snapshot_ids)
    await in_query(session, "DELETE FROM feed_impressions WHERE user_id IS NULL AND article_id IN :ids", ids)
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
                    for offset in range(0, len(initial["article_ids"]), 100):
                        async with session.begin():
                            # Re-check user references before each atomic batch.
                            current = await plan(session, now)
                            ids = set(initial["article_ids"][offset:offset + 100]) & set(current["article_ids"])
                            if ids:
                                result = await delete_batch(session, ids, now)
                                for key, value in result.items():
                                    totals[key] += value
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
    args = parser.parse_args()
    if (args.apply or args.check) and os.environ.get("ARTICLE_RETENTION_WRITERS_STOPPED") != "1":
        parser.error("apply/check must run through the maintenance service with writers stopped")
    result = asyncio.run(run(apply=args.apply, check=args.check))
    # The operational log contains counts, not identifiers or user content.
    for key in ("before", "after"):
        result[key].pop("article_ids", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
