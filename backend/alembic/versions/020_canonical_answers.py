"""Canonical answers and active suggestions — E1.5.5.

Revision ID: 020_canonical_answers
Revises: 019_eval_default_onboard
Create Date: 2026-04-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "020_canonical_answers"
down_revision = "019_eval_default_onboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_answers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.String(length=2000), nullable=False),
        sa.Column("source_decision_id", sa.String(length=36), nullable=True),
        sa.Column("source_feedback_id", sa.String(length=36), nullable=True),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("similarity_threshold", sa.Float(), nullable=False, server_default="0.9"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=255), nullable=False, server_default="demo-user"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_canonical_answers_workspace_id",
        "canonical_answers",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_answers_workspace_norm",
        "canonical_answers",
        ["workspace_id", "normalized_question"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_answers_workspace_norm", table_name="canonical_answers")
    op.drop_index("ix_canonical_answers_workspace_id", table_name="canonical_answers")
    op.drop_table("canonical_answers")
