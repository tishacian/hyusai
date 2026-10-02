"""Persist server-timed human benchmark trials, separate from production ROI.

Revision ID: 119_claim_trials
Revises: 118_claim_actions
"""
import sqlalchemy as sa
from alembic import op
revision = "119_claim_trials"
down_revision = "118_claim_actions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("claim_trials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("operator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("protocol_sha256", sa.String(64), nullable=False),
        sa.Column("pair_id", sa.String(40), nullable=False),
        sa.Column("condition", sa.String(20), nullable=False),
        sa.Column("claim_id", sa.String(80), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()), sa.Column("review", sa.JSON()),
        sa.Column("started_at", sa.DateTime(), nullable=False), sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint("workspace_id", "protocol_sha256", "pair_id", "condition", name="uq_claim_trials_condition"))
    op.create_index("ix_claim_trials_workspace_id", "claim_trials", ["workspace_id"])


def downgrade():
    op.drop_table("claim_trials")
