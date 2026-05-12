"""Workspace calendar events.

Revision ID: 026_workspace_calendar_events
Revises: 025_kc_worker_jobs
Create Date: 2026-05-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "026_workspace_calendar_events"
down_revision = "025_kc_worker_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_calendar_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Africa/Abidjan"),
        sa.Column("location", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("participants", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="ministerial"),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="scheduled"),
        sa.Column("source_kind", sa.String(length=64), nullable=False, server_default="internal_shared"),
        sa.Column("source_label", sa.String(length=255), nullable=False, server_default="Agenda institutionnel"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('scheduled', 'tentative', 'completed', 'cancelled')",
            name="ck_workspace_calendar_events_status",
        ),
        sa.CheckConstraint(
            "priority IN ('critical', 'high', 'medium', 'low')",
            name="ck_workspace_calendar_events_priority",
        ),
    )
    op.create_index("ix_workspace_calendar_events_workspace_id", "workspace_calendar_events", ["workspace_id"])
    op.create_index("ix_workspace_calendar_events_start_at", "workspace_calendar_events", ["start_at"])
    op.create_index("ix_workspace_calendar_events_end_at", "workspace_calendar_events", ["end_at"])
    op.create_index("ix_workspace_calendar_events_workspace_start", "workspace_calendar_events", ["workspace_id", "start_at"])
    op.create_index("ix_workspace_calendar_events_workspace_status", "workspace_calendar_events", ["workspace_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_workspace_calendar_events_workspace_status", table_name="workspace_calendar_events")
    op.drop_index("ix_workspace_calendar_events_workspace_start", table_name="workspace_calendar_events")
    op.drop_index("ix_workspace_calendar_events_end_at", table_name="workspace_calendar_events")
    op.drop_index("ix_workspace_calendar_events_start_at", table_name="workspace_calendar_events")
    op.drop_index("ix_workspace_calendar_events_workspace_id", table_name="workspace_calendar_events")
    op.drop_table("workspace_calendar_events")
