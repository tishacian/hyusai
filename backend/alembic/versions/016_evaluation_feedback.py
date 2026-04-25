"""Evaluation feedback signal — E1.5.1.

Revision ID: 016_evaluation_feedback
Revises: 015_system_versions
Create Date: 2026-04-25

Until now, when a reviewer Accept/Reject'd a `Decision(kind=review_required)`
filed by the auto-eval loop, the only effect was a status change on the
Decision row. Nothing fed back into the system: no learning signal, no
record of *why* the breach was wrong, no corrected output to anchor a
future fine-tune. The loop was open.

This migration adds ``evaluation_feedback`` — the persistent home of
the human signal. Each row captures:

- ``decision_id`` (nullable): when the feedback originated from a
  triage queue item. Nullable because we may later let users grade an
  answer directly from the chat ("👍 / 👎") and we want the table to
  outlive that decoupling.
- ``run_id`` (always set): the Run being graded. This is the join
  point for per-skill / per-system analytics (E1.5.3) and for re-runs
  with override (E1.5.2).
- ``evaluation_score_id``: the specific score row whose threshold was
  in question, when the feedback came from auto-eval. NULL for manual
  feedback paths.
- ``label``: a closed enum (validated app-side, not DB-enforced for
  forward-compat). Today: ``false_positive``, ``true_breach``,
  ``correct_with_fix``.
- ``notes`` / ``corrected_output``: optional reviewer payload. The
  corrected output is the gold for future supervised tuning.
- ``created_by``: actor handle (Keycloak sub or "demo-user").

Indexes target the three read patterns we already need:

- ``(workspace_id, created_at DESC)`` for the queue history widget.
- ``(run_id)`` for "show me feedback on this run".
- ``(decision_id)`` for "which Decisions already have feedback".
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "016_evaluation_feedback"
down_revision = "015_system_versions"
branch_labels = None
depends_on = None


def _table_exists(bind, table: str) -> bool:
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "evaluation_feedback"):
        op.create_table(
            "evaluation_feedback",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.String(length=36),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column(
                "decision_id",
                sa.String(length=36),
                nullable=True,
            ),
            sa.Column(
                "run_id",
                sa.String(length=36),
                nullable=False,
            ),
            sa.Column(
                "evaluation_score_id",
                sa.String(length=36),
                nullable=True,
            ),
            sa.Column("label", sa.String(length=40), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("corrected_output", sa.JSON(), nullable=True),
            sa.Column(
                "created_by",
                sa.String(length=255),
                nullable=False,
                server_default="demo-user",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_evaluation_feedback_workspace_created",
            "evaluation_feedback",
            ["workspace_id", "created_at"],
        )
        op.create_index(
            "ix_evaluation_feedback_run_id",
            "evaluation_feedback",
            ["run_id"],
        )
        op.create_index(
            "ix_evaluation_feedback_decision_id",
            "evaluation_feedback",
            ["decision_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "evaluation_feedback"):
        op.drop_index("ix_evaluation_feedback_decision_id", table_name="evaluation_feedback")
        op.drop_index("ix_evaluation_feedback_run_id", table_name="evaluation_feedback")
        op.drop_index(
            "ix_evaluation_feedback_workspace_created",
            table_name="evaluation_feedback",
        )
        op.drop_table("evaluation_feedback")
