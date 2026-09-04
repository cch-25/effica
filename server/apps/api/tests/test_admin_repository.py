from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import JobStatus, UserRole, UserStatus
from apps.api.app.db.models import Job, SourceAdapter, User, WeightRecommendation
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.repositories.admin import (
    AdminValidationError,
    GuardrailError,
    IdempotencyConflictError,
)
from apps.api.app.repositories.platform import MariaDBPlatformRepository


@pytest.mark.asyncio
async def test_llm_usage_control_is_durable_and_cancels_active_queue_rows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        actor_id = new_ulid()
        session.add(
            User(
                id=actor_id,
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
                display_name="Runtime Admin",
                created_at=utc_now(),
                deleted_at=None,
            )
        )
        await session.commit()
        repository = MariaDBPlatformRepository(session, encryption_secret="a" * 40)

        initial = await repository.get_llm_usage()
        assert initial["status"] == "STOPPED"
        started = await repository.update_llm_usage(
            True,
            if_match="1",
            actor_id=actor_id,
            idempotency_key="runtime-start",
            reason="start runtime",
        )
        assert started["status"] == "RUNNING"

        now = utc_now()
        job = Job(
            id=new_ulid(),
            job_type="analyze",
            dedupe_key="runtime-stop-analysis",
            status=JobStatus.PENDING,
            priority=0,
            available_at=now,
            lease_owner=None,
            lease_expires_at=None,
            attempts=0,
            max_attempts=3,
            payload_json={"article_version_id": new_ulid()},
            last_error_json=None,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.commit()

        stopped = await repository.update_llm_usage(
            False,
            if_match="2",
            actor_id=actor_id,
            idempotency_key="runtime-stop",
            reason="stop runtime",
        )
        await session.refresh(job)
        assert stopped["status"] == "STOPPED"
        assert stopped["cancelled_jobs"] == 1
        assert job.status == JobStatus.CANCELLED
        assert job.last_error_json["code"] == "LLM_USAGE_DISABLED"
    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_repository_is_durable_idempotent_and_guarded() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        actor_id = new_ulid()
        session.add(
            User(
                id=actor_id,
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
                display_name="Admin",
                created_at=utc_now(),
                deleted_at=None,
            )
        )
        await session.commit()
        repository = MariaDBPlatformRepository(session, encryption_secret="a" * 40)

        source_payload = {
            "name": "Fixture",
            "source_type": "RSS",
            "canonical_url": "https://source.example",
            "policy_status": "APPROVED",
            "robots_status": "UNKNOWN",
            "terms_status": "UNKNOWN",
            "active": True,
            "adapter_type": "RSS",
            "config_json": {"max_items": 40, "strip_html": True},
            "rate_limit": 12,
            "raw_payload_retention_days": 7,
        }
        source = await repository.create_source(
            source_payload, actor_id=actor_id, idempotency_key="source-create-1"
        )
        replay = await repository.create_source(
            source_payload, actor_id=actor_id, idempotency_key="source-create-1"
        )
        assert replay == source
        assert source["robots_status"] == "PENDING"
        adapter = await session.scalar(
            select(SourceAdapter).where(SourceAdapter.source_id == source["id"])
        )
        assert adapter is not None
        assert adapter.config_json == {"max_items": 40, "strip_html": True}
        assert adapter.rate_limit == 12
        assert adapter.raw_payload_retention_days == 7
        updated = await repository.update_source(
            source["id"],
            {"robots_status": "APPROVED", "terms_status": "APPROVED"},
            if_match="1",
            actor_id=actor_id,
            idempotency_key="source-update-1",
            reason="policy review",
        )
        assert updated["version"] == 2
        with pytest.raises(IdempotencyConflictError):
            await repository.create_source(
                {**source_payload, "name": "Changed"},
                actor_id=actor_id,
                idempotency_key="source-create-1",
            )

        model = await repository.create_model_alias(
                {
                    "alias": "fixture-model",
                    "provider": "openai",
                    "actual_model_id": "gpt-5.6-luna",
                    "reasoning_effort": "xhigh",
                    "secret_env_name": "OPENAI_API_KEY",
                    "status": "ACTIVE",
            },
            actor_id=actor_id,
            idempotency_key="model-create-1",
        )
        assert model["secret_env_name"] == "OPENAI_API_KEY"
        assert model["reasoning_effort"] == "xhigh"
        assert model["config_json"]["secret_env_name"] == "[REDACTED]"
        model = await repository.update_model_alias(
            model["id"],
            {"actual_model_id": "gpt-5.6-terra", "reasoning_effort": "high"},
            if_match="1",
            actor_id=actor_id,
            idempotency_key="model-update-1",
            reason="adjust model runtime",
        )
        assert model["actual_model_id"] == "gpt-5.6-terra"
        assert model["reasoning_effort"] == "high"
        with pytest.raises(AdminValidationError):
            await repository.update_model_alias(
                model["id"],
                {"provider": "upstage"},
                if_match="2",
                actor_id=actor_id,
                idempotency_key="model-update-invalid-provider",
                reason="invalid provider regression",
            )

        weight = await repository.create_weight(
            {"weights": {"model": 1.0}, "guardrails": {"max_axis_change": 0.1}},
            actor_id=actor_id,
            idempotency_key="weight-create-1",
        )
        simulation = await repository.simulate_weight(
            weight["id"],
            [7, 30],
            actor_id=actor_id,
            idempotency_key="weight-simulate-1",
        )
        assert simulation["status"] == "PENDING"
        recommendation = await session.get(WeightRecommendation, weight["id"])
        assert recommendation is not None
        await repository.review_recommendation(
            weight["id"],
            "APPROVED",
            actor_id=actor_id,
            idempotency_key="weight-review-1",
            reason="reviewed",
        )
        with pytest.raises(GuardrailError):
            await repository.publish_weight(
                weight["id"],
                if_match="1",
                actor_id=actor_id,
                idempotency_key="weight-publish-1",
                reason="must wait for worker evidence",
            )

        audit = await repository.list_audit(actor=actor_id)
        assert {row["action"] for row in audit} >= {
            "SOURCE_CREATED",
            "SOURCE_UPDATED",
            "MODEL_CREATED",
            "MODEL_UPDATED",
            "WEIGHT_DRAFT_CREATED",
            "WEIGHT_SIMULATION_ENQUEUED",
            "RECOMMENDATION_APPROVED",
        }
    await engine.dispose()
