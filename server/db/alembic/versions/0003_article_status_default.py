"""Align the article status server default with its persisted enum values.

Revision ID: 0003_article_status_default
Revises: 0002_schema_corrections
Create Date: 2026-08-16

The shared initial migration declared the lowercase article-status CHECK but
used an uppercase server default.  ORM writes supplied an explicit value and
therefore hid the mismatch; direct ingestion inserts could fail.  Correct it
in a new migration without rewriting published history.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_article_status_default"
down_revision = "0002_schema_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "articles",
        "status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default="active",
    )


def downgrade() -> None:
    # Restore the historical default exactly.  It is intentionally invalid
    # under the lowercase CHECK and is retained only for migration symmetry.
    op.alter_column(
        "articles",
        "status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default="ACTIVE",
    )
