from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import AdapterType, SourcePolicyStatus
from apps.api.app.db.models import Job, Source, SourceAdapter
from db.seeds.pipeline_recovery import recover_pipeline
from db.seeds.source_feeds import scheduled_publisher_sources


@pytest.mark.asyncio
async def test_publisher_bootstrap_keeps_review_required_sources_out_of_ingestion() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    publishers = scheduled_publisher_sources()
    manual_names = {
        source.name for source in publishers if not source.approve_on_bootstrap
    }
    approved_names = {
        source.name for source in publishers if source.approve_on_bootstrap
    }

    async with factory() as session:
        async with session.begin():
            report = await recover_pipeline(
                session,
                generation="publisher-catalog",
                dry_run=False,
                bootstrap_sources=True,
            )

        stored = list(
            (
                await session.scalars(
                    select(Source).where(Source.name.in_({source.name for source in publishers}))
                )
            ).all()
        )
        stored_by_name = {source.name: source for source in stored}
        adapters = list(
            (
                await session.execute(
                    select(Source.name, SourceAdapter)
                    .join(SourceAdapter, SourceAdapter.source_id == Source.id)
                    .where(Source.name.in_({source.name for source in publishers}))
                )
            ).all()
        )

        assert set(stored_by_name) == {source.name for source in publishers}
        assert {
            name
            for name, source in stored_by_name.items()
            if source.policy_status == SourcePolicyStatus.APPROVED
        } == approved_names
        assert {
            name
            for name, source in stored_by_name.items()
            if source.policy_status == SourcePolicyStatus.PENDING
        } == manual_names
        assert {name for name, adapter in adapters if adapter.adapter_type == AdapterType.RSS} == (
            approved_names
        )
        assert not any(name in manual_names for name, _adapter in adapters)
        assert {
            plan["source"]
            for plan in report["diagnostics"]["scheduled_rss_adapter_plans"]
            if plan["action"] == "REVIEW_REQUIRED"
        } == manual_names

        blocked_name = sorted(manual_names)[0]
        blocked_source = stored_by_name[blocked_name]
        blocked_config = next(
            source for source in publishers if source.name == blocked_name
        )
        session.add(
            SourceAdapter(
                id="01M00000000000000000000000",
                source_id=blocked_source.id,
                adapter_type=AdapterType.RSS,
                config_json={
                    "scheduled": True,
                    "feed_url": blocked_config.feed_url,
                },
                rate_limit=10,
                active=True,
            )
        )
        await session.commit()

        async with session.begin():
            replay = await recover_pipeline(
                session,
                generation="publisher-policy-gate",
                dry_run=False,
            )
        queued = list((await session.scalars(select(Job))).all())
        assert not any(
            (job.payload_json or {}).get("source_id") == blocked_source.id
            for job in queued
        )
        assert replay["deferred"]["crawl_blocked_policy"] >= 1

    await engine.dispose()
