"""Persist an automation reservation, its reread and its comparison."""
from alembic import op
import sqlalchemy as sa

revision = "109_automation_review"
down_revision = "108_flow_draft_control_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automation_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("system_id", sa.String(36), sa.ForeignKey("systems.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("draft_hash", sa.String(64), nullable=True),
        sa.Column("correction_hash", sa.String(64), nullable=True),
        sa.Column("later_run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_automation_reviews_workspace_id", "automation_reviews", ["workspace_id"])
    op.create_index("ix_automation_reviews_system_id", "automation_reviews", ["system_id"])


def downgrade():
    op.drop_index("ix_automation_reviews_system_id", table_name="automation_reviews")
    op.drop_index("ix_automation_reviews_workspace_id", table_name="automation_reviews")
    op.drop_table("automation_reviews")
