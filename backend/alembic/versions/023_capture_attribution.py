"""Capture and run attribution.

Revision ID: 023_capture_attribution
Revises: 022_workspace_iam_foundations
Create Date: 2026-05-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "023_capture_attribution"
down_revision = "022_workspace_iam_foundations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "expert_capture_sessions",
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index(
        "ix_expert_capture_sessions_created_by_user_id",
        "expert_capture_sessions",
        ["created_by_user_id"],
    )

    op.add_column(
        "knowledge_update_proposals",
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "knowledge_update_proposals",
        sa.Column("reviewer_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index(
        "ix_knowledge_update_proposals_created_by_user_id",
        "knowledge_update_proposals",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_knowledge_update_proposals_reviewer_user_id",
        "knowledge_update_proposals",
        ["reviewer_user_id"],
    )

    op.add_column(
        "runs",
        sa.Column("initiated_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_runs_initiated_by_user_id", "runs", ["initiated_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_initiated_by_user_id", table_name="runs")
    op.drop_column("runs", "initiated_by_user_id")
    op.drop_index("ix_knowledge_update_proposals_reviewer_user_id", table_name="knowledge_update_proposals")
    op.drop_index("ix_knowledge_update_proposals_created_by_user_id", table_name="knowledge_update_proposals")
    op.drop_column("knowledge_update_proposals", "reviewer_user_id")
    op.drop_column("knowledge_update_proposals", "created_by_user_id")
    op.drop_index("ix_expert_capture_sessions_created_by_user_id", table_name="expert_capture_sessions")
    op.drop_column("expert_capture_sessions", "created_by_user_id")
