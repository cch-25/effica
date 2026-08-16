"""Remove the temporary MariaDB score FK migration index.

Revision ID: 0005_remove_migration_index
Revises: 0004_mariadb_ledger_fk
Create Date: 2026-08-16

The Alembic environment creates this index only so immutable revision 0002 can
replace its unique composite key without briefly leaving a foreign key
unindexed. Revision 0002's final composite index starts with the same FK column,
so the temporary index is redundant at the migration head.
"""

from __future__ import annotations

from alembic import op

revision = "0005_remove_migration_index"
down_revision = "0004_mariadb_ledger_fk"
branch_labels = None
depends_on = None

_INDEX = "ix_score_versions_article_version_migration"


def upgrade() -> None:
    op.drop_index(_INDEX, table_name="score_versions")


def downgrade() -> None:
    op.create_index(_INDEX, "score_versions", ["article_version_id"])
