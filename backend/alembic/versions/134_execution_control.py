"""Durable dispatch, resource reservations and native execution control."""

import sqlalchemy as sa

from alembic import op

revision = "134_execution_control"
down_revision = "133_activity_observability"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "runs",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("runs", sa.Column("execution_policy", sa.JSON()))
    for column in (
        sa.Column("execution_policy", sa.JSON()),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("deadline_at", sa.DateTime()),
    ):
        op.add_column("ml_models", column)
    for column in (
        sa.Column("lifecycle_controller", sa.String(20)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("deadline_at", sa.DateTime()),
    ):
        op.add_column("recipe_executions", column)
    op.create_table(
        "execution_capacity",
        sa.Column("scope", sa.String(100), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Integer(), nullable=False),
    )
    op.create_table(
        "execution_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entity_kind", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("lane", sa.String(16), nullable=False),
        sa.Column("cpu_cores", sa.Float(), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("reserved_core_hours", sa.Float(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("released_at", sa.DateTime()),
        sa.Column("allocated_core_hours", sa.Float()),
        sa.Column("cpu_seconds", sa.Float()),
        sa.Column("peak_rss_bytes", sa.Float()),
        sa.Column("outcome", sa.String(32)),
        sa.UniqueConstraint("entity_kind", "entity_id", name="uq_execution_reservation_native"),
        sa.CheckConstraint(
            "cpu_cores > 0 AND memory_mb > 0 AND reserved_core_hours >= 0",
            name="ck_execution_reservation_resources",
        ),
        sa.CheckConstraint("lane IN ('interactive','batch')", name="ck_execution_reservation_lane"),
    )
    op.create_index(
        "ix_execution_reservations_workspace_id", "execution_reservations", ["workspace_id"]
    )
    op.create_index(
        "ix_execution_reservations_active",
        "execution_reservations",
        ["released_at", "workspace_id"],
    )
    op.create_table(
        "execution_dispatches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entity_kind", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("task_name", sa.String(120), nullable=False),
        sa.Column("task_queue", sa.String(120), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False, unique=True),
        sa.Column("dedupe_key", sa.String(255), nullable=False, unique=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime()),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("reconciled_at", sa.DateTime()),
        sa.Column("error_code", sa.String(80)),
        sa.CheckConstraint(
            "state IN ('pending','leased','published','cancelled','dead')",
            name="ck_execution_dispatch_state",
        ),
    )
    op.create_index(
        "ix_execution_dispatches_workspace_id", "execution_dispatches", ["workspace_id"]
    )
    op.create_index(
        "ix_execution_dispatch_due",
        "execution_dispatches",
        ["state", "available_at", "lease_expires_at"],
    )

    op.create_index(
        "ix_execution_dispatch_reconcile", "execution_dispatches", ["task_name", "reconciled_at"]
    )


def downgrade():
    connection = op.get_bind()
    for table in ("execution_dispatches", "execution_reservations"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("134 downgrade refused: execution coordination evidence exists")
    if connection.execute(
        sa.text("SELECT 1 FROM recipe_executions WHERE lifecycle_controller IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError("134 downgrade refused: native lifecycle attempts exist")
    if connection.execute(
        sa.text(
            "SELECT 1 FROM runs WHERE execution_policy IS NOT NULL OR cancel_requested = true LIMIT 1"
        )
    ).first():
        raise RuntimeError("134 downgrade refused: controlled workflows exist")
    if connection.execute(
        sa.text("SELECT 1 FROM ml_models WHERE execution_policy IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError("134 downgrade refused: controlled training exists")
    for table in ("execution_dispatches", "execution_reservations", "execution_capacity"):
        op.drop_table(table)
    for name in (
        "deadline_at",
        "lease_expires_at",
        "lease_generation",
        "lease_token",
        "lifecycle_controller",
    ):
        op.drop_column("recipe_executions", name)
    op.drop_column("runs", "execution_policy")
    op.drop_column("runs", "cancel_requested")
    for name in ("execution_policy", "lease_token", "lease_expires_at", "deadline_at"):
        op.drop_column("ml_models", name)
