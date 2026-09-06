"""Add durable daily LLM cost authorization and lower reasoning spend."""

import sqlalchemy as sa
from alembic import op

revision = "0018_llm_cost_guardrails"
down_revision = "0017_remove_obsolete_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_daily_usage",
        sa.Column("usage_date", sa.Date(), primary_key=True),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("article_request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comparison_request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_microusd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("observed_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("request_count >= 0", name="nonnegative_llm_request_count"),
        sa.CheckConstraint(
            "article_request_count >= 0",
            name="nonnegative_llm_article_request_count",
        ),
        sa.CheckConstraint(
            "comparison_request_count >= 0",
            name="nonnegative_llm_comparison_request_count",
        ),
        sa.CheckConstraint(
            "reserved_microusd >= 0",
            name="nonnegative_llm_reserved_microusd",
        ),
        sa.CheckConstraint(
            "observed_tokens >= 0",
            name="nonnegative_llm_observed_tokens",
        ),
    )
    op.execute(
        """
        UPDATE model_aliases
        SET actual_model_id = 'gpt-5.6-luna',
            config_json = JSON_SET(
                COALESCE(config_json, JSON_OBJECT()),
                '$.reasoning_effort', 'none',
                '$.secret_env_name', 'OPENAI_API_KEY'
            ),
            version = version + 1
        WHERE provider = 'openai' AND status = 'ACTIVE'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE model_aliases
        SET config_json = JSON_SET(
            COALESCE(config_json, JSON_OBJECT()),
            '$.reasoning_effort', 'high'
        )
        WHERE provider = 'openai' AND status = 'ACTIVE'
        """
    )
    op.drop_table("llm_daily_usage")
