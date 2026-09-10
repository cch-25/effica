"""Include bounded daily issue search in the shared paid-request ledger."""

from alembic import op

revision = "0022_issue_discovery_budget"
down_revision = "0021_article_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("valid_llm_category", "llm_requests", type_="check")
    op.create_check_constraint(
        "valid_llm_category", "llm_requests",
        "category IN ('article', 'comparison', 'discovery')",
    )


def downgrade() -> None:
    # Paid-submission evidence must survive rollback and continue to suppress retries.
    raise RuntimeError("Restore a pre-0022 backup to remove discovery ledger entries safely.")
