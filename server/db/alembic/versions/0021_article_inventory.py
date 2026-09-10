"""Serialize article inventory and detach expired content from activity history."""
import sqlalchemy as sa
from alembic import op

revision = "0021_article_inventory"
down_revision = "0020_questionnaire_beta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("article_inventory_guard", sa.Column("id", sa.Integer(), primary_key=True))
    op.execute("INSERT INTO article_inventory_guard (id) VALUES (1)")
    for table in ("votes", "read_sessions"):
        name = f"fk_{table}_article_id_articles"
        op.drop_constraint(name, table, type_="foreignkey")
        op.alter_column(table, "article_id", existing_type=sa.CHAR(26), nullable=True)
        op.create_foreign_key(name, table, "articles", ["article_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    raise RuntimeError("Restore a pre-0021 backup to restore removed article associations.")
