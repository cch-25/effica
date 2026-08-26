from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import ModelStatus
from apps.api.app.db.models import Issue, Job, ModelAlias, Source, SourceAdapter
from apps.api.app.db.ulid import new_ulid
from apps.api.app.domains.content.trust import (
    is_trusted_openai_assessment,
    public_assessment_evidence,
    public_assessment_summary,
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
    assert REQUIRED_DB_REVISION == EXPECTED_DB_REVISION
    decisions = [article for issue in manifest.issues for article in issue.articles]
    assert all(issue.editorial_review_status == "APPROVED" for issue in manifest.issues)
    assert all(
        issue.reviewed_by
        == "johnnybae (human operator approval in Codex thread, 2026-08-23)"
        for issue in manifest.issues
    )
    assert all(
        article.policy_status == article.robots_status == article.terms_status == "APPROVED"
        for article in decisions
    )
    assert all("https://" in article.policy_reference for article in decisions)


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
    synthetic = SimpleNamespace(**{**vars(assessment), "evidence_json": {"synthetic": True}})

    assert is_trusted_openai_assessment(assessment, alias)
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
    assert score_matches_trusted_assessments(
        SimpleNamespace(
            components_json={
                "분석방식": "LLM",
                "모델평가ID": "assessment-1",
                "근거요약": "기존 시드의 공개 요약",
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


def test_public_assessment_content_preserves_summary_and_has_an_honest_empty_fallback() -> None:
    stored = {
        "rationale_summary": "수치와 절차 중심의 중립적인 행정 안내입니다.",
        "evidence": [],
        "synthetic": False,
    }

    assert public_assessment_summary(stored) == "수치와 절차 중심의 중립적인 행정 안내입니다."
    assert public_assessment_summary(
        {"summary": "이전 요약", "rationale_summary": "검증된 최신 요약", "evidence": []}
    ) == "검증된 최신 요약"
    assert public_assessment_evidence(stored) == []
    assert public_assessment_evidence([{"quote": "기존 저장 형식"}]) == [
        {"quote": "기존 저장 형식"}
    ]
    assert public_assessment_summary([]) == "공개 가능한 근거 인용이 제공되지 않았습니다."


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
        incomplete_payload = manifest.model_dump(mode="json")
        incomplete_payload["issues"][0]["articles"][1]["robots_status"] = "PENDING"
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
        assert second.issues_updated == 0
        assert second.crawl_jobs_enqueued == 0
        assert await session.scalar(select(func.count()).select_from(Issue)) == 3
        assert await session.scalar(select(func.count()).select_from(Source)) == len(
            expected_sources
        )
        assert await session.scalar(select(func.count()).select_from(SourceAdapter)) == len(
            expected_sources
        )
        assert await session.scalar(select(func.count()).select_from(Job)) == 9

        audit = await audit_showcase(session)
        assert audit.exit_code == 1
        assert any("최소 3개" in error for error in audit.errors)

    await engine.dispose()
