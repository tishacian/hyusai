"""Expert knowledge capture sessions.

Revision ID: 021_expert_capture
Revises: 020_canonical_answers
Create Date: 2026-04-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "021_expert_capture"
down_revision = "020_canonical_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expert_capture_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("capability_id", sa.String(length=36), nullable=True),
        sa.Column("context_id", sa.String(length=36), nullable=True),
        sa.Column("system_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False, server_default="Expert capture session"),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("expert_profile", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("voice_runtime", sa.String(length=80), nullable=False, server_default="cascade"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="planned"),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("knowledge_gaps", sa.JSON(), nullable=True),
        sa.Column("transcript", sa.JSON(), nullable=True),
        sa.Column("evaluations", sa.JSON(), nullable=True),
        sa.Column("captured_facts", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_expert_capture_sessions_workspace_id", "expert_capture_sessions", ["workspace_id"])
    op.create_index("ix_expert_capture_sessions_status", "expert_capture_sessions", ["status"])
    op.create_index("ix_expert_capture_sessions_context_id", "expert_capture_sessions", ["context_id"])
    op.create_index("ix_expert_capture_sessions_system_id", "expert_capture_sessions", ["system_id"])
    op.create_index("ix_expert_capture_sessions_capability_id", "expert_capture_sessions", ["capability_id"])
    op.create_index("ix_expert_capture_sessions_run_id", "expert_capture_sessions", ["run_id"])

    op.create_table(
        "expert_capture_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column(
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("expert_capture_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_event_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("speaker", sa.String(length=40), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("question_id", sa.String(length=80), nullable=True),
        sa.Column("audio_ref", sa.Text(), nullable=True),
        sa.Column("text_raw", sa.Text(), nullable=True),
        sa.Column("text_amended", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=40), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="capture_engine"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="accepted"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_expert_capture_events_workspace_id", "expert_capture_events", ["workspace_id"])
    op.create_index("ix_expert_capture_events_session_id", "expert_capture_events", ["session_id"])
    op.create_index("ix_expert_capture_events_parent_event_id", "expert_capture_events", ["parent_event_id"])
    op.create_index("ix_expert_capture_events_event_type", "expert_capture_events", ["event_type"])
    op.create_index("ix_expert_capture_events_speaker", "expert_capture_events", ["speaker"])
    op.create_index("ix_expert_capture_events_question_id", "expert_capture_events", ["question_id"])
    op.create_index("ix_expert_capture_events_source", "expert_capture_events", ["source"])
    op.create_index("ix_expert_capture_events_status", "expert_capture_events", ["status"])

    op.create_table(
        "knowledge_update_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column(
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("expert_capture_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending_review"),
        sa.Column("proposal", sa.JSON(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_knowledge_update_proposals_workspace_id", "knowledge_update_proposals", ["workspace_id"])
    op.create_index("ix_knowledge_update_proposals_session_id", "knowledge_update_proposals", ["session_id"])
    op.create_index("ix_knowledge_update_proposals_status", "knowledge_update_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_update_proposals_status", table_name="knowledge_update_proposals")
    op.drop_index("ix_knowledge_update_proposals_session_id", table_name="knowledge_update_proposals")
    op.drop_index("ix_knowledge_update_proposals_workspace_id", table_name="knowledge_update_proposals")
    op.drop_table("knowledge_update_proposals")
    op.drop_index("ix_expert_capture_events_status", table_name="expert_capture_events")
    op.drop_index("ix_expert_capture_events_source", table_name="expert_capture_events")
    op.drop_index("ix_expert_capture_events_question_id", table_name="expert_capture_events")
    op.drop_index("ix_expert_capture_events_speaker", table_name="expert_capture_events")
    op.drop_index("ix_expert_capture_events_event_type", table_name="expert_capture_events")
    op.drop_index("ix_expert_capture_events_parent_event_id", table_name="expert_capture_events")
    op.drop_index("ix_expert_capture_events_session_id", table_name="expert_capture_events")
    op.drop_index("ix_expert_capture_events_workspace_id", table_name="expert_capture_events")
    op.drop_table("expert_capture_events")
    op.drop_index("ix_expert_capture_sessions_run_id", table_name="expert_capture_sessions")
    op.drop_index("ix_expert_capture_sessions_capability_id", table_name="expert_capture_sessions")
    op.drop_index("ix_expert_capture_sessions_system_id", table_name="expert_capture_sessions")
    op.drop_index("ix_expert_capture_sessions_context_id", table_name="expert_capture_sessions")
    op.drop_index("ix_expert_capture_sessions_status", table_name="expert_capture_sessions")
    op.drop_index("ix_expert_capture_sessions_workspace_id", table_name="expert_capture_sessions")
    op.drop_table("expert_capture_sessions")
