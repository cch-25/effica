"""Add reviewed, versioned issue comparison snapshots.

Revision ID: 0010_issue_comparison_snapshots
Revises: 0009_issue_editorial_metadata
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0010_issue_comparison_snapshots"
down_revision = "0009_issue_editorial_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issue_comparison_snapshots",
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("issue_id", sa.CHAR(length=26), nullable=False),
        sa.Column("issue_version", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("model_alias_id", sa.CHAR(length=26), nullable=False),
        sa.Column("common_facts_json", mysql.JSON(), nullable=False),
        sa.Column("framing_dimensions_json", mysql.JSON(), nullable=False),
        sa.Column("article_frames_json", mysql.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("reviewed_by", sa.CHAR(length=26), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','SUCCEEDED','FAILED','SUPERSEDED')",
            name="ck_issue_comparison_snapshots_status",
        ),
        sa.CheckConstraint("issue_version > 0", name="ck_issue_comparison_snapshots_positive_issue_version"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_issue_comparison_snapshots_confidence_range"),
        sa.CheckConstraint("JSON_VALID(common_facts_json)", name="ck_issue_comparison_snapshots_json_valid_common_facts_json"),
        sa.CheckConstraint("JSON_VALID(framing_dimensions_json)", name="ck_issue_comparison_snapshots_json_valid_framing_dimensions_json"),
        sa.CheckConstraint("JSON_VALID(article_frames_json)", name="ck_issue_comparison_snapshots_json_valid_article_frames_json"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_alias_id"], ["model_aliases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issue_id",
            "issue_version",
            "prompt_version",
            name="uq_issue_comparison_issue_version_prompt",
        ),
    )
    op.create_index(
        "ix_issue_comparison_public",
        "issue_comparison_snapshots",
        ["issue_id", "status", "reviewed_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_issue_comparison_public", table_name="issue_comparison_snapshots")
    op.drop_table("issue_comparison_snapshots")
