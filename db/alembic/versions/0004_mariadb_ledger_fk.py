"""Make the append-only credit reversal reference MariaDB-compatible.

Revision ID: 0004_mariadb_ledger_fk
Revises: 0003_article_status_default
Create Date: 2026-08-16

MariaDB 11.8 rejects CHECK expressions that reference a column affected by an
ON DELETE SET NULL foreign key action. Credit ledger rows are append-only, so
RESTRICT is also the correct deletion policy for reversal references.
"""

from __future__ import annotations

from alembic import op

revision = "0004_mariadb_ledger_fk"
down_revision = "0003_article_status_default"
branch_labels = None
depends_on = None

_CONSTRAINT = "fk_credit_ledger_reversed_ledger_id_credit_ledger"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "credit_ledger", type_="foreignkey")
    op.create_foreign_key(
        _CONSTRAINT,
        "credit_ledger",
        "credit_ledger",
        ["reversed_ledger_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    raise RuntimeError(
        "MariaDB 11.8 cannot restore the former SET NULL self-FK while the reversal CHECK exists; "
        "restore a pre-0004 database backup instead"
    )
