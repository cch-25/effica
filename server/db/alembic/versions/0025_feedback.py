"""Persist the public reader guestbook."""

import sqlalchemy as sa
from alembic import op

revision = "0025_feedback"
down_revision = "0024_engagement_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_entries",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("submission_key", sa.String(36), nullable=False),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("content", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_key", name="uq_feedback_entries_submission_key"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("feedback_entries")
