"""Durable connector write intents and exact contract approvals."""

import sqlalchemy as sa

from alembic import op

revision = "131_connector_writes"
down_revision = "130_connector_oauth_states"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "connector_writes",
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
        sa.Column("request_key", sa.String(120), nullable=False),
        sa.Column("connection_revision", sa.Integer(), nullable=False),
        sa.Column("profile_digest", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("target_digest", sa.String(64), nullable=False),
        sa.Column("contract", sa.JSON(), nullable=False),
        sa.Column("contract_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column(
            "compute_run_id",
            sa.String(36),
            sa.ForeignKey("compute_runs.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("receipt", sa.JSON()),
        sa.Column("error_code", sa.String(160)),
        sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint("workspace_id", "request_key", name="uq_connector_write_request"),
        sa.CheckConstraint(
            "state IN ('prepared','approved','sent','applied','failed','unknown','abandoned')",
            name="ck_connector_write_state",
        ),
    )
    for column in ("workspace_id", "connection_id", "target_digest", "state"):
        op.create_index("ix_connector_writes_" + column, "connector_writes", [column])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM connector_writes LIMIT 1")).first():
        raise RuntimeError("131 downgrade refused: connector write receipts exist")
    op.drop_table("connector_writes")
