from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.api.v1.analysis_status import (
    _persisted_article_readiness,
    _readiness_from_jobs,
    get_analysis_status,
    router,
)
from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.core.config import Settings
from apps.api.app.core.errors import install_error_handlers
from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    ArticleStatus,
    IssueKind,
    IssueStatus,
    JobStatus,
    SourcePolicyStatus,
    SourceType,
)
from apps.api.app.db.models import (
    Article,
    ArticleVersion,
    Issue,
    IssueMembership,
    Job,
    Source,
    StoredBlob,
)
from apps.api.app.db.ulid import new_ulid
from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.state import PlatformState


def _test_app(state: PlatformState) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_state] = lambda: state
    return app


def test_memory_readiness_reports_current_event_and_article_state() -> None:
    state = PlatformState()
    article_id = next(iter(state.articles))
    client = TestClient(_test_app(state))

    overview = client.get("/api/v1/analysis-status")
    assert overview.status_code == 200
    assert overview.json()["status"] == "READY"
    assert overview.json()["reason"] == "CURRENT_EVENT_AVAILABLE"
    assert overview.json()["refresh_interval_seconds"] == 86400
    assert overview.json()["next_eligible_at"] is None

    article = client.get(f"/api/v1/articles/{article_id}/analysis-status")
    assert article.status_code == 200
    assert article.json()["status"] == "READY"
    assert article.json()["reason"] == "ANALYSIS_AVAILABLE"


def test_memory_readiness_distinguishes_deferred_from_not_selected() -> None:
    state = PlatformState()
    article_id = next(iter(state.articles))
    article = state.articles[article_id]
    version_id = article["current_version_id"]
    article["analysis_status"] = "PROCESSING"
    article["content"] = "공공 정책을 다루는 충분한 기사 본문입니다. " * 40
    state.assessments.pop(article_id, None)
    state.scores.pop(article_id, None)
    available_at = datetime.now(UTC) + timedelta(hours=6)
    job_id = new_ulid()
    state.jobs[job_id] = {
        "id": job_id,
        "job_type": "analyze",
        "status": "PENDING",
        "available_at": available_at,
        "updated_at": datetime.now(UTC),
        "payload": {
            "article_version_id": version_id,
            "budget_defer_reason": "ESSENTIAL_LLM_BUDGET_RESERVED",
        },
    }
    client = TestClient(_test_app(state))

    deferred = client.get(f"/api/v1/articles/{article_id}/analysis-status")
    assert deferred.status_code == 200
    assert deferred.json()["status"] == "DEFERRED"
    assert deferred.json()["reason"] == "DAILY_SELECTION_DEFERRED"
    assert deferred.json()["next_eligible_at"] is not None

    state.jobs.clear()
    not_selected = client.get(f"/api/v1/articles/{article_id}/analysis-status")
    assert not_selected.status_code == 200
    assert not_selected.json()["status"] == "NOT_SCHEDULED"
    assert not_selected.json()["reason"] == "NOT_SELECTED_FOR_DAILY_ANALYSIS"
    assert not_selected.json()["next_eligible_at"] is None


@pytest.mark.parametrize("violation", ["legacy", "sports", "insufficient_sources", "expired", "unfetched"])
def test_memory_readiness_excludes_hidden_content(violation: str) -> None:
    state = PlatformState()
    issue = next(iter(state.issues.values()))
    article_id = issue["article_ids"][0]
    if violation == "legacy":
        issue.pop("editorial_key", None)
    elif violation == "sports":
        issue["topic"] = "스포츠"
    elif violation == "insufficient_sources":
        issue["article_ids"] = issue["article_ids"][:2]
    elif violation == "expired":
        state.articles[issue["article_ids"][-1]]["published_at"] = datetime.now(UTC) - timedelta(days=8)
    else:
        state.articles[issue["article_ids"][-1]]["current_version_id"] = None
    client = TestClient(_test_app(state))
    overview = client.get("/api/v1/analysis-status")
    assert overview.status_code == 200
    assert overview.json()["status"] == "WAITING_FOR_ELIGIBLE_CONTENT"
    assert overview.json()["reason"] == "NO_ELIGIBLE_EVENT"
    article = client.get(f"/api/v1/articles/{article_id}/analysis-status")
    assert article.status_code == 404
    assert article.json()["error"]["code"] == "ARTICLE_NOT_FOUND"


def test_completed_job_without_public_assessment_is_unavailable() -> None:
    now = datetime.now(UTC)
    result = _readiness_from_jobs(
        [
            {
                "id": new_ulid(),
                "job_type": "analyze",
                "status": "SUCCEEDED",
                "updated_at": now,
                "payload": {"article_version_id": "version-1"},
            }
        ],
        article_id="article-1",
        version_id="version-1",
        checked_at=now,
    )

    assert result is not None
    assert result.status == "UNAVAILABLE"
    assert result.reason == "ANALYSIS_RESULT_UNAVAILABLE"
    assert result.next_eligible_at is None


@pytest.mark.asyncio
async def test_persisted_overview_ignores_stale_event_candidates() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    async with factory() as session:
        session.add(
            Issue(
                id=new_ulid(),
                title="Stale candidate",
                summary="정책 개편을 둘러싼 논쟁",
                topic="정치",
                editorial_key="daily-issue:readiness-candidate",
                status=IssueStatus.CANDIDATE,
                issue_kind=IssueKind.EVENT,
                opened_at=now - timedelta(days=9),
                last_activity_at=now - timedelta(days=8),
                version=1,
            )
        )
        await session.commit()
        repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        settings = Settings(
            app_env="test",
            app_backend="memory",
            session_secret="x" * 40,
            oauth_redirect_allowlist="http://localhost:3000/auth/callback",
        )
        stale = await get_analysis_status(
            settings=settings,
            state=PlatformState(),
            repository=repository,
        )
        assert stale.reason == "NO_ELIGIBLE_EVENT"

        issue = await session.scalar(select(Issue))
        assert issue is not None
        issue.last_activity_at = now
        await session.commit()
        current = await get_analysis_status(
            settings=settings,
            state=PlatformState(),
            repository=repository,
        )
        assert current.reason == "EVENT_CANDIDATE_NEEDS_MORE_SOURCES"
        issue.editorial_key = None
        await session.commit()
        uncurated = await get_analysis_status(settings=settings, state=PlatformState(), repository=repository)
        assert uncurated.reason == "NO_ELIGIBLE_EVENT"

    await engine.dispose()


@pytest.mark.asyncio
async def test_persisted_readiness_uses_deferred_job_timestamp() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    available_at = now + timedelta(hours=8)
    source_id, article_id, version_id, blob_id, job_id = (new_ulid() for _ in range(5))
    body = ("정부 정책과 국회 논의를 설명하는 기사 본문입니다. " * 50).encode()
    url = "https://readiness.example.test/article"

    async with factory() as session:
        session.add(
            Source(
                id=source_id,
                name="Readiness Source",
                source_type=SourceType.RSS,
                canonical_url="https://readiness.example.test",
                policy_status=SourcePolicyStatus.APPROVED,
                robots_status=SourcePolicyStatus.APPROVED,
                terms_status=SourcePolicyStatus.APPROVED,
                active=True,
            )
        )
        session.add(
            Article(
                id=article_id,
                source_id=source_id,
                canonical_url=url,
                canonical_url_hash=hashlib.sha256(url.encode()).digest(),
                title="정부 정책과 국회 논의를 다룬 오늘의 기사",
                author=None,
                published_at=now,
                current_version_id=None,
                status=ArticleStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            StoredBlob(
                id=blob_id,
                sha256=hashlib.sha256(body).digest(),
                mime_type="text/plain; charset=utf-8",
                byte_size=len(body),
                payload=body,
                expires_at=None,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            ArticleVersion(
                id=version_id,
                article_id=article_id,
                content_hash=hashlib.sha256(body).digest(),
                normalized_text_ref=blob_id,
                fetched_at=now,
                modified_at=now,
            )
        )
        await session.flush()
        article = await session.get(Article, article_id)
        assert article is not None
        article.current_version_id = version_id
        session.add(
            Job(
                id=job_id,
                job_type="analyze",
                dedupe_key=f"analysis:{version_id}",
                status=JobStatus.PENDING,
                priority=0,
                available_at=available_at,
                lease_owner=None,
                lease_expires_at=None,
                attempts=0,
                max_attempts=3,
                payload_json={
                    "article_version_id": version_id,
                    "budget_defer_reason": "DAILY_LLM_BUDGET_EXCEEDED",
                },
                last_error_json=None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

        issue_id = new_ulid()
        session.add(Issue(id=issue_id, title="Policy readiness issue", summary="Policy debate", topic="정치",
                          issue_kind=IssueKind.EVENT, status=IssueStatus.ACTIVE, editorial_key="daily-issue:readiness",
                          opened_at=now, last_activity_at=now))
        await session.flush()
        session.add(IssueMembership(issue_id=issue_id, article_id=article_id, confidence=1))
        for index in range(2):
            support_source_id, support_article_id = new_ulid(), new_ulid()
            support_url = f"https://support{index}.co.kr/report"
            session.add(Source(id=support_source_id, name=f"Support {index}", source_type=SourceType.RSS,
                               canonical_url=support_url, active=True, policy_status=SourcePolicyStatus.APPROVED))
            session.add(Article(id=support_article_id, source_id=support_source_id, canonical_url=support_url,
                                canonical_url_hash=hashlib.sha256(support_url.encode()).digest(), title="Policy debate",
                                published_at=now, status=ArticleStatus.ACTIVE))
            await session.flush()
            support_version_id = new_ulid()
            session.add(ArticleVersion(id=support_version_id, article_id=support_article_id,
                                       content_hash=hashlib.sha256(support_article_id.encode()).digest(),
                                       normalized_text_ref="fixture://support", fetched_at=now))
            await session.flush()
            support_article = await session.get(Article, support_article_id)
            support_article.current_version_id = support_version_id
            session.add(IssueMembership(issue_id=issue_id, article_id=support_article_id, confidence=1))
        await session.commit()
        repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        result = await _persisted_article_readiness(
            repository,
            article_id,
            settings=Settings(
                app_env="test",
                app_backend="memory",
                session_secret="x" * 40,
                oauth_redirect_allowlist="http://localhost:3000/auth/callback",
            ),
            checked_at=now,
        )
        assert result.status == "DEFERRED"
        assert result.reason == "DAILY_SELECTION_DEFERRED"
        assert result.next_eligible_at == available_at

    await engine.dispose()
