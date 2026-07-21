"""Add gate TTL on decisions + run_inbox + system_memory.

Revision ID: 063_gate_ttl_inbox_memory
Revises: 062_run_schedules_webhook_hooks

The revision id must stay under alembic_version's varchar(32).
"""
import sqlalchemy as sa

from alembic import op

revision = "063_gate_ttl_inbox_memory"
down_revision = "062_run_schedules_webhook_hooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("decisions", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column(
        "decisions",
        sa.Column("expiry_action", sa.String(length=20), nullable=True),
    )
    op.create_index("ix_decisions_expires_at", "decisions", ["expires_at"])
    op.create_index(
        "ix_decisions_gate_ttl",
        "decisions",
        ["status", "expires_at"],
    )

    op.create_table(
        "run_inbox",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("system_id", sa.String(length=36), nullable=True),
        sa.Column("event_kind", sa.String(length=120), nullable=False, server_default="event"),
        sa.Column("correlation_key", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_run_inbox_run_id", "run_inbox", ["run_id"])
    op.create_index("ix_run_inbox_system_id", "run_inbox", ["system_id"])
    op.create_index("ix_run_inbox_correlation_key", "run_inbox", ["correlation_key"])
    op.create_index(
        "ix_run_inbox_system_correlation",
        "run_inbox",
        ["system_id", "correlation_key"],
    )

    op.create_table(
        "system_memory",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("correlation_key", sa.String(length=255), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "workspace_id",
            "system_id",
            "correlation_key",
            name="uq_system_memory_ws_system_corr",
        ),
    )
    op.create_index("ix_system_memory_workspace_id", "system_memory", ["workspace_id"])
    op.create_index("ix_system_memory_system_id", "system_memory", ["system_id"])
    op.create_index(
        "ix_system_memory_lookup",
        "system_memory",
        ["workspace_id", "system_id", "correlation_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_system_memory_lookup", table_name="system_memory")
    op.drop_index("ix_system_memory_system_id", table_name="system_memory")
    op.drop_index("ix_system_memory_workspace_id", table_name="system_memory")
    op.drop_table("system_memory")

    op.drop_index("ix_run_inbox_system_correlation", table_name="run_inbox")
    op.drop_index("ix_run_inbox_correlation_key", table_name="run_inbox")
    op.drop_index("ix_run_inbox_system_id", table_name="run_inbox")
    op.drop_index("ix_run_inbox_run_id", table_name="run_inbox")
    op.drop_table("run_inbox")

    op.drop_index("ix_decisions_gate_ttl", table_name="decisions")
    op.drop_index("ix_decisions_expires_at", table_name="decisions")
    op.drop_column("decisions", "expiry_action")
    op.drop_column("decisions", "expires_at")
