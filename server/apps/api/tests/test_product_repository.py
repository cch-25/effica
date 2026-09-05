from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    ArticleStatus,
    AssessmentStatus,
    ComparisonSnapshotStatus,
    IssueStatus,
    JobStatus,
    ModelStatus,
    ProfileKind,
    QuestionnaireKind,
    RevisionStatus,
    ScoreStatus,
    ShareCardStatus,
    SourcePolicyStatus,
    SourceType,
    UserRole,
    UserStatus,
)
from apps.api.app.db.models import (
    Article,
    ArticleVersion,
    Issue,
    IssueComparisonSnapshot,
    IssueMembership,
    Job,
    ModelAlias,
    ModelAssessment,
    QuestionnaireVersion,
    ScoreVersion,
    ShareCard,
    Source,
    User,
    UserProfile,
    WeightProfileRevision,
)
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.repositories.product import ProductComparisonError


@pytest.mark.asyncio
async def test_public_issues_and_comparisons_enforce_rolling_four_day_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)
    monkeypatch.setattr("apps.api.app.repositories.product.utc_now", lambda: now)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        source_id, alias_id, fresh_issue_id, stale_issue_id = (
            new_ulid() for _ in range(4)
        )
        fresh_article_id, stale_article_id, undated_article_id, stale_issue_article_id = (
            new_ulid() for _ in range(4)
        )
        session.add_all(
            [
                Source(
                    id=source_id,
                    name="Freshness Source",
                    source_type=SourceType.RSS,
                    canonical_url="https://freshness.example.test",
                    policy_status=SourcePolicyStatus.APPROVED,
                    robots_status=SourcePolicyStatus.APPROVED,
                    terms_status=SourcePolicyStatus.APPROVED,
                    active=True,
                ),
                ModelAlias(
                    id=alias_id,
                    alias="freshness-openai",
                    provider="openai",
                    actual_model_id="gpt-5-mini",
                    status=ModelStatus.ACTIVE,
                    config_json={},
                ),
                Issue(
                    id=fresh_issue_id,
                    title="Fresh public issue",
                    summary="Fresh summary",
                    status=IssueStatus.ACTIVE,
                    opened_at=now - timedelta(days=4),
                    last_activity_at=now - timedelta(days=4),
                    version=1,
                ),
                Issue(
                    id=stale_issue_id,
                    title="Stale public issue",
                    summary="Stale summary",
                    status=IssueStatus.ACTIVE,
                    opened_at=now - timedelta(days=5),
                    last_activity_at=now - timedelta(days=4, microseconds=1),
                    version=1,
                ),
            ]
        )
        await session.flush()

        def article(
            article_id: str,
            slug: str,
            published_at: datetime | None,
        ) -> Article:
            url = f"https://freshness.example.test/{slug}"
            return Article(
                id=article_id,
                source_id=source_id,
                canonical_url=url,
                canonical_url_hash=hashlib.sha256(url.encode()).digest(),
                title=slug,
                author=None,
                published_at=published_at,
                current_version_id=None,
                status=ArticleStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )

        session.add_all(
            [
                article(fresh_article_id, "four-day-boundary", now - timedelta(days=4)),
                article(
                    stale_article_id,
                    "older-than-four-days",
                    now - timedelta(days=4, microseconds=1),
                ),
                article(undated_article_id, "missing-publication-date", None),
                article(stale_issue_article_id, "fresh-article-in-stale-issue", now),
            ]
        )
        await session.flush()
        session.add_all(
            [
                IssueMembership(
                    issue_id=fresh_issue_id,
                    article_id=article_id,
                    confidence=0.9,
                    created_at=now,
                )
                for article_id in (
                    fresh_article_id,
                    stale_article_id,
                    undated_article_id,
                )
            ]
            + [
                IssueMembership(
                    issue_id=stale_issue_id,
                    article_id=stale_issue_article_id,
                    confidence=0.9,
                    created_at=now,
                ),
                IssueComparisonSnapshot(
                    id=new_ulid(),
                    issue_id=fresh_issue_id,
                    issue_version=1,
                    prompt_version="issue-comparison-v1",
                    model_alias_id=alias_id,
                    common_facts_json={"common_facts": []},
                    framing_dimensions_json={"dimensions": []},
                    article_frames_json={
                        "article_frames": {},
                        "article_version_ids": {},
                    },
                    confidence=0.8,
                    status=ComparisonSnapshotStatus.SUCCEEDED,
                    reviewed_at=now,
                    reviewed_by=None,
                    created_at=now,
                ),
            ]
        )
        await session.commit()

        issues = await repository.list_issue_rows()
        assert [row["id"] for row in issues] == [fresh_issue_id]
        assert issues[0]["article_ids"] == [fresh_article_id]
        assert issues[0]["source_count"] == 1

        articles = await repository.issue_article_rows(fresh_issue_id)
        assert articles is not None
        assert [row["id"] for row in articles] == [fresh_article_id]
        assert await repository.issue_view(stale_issue_id) is None
        assert await repository.issue_article_rows(stale_issue_id) is None
        assert (
            await repository.issue_comparison_view(
                issue_id=stale_issue_id,
                article_ids=[stale_issue_article_id],
            )
            is None
        )
        with pytest.raises(ProductComparisonError) as exc_info:
            await repository.issue_comparison_view(
                issue_id=fresh_issue_id,
                article_ids=[fresh_article_id, stale_article_id],
            )
        assert exc_info.value.code == "COMPARE_ARTICLE_OUTSIDE_ISSUE"

    await engine.dispose()


@pytest.mark.asyncio
async def test_public_feed_enforces_four_day_article_cutoff_without_stale_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)
    monkeypatch.setattr("apps.api.app.repositories.product.utc_now", lambda: now)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        approved_source_id, rejected_source_id, alias_id, weight_id = (
            new_ulid() for _ in range(4)
        )
        session.add_all(
            [
                Source(
                    id=approved_source_id,
                    name="Approved feed source",
                    source_type=SourceType.RSS,
                    canonical_url="https://approved-feed.example.test",
                    policy_status=SourcePolicyStatus.APPROVED,
                    robots_status=SourcePolicyStatus.APPROVED,
                    terms_status=SourcePolicyStatus.APPROVED,
                    active=True,
                ),
                Source(
                    id=rejected_source_id,
                    name="Rejected feed source",
                    source_type=SourceType.RSS,
                    canonical_url="https://rejected-feed.example.test",
                    policy_status=SourcePolicyStatus.REJECTED,
                    robots_status=SourcePolicyStatus.REJECTED,
                    terms_status=SourcePolicyStatus.REJECTED,
                    active=False,
                ),
                ModelAlias(
                    id=alias_id,
                    alias="feed-freshness-openai",
                    provider="openai",
                    actual_model_id="gpt-5-mini",
                    status=ModelStatus.ACTIVE,
                    config_json={},
                ),
                WeightProfileRevision(
                    id=weight_id,
                    revision=1,
                    status=RevisionStatus.ACTIVE,
                    weights_json={"model": 1.0},
                    guardrails_json={},
                    based_on_revision_id=None,
                    created_by=None,
                    created_at=now,
                    published_at=now,
                ),
            ]
        )
        await session.flush()

        async def add_analyzed_article(
            slug: str,
            published_at: datetime | None,
            *,
            source_id: str = approved_source_id,
            status: ArticleStatus = ArticleStatus.ACTIVE,
        ) -> str:
            article_id, version_id, assessment_id, score_id = (
                new_ulid() for _ in range(4)
            )
            url = f"https://feed.example.test/{slug}"
            article = Article(
                id=article_id,
                source_id=source_id,
                canonical_url=url,
                canonical_url_hash=hashlib.sha256(url.encode()).digest(),
                title=slug,
                author=None,
                published_at=published_at,
                current_version_id=None,
                status=status,
                created_at=now,
                updated_at=now,
            )
            session.add(article)
            await session.flush()
            session.add(
                ArticleVersion(
                    id=version_id,
                    article_id=article_id,
                    content_hash=hashlib.sha256(f"body-{slug}".encode()).digest(),
                    normalized_text_ref=f"fixture://{slug}",
                    fetched_at=now,
                    modified_at=None,
                )
            )
            await session.flush()
            article.current_version_id = version_id
            session.add_all(
                [
                    ModelAssessment(
                        id=assessment_id,
                        article_version_id=version_id,
                        model_alias_id=alias_id,
                        prompt_version="feed-freshness-v1",
                        x=0,
                        y=0,
                        z=0,
                        sensationalism=20,
                        confidence=0.8,
                        evidence_json={"rationale_summary": "검증된 분석"},
                        token_usage=100,
                        latency_ms=50,
                        status=AssessmentStatus.SUCCEEDED,
                        created_at=now,
                    ),
                    ScoreVersion(
                        id=score_id,
                        article_version_id=version_id,
                        weight_revision_id=weight_id,
                        x=0,
                        y=0,
                        z=0,
                        sensationalism=20,
                        confidence=0.8,
                        components_json={
                            "analysis_provider": "openai",
                            "assessment_ids": [assessment_id],
                        },
                        status=ScoreStatus.ACTIVE,
                        created_at=now,
                    ),
                ]
            )
            return article_id

        boundary_id = await add_analyzed_article(
            "exact-four-day-boundary",
            now - timedelta(days=4),
        )
        stale_id = await add_analyzed_article(
            "older-than-four-days",
            now - timedelta(days=4, microseconds=1),
        )
        undated_id = await add_analyzed_article("missing-publication-date", None)
        inactive_id = await add_analyzed_article(
            "inactive-article",
            now,
            status=ArticleStatus.BLOCKED,
        )
        rejected_source_article_id = await add_analyzed_article(
            "rejected-source",
            now,
            source_id=rejected_source_id,
        )
        await session.commit()

        feed, personalized = await repository.feed_items(
            user_id=None,
            personalized_requested=False,
        )

        assert personalized is False
        assert [item["article_id"] for item in feed] == [boundary_id]
        excluded_ids = {
            stale_id,
            undated_id,
            inactive_id,
            rejected_source_article_id,
        }
        assert excluded_ids.isdisjoint(item["article_id"] for item in feed)

    await engine.dispose()


@pytest.mark.asyncio
async def test_db_product_engagement_vertical_slice() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        user_id, source_id, article_id, version_id, issue_id, weight_id, alias_id, assessment_id = (
            new_ulid() for _ in range(8)
        )
        now = utc_now()
        session.add_all(
            [
                User(
                    id=user_id,
                    role=UserRole.MEMBER,
                    status=UserStatus.ACTIVE,
                    display_name="Test Member",
                    created_at=now,
                    deleted_at=None,
                ),
                Source(
                    id=source_id,
                    name="Fixture Source",
                    source_type=SourceType.RSS,
                    canonical_url="https://example.test",
                    policy_status=SourcePolicyStatus.APPROVED,
                    robots_status=SourcePolicyStatus.APPROVED,
                    terms_status=SourcePolicyStatus.APPROVED,
                    active=True,
                ),
                Issue(
                    id=issue_id,
                    title="Fixture issue",
                    summary="Summary",
                    status=IssueStatus.ACTIVE,
                    opened_at=now,
                    last_activity_at=now,
                    version=1,
                ),
                WeightProfileRevision(
                    id=weight_id,
                    revision=1,
                    status=RevisionStatus.ACTIVE,
                    weights_json={"model": 1.0},
                    guardrails_json={},
                    based_on_revision_id=None,
                    created_by=user_id,
                    created_at=now,
                    published_at=now,
                ),
                ModelAlias(
                    id=alias_id,
                    alias="phase-1-openai",
                    provider="openai",
                    actual_model_id="gpt-5-mini",
                    status=ModelStatus.ACTIVE,
                    config_json={},
                ),
                QuestionnaireVersion(
                    id=new_ulid(),
                    kind=QuestionnaireKind.EFFICACY,
                    version="efficacy-v1",
                    schema_json={"scale": [0, 100]},
                    scoring_json={"method": "mean"},
                    active_from=now,
                ),
                UserProfile(
                    id=new_ulid(),
                    user_id=user_id,
                    kind=ProfileKind.SELF_REPORTED,
                    x=10,
                    y=-5,
                    z=3,
                    confidence=0.8,
                    source_version="onboarding-v1",
                    active=True,
                    created_at=now,
                ),
            ]
        )
        await session.flush()
        article = Article(
            id=article_id,
            source_id=source_id,
            canonical_url="https://example.test/a",
            canonical_url_hash=hashlib.sha256(b"https://example.test/a").digest(),
            title="Fixture article",
            author="Reporter",
            published_at=now,
            current_version_id=None,
            status=ArticleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        session.add(article)
        await session.flush()
        session.add(
            ArticleVersion(
                id=version_id,
                article_id=article_id,
                content_hash=hashlib.sha256(b"body").digest(),
                normalized_text_ref="fixture://body",
                fetched_at=now,
                modified_at=None,
            )
        )
        await session.flush()
        article.current_version_id = version_id
        session.add_all(
            [
                IssueMembership(
                    issue_id=issue_id,
                    article_id=article_id,
                    confidence=0.9,
                    created_at=now,
                ),
                ModelAssessment(
                    id=assessment_id,
                    article_version_id=version_id,
                    model_alias_id=alias_id,
                    prompt_version="phase-1-v1",
                    x=20,
                    y=0,
                    z=0,
                    sensationalism=25,
                    confidence=0.75,
                    evidence_json=[],
                    token_usage=100,
                    latency_ms=50,
                    status=AssessmentStatus.SUCCEEDED,
                    created_at=now,
                ),
                ScoreVersion(
                    id=new_ulid(),
                    article_version_id=version_id,
                    weight_revision_id=weight_id,
                    x=20,
                    y=-10,
                    z=5,
                    sensationalism=25,
                    confidence=0.75,
                    components_json={
                        "model": 1.0,
                        "분석방식": "LLM",
                        "모델평가ID": assessment_id,
                        "근거요약": "검증된 OpenAI 분석",
                    },
                    status=ScoreStatus.ACTIVE,
                    created_at=now,
                ),
            ]
        )
        await session.commit()

        feed, personalized = await repository.feed_items(
            user_id=user_id, personalized_requested=True
        )
        assert personalized is True
        assert feed[0]["article_id"] == article_id
        assert (await repository.issue_view(issue_id))["distribution"]["count"] == 1
        issue_articles = await repository.issue_article_rows(issue_id)
        assert issue_articles is not None
        assert issue_articles[0]["summary"] == "검증된 OpenAI 분석"
        assessment_page = await repository.assessment_view(article_id)
        assert assessment_page is not None
        assert assessment_page["assessments"][0]["summary"] == "검증된 OpenAI 분석"
        assert assessment_page["assessments"][0]["evidence"] == []

        read_id = new_ulid()
        assert await repository.create_read_session_row(
            session_id=read_id,
            user_id=user_id,
            article_id=article_id,
            token="signed-token",
            expires_at=utc_now() + timedelta(minutes=30),
        )
        assert (
            await repository.use_read_redirect(
                session_id=read_id,
                user_id=user_id,
                article_id=article_id,
                token="signed-token",
            )
            == "https://example.test/a"
        )

        vote = await repository.put_vote_row(
            user_id=user_id,
            article_id=article_id,
            values={"x": 1, "y": 2, "z": 3, "sensationalism": 4},
        )
        assert vote and vote["revision"] == 1
        assert (await repository.vote_aggregate(article_id))["qualified_count"] == 1

        efficacy_version = await session.scalar(
            select(QuestionnaireVersion.id).where(
                QuestionnaireVersion.kind == QuestionnaireKind.EFFICACY
            )
        )
        efficacy = await repository.submit_efficacy_row(
            user_id=user_id,
            questionnaire_version_id=efficacy_version,
            answers={"one": 60, "two": 80},
        )
        assert efficacy == {
            "normalized_score": 70.0,
            "baseline_delta": None,
            "due_survey": False,
        }

        job, card = await repository.create_share_card_row(
            user_id=user_id, template="standard", display_name="Member"
        )
        assert job["status"] == "PENDING"
        assert card["public_token"]
        assert card["snapshot"]["sensationalism"] is None
        assert card["snapshot"]["coordinate"]["sensationalism"] is None
        assert card["snapshot"]["activity"] == card["snapshot"]["credit_total"] == 0
        assert (await repository.public_share_card(card["public_token"])) is not None
        persisted_job = await session.get(Job, job["id"])
        assert persisted_job is not None
        persisted_job.status = JobStatus.DEAD
        await session.commit()
        failed_card = await repository.owner_share_card(card_id=card["id"], user_id=user_id)
        assert failed_card is not None
        assert failed_card["status"] == "failed"
        retried = await repository.retry_share_card(card_id=card["id"], user_id=user_id)
        assert retried == {
            "job_id": job["id"],
            "status": "PENDING",
            "share_card_id": card["id"],
        }
        await session.refresh(persisted_job)
        assert persisted_job.status == JobStatus.PENDING
        assert persisted_job.attempts == 0
        persisted_card = await session.get(ShareCard, card["id"])
        assert persisted_card is not None
        assert persisted_card.status == ShareCardStatus.QUEUED
        assert await repository.revoke_share_card(card_id=card["id"], user_id=user_id)
        assert (await repository.public_share_card(card["public_token"])) is None
    await engine.dispose()
