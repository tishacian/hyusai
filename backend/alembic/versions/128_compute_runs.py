"""Durable local compute admission, leases and terminal evidence.

Revision ID: 128_compute_runs
Revises: 127_connector_connections
"""

import sqlalchemy as sa

from alembic import op

revision = "128_compute_runs"
down_revision = "127_connector_connections"
branch_labels = None
depends_on = None


def upgrade():
    # Keep the migration frozen: no application model import here.
    op.create_table(
        "compute_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36)),
        sa.Column(
            "connection_id", sa.String(36), sa.ForeignKey("connections.id", ondelete="RESTRICT")
        ),
        sa.Column("connection_revision", sa.Integer()),
        sa.Column("system_id", sa.String(36)),
        sa.Column("system_version_id", sa.String(36)),
        sa.Column("delegation_id", sa.String(36)),
        sa.Column("run_id", sa.String(36)),
        sa.Column("node_id", sa.String(160)),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "recipe_execution_id",
            sa.String(36),
            sa.ForeignKey("recipe_executions.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("placement", sa.String(24), nullable=False, server_default="local"),
        sa.Column("profile", sa.String(160)),
        sa.Column("fingerprint", sa.String(64)),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON()),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("celery_task_id", sa.String(255)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_started", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outcome_unknown", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cpu_cores", sa.Float(), nullable=False, server_default="1"),
        sa.Column("memory_mb", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("reserved_core_hours", sa.Float(), nullable=False, server_default="0"),
        sa.Column("core_hours", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.CheckConstraint(
            "status IN ('queued','admitted','launching','running','committing','succeeded','failed','cancelled','timed_out','lost')",
            name="ck_compute_runs_status",
        ),
        sa.CheckConstraint(
            "cpu_cores > 0 AND memory_mb > 0 AND reserved_core_hours >= 0 AND core_hours >= 0 AND cost_usd >= 0",
            name="ck_compute_runs_resources",
        ),
        sa.CheckConstraint("placement = 'local'", name="ck_compute_runs_local"),
    )
    for name in (
        "workspace_id",
        "connection_id",
        "run_id",
        "status",
        "lease_expires_at",
        "deadline_at",
    ):
        op.create_index(f"ix_compute_runs_{name}", "compute_runs", [name])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM compute_runs LIMIT 1")).first():
        raise RuntimeError("COMPUTE_RUNS_DOWNGRADE_REQUIRES_EMPTY_REGISTRY")
    op.drop_table("compute_runs")
