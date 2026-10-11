"""Evaluation loop — auto-scoring post-run + workspace thresholds (Vague E/E1).

Revision ID: 011_evaluation_loop
Revises: 010_context_ephemeral
Create Date: 2026-04-24

Three additive changes, no data migration required.

1. ``runs.evaluation_scores`` — JSON column that snapshots the scoring
   run produced by the auto-eval hook at ``_finalize_run``. Mirrors the
   shape of ``EvaluationScore.scores`` + composite + hallucination_rate
   + ``threshold_breach: bool`` so the UI can render the Run card
   without a join. Nullable (eval runs off for most systems today).

2. ``evaluation_scores.run_id`` — optional FK into ``runs`` so we can
   trace a score back to the run that produced it and build the review
   queue without persisting duplicate data. Backfilled as NULL; the
   manual ``/evaluation/score`` endpoint still produces rows with
   ``run_id=NULL``.

3. New ``evaluation_presets`` table, mirrors ``rag_presets`` shape
   (scope/scope_id/workspace_id/config JSON/is_default). Holds the
   threshold config (``composite_min``, ``hallucination_max``, etc.)
   so a workspace admin can tune the auto-eval trigger without code.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "011_evaluation_loop"
down_revision = "010_context_ephemeral"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("evaluation_scores", sa.JSON(), nullable=True))

    with op.batch_alter_table("evaluation_scores") as batch:
        batch.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
        batch.create_index(
            "ix_evaluation_scores_run_id",
            ["run_id"],
            unique=False,
        )

    op.create_table(
        "evaluation_presets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "scope IN ('workspace', 'capability', 'system')",
            name="ck_evaluation_presets_scope",
        ),
    )
    op.create_index(
        "ix_evaluation_presets_workspace_id",
        "evaluation_presets",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_presets_scope",
        "evaluation_presets",
        ["scope", "scope_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_presets_scope",
        table_name="evaluation_presets",
    )
    op.drop_index(
        "ix_evaluation_presets_workspace_id",
        table_name="evaluation_presets",
    )
    op.drop_table("evaluation_presets")

    with op.batch_alter_table("evaluation_scores") as batch:
        batch.drop_index("ix_evaluation_scores_run_id")
        batch.drop_column("run_id")

    with op.batch_alter_table("runs") as batch:
        batch.drop_column("evaluation_scores")
