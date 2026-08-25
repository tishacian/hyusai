"""Make installed Workspace App manifests authoritative for entitlement keys.

Revision ID: 070_app_entitlement_registry
Revises: 069_workspace_app_lifecycle

The previous CHECK enumerated four Andritz-era surface keys. A Workspace App
manifest may now introduce another canonical key without requiring a schema
change. Application writes still validate against the exact manifests installed
in the target workspace; this database constraint is the format boundary.
No row is created, deleted or rewritten by this migration.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Keep Alembic revision ids within the production alembic_version VARCHAR(32).
revision = "070_app_entitlement_registry"
down_revision = "069_workspace_app_lifecycle"
branch_labels = None
depends_on = None

TABLE = "workspace_member_app_entitlements"
CONSTRAINT = "ck_workspace_member_app_entitlements_app_key"
LEGACY_KEYS = ("chat", "client360-pdr", "knowledge-capture", "fse-reports")


def _enum_check() -> str:
    return f"app_key IN ({', '.join(repr(value) for value in LEGACY_KEYS)})"


def _format_check(dialect: str) -> str:
    # No LIKE wildcard here: this string is embedded into DDL, and psycopg2
    # interpolates '%' in whatever statement it is handed. See the matching note
    # on ``app.models.workspace._app_key_common_check``.
    common = (
        "length(app_key) BETWEEN 1 AND 80 "
        "AND app_key = lower(trim(app_key)) "
        "AND app_key = replace(app_key, ' ', '')"
    )
    if dialect == "postgresql":
        return common + " AND app_key ~ '^[a-z0-9][a-z0-9.-]{0,79}$'"
    if dialect == "sqlite":
        return (
            common
            + " AND app_key NOT GLOB '*[^a-z0-9.-]*'"
            + " AND substr(app_key, 1, 1) GLOB '[a-z0-9]'"
        )
    # The service-level regex and installed-manifest validation remain the
    # authority on other supported dialects; the portable subset still rejects
    # empty, mixed-case, padded and space-containing values.
    return common


def _constraint_exists(bind: sa.engine.Connection) -> bool:
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return False
    return any(
        item.get("name") == CONSTRAINT
        for item in inspector.get_check_constraints(TABLE)
    )


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE not in sa.inspect(bind).get_table_names():
        return
    with op.batch_alter_table(TABLE) as batch:
        if _constraint_exists(bind):
            batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, _format_check(bind.dialect.name))


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE not in sa.inspect(bind).get_table_names():
        return
    table = sa.table(TABLE, sa.column("app_key", sa.String(length=80)))
    unsupported = int(
        bind.execute(
            sa.select(sa.func.count())
            .select_from(table)
            .where(table.c.app_key.notin_(LEGACY_KEYS))
        ).scalar_one()
    )
    if unsupported:
        raise RuntimeError(
            "Refusing to restore the legacy entitlement enum while "
            f"{unsupported} manifest-defined grants exist"
        )
    with op.batch_alter_table(TABLE) as batch:
        if _constraint_exists(bind):
            batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, _enum_check())
