"""Allow at most one durable reversal for each original ledger entry.

Revision ID: 0007_credit_reversal_uniqueness
Revises: 0006_openai_single_model
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op

revision = "0007_credit_reversal_uniqueness"
down_revision = "0006_openai_single_model"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_credit_ledger_reversed_source"


def upgrade() -> None:
    # A nullable unique key permits any number of ordinary entries while
    # serializing the non-null reversal target to one row.
    op.create_unique_constraint(_CONSTRAINT, "credit_ledger", ["reversed_ledger_id"])


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "credit_ledger", type_="unique")
