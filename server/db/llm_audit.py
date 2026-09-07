"""Read-only LLM workload audit. Run with ``.ops/run.sh llm-audit``."""

from __future__ import annotations

import asyncio
import difflib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.app.db.session import create_engine, dispose_engine
from apps.worker.worker.comparison_cohort import COMPARISON_ARTICLES_SQL, select_comparison_cohort
from apps.worker.worker.queue import MariaDBQueueRepository


def _body(value: object) -> str:
    return bytes(value).decode("utf-8", errors="replace") if isinstance(value, (bytes, bytearray)) else str(value or "")


def _diff(before: str, after: str) -> dict:
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    changes = []
    for kind, a, b, c, d in matcher.get_opcodes():
        if kind == "equal":
            continue
        old, new = before[a:b], after[c:d]
        # No article body or personal information is copied to the report.
        # Numeric-only deltas and recognized page-counter labels are safe evidence.
        context = before[max(0, a - 40):b + 40] + after[max(0, c - 40):d + 40]
        labels = [label for label in ("조회수", "조회", "추천", "댓글", "첨부", "다운로드") if label in context]
        numeric = bool(re.fullmatch(r"[\d\s,.:/%+-]*", old + new))
        changes.append({"kind": kind, "before_chars": len(old), "after_chars": len(new),
                        "numeric_only": numeric, "nearby_labels": labels,
                        "before_numeric": old[:40] if numeric else None,
                        "after_numeric": new[:40] if numeric else None})
    return {"before_chars": len(before), "after_chars": len(after),
            "similarity": round(matcher.ratio(), 6), "changed_regions": len(changes),
            "all_changes_numeric": all(change["numeric_only"] for change in changes),
            "changes": changes[:15]}


async def main() -> None:
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    start = datetime.combine(today - timedelta(days=2), datetime.min.time(), ZoneInfo("Asia/Seoul")).astimezone(UTC).replace(tzinfo=None)
    engine = create_engine()
    report = {"audited_at_utc": now.isoformat(), "window_start_utc": str(start),
              "caveats": ["Assessment rows and job attempts are not verified API request counts.",
                          "Historical retention can remove prior jobs, versions and assessments.",
                          "2026-09-06 ledger was deliberately seeded to its limit; it is not measured daily spend.",
                          "Body differences are sampled from retained adjacent versions, not all historic versions."]}
    try:
        async with async_sessionmaker(engine)() as session:
            async def rows(query: str, **params) -> list[dict]:
                if not query.lstrip().upper().startswith("SELECT"):
                    raise ValueError("audit permits SELECT queries only")
                result = await session.execute(text(query), params)
                return [dict(row) for row in result.mappings()]

            report["revision"] = await rows("SELECT version_num FROM alembic_version")
            report["assessments_by_day"] = await rows("""
                SELECT DATE(DATE_ADD(ma.created_at, INTERVAL 9 HOUR)) AS kst_day,
                    COUNT(*) AS assessment_rows, COUNT(DISTINCT av.article_id) AS distinct_articles,
                    COUNT(DISTINCT ma.article_version_id) AS assessed_versions,
                    SUM(COALESCE(ma.token_usage, 0)) AS recorded_tokens,
                    MAX(ma.created_at) AS latest_assessment_utc
                FROM model_assessments ma JOIN article_versions av ON av.id=ma.article_version_id
                WHERE ma.created_at >= :start AND ma.status='SUCCEEDED'
                GROUP BY kst_day ORDER BY kst_day
            """, start=start)
            report["jobs_by_day"] = await rows("""
                SELECT DATE(DATE_ADD(created_at, INTERVAL 9 HOUR)) AS kst_day,
                    job_type, status, COUNT(*) AS job_rows, SUM(attempts) AS execution_attempts
                FROM jobs WHERE created_at >= :start
                    AND job_type IN ('analyze', 'build_issue_comparison')
                GROUP BY kst_day, job_type, status ORDER BY kst_day, job_type, status
            """, start=start)
            report["article_versions_by_day"] = await rows("""
                SELECT DATE(DATE_ADD(fetched_at, INTERVAL 9 HOUR)) AS kst_day,
                    COUNT(*) AS version_rows, COUNT(DISTINCT article_id) AS distinct_articles
                FROM article_versions WHERE fetched_at >= :start GROUP BY kst_day ORDER BY kst_day
            """, start=start)
            comparison_jobs = await rows("""
                SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.issue_id')) AS issue_id,
                    JSON_EXTRACT(payload_json, '$.article_version_ids') AS version_ids,
                    JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.issue_version')) AS issue_version,
                    JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.prompt_version')) AS prompt_version,
                    attempts, status
                FROM jobs WHERE created_at >= :start AND job_type='build_issue_comparison'
            """, start=start)
            comparison_groups = defaultdict(list)
            for job in comparison_jobs:
                version_ids = job["version_ids"]
                if isinstance(version_ids, str):
                    version_ids = json.loads(version_ids)
                if not isinstance(version_ids, list):
                    continue
                key = (job["issue_id"], tuple(sorted(str(value) for value in version_ids)), job["prompt_version"])
                comparison_groups[key].append(job)
            repeated = []
            for (issue_id, versions, prompt), jobs in comparison_groups.items():
                if len(jobs) < 2:
                    continue
                repeated.append({"issue_id": issue_id, "article_version_ids": versions,
                                 "prompt_version": prompt, "job_rows": len(jobs),
                                 "distinct_issue_versions": len({job["issue_version"] for job in jobs}),
                                 "execution_attempts": sum(job["attempts"] for job in jobs)})
            report["comparison_repeated_inputs"] = {
                "repeated_groups": len(repeated),
                "jobs_in_repeated_groups": sum(group["job_rows"] for group in repeated),
                "largest_groups": sorted(repeated, key=lambda group: group["job_rows"], reverse=True)[:8]}
            report["most_reanalyzed_articles"] = await rows("""
                SELECT a.id AS article_id, a.title, s.name AS source_name,
                    COUNT(*) AS assessment_rows, COUNT(DISTINCT av.id) AS assessed_versions,
                    SUM(COALESCE(ma.token_usage,0)) AS recorded_tokens,
                    MIN(ma.created_at) AS first_assessment_utc, MAX(ma.created_at) AS latest_assessment_utc
                FROM model_assessments ma JOIN article_versions av ON av.id=ma.article_version_id
                JOIN articles a ON a.id=av.article_id JOIN sources s ON s.id=a.source_id
                WHERE ma.created_at >= :start AND ma.status='SUCCEEDED'
                GROUP BY a.id, a.title, s.name ORDER BY assessment_rows DESC LIMIT 15
            """, start=start)
            report["runtime_control"] = await rows("SELECT id, llm_enabled, version, updated_at FROM runtime_controls")
            events = await rows("""
                SELECT id, title FROM issues WHERE issue_kind='EVENT' AND status='active'
                  AND last_activity_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 4 DAY)
                ORDER BY editorial_priority IS NULL, editorial_priority, id
            """)
            report["essential_event_inputs"] = []
            for event in events:
                candidates = await rows(COMPARISON_ARTICLES_SQL, issue_id=event["id"])
                cohort = select_comparison_cohort(candidates)
                report["essential_event_inputs"].append({
                    **event, "candidate_articles": len(candidates),
                    "selected_articles": [{"article_id": row["article_id"],
                                           "source": row["source_name"], "title": row["title"]}
                                          for row in cohort],
                })
            claim_order = MariaDBQueueRepository(lambda: None)._claim_order()
            report["next_work_under_essential_priority"] = await rows(f"""
                SELECT id, job_type, priority FROM jobs
                WHERE status='PENDING' AND available_at <= :now
                ORDER BY {claim_order} LIMIT 10
            """, now=now.replace(tzinfo=None))
            report["ledger"] = await rows("SELECT * FROM llm_daily_usage WHERE usage_date >= :start ORDER BY usage_date", start=start.date())
            report["active_models"] = await rows("""
                SELECT alias, provider, actual_model_id, status,
                    JSON_UNQUOTE(JSON_EXTRACT(config_json, '$.reasoning_effort')) AS reasoning_effort
                FROM model_aliases WHERE status='active'
            """)
            report["assessments_since_emergency_reenable"] = await rows("""
                SELECT COUNT(*) AS assessment_rows, MAX(created_at) AS latest_assessment_utc,
                    SUM(COALESCE(token_usage, 0)) AS recorded_tokens
                FROM model_assessments WHERE created_at >= '2026-09-06 12:48:00'
                    AND status='SUCCEEDED'
            """)
            cache_exists = await rows("SELECT COUNT(*) AS present FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='llm_requests'")
            if cache_exists[0]["present"]:
                report["durable_requests"] = await rows("""
                    SELECT usage_date, category, state, COUNT(*) AS request_rows,
                        COUNT(DISTINCT subject_key) AS distinct_subjects
                    FROM llm_requests GROUP BY usage_date, category, state
                    ORDER BY usage_date DESC LIMIT 30
                """)
                report["daily_paid_article_cohort"] = await rows("""
                    SELECT usage_date, COUNT(*) AS distinct_articles
                    FROM llm_daily_articles GROUP BY usage_date
                    ORDER BY usage_date DESC LIMIT 30
                """)
            else:
                report["durable_requests"] = "not installed in this database revision"
            government = await rows("""
                SELECT article_id, title, source_name, retained_versions FROM (
                    SELECT a.id AS article_id, a.title, s.name AS source_name,
                        COUNT(*) AS retained_versions,
                        ROW_NUMBER() OVER (PARTITION BY s.id ORDER BY COUNT(*) DESC, a.id) AS rank_in_source
                    FROM article_versions av JOIN articles a ON a.id=av.article_id
                    JOIN sources s ON s.id=a.source_id
                    WHERE a.canonical_url LIKE '%mss.go.kr%' OR a.canonical_url LIKE '%fsc.go.kr%'
                    GROUP BY a.id, a.title, s.id, s.name HAVING COUNT(*) > 1
                ) ranked WHERE rank_in_source <= 3 ORDER BY source_name, rank_in_source
            """)
            samples = []
            for article in government:
                versions = await rows("""
                    SELECT av.id, av.fetched_at, HEX(av.content_hash) AS content_hash, b.payload
                    FROM article_versions av LEFT JOIN stored_blobs b ON b.id=av.normalized_text_ref
                    WHERE av.article_id=:article ORDER BY av.fetched_at DESC, av.id DESC LIMIT 3
                """, article=article["article_id"])
                versions.reverse()
                differences = []
                for before, after in zip(versions, versions[1:], strict=False):
                    differences.append({"before_version": before["id"], "after_version": after["id"],
                                        "before_time_utc": before["fetched_at"], "after_time_utc": after["fetched_at"],
                                        "before_hash": before["content_hash"], "after_hash": after["content_hash"],
                                        **_diff(_body(before["payload"]), _body(after["payload"]))})
                samples.append({**article, "adjacent_differences": differences})
            report["government_body_samples"] = samples
            await session.rollback()
    finally:
        await dispose_engine()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
