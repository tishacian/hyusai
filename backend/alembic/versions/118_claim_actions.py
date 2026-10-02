"""Record unique simulated claim actions after canonical human approval.

Revision ID: 118_claim_actions
Revises: 117_collection_access
"""
import sqlalchemy as sa
from alembic import op

revision = "118_claim_actions"
down_revision = "117_collection_access"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "claim_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("order_id", sa.String(80), nullable=False),
        sa.Column("claim_id", sa.String(80), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("decision_id", sa.String(36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "order_id", "action", name="uq_claim_actions_order_action"),
        sa.UniqueConstraint("workspace_id", "run_id", name="uq_claim_actions_run"),
    )
    op.create_index("ix_claim_actions_workspace_id", "claim_actions", ["workspace_id"])


def downgrade():
    op.drop_table("claim_actions")
