"""Diagnose and repair incomplete persisted content-pipeline projections.

This module is deliberately an operator-invoked recovery path, not an
application-startup hook.  It never calls a provider or fetches a URL itself;
it repairs safe pointers/statuses and places validated work on the durable
queue for the normal worker to execute.

The recovery generation is part of every new dedupe key.  Re-running one
generation is idempotent, while a later generation can retry work whose old
canonical queue key is permanently occupied by a terminal row.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.app.core.config import get_settings
from apps.api.app.db.enums import (
    AdapterType,
    ArticleStatus,
    CrawlStatus,
    IssueKind,
    IssueStatus,
    JobStatus,
    ModelStatus,
    ScoreStatus,
    SourcePolicyStatus,
    SourceType,
)
from apps.api.app.db.models import (
    Article,
    ArticleVersion,
    AuditLog,
    CrawlRun,
    Issue,
    IssueMembership,
    Job,
    ModelAlias,
    ModelAssessment,
    ScoreVersion,
    Source,
    SourceAdapter,
    StoredBlob,
    WeightProfileRevision,
)
from apps.api.app.db.session import create_engine, dispose_engine
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.domains.content.trust import (
    is_trusted_openai_assessment,
    score_matches_trusted_assessments,
)
from apps.api.app.domains.issues.topics import (
    PUBLIC_ISSUE_TOPICS,
    canonical_topic_editorial_key,
    canonical_topic_issue_id,
    infer_issue_topic,
    normalize_issue_topic,
)
from apps.api.app.jobs.payloads import validate_job_payload
from db.seeds.source_feeds import (
    bootstrap_scheduled_rss_sources,
    scheduled_rss_config,
)

_ACTIVE_JOB_STATUSES = frozenset({JobStatus.PENDING.value, JobStatus.LEASED.value})
_RETRYABLE_JOB_STATUSES = frozenset(
    {JobStatus.FAILED.value, JobStatus.DEAD.value, JobStatus.CANCELLED.value}
)
_GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def default_recovery_generation(today: date | None = None) -> str:
    """Return a daily generation suitable for unattended operator reruns."""

    return (today or utc_now().date()).isoformat()


def validate_recovery_generation(value: str) -> str:
    generation = str(value or "").strip()
    if not _GENERATION_RE.fullmatch(generation):
        raise ValueError(
            "recovery generation must contain 1-64 letters, numbers, '.', '_', ':' or '-'"
        )
    return generation


def _value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _status(job: Job) -> str:
    return _value(job.status)


def _job_payload_identifier(job: Job, field: str) -> str | None:
    value = (job.payload_json or {}).get(field)
    return None if value in (None, "") else str(value)


def _new_report(*, generation: str, dry_run: bool) -> dict[str, Any]:
    return {
        "generation": generation,
        "dry_run": dry_run,
        "diagnostics": {
            "active_sources": 0,
            "approved_policy_sources": 0,
            "active_adapters": 0,
            "active_adapter_types": {},
            "duplicate_source_plans": [],
            "active_openai_aliases_before": [],
            "selected_active_openai_alias": None,
            "scheduled_rss_adapter_plans": [],
            "scheduled_rss_source_plans": [],
            "legacy_candidate_topic_issues": 0,
            "legacy_active_topic_collections": 0,
            "canonical_topic_collections": 0,
            "articles": 0,
            "article_versions": 0,
            "orphan_article_versions": 0,
            "orphan_assessments": 0,
            "orphan_scores": 0,
            "current_version_missing": 0,
            "current_version_cross_linked": 0,
            "current_version_stale": 0,
            "current_body_missing": 0,
            "metadata_only_articles": 0,
            "homepage_placeholder_articles": 0,
            "unscheduled_periodic_crawl_jobs": 0,
            "redundant_analysis_jobs": 0,
            "stale_comparison_jobs": 0,
            "recoverable_comparison_jobs": 0,
            "trusted_assessment_missing": 0,
            "matching_active_score_missing": 0,
            "job_counts": {},
            "sources": [],
        },
        "actions": {
            "version_pointers_repaired": 0,
            "duplicate_sources_merged": 0,
            "source_articles_reassigned": 0,
            "source_crawl_runs_reassigned": 0,
            "draft_scores_promoted": 0,
            "invalid_active_scores_superseded": 0,
            "analysis_jobs_enqueued": 0,
            "analysis_jobs_requeued": 0,
            "score_jobs_enqueued": 0,
            "score_jobs_requeued": 0,
            "crawl_jobs_enqueued": 0,
            "crawl_jobs_requeued": 0,
            "cluster_jobs_enqueued": 0,
            "cluster_jobs_requeued": 0,
            "scheduled_rss_adapters_upserted": 0,
            "scheduled_rss_sources_bootstrapped": 0,
            "legacy_candidate_topic_issues_archived": 0,
            "legacy_active_topic_collections_archived": 0,
            "canonical_topic_collections_upserted": 0,
            "topic_memberships_upserted": 0,
            "openai_aliases_deprecated": 0,
            "homepage_placeholder_articles_blocked": 0,
            "unscheduled_periodic_crawl_jobs_cancelled": 0,
            "redundant_analysis_jobs_cancelled": 0,
            "stale_comparison_jobs_cancelled": 0,
            "comparison_jobs_requeued": 0,
            "audit_rows_written": 0,
        },
        "deferred": {
            "articles_without_versions": 0,
            "articles_without_body": 0,
            "analysis_work_in_progress": 0,
            "score_work_in_progress": 0,
            "crawl_work_in_progress": 0,
            "unscheduled_periodic_crawl_work_in_progress": 0,
            "redundant_analysis_work_in_progress": 0,
            "stale_comparison_work_in_progress": 0,
            "cluster_work_in_progress": 0,
            "score_blocked_no_active_weight": 0,
            "crawl_blocked_no_adapter": 0,
            "crawl_blocked_policy": 0,
            "generation_already_succeeded": 0,
            "ambiguous_duplicate_sources": 0,
        },
    }


async def _ensure_job(
    session: AsyncSession,
    *,
    jobs: list[Job],
    exact_jobs: dict[tuple[str, str], Job],
    job_type: str,
    dedupe_key: str,
    payload: Mapping[str, Any],
    dry_run: bool,
    crawl_source_id: str | None = None,
) -> str:
    """Plan or create one recovery job and return its disposition.

    A SUCCEEDED job is never silently rerun inside the same generation.  If
    its expected projection is still absent, the report tells the operator to
    use a new generation.  Failed/dead/cancelled rows are safe to reset because
    the missing projection proves the earlier attempt did not finish the
    requested recovery.
    """

    validated = validate_job_payload(job_type, payload)
    existing = exact_jobs.get((job_type, dedupe_key))
    if existing is not None:
        state = _status(existing)
        if state in _ACTIVE_JOB_STATUSES:
            return "in_progress"
        if state == JobStatus.SUCCEEDED.value:
            return "generation_succeeded"
        if state not in _RETRYABLE_JOB_STATUSES:
            return "in_progress"
        if not dry_run:
            existing.status = JobStatus.PENDING
            existing.attempts = 0
            existing.available_at = utc_now()
            existing.lease_owner = None
            existing.lease_expires_at = None
            existing.last_error_json = None
            existing.updated_at = utc_now()
            if job_type == "crawl":
                run = await session.get(CrawlRun, existing.id)
                if run is not None:
                    run.status = CrawlStatus.PENDING
                    run.started_at = None
                    run.finished_at = None
                    run.error_json = None
        return "requeued"

    row = Job(
        id=new_ulid(),
        job_type=job_type,
        dedupe_key=dedupe_key,
        status=JobStatus.PENDING,
        priority=10,
        available_at=utc_now(),
        lease_owner=None,
        lease_expires_at=None,
        attempts=0,
        max_attempts=5,
        payload_json=dict(validated),
        last_error_json=None,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    if not dry_run:
        session.add(row)
        if job_type == "crawl" and crawl_source_id is not None:
            session.add(
                CrawlRun(
                    id=row.id,
                    source_id=crawl_source_id,
                    status=CrawlStatus.PENDING,
                    started_at=None,
                    finished_at=None,
                    stats_json=None,
                    error_json=None,
                )
            )
    jobs.append(row)
    exact_jobs[(job_type, dedupe_key)] = row
    return "enqueued"


def _record_job_disposition(
    report: dict[str, Any], *, prefix: str, disposition: str
) -> None:
    if disposition in {"enqueued", "requeued"}:
        report["actions"][f"{prefix}_jobs_{disposition}"] += 1
    elif disposition == "in_progress":
        report["deferred"][f"{prefix}_work_in_progress"] += 1
    elif disposition == "generation_succeeded":
        report["deferred"]["generation_already_succeeded"] += 1


async def recover_pipeline(
    session: AsyncSession,
    *,
    generation: str,
    dry_run: bool = True,
    bootstrap_sources: bool = False,
) -> dict[str, Any]:
    """Inspect the whole persisted content graph and repair safe gaps.

    The caller owns the surrounding transaction.  ``dry_run`` performs no ORM
    mutations at all, making it safe to call through a read-only transaction.
    """

    generation = validate_recovery_generation(generation)
    report = _new_report(generation=generation, dry_run=dry_run)
    diagnostics = report["diagnostics"]
    actions = report["actions"]
    deferred = report["deferred"]

    sources = list((await session.scalars(select(Source).order_by(Source.id))).all())
    adapters = list(
        (
            await session.scalars(
                select(SourceAdapter).where(SourceAdapter.active.is_(True)).order_by(SourceAdapter.id)
            )
        ).all()
    )
    if bootstrap_sources:
        sources_by_url = {
            source.canonical_url.rstrip("/").casefold(): source for source in sources
        }
        for spec in bootstrap_scheduled_rss_sources():
            key = spec.home_url.rstrip("/").casefold()
            source = sources_by_url.get(key)
            if source is not None:
                approved = all(
                    _value(value) == SourcePolicyStatus.APPROVED.value
                    for value in (
                        source.policy_status,
                        source.robots_status,
                        source.terms_status,
                    )
                )
                diagnostics["scheduled_rss_source_plans"].append(
                    {
                        "source_id": source.id,
                        "source": source.name,
                        "home_url": spec.home_url,
                        "action": "NONE" if source.active and approved else "REVIEW_REQUIRED",
                    }
                )
                continue
            diagnostics["scheduled_rss_source_plans"].append(
                {
                    "source_id": None,
                    "source": spec.name,
                    "home_url": spec.home_url,
                    "action": "CREATE",
                }
            )
            actions["scheduled_rss_sources_bootstrapped"] += 1
            if dry_run:
                continue
            source = Source(
                id=new_ulid(),
                name=spec.name,
                source_type=SourceType.RSS,
                canonical_url=spec.home_url,
                policy_status=SourcePolicyStatus.APPROVED,
                robots_status=SourcePolicyStatus.APPROVED,
                terms_status=SourcePolicyStatus.APPROVED,
                active=True,
            )
            session.add(source)
            await session.flush()
            sources.append(source)
            sources_by_url[key] = source
    adapters_by_source: dict[str, list[SourceAdapter]] = defaultdict(list)
    for adapter in adapters:
        adapters_by_source[adapter.source_id].append(adapter)
    metadata_only_source_ids = {
        adapter.source_id
        for adapter in adapters
        if bool((adapter.config_json or {}).get("metadata_only"))
    }

    sources_by_name: dict[str, list[Source]] = defaultdict(list)
    for source in sources:
        if source.active:
            sources_by_name[source.name.strip().casefold()].append(source)
    for normalized_name, duplicates in sorted(sources_by_name.items()):
        if not normalized_name or len(duplicates) < 2:
            continue
        canonical_candidates = [
            source
            for source in duplicates
            if _value(source.policy_status) == SourcePolicyStatus.APPROVED.value
            and _value(source.robots_status) == SourcePolicyStatus.APPROVED.value
            and _value(source.terms_status) == SourcePolicyStatus.APPROVED.value
            and adapters_by_source.get(source.id)
        ]
        merge_candidates = [
            source
            for source in duplicates
            if not adapters_by_source.get(source.id)
        ]
        if len(canonical_candidates) != 1 or not merge_candidates:
            deferred["ambiguous_duplicate_sources"] += len(duplicates)
            continue
        canonical = canonical_candidates[0]
        for duplicate in merge_candidates:
            if duplicate.id == canonical.id:
                continue
            article_count = int(
                await session.scalar(
                    select(func.count(Article.id)).where(
                        Article.source_id == duplicate.id
                    )
                )
                or 0
            )
            crawl_run_count = int(
                await session.scalar(
                    select(func.count(CrawlRun.id)).where(
                        CrawlRun.source_id == duplicate.id
                    )
                )
                or 0
            )
            diagnostics["duplicate_source_plans"].append(
                {
                    "name": canonical.name,
                    "canonical_source_id": canonical.id,
                    "duplicate_source_id": duplicate.id,
                    "articles": article_count,
                    "crawl_runs": crawl_run_count,
                    "action": "MERGE",
                }
            )
            actions["duplicate_sources_merged"] += 1
            actions["source_articles_reassigned"] += article_count
            actions["source_crawl_runs_reassigned"] += crawl_run_count
            if not dry_run:
                if article_count:
                    await session.execute(
                        update(Article)
                        .where(Article.source_id == duplicate.id)
                        .values(source_id=canonical.id)
                    )
                if crawl_run_count:
                    await session.execute(
                        update(CrawlRun)
                        .where(CrawlRun.source_id == duplicate.id)
                        .values(source_id=canonical.id)
                    )
                duplicate.active = False

    active_sources = [source for source in sources if source.active]
    diagnostics["active_sources"] = len(active_sources)
    diagnostics["approved_policy_sources"] = sum(
        _value(source.policy_status) == SourcePolicyStatus.APPROVED.value
        for source in active_sources
    )
    diagnostics["active_adapters"] = len(adapters)
    diagnostics["active_adapter_types"] = dict(
        sorted(Counter(_value(adapter.adapter_type) for adapter in adapters).items())
    )
    model_aliases = list(
        (await session.scalars(select(ModelAlias).order_by(ModelAlias.id))).all()
    )
    active_openai_aliases = [
        alias
        for alias in model_aliases
        if alias.provider.casefold() == "openai"
        and alias.actual_model_id.startswith("gpt-")
        and _value(alias.status) == ModelStatus.ACTIVE.value
    ]
    diagnostics["active_openai_aliases_before"] = [
        {
            "id": alias.id,
            "alias": alias.alias,
            "actual_model_id": alias.actual_model_id,
        }
        for alias in active_openai_aliases
    ]
    preferred_alias = next(
        (alias for alias in active_openai_aliases if alias.alias == "openai-default"),
        active_openai_aliases[-1] if active_openai_aliases else None,
    )
    if preferred_alias is not None:
        diagnostics["selected_active_openai_alias"] = preferred_alias.id
        for alias in active_openai_aliases:
            if alias.id == preferred_alias.id:
                continue
            actions["openai_aliases_deprecated"] += 1
            if not dry_run:
                alias.status = ModelStatus.DEPRECATED
    scheduled_refresh_source_ids: set[str] = set()
    for source in active_sources:
        crawler_adapter = next(
            (
                adapter
                for adapter in adapters_by_source.get(source.id, [])
                if _value(adapter.adapter_type) == "CRAWLER"
            ),
            None,
        )
        policy_reference = None
        if crawler_adapter is not None:
            configured_reference = (crawler_adapter.config_json or {}).get(
                "policy_reference"
            )
            if configured_reference:
                policy_reference = str(configured_reference)
        expected_rss = scheduled_rss_config(
            source.canonical_url,
            policy_reference=policy_reference,
        )
        if expected_rss is None:
            continue
        rss_adapter = next(
            (
                adapter
                for adapter in adapters_by_source.get(source.id, [])
                if _value(adapter.adapter_type) == "RSS"
            ),
            None,
        )
        changed = rss_adapter is None or any(
            (
                not rss_adapter.active,
                rss_adapter.rate_limit != 10,
                rss_adapter.raw_payload_retention_days != 7,
                any(
                    (rss_adapter.config_json or {}).get(key) != value
                    for key, value in expected_rss.items()
                )
                if rss_adapter is not None
                else True,
            )
        )
        diagnostics["scheduled_rss_adapter_plans"].append(
            {
                "source_id": source.id,
                "source": source.name,
                "source_type_preserved": _value(source.source_type),
                "feed_url": expected_rss["feed_url"],
                "action": "UPSERT" if changed else "NONE",
            }
        )
        if not changed:
            continue
        scheduled_refresh_source_ids.add(source.id)
        actions["scheduled_rss_adapters_upserted"] += 1
        if not dry_run:
            if rss_adapter is None:
                rss_adapter = SourceAdapter(
                    id=new_ulid(),
                    source_id=source.id,
                    adapter_type=AdapterType.RSS,
                    config_json=expected_rss,
                    rate_limit=10,
                    raw_payload_retention_days=7,
                    active=True,
                )
                session.add(rss_adapter)
                adapters.append(rss_adapter)
                adapters_by_source[source.id].append(rss_adapter)
            else:
                rss_adapter.config_json = {
                    **(rss_adapter.config_json or {}),
                    **expected_rss,
                }
                rss_adapter.rate_limit = 10
                rss_adapter.raw_payload_retention_days = 7
                rss_adapter.active = True

    articles = list((await session.scalars(select(Article).order_by(Article.id))).all())
    article_ids = {article.id for article in articles}
    versions = list(
        (
            await session.scalars(
                select(ArticleVersion).order_by(
                    ArticleVersion.article_id,
                    ArticleVersion.fetched_at.desc(),
                    ArticleVersion.id.desc(),
                )
            )
        ).all()
    )
    versions_by_article: dict[str, list[ArticleVersion]] = defaultdict(list)
    versions_by_id = {version.id: version for version in versions}
    for version in versions:
        versions_by_article[version.article_id].append(version)
    diagnostics["articles"] = len(articles)
    diagnostics["article_versions"] = len(versions)
    diagnostics["orphan_article_versions"] = sum(
        version.article_id not in article_ids for version in versions
    )

    assessments_with_alias = list(
        (
            await session.execute(
                select(ModelAssessment, ModelAlias)
                .join(ModelAlias, ModelAlias.id == ModelAssessment.model_alias_id)
                .order_by(ModelAssessment.created_at.desc(), ModelAssessment.id.desc())
            )
        ).all()
    )
    version_ids = set(versions_by_id)
    diagnostics["orphan_assessments"] = sum(
        assessment.article_version_id not in version_ids
        for assessment, _alias in assessments_with_alias
    )
    trusted_by_version: dict[str, list[tuple[ModelAssessment, ModelAlias]]] = defaultdict(list)
    for assessment, alias in assessments_with_alias:
        if is_trusted_openai_assessment(assessment, alias):
            trusted_by_version[assessment.article_version_id].append((assessment, alias))

    scores = list(
        (
            await session.scalars(
                select(ScoreVersion).order_by(
                    ScoreVersion.article_version_id,
                    ScoreVersion.created_at.desc(),
                    ScoreVersion.id.desc(),
                )
            )
        ).all()
    )
    diagnostics["orphan_scores"] = sum(
        score.article_version_id not in version_ids for score in scores
    )
    scores_by_version: dict[str, list[ScoreVersion]] = defaultdict(list)
    for score in scores:
        scores_by_version[score.article_version_id].append(score)

    body_blob_rows = list(
        (
            await session.execute(
                select(StoredBlob.id, StoredBlob.byte_size).where(
                    StoredBlob.byte_size > 0,
                    (StoredBlob.expires_at.is_(None)) | (StoredBlob.expires_at > utc_now()),
                )
            )
        ).all()
    )
    body_blob_sizes = {str(blob_id): int(byte_size) for blob_id, byte_size in body_blob_rows}
    body_blob_ids = set(body_blob_sizes)

    sources_by_id = {source.id: source for source in sources}
    homepage_placeholder_ids: set[str] = set()
    for article in articles:
        if _value(article.status) != ArticleStatus.ACTIVE.value:
            continue
        source = sources_by_id.get(article.source_id)
        latest = next(iter(versions_by_article.get(article.id, [])), None)
        if source is None or latest is None or latest.normalized_text_ref is None:
            continue
        same_home_url = article.canonical_url.rstrip("/").casefold() == (
            source.canonical_url.rstrip("/").casefold()
        )
        # A source homepage is a discovery surface, never an article URL.
        # Some legacy direct crawls stored the homepage itself with a large
        # navigation body, so body length/title heuristics are insufficient.
        if same_home_url:
            homepage_placeholder_ids.add(article.id)
            if not dry_run:
                article.status = ArticleStatus.BLOCKED
                article.updated_at = utc_now()
    diagnostics["homepage_placeholder_articles"] = len(homepage_placeholder_ids)
    actions["homepage_placeholder_articles_blocked"] = len(homepage_placeholder_ids)
    active_articles = [
        article
        for article in articles
        if _value(article.status) == ArticleStatus.ACTIVE.value
        and article.id not in homepage_placeholder_ids
    ]
    membership_rows = list(
        (await session.scalars(select(IssueMembership).order_by(IssueMembership.issue_id))).all()
    )
    issues = list((await session.scalars(select(Issue).order_by(Issue.id))).all())
    issues_by_id = {issue.id: issue for issue in issues}
    memberships = {
        membership.article_id
        for membership in membership_rows
        if (issue := issues_by_id.get(membership.issue_id)) is not None
        and _value(issue.issue_kind) == IssueKind.EVENT.value
        and _value(issue.status)
        not in {
            IssueStatus.ARCHIVED.value,
            IssueStatus.CLOSED.value,
            IssueStatus.MERGED.value,
        }
    }
    legacy_candidate_topics = [
        issue
        for issue in issues
        if _value(issue.status) == IssueStatus.CANDIDATE.value
        and _value(issue.issue_kind) == IssueKind.TOPIC.value
        and not issue.editorial_key
    ]
    diagnostics["legacy_candidate_topic_issues"] = len(legacy_candidate_topics)
    if bootstrap_sources:
        actions["legacy_candidate_topic_issues_archived"] = len(
            legacy_candidate_topics
        )
        if not dry_run:
            for issue in legacy_candidate_topics:
                issue.status = IssueStatus.ARCHIVED
                issue.version += 1

    canonical_keys = {
        canonical_topic_editorial_key(topic) for topic in PUBLIC_ISSUE_TOPICS
    }
    canonical_by_topic = {
        issue.topic: issue
        for issue in issues
        if issue.editorial_key in canonical_keys
        and issue.topic in PUBLIC_ISSUE_TOPICS
    }
    legacy_active_topics = [
        issue
        for issue in issues
        if _value(issue.status) == IssueStatus.ACTIVE.value
        and _value(issue.issue_kind) == IssueKind.TOPIC.value
        and not issue.editorial_key
    ]
    diagnostics["canonical_topic_collections"] = len(canonical_by_topic)
    diagnostics["legacy_active_topic_collections"] = len(legacy_active_topics)
    if bootstrap_sources:
        topic_priority = {topic: index for index, topic in enumerate(PUBLIC_ISSUE_TOPICS)}
        topic_hints: dict[str, set[str]] = defaultdict(set)
        for membership in membership_rows:
            issue = issues_by_id.get(membership.issue_id)
            if issue is None or _value(issue.issue_kind) != IssueKind.TOPIC.value:
                continue
            topic = normalize_issue_topic(issue.topic, issue.title, issue.summary or "")
            if topic in PUBLIC_ISSUE_TOPICS:
                topic_hints[membership.article_id].add(topic)

        article_topics: dict[str, str] = {}
        for article in active_articles:
            hints = sorted(
                topic_hints.get(article.id, set()),
                key=lambda value: topic_priority[value],
            )
            topic = hints[0] if hints else infer_issue_topic(article.title)
            if topic in PUBLIC_ISSUE_TOPICS:
                article_topics[article.id] = topic

        now = utc_now()
        for topic in PUBLIC_ISSUE_TOPICS:
            topic_articles = [
                article for article in active_articles if article_topics.get(article.id) == topic
            ]
            activity_values = [
                article.published_at or article.updated_at or now for article in topic_articles
            ]
            opened_at = min(activity_values, default=now)
            last_activity_at = max(activity_values, default=now)
            expected_summary = f"{topic} 분야의 최신 기사"
            issue = canonical_by_topic.get(topic)
            changed = issue is None or any(
                (
                    issue.title != topic,
                    issue.summary != expected_summary,
                    issue.topic != topic,
                    _value(issue.status) != IssueStatus.ACTIVE.value,
                    _value(issue.issue_kind) != IssueKind.TOPIC.value,
                    issue.last_activity_at < last_activity_at,
                )
            )
            if changed:
                actions["canonical_topic_collections_upserted"] += 1
            if dry_run:
                continue
            if issue is None:
                issue = Issue(
                    id=canonical_topic_issue_id(topic),
                    title=topic,
                    summary=expected_summary,
                    topic=topic,
                    status=IssueStatus.ACTIVE,
                    issue_kind=IssueKind.TOPIC,
                    editorial_key=canonical_topic_editorial_key(topic),
                    opened_at=opened_at,
                    last_activity_at=last_activity_at,
                    version=1,
                )
                session.add(issue)
                issues.append(issue)
                issues_by_id[issue.id] = issue
                canonical_by_topic[topic] = issue
            elif changed:
                issue.title = topic
                issue.summary = expected_summary
                issue.topic = topic
                issue.status = IssueStatus.ACTIVE
                issue.issue_kind = IssueKind.TOPIC
                issue.last_activity_at = max(issue.last_activity_at, last_activity_at)
                issue.version += 1
        if not dry_run:
            await session.flush()

        membership_pairs = {
            (membership.issue_id, membership.article_id) for membership in membership_rows
        }
        for article_id, topic in sorted(article_topics.items()):
            issue_id = canonical_topic_issue_id(topic)
            if (issue_id, article_id) in membership_pairs:
                continue
            actions["topic_memberships_upserted"] += 1
            if not dry_run:
                session.add(
                    IssueMembership(
                        issue_id=issue_id,
                        article_id=article_id,
                        confidence=1.0,
                        created_at=now,
                    )
                )

        actions["legacy_active_topic_collections_archived"] = len(
            legacy_active_topics
        )
        if not dry_run:
            for issue in legacy_active_topics:
                issue.status = IssueStatus.ARCHIVED
                issue.version += 1

    jobs = list(
        (
            await session.scalars(
                select(Job)
                .where(Job.job_type != "__oauth_challenge__")
                .order_by(Job.created_at.desc(), Job.id.desc())
            )
        ).all()
    )

    issue_versions = {
        issue.id: int(issue.version)
        for issue in issues
    }
    current_article_versions = {
        article.id: versions_by_article[article.id][0].id
        for article in active_articles
        if versions_by_article.get(article.id)
    }
    comparison_candidate_states = {
        JobStatus.PENDING.value,
        JobStatus.LEASED.value,
        JobStatus.FAILED.value,
        JobStatus.DEAD.value,
    }
    for job in jobs:
        if (
            job.job_type != "build_issue_comparison"
            or _status(job) not in comparison_candidate_states
        ):
            continue
        payload = job.payload_json or {}
        article_ids_value = payload.get("article_ids")
        version_ids_value = payload.get("article_version_ids")
        article_ids_value = (
            list(article_ids_value)
            if isinstance(article_ids_value, (list, tuple))
            else []
        )
        version_ids_value = (
            list(version_ids_value)
            if isinstance(version_ids_value, (list, tuple))
            else []
        )
        issue_id = str(payload.get("issue_id") or "")
        try:
            requested_issue_version = int(payload.get("issue_version") or 0)
        except (TypeError, ValueError):
            requested_issue_version = 0
        stale = (
            len(article_ids_value) != len(version_ids_value)
            or not article_ids_value
            or issue_versions.get(issue_id) != requested_issue_version
            or any(
                current_article_versions.get(str(article_id)) != str(version_id)
                for article_id, version_id in zip(
                    article_ids_value, version_ids_value, strict=True
                )
            )
        )
        if not stale:
            last_error = job.last_error_json or {}
            error_code = (
                str(last_error.get("code") or "")
                if isinstance(last_error, Mapping)
                else ""
            )
            if (
                _status(job) in {JobStatus.FAILED.value, JobStatus.DEAD.value}
                and error_code
                in {"RESULT_APPLICATION_FAILED", "PROVIDER_SCHEMA_REJECTED"}
            ):
                diagnostics["recoverable_comparison_jobs"] += 1
                actions["comparison_jobs_requeued"] += 1
                if not dry_run:
                    job.status = JobStatus.PENDING
                    job.attempts = 0
                    job.available_at = utc_now()
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.last_error_json = None
                    job.updated_at = utc_now()
            continue
        diagnostics["stale_comparison_jobs"] += 1
        if _status(job) == JobStatus.LEASED.value:
            deferred["stale_comparison_work_in_progress"] += 1
            continue
        actions["stale_comparison_jobs_cancelled"] += 1
        if not dry_run:
            job.status = JobStatus.CANCELLED
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utc_now()

    active_analysis_jobs: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        if job.job_type != "analyze" or _status(job) not in _ACTIVE_JOB_STATUSES:
            continue
        version_id = _job_payload_identifier(job, "article_version_id")
        if version_id is not None:
            active_analysis_jobs[version_id].append(job)
    for version_id, version_jobs in active_analysis_jobs.items():
        leased = [
            job for job in version_jobs if _status(job) == JobStatus.LEASED.value
        ]
        pending = [
            job for job in version_jobs if _status(job) == JobStatus.PENDING.value
        ]
        redundant: list[Job]
        if trusted_by_version.get(version_id):
            redundant = pending
            deferred["redundant_analysis_work_in_progress"] += len(leased)
        elif leased:
            redundant = pending
            deferred["redundant_analysis_work_in_progress"] += max(0, len(leased) - 1)
        elif len(pending) > 1:
            keep = min(pending, key=lambda item: (item.created_at, item.id))
            redundant = [job for job in pending if job.id != keep.id]
        else:
            redundant = []
        diagnostics["redundant_analysis_jobs"] += len(redundant)
        actions["redundant_analysis_jobs_cancelled"] += len(redundant)
        if not dry_run:
            for job in redundant:
                job.status = JobStatus.CANCELLED
                job.lease_owner = None
                job.lease_expires_at = None
                job.updated_at = utc_now()

    job_counts = Counter((job.job_type, _status(job)) for job in jobs)
    diagnostics["job_counts"] = {
        job_type: {
            status: count
            for (count_type, status), count in sorted(job_counts.items())
            if count_type == job_type
        }
        for job_type in sorted({job_type for job_type, _status_value in job_counts})
    }
    for job in jobs:
        if job.job_type != "crawl" or not job.dedupe_key.startswith("scheduled:"):
            continue
        config = (job.payload_json or {}).get("config")
        scheduled_value = config.get("scheduled") if isinstance(config, Mapping) else None
        explicitly_scheduled = scheduled_value is True or (
            isinstance(scheduled_value, str)
            and scheduled_value.strip().casefold() == "true"
        )
        if explicitly_scheduled:
            continue
        state = _status(job)
        if state not in {
            JobStatus.PENDING.value,
            JobStatus.LEASED.value,
            JobStatus.FAILED.value,
        }:
            continue
        diagnostics["unscheduled_periodic_crawl_jobs"] += 1
        if state == JobStatus.LEASED.value:
            deferred["unscheduled_periodic_crawl_work_in_progress"] += 1
            continue
        actions["unscheduled_periodic_crawl_jobs_cancelled"] += 1
        if not dry_run:
            job.status = JobStatus.CANCELLED
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utc_now()
            run = await session.get(CrawlRun, job.id)
            if run is not None and _value(run.status) in {
                CrawlStatus.PENDING.value,
                CrawlStatus.RUNNING.value,
                CrawlStatus.FAILED.value,
            }:
                run.status = CrawlStatus.CANCELLED
                run.finished_at = utc_now()
    exact_jobs = {(job.job_type, job.dedupe_key): job for job in jobs}
    active_analysis_versions = {
        value
        for job in jobs
        if job.job_type == "analyze" and _status(job) in _ACTIVE_JOB_STATUSES
        if (value := _job_payload_identifier(job, "article_version_id")) is not None
    }
    active_score_versions = {
        value
        for job in jobs
        if job.job_type == "calculate_score" and _status(job) in _ACTIVE_JOB_STATUSES
        if (value := _job_payload_identifier(job, "article_version_id")) is not None
    }
    active_crawl_sources = {
        value
        for job in jobs
        if job.job_type == "crawl" and _status(job) in _ACTIVE_JOB_STATUSES
        if (value := _job_payload_identifier(job, "source_id")) is not None
    }
    actively_clustering_articles = {
        str(article_id)
        for job in jobs
        if job.job_type == "cluster" and _status(job) in _ACTIVE_JOB_STATUSES
        for article_id in ((job.payload_json or {}).get("article_ids") or [])
    }

    active_weight = await session.scalar(
        select(WeightProfileRevision)
        .where(WeightProfileRevision.status == "active")
        .order_by(
            WeightProfileRevision.revision.desc(),
            WeightProfileRevision.created_at.desc(),
            WeightProfileRevision.id.desc(),
        )
        .limit(1)
    )

    source_counters: dict[str, Counter[str]] = defaultdict(Counter)
    projected_current: dict[str, ArticleVersion | None] = {}
    for article in articles:
        source_counter = source_counters[article.source_id]
        source_counter["articles"] += 1
        owned_versions = versions_by_article.get(article.id, [])
        latest = owned_versions[0] if owned_versions else None
        current = versions_by_id.get(article.current_version_id or "")
        current_owned = current is not None and current.article_id == article.id
        if article.current_version_id is None:
            diagnostics["current_version_missing"] += 1
        elif not current_owned:
            diagnostics["current_version_cross_linked"] += 1
        elif latest is not None and current.id != latest.id:
            diagnostics["current_version_stale"] += 1
        expected = latest
        projected_current[article.id] = expected
        if current_owned and article.id not in homepage_placeholder_ids:
            source_counter["current_versions"] += 1
        if current_owned and current.normalized_text_ref in body_blob_ids:
            source_counter["current_bodies"] += 1
        if current_owned and trusted_by_version.get(current.id):
            source_counter["trusted_assessments"] += 1
        if current_owned:
            trusted = trusted_by_version.get(current.id, [])
            valid_active = any(
                _value(score.status) == ScoreStatus.ACTIVE.value
                and score_matches_trusted_assessments(score, trusted)
                for score in scores_by_version.get(current.id, [])
            )
            if valid_active:
                source_counter["matching_active_scores"] += 1
                source_counter["public_ready_articles"] += 1

    diagnostics["sources"] = [
        {
            "id": source.id,
            "name": source.name,
            "active": bool(source.active),
            "source_type": _value(source.source_type),
            "policy_status": _value(source.policy_status),
            "robots_status": _value(source.robots_status),
            "terms_status": _value(source.terms_status),
            "active_adapter_types": [
                _value(adapter.adapter_type) for adapter in adapters_by_source.get(source.id, [])
            ],
            **{
                name: int(source_counters[source.id][name])
                for name in (
                    "articles",
                    "current_versions",
                    "current_bodies",
                    "trusted_assessments",
                    "matching_active_scores",
                    "public_ready_articles",
                )
            },
        }
        for source in sources
    ]

    crawl_source_ids: set[str] = set()
    crawl_source_ids.update(scheduled_refresh_source_ids)
    cluster_article_ids: list[str] = []
    for article in active_articles:
        version = projected_current[article.id]
        if article.current_version_id != (None if version is None else version.id):
            actions["version_pointers_repaired"] += 1
            if not dry_run:
                article.current_version_id = None if version is None else version.id
                article.updated_at = utc_now()
        if version is None:
            deferred["articles_without_versions"] += 1
            crawl_source_ids.add(article.source_id)
            continue
        if version.normalized_text_ref not in body_blob_ids:
            if article.source_id in metadata_only_source_ids:
                diagnostics["metadata_only_articles"] += 1
                continue
            diagnostics["current_body_missing"] += 1
            deferred["articles_without_body"] += 1
            crawl_source_ids.add(article.source_id)
            continue
        if article.id not in memberships:
            cluster_article_ids.append(article.id)
        trusted = trusted_by_version.get(version.id, [])
        if not trusted:
            diagnostics["trusted_assessment_missing"] += 1
            if version.id in active_analysis_versions:
                deferred["analysis_work_in_progress"] += 1
            else:
                disposition = await _ensure_job(
                    session,
                    jobs=jobs,
                    exact_jobs=exact_jobs,
                    job_type="analyze",
                    dedupe_key=f"recovery:{generation}:analyze:{version.id}",
                    payload={
                        "article_id": article.id,
                        "article_version_id": version.id,
                        "request_id": f"pipeline-recovery:{generation}",
                    },
                    dry_run=dry_run,
                )
                _record_job_disposition(report, prefix="analysis", disposition=disposition)
            continue

        version_scores = scores_by_version.get(version.id, [])
        valid_active = [
            score
            for score in version_scores
            if _value(score.status) == ScoreStatus.ACTIVE.value
            and score_matches_trusted_assessments(score, trusted)
        ]
        if valid_active:
            continue
        diagnostics["matching_active_score_missing"] += 1
        matching_drafts = [
            score
            for score in version_scores
            if _value(score.status) == ScoreStatus.DRAFT.value
            and score_matches_trusted_assessments(score, trusted)
        ]
        latest_active = next(
            (
                score
                for score in version_scores
                if _value(score.status) == ScoreStatus.ACTIVE.value
            ),
            None,
        )
        draft = matching_drafts[0] if matching_drafts else None
        # Promote only when the matching draft is at least as recent, so the
        # public latest-active selection cannot remain pinned to a newer
        # invalid legacy score. Older invalid ACTIVE rows are superseded in
        # the same transaction to restore the single-public-score invariant.
        if draft is not None and (
            latest_active is None
            or (draft.created_at, draft.id) >= (latest_active.created_at, latest_active.id)
        ):
            actions["draft_scores_promoted"] += 1
            invalid_active_scores = [
                score
                for score in version_scores
                if _value(score.status) == ScoreStatus.ACTIVE.value
                and score.id != draft.id
            ]
            actions["invalid_active_scores_superseded"] += len(invalid_active_scores)
            if not dry_run:
                for score in invalid_active_scores:
                    score.status = ScoreStatus.SUPERSEDED
                draft.status = ScoreStatus.ACTIVE
            continue
        if version.id in active_score_versions:
            deferred["score_work_in_progress"] += 1
            continue
        if active_weight is None:
            deferred["score_blocked_no_active_weight"] += 1
            continue
        disposition = await _ensure_job(
            session,
            jobs=jobs,
            exact_jobs=exact_jobs,
            job_type="calculate_score",
            dedupe_key=(
                f"recovery:{generation}:score:{version.id}:{active_weight.id}"
            ),
            payload={
                "article_id": article.id,
                "article_version_id": version.id,
                "weight_revision_id": active_weight.id,
                "request_id": f"pipeline-recovery:{generation}",
            },
            dry_run=dry_run,
        )
        _record_job_disposition(report, prefix="score", disposition=disposition)

    # An active configured source with no article is also a persisted pipeline
    # gap.  Sources with content are recrawled only when an article lacks a
    # usable version/body, keeping recovery bounded and policy-safe.
    sources_with_articles = {article.source_id for article in articles}
    crawl_source_ids.update(
        source.id for source in active_sources if source.id not in sources_with_articles
    )
    for source_id in sorted(crawl_source_ids):
        source = sources_by_id.get(source_id)
        if source is None or not source.active:
            continue
        source_adapters = adapters_by_source.get(source.id, [])
        if not source_adapters:
            deferred["crawl_blocked_no_adapter"] += 1
            continue
        scheduled_adapter = next(
            (
                adapter
                for adapter in source_adapters
                if bool((adapter.config_json or {}).get("scheduled"))
            ),
            None,
        )
        selected_adapter = scheduled_adapter or source_adapters[0]
        selected_config = dict(selected_adapter.config_json or {})
        selected_type = _value(selected_adapter.adapter_type)
        selected_url = str(
            selected_config.get("feed_url") or source.canonical_url
        )
        statuses = {
            "policy_status": _value(source.policy_status),
            "robots_status": _value(source.robots_status),
            "terms_status": _value(source.terms_status),
        }
        if selected_type == SourceType.CRAWLER.value and any(
            value != SourcePolicyStatus.APPROVED.value for value in statuses.values()
        ):
            deferred["crawl_blocked_policy"] += 1
            continue
        if statuses["policy_status"] in {
            SourcePolicyStatus.REJECTED.value,
            SourcePolicyStatus.EXPIRED.value,
        }:
            deferred["crawl_blocked_policy"] += 1
            continue
        if source.id in active_crawl_sources:
            deferred["crawl_work_in_progress"] += 1
            continue
        disposition = await _ensure_job(
            session,
            jobs=jobs,
            exact_jobs=exact_jobs,
            job_type="crawl",
            dedupe_key=f"recovery:{generation}:crawl:{source.id}",
            payload={
                "source_id": source.id,
                "url": selected_url,
                "source_type": selected_type,
                "adapter_type": selected_type,
                "config": selected_config,
                **statuses,
                "mode": "live",
                "reason": "pipeline recovery",
                "request_id": f"pipeline-recovery:{generation}",
            },
            dry_run=dry_run,
            crawl_source_id=source.id,
        )
        _record_job_disposition(report, prefix="crawl", disposition=disposition)

    uncovered = sorted(set(cluster_article_ids) - actively_clustering_articles)
    for offset in range(0, len(uncovered), 100):
        batch = uncovered[offset : offset + 100]
        if not batch:
            continue
        batch_key = f"{offset // 100 + 1:04d}"
        disposition = await _ensure_job(
            session,
            jobs=jobs,
            exact_jobs=exact_jobs,
            job_type="cluster",
            dedupe_key=f"recovery:{generation}:cluster:{batch_key}",
            payload={
                "article_ids": batch,
                "request_id": f"pipeline-recovery:{generation}",
            },
            dry_run=dry_run,
        )
        _record_job_disposition(report, prefix="cluster", disposition=disposition)
    deferred["cluster_work_in_progress"] += len(
        set(cluster_article_ids) & actively_clustering_articles
    )

    material_actions = sum(
        count for name, count in actions.items() if name != "audit_rows_written"
    )
    if not dry_run and material_actions:
        audit_summary = {
            "generation": generation,
            "actions": dict(actions),
            "deferred": dict(deferred),
            "diagnostic_totals": {
                key: value
                for key, value in diagnostics.items()
                if isinstance(value, int)
            },
        }
        session.add(
            AuditLog(
                id=new_ulid(),
                actor_id=None,
                action="PIPELINE_RECOVERY_APPLIED",
                target_type="content_pipeline",
                target_id=generation,
                before_json=None,
                after_json=audit_summary,
                reason="idempotent persisted content-pipeline recovery",
                request_id=f"pipeline-recovery:{generation}",
                created_at=utc_now(),
            )
        )
        actions["audit_rows_written"] = 1
    return report


async def run_pipeline_recovery(
    *,
    generation: str | None = None,
    dry_run: bool = True,
    bootstrap_sources: bool = False,
) -> dict[str, Any]:
    """Connect to the configured DB and run one atomic recovery transaction."""

    selected_generation = validate_recovery_generation(
        generation or default_recovery_generation()
    )
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as session:
            async with session.begin():
                report = await recover_pipeline(
                    session,
                    generation=selected_generation,
                    dry_run=dry_run,
                    bootstrap_sources=bootstrap_sources,
                )
            return report
    finally:
        await dispose_engine()


__all__ = [
    "default_recovery_generation",
    "recover_pipeline",
    "run_pipeline_recovery",
    "validate_recovery_generation",
]
