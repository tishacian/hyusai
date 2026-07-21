"""Add run_schedules + webhook_hooks for orchestration triggers.

Revision ID: 062_run_schedules_webhook_hooks
Revises: 061_subflow_delegation_state
"""
import sqlalchemy as sa

from alembic import op

revision = "062_run_schedules_webhook_hooks"
down_revision = "061_subflow_delegation_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_schedules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default="Schedule"),
        sa.Column("cron_expr", sa.String(length=120), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("input_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("next_fire_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_run_id"], ["runs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_run_schedules_workspace_id", "run_schedules", ["workspace_id"])
    op.create_index("ix_run_schedules_system_id", "run_schedules", ["system_id"])
    op.create_index("ix_run_schedules_next_fire_at", "run_schedules", ["next_fire_at"])
    op.create_index("ix_run_schedules_due", "run_schedules", ["enabled", "next_fire_at"])
    op.create_index(
        "ix_run_schedules_workspace_system",
        "run_schedules",
        ["workspace_id", "system_id"],
    )

    op.create_table(
        "webhook_hooks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default="Webhook"),
        sa.Column("event_type", sa.String(length=120), nullable=False, server_default="webhook.received"),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_webhook_hooks_workspace_id", "webhook_hooks", ["workspace_id"])
    op.create_index("ix_webhook_hooks_system_id", "webhook_hooks", ["system_id"])
    op.create_index(
        "ix_webhook_hooks_workspace_system",
        "webhook_hooks",
        ["workspace_id", "system_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_hooks_workspace_system", table_name="webhook_hooks")
    op.drop_index("ix_webhook_hooks_system_id", table_name="webhook_hooks")
    op.drop_index("ix_webhook_hooks_workspace_id", table_name="webhook_hooks")
    op.drop_table("webhook_hooks")

    op.drop_index("ix_run_schedules_workspace_system", table_name="run_schedules")
    op.drop_index("ix_run_schedules_due", table_name="run_schedules")
    op.drop_index("ix_run_schedules_next_fire_at", table_name="run_schedules")
    op.drop_index("ix_run_schedules_system_id", table_name="run_schedules")
    op.drop_index("ix_run_schedules_workspace_id", table_name="run_schedules")
    op.drop_table("run_schedules")
