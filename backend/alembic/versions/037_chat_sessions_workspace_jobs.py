"""Durable chat sessions and workspace deep retrieval jobs.

Revision ID: 037_chat_sessions_workspace_jobs
Revises: 036_retrieval_worker_job_kinds
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "037_chat_sessions_workspace_jobs"
down_revision = "036_retrieval_worker_job_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("status", sa.String(length=32), nullable=False, server_default="active"))
    op.add_column("sessions", sa.Column("context_signature", sa.String(length=512), nullable=True))
    op.add_column("sessions", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column("sessions", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_check_constraint(
        "ck_sessions_status",
        "sessions",
        "status IN ('active', 'archived', 'deleted')",
    )
    op.create_index("ix_sessions_context_signature", "sessions", ["context_signature"])
    op.create_index("ix_sessions_workspace_user_status", "sessions", ["workspace_id", "user_id", "status"])

    op.add_column("workspace_jobs", sa.Column("session_id", sa.String(length=36), nullable=True))
    op.add_column("workspace_jobs", sa.Column("collection_id", sa.String(length=36), nullable=True))
    op.add_column("workspace_jobs", sa.Column("parent_message_id", sa.String(length=36), nullable=True))
    op.add_column("workspace_jobs", sa.Column("message_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_workspace_jobs_session_id_sessions", "workspace_jobs", "sessions", ["session_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        "fk_workspace_jobs_collection_id_knowledge_collections",
        "workspace_jobs",
        "knowledge_collections",
        ["collection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_workspace_jobs_parent_message_id_messages",
        "workspace_jobs",
        "messages",
        ["parent_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_workspace_jobs_message_id_messages",
        "workspace_jobs",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_workspace_jobs_session_id", "workspace_jobs", ["session_id"])
    op.create_index("ix_workspace_jobs_collection_id", "workspace_jobs", ["collection_id"])
    op.create_index("ix_workspace_jobs_parent_message_id", "workspace_jobs", ["parent_message_id"])
    op.create_index("ix_workspace_jobs_message_id", "workspace_jobs", ["message_id"])
    op.create_index("ix_workspace_jobs_workspace_session_status", "workspace_jobs", ["workspace_id", "session_id", "status"])
    op.create_index("ix_workspace_jobs_workspace_user_status", "workspace_jobs", ["workspace_id", "created_by_user_id", "status"])
    op.create_index("ix_workspace_jobs_workspace_kind_status", "workspace_jobs", ["workspace_id", "kind", "status"])


def downgrade() -> None:
    op.drop_index("ix_workspace_jobs_workspace_kind_status", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_workspace_user_status", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_workspace_session_status", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_message_id", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_parent_message_id", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_collection_id", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_session_id", table_name="workspace_jobs")
    op.drop_constraint("fk_workspace_jobs_message_id_messages", "workspace_jobs", type_="foreignkey")
    op.drop_constraint("fk_workspace_jobs_parent_message_id_messages", "workspace_jobs", type_="foreignkey")
    op.drop_constraint("fk_workspace_jobs_collection_id_knowledge_collections", "workspace_jobs", type_="foreignkey")
    op.drop_constraint("fk_workspace_jobs_session_id_sessions", "workspace_jobs", type_="foreignkey")
    op.drop_column("workspace_jobs", "message_id")
    op.drop_column("workspace_jobs", "parent_message_id")
    op.drop_column("workspace_jobs", "collection_id")
    op.drop_column("workspace_jobs", "session_id")

    op.drop_index("ix_sessions_workspace_user_status", table_name="sessions")
    op.drop_index("ix_sessions_context_signature", table_name="sessions")
    op.drop_constraint("ck_sessions_status", "sessions", type_="check")
    op.drop_column("sessions", "deleted_at")
    op.drop_column("sessions", "archived_at")
    op.drop_column("sessions", "context_signature")
    op.drop_column("sessions", "status")
