"""Checkpoint publication fences and persistent object watches."""

import sqlalchemy as sa

from alembic import op

revision = "132_connector_sync"
down_revision = "131_connector_writes"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "connector_sync_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope_digest", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("checkpoint", sa.JSON()),
        sa.Column(
            "dataset_id", sa.String(36), sa.ForeignKey("tabular_datasets.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "compute_run_id", sa.String(36), sa.ForeignKey("compute_runs.id", ondelete="RESTRICT")
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "scope_digest", name="uq_connector_sync_scope"),
    )
    op.create_index(
        "ix_connector_sync_states_workspace_id", "connector_sync_states", ["workspace_id"]
    )
    op.create_table(
        "connector_watches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("connection_revision", sa.Integer(), nullable=False),
        sa.Column(
            "system_id",
            sa.String(36),
            sa.ForeignKey("systems.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("prefix", sa.String(1024), nullable=False),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64)),
        sa.Column("objects", sa.JSON(), nullable=False),
        sa.Column(
            "pending_run_id", sa.String(36), sa.ForeignKey("compute_runs.id", ondelete="RESTRICT")
        ),
        sa.Column("next_poll_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(160)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_connector_watches_workspace_id", "connector_watches", ["workspace_id"])
    op.create_index("ix_connector_watches_next_poll_at", "connector_watches", ["next_poll_at"])


def downgrade():
    for name in ("connector_sync_states", "connector_watches"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first():
            raise RuntimeError("132 downgrade refused: connector checkpoints/watches exist")
    op.drop_table("connector_watches")
    op.drop_table("connector_sync_states")
