"""Persist reviewed, idempotent corrections to System drafts."""
from alembic import op
import sqlalchemy as sa
revision = "105_evaluation_corrections"
down_revision = "104_evaluation_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("evaluation_corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("system_id", sa.String(36), sa.ForeignKey("systems.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("proposal_sha256", sa.String(64), nullable=False),
        sa.Column("proposal", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("applied_revision", sa.Integer(), nullable=True),
        sa.Column("applied_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("workspace_id", "created_by_user_id", "idempotency_key", name="uq_evaluation_correction_request"))


def downgrade():
    op.drop_table("evaluation_corrections")
