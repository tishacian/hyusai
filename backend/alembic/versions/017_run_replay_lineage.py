"""Run replay lineage — E1.5.2.

Revision ID: 017_run_replay_lineage
Revises: 016_evaluation_feedback
Create Date: 2026-04-25

Adds two columns to ``runs`` to support the "Re-run with override"
flow from the review queue:

- ``parent_run_id`` (nullable, indexed): the run this one was replayed
  from. ``NULL`` for the original chat/system runs (the vast majority).
  Indexed because the canonical UI query is "show me all replays of
  run X" — listing children for a parent.
- ``replay_overrides`` (JSON, nullable): the dict of fields the
  reviewer overrode at replay time (`query`, `rag_pipeline_mode`,
  `model`, …). Captured separately from ``input_ref`` so the audit
  can answer "what did the operator change" without diff'ing two JSON
  blobs. ``NULL`` for non-replay runs.

No FK on ``parent_run_id`` — runs can legitimately be hard-deleted
(GDPR purge, workspace teardown) and we'd rather have orphan replays
than cascade-cascade everything. The query side handles missing
parents gracefully.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "017_run_replay_lineage"
down_revision = "016_evaluation_feedback"
branch_labels = None
depends_on = None


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    if not _column_exists(bind, "runs", "parent_run_id"):
        with op.batch_alter_table("runs") as batch:
            batch.add_column(sa.Column("parent_run_id", sa.String(length=36), nullable=True))
        op.create_index(
            "ix_runs_parent_run_id",
            "runs",
            ["parent_run_id"],
        )

    if not _column_exists(bind, "runs", "replay_overrides"):
        with op.batch_alter_table("runs") as batch:
            batch.add_column(sa.Column("replay_overrides", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _column_exists(bind, "runs", "replay_overrides"):
        with op.batch_alter_table("runs") as batch:
            batch.drop_column("replay_overrides")
    if _column_exists(bind, "runs", "parent_run_id"):
        op.drop_index("ix_runs_parent_run_id", table_name="runs")
        with op.batch_alter_table("runs") as batch:
            batch.drop_column("parent_run_id")
