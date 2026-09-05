from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    ArticleStatus,
    IssueStatus,
    QuestionnaireKind,
    RevisionStatus,
    SourcePolicyStatus,
    SourceType,
    UserRole,
    UserStatus,
)
from apps.api.app.db.models import (
    Article,
    EfficacyResponse,
    Issue,
    IssueMembership,
    QuestionnaireVersion,
    Source,
    User,
    WeightProfileRevision,
)
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.repositories.admin import AdminConflictError
from apps.api.app.repositories.platform import MariaDBPlatformRepository


@pytest.fixture
async def repository_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_d04_durable_efficacy_metrics_use_latest_distinct_user(
    repository_session,
) -> None:
    session = repository_session
    now = utc_now()
    questionnaire_id = new_ulid()
    user_ids = [new_ulid() for _ in range(3)]
    session.add_all(
        [
            User(
                id=user_id,
                role=UserRole.MEMBER,
                status=UserStatus.ACTIVE,
                display_name="member",
                created_at=now,
                deleted_at=None,
            )
            for user_id in user_ids
        ]
    )
    session.add(
        QuestionnaireVersion(
            id=questionnaire_id,
            kind=QuestionnaireKind.EFFICACY,
            version="efficacy-test",
            schema_json={},
            scoring_json={},
            active_from=now,
        )
    )
    session.add_all(
        [
            EfficacyResponse(
                id=new_ulid(),
                user_id=user_ids[index],
                questionnaire_version_id=questionnaire_id,
                normalized_score=float(index + 1),
                submitted_at=now,
            )
            for index in range(3)
        ]
    )
    # This follow-up replaces user 0's representative score rather than
    # increasing the cohort size or contributing both rows to the mean.
    session.add(
        EfficacyResponse(
            id=new_ulid(),
            user_id=user_ids[0],
            questionnaire_version_id=questionnaire_id,
            normalized_score=100,
            submitted_at=now + timedelta(seconds=1),
        )
    )
    await session.commit()

    repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
    metrics = await repository.get_efficacy_metrics(minimum_cohort_size=3)

    assert metrics["suppressed"] is False
    assert metrics["cohorts"] == [
        {"cohort_key": "all", "count": 3, "mean": 35.0}
    ]


@pytest.mark.asyncio
async def test_issue_topics_and_pending_articles_remain_public(repository_session) -> None:
    session = repository_session
    now = utc_now()
    issue_id, source_id, article_id, blocked_source_id, blocked_article_id = (
        new_ulid() for _ in range(5)
    )
    session.add_all(
        [
            Issue(
                id=issue_id,
                title="공공 AI 산업 정책",
                summary="인공지능 산업의 새로운 기준을 다룹니다.",
                topic="일반",
                status=IssueStatus.ACTIVE,
                opened_at=now,
                last_activity_at=now,
                version=1,
            ),
            Source(
                id=source_id,
                name="테스트 언론사",
                source_type=SourceType.RSS,
                canonical_url="https://source.example.test",
                policy_status=SourcePolicyStatus.APPROVED,
                robots_status=SourcePolicyStatus.APPROVED,
                terms_status=SourcePolicyStatus.APPROVED,
                active=True,
            ),
            Source(
                id=blocked_source_id,
                name="비공개 언론사",
                source_type=SourceType.RSS,
                canonical_url="https://blocked-source.example.test",
                policy_status=SourcePolicyStatus.REJECTED,
                robots_status=SourcePolicyStatus.REJECTED,
                terms_status=SourcePolicyStatus.REJECTED,
                active=False,
            ),
        ]
    )
    await session.flush()
    session.add(
        Article(
            id=article_id,
            source_id=source_id,
            canonical_url="https://source.example.test/pending",
            canonical_url_hash=hashlib.sha256(b"https://source.example.test/pending").digest(),
            title="분석을 기다리는 기사",
            author=None,
            published_at=now,
            current_version_id=None,
            status=ArticleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        Article(
            id=blocked_article_id,
            source_id=blocked_source_id,
            canonical_url="https://blocked-source.example.test/removed",
            canonical_url_hash=hashlib.sha256(
                b"https://blocked-source.example.test/removed"
            ).digest(),
            title="공개하면 안 되는 기사",
            author=None,
            published_at=now,
            current_version_id=None,
            status=ArticleStatus.BLOCKED,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
    session.add(
        IssueMembership(
            issue_id=issue_id,
            article_id=article_id,
            confidence=0.7,
            created_at=now,
        )
    )
    session.add(
        IssueMembership(
            issue_id=issue_id,
            article_id=blocked_article_id,
            confidence=0.9,
            created_at=now,
        )
    )
    await session.commit()

    repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
    issues = await repository.list_issue_rows(topic="산업")
    articles = await repository.issue_article_rows(issue_id)

    assert issues[0]["topic"] == "산업"
    assert issues[0]["article_ids"] == [article_id]
    assert issues[0]["source_count"] == 1
    assert articles is not None
    assert len(articles) == 1
    assert articles[0]["canonical_url"] == "https://source.example.test/pending"
    assert articles[0]["analysis_status"] == "PROCESSING"
    assert "coordinate" not in articles[0]


@pytest.mark.asyncio
async def test_d11_durable_merge_creates_target_and_audits_enqueue(repository_session) -> None:
    session = repository_session
    now = utc_now()
    actor_id, source_id, target_id = (new_ulid() for _ in range(3))
    session.add(
        User(
            id=actor_id,
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
            display_name="admin",
            created_at=now,
            deleted_at=None,
        )
    )
    session.add(
        Issue(
            id=source_id,
            title="Source issue",
            summary="Source summary",
            status=IssueStatus.ACTIVE,
            opened_at=now,
            last_activity_at=now,
            version=1,
        )
    )
    await session.commit()

    repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
    accepted = await repository.enqueue_merge_issue(
        source_id,
        target_id,
        actor_id=actor_id,
        idempotency_key="merge-target-create",
    )

    target = await session.get(Issue, target_id)
    assert accepted["status"] == "PENDING"
    assert target is not None
    assert getattr(target.status, "value", target.status) == IssueStatus.CANDIDATE.value
    assert target.title == "Source issue"
    audit = await repository.list_audit(actor=actor_id, action="ISSUE_MERGE_ENQUEUED")
    assert audit == []


@pytest.mark.asyncio
async def test_d07_durable_rollback_requires_older_published_archived_target(
    repository_session,
) -> None:
    session = repository_session
    now = utc_now()
    actor_id, target_id, active_id, draft_id = (new_ulid() for _ in range(4))
    session.add(
        User(
            id=actor_id,
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
            display_name="admin",
            created_at=now,
            deleted_at=None,
        )
    )
    session.add_all(
        [
            WeightProfileRevision(
                id=target_id,
                revision=1,
                status=RevisionStatus.ARCHIVED,
                weights_json={"model": 1.0},
                guardrails_json={},
                based_on_revision_id=None,
                created_by=actor_id,
                created_at=now,
                published_at=now,
            ),
            WeightProfileRevision(
                id=active_id,
                revision=2,
                status=RevisionStatus.ACTIVE,
                weights_json={"model": 1.0},
                guardrails_json={},
                based_on_revision_id=None,
                created_by=actor_id,
                created_at=now,
                published_at=now,
            ),
            WeightProfileRevision(
                id=draft_id,
                revision=3,
                status=RevisionStatus.DRAFT,
                weights_json={"model": 1.0},
                guardrails_json={},
                based_on_revision_id=None,
                created_by=actor_id,
                created_at=now,
                published_at=None,
            ),
        ]
    )
    await session.commit()

    repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
    accepted = await repository.rollback_weight(
        active_id,
        target_id,
        if_match="1",
        actor_id=actor_id,
        idempotency_key="rollback-archived",
    )
    assert accepted["status"] == RevisionStatus.ACTIVE.value

    with pytest.raises(AdminConflictError) as error:
        await repository.rollback_weight(
            accepted["id"],
            draft_id,
            if_match=str(accepted["profile_version"]),
            actor_id=actor_id,
            idempotency_key="rollback-draft",
        )
    assert error.value.details["code"] == "ROLLBACK_TARGET_INVALID"
