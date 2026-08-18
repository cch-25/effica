"""Add the question-bearing efficacy questionnaire revision.

Revision ID: 0008_efficacy_questionnaire
Revises: 0007_credit_reversal_uniqueness
Create Date: 2026-08-19

The original bootstrap stored efficacy ``1.0`` with only scale metadata.
Questionnaire definitions are immutable once responses can reference them, so
the baseline/current questions are introduced as revision ``1.1`` rather than
rewriting the existing row.  The insert is safe to rerun for an operator that
has already seeded the revision by hand.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_efficacy_questionnaire"
down_revision = "0007_credit_reversal_uniqueness"
branch_labels = None
depends_on = None

_QUESTIONNAIRE_ID = "01K00000000000000000000801"


def upgrade() -> None:
    # The unique (kind, version) key makes this seed idempotent.  The no-op
    # duplicate clause deliberately does not replace an existing definition;
    # questionnaire rows are immutable and may already have responses.
    op.execute(
        sa.text(
            f"""
            INSERT INTO questionnaire_versions
                (id, kind, version, schema_json, scoring_json, active_from)
            VALUES
                ('{_QUESTIONNAIRE_ID}', 'efficacy', '1.1',
                 JSON_OBJECT(
                     'scale', JSON_OBJECT('minimum', 0, 'maximum', 100),
                     'questions', JSON_ARRAY(
                         JSON_OBJECT('id', 'baseline', 'required', TRUE,
                                     'minimum', 0, 'maximum', 100),
                         JSON_OBJECT('id', 'current', 'required', TRUE,
                                     'minimum', 0, 'maximum', 100)
                     )
                 ),
                 JSON_OBJECT('method', 'mean', 'reverse_items', JSON_ARRAY()),
                 CURRENT_TIMESTAMP(6))
            ON DUPLICATE KEY UPDATE id = id
            """
        )
    )


def downgrade() -> None:
    # The response FK is RESTRICT, so a questionnaire that has already been
    # answered remains immutable and the downgrade fails before Alembic moves
    # its revision marker.  Fresh/unused installations can still roll back.
    op.execute(
        sa.text(
            "DELETE FROM questionnaire_versions "
            "WHERE kind = 'efficacy' AND version = '1.1'"
        )
    )
