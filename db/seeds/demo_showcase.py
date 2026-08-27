"""Versioned, idempotent showcase preparation and read-only trust audit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.app.core.config import get_settings
from apps.api.app.db.enums import (
    AdapterType,
    ComparisonSnapshotStatus,
    IssueKind,
    IssueStatus,
    JobStatus,
    ScoreStatus,
    SourcePolicyStatus,
    SourceType,
)
from apps.api.app.db.models import (
    Article,
    ArticleVersion,
    AuditLog,
    Issue,
    IssueComparisonSnapshot,
    IssueMembership,
    Job,
    ModelAlias,
    ModelAssessment,
    ScoreVersion,
    Source,
    SourceAdapter,
)
from apps.api.app.db.session import create_engine, dispose_engine
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import ensure_utc, utc_now
from apps.api.app.domains.content.canonical import canonicalize_url
from apps.api.app.domains.content.trust import (
    evidence_is_synthetic,
    is_trusted_openai_assessment,
    score_matches_trusted_assessments,
)
from db.seeds.source_feeds import scheduled_rss_config

DEFAULT_MANIFEST = Path(__file__).with_name("demo_showcase.json")
REQUIRED_DB_REVISION = "0012_share_card_recovery"
_GENERIC_TITLES = frozenset({"정치", "경제", "사회", "국제", "문화", "과학", "기술"})


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ShowcaseArticle(ManifestModel):
    source: str = Field(min_length=1, max_length=255)
    source_home_url: str
    publisher_kind: Literal["MEDIA", "GOVERNMENT", "OTHER"]
    source_type: Literal["API", "RSS", "CRAWLER"] = "CRAWLER"
    policy_status: Literal["PENDING", "APPROVED", "REJECTED"]
    robots_status: Literal["PENDING", "APPROVED", "REJECTED"]
    terms_status: Literal["PENDING", "APPROVED", "REJECTED"]
    policy_reference: str = Field(min_length=3, max_length=500)
    url: str

    @field_validator("source_home_url", "url")
    @classmethod
    def direct_https_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("showcase sources and articles require direct HTTPS URLs")
        return canonicalize_url(value)

    @model_validator(mode="after")
    def require_review_evidence(self) -> ShowcaseArticle:
        reference = self.policy_reference.strip()
        if "https://" not in reference:
            raise ValueError("policy_reference must include an authoritative HTTPS evidence URL")
        if {
            self.policy_status,
            self.robots_status,
            self.terms_status,
        } == {"APPROVED"} and reference.upper().startswith("PENDING"):
            raise ValueError("fully APPROVED decisions cannot use a PENDING policy reference")
        return self


class ShowcaseIssue(ManifestModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    title: str = Field(min_length=10, max_length=500)
    summary: str = Field(min_length=40, max_length=1200)
    topic: Literal["정치", "국제", "사회", "경제", "산업"]
    featured_rank: int = Field(gt=0)
    selection_reason: str = Field(min_length=10, max_length=1000)
    editorial_review_status: Literal["PENDING", "APPROVED"]
    reviewed_by: str = Field(min_length=2, max_length=120)
    articles: list[ShowcaseArticle] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_event(self) -> ShowcaseIssue:
        if self.title.strip() in _GENERIC_TITLES:
            raise ValueError("issue title must describe an event, not a broad category")
        urls = [article.url for article in self.articles]
        if len(urls) != len(set(urls)):
            raise ValueError("issue article URLs must be unique")
        if len({article.source_home_url for article in self.articles}) < 3:
            raise ValueError("each showcase issue requires at least three distinct sources")
        if sum(article.publisher_kind == "MEDIA" for article in self.articles) < 2:
            raise ValueError("each showcase issue requires at least two media publishers")
        if self.editorial_review_status == "APPROVED" and self.reviewed_by.upper().startswith(
            "PENDING"
        ):
            raise ValueError("an APPROVED editorial review requires an identified reviewer")
        return self


class ShowcaseManifest(ManifestModel):
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$")
    as_of: datetime
    max_age_days: int = Field(default=7, gt=0, le=30)
    issues: list[ShowcaseIssue] = Field(min_length=3, max_length=5)

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("manifest as_of must include a timezone")
        return ensure_utc(value)

    @model_validator(mode="after")
    def unique_keys_and_ranks(self) -> ShowcaseManifest:
        keys = [issue.key for issue in self.issues]
        ranks = [issue.featured_rank for issue in self.issues]
        if len(keys) != len(set(keys)):
            raise ValueError("showcase issue keys must be unique")
        if len(ranks) != len(set(ranks)):
            raise ValueError("showcase featured ranks must be unique")
        source_identities: dict[str, tuple[str, str, str]] = {}
        source_policy_decisions: dict[str, tuple[str, str, str, str]] = {}
        for issue in self.issues:
            for article in issue.articles:
                identity = (article.source, article.source_type, article.publisher_kind)
                previous = source_identities.setdefault(article.source_home_url, identity)
                if previous != identity:
                    raise ValueError("one source_home_url has conflicting source metadata")
                decision = (
                    article.policy_status,
                    article.robots_status,
                    article.terms_status,
                    article.policy_reference,
                )
                previous_decision = source_policy_decisions.setdefault(
                    article.source_home_url, decision
                )
                if previous_decision != decision:
                    raise ValueError("one source_home_url has conflicting policy decisions")
        return self


@dataclass
class RefreshSummary:
    issues_created: int = 0
    issues_updated: int = 0
    sources_created: int = 0
    scheduled_rss_adapters_planned: int = 0
    memberships_upserted: int = 0
    crawl_jobs_enqueued: int = 0
    analysis_jobs_enqueued: int = 0
    score_jobs_enqueued: int = 0
    scores_promoted: int = 0
    comparison_jobs_enqueued: int = 0
    missing_articles: int = 0
    policy_blocked: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(vars(self))


@dataclass
class AuditIssue:
    id: str
    title: str
    article_count: int
    source_count: int
    media_source_count: int
    trusted_analysis_count: int
    synthetic_analysis_count: int
    data_as_of: datetime | None
    articles: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            **vars(self),
            "data_as_of": self.data_as_of.isoformat() if self.data_as_of else None,
        }


@dataclass
class AuditResult:
    issues: list[AuditIssue]
    errors: list[str]
    warnings: list[str]
    queue: dict[str, int]

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.warnings:
            return 2
        return 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "failed" if self.errors else "warning" if self.warnings else "passed",
            "issues": [issue.as_dict() for issue in self.issues],
            "errors": self.errors,
            "warnings": self.warnings,
            "queue": self.queue,
        }


async def preflight_showcase(session: AsyncSession, manifest: ShowcaseManifest) -> dict[str, Any]:
    """Inspect deployment prerequisites without relying on the Phase 1 schema."""

    actual_revision = await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    database_counts: dict[str, int] = {}
    for table_name in ("sources", "articles", "issues", "model_assessments", "score_versions"):
        value = await session.scalar(text(f"SELECT COUNT(*) FROM {table_name}"))
        database_counts[table_name] = int(value or 0)
    provider_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT aliases.provider, assessments.status, COUNT(*) AS count
                FROM model_assessments assessments
                JOIN model_aliases aliases ON aliases.id = assessments.model_alias_id
                GROUP BY aliases.provider, assessments.status
                ORDER BY aliases.provider, assessments.status
                """
                )
            )
        )
        .mappings()
        .all()
    )
    model_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT alias, actual_model_id
                FROM model_aliases
                WHERE provider = 'openai' AND status = 'ACTIVE'
                ORDER BY alias
                """
                )
            )
        )
        .mappings()
        .all()
    )
    queue_rows = (
        (
            await session.execute(
                text("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status ORDER BY status")
            )
        )
        .mappings()
        .all()
    )
    latest_row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                  (SELECT MAX(published_at) FROM articles) AS article_published_at,
                  (SELECT MAX(fetched_at) FROM article_versions) AS article_fetched_at,
                  (SELECT MAX(created_at) FROM model_assessments) AS assessment_created_at
                """
                )
            )
        )
        .mappings()
        .one()
    )
    decision_counts: dict[str, dict[str, int]] = {
        field: {} for field in ("policy_status", "robots_status", "terms_status")
    }
    review_counts: dict[str, int] = {}
    publisher_counts: dict[str, int] = {}
    for issue in manifest.issues:
        review_counts[issue.editorial_review_status] = (
            review_counts.get(issue.editorial_review_status, 0) + 1
        )
        for article in issue.articles:
            publisher_counts[article.publisher_kind] = (
                publisher_counts.get(article.publisher_kind, 0) + 1
            )
            for decision_field in decision_counts:
                value = str(getattr(article, decision_field))
                status_counts = decision_counts[decision_field]
                status_counts[value] = status_counts.get(value, 0) + 1
    errors: list[str] = []
    if actual_revision != REQUIRED_DB_REVISION:
        errors.append(
            f"schema revision {actual_revision!s} must be upgraded to {REQUIRED_DB_REVISION}"
        )
    article_count = sum(len(issue.articles) for issue in manifest.issues)
    if any(counts.get("APPROVED", 0) != article_count for counts in decision_counts.values()):
        errors.append(
            "all manifest policy, robots and terms decisions must be APPROVED before refresh"
        )
    if review_counts.get("APPROVED", 0) != len(manifest.issues):
        errors.append("all manifest issues require APPROVED human editorial review before refresh")
    if not model_rows:
        errors.append("an active OpenAI model alias is required")

    def serialize(value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else value

    return {
        "status": "passed" if not errors else "failed",
        "required_schema_revision": REQUIRED_DB_REVISION,
        "actual_schema_revision": actual_revision,
        "manifest": {
            "version": manifest.version,
            "issue_count": len(manifest.issues),
            "article_count": article_count,
            "decision_counts": decision_counts,
            "editorial_review_counts": review_counts,
            "publisher_counts": publisher_counts,
        },
        "database_counts": database_counts,
        "assessment_counts": [dict(row) for row in provider_rows],
        "active_openai_models": [dict(row) for row in model_rows],
        "queue": {str(row["status"]): int(row["count"]) for row in queue_rows},
        "latest": {key: serialize(value) for key, value in latest_row.items()},
        "errors": errors,
    }


def load_manifest(path: Path = DEFAULT_MANIFEST) -> ShowcaseManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ShowcaseManifest.model_validate(payload)


async def _get_or_create_source(
    session: AsyncSession,
    article: ShowcaseArticle,
    *,
    apply: bool,
    summary: RefreshSummary,
    planned_source_urls: set[str],
    planned_scheduled_adapter_urls: set[str],
) -> Source | None:
    scheduled_config = scheduled_rss_config(
        article.source_home_url,
        policy_reference=article.policy_reference,
    )
    source = await session.scalar(
        select(Source).where(Source.canonical_url == article.source_home_url)
    )
    if source is not None:
        if apply:
            source.name = article.source
            source.source_type = SourceType(article.source_type)
            source.policy_status = SourcePolicyStatus(article.policy_status)
            source.robots_status = SourcePolicyStatus(article.robots_status)
            source.terms_status = SourcePolicyStatus(article.terms_status)
            source.active = True
            adapter = await session.scalar(
                select(SourceAdapter).where(
                    SourceAdapter.source_id == source.id,
                    SourceAdapter.adapter_type == AdapterType(article.source_type),
                )
            )
            if adapter is None:
                session.add(
                    SourceAdapter(
                        id=new_ulid(),
                        source_id=source.id,
                        adapter_type=AdapterType(article.source_type),
                        config_json={
                            "discover_links": False,
                            "policy_reference": article.policy_reference,
                        },
                        rate_limit=10,
                        raw_payload_retention_days=7,
                        active=True,
                    )
                )
            else:
                adapter.config_json = {
                    **(adapter.config_json or {}),
                    "discover_links": False,
                    "policy_reference": article.policy_reference,
                }
                adapter.rate_limit = adapter.rate_limit or 10
                adapter.raw_payload_retention_days = 7
                adapter.active = True
        if scheduled_config is not None:
            scheduled_adapter = await session.scalar(
                select(SourceAdapter).where(
                    SourceAdapter.source_id == source.id,
                    SourceAdapter.adapter_type == AdapterType.RSS,
                )
            )
            scheduled_changed = scheduled_adapter is None or any(
                (
                    not scheduled_adapter.active,
                    scheduled_adapter.rate_limit != 10,
                    scheduled_adapter.raw_payload_retention_days != 7,
                    any(
                        (scheduled_adapter.config_json or {}).get(key) != value
                        for key, value in scheduled_config.items()
                    )
                    if scheduled_adapter is not None
                    else True,
                )
            )
            if (
                scheduled_changed
                and article.source_home_url not in planned_scheduled_adapter_urls
            ):
                summary.scheduled_rss_adapters_planned += 1
                planned_scheduled_adapter_urls.add(article.source_home_url)
            if apply and scheduled_changed:
                if scheduled_adapter is None:
                    session.add(
                        SourceAdapter(
                            id=new_ulid(),
                            source_id=source.id,
                            adapter_type=AdapterType.RSS,
                            config_json=scheduled_config,
                            rate_limit=10,
                            raw_payload_retention_days=7,
                            active=True,
                        )
                    )
                else:
                    scheduled_adapter.config_json = {
                        **(scheduled_adapter.config_json or {}),
                        **scheduled_config,
                    }
                    scheduled_adapter.rate_limit = 10
                    scheduled_adapter.raw_payload_retention_days = 7
                    scheduled_adapter.active = True
        return source
    if article.source_home_url not in planned_source_urls:
        summary.sources_created += 1
        planned_source_urls.add(article.source_home_url)
    if not apply:
        if (
            scheduled_config is not None
            and article.source_home_url not in planned_scheduled_adapter_urls
        ):
            summary.scheduled_rss_adapters_planned += 1
            planned_scheduled_adapter_urls.add(article.source_home_url)
        return None
    source = Source(
        id=new_ulid(),
        name=article.source,
        source_type=SourceType(article.source_type),
        canonical_url=article.source_home_url,
        policy_status=SourcePolicyStatus(article.policy_status),
        robots_status=SourcePolicyStatus(article.robots_status),
        terms_status=SourcePolicyStatus(article.terms_status),
        active=True,
    )
    session.add(source)
    await session.flush()
    session.add(
        SourceAdapter(
            id=new_ulid(),
            source_id=source.id,
            adapter_type=AdapterType(article.source_type),
            config_json={"discover_links": False, "policy_reference": article.policy_reference},
            rate_limit=10,
            raw_payload_retention_days=7,
            active=True,
        )
    )
    if scheduled_config is not None:
        session.add(
            SourceAdapter(
                id=new_ulid(),
                source_id=source.id,
                adapter_type=AdapterType.RSS,
                config_json=scheduled_config,
                rate_limit=10,
                raw_payload_retention_days=7,
                active=True,
            )
        )
        if article.source_home_url not in planned_scheduled_adapter_urls:
            summary.scheduled_rss_adapters_planned += 1
            planned_scheduled_adapter_urls.add(article.source_home_url)
    return source


async def _enqueue_once(
    session: AsyncSession,
    *,
    job_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
    apply: bool,
    reopen_succeeded: bool = False,
) -> bool:
    existing = await session.scalar(
        select(Job).where(Job.job_type == job_type, Job.dedupe_key == dedupe_key)
    )
    if existing is not None:
        if apply and (
            existing.status in {JobStatus.FAILED, JobStatus.DEAD, JobStatus.CANCELLED}
            or (reopen_succeeded and existing.status == JobStatus.SUCCEEDED)
        ):
            existing.status = JobStatus.PENDING
            existing.attempts = 0
            existing.available_at = utc_now()
            existing.lease_owner = None
            existing.lease_expires_at = None
            existing.last_error_json = None
            existing.payload_json = payload
            existing.updated_at = utc_now()
            return True
        return False
    if not apply:
        return True
    now = utc_now()
    session.add(
        Job(
            id=new_ulid(),
            job_type=job_type,
            dedupe_key=dedupe_key,
            status=JobStatus.PENDING,
            priority=100,
            available_at=now,
            lease_owner=None,
            lease_expires_at=None,
            attempts=0,
            max_attempts=5,
            payload_json=payload,
            last_error_json=None,
            created_at=now,
            updated_at=now,
        )
    )
    return True


async def refresh_showcase(
    session: AsyncSession,
    manifest: ShowcaseManifest,
    *,
    apply: bool,
    backup_reference: str | None = None,
) -> RefreshSummary:
    if apply and not (backup_reference or "").strip():
        raise ValueError("a verified DB backup reference is required before mutation")
    if apply and any(issue.editorial_review_status != "APPROVED" for issue in manifest.issues):
        raise ValueError("APPROVED human editorial review is required before mutation")
    if apply and any(
        decision != "APPROVED"
        for issue in manifest.issues
        for article in issue.articles
        for decision in (
            article.policy_status,
            article.robots_status,
            article.terms_status,
        )
    ):
        raise ValueError("APPROVED policy, robots and terms decisions are required before mutation")
    summary = RefreshSummary()
    request_id = f"demo-refresh:{manifest.version}"
    planned_source_urls: set[str] = set()
    planned_scheduled_adapter_urls: set[str] = set()
    for issue_input in sorted(manifest.issues, key=lambda item: item.featured_rank):
        issue = await session.scalar(select(Issue).where(Issue.editorial_key == issue_input.key))
        if issue is None:
            if apply:
                issue = Issue(
                    id=new_ulid(),
                    title=issue_input.title,
                    summary=issue_input.summary,
                    topic=issue_input.topic,
                    status=IssueStatus.ACTIVE,
                    issue_kind=IssueKind.EVENT,
                    editorial_key=issue_input.key,
                    editorial_priority=issue_input.featured_rank,
                    editorial_reviewed_at=utc_now(),
                    editorial_data_as_of=manifest.as_of,
                    opened_at=manifest.as_of,
                    last_activity_at=manifest.as_of,
                    version=1,
                )
                session.add(issue)
                await session.flush()
            summary.issues_created += 1
        else:
            issue_changed = any(
                (
                    issue.title != issue_input.title,
                    issue.summary != issue_input.summary,
                    issue.topic != issue_input.topic,
                    issue.status != IssueStatus.ACTIVE,
                    issue.issue_kind != IssueKind.EVENT,
                    issue.editorial_priority != issue_input.featured_rank,
                    ensure_utc(issue.editorial_data_as_of) != manifest.as_of
                    if issue.editorial_data_as_of is not None
                    else True,
                    ensure_utc(issue.last_activity_at) != manifest.as_of,
                )
            )
            if apply and issue_changed:
                issue.title = issue_input.title
                issue.summary = issue_input.summary
                issue.topic = issue_input.topic
                issue.status = IssueStatus.ACTIVE
                issue.issue_kind = IssueKind.EVENT
                issue.editorial_priority = issue_input.featured_rank
                issue.editorial_reviewed_at = utc_now()
                issue.editorial_data_as_of = manifest.as_of
                issue.last_activity_at = manifest.as_of
                issue.version += 1
            summary.issues_updated += int(issue_changed)

        desired_article_ids: set[str] = set()
        for article_input in issue_input.articles:
            source = await _get_or_create_source(
                session,
                article_input,
                apply=apply,
                summary=summary,
                planned_source_urls=planned_source_urls,
                planned_scheduled_adapter_urls=planned_scheduled_adapter_urls,
            )
            url_hash = hashlib.sha256(article_input.url.encode()).digest()
            article = await session.scalar(
                select(Article).where(Article.canonical_url_hash == url_hash)
            )
            policy_approved = all(
                value == "APPROVED"
                for value in (
                    article_input.policy_status,
                    article_input.robots_status,
                    article_input.terms_status,
                )
            )
            crawl_payload = {
                "source_id": source.id if source is not None else None,
                "url": article_input.url,
                "source_type": article_input.source_type,
                "policy_status": article_input.policy_status,
                "robots_status": article_input.robots_status,
                "terms_status": article_input.terms_status,
                "mode": "live",
                "request_id": request_id,
            }
            if article is None:
                summary.missing_articles += 1
                if not policy_approved:
                    summary.policy_blocked += 1
                    continue
                if await _enqueue_once(
                    session,
                    job_type="crawl",
                    dedupe_key=f"showcase:{manifest.version}:{url_hash.hex()}",
                    payload=crawl_payload,
                    apply=apply,
                ):
                    summary.crawl_jobs_enqueued += 1
                continue
            desired_article_ids.add(article.id)
            membership = None
            if issue is not None:
                membership = await session.get(IssueMembership, (issue.id, article.id))
            if membership is None and apply and issue is not None:
                session.add(
                    IssueMembership(
                        issue_id=issue.id,
                        article_id=article.id,
                        confidence=1.0,
                        created_at=utc_now(),
                    )
                )
                summary.memberships_upserted += 1

            if not article.current_version_id:
                if policy_approved and await _enqueue_once(
                    session,
                    job_type="crawl",
                    dedupe_key=f"showcase:{manifest.version}:{url_hash.hex()}",
                    payload=crawl_payload,
                    apply=apply,
                    reopen_succeeded=True,
                ):
                    summary.crawl_jobs_enqueued += 1
                continue
            trusted = list(
                (
                    await session.execute(
                        select(ModelAssessment, ModelAlias)
                        .join(ModelAlias, ModelAlias.id == ModelAssessment.model_alias_id)
                        .where(ModelAssessment.article_version_id == article.current_version_id)
                    )
                ).all()
            )
            trusted = [pair for pair in trusted if is_trusted_openai_assessment(*pair)]
            if not trusted:
                if await _enqueue_once(
                    session,
                    job_type="analyze",
                    dedupe_key=f"showcase:{manifest.version}:{article.current_version_id}",
                    payload={
                        "article_version_id": article.current_version_id,
                        "request_id": request_id,
                    },
                    apply=apply,
                ):
                    summary.analysis_jobs_enqueued += 1
                continue
            score_candidates = list(
                (
                    await session.scalars(
                        select(ScoreVersion)
                        .where(ScoreVersion.article_version_id == article.current_version_id)
                        .order_by(ScoreVersion.created_at.desc(), ScoreVersion.id.desc())
                    )
                ).all()
            )
            latest_score = next(
                (
                    score
                    for score in score_candidates
                    if score_matches_trusted_assessments(score, trusted)
                ),
                None,
            )
            if latest_score is None:
                if await _enqueue_once(
                    session,
                    job_type="calculate_score",
                    dedupe_key=(f"showcase:{manifest.version}:score:{article.current_version_id}"),
                    payload={
                        "article_version_id": article.current_version_id,
                        "request_id": request_id,
                    },
                    apply=apply,
                ):
                    summary.score_jobs_enqueued += 1
                continue
            if latest_score is not None and latest_score.status != ScoreStatus.ACTIVE:
                if apply:
                    await session.execute(
                        update(ScoreVersion)
                        .where(
                            ScoreVersion.article_version_id == article.current_version_id,
                            ScoreVersion.status == ScoreStatus.ACTIVE,
                        )
                        .values(status=ScoreStatus.SUPERSEDED)
                    )
                    latest_score.status = ScoreStatus.ACTIVE
                summary.scores_promoted += 1

        if issue is not None:
            if apply:
                obsolete = delete(IssueMembership).where(IssueMembership.issue_id == issue.id)
                if desired_article_ids:
                    obsolete = obsolete.where(
                        IssueMembership.article_id.not_in(desired_article_ids)
                    )
                await session.execute(obsolete)
                await session.flush()

            comparison_rows = list(
                (
                    await session.execute(
                        select(Article, ModelAssessment, ModelAlias)
                        .join(IssueMembership, IssueMembership.article_id == Article.id)
                        .join(
                            ModelAssessment,
                            ModelAssessment.article_version_id == Article.current_version_id,
                        )
                        .join(ModelAlias, ModelAlias.id == ModelAssessment.model_alias_id)
                        .where(IssueMembership.issue_id == issue.id)
                        .order_by(Article.id, ModelAssessment.created_at.desc())
                    )
                ).all()
            )
            trusted_by_article: dict[str, tuple[Article, ModelAssessment, ModelAlias]] = {}
            for article, assessment, alias in comparison_rows:
                if article.id not in trusted_by_article and is_trusted_openai_assessment(
                    assessment, alias
                ):
                    trusted_by_article[article.id] = (article, assessment, alias)
            if len(trusted_by_article) >= 3:
                existing_snapshot = await session.scalar(
                    select(IssueComparisonSnapshot).where(
                        IssueComparisonSnapshot.issue_id == issue.id,
                        IssueComparisonSnapshot.issue_version == issue.version,
                        IssueComparisonSnapshot.prompt_version == "issue-comparison-v1",
                    )
                )
                article_ids = sorted(trusted_by_article)[:4]
                article_version_ids = [
                    str(trusted_by_article[article_id][0].current_version_id)
                    for article_id in article_ids
                ]
                existing_versions = None
                if existing_snapshot is not None and isinstance(
                    existing_snapshot.article_frames_json, dict
                ):
                    existing_versions = existing_snapshot.article_frames_json.get(
                        "article_version_ids"
                    )
                expected_versions = dict(zip(article_ids, article_version_ids, strict=True))
                if existing_versions != expected_versions and await _enqueue_once(
                    session,
                    job_type="build_issue_comparison",
                    dedupe_key=(
                        f"showcase:{manifest.version}:comparison:{issue.id}:"
                        f"{issue.version}:{':'.join(article_version_ids)}"
                    ),
                    payload={
                        "issue_id": issue.id,
                        "issue_version": issue.version,
                        "article_ids": article_ids,
                        "article_version_ids": article_version_ids,
                        "prompt_version": "issue-comparison-v1",
                        "request_id": request_id,
                    },
                    apply=apply,
                    reopen_succeeded=True,
                ):
                    summary.comparison_jobs_enqueued += 1

    if apply:
        session.add(
            AuditLog(
                id=new_ulid(),
                actor_id=None,
                action="DEMO_SHOWCASE_REFRESH",
                target_type="showcase_manifest",
                target_id=manifest.version,
                before_json=None,
                after_json={
                    "manifest_version": manifest.version,
                    "backup_reference": backup_reference,
                    "summary": summary.as_dict(),
                },
                reason="Reviewed showcase refresh",
                request_id=request_id,
                created_at=utc_now(),
            )
        )
        await session.commit()
    else:
        await session.rollback()
    return summary


async def audit_showcase(
    session: AsyncSession,
    *,
    manifest: ShowcaseManifest | None = None,
    max_age_days: int = 7,
    now: datetime | None = None,
) -> AuditResult:
    now = ensure_utc(now or utc_now())
    media_source_urls = {
        article.source_home_url
        for manifest_issue in (manifest.issues if manifest is not None else [])
        for article in manifest_issue.articles
        if article.publisher_kind == "MEDIA"
    }
    issues = list(
        (
            await session.scalars(
                select(Issue)
                .where(
                    Issue.issue_kind == IssueKind.EVENT,
                    Issue.editorial_priority.is_not(None),
                    Issue.status == IssueStatus.ACTIVE,
                )
                .order_by(Issue.editorial_priority, Issue.id)
            )
        ).all()
    )
    reports: list[AuditIssue] = []
    errors: list[str] = []
    warnings: list[str] = []
    ready_article_version_ids: set[str] = set()
    if len(issues) < 3:
        errors.append(f"대표 EVENT 이슈가 {len(issues)}개입니다. 최소 3개가 필요합니다.")
    if len(issues) > 5:
        errors.append(f"대표 EVENT 이슈가 {len(issues)}개입니다. 최대 5개까지 허용합니다.")
    priorities = [issue.editorial_priority for issue in issues]
    if len(priorities) != len(set(priorities)):
        errors.append("대표 EVENT 이슈의 editorial_priority가 중복되었습니다.")
    for issue in issues:
        rows = list(
            (
                await session.execute(
                    select(Article, Source, ArticleVersion)
                    .join(IssueMembership, IssueMembership.article_id == Article.id)
                    .join(Source, Source.id == Article.source_id)
                    .outerjoin(ArticleVersion, ArticleVersion.id == Article.current_version_id)
                    .where(IssueMembership.issue_id == issue.id)
                    .order_by(Article.published_at.desc(), Article.id)
                )
            ).all()
        )
        trusted_count = 0
        synthetic_count = 0
        timestamps: list[datetime] = []
        article_reports: list[dict[str, Any]] = []
        for article, source, version in rows:
            assessment_rows = []
            scores: list[ScoreVersion] = []
            if version is not None:
                assessment_rows = list(
                    (
                        await session.execute(
                            select(ModelAssessment, ModelAlias)
                            .join(ModelAlias, ModelAlias.id == ModelAssessment.model_alias_id)
                            .where(ModelAssessment.article_version_id == version.id)
                            .order_by(ModelAssessment.created_at.desc(), ModelAssessment.id.desc())
                        )
                    ).all()
                )
                scores = list(
                    (
                        await session.scalars(
                            select(ScoreVersion)
                            .where(
                                ScoreVersion.article_version_id == version.id,
                                ScoreVersion.status == ScoreStatus.ACTIVE,
                            )
                            .order_by(ScoreVersion.created_at.desc(), ScoreVersion.id.desc())
                        )
                    ).all()
                )
            trusted = [pair for pair in assessment_rows if is_trusted_openai_assessment(*pair)]
            synthetic = [
                pair
                for pair in assessment_rows
                if evidence_is_synthetic(pair[0].evidence_json) or pair[1].provider != "openai"
            ]
            trusted_scores = [
                score for score in scores if score_matches_trusted_assessments(score, trusted)
            ]
            ready = bool(trusted and trusted_scores)
            if ready and version is not None:
                ready_article_version_ids.add(version.id)
            trusted_count += int(ready)
            synthetic_count += len(synthetic)
            for value in (
                article.published_at,
                version.fetched_at if version is not None else None,
                trusted[0][0].created_at if trusted else None,
            ):
                if value is not None:
                    timestamps.append(ensure_utc(value))
            assessment, alias = trusted[0] if trusted else (None, None)
            score = trusted_scores[0] if trusted_scores else None
            article_reports.append(
                {
                    "article_id": article.id,
                    "source": source.name,
                    "published_at": article.published_at.isoformat()
                    if article.published_at
                    else None,
                    "fetched_at": version.fetched_at.isoformat() if version is not None else None,
                    "provider": alias.provider if alias is not None else None,
                    "model_id": alias.actual_model_id if alias is not None else None,
                    "prompt_version": assessment.prompt_version if assessment is not None else None,
                    "assessment_status": "SUCCEEDED" if assessment is not None else None,
                    "synthetic": bool(synthetic),
                    "score_version_id": score.id if score is not None else None,
                    "confidence": float(score.confidence) if score is not None else None,
                    "ready": ready,
                }
            )
        source_count = len({source.id for _article, source, _version in rows})
        media_source_count = len(
            {
                source.id
                for _article, source, _version in rows
                if source.canonical_url in media_source_urls
            }
        )
        data_as_of = max(timestamps) if timestamps else issue.editorial_data_as_of
        report = AuditIssue(
            id=issue.id,
            title=issue.title,
            article_count=len(rows),
            source_count=source_count,
            media_source_count=media_source_count,
            trusted_analysis_count=trusted_count,
            synthetic_analysis_count=synthetic_count,
            data_as_of=data_as_of,
            articles=article_reports,
        )
        reports.append(report)
        if not (issue.summary or "").strip():
            errors.append(f"{issue.title}: 요약이 비어 있습니다.")
        if issue.editorial_reviewed_at is None:
            errors.append(f"{issue.title}: 편집 검수 시각이 없습니다.")
        comparison_snapshot = await session.scalar(
            select(IssueComparisonSnapshot).where(
                IssueComparisonSnapshot.issue_id == issue.id,
                IssueComparisonSnapshot.issue_version == issue.version,
                IssueComparisonSnapshot.status == ComparisonSnapshotStatus.SUCCEEDED,
                IssueComparisonSnapshot.reviewed_at.is_not(None),
            )
        )
        if comparison_snapshot is None:
            errors.append(f"{issue.title}: 검수된 비교 snapshot이 없습니다.")
        else:
            frame_payload = comparison_snapshot.article_frames_json
            snapshot_versions = (
                frame_payload.get("article_version_ids")
                if isinstance(frame_payload, dict)
                else None
            )
            current_versions = {
                article.id: str(article.current_version_id)
                for article, _source, _version in rows
                if article.current_version_id is not None
            }
            if not isinstance(snapshot_versions, dict) or {
                str(key): str(value) for key, value in snapshot_versions.items()
            } != current_versions:
                errors.append(f"{issue.title}: 비교 snapshot의 기사 version이 최신이 아닙니다.")
            comparison_model = await session.get(
                ModelAlias, comparison_snapshot.model_alias_id
            )
            if (
                comparison_model is None
                or comparison_model.provider != "openai"
                or not comparison_model.actual_model_id.startswith("gpt-")
                or str(getattr(comparison_model.status, "value", comparison_model.status))
                != "ACTIVE"
            ):
                errors.append(f"{issue.title}: 비교 snapshot 모델 provenance가 신뢰되지 않습니다.")
        if len(rows) < 3:
            errors.append(f"{issue.title}: 기사가 {len(rows)}개입니다. 최소 3개가 필요합니다.")
        if source_count < 3:
            errors.append(f"{issue.title}: 출처가 {source_count}개입니다. 최소 3개가 필요합니다.")
        if manifest is not None and media_source_count < 2:
            errors.append(
                f"{issue.title}: 언론 출처가 {media_source_count}개입니다. 최소 2개가 필요합니다."
            )
        if trusted_count != len(rows):
            errors.append(
                f"{issue.title}: 신뢰 분석 {trusted_count}/{len(rows)}개로 100%가 아닙니다."
            )
        if synthetic_count:
            errors.append(
                f"{issue.title}: synthetic/dummy 분석 {synthetic_count}개가 연결되어 있습니다."
            )
        if data_as_of is None:
            errors.append(f"{issue.title}: 데이터 기준 시각을 계산할 수 없습니다.")
        elif now - ensure_utc(data_as_of) > timedelta(days=max_age_days):
            warnings.append(
                f"{issue.title}: 최신 데이터가 {max_age_days}일 임계값보다 오래되었습니다."
            )

    queue: dict[str, int] = {}
    showcase_jobs = list(
        (
            await session.scalars(
                select(Job).where(Job.dedupe_key.like("showcase:%"))
            )
        ).all()
    )
    for job in showcase_jobs:
        status = str(getattr(job.status, "value", job.status))
        payload = job.payload_json if isinstance(job.payload_json, dict) else {}
        if (
            status in {"FAILED", "DEAD", "CANCELLED"}
            and job.job_type == "analyze"
            and str(payload.get("article_version_id") or "")
            in ready_article_version_ids
        ):
            # The regular crawl pipeline and the showcase refresh can race to
            # analyze the same imported version under different dedupe keys.
            # A terminal duplicate is resolved once that exact version has a
            # trusted OpenAI assessment and matching active score.
            continue
        queue[status] = queue.get(status, 0) + 1
    if queue.get("DEAD", 0) or queue.get("FAILED", 0):
        errors.append("showcase crawl/analyze 작업에 실패 또는 DEAD 작업이 남아 있습니다.")
    if queue.get("PENDING", 0) or queue.get("LEASED", 0):
        errors.append("showcase crawl/analyze queue가 아직 drain되지 않았습니다.")
    return AuditResult(reports, errors, warnings, queue)


async def comparison_review_status(
    session: AsyncSession,
    manifest: ShowcaseManifest,
) -> dict[str, Any]:
    """Return limited, non-secret comparison material for operator review."""

    results: list[dict[str, Any]] = []
    for manifest_issue in sorted(manifest.issues, key=lambda item: item.featured_rank):
        issue = await session.scalar(
            select(Issue).where(Issue.editorial_key == manifest_issue.key)
        )
        if issue is None:
            results.append(
                {
                    "editorial_key": manifest_issue.key,
                    "title": manifest_issue.title,
                    "status": "MISSING_ISSUE",
                }
            )
            continue

        snapshot = await session.scalar(
            select(IssueComparisonSnapshot)
            .where(
                IssueComparisonSnapshot.issue_id == issue.id,
                IssueComparisonSnapshot.issue_version == issue.version,
            )
            .order_by(
                IssueComparisonSnapshot.created_at.desc(),
                IssueComparisonSnapshot.id.desc(),
            )
        )
        job = await session.scalar(
            select(Job)
            .where(
                Job.job_type == "build_issue_comparison",
                Job.dedupe_key.like(f"%:comparison:{issue.id}:%"),
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
        )
        article_rows = list(
            (
                await session.execute(
                    select(Article, Source)
                    .join(IssueMembership, IssueMembership.article_id == Article.id)
                    .join(Source, Source.id == Article.source_id)
                    .where(IssueMembership.issue_id == issue.id)
                    .order_by(Article.id)
                )
            ).all()
        )
        model = (
            await session.get(ModelAlias, snapshot.model_alias_id)
            if snapshot is not None
            else None
        )
        last_error_code = None
        last_error_message = None
        if job is not None and isinstance(job.last_error_json, dict):
            last_error_code = job.last_error_json.get("code")
            message = job.last_error_json.get("message")
            if isinstance(message, str):
                last_error_message = message[:500]
        results.append(
            {
                "editorial_key": manifest_issue.key,
                "title": issue.title,
                "issue_id": issue.id,
                "issue_version": issue.version,
                "articles": [
                    {
                        "article_id": article.id,
                        "article_version_id": article.current_version_id,
                        "source": source.name,
                        "title": article.title,
                        "canonical_url": article.canonical_url,
                    }
                    for article, source in article_rows
                ],
                "job": {
                    "id": job.id,
                    "status": str(getattr(job.status, "value", job.status)),
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "last_error_code": last_error_code,
                    "last_error_message": last_error_message,
                    "created_at": job.created_at.isoformat(),
                    "updated_at": job.updated_at.isoformat(),
                }
                if job is not None
                else None,
                "snapshot": {
                    "snapshot_id": snapshot.id,
                    "status": str(getattr(snapshot.status, "value", snapshot.status)),
                    "prompt_version": snapshot.prompt_version,
                    "model_alias": model.alias if model is not None else None,
                    "actual_model_id": model.actual_model_id if model is not None else None,
                    "confidence": float(snapshot.confidence),
                    "common_facts": snapshot.common_facts_json,
                    "dimensions": snapshot.framing_dimensions_json,
                    "article_frames": snapshot.article_frames_json,
                    "created_at": snapshot.created_at.isoformat(),
                    "reviewed_at": snapshot.reviewed_at.isoformat()
                    if snapshot.reviewed_at is not None
                    else None,
                    "reviewed_by": snapshot.reviewed_by,
                }
                if snapshot is not None
                else None,
            }
        )
    return {
        "manifest_version": manifest.version,
        "issues": results,
        "ready_for_admin_review": all(
            isinstance(item.get("snapshot"), dict)
            and item["snapshot"].get("status") == "SUCCEEDED"
            for item in results
        ),
    }


async def _run_with_database(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest)) if getattr(args, "manifest", None) else None
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            if args.command == "preflight":
                assert manifest is not None
                preflight_result = await preflight_showcase(session, manifest)
                print(json.dumps(preflight_result, ensure_ascii=False, indent=2, default=str))
                return 0 if preflight_result["status"] == "passed" else 1
            try:
                actual_revision = await session.scalar(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
            except SQLAlchemyError:
                actual_revision = None
            if actual_revision != REQUIRED_DB_REVISION:
                print(
                    json.dumps(
                        {
                            "status": "failed",
                            "required_schema_revision": REQUIRED_DB_REVISION,
                            "actual_schema_revision": actual_revision,
                            "errors": [
                                "Phase 1 migration is not applied; run the reviewed backup/migration procedure first."
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1
            if args.command == "refresh":
                assert manifest is not None
                summary = await refresh_showcase(
                    session,
                    manifest,
                    apply=not args.dry_run,
                    backup_reference=args.backup_reference,
                )
                print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))
                return 0
            if args.command == "comparisons":
                assert manifest is not None
                comparison_status = await comparison_review_status(session, manifest)
                print(json.dumps(comparison_status, ensure_ascii=False, indent=2, default=str))
                return 0
            audit_result = await audit_showcase(
                session,
                manifest=manifest,
                max_age_days=args.max_age_days,
            )
            print(json.dumps(audit_result.as_dict(), ensure_ascii=False, indent=2))
            return 0 if args.allow_stale and audit_result.exit_code == 2 else audit_result.exit_code
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Showcase refresh and trust audit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    refresh = subparsers.add_parser("refresh")
    refresh.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    refresh.add_argument("--dry-run", action="store_true")
    refresh.add_argument("--backup-reference")
    comparisons = subparsers.add_parser("comparisons")
    comparisons.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    audit = subparsers.add_parser("audit")
    audit.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    audit.add_argument("--max-age-days", type=int, default=7)
    audit.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "refresh" and not args.dry_run and not args.backup_reference:
        parser.error("refresh mutation requires --backup-reference")
    return asyncio.run(_run_with_database(args))


if __name__ == "__main__":
    raise SystemExit(main())
