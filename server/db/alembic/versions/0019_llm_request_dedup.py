"""Persist paid-input identity and replayable responses across worker restarts."""

import sqlalchemy as sa
from alembic import op

revision = "0019_llm_request_dedup"
down_revision = "0018_llm_cost_guardrails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_daily_articles",
        sa.Column("usage_date", sa.Date(), primary_key=True),
        sa.Column("article_key", sa.String(255), primary_key=True),
    )
    op.create_table(
        "llm_requests",
        sa.Column("request_key", sa.String(64), primary_key=True),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("subject_key", sa.String(255), nullable=True),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("category IN ('article', 'comparison')", name="valid_llm_category"),
        sa.CheckConstraint("state IN ('SUBMITTED', 'SUCCEEDED')", name="valid_llm_request_state"),
        sa.CheckConstraint(
            "JSON_VALID(response_json)",
            name="json_valid_response_json",
        ),
    )
    op.create_index(
        "ix_llm_requests_subject_day", "llm_requests",
        ["category", "usage_date", "subject_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_requests_subject_day", table_name="llm_requests")
    op.drop_table("llm_requests")
    op.drop_table("llm_daily_articles")
