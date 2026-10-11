"""Workspace action items.

Revision ID: 027_workspace_action_items
Revises: 026_workspace_calendar_events
Create Date: 2026-05-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "027_workspace_action_items"
down_revision = "026_workspace_calendar_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_action_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_kind", sa.String(length=64), nullable=False, server_default="cabinet"),
        sa.Column("target_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("target_label", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("owner_label", sa.String(length=255), nullable=False, server_default="Cabinet"),
        sa.Column("source_kind", sa.String(length=64), nullable=False, server_default="assistant"),
        sa.Column("source_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("calendar_event_id", sa.String(length=36), sa.ForeignKey("workspace_calendar_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("recommended_window", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("scenario_options", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed', 'cancelled')",
            name="ck_workspace_action_items_status",
        ),
        sa.CheckConstraint(
            "priority IN ('critical', 'high', 'medium', 'low')",
            name="ck_workspace_action_items_priority",
        ),
    )
    op.create_index("ix_workspace_action_items_workspace_id", "workspace_action_items", ["workspace_id"])
    op.create_index("ix_workspace_action_items_due_at", "workspace_action_items", ["due_at"])
    op.create_index("ix_workspace_action_items_workspace_status", "workspace_action_items", ["workspace_id", "status"])
    op.create_index("ix_workspace_action_items_workspace_due", "workspace_action_items", ["workspace_id", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_workspace_action_items_workspace_due", table_name="workspace_action_items")
    op.drop_index("ix_workspace_action_items_workspace_status", table_name="workspace_action_items")
    op.drop_index("ix_workspace_action_items_due_at", table_name="workspace_action_items")
    op.drop_index("ix_workspace_action_items_workspace_id", table_name="workspace_action_items")
    op.drop_table("workspace_action_items")
