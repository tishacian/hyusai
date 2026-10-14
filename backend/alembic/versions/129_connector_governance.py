"""Expiring network exceptions and immutable connector evidence.

Revision ID: 129_connector_governance
Revises: 128_compute_runs
"""

import sqlalchemy as sa

from alembic import op

revision = "129_connector_governance"
down_revision = "128_compute_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "connector_network_exceptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE")
        ),
        sa.Column("cidr", sa.String(64), nullable=False),
        sa.Column("ports", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("revoked_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")),
    )
    op.create_index(
        "ix_connector_network_exceptions_workspace_id",
        "connector_network_exceptions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_connector_network_exceptions_expires_at", "connector_network_exceptions", ["expires_at"]
    )
    op.create_table(
        "connector_evidence",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("profile_key", sa.String(160), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reports", sa.JSON(), nullable=False),
        sa.Column(
            "accepted_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("producer", sa.String(160), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("revoked_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")),
    )
    op.create_index("ix_connector_evidence_profile_key", "connector_evidence", ["profile_key"])
    op.create_index(
        "ix_connector_evidence_identity_digest", "connector_evidence", ["identity_digest"]
    )


def downgrade():
    bind = op.get_bind()
    for table in ("connector_evidence", "connector_network_exceptions"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("129 downgrade refused: connector governance records exist")
    op.drop_table("connector_evidence")
    op.drop_table("connector_network_exceptions")
