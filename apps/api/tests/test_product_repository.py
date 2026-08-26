from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    ArticleStatus,
    AssessmentStatus,
    IssueStatus,
    ModelStatus,
    ProfileKind,
    QuestionnaireKind,
    RevisionStatus,
    ScoreStatus,
    SourcePolicyStatus,
    SourceType,
    UserRole,
    UserStatus,
)
from apps.api.app.db.models import (
    Article,
    ArticleVersion,
    Issue,
    IssueMembership,
    ModelAlias,
    ModelAssessment,
    QuestionnaireVersion,
    ScoreVersion,
    Source,
    User,
    UserProfile,
    WeightProfileRevision,
)
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.repositories.platform import MariaDBPlatformRepository


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
                raw_payload_ref=None,
                raw_payload_expires_at=None,
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
                    evidence_json={"summary": "검증된 OpenAI 분석", "synthetic": False},
                    raw_response_ref=None,
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
                        "analysis_provider": "openai",
                        "assessment_ids": [assessment_id],
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
        assert await repository.revoke_share_card(card_id=card["id"], user_id=user_id)
        assert (await repository.public_share_card(card["public_token"])) is None
    await engine.dispose()
