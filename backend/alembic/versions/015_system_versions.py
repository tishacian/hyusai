"""Custom chain versioning — E3.1 foundation.

Revision ID: 015_system_versions
Revises: 014_sp_workspace_id
Create Date: 2026-04-24

Creates the ``system_versions`` table (rolling window of 500 historical
``System.flow_definition`` snapshots per chain, decision
2026-04-24) and adds ``runs.flow_snapshot`` + ``runs.flow_version_id``
so runs keep an inline copy of the DAG they executed against — even
after their source version has been purged from the window.

Design notes:

- ``system_versions.system_id`` is ``ondelete=CASCADE`` so deleting a
  System takes its history with it. Matches the existing
  ``System.runs`` cascade.
- ``workspace_id`` is denormalized onto the version row (instead of
  joining through ``systems``) so the listing endpoint gates on a
  single indexed column and cross-tenant leaks are structurally
  impossible.
- ``(system_id, version_number)`` is indexed for "versions of system X
  latest first", the only paginated listing pattern on this table.
- ``runs.flow_snapshot`` is a plain JSON column (no FK); ``flow_version_id``
  is a soft reference (no FK) since the version row is legitimately
  allowed to disappear under the rolling window without orphaning the
  run. The snapshot on the run remains the source of truth for replay.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "015_system_versions"
down_revision = "014_sp_workspace_id"
branch_labels = None
depends_on = None


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def _table_exists(bind, table: str) -> bool:
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "system_versions"):
        op.create_table(
            "system_versions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "system_id",
                sa.String(length=36),
                sa.ForeignKey("systems.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "workspace_id",
                sa.String(length=36),
                sa.ForeignKey("workspaces.id"),
                nullable=True,
            ),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("flow_definition", sa.JSON(), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("rolled_back_from_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column(
                "created_by",
                sa.String(length=255),
                nullable=False,
                server_default="demo-user",
            ),
        )
        op.create_index(
            "ix_system_versions_system_id",
            "system_versions",
            ["system_id"],
        )
        op.create_index(
            "ix_system_versions_workspace_id",
            "system_versions",
            ["workspace_id"],
        )
        op.create_index(
            "ix_system_versions_system_version",
            "system_versions",
            ["system_id", "version_number"],
        )

    if not _column_exists(bind, "runs", "flow_snapshot"):
        with op.batch_alter_table("runs") as batch:
            batch.add_column(sa.Column("flow_snapshot", sa.JSON(), nullable=True))

    if not _column_exists(bind, "runs", "flow_version_id"):
        with op.batch_alter_table("runs") as batch:
            batch.add_column(
                sa.Column("flow_version_id", sa.String(length=36), nullable=True)
            )
        op.create_index(
            "ix_runs_flow_version_id",
            "runs",
            ["flow_version_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _column_exists(bind, "runs", "flow_version_id"):
        op.drop_index("ix_runs_flow_version_id", table_name="runs")
        with op.batch_alter_table("runs") as batch:
            batch.drop_column("flow_version_id")

    if _column_exists(bind, "runs", "flow_snapshot"):
        with op.batch_alter_table("runs") as batch:
            batch.drop_column("flow_snapshot")

    if _table_exists(bind, "system_versions"):
        op.drop_index(
            "ix_system_versions_system_version", table_name="system_versions"
        )
        op.drop_index(
            "ix_system_versions_workspace_id", table_name="system_versions"
        )
        op.drop_index("ix_system_versions_system_id", table_name="system_versions")
        op.drop_table("system_versions")
