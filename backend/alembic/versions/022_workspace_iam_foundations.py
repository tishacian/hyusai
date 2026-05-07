"""Workspace IAM foundations.

Revision ID: 022_workspace_iam_foundations
Revises: 021_expert_capture
Create Date: 2026-05-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "022_workspace_iam_foundations"
down_revision = "021_expert_capture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_members", sa.Column("role_template", sa.String(length=80), nullable=True))
    op.add_column("workspace_members", sa.Column("custom_labels", sa.JSON(), nullable=True))
    op.create_index("ix_workspace_members_role_template", "workspace_members", ["role_template"])

    op.execute(
        """
        UPDATE workspace_members
        SET role_template = CASE
            WHEN role = 'owner' THEN 'workspace_owner'
            WHEN role = 'admin' THEN 'workspace_admin'
            ELSE 'workspace_contributor'
        END
        WHERE role_template IS NULL
        """
    )
    op.execute("UPDATE workspace_members SET custom_labels = '[]' WHERE custom_labels IS NULL")

    op.create_table(
        "workspace_iam_configs",
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("role_flags", sa.JSON(), nullable=True),
        sa.Column("capability_overrides", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("workspace_iam_configs")
    op.drop_index("ix_workspace_members_role_template", table_name="workspace_members")
    op.drop_column("workspace_members", "custom_labels")
    op.drop_column("workspace_members", "role_template")

