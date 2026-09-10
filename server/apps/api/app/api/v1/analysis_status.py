"""Public, non-promissory readiness reasons for issue and article analysis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from apps.api.app.api.v1.dependencies import get_repository, get_state
from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.errors import COMMON_ERROR_RESPONSES, ApiError
from apps.api.app.db.enums import IssueKind, IssueStatus
from apps.api.app.db.models import (
    Article,
    ArticleVersion,
    Issue,
    Job,
    JobReceipt,
    StoredBlob,
)
from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.state import PlatformState
from apps.worker.worker.analysis_eligibility import assess_analysis_eligibility

router = APIRouter(prefix="/api/v1", responses=COMMON_ERROR_RESPONSES)


class ReadinessStatus(StrEnum):
    READY = "READY"
    PROCESSING = "PROCESSING"
    DEFERRED = "DEFERRED"
    NOT_SCHEDULED = "NOT_SCHEDULED"
    UNAVAILABLE = "UNAVAILABLE"
    WAITING_FOR_ELIGIBLE_CONTENT = "WAITING_FOR_ELIGIBLE_CONTENT"


class ReadinessReason(StrEnum):
    ANALYSIS_AVAILABLE = "ANALYSIS_AVAILABLE"
    ANALYSIS_RUNNING = "ANALYSIS_RUNNING"
    QUEUED_FOR_ANALYSIS = "QUEUED_FOR_ANALYSIS"
    DAILY_SELECTION_DEFERRED = "DAILY_SELECTION_DEFERRED"
    CONTENT_NOT_ELIGIBLE = "CONTENT_NOT_ELIGIBLE"
    SOURCE_CONTENT_UNAVAILABLE = "SOURCE_CONTENT_UNAVAILABLE"
    NOT_SELECTED_FOR_DAILY_ANALYSIS = "NOT_SELECTED_FOR_DAILY_ANALYSIS"
    ANALYSIS_RESULT_UNAVAILABLE = "ANALYSIS_RESULT_UNAVAILABLE"
    CURRENT_EVENT_AVAILABLE = "CURRENT_EVENT_AVAILABLE"
    EVENT_ANALYSIS_IN_PROGRESS = "EVENT_ANALYSIS_IN_PROGRESS"
    EVENT_CANDIDATE_NEEDS_MORE_SOURCES = "EVENT_CANDIDATE_NEEDS_MORE_SOURCES"
    NO_ELIGIBLE_EVENT = "NO_ELIGIBLE_EVENT"


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisReadiness(_ContractModel):
    status: ReadinessStatus
    reason: ReadinessReason
    checked_at: datetime
    next_eligible_at: datetime | None = None


class OverallAnalysisReadiness(AnalysisReadiness):
    refresh_interval_seconds: int = Field(ge=60)


class ArticleAnalysisReadiness(AnalysisReadiness):
    article_id: str
    article_version_id: str | None = None


_CONTENT_SKIP_REASONS = {
    "ARTICLE_NO_LONGER_PUBLIC",
    "CONTENT_TOO_SHORT",
    "GENERIC_INDEX_TITLE",
    "STALE_ARTICLE_VERSION",
    "TITLE_TOO_SHORT",
}
_DAILY_DEFER_REASONS = {
    "DAILY_LLM_BUDGET_EXCEEDED",
    "ESSENTIAL_LLM_BUDGET_RESERVED",
}
_PUBLIC_CANDIDATE_MAX_AGE = timedelta(days=4)


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_payload(job: Any) -> dict[str, Any]:
    value = (
        job.get("payload_json", job.get("payload", {}))
        if isinstance(job, dict)
        else getattr(job, "payload_json", {})
    )
    return dict(value) if isinstance(value, dict) else {}


def _job_status(job: Any) -> str:
    value = job.get("status") if isinstance(job, dict) else getattr(job, "status", "")
    return _value(value).upper()


def _job_time(job: Any, field: str) -> datetime | None:
    value = job.get(field) if isinstance(job, dict) else getattr(job, field, None)
    return _as_utc(value)


def _readiness_from_jobs(
    jobs: list[Any],
    *,
    article_id: str,
    version_id: str | None,
    checked_at: datetime,
    receipt_results: dict[str, dict[str, Any]] | None = None,
) -> ArticleAnalysisReadiness | None:
    receipt_results = receipt_results or {}
    matching = [
        job
        for job in jobs
        if _job_payload(job).get("article_version_id") == version_id
    ]
    active = [job for job in matching if _job_status(job) in {"PENDING", "LEASED"}]
    leased = next((job for job in active if _job_status(job) == "LEASED"), None)
    if leased is not None:
        return ArticleAnalysisReadiness(
            article_id=article_id,
            article_version_id=version_id,
            status=ReadinessStatus.PROCESSING,
            reason=ReadinessReason.ANALYSIS_RUNNING,
            checked_at=checked_at,
        )
    ready = next(
        (
            job
            for job in active
            if (_job_time(job, "available_at") or checked_at) <= checked_at
        ),
        None,
    )
    if ready is not None:
        return ArticleAnalysisReadiness(
            article_id=article_id,
            article_version_id=version_id,
            status=ReadinessStatus.PROCESSING,
            reason=ReadinessReason.QUEUED_FOR_ANALYSIS,
            checked_at=checked_at,
        )
    if active:
        next_job = min(
            active,
            key=lambda item: _job_time(item, "available_at") or datetime.max.replace(tzinfo=UTC),
        )
        payload = _job_payload(next_job)
        is_daily_defer = (
            payload.get("budget_defer_reason") in _DAILY_DEFER_REASONS
            or payload.get("budget_defer_deadline") not in (None, "")
        )
        return ArticleAnalysisReadiness(
            article_id=article_id,
            article_version_id=version_id,
            status=(ReadinessStatus.DEFERRED if is_daily_defer else ReadinessStatus.PROCESSING),
            reason=(
                ReadinessReason.DAILY_SELECTION_DEFERRED
                if is_daily_defer
                else ReadinessReason.QUEUED_FOR_ANALYSIS
            ),
            checked_at=checked_at,
            next_eligible_at=_job_time(next_job, "available_at"),
        )

    matching.sort(
        key=lambda item: _job_time(item, "updated_at") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    for job in matching:
        job_id = str(job.get("id") if isinstance(job, dict) else getattr(job, "id", ""))
        result = receipt_results.get(job_id, {})
        skip_reason = str(result.get("skip_reason") or "")
        if skip_reason in _CONTENT_SKIP_REASONS:
            return ArticleAnalysisReadiness(
                article_id=article_id,
                article_version_id=version_id,
                status=ReadinessStatus.NOT_SCHEDULED,
                reason=ReadinessReason.CONTENT_NOT_ELIGIBLE,
                checked_at=checked_at,
            )
        last_error = (
            job.get("last_error_json", job.get("last_error"))
            if isinstance(job, dict)
            else getattr(job, "last_error_json", None)
        )
        if _job_status(job) in {"FAILED", "DEAD"} or last_error:
            return ArticleAnalysisReadiness(
                article_id=article_id,
                article_version_id=version_id,
                status=ReadinessStatus.UNAVAILABLE,
                reason=ReadinessReason.ANALYSIS_RESULT_UNAVAILABLE,
                checked_at=checked_at,
            )
        if _job_status(job) == "SUCCEEDED":
            # A completed analyze job without a public assessment must not be
            # presented as work that simply was not selected. Result receipts
            # intentionally retain only application metadata, so the public
            # contract uses the conservative unavailable reason here.
            return ArticleAnalysisReadiness(
                article_id=article_id,
                article_version_id=version_id,
                status=ReadinessStatus.UNAVAILABLE,
                reason=ReadinessReason.ANALYSIS_RESULT_UNAVAILABLE,
                checked_at=checked_at,
            )
    return None


def _memory_article_readiness(
    state: PlatformState,
    article_id: str,
    *,
    settings: Settings,
    checked_at: datetime,
) -> ArticleAnalysisReadiness:
    article = state.articles.get(article_id)
    if article is None:
        raise ApiError(404, "ARTICLE_NOT_FOUND", "The requested article was not found.")
    version_id = article.get("current_version_id")
    if str(article.get("analysis_status") or "").upper() == "READY":
        return ArticleAnalysisReadiness(
            article_id=article_id,
            article_version_id=version_id,
            status=ReadinessStatus.READY,
            reason=ReadinessReason.ANALYSIS_AVAILABLE,
            checked_at=checked_at,
        )
    queued = _readiness_from_jobs(
        list(state.jobs.values()),
        article_id=article_id,
        version_id=version_id,
        checked_at=checked_at,
    )
    if queued is not None:
        return queued
    content = article.get("content") or article.get("text")
    if not isinstance(content, str) or not content.strip():
        return ArticleAnalysisReadiness(
            article_id=article_id,
            article_version_id=version_id,
            status=ReadinessStatus.NOT_SCHEDULED,
            reason=ReadinessReason.SOURCE_CONTENT_UNAVAILABLE,
            checked_at=checked_at,
        )
    eligibility = assess_analysis_eligibility(
        str(article.get("title") or ""),
        content,
        minimum_content_chars=settings.llm_min_article_chars,
    )
    return ArticleAnalysisReadiness(
        article_id=article_id,
        article_version_id=version_id,
        status=ReadinessStatus.NOT_SCHEDULED,
        reason=(
            ReadinessReason.NOT_SELECTED_FOR_DAILY_ANALYSIS
            if eligibility.eligible
            else ReadinessReason.CONTENT_NOT_ELIGIBLE
        ),
        checked_at=checked_at,
    )


async def _persisted_article_readiness(
    repository: MariaDBPlatformRepository,
    article_id: str,
    *,
    settings: Settings,
    checked_at: datetime,
) -> ArticleAnalysisReadiness:
    public_article = await repository.article_view(article_id)
    if public_article is None:
        raise ApiError(404, "ARTICLE_NOT_FOUND", "The requested article was not found.")
    version_id = public_article.get("current_version_id")
    if str(public_article.get("analysis_status") or "").upper() == "READY":
        return ArticleAnalysisReadiness(
            article_id=article_id,
            article_version_id=version_id,
            status=ReadinessStatus.READY,
            reason=ReadinessReason.ANALYSIS_AVAILABLE,
            checked_at=checked_at,
        )

    session = repository.session
    job_rows = list(
        (
            await session.execute(
                select(Job, JobReceipt)
                .outerjoin(JobReceipt, JobReceipt.job_id == Job.id)
                .where(
                    Job.job_type == "analyze",
                    Job.payload_json["article_version_id"].as_string() == version_id,
                )
                .order_by(Job.updated_at.desc(), Job.id.desc())
            )
        ).all()
    )
    jobs = [job for job, _receipt in job_rows]
    receipts = {
        str(job.id): dict(receipt.result_json)
        for job, receipt in job_rows
        if receipt is not None and isinstance(receipt.result_json, dict)
    }
    queued = _readiness_from_jobs(
        jobs,
        article_id=article_id,
        version_id=version_id,
        checked_at=checked_at,
        receipt_results=receipts,
    )
    if queued is not None:
        return queued

    article = await session.get(Article, article_id)
    version = await session.get(ArticleVersion, version_id) if version_id else None
    blob = (
        await session.get(StoredBlob, version.normalized_text_ref)
        if version is not None and version.normalized_text_ref
        else None
    )
    if article is None or blob is None:
        return ArticleAnalysisReadiness(
            article_id=article_id,
            article_version_id=version_id,
            status=ReadinessStatus.NOT_SCHEDULED,
            reason=ReadinessReason.SOURCE_CONTENT_UNAVAILABLE,
            checked_at=checked_at,
        )
    content = bytes(blob.payload).decode("utf-8", errors="replace")
    eligibility = assess_analysis_eligibility(
        article.title,
        content,
        minimum_content_chars=settings.llm_min_article_chars,
    )
    return ArticleAnalysisReadiness(
        article_id=article_id,
        article_version_id=version_id,
        status=ReadinessStatus.NOT_SCHEDULED,
        reason=(
            ReadinessReason.NOT_SELECTED_FOR_DAILY_ANALYSIS
            if eligibility.eligible
            else ReadinessReason.CONTENT_NOT_ELIGIBLE
        ),
        checked_at=checked_at,
    )


@router.get(
    "/analysis-status",
    response_model=OverallAnalysisReadiness,
    operation_id="get_analysis_status",
)
async def get_analysis_status(
    settings: Settings = Depends(get_settings),
    state: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> OverallAnalysisReadiness:
    checked_at = datetime.now(UTC)
    if repository is None:
        events = [
            issue
            for issue in state.issues.values()
            if str(issue.get("kind") or "").upper() == "EVENT"
            and str(issue.get("status") or "").lower()
            not in {"merged", "closed", "archived"}
        ]
        ready = any(
            str(issue.get("analysis_status") or "").upper() == "READY"
            for issue in events
        )
        visible_event = bool(events)
        candidate = False
    else:
        session = repository.session
        public_events = [
            issue
            for issue in await repository.list_issue_rows()
            if str(issue.get("kind") or "").upper() == "EVENT"
        ]
        ready = any(
            str(issue.get("analysis_status") or "").upper() == "READY"
            for issue in public_events
        )
        visible_event = bool(public_events)
        candidate = bool(
            await session.scalar(
                select(func.count())
                .select_from(Issue)
                .where(
                    Issue.issue_kind == IssueKind.EVENT,
                    Issue.status == IssueStatus.CANDIDATE,
                    Issue.last_activity_at
                    >= checked_at - _PUBLIC_CANDIDATE_MAX_AGE,
                )
            )
        )

    if ready:
        status = ReadinessStatus.READY
        reason = ReadinessReason.CURRENT_EVENT_AVAILABLE
    elif visible_event:
        status = ReadinessStatus.PROCESSING
        reason = ReadinessReason.EVENT_ANALYSIS_IN_PROGRESS
    elif candidate:
        status = ReadinessStatus.PROCESSING
        reason = ReadinessReason.EVENT_CANDIDATE_NEEDS_MORE_SOURCES
    else:
        status = ReadinessStatus.WAITING_FOR_ELIGIBLE_CONTENT
        reason = ReadinessReason.NO_ELIGIBLE_EVENT
    return OverallAnalysisReadiness(
        status=status,
        reason=reason,
        checked_at=checked_at,
        next_eligible_at=None,
        refresh_interval_seconds=round(settings.worker_crawl_interval_seconds),
    )


@router.get(
    "/articles/{article_id}/analysis-status",
    response_model=ArticleAnalysisReadiness,
    operation_id="get_article_analysis_status",
)
async def get_article_analysis_status(
    article_id: str,
    settings: Settings = Depends(get_settings),
    state: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> ArticleAnalysisReadiness:
    checked_at = datetime.now(UTC)
    if repository is None:
        return _memory_article_readiness(
            state,
            article_id,
            settings=settings,
            checked_at=checked_at,
        )
    return await _persisted_article_readiness(
        repository,
        article_id,
        settings=settings,
        checked_at=checked_at,
    )


__all__ = [
    "AnalysisReadiness",
    "ArticleAnalysisReadiness",
    "OverallAnalysisReadiness",
    "ReadinessReason",
    "ReadinessStatus",
    "get_analysis_status",
    "get_article_analysis_status",
    "router",
]
