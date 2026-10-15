"""Serving usage aggregates and durable ML alerts (metadata only)."""

import sqlalchemy as sa

from alembic import op

revision = "137_mlops_operations"
down_revision = "136_mlops_correctness"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "ml_inference_usage",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("served_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("caller", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("cpu_seconds", sa.Float(), nullable=True),
        sa.Column("measured_cost_usd", sa.Float(), nullable=True),
        sa.Column("tariff_cost_usd", sa.Float(), nullable=True),
        sa.Column("tariff_evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("rolled_up_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ml_usage_pending", "ml_inference_usage", ["rolled_up_at", "created_at"], unique=False
    )
    op.create_table(
        "ml_usage_rollups",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("served_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("caller", sa.String(length=32), nullable=False),
        sa.Column("interval_start", sa.DateTime(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("latency_histogram", sa.JSON(), nullable=False),
        sa.Column("cpu_seconds", sa.Float(), nullable=False),
        sa.Column("cpu_requests", sa.Integer(), nullable=False),
        sa.Column("measured_cost_usd", sa.Float(), nullable=False),
        sa.Column("measured_rows", sa.Integer(), nullable=False),
        sa.Column("measured_requests", sa.Integer(), nullable=False),
        sa.Column("tariff_cost_usd", sa.Float(), nullable=False),
        sa.Column("tariff_requests", sa.Integer(), nullable=False),
        sa.Column("tariff_rows", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ml_rollups_scope_window",
        "ml_usage_rollups",
        ["workspace_id", "model_id", "interval_start"],
        unique=False,
    )
    op.create_table(
        "ml_alert_channels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("destination_email", sa.String(length=254), nullable=True),
        sa.Column("webhook_url_ref", sa.String(length=255), nullable=True),
        sa.Column("signing_key_ref", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ml_alert_channels_workspace_id"),
        "ml_alert_channels",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "ml_alert_states",
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("badge", sa.String(length=16), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("model_id"),
    )
    op.create_table(
        "ml_alerts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ml_alerts_workspace_created", "ml_alerts", ["workspace_id", "created_at"], unique=False
    )
    op.create_table(
        "ml_alert_deliveries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("alert_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["ml_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["ml_alert_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ml_alert_delivery_due", "ml_alert_deliveries", ["status", "available_at"], unique=False
    )
    op.create_table(
        "ml_alert_sources",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("alert_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["ml_alerts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_ml_alert_sources_source_id", "ml_alert_sources", ["source_id"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM ml_inference_usage LIMIT 1")).first():
        raise RuntimeError("ML_OPERATIONS_DOWNGRADE_NOT_EMPTY")
    if connection.execute(sa.text("SELECT 1 FROM ml_usage_rollups LIMIT 1")).first():
        raise RuntimeError("ML_OPERATIONS_DOWNGRADE_NOT_EMPTY")
    if connection.execute(sa.text("SELECT 1 FROM ml_alert_channels LIMIT 1")).first():
        raise RuntimeError("ML_OPERATIONS_DOWNGRADE_NOT_EMPTY")
    if connection.execute(sa.text("SELECT 1 FROM ml_alert_states LIMIT 1")).first():
        raise RuntimeError("ML_OPERATIONS_DOWNGRADE_NOT_EMPTY")
    if connection.execute(sa.text("SELECT 1 FROM ml_alerts LIMIT 1")).first():
        raise RuntimeError("ML_OPERATIONS_DOWNGRADE_NOT_EMPTY")
    if connection.execute(sa.text("SELECT 1 FROM ml_alert_deliveries LIMIT 1")).first():
        raise RuntimeError("ML_OPERATIONS_DOWNGRADE_NOT_EMPTY")
    if connection.execute(sa.text("SELECT 1 FROM ml_alert_sources LIMIT 1")).first():
        raise RuntimeError("ML_OPERATIONS_DOWNGRADE_NOT_EMPTY")
    op.drop_table("ml_alert_sources")
    op.drop_table("ml_alert_deliveries")
    op.drop_table("ml_alerts")
    op.drop_table("ml_alert_states")
    op.drop_table("ml_alert_channels")
    op.drop_table("ml_usage_rollups")
    op.drop_table("ml_inference_usage")
