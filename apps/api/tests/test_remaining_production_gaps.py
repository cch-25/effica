from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    IssueStatus,
    QuestionnaireKind,
    RevisionStatus,
    UserRole,
    UserStatus,
)
from apps.api.app.db.models import (
    EfficacyResponse,
    Issue,
    QuestionnaireVersion,
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
    assert audit and audit[0]["after"]["target_created"] is True


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
