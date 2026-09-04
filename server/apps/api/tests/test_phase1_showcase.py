from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import AdapterType, ModelStatus
from apps.api.app.db.models import Issue, Job, ModelAlias, Source, SourceAdapter
from apps.api.app.db.ulid import new_ulid
from apps.api.app.domains.content.trust import (
    is_trusted_openai_assessment,
    score_matches_trusted_assessments,
)
from apps.api.app.main import EXPECTED_DB_REVISION
from db.seeds.demo_showcase import (
    DEFAULT_MANIFEST,
    REQUIRED_DB_REVISION,
    ShowcaseManifest,
    audit_showcase,
    load_manifest,
    preflight_showcase,
    refresh_showcase,
)


def _approved_manifest() -> ShowcaseManifest:
    payload = load_manifest(DEFAULT_MANIFEST).model_dump(mode="json")
    for issue in payload["issues"]:
        issue["editorial_review_status"] = "APPROVED"
        issue["reviewed_by"] = "Test content reviewer"
        for article in issue["articles"]:
            article.update(
                {
                    "policy_status": "APPROVED",
                    "robots_status": "APPROVED",
                    "terms_status": "APPROVED",
                    "policy_reference": (
                        f"APPROVED: test review evidence for {article['source_home_url']}robots.txt"
                    ),
                }
            )
    return ShowcaseManifest.model_validate(payload)


def test_default_showcase_manifest_is_event_scoped_and_policy_gated() -> None:
    manifest = load_manifest(Path("db/seeds/demo_showcase.json"))

    assert 3 <= len(manifest.issues) <= 5
    assert [issue.featured_rank for issue in manifest.issues] == [1, 2, 3]
    assert all(len(issue.articles) >= 3 for issue in manifest.issues)
    assert all(
        len({article.source_home_url for article in issue.articles}) >= 3
        for issue in manifest.issues
    )
    assert all(
        sum(article.publisher_kind == "MEDIA" for article in issue.articles) >= 2
        for issue in manifest.issues
    )
    assert REQUIRED_DB_REVISION == EXPECTED_DB_REVISION
    decisions = [article for issue in manifest.issues for article in issue.articles]
    assert all(issue.editorial_review_status == "APPROVED" for issue in manifest.issues)
    assert all(
        issue.reviewed_by
        == "johnnybae (human operator request in Codex thread, 2026-08-27)"
        for issue in manifest.issues
    )
    assert all(
        article.policy_status == article.robots_status == article.terms_status == "APPROVED"
        for article in decisions
    )
    assert all("https://" in article.policy_reference for article in decisions)
    assert sum(article.publisher_kind == "MEDIA" for article in decisions) == 6


def test_showcase_manifest_rejects_government_centered_issue() -> None:
    payload = _approved_manifest().model_dump(mode="json")
    payload["issues"][0]["articles"][0]["publisher_kind"] = "GOVERNMENT"
    payload["issues"][0]["articles"][1]["publisher_kind"] = "GOVERNMENT"

    with pytest.raises(ValidationError, match="two media publishers"):
        ShowcaseManifest.model_validate(payload)


def test_showcase_manifest_rejects_approval_without_review_evidence() -> None:
    payload = load_manifest(DEFAULT_MANIFEST).model_dump(mode="json")
    payload["issues"][0]["articles"][0].update(
        {
            "policy_status": "APPROVED",
            "robots_status": "APPROVED",
            "terms_status": "APPROVED",
            "policy_reference": "PENDING: https://example.test/review",
        }
    )

    with pytest.raises(ValidationError, match="APPROVED decision"):
        ShowcaseManifest.model_validate(payload)


def test_showcase_manifest_rejects_anonymous_editorial_approval() -> None:
    payload = load_manifest(DEFAULT_MANIFEST).model_dump(mode="json")
    payload["issues"][0]["editorial_review_status"] = "APPROVED"
    payload["issues"][0]["reviewed_by"] = "PENDING: assign human content reviewer"

    with pytest.raises(ValidationError, match="identified reviewer"):
        ShowcaseManifest.model_validate(payload)


def test_showcase_manifest_rejects_duplicate_sources() -> None:
    payload = _approved_manifest().model_dump(mode="json")
    payload["issues"][0]["articles"][1]["source_home_url"] = payload["issues"][0]["articles"][0][
        "source_home_url"
    ]
    payload["issues"][0]["articles"][2]["source_home_url"] = payload["issues"][0]["articles"][0][
        "source_home_url"
    ]

    with pytest.raises(ValidationError, match="three distinct sources"):
        ShowcaseManifest.model_validate(payload)


def test_public_trust_filter_rejects_dummy_synthetic_and_unlinked_scores() -> None:
    assessment = SimpleNamespace(
        id="assessment-1",
        status="SUCCEEDED",
        evidence_json={"summary": "real", "synthetic": False},
    )
    alias = SimpleNamespace(
        alias="phase-1-openai",
        provider="openai",
        actual_model_id="gpt-5-mini",
        status="ACTIVE",
    )
    dummy_alias = SimpleNamespace(**{**vars(alias), "alias": "deterministic-stub"})
    historical_alias = SimpleNamespace(**{**vars(alias), "status": "DEPRECATED"})
    non_gpt_alias = SimpleNamespace(**{**vars(alias), "actual_model_id": "other-model"})
    synthetic = SimpleNamespace(**{**vars(assessment), "evidence_json": {"synthetic": True}})

    assert is_trusted_openai_assessment(assessment, alias)
    assert is_trusted_openai_assessment(assessment, historical_alias)
    assert not is_trusted_openai_assessment(assessment, non_gpt_alias)
    assert not is_trusted_openai_assessment(assessment, dummy_alias)
    assert not is_trusted_openai_assessment(synthetic, alias)
    assert score_matches_trusted_assessments(
        SimpleNamespace(
            components_json={
                "analysis_provider": "openai",
                "assessment_ids": ["assessment-1"],
            }
        ),
        [(assessment, alias)],
    )
    assert not score_matches_trusted_assessments(
        SimpleNamespace(
            components_json={
                "analysis_provider": "openai",
                "assessment_ids": ["some-old-assessment"],
            }
        ),
        [(assessment, alias)],
    )


@pytest.mark.asyncio
async def test_showcase_refresh_is_idempotent_and_audit_fails_closed() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    manifest = _approved_manifest()
    expected_sources = {
        article.source_home_url for issue in manifest.issues for article in issue.articles
    }

    async with factory() as session:
        await session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64))"))
        await session.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": REQUIRED_DB_REVISION},
        )
        session.add(
            ModelAlias(
                id=new_ulid(),
                alias="phase-1-openai",
                provider="openai",
                actual_model_id="gpt-5-mini",
                status=ModelStatus.ACTIVE,
                config_json={},
            )
        )
        await session.commit()
        preflight = await preflight_showcase(session, manifest)
        assert preflight["status"] == "passed"
        assert preflight["actual_schema_revision"] == REQUIRED_DB_REVISION
        assert preflight["database_counts"] == {
            "sources": 0,
            "articles": 0,
            "issues": 0,
            "model_assessments": 0,
            "score_versions": 0,
        }
        assert all(
            counts == {"APPROVED": 9}
            for counts in preflight["manifest"]["decision_counts"].values()
        )
        assert preflight["manifest"]["editorial_review_counts"] == {"APPROVED": 3}
        assert preflight["manifest"]["publisher_counts"] == {
            "MEDIA": 6,
            "GOVERNMENT": 3,
        }
        incomplete_payload = manifest.model_dump(mode="json")
        pending_source = incomplete_payload["issues"][0]["articles"][1]["source_home_url"]
        for issue in incomplete_payload["issues"]:
            for article in issue["articles"]:
                if article["source_home_url"] == pending_source:
                    article["robots_status"] = "PENDING"
        incomplete = await preflight_showcase(
            session, ShowcaseManifest.model_validate(incomplete_payload)
        )
        assert incomplete["status"] == "failed"
        assert "robots and terms" in incomplete["errors"][0]
        pending_payload = manifest.model_dump(mode="json")
        pending_payload["issues"][0]["editorial_review_status"] = "PENDING"
        pending_payload["issues"][0]["reviewed_by"] = "PENDING: assign human content reviewer"
        with pytest.raises(ValueError, match="human editorial review"):
            await refresh_showcase(
                session,
                ShowcaseManifest.model_validate(pending_payload),
                apply=True,
                backup_reference="test-backup-before-phase-1",
            )

        dry_run = await refresh_showcase(session, manifest, apply=False)
        assert dry_run.issues_created == 3
        assert dry_run.sources_created == len(expected_sources)
        assert dry_run.scheduled_rss_adapters_planned == 2
        assert dry_run.crawl_jobs_enqueued == 9
        assert await session.scalar(select(func.count()).select_from(Issue)) == 0
        assert await session.scalar(select(func.count()).select_from(Source)) == 0
        assert await session.scalar(select(func.count()).select_from(Job)) == 0

        first = await refresh_showcase(
            session,
            manifest,
            apply=True,
            backup_reference="test-backup-before-phase-1",
        )
        second = await refresh_showcase(
            session,
            manifest,
            apply=True,
            backup_reference="test-backup-before-phase-1",
        )

        assert first.issues_created == 3
        assert first.crawl_jobs_enqueued == 9
        assert first.scheduled_rss_adapters_planned == 2
        assert second.issues_updated == 0
        assert second.crawl_jobs_enqueued == 0
        assert second.scheduled_rss_adapters_planned == 0
        assert await session.scalar(select(func.count()).select_from(Issue)) == 3
        assert await session.scalar(select(func.count()).select_from(Source)) == len(
            expected_sources
        )
        assert await session.scalar(select(func.count()).select_from(SourceAdapter)) == (
            len(expected_sources) + 2
        )
        scheduled_adapters = list(
            (
                await session.scalars(
                    select(SourceAdapter).where(SourceAdapter.adapter_type == AdapterType.RSS)
                )
            ).all()
        )
        assert {adapter.config_json["feed_url"] for adapter in scheduled_adapters} == {
            "https://nwww.newsis.com/RSS/sokbo.xml",
            "https://rss.etoday.co.kr/eto/etoday_news_all.xml",
        }
        assert all(
            adapter.config_json["scheduled"] is True
            and adapter.config_json["hydrate_article_links"] is False
            and adapter.config_json["metadata_only"] is True
            and adapter.config_json["max_items"] == 80
            for adapter in scheduled_adapters
        )
        assert await session.scalar(select(func.count()).select_from(Job)) == 9

        audit = await audit_showcase(session)
        assert audit.exit_code == 1
        assert any("최소 3개" in error for error in audit.errors)

    await engine.dispose()
