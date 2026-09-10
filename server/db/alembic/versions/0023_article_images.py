"""Keep publisher-provided article preview images alongside article metadata."""
import sqlalchemy as sa
from alembic import op

revision = "0023_article_images"
down_revision = "0022_issue_discovery_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("image_url", sa.String(2048), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "image_url")
