"""Keep only site data and bounded replay metadata, alongside article retention."""
from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.app.db.session import create_engine, dispose_engine
from apps.api.app.domains.content.storage import compact_job_payload
from db.article_retention import in_query, rows, strings
from db.article_retention import run as retain_articles


async def compact(session) -> dict[str, int]:
    counts: dict[str, int] = {}
    async def execute(name, query, **params):
        result = await session.execute(text(query), params)
        counts[name] = result.rowcount

    await execute("impressions", "DELETE FROM feed_impressions")

    # Keep the latest reviewed comparison plus the latest candidate per issue.
    # Older generated comparisons duplicate both article frames and summaries.
    kept_comparisons: dict[str, set[str]] = defaultdict(set)
    snapshot_ids = set()
    protected_versions = set()
    stream = await session.stream(text(
        "SELECT s.id, s.issue_id, s.status, s.reviewed_at, s.article_frames_json, "
        "s.issue_version, i.version, i.status AS issue_status "
        "FROM issue_comparison_snapshots s JOIN issues i ON i.id=s.issue_id "
        "ORDER BY s.created_at DESC, s.id DESC"), execution_options={"yield_per": 25})
    async for snapshot in stream.mappings():
        bucket = "reviewed" if snapshot["reviewed_at"] else "candidate"
        valid = snapshot["status"] in {"SUCCEEDED", "PENDING"} and snapshot["issue_version"] == snapshot["version"] and snapshot["issue_status"] not in {"archived", "closed", "merged"}
        if not valid or bucket in kept_comparisons[snapshot["issue_id"]]:
            snapshot_ids.add(snapshot["id"])
        else:
            kept_comparisons[snapshot["issue_id"]].add(bucket)
            protected_versions.update(strings(snapshot["article_frames_json"]))
    await stream.close()
    if snapshot_ids:
        result = await in_query(session, "DELETE FROM issue_comparison_snapshots WHERE id IN :ids", snapshot_ids)
        counts["comparisons"] = result.rowcount

    # A small history supports the score-history view. Current and publicly
    # referenced versions always survive regardless of the history count.
    protected_versions.update(r["current_version_id"] for r in await rows(session, "SELECT current_version_id FROM articles") if r["current_version_id"])
    for card in await rows(session, "SELECT snapshot_json FROM share_cards"):
        protected_versions.update(strings(card["snapshot_json"]))
    versions = await rows(session, "SELECT id, article_id FROM article_versions ORDER BY fetched_at DESC, id DESC")
    history = defaultdict(int)
    remove_versions = set()
    for version in versions:
        if version["id"] in protected_versions:
            continue
        history[version["article_id"]] += 1
        if history[version["article_id"]] > 2:
            remove_versions.add(version["id"])

    job_ids = set()
    if remove_versions:
        stream = await session.stream(text("SELECT id, payload_json FROM jobs"), execution_options={"yield_per": 50})
        async for job in stream.mappings():
            if strings(job["payload_json"]) & remove_versions:
                job_ids.add(job["id"])
        await stream.close()
        if job_ids:
            await in_query(session, "DELETE FROM jobs WHERE id IN :ids", job_ids)
        for table in ("score_versions", "model_assessments"):
            await in_query(session, f"DELETE FROM {table} WHERE article_version_id IN :ids", remove_versions)
        result = await in_query(session, "DELETE FROM article_versions WHERE id IN :ids", remove_versions)
        counts["versions"] = result.rowcount

    await execute("superseded_scores", "DELETE FROM score_versions WHERE status = 'superseded'")
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    await execute("finished_jobs", "DELETE FROM jobs WHERE status NOT IN ('PENDING','LEASED') AND updated_at < :cutoff", cutoff=cutoff)
    await execute("crawl_history", "DELETE FROM crawl_runs WHERE status NOT IN ('PENDING','RUNNING') AND finished_at < :cutoff", cutoff=cutoff)
    await execute("admin_receipts", "DELETE FROM admin_request_receipts WHERE created_at < :cutoff", cutoff=cutoff)
    await execute("expired_sessions", "DELETE FROM sessions WHERE expires_at < :now", now=datetime.now(UTC).replace(tzinfo=None))
    for job in await rows(session, "SELECT id, payload_json FROM jobs WHERE status NOT IN ('PENDING','LEASED')"):
        payload = json.loads(job["payload_json"]) if isinstance(job["payload_json"], str) else job["payload_json"]
        lean = compact_job_payload(payload)
        if lean != payload:
            await session.execute(text("UPDATE jobs SET payload_json=:payload WHERE id=:id"), {"id": job["id"], "payload": json.dumps(lean)})

    # Job receipts preserve live export pointers. All other artifacts must be
    # referenced by the actual site data, not by historical debug payloads.
    await execute("unused_blobs", """DELETE FROM stored_blobs
        WHERE NOT EXISTS (SELECT 1 FROM article_versions v WHERE v.normalized_text_ref=stored_blobs.id)
        AND NOT EXISTS (SELECT 1 FROM share_cards s WHERE s.blob_id=stored_blobs.id)
        AND NOT EXISTS (SELECT 1 FROM job_receipts r WHERE JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.blob_id'))=stored_blobs.id)""")
    return counts


async def main() -> None:
    if os.environ.get("ARTICLE_RETENTION_WRITERS_STOPPED") != "1":
        raise RuntimeError("storage maintenance requires stopped API/worker writers")
    result = await retain_articles(apply=True)
    for key in ("before", "after"):
        result[key].pop("article_ids", None)
    engine = create_engine()
    try:
        async with async_sessionmaker(engine)() as session:
            async with session.begin():
                result["storage_removed"] = await compact(session)
    finally:
        await dispose_engine()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
