"""Regression coverage for retained reading history and event comparisons."""
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    ArticleStatus,
    ReadSessionStatus,
    SourcePolicyStatus,
    SourceType,
    UserRole,
    UserStatus,
)
from apps.api.app.db.models import Article, ReadSession, Source, User
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.repositories.platform import MariaDBPlatformRepository


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_expired_articles_preserve_read_count(database):
    async with database() as session:
        user_id = new_ulid()
        session.add(User(id=user_id, role=UserRole.MEMBER, status=UserStatus.ACTIVE))
        # Retention nulls each article_id but retains the three eligible reads.
        for index in range(3):
            session.add(ReadSession(id=new_ulid(), user_id=user_id, article_id=None,
                token_hash=hashlib.sha256(str(index).encode()).digest(),
                expires_at=utc_now() + timedelta(minutes=30), status=ReadSessionStatus.ELIGIBLE,
                policy_version="read-v1"))
        await session.commit()
        result = await MariaDBPlatformRepository(session, encryption_secret="x" * 40).progress_view(user_id)
        assert result["read_article_count"] == 3, result


@pytest.mark.asyncio
async def test_repeated_sessions_for_expired_article_count_only_once(database):
    async with database() as session:
        user_id = new_ulid()
        article_keys = [new_ulid(), new_ulid()]
        session.add(User(id=user_id, role=UserRole.MEMBER, status=UserStatus.ACTIVE))
        for index, key in enumerate([article_keys[0], article_keys[0], article_keys[1]]):
            session.add(ReadSession(id=new_ulid(), user_id=user_id, article_id=None, article_key=key,
                token_hash=hashlib.sha256(str(index).encode()).digest(),
                expires_at=utc_now() + timedelta(minutes=30), status=ReadSessionStatus.ELIGIBLE,
                policy_version="read-v1"))
        await session.commit()
        assert (await MariaDBPlatformRepository(session, encryption_secret="x" * 40).progress_view(user_id))["read_article_count"] == 2


@pytest.mark.parametrize("article_count", [4, 8])
@pytest.mark.asyncio
async def test_any_four_articles_supported_by_public_comparison(database, article_count):
    from apps.api.app.db.enums import (
        AssessmentStatus,
        ComparisonSnapshotStatus,
        IssueKind,
        IssueStatus,
        ModelStatus,
        RevisionStatus,
        ScoreStatus,
    )
    from apps.api.app.db.models import (
        ArticleVersion,
        Issue,
        IssueComparisonSnapshot,
        IssueMembership,
        ModelAlias,
        ModelAssessment,
        ScoreVersion,
        WeightProfileRevision,
    )
    from apps.worker.worker.comparison_cohort import select_comparison_cohort
    async with database() as session:
        user_id, issue_id, alias_id, weight_id = [new_ulid() for _ in range(4)]
        now = utc_now()
        session.add(User(id=user_id, role=UserRole.ADMIN, status=UserStatus.ACTIVE))
        session.add(Issue(id=issue_id, title="국회 정책 논쟁", summary="국회 정책 논쟁의 서로 다른 입장", topic="정치", issue_kind=IssueKind.EVENT,
            editorial_key="daily-issue:review", status=IssueStatus.ACTIVE, opened_at=now, last_activity_at=now, version=1))
        session.add(ModelAlias(id=alias_id, alias="review-model", provider="openai", actual_model_id="gpt-fixture", status=ModelStatus.ACTIVE, config_json={}))
        session.add(WeightProfileRevision(id=weight_id, revision=1, status=RevisionStatus.ACTIVE, weights_json={"model": 1}, guardrails_json={}, created_by=user_id))
        rows = []
        for index in range(article_count):
            aid, sid, vid, mid = [new_ulid() for _ in range(4)]
            url = f"https://source{index}.co.kr/news"
            session.add(Source(id=sid, name=f"Source {index}", source_type=SourceType.RSS, canonical_url=url,
                policy_status=SourcePolicyStatus.APPROVED, active=True))
            article = Article(id=aid, source_id=sid, canonical_url=url, canonical_url_hash=hashlib.sha256(url.encode()).digest(),
                title="국회 정책 논쟁 보도", published_at=now, status=ArticleStatus.ACTIVE)
            session.add(article)
            await session.flush()
            session.add(ArticleVersion(id=vid, article_id=aid, content_hash=hashlib.sha256(aid.encode()).digest(), normalized_text_ref="fixture", fetched_at=now))
            await session.flush()
            article.current_version_id = vid
            session.add(IssueMembership(issue_id=issue_id, article_id=aid, confidence=1))
            session.add(ModelAssessment(id=mid, article_version_id=vid, model_alias_id=alias_id, prompt_version="test-v1",
                x=0, y=0, z=0, sensationalism=0, confidence=.9, evidence_json=[], status=AssessmentStatus.SUCCEEDED))
            session.add(ScoreVersion(id=new_ulid(), article_version_id=vid, weight_revision_id=weight_id,
                x=0, y=0, z=0, sensationalism=0, confidence=.9, status=ScoreStatus.ACTIVE,
                components_json={"analysis_provider": "openai", "assessment_ids": [mid]}))
            rows.append(dict(article_id=aid, article_version_id=vid, source_url=url, title=article.title, content="국회에서 논의한 정책의 쟁점과 각 정당의 반응을 전하는 기사입니다. " * 20))
        cohort = select_comparison_cohort(rows)
        assert len(cohort) == article_count
        session.add(IssueComparisonSnapshot(id=new_ulid(), issue_id=issue_id, issue_version=1, prompt_version="issue-comparison-v1", model_alias_id=alias_id,
            common_facts_json=[{"id": "fact", "text": "두 기사가 확인한 사실", "article_ids": [rows[0]["article_id"], rows[1]["article_id"]], "evidence_refs": []}],
            framing_dimensions_json=[], article_frames_json={
                "article_frames": {row["article_id"]: {} for row in cohort},
                "article_version_ids": {row["article_id"]: row["article_version_id"] for row in cohort}},
            confidence=.9, status=ComparisonSnapshotStatus.SUCCEEDED, reviewed_at=now, reviewed_by=user_id))
        await session.commit()
        repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        from itertools import combinations
        for selected in combinations([row["article_id"] for row in rows], 4):
            result = await repository.issue_comparison_view(issue_id=issue_id, article_ids=list(selected))
            assert len(result["articles"]) == 4
            assert bool(result["common_facts"]) == {rows[0]["article_id"], rows[1]["article_id"]}.issubset(selected)
