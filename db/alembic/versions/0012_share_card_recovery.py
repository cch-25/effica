"""Persist terminal share-card render failures.

Revision ID: 0012_share_card_recovery
Revises: 0011_issue_topics
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op

revision = "0012_share_card_recovery"
down_revision = "0011_issue_topics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE share_cards
        SET status = 'failed'
        WHERE status IN ('queued', 'rendering')
          AND EXISTS (
            SELECT 1
            FROM jobs
            WHERE jobs.job_type = 'render_share_card'
              AND jobs.dedupe_key = share_cards.id
              AND jobs.status IN ('FAILED', 'DEAD', 'CANCELLED')
          )
        """
    )


def downgrade() -> None:
    # A terminal render failure cannot be reconstructed as active work safely.
    pass
