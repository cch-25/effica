"""Add a fail-closed runtime switch for background LLM work.

Revision ID: 0013_runtime_llm_control
Revises: 0012_share_card_recovery
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0013_runtime_llm_control"
down_revision = "0012_share_card_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_controls",
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column(
            "singleton_key",
            sa.String(length=32),
            nullable=False,
            server_default="global",
        ),
        sa.Column(
            "llm_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "singleton_key", name="uq_runtime_controls_singleton_key"
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_runtime_controls_positive_version"
        ),
    )
    op.execute(
        """
        INSERT INTO runtime_controls
          (id, singleton_key, llm_enabled, version, updated_by, updated_at)
        VALUES
          ('01K3W0R0000000000000000000', 'global', 0, 1, NULL, CURRENT_TIMESTAMP(6))
        """
    )
    op.execute(
        """
        UPDATE jobs
        SET status = 'CANCELLED', lease_owner = NULL, lease_expires_at = NULL,
            last_error_json = JSON_OBJECT(
              'code', 'LLM_USAGE_DISABLED',
              'message', 'Background processing was stopped by the runtime control.',
              'retryable', false
            ),
            updated_at = CURRENT_TIMESTAMP(6)
        WHERE status IN ('PENDING', 'LEASED')
        """
    )
    op.execute(
        """
        UPDATE crawl_runs
        SET status = 'CANCELLED', finished_at = CURRENT_TIMESTAMP(6),
            error_json = JSON_OBJECT(
              'code', 'LLM_USAGE_DISABLED',
              'message', 'Collection was stopped by the runtime control.'
            )
        WHERE status IN ('PENDING', 'RUNNING')
        """
    )


def downgrade() -> None:
    op.drop_table("runtime_controls")
