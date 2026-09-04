"""Configure the single OpenAI GPT analysis model.

Revision ID: 0006_openai_single_model
Revises: 0005_remove_migration_index
Create Date: 2026-08-16
"""

from __future__ import annotations

from alembic import op

revision = "0006_openai_single_model"
down_revision = "0005_remove_migration_index"
branch_labels = None
depends_on = None

_MODEL_ID = "01K00000000000000000000401"


def upgrade() -> None:
    # Keep historical aliases for assessment provenance, but leave exactly
    # one model eligible for new analysis after the constraint changes.
    op.execute(
        "UPDATE model_aliases SET status = 'DISABLED' WHERE status = 'ACTIVE'"
    )
    op.execute(
        f"""
        INSERT INTO model_aliases
            (id, alias, provider, actual_model_id, status, config_json)
        VALUES
            ('{_MODEL_ID}', 'openai-default', 'openai', 'gpt-5.6-luna', 'ACTIVE',
             JSON_OBJECT('reasoning_effort', 'xhigh',
                         'secret_env_name', 'OPENAI_API_KEY'))
        ON DUPLICATE KEY UPDATE
            provider = 'openai',
            actual_model_id = 'gpt-5.6-luna',
            status = 'ACTIVE',
            config_json = JSON_OBJECT('reasoning_effort', 'xhigh',
                                      'secret_env_name', 'OPENAI_API_KEY')
        """
    )


def downgrade() -> None:
    # Do not delete an alias that may already be referenced by assessments.
    op.execute(
        "UPDATE model_aliases SET status = 'DISABLED' "
        "WHERE alias = 'openai-default' AND provider = 'openai'"
    )
