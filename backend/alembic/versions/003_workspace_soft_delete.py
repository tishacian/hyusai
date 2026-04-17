"""Add deleted_at to workspaces for soft-delete

Revision ID: 003_ws_soft_delete
Revises: 002_mfa_account
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "003_ws_soft_delete"
down_revision = "002_mfa_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workspaces_deleted_at", "workspaces", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_workspaces_deleted_at", table_name="workspaces")
    op.drop_column("workspaces", "deleted_at")
