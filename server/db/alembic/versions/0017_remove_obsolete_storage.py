"""Remove retired audit storage and raw-content columns."""
import sqlalchemy as sa
from alembic import op

revision = "0017_remove_obsolete_storage"
down_revision = "0016_essential_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_constraint("nonnegative_raw_payload_retention_days", "source_adapters", type_="check")
    op.drop_column("source_adapters", "raw_payload_retention_days")
    op.drop_column("article_versions", "raw_payload_expires_at")
    op.drop_column("article_versions", "raw_payload_ref")
    op.drop_column("model_assessments", "raw_response_ref")
    op.execute("UPDATE source_adapters SET config_json = JSON_REMOVE(config_json, '$.raw_payload_retention_days', '$.raw_payload_expires_at')")
    op.execute("UPDATE jobs SET payload_json = JSON_REMOVE(payload_json, '$.raw_payload_retention_days', '$.raw_payload_expires_at', '$.config.raw_payload_retention_days', '$.config_json.raw_payload_retention_days', '$.adapter_config.raw_payload_retention_days')")


def downgrade() -> None:
    # Recreate only the previous schema. Removed diagnostics are not restored.
    op.add_column("source_adapters", sa.Column("raw_payload_retention_days", sa.Integer(), nullable=True))
    op.create_check_constraint("nonnegative_raw_payload_retention_days", "source_adapters", "raw_payload_retention_days IS NULL OR raw_payload_retention_days >= 0")
    op.add_column("article_versions", sa.Column("raw_payload_ref", sa.String(1024), nullable=True))
    op.add_column("article_versions", sa.Column("raw_payload_expires_at", sa.DateTime(), nullable=True))
    op.add_column("model_assessments", sa.Column("raw_response_ref", sa.String(1024), nullable=True))
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.CHAR(26), primary_key=True),
        sa.Column("actor_id", sa.CHAR(26), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(128), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_target_created", "audit_logs", ["target_type", "target_id", "created_at"])
