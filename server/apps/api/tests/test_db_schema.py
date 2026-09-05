"""Regression checks for the physical schema contract.

These assertions are dialect-neutral metadata checks; MariaDB-only CHECK
behaviour is covered by the migration's offline SQL and live integration
environment when one is available.
"""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.base import metadata
from app.db.models import CreditLedger, ScoreVersion
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

from apps.api.app.main import EXPECTED_DB_REVISION


def _checks(table_name: str) -> dict[str, str]:
    table = metadata.tables[table_name]
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_readiness_revision_matches_the_single_migration_head() -> None:
    config = Config("db/alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [EXPECTED_DB_REVISION]


def test_schema_preserves_initial_tables_and_adds_evidence_snapshot() -> None:
    assert len(metadata.tables) == 41
    assert "article_retention_tombstones" in metadata.tables
    assert "weight_evidence_snapshots" in metadata.tables
    assert "issue_comparison_snapshots" in metadata.tables
    assert {
        "sources",
        "source_adapters",
        "article_versions",
        "read_sessions",
        "weight_recommendations",
        "autopilot_settings",
        "runtime_controls",
        "stored_blobs",
        "job_receipts",
        "admin_request_receipts",
    } <= set(metadata.tables)


def test_source_policy_survives_without_obsolete_raw_storage() -> None:
    sources = metadata.tables["sources"]
    assert sources.c.robots_status.nullable is False
    assert sources.c.terms_status.nullable is False
    assert any("robots_status" in expression for expression in _checks("sources").values())
    assert any("terms_status" in expression for expression in _checks("sources").values())

    adapters = metadata.tables["source_adapters"]
    assert "raw_payload_retention_days" not in adapters.c

    versions = metadata.tables["article_versions"]
    assert "raw_payload_ref" not in versions.c
    assert "raw_payload_expires_at" not in versions.c
    assert "raw_response_ref" not in metadata.tables["model_assessments"].c


def test_read_session_expiry_and_client_elapsed_are_physical_columns() -> None:
    table = metadata.tables["read_sessions"]
    assert table.c.expires_at.nullable is False
    assert table.c.client_elapsed_ms.nullable is True
    assert any(
        isinstance(index, Index)
        and index.name == "ix_read_sessions_user_expires"
        for index in table.indexes
    )


def test_evidence_snapshot_is_json_checked_and_referenced() -> None:
    snapshots = metadata.tables["weight_evidence_snapshots"]
    assert snapshots.c.evidence_json.nullable is False
    assert any("JSON_VALID(evidence_json)" in expression for expression in _checks("weight_evidence_snapshots").values())

    recommendations = metadata.tables["weight_recommendations"]
    foreign_keys = {
        foreign_key.target_fullname
        for constraint in recommendations.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for foreign_key in constraint.elements
    }
    assert "weight_evidence_snapshots.id" in foreign_keys


def test_autopilot_is_a_versioned_singleton() -> None:
    table = metadata.tables["autopilot_settings"]
    assert table.c.singleton_key.nullable is False
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_autopilot_settings_singleton_key"
        for constraint in table.constraints
    )
    assert any("version > 0" in expression for expression in _checks("autopilot_settings").values())


def test_blob_integrity_and_size_checks_are_database_constraints() -> None:
    checks = _checks("stored_blobs")
    expressions = set(checks.values())
    assert any("OCTET_LENGTH(payload)" in expression for expression in expressions)
    assert any("byte_size >= 0" in expression for expression in expressions)
    assert any("byte_size <= 10485760" in expression for expression in expressions)


def test_score_recalculation_is_not_blocked_by_pair_uniqueness() -> None:
    assert not any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_score_versions_article_weight"
        for constraint in ScoreVersion.__table__.constraints
    )
    assert any(index.name == "ix_score_versions_article_weight_created" for index in ScoreVersion.__table__.indexes)


def test_audit_table_is_removed_and_replay_receipts_remain() -> None:
    assert "audit_logs" not in metadata.tables
    assert "job_receipts" in metadata.tables
    assert "admin_request_receipts" in metadata.tables


def test_credit_ledger_matches_append_only_reversal_contract() -> None:
    table = CreditLedger.__table__
    status = table.c.status.type
    assert set(status.enums) == {"posted", "reversed", "voided"}
    assert table.c.reversed_ledger_id.nullable is True
    assert any(
        foreign_key.target_fullname == "credit_ledger.id"
        and foreign_key.ondelete == "RESTRICT"
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for foreign_key in constraint.elements
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_credit_ledger_reversed_source"
        for constraint in table.constraints
    )
