"""Versioned evaluation suites and durable canonical Run comparisons."""
from alembic import op
import sqlalchemy as sa

revision = "104_evaluation_campaigns"
down_revision = "103_human_confirmation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("evaluation_suites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("system_id", sa.String(36), sa.ForeignKey("systems.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("cases", sa.JSON(), nullable=False),
        sa.Column("corpus_manifest", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "system_id", "name", "revision", name="uq_evaluation_suite_revision"))
    op.create_table("evaluation_campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("system_id", sa.String(36), sa.ForeignKey("systems.id"), nullable=False),
        sa.Column("suite_id", sa.String(36), sa.ForeignKey("evaluation_suites.id"), nullable=False),
        sa.Column("baseline_run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("workspace_jobs.id")),
        sa.Column("request_key", sa.String(160), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.UniqueConstraint("workspace_id", "created_by_user_id", "request_key", name="uq_evaluation_campaign_request"))
    for table in ("evaluation_suites", "evaluation_campaigns"):
        for field in ("workspace_id", "system_id"):
            op.create_index(f"ix_{table}_{field}", table, [field])


def downgrade():
    op.drop_table("evaluation_campaigns")
    op.drop_table("evaluation_suites")
