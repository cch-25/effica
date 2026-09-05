"""Set the active OpenAI analysis model to Luna with high reasoning.

Revision ID: 0014_luna_high_reasoning
Revises: 0013_runtime_llm_control
Create Date: 2026-09-04
"""

from __future__ import annotations

from alembic import op

revision = "0014_luna_high_reasoning"
down_revision = "0013_runtime_llm_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE model_aliases
        SET actual_model_id = 'gpt-5.6-luna',
            config_json = JSON_SET(
                COALESCE(config_json, JSON_OBJECT()),
                '$.reasoning_effort', 'high',
                '$.secret_env_name', 'OPENAI_API_KEY'
            )
        WHERE provider = 'openai' AND status = 'ACTIVE'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE model_aliases
        SET config_json = JSON_SET(
                COALESCE(config_json, JSON_OBJECT()),
                '$.reasoning_effort', 'xhigh'
            )
        WHERE provider = 'openai' AND status = 'ACTIVE'
          AND actual_model_id = 'gpt-5.6-luna'
        """
    )
