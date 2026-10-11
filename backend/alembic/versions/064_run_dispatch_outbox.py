"""Add the durable Run dispatch outbox and indexed delegation deadline.

Revision ID: 064_run_dispatch_outbox
Revises: 063_gate_ttl_inbox_memory
"""
import sqlalchemy as sa

from alembic import op


revision = "064_run_dispatch_outbox"
down_revision = "063_gate_ttl_inbox_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("delegation_deadline_at", sa.DateTime(), nullable=True))
    op.add_column(
        "runs",
        sa.Column("delegation_quarantined_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_runs_delegation_deadline_at",
        "runs",
        ["delegation_deadline_at"],
    )
    op.create_index(
        "ix_runs_delegation_quarantined_at",
        "runs",
        ["delegation_quarantined_at"],
    )
    op.create_table(
        "run_dispatch_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("decision_id", sa.String(length=36), nullable=True),
        sa.Column("wave_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('subflow_run', 'subflow_parent_resume', "
            "'subflow_hitl_resume', 'run_hitl_resume')",
            name="ck_run_dispatch_outbox_event_type",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'leased', 'published', 'cancelled', 'dead')",
            name="ck_run_dispatch_outbox_state",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_run_dispatch_outbox_attempts"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_run_dispatch_outbox_dedupe_key"),
        sa.UniqueConstraint("task_id", name="uq_run_dispatch_outbox_task_id"),
    )
    op.create_index(
        "ix_run_dispatch_outbox_due",
        "run_dispatch_outbox",
        ["state", "available_at", "lease_expires_at"],
    )
    op.create_index(
        "ix_run_dispatch_outbox_workspace_state",
        "run_dispatch_outbox",
        ["workspace_id", "state"],
    )
    op.create_index(
        "ix_run_dispatch_outbox_run_event",
        "run_dispatch_outbox",
        ["run_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_dispatch_outbox_run_event", table_name="run_dispatch_outbox")
    op.drop_index("ix_run_dispatch_outbox_workspace_state", table_name="run_dispatch_outbox")
    op.drop_index("ix_run_dispatch_outbox_due", table_name="run_dispatch_outbox")
    op.drop_table("run_dispatch_outbox")
    op.drop_index("ix_runs_delegation_quarantined_at", table_name="runs")
    op.drop_index("ix_runs_delegation_deadline_at", table_name="runs")
    op.drop_column("runs", "delegation_quarantined_at")
    op.drop_column("runs", "delegation_deadline_at")
