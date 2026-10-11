"""Workspace mode (builder/operator/executive) for progressive disclosure.

Revision ID: 008_workspace_mode
Revises: 007_outcome_decision
Create Date: 2026-04-21

Wave 5 of the realignment plan — T5.2. Add a canonical `mode` column to
workspaces so the shell can reveal progressively the Hypervisor/ROI surfaces
based on the operator's persona. Always additive: the underlying data stays,
only the surface adapts.
"""
from alembic import op
import sqlalchemy as sa


revision = "008_workspace_mode"
down_revision = "007_outcome_decision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(
            sa.Column(
                "mode",
                sa.String(length=32),
                nullable=False,
                server_default="executive",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("mode")
