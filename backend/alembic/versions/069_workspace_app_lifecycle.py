"""Add content-addressed Workspace App installation lifecycle records.

Revision ID: 069_workspace_app_lifecycle
Revises: 068_value_loop_core

The migration is additive and performs no application or entitlement backfill.
Existing workspace settings therefore retain their exact legacy semantics until
an explicit, separately reviewed lifecycle backfill is applied.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "069_workspace_app_lifecycle"
down_revision = "068_value_loop_core"
branch_labels = None
depends_on = None


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "workspace_app_installations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=True),
        sa.Column("manifest_digest", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            _enum_check("state", ("installed", "uninstalled")),
            name="ck_workspace_app_installations_state",
        ),
        sa.CheckConstraint(
            "(state = 'installed' AND version IS NOT NULL "
            "AND manifest_digest IS NOT NULL) OR "
            "(state = 'uninstalled' AND version IS NULL "
            "AND manifest_digest IS NULL)",
            name="ck_workspace_app_installations_materialized_state",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_workspace_app_installations_revision",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "app_id",
            name="uq_workspace_app_installations_workspace_app",
        ),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            name="uq_workspace_app_installations_id_workspace",
        ),
    )
    for column in ("workspace_id", "app_id", "state"):
        op.create_index(
            f"ix_workspace_app_installations_{column}",
            "workspace_app_installations",
            [column],
            unique=False,
        )

    op.create_table(
        "workspace_app_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=24), nullable=False),
        sa.Column("from_version", sa.String(length=40), nullable=True),
        sa.Column("to_version", sa.String(length=40), nullable=True),
        sa.Column("manifest_digest", sa.String(length=64), nullable=False),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check("operation", ("install", "upgrade", "rollback", "uninstall")),
            name="ck_workspace_app_operations_operation",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["installation_id", "workspace_id"],
            ["workspace_app_installations.id", "workspace_app_installations.workspace_id"],
            name="fk_workspace_app_operations_installation_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_workspace_app_operations_workspace_key",
        ),
    )
    for column in ("workspace_id", "installation_id", "app_id", "operation", "created_at"):
        op.create_index(
            f"ix_workspace_app_operations_{column}",
            "workspace_app_operations",
            [column],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    operations = sa.Table("workspace_app_operations", metadata, autoload_with=bind)
    installations = sa.Table("workspace_app_installations", metadata, autoload_with=bind)
    operation_count = int(
        bind.execute(sa.select(sa.func.count()).select_from(operations)).scalar_one()
    )
    installation_count = int(
        bind.execute(sa.select(sa.func.count()).select_from(installations)).scalar_one()
    )
    if operation_count or installation_count:
        raise RuntimeError(
            "Refusing to downgrade Workspace App lifecycle tables containing "
            f"{installation_count} installations and {operation_count} operation receipts"
        )
    op.drop_table("workspace_app_operations")
    op.drop_table("workspace_app_installations")
