"""Generic secret registry: secrets and their immutable versions.

Revision ID: 124_secret_registry
Revises: 123_huggingface_connector
"""

import sqlalchemy as sa

from alembic import op

revision = "124_secret_registry"
down_revision = "123_huggingface_connector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "system_id",
            sa.String(length=36),
            sa.ForeignKey("systems.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("owner_key", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("backend", sa.String(length=16), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("scope", "owner_key", "name", name="uq_secrets_scope_owner_name"),
        sa.CheckConstraint("scope IN ('platform','workspace','system')", name="ck_secrets_scope"),
        sa.CheckConstraint(
            "kind IN ('api_key','token','password','oauth_client','generic')",
            name="ck_secrets_kind",
        ),
        sa.CheckConstraint("backend IN ('db','openbao')", name="ck_secrets_backend"),
    )
    op.create_index("ix_secrets_workspace_id", "secrets", ["workspace_id"])
    op.create_index("ix_secrets_system_id", "secrets", ["system_id"])
    op.create_table(
        "secret_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "secret_id",
            sa.String(length=36),
            sa.ForeignKey("secrets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=True),
        sa.Column("backend_ref", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("destroyed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("secret_id", "version", name="uq_secret_versions_secret_ver"),
    )
    op.create_index("ix_secret_versions_secret_id", "secret_versions", ["secret_id"])


def downgrade() -> None:
    op.drop_index("ix_secret_versions_secret_id", table_name="secret_versions")
    op.drop_table("secret_versions")
    op.drop_index("ix_secrets_system_id", table_name="secrets")
    op.drop_index("ix_secrets_workspace_id", table_name="secrets")
    op.drop_table("secrets")
