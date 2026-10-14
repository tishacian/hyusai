"""Connection registry and personal authorization scopes (no legacy credential reads).

Revision ID: 127_connector_connections
Revises: 126_service_contracts
"""

import sqlalchemy as sa

from alembic import op

revision = "127_connector_connections"
down_revision = "126_service_contracts"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("secrets") as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_secrets_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_index("ix_secrets_user_id", ["user_id"])
        batch.drop_constraint("ck_secrets_scope", type_="check")
        batch.create_check_constraint(
            "ck_secrets_scope", "scope IN ('platform','workspace','system','user')"
        )
        batch.create_check_constraint(
            "ck_secrets_user_owner",
            "(scope = 'user' AND user_id IS NOT NULL AND workspace_id IS NOT NULL AND system_id IS NULL) OR (scope != 'user' AND user_id IS NULL)",
        )
    op.create_table(
        "connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("profile_key", sa.String(80), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("secret_refs", sa.JSON(), nullable=False),
        sa.Column("access", sa.String(16), nullable=False),
        sa.Column("allowed_schemas", sa.JSON(), nullable=False),
        sa.Column("allowed_tables", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("legacy_source", sa.String(120), nullable=True),
        sa.Column("last_test", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("workspace_id", "name", name="uq_connections_workspace_name"),
        sa.UniqueConstraint("workspace_id", "legacy_source", name="uq_connections_legacy_source"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_connections_tenant_id"),
        sa.CheckConstraint("access IN ('read','read_write')", name="ck_connections_access"),
        sa.CheckConstraint("revision > 0 AND profile_version > 0", name="ck_connections_revision"),
    )
    op.create_index("ix_connections_workspace_id", "connections", ["workspace_id"])
    op.create_table(
        "connector_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("token_refs", sa.JSON(), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_connector_grants_tenant_id"),
        sa.UniqueConstraint(
            "connection_id", "owner_user_id", name="uq_connector_grants_connection_user"
        ),
    )
    op.create_index("ix_connector_grants_workspace_id", "connector_grants", ["workspace_id"])
    op.create_index("ix_connector_grants_owner_user_id", "connector_grants", ["owner_user_id"])
    op.create_table(
        "connector_delegations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("grant_id", sa.String(36), nullable=False),
        sa.Column(
            "system_id",
            sa.String(36),
            sa.ForeignKey("systems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "system_version_id",
            sa.String(36),
            sa.ForeignKey("system_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("approved_by", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "grant_id"],
            ["connector_grants.workspace_id", "connector_grants.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "grant_id", "system_version_id", name="uq_connector_delegations_version"
        ),
    )
    op.create_index(
        "ix_connector_delegations_workspace_id", "connector_delegations", ["workspace_id"]
    )


def downgrade():
    bind = op.get_bind()
    for table in ("connections", "connector_grants", "connector_delegations"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Downgrade refused: connection governance records exist")
    if bind.execute(sa.text("SELECT 1 FROM secrets WHERE scope = 'user' LIMIT 1")).first():
        raise RuntimeError("Downgrade refused: personal secrets exist")
    op.drop_table("connector_delegations")
    op.drop_table("connector_grants")
    op.drop_table("connections")
    with op.batch_alter_table("secrets") as batch:
        batch.drop_constraint("ck_secrets_user_owner", type_="check")
        batch.drop_constraint("ck_secrets_scope", type_="check")
        batch.create_check_constraint(
            "ck_secrets_scope", "scope IN ('platform','workspace','system')"
        )
        batch.drop_index("ix_secrets_user_id")
        batch.drop_constraint("fk_secrets_user_id", type_="foreignkey")
        batch.drop_column("user_id")
