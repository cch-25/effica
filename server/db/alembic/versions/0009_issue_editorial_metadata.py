"""Add generic editorial metadata for reviewed event issues.

Revision ID: 0009_issue_editorial_metadata
Revises: 0008_efficacy_questionnaire
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_issue_editorial_metadata"
down_revision = "0008_efficacy_questionnaire"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("issues") as batch:
        batch.add_column(
            sa.Column(
                "issue_kind",
                sa.Enum(
                    "EVENT",
                    "TOPIC",
                    name="issue_kind",
                    native_enum=False,
                    create_constraint=True,
                    length=16,
                ),
                nullable=False,
                server_default="TOPIC",
            )
        )
        batch.add_column(sa.Column("editorial_key", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("editorial_priority", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("editorial_reviewed_at", sa.DateTime(timezone=False), nullable=True)
        )
        batch.add_column(
            sa.Column("editorial_data_as_of", sa.DateTime(timezone=False), nullable=True)
        )
        batch.create_check_constraint(
            "positive_editorial_priority",
            "editorial_priority IS NULL OR editorial_priority > 0",
        )
        batch.create_unique_constraint("uq_issues_editorial_key", ["editorial_key"])
        batch.create_index(
            "ix_issues_editorial_order",
            ["issue_kind", "editorial_priority"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("issues") as batch:
        batch.drop_index("ix_issues_editorial_order")
        batch.drop_constraint("uq_issues_editorial_key", type_="unique")
        batch.drop_constraint("positive_editorial_priority", type_="check")
        batch.drop_column("editorial_data_as_of")
        batch.drop_column("editorial_reviewed_at")
        batch.drop_column("editorial_priority")
        batch.drop_column("editorial_key")
        batch.drop_column("issue_kind")
