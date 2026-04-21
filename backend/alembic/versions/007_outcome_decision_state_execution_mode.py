"""Canonical Outcome + Decision state machine + execution_mode first-class.

Revision ID: 007_outcome_decision_state_execution_mode
Revises: 006_adaptive_policy_scope
Create Date: 2026-04-21

Wave 1 of the realignment plan:

1. runs.value_source + operator_value_note — so every Run records whether
   its business value was auto-derived from the Capability ROI model or
   declared by an operator (hybrid strategy).
2. decisions: canonicalise the state machine. Rename legacy `status='open'`
   to `status='proposed'`, add applied_at / applied_patch / applied_by for
   enactment traceability.
3. systems.execution_profile (JSON) — carries the SLA profile, durability
   flags and pricing profile attached to the execution mode. The existing
   `execution_mode` column is re-valued from `real_time` → `real_time_decision`
   to match the canonical taxonomy (mental model §20).
"""
from alembic import op
import sqlalchemy as sa


revision = "007_outcome_decision_state_execution_mode"
down_revision = "006_adaptive_policy_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(
            sa.Column(
                "value_source",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'unset'"),
            )
        )
        batch.add_column(sa.Column("operator_value_note", sa.Text(), nullable=True))

    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("applied_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("applied_patch", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("applied_by", sa.String(length=255), nullable=True))

    op.execute("UPDATE decisions SET status = 'proposed' WHERE status = 'open'")

    with op.batch_alter_table("systems") as batch:
        batch.add_column(sa.Column("execution_profile", sa.JSON(), nullable=True))

    op.execute(
        "UPDATE systems SET execution_mode = 'real_time_decision' "
        "WHERE execution_mode IS NULL OR execution_mode = 'real_time'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE systems SET execution_mode = 'real_time' "
        "WHERE execution_mode = 'real_time_decision'"
    )
    with op.batch_alter_table("systems") as batch:
        batch.drop_column("execution_profile")

    op.execute("UPDATE decisions SET status = 'open' WHERE status = 'proposed'")

    with op.batch_alter_table("decisions") as batch:
        batch.drop_column("applied_by")
        batch.drop_column("applied_patch")
        batch.drop_column("applied_at")

    with op.batch_alter_table("runs") as batch:
        batch.drop_column("operator_value_note")
        batch.drop_column("value_source")
