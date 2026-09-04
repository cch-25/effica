"""Correct physical gaps discovered after the initial MAS schema audit.

Revision ID: 0002_schema_corrections
Revises: 0001_initial
Create Date: 2026-08-16

The initial migration is shared and immutable.  This revision is deliberately
additive/corrective: new columns are added nullable, legacy values are
backfilled, and constraints are enforced only after the backfill.  The
evidence table is intentional: recommendations need a durable JSON input
snapshot rather than an unverified cross-service ULID.
"""

# ruff: noqa: E501

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0002_schema_corrections"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _dt() -> sa.types.TypeEngine:
    return mysql.DATETIME(fsp=6)


def _json() -> sa.types.TypeEngine:
    return mysql.JSON()


def _policy_check(column: str) -> str:
    return f"{column} IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')"


def upgrade() -> None:
    # Source crawler permission is persisted independently from the aggregate
    # source lifecycle status.  Existing sources inherit their current policy
    # state until an operator records a separate decision.
    op.add_column(
        "sources",
        sa.Column("robots_status", sa.String(16), nullable=True, server_default="PENDING"),
    )
    op.add_column(
        "sources",
        sa.Column("terms_status", sa.String(16), nullable=True, server_default="PENDING"),
    )
    op.execute(
        sa.text(
            "UPDATE sources "
            "SET robots_status = COALESCE(robots_status, policy_status), "
            "terms_status = COALESCE(terms_status, policy_status)"
        )
    )
    op.alter_column(
        "sources",
        "robots_status",
        existing_type=sa.String(16),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "sources",
        "terms_status",
        existing_type=sa.String(16),
        nullable=False,
        server_default=None,
    )
    op.create_check_constraint(
        "robots_status",
        "sources",
        _policy_check("robots_status"),
    )
    op.create_check_constraint(
        "terms_status",
        "sources",
        _policy_check("terms_status"),
    )

    # Adapter retention is explicit metadata; the raw payload itself is
    # referenced from article_versions and may live in stored_blobs/object
    # storage under the source's legal retention policy.
    op.add_column(
        "source_adapters",
        sa.Column("raw_payload_retention_days", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "nonnegative_raw_payload_retention_days",
        "source_adapters",
        "raw_payload_retention_days IS NULL OR raw_payload_retention_days >= 0",
    )
    op.add_column(
        "article_versions",
        sa.Column("raw_payload_ref", sa.String(1024), nullable=True),
    )
    op.add_column(
        "article_versions",
        sa.Column("raw_payload_expires_at", _dt(), nullable=True),
    )

    # ``client_elapsed_ms`` already exists in 0001 and is retained.  Expiry is
    # added nullable, populated for legacy rows, then made mandatory so every
    # persisted session has the server-side token/session deadline.
    op.add_column("read_sessions", sa.Column("expires_at", _dt(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE read_sessions SET expires_at = "
            "DATE_ADD(COALESCE(outbound_at, returned_at, CURRENT_TIMESTAMP(6)), INTERVAL 1 DAY) "
            "WHERE expires_at IS NULL"
        )
    )
    op.alter_column(
        "read_sessions",
        "expires_at",
        existing_type=_dt(),
        nullable=False,
    )
    op.create_index(
        "ix_read_sessions_user_expires",
        "read_sessions",
        ["user_id", "expires_at"],
    )

    # A recommendation's evidence reference now points to a durable JSON
    # snapshot.  Rows are append-only by service convention and RESTRICT keeps
    # referenced evidence from being deleted accidentally.
    op.create_table(
        "weight_evidence_snapshots",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("evidence_json", _json(), nullable=False),
        sa.Column("window_start", _dt(), nullable=True),
        sa.Column("window_end", _dt(), nullable=True),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_weight_evidence_snapshots"),
        _json_check("evidence_json"),
        sa.CheckConstraint(
            "window_end IS NULL OR window_start IS NULL OR window_end >= window_start",
            name="evidence_window_order",
        ),
    )
    op.create_foreign_key(
        "fk_weight_recommendations_evidence_snapshot_id_weight_evidence_snapshots",
        "weight_recommendations",
        "weight_evidence_snapshots",
        ["evidence_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Auto Pilot settings are one logical resource.  Existing duplicate rows
    # intentionally make this unique-constraint step fail rather than being
    # silently discarded; operators must choose the canonical row first.
    op.add_column(
        "autopilot_settings",
        sa.Column("singleton_key", sa.String(32), nullable=True, server_default="global"),
    )
    op.execute(
        sa.text(
            "UPDATE autopilot_settings SET singleton_key = 'global' "
            "WHERE singleton_key IS NULL"
        )
    )
    op.alter_column(
        "autopilot_settings",
        "singleton_key",
        existing_type=sa.String(32),
        nullable=False,
        server_default="global",
    )
    op.create_unique_constraint(
        "uq_autopilot_settings_singleton_key",
        "autopilot_settings",
        ["singleton_key"],
    )

    # byte_size is derived from payload and must not drift.  Recompute legacy
    # metadata before replacing the broad initial check with explicit
    # nonnegative, maximum-size, and byte-length checks.
    op.execute(sa.text("UPDATE stored_blobs SET byte_size = OCTET_LENGTH(payload)"))
    op.drop_constraint("blob_size_limit", "stored_blobs", type_="check")
    op.create_check_constraint("nonnegative_byte_size", "stored_blobs", "byte_size >= 0")
    op.create_check_constraint("blob_size_limit", "stored_blobs", "byte_size <= 10485760")
    op.create_check_constraint(
        "blob_byte_size_matches_payload",
        "stored_blobs",
        "byte_size = OCTET_LENGTH(payload)",
    )

    # Scores are immutable snapshots.  Recalculating an article with the same
    # weight revision must append another row rather than collide with the
    # original snapshot.
    op.drop_constraint(
        "uq_score_versions_article_weight",
        "score_versions",
        type_="unique",
    )
    op.create_index(
        "ix_score_versions_article_weight_created",
        "score_versions",
        ["article_version_id", "weight_revision_id", "created_at"],
    )

    # Audit target IDs are polymorphic.  Most targets are ULIDs, but singleton
    # resources use stable labels such as ``singleton``.
    op.alter_column(
        "audit_logs",
        "target_id",
        existing_type=sa.CHAR(26),
        type_=sa.String(128),
        existing_nullable=True,
    )

    # credit_ledger already matches the append-only service contract: service
    # reversals are REVERSAL event rows linked by reversed_ledger_id, while
    # status defaults to posted for payloads that do not carry a status key.


def downgrade() -> None:
    # Downgrading can fail if recalculation snapshots share an article/weight
    # pair, if multiple Auto Pilot rows were prevented from coexisting, or if
    # audit target IDs contain non-ULID singleton labels.  Take a backup and
    # remediate those rows before invoking this intentionally lossy downgrade.
    op.alter_column(
        "audit_logs",
        "target_id",
        existing_type=sa.String(128),
        type_=sa.CHAR(26),
        existing_nullable=True,
    )

    op.drop_index("ix_score_versions_article_weight_created", table_name="score_versions")
    op.create_unique_constraint(
        "uq_score_versions_article_weight",
        "score_versions",
        ["article_version_id", "weight_revision_id"],
    )

    op.drop_constraint("blob_byte_size_matches_payload", "stored_blobs", type_="check")
    op.drop_constraint("blob_size_limit", "stored_blobs", type_="check")
    op.drop_constraint("nonnegative_byte_size", "stored_blobs", type_="check")
    op.create_check_constraint(
        "blob_size_limit",
        "stored_blobs",
        "byte_size BETWEEN 0 AND 10485760",
    )

    op.drop_constraint(
        "uq_autopilot_settings_singleton_key",
        "autopilot_settings",
        type_="unique",
    )
    op.drop_column("autopilot_settings", "singleton_key")

    op.drop_constraint(
        "fk_weight_recommendations_evidence_snapshot_id_weight_evidence_snapshots",
        "weight_recommendations",
        type_="foreignkey",
    )
    op.drop_table("weight_evidence_snapshots")

    op.drop_index("ix_read_sessions_user_expires", table_name="read_sessions")
    op.drop_column("read_sessions", "expires_at")

    op.drop_column("article_versions", "raw_payload_expires_at")
    op.drop_column("article_versions", "raw_payload_ref")
    op.drop_constraint(
        "nonnegative_raw_payload_retention_days",
        "source_adapters",
        type_="check",
    )
    op.drop_column("source_adapters", "raw_payload_retention_days")

    op.drop_constraint("terms_status", "sources", type_="check")
    op.drop_constraint("robots_status", "sources", type_="check")
    op.drop_column("sources", "terms_status")
    op.drop_column("sources", "robots_status")


def _json_check(column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"JSON_VALID({column})", name=f"json_valid_{column}")
