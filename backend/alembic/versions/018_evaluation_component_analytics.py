"""Evaluation component analytics — E1.5.3.

Revision ID: 018_eval_component_analytics
Revises: 017_run_replay_lineage
Create Date: 2026-04-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "018_eval_component_analytics"
down_revision = "017_run_replay_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation_scores") as batch:
        batch.add_column(sa.Column("question_type", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("failed_components", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("topic", sa.String(length=200), nullable=True))
        batch.create_index(
            "ix_evaluation_scores_workspace_question_type",
            ["workspace_id", "question_type"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("evaluation_scores") as batch:
        batch.drop_index("ix_evaluation_scores_workspace_question_type")
        batch.drop_column("topic")
        batch.drop_column("failed_components")
        batch.drop_column("question_type")
