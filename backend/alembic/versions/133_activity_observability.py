"""Add non-authoritative activity projections, ordered events and durable controls."""

import sqlalchemy as sa

from alembic import op

revision = "133_activity_observability"
down_revision = "132_connector_sync"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "activity_workspace_cursors",
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "activities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("native_id", sa.String(36), nullable=False),
        sa.Column("system_id", sa.String(36)),
        sa.Column("run_id", sa.String(36)),
        sa.Column("owner_id", sa.String(36)),
        sa.Column("parent_activity_id", sa.String(36)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("native_status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kind", "native_id", name="uq_activity_native"),
    )
    op.create_index("ix_activities_workspace_status", "activities", ["workspace_id", "status"])
    op.create_index("ix_activities_workspace_system", "activities", ["workspace_id", "system_id"])
    op.create_index(
        "ix_activities_workspace_created", "activities", ["workspace_id", "created_at", "id"]
    )
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "activity_id",
            sa.String(36),
            sa.ForeignKey("activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "sequence", name="uq_activity_event_sequence"),
        sa.UniqueConstraint("activity_id", "version", name="uq_activity_event_version"),
    )
    op.create_index(
        "ix_activity_events_activity_sequence", "activity_events", ["activity_id", "sequence"]
    )
    op.create_table(
        "activity_commands",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "activity_id",
            sa.String(36),
            sa.ForeignKey("activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.UniqueConstraint(
            "workspace_id", "actor_id", "idempotency_key", name="uq_activity_command_idempotency"
        ),
    )
    op.create_index("ix_activity_commands_dispatch", "activity_commands", ["status", "created_at"])


def downgrade():
    bind = op.get_bind()
    for table in ("activity_commands", "activity_events", "activities"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot discard activity audit records during downgrade")
    for table in (
        "activity_commands",
        "activity_events",
        "activities",
        "activity_workspace_cursors",
    ):
        op.drop_table(table)
