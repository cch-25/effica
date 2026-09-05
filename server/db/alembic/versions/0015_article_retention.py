"""Remember purged article URLs so undated feeds cannot resurrect them."""
import sqlalchemy as sa
from alembic import op

revision = "0015_article_retention"
down_revision = "0014_luna_high_reasoning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_retention_tombstones",
        sa.Column("canonical_url_hash", sa.BINARY(32), primary_key=True),
        sa.Column("retired_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("article_retention_tombstones")
