"""Replace unbounded audit payloads with compact replay receipts."""
import sqlalchemy as sa
from alembic import op

revision = "0016_essential_storage"
down_revision = "0015_article_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("sources", "model_aliases"):
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.execute("UPDATE sources s SET version = GREATEST(1, (SELECT COUNT(*) FROM audit_logs a WHERE a.target_type = 'source' AND a.target_id = s.id AND a.action IN ('SOURCE_CREATED','SOURCE_UPDATED')))")
    op.execute("UPDATE model_aliases m SET version = GREATEST(1, (SELECT COUNT(*) FROM audit_logs a WHERE a.target_type = 'model' AND a.target_id = m.id AND a.action IN ('MODEL_CREATED','MODEL_UPDATED')))")
    op.create_table(
        "job_receipts",
        sa.Column("job_id", sa.CHAR(26), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "admin_request_receipts",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.execute("""INSERT IGNORE INTO job_receipts (job_id, job_type, result_json, applied_at)
        SELECT j.id, j.job_type, JSON_OBJECT('applied', TRUE), a.created_at
        FROM audit_logs a JOIN jobs j ON j.id = a.target_id
        WHERE a.action = 'JOB_RESULT_APPLIED' AND a.target_type = 'job'""")
    op.execute("""INSERT IGNORE INTO admin_request_receipts (key_hash, data_json, created_at)
        SELECT target_id, after_json, created_at FROM audit_logs
        WHERE action = 'IDEMPOTENCY_RECORDED' AND target_type = 'idempotency'
        AND created_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        ORDER BY created_at DESC""")
    # No runtime code uses audit history after this migration. TRUNCATE also
    # releases its large physical table allocation on a restored database.
    op.execute("TRUNCATE TABLE audit_logs")


def downgrade() -> None:
    # Deleted audit payloads are intentionally not reconstructed.
    op.drop_table("admin_request_receipts")
    op.drop_table("job_receipts")
    op.drop_column("model_aliases", "version")
    op.drop_column("sources", "version")
