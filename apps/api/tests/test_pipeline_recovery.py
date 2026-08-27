from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    AdapterType,
    ArticleStatus,
    AssessmentStatus,
    CrawlStatus,
    JobStatus,
    ModelStatus,
    RevisionStatus,
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
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.domains.issues.topics import canonical_topic_issue_id
from db.seeds.pipeline_recovery import recover_pipeline


@pytest.mark.asyncio
async def test_source_bootstrap_rebuilds_durable_broad_topic_collections() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        source = Source(
            id=new_ulid(),
            name="Topic News",
            source_type=SourceType.RSS,
            canonical_url="https://topic.example/rss",
            policy_status=SourcePolicyStatus.APPROVED,
            robots_status=SourcePolicyStatus.APPROVED,
            terms_status=SourcePolicyStatus.APPROVED,
            active=True,
        )
        session.add(source)
        await session.flush()
        session.add(
            SourceAdapter(
                id=new_ulid(),
                source_id=source.id,
                adapter_type=AdapterType.RSS,
                config_json={"metadata_only": True},
                rate_limit=10,
                raw_payload_retention_days=7,
                active=True,
            )
        )
        article, _version = await _article(
            session,
            source_id=source.id,
            title="프로야구 KBO 시즌 개막",
            body=False,
        )
        legacy = Issue(
            id=new_ulid(),
            title="프로야구",
            summary="스포츠 분야의 최신 한국어 원문 기사 모음",
            topic="스포츠",
            status="active",
            issue_kind="TOPIC",
            editorial_key=None,
            opened_at=utc_now(),
            last_activity_at=utc_now(),
            version=1,
        )
        session.add(legacy)
        await session.flush()
        session.add(
            IssueMembership(
                issue_id=legacy.id,
                article_id=article.id,
                confidence=Decimal("1.0000"),
                created_at=utc_now(),
            )
        )
        await session.commit()

        async with session.begin():
            report = await recover_pipeline(
                session,
                generation="topic-collection-rebuild",
                dry_run=False,
                bootstrap_sources=True,
            )

        canonical = await session.get(Issue, canonical_topic_issue_id("스포츠"))
        membership = await session.get(
            IssueMembership,
            (canonical_topic_issue_id("스포츠"), article.id),
        )
        await session.refresh(legacy)
        assert canonical is not None
        assert canonical.status == "active"
        assert canonical.issue_kind == "TOPIC"
        assert membership is not None
        assert legacy.status == "archived"
        assert report["actions"]["canonical_topic_collections_upserted"] == 8
        assert report["actions"]["topic_memberships_upserted"] == 1
        assert report["actions"]["legacy_active_topic_collections_archived"] == 1
        assert report["diagnostics"]["metadata_only_articles"] == 1
        assert report["deferred"]["articles_without_body"] == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_pipeline_recovery_merges_unconfigured_duplicate_sources_safely() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        canonical = Source(
            id=new_ulid(),
            name="중복 언론사",
            source_type=SourceType.CRAWLER,
            canonical_url="https://news.example",
            policy_status=SourcePolicyStatus.APPROVED,
            robots_status=SourcePolicyStatus.APPROVED,
            terms_status=SourcePolicyStatus.APPROVED,
            active=True,
        )
        duplicate = Source(
            id=new_ulid(),
            name="중복 언론사",
            source_type=SourceType.CRAWLER,
            canonical_url="https://news.example/seed-home",
            policy_status=SourcePolicyStatus.PENDING,
            robots_status=SourcePolicyStatus.PENDING,
            terms_status=SourcePolicyStatus.PENDING,
            active=True,
        )
        session.add_all([canonical, duplicate])
        await session.flush()
        session.add(
            SourceAdapter(
                id=new_ulid(),
                source_id=canonical.id,
                adapter_type=AdapterType.CRAWLER,
                config_json={"scheduled": False},
                rate_limit=10,
                raw_payload_retention_days=7,
                active=True,
            )
        )
        article, _ = await _article(
            session,
            source_id=duplicate.id,
            title="중복 출처 병합 기사",
        )
        crawl_run = CrawlRun(
            id=new_ulid(),
            source_id=duplicate.id,
            status=CrawlStatus.SUCCEEDED,
            started_at=utc_now(),
            finished_at=utc_now(),
            stats_json={},
            error_json=None,
        )
        session.add(crawl_run)
        await session.flush()

        dry_report = await recover_pipeline(
            session,
            generation="duplicate-source-dry-run",
            dry_run=True,
        )
        assert dry_report["actions"]["duplicate_sources_merged"] == 1
        assert dry_report["actions"]["source_articles_reassigned"] == 1
        assert dry_report["actions"]["source_crawl_runs_reassigned"] == 1
        assert duplicate.active is True
        assert article.source_id == duplicate.id

        report = await recover_pipeline(
            session,
            generation="duplicate-source-apply",
            dry_run=False,
        )
        await session.flush()

        assert report["actions"]["duplicate_sources_merged"] == 1
        assert duplicate.active is False
        assert article.source_id == canonical.id
        assert crawl_run.source_id == canonical.id
    await engine.dispose()


async def _article(
    session,
    *,
    source_id: str,
    title: str,
    current: bool = True,
    body: bool = True,
) -> tuple[Article, ArticleVersion | None]:
    now = utc_now()
    article = Article(
        id=new_ulid(),
        source_id=source_id,
        canonical_url=f"https://news.example/{new_ulid()}",
        canonical_url_hash=__import__("hashlib").sha256(title.encode()).digest(),
        title=title,
        author=None,
        published_at=now,
        current_version_id=None,
        status=ArticleStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session.add(article)
    await session.flush()
    if not body and not current:
        return article, None
    blob_id = None
    if body:
        payload = f"{title}의 충분한 기사 본문입니다.".encode()
        blob = StoredBlob(
            id=new_ulid(),
            sha256=__import__("hashlib").sha256(payload).digest(),
            mime_type="text/plain",
            byte_size=len(payload),
            payload=payload,
            expires_at=None,
            created_at=now,
        )
        session.add(blob)
        blob_id = blob.id
    version = ArticleVersion(
        id=new_ulid(),
        article_id=article.id,
        content_hash=__import__("hashlib").sha256(f"version:{title}".encode()).digest(),
        normalized_text_ref=blob_id,
        raw_payload_ref=None,
        raw_payload_expires_at=None,
        fetched_at=now,
        modified_at=None,
    )
    session.add(version)
    await session.flush()
    if current:
        article.current_version_id = version.id
    return article, version


def _assessment(
    *,
    version_id: str,
    alias_id: str,
    status: AssessmentStatus = AssessmentStatus.SUCCEEDED,
) -> ModelAssessment:
    return ModelAssessment(
        id=new_ulid(),
        article_version_id=version_id,
        model_alias_id=alias_id,
        prompt_version="bias-sensationalism-v1",
        x=10,
        y=0,
        z=0,
        sensationalism=20,
        confidence=Decimal("0.9000"),
        evidence_json={"summary": "근거", "evidence": []},
        raw_response_ref=None,
        token_usage=10,
        latency_ms=20,
        status=status,
        created_at=utc_now(),
    )


@pytest.mark.asyncio
async def test_pipeline_recovery_repairs_only_trusted_safe_state_and_is_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        source = Source(
            id=new_ulid(),
            name="Recovery News",
            source_type=SourceType.RSS,
            canonical_url="https://news.example/rss",
            policy_status=SourcePolicyStatus.APPROVED,
            robots_status=SourcePolicyStatus.APPROVED,
            terms_status=SourcePolicyStatus.APPROVED,
            active=True,
        )
        session.add(source)
        await session.flush()
        session.add(
            SourceAdapter(
                id=new_ulid(),
                source_id=source.id,
                adapter_type=AdapterType.RSS,
                config_json={},
                rate_limit=5,
                raw_payload_retention_days=7,
                active=True,
            )
        )
        trusted_alias = ModelAlias(
            id=new_ulid(),
            alias="openai-live",
            provider="openai",
            actual_model_id="gpt-5.6-luna",
            status=ModelStatus.ACTIVE,
            config_json={},
        )
        configured_alias = ModelAlias(
            id=new_ulid(),
            alias="openai-default",
            provider="openai",
            actual_model_id="gpt-5.6-luna",
            status=ModelStatus.ACTIVE,
            config_json={},
        )
        stub_alias = ModelAlias(
            id=new_ulid(),
            alias="deterministic-stub",
            provider="deterministic-stub",
            actual_model_id="fixture",
            status=ModelStatus.ACTIVE,
            config_json={},
        )
        weight = WeightProfileRevision(
            id=new_ulid(),
            revision=1,
            status=RevisionStatus.ACTIVE,
            weights_json={"model": 1.0},
            guardrails_json={},
            based_on_revision_id=None,
            created_by=None,
            created_at=utc_now(),
            published_at=utc_now(),
        )
        session.add_all([trusted_alias, configured_alias, stub_alias, weight])
        await session.flush()

        pointer_article, pointer_version = await _article(
            session, source_id=source.id, title="포인터 복구", current=False
        )
        assert pointer_version is not None
        pointer_assessment = _assessment(
            version_id=pointer_version.id, alias_id=trusted_alias.id
        )
        session.add(pointer_assessment)
        redundant_analysis = Job(
            id=new_ulid(),
            job_type="analyze",
            dedupe_key=f"redundant:{pointer_version.id}",
            status=JobStatus.PENDING,
            priority=0,
            available_at=utc_now(),
            lease_owner=None,
            lease_expires_at=None,
            attempts=0,
            max_attempts=3,
            payload_json={"article_version_id": pointer_version.id},
            last_error_json=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(redundant_analysis)
        await session.flush()
        legacy_active = ScoreVersion(
            id=new_ulid(),
            article_version_id=pointer_version.id,
            weight_revision_id=weight.id,
            x=0,
            y=0,
            z=0,
            sensationalism=0,
            confidence=Decimal("0.1000"),
            components_json={"legacy": True},
            status=ScoreStatus.ACTIVE,
            created_at=utc_now() - timedelta(minutes=1),
        )
        draft = ScoreVersion(
            id=new_ulid(),
            article_version_id=pointer_version.id,
            weight_revision_id=weight.id,
            x=10,
            y=0,
            z=0,
            sensationalism=20,
            confidence=Decimal("0.9000"),
            components_json={
                "analysis_provider": "openai",
                "assessment_ids": [pointer_assessment.id],
            },
            status=ScoreStatus.DRAFT,
            created_at=utc_now(),
        )
        session.add_all([legacy_active, draft])

        stub_article, stub_version = await _article(
            session, source_id=source.id, title="스텁 재분석"
        )
        assert stub_version is not None
        session.add(_assessment(version_id=stub_version.id, alias_id=stub_alias.id))
        session.add(
            Job(
                id=new_ulid(),
                job_type="analyze",
                dedupe_key=f"article-version:{stub_version.id}",
                status=JobStatus.SUCCEEDED,
                priority=0,
                available_at=utc_now(),
                lease_owner=None,
                lease_expires_at=None,
                attempts=1,
                max_attempts=3,
                payload_json={"article_version_id": stub_version.id},
                last_error_json=None,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )

        score_article, score_version = await _article(
            session, source_id=source.id, title="점수 재계산"
        )
        assert score_version is not None
        session.add(_assessment(version_id=score_version.id, alias_id=trusted_alias.id))

        empty_article, _ = await _article(
            session, source_id=source.id, title="본문 재수집", current=False, body=False
        )
        issue = Issue(
            id=new_ulid(),
            title="복구 테스트 이슈",
            summary="테스트",
            topic="사회",
            status="active",
            issue_kind="TOPIC",
            editorial_key=None,
            editorial_priority=None,
            editorial_reviewed_at=None,
            editorial_data_as_of=None,
            opened_at=utc_now(),
            last_activity_at=utc_now(),
            version=1,
        )
        session.add(issue)
        await session.flush()
        for article in (pointer_article, stub_article, score_article):
            session.add(
                IssueMembership(
                    issue_id=issue.id,
                    article_id=article.id,
                    confidence=Decimal("1.0000"),
                    created_at=utc_now(),
                )
            )
        await session.commit()

        async with session.begin():
            report = await recover_pipeline(
                session, generation="test-generation", dry_run=False
            )

        assert report["diagnostics"]["active_sources"] == 1
        assert report["diagnostics"]["approved_policy_sources"] == 1
        assert report["diagnostics"]["active_adapter_types"] == {"RSS": 1}
        assert report["diagnostics"]["current_version_missing"] == 2
        source_report = report["diagnostics"]["sources"][0]
        assert source_report["articles"] == 4
        assert source_report["current_versions"] == 2
        assert report["actions"]["version_pointers_repaired"] == 1
        assert report["actions"]["draft_scores_promoted"] == 1
        assert report["actions"]["invalid_active_scores_superseded"] == 1
        assert report["actions"]["analysis_jobs_enqueued"] == 1
        assert report["actions"]["score_jobs_enqueued"] == 1
        assert report["actions"]["crawl_jobs_enqueued"] == 1
        assert report["actions"]["cluster_jobs_enqueued"] == 1
        assert report["actions"]["openai_aliases_deprecated"] == 1
        assert report["actions"]["redundant_analysis_jobs_cancelled"] == 1
        assert report["actions"]["audit_rows_written"] == 1
        assert pointer_article.current_version_id == pointer_version.id
        assert draft.status == ScoreStatus.ACTIVE
        assert legacy_active.status == ScoreStatus.SUPERSEDED
        assert trusted_alias.status == ModelStatus.DEPRECATED
        assert configured_alias.status == ModelStatus.ACTIVE
        assert redundant_analysis.status == JobStatus.CANCELLED

        queued = list(
            (
                await session.scalars(
                    select(Job).where(Job.dedupe_key.like("recovery:test-generation:%"))
                )
            ).all()
        )
        assert {job.job_type for job in queued} == {
            "analyze",
            "calculate_score",
            "cluster",
            "crawl",
        }
        analyze = next(job for job in queued if job.job_type == "analyze")
        assert analyze.payload_json["article_version_id"] == stub_version.id
        assert analyze.status == JobStatus.PENDING
        await session.commit()

        async with session.begin():
            replay = await recover_pipeline(
                session, generation="test-generation", dry_run=False
            )
        assert sum(replay["actions"].values()) == 0
        assert (
            await session.scalar(
                select(func.count()).select_from(AuditLog).where(
                    AuditLog.action == "PIPELINE_RECOVERY_APPLIED"
                )
            )
        ) == 1
        assert empty_article.current_version_id is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_pipeline_recovery_dry_run_never_mutates_rows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        source = Source(
            id=new_ulid(),
            name="Dry Run",
            source_type=SourceType.CRAWLER,
            canonical_url="https://www.newsis.com/",
            policy_status=SourcePolicyStatus.APPROVED,
            robots_status=SourcePolicyStatus.APPROVED,
            terms_status=SourcePolicyStatus.APPROVED,
            active=True,
        )
        session.add(source)
        await session.flush()
        session.add(
            SourceAdapter(
                id=new_ulid(),
                source_id=source.id,
                adapter_type=AdapterType.CRAWLER,
                config_json={"discover_links": False},
                rate_limit=None,
                raw_payload_retention_days=None,
                active=True,
            )
        )
        article, version = await _article(
            session, source_id=source.id, title="드라이런", current=False
        )
        assert version is not None
        await session.commit()

        async with session.begin():
            report = await recover_pipeline(session, generation="dry-run", dry_run=True)
        await session.refresh(article)

        assert report["actions"]["version_pointers_repaired"] == 1
        assert report["actions"]["analysis_jobs_enqueued"] == 1
        assert report["actions"]["scheduled_rss_adapters_upserted"] == 1
        assert report["diagnostics"]["scheduled_rss_adapter_plans"] == [
            {
                "source_id": source.id,
                "source": "Dry Run",
                "source_type_preserved": "CRAWLER",
                "feed_url": "https://nwww.newsis.com/RSS/sokbo.xml",
                "action": "UPSERT",
            }
        ]
        assert report["actions"]["audit_rows_written"] == 0
        assert article.current_version_id is None
        assert await session.scalar(select(func.count()).select_from(Job)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert await session.scalar(select(func.count()).select_from(SourceAdapter)) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_pipeline_recovery_cancels_stale_comparison_work() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        source = Source(
            id=new_ulid(),
            name="Comparison Recovery",
            source_type=SourceType.RSS,
            canonical_url="https://comparison.example/rss",
            policy_status=SourcePolicyStatus.APPROVED,
            robots_status=SourcePolicyStatus.APPROVED,
            terms_status=SourcePolicyStatus.APPROVED,
            active=True,
        )
        session.add(source)
        await session.flush()
        article_ids: list[str] = []
        current_version_ids: list[str] = []
        for title in ("비교 기사 1", "비교 기사 2"):
            article, version = await _article(session, source_id=source.id, title=title)
            assert version is not None
            article_ids.append(article.id)
            current_version_ids.append(version.id)
        issue = Issue(
            id=new_ulid(),
            title="비교 복구 이슈",
            summary="테스트",
            topic="사회",
            status="active",
            issue_kind="TOPIC",
            editorial_key=None,
            editorial_priority=None,
            editorial_reviewed_at=None,
            editorial_data_as_of=None,
            opened_at=utc_now(),
            last_activity_at=utc_now(),
            version=2,
        )
        session.add(issue)
        await session.flush()
        payload = {
            "issue_id": issue.id,
            "issue_version": issue.version,
            "article_ids": article_ids,
            "article_version_ids": ["retired-version", current_version_ids[1]],
            "prompt_version": "issue-comparison-v1",
        }
        failed = Job(
            id=new_ulid(),
            job_type="build_issue_comparison",
            dedupe_key="stale-comparison-failed",
            status=JobStatus.FAILED,
            priority=0,
            available_at=utc_now(),
            lease_owner=None,
            lease_expires_at=None,
            attempts=1,
            max_attempts=3,
            payload_json=payload,
            last_error_json={"code": "COMPARISON_ANALYSIS_REQUIRED"},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        leased = Job(
            id=new_ulid(),
            job_type="build_issue_comparison",
            dedupe_key="stale-comparison-leased",
            status=JobStatus.LEASED,
            priority=0,
            available_at=utc_now(),
            lease_owner="worker-1",
            lease_expires_at=utc_now() + timedelta(minutes=5),
            attempts=1,
            max_attempts=3,
            payload_json=payload,
            last_error_json=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        recoverable = Job(
            id=new_ulid(),
            job_type="build_issue_comparison",
            dedupe_key="current-comparison-result-apply",
            status=JobStatus.DEAD,
            priority=0,
            available_at=utc_now(),
            lease_owner=None,
            lease_expires_at=None,
            attempts=3,
            max_attempts=3,
            payload_json={
                **payload,
                "article_version_ids": current_version_ids,
            },
            last_error_json={"code": "RESULT_APPLICATION_FAILED"},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        schema_rejected = Job(
            id=new_ulid(),
            job_type="build_issue_comparison",
            dedupe_key="current-comparison-schema-retry",
            status=JobStatus.FAILED,
            priority=0,
            available_at=utc_now(),
            lease_owner=None,
            lease_expires_at=None,
            attempts=1,
            max_attempts=3,
            payload_json={
                **payload,
                "article_version_ids": current_version_ids,
            },
            last_error_json={"code": "PROVIDER_SCHEMA_REJECTED"},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add_all([failed, leased, recoverable, schema_rejected])
        await session.commit()

        async with session.begin():
            report = await recover_pipeline(
                session,
                generation="stale-comparison-cleanup",
                dry_run=False,
            )

        assert report["diagnostics"]["stale_comparison_jobs"] == 2
        assert report["diagnostics"]["recoverable_comparison_jobs"] == 2
        assert report["actions"]["stale_comparison_jobs_cancelled"] == 1
        assert report["actions"]["comparison_jobs_requeued"] == 2
        assert report["deferred"]["stale_comparison_work_in_progress"] == 1
        assert failed.status == JobStatus.CANCELLED
        assert leased.status == JobStatus.LEASED
        assert recoverable.status == JobStatus.PENDING
        assert recoverable.attempts == 0
        assert recoverable.last_error_json is None
        assert schema_rejected.status == JobStatus.PENDING
        assert schema_rejected.attempts == 0
        assert schema_rejected.last_error_json is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_pipeline_recovery_blocks_homepage_placeholders_and_cancels_bad_schedule() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        source = Source(
            id=new_ulid(),
            name="Homepage News",
            source_type=SourceType.CRAWLER,
            canonical_url="https://homepage.example/",
            policy_status=SourcePolicyStatus.APPROVED,
            robots_status=SourcePolicyStatus.APPROVED,
            terms_status=SourcePolicyStatus.APPROVED,
            active=True,
        )
        session.add(source)
        await session.flush()
        session.add(
            SourceAdapter(
                id=new_ulid(),
                source_id=source.id,
                adapter_type=AdapterType.CRAWLER,
                config_json={"discover_links": False},
                rate_limit=5,
                raw_payload_retention_days=7,
                active=True,
            )
        )
        article, version = await _article(
            session,
            source_id=source.id,
            title=source.name,
        )
        assert version is not None
        article.canonical_url = source.canonical_url
        bad_job = Job(
            id=new_ulid(),
            job_type="crawl",
            dedupe_key=f"scheduled:{source.id}:123",
            status=JobStatus.FAILED,
            priority=10,
            available_at=utc_now(),
            lease_owner=None,
            lease_expires_at=None,
            attempts=1,
            max_attempts=5,
            payload_json={
                "source_id": source.id,
                "url": source.canonical_url,
                "source_type": "CRAWLER",
                "config": {"discover_links": False},
            },
            last_error_json={"code": "SOURCE_NO_ARTICLES"},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(bad_job)
        session.add(
            CrawlRun(
                id=bad_job.id,
                source_id=source.id,
                status="FAILED",
                started_at=utc_now(),
                finished_at=utc_now(),
                stats_json=None,
                error_json={"code": "SOURCE_NO_ARTICLES"},
            )
        )
        await session.commit()

        async with session.begin():
            report = await recover_pipeline(
                session,
                generation="scheduler-cleanup",
                dry_run=False,
            )

        await session.refresh(article)
        await session.refresh(bad_job)
        crawl_run = await session.get(CrawlRun, bad_job.id)
        assert report["diagnostics"]["homepage_placeholder_articles"] == 1
        assert report["diagnostics"]["unscheduled_periodic_crawl_jobs"] == 1
        assert report["actions"]["homepage_placeholder_articles_blocked"] == 1
        assert report["actions"]["unscheduled_periodic_crawl_jobs_cancelled"] == 1
        assert article.status == ArticleStatus.BLOCKED
        assert bad_job.status == JobStatus.CANCELLED
        assert crawl_run is not None
        assert crawl_run.status == "CANCELLED"

        await session.commit()
        async with session.begin():
            replay = await recover_pipeline(
                session,
                generation="scheduler-cleanup",
                dry_run=False,
            )
        assert replay["diagnostics"]["homepage_placeholder_articles"] == 0
        assert replay["diagnostics"]["unscheduled_periodic_crawl_jobs"] == 0
        assert sum(replay["actions"].values()) == 0
    await engine.dispose()
