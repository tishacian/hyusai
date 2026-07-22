"""Add opaque Workspace Blueprint identities to Systems and Contexts.

Revision ID: 071_blueprint_object_keys
Revises: 070_app_entitlement_registry

Names are presentation data and may legitimately collide inside a workspace.
Existing rows therefore receive their current object ID as an opaque stable
key, while new rows receive an application-generated key. The composite
uniques close concurrent Blueprint imports without imposing name uniqueness.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "071_blueprint_object_keys"
down_revision = "070_app_entitlement_registry"
branch_labels = None
depends_on = None

KEY_COLUMN = "blueprint_key"
TABLE_CONSTRAINTS = {
    "systems": "uq_systems_workspace_blueprint_key",
    "contexts": "uq_contexts_workspace_blueprint_key",
}


def _backfill_key(table_name: str) -> None:
    table = sa.table(
        table_name,
        sa.column("id", sa.String(length=36)),
        sa.column(KEY_COLUMN, sa.String(length=120)),
    )
    op.get_bind().execute(
        table.update()
        .where(table.c.blueprint_key.is_(None))
        .values(blueprint_key=table.c.id)
    )


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    for table_name, constraint_name in TABLE_CONSTRAINTS.items():
        if table_name not in existing_tables:
            continue
        op.add_column(
            table_name,
            sa.Column(KEY_COLUMN, sa.String(length=120), nullable=True),
        )
        _backfill_key(table_name)
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                KEY_COLUMN,
                existing_type=sa.String(length=120),
                nullable=False,
            )
            batch.create_unique_constraint(
                constraint_name,
                ["workspace_id", KEY_COLUMN],
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    for table_name, constraint_name in reversed(tuple(TABLE_CONSTRAINTS.items())):
        if table_name not in existing_tables:
            continue
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint(constraint_name, type_="unique")
            batch.drop_column(KEY_COLUMN)
