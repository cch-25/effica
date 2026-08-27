"""Add public issue topics.

Revision ID: 0011_issue_topics
Revises: 0010_issue_comparison_snapshots
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_issue_topics"
down_revision = "0010_issue_comparison_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("issues") as batch:
        batch.add_column(
            sa.Column("topic", sa.String(length=40), nullable=False, server_default="일반")
        )
        batch.create_index("ix_issues_topic", ["topic"], unique=False)

    op.execute(
        """
        UPDATE issues
        SET topic = CASE
          WHEN LOWER(CONCAT(title, ' ', COALESCE(summary, ''))) REGEXP '국제|외교|안보|북한|한미|한일|우크라이나|통상|관세|무역|공급망' THEN '국제'
          WHEN LOWER(CONCAT(title, ' ', COALESCE(summary, ''))) REGEXP '산업|인공지능|ai|반도체|디지털|로봇|바이오|자동차|조선|에너지|기술|연구개발|우주|이차전지|제조' THEN '산업'
          WHEN LOWER(CONCAT(title, ' ', COALESCE(summary, ''))) REGEXP '경제|금융|금리|재정|세금|물가|부동산|주택|고용|중소기업' THEN '경제'
          WHEN LOWER(CONCAT(title, ' ', COALESCE(summary, ''))) REGEXP '정치|대통령|국회|정당|선거|총선|대선|입법' THEN '정치'
          WHEN LOWER(CONCAT(title, ' ', COALESCE(summary, ''))) REGEXP '사회|교육|학교|재난|화재|범죄|경찰|복지|아동|청년|문화|보건|의료|노동|환경|기후|교통' THEN '사회'
          ELSE '일반'
        END
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("issues") as batch:
        batch.drop_index("ix_issues_topic")
        batch.drop_column("topic")
