"""Workspace macro indicators cache + meeting decisions log.

Revision ID: 033_macro_indicators_meeting_decisions
Revises: 032_document_intelligence
Create Date: 2026-05-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "033_macro_indicators_meeting_decisions"
down_revision = "032_document_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_macro_indicators",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("indicator_key", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="world_bank"),
        sa.Column("label", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("unit", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("series", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("current", sa.JSON(), nullable=True),
        sa.Column("trend", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="cached"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_workspace_macro_indicators_workspace_id",
        "workspace_macro_indicators",
        ["workspace_id"],
    )
    op.create_index(
        "ux_workspace_macro_indicator_key",
        "workspace_macro_indicators",
        ["workspace_id", "indicator_key"],
        unique=True,
    )

    op.create_table(
        "meeting_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("calendar_event_id", sa.String(length=36), nullable=False),
        sa.Column("agenda_item_ref", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_by_label", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("options_offered", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("chosen_option", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="logged"),
        sa.Column("audit_log_ref", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_meeting_decisions_workspace_id",
        "meeting_decisions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_meeting_decisions_calendar_event_id",
        "meeting_decisions",
        ["calendar_event_id"],
    )
    op.create_index(
        "ix_meeting_decisions_workspace_event",
        "meeting_decisions",
        ["workspace_id", "calendar_event_id"],
    )
    op.create_index(
        "ix_meeting_decisions_workspace_decided_at",
        "meeting_decisions",
        ["workspace_id", "decided_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_meeting_decisions_workspace_decided_at", table_name="meeting_decisions")
    op.drop_index("ix_meeting_decisions_workspace_event", table_name="meeting_decisions")
    op.drop_index("ix_meeting_decisions_calendar_event_id", table_name="meeting_decisions")
    op.drop_index("ix_meeting_decisions_workspace_id", table_name="meeting_decisions")
    op.drop_table("meeting_decisions")

    op.drop_index("ux_workspace_macro_indicator_key", table_name="workspace_macro_indicators")
    op.drop_index("ix_workspace_macro_indicators_workspace_id", table_name="workspace_macro_indicators")
    op.drop_table("workspace_macro_indicators")
