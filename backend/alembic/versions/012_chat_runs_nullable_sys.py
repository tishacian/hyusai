"""Chat auto-eval loop — make runs.system_id nullable (Vague E / E1 closure).

Revision ID: 012_chat_runs_nullable_sys
Revises: 011_evaluation_loop
Create Date: 2026-04-25

Why: closing the auto-eval loop on chat required every chat turn to
produce a canonical :class:`~app.models.run.Run` so the existing
``_finalize_run → schedule_eval`` pipeline can score it. Historically a
Run always targeted a specific System (``runs.system_id NOT NULL``),
but chat can legitimately happen outside any System context — e.g.
workspace-wide conversations from the top-level chat screen with no
System picker engaged. Forcing a dummy System for those conversations
would pollute ``/systems`` and distort per-System metrics.

Product decision (see docs/vague-e-plan.md 2026-04-25 journal): a Run
is first-class relative to a Workspace; its System attachment is now
an optional relationship. All downstream code that filtered on
``system_id`` already handles ``NULL`` gracefully (impact.py,
systems.py, auto_eval.py, run_engine/*) — verified via
``rg '\\.system_id' backend/app`` before shipping this migration.

One additive column change, no data migration needed.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "012_chat_runs_nullable_sys"
down_revision = "011_evaluation_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.alter_column(
            "system_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )


def downgrade() -> None:
    # We deliberately don't backfill a fake system_id on downgrade:
    # any chat Run created post-012 will have NULL system_id and
    # cannot be coerced to a real System id after the fact. Operators
    # rolling back must first DELETE chat Runs (trigger='chat' AND
    # system_id IS NULL) or they'll hit an IntegrityError.
    with op.batch_alter_table("runs") as batch:
        batch.alter_column(
            "system_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
