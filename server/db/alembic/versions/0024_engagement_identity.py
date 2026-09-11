"""Retain engagement identities independently of deleted users and content."""
import sqlalchemy as sa
from alembic import op

revision = "0024_engagement_identity"
down_revision = "0023_article_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("vote_revision", sa.BigInteger(), nullable=False, server_default="0"))
    op.execute("""UPDATE articles a SET vote_revision = GREATEST(
        COALESCE((SELECT MAX(v.revision) FROM votes v WHERE v.article_id=a.id), 0),
        COALESCE((SELECT MAX(s.version) FROM vote_aggregate_snapshots s WHERE s.article_id=a.id), 0),
        COALESCE((SELECT MAX(CAST(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(j.payload_json, '$.version')),
                SUBSTRING_INDEX(j.dedupe_key, ':', -1)) AS UNSIGNED))
            FROM jobs j WHERE j.job_type='aggregate_votes'
            AND JSON_UNQUOTE(JSON_EXTRACT(j.payload_json, '$.article_id'))=a.id), 0)
    )""")
    op.add_column("read_sessions", sa.Column("article_key", sa.CHAR(26), nullable=True))
    # Already detached histories have irrecoverably lost the original article
    # IDs. Preserve each such record, rather than collapsing all of them to NULL.
    op.execute("UPDATE read_sessions SET article_key = COALESCE(article_id, id)")


def downgrade() -> None:
    op.drop_column("read_sessions", "article_key")
    op.drop_column("articles", "vote_revision")
