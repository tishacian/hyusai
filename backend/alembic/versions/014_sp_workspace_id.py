"""Add workspace_id to sharepoint_sync_jobs — latent drift catch-up.

Revision ID: 014_sp_workspace_id
Revises: 013_sp_ingest_columns
Create Date: 2026-04-24

Background: ``SharePointSyncJob.workspace_id`` was added to the SQL
model in commit ``df4cf80`` (2026-04-20 / Vague E E4b foundation —
"Scoping par workspace") but no Alembic migration was generated at
the time. Existing environments whose ``sharepoint_sync_jobs`` table
was initially created by ``create_all`` (pre-alembic for this table)
still lack the column; trying to enqueue a sync there fails with
``UndefinedColumn: workspace_id`` inside the INSERT.

Caught during E4.1 smoke on the VM (2026-04-24). Fix:
- Add the column as nullable String(36) with the matching FK + index.
- No data migration: pre-existing rows (if any) stay with
  ``workspace_id IS NULL``. They're invisible to workspace-scoped
  listing endpoints, which is the safe default for orphaned rows.
- Keep the column nullable permanently to match the model declaration
  (``ForeignKey("workspaces.id"), nullable=True, index=True``).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "014_sp_workspace_id"
down_revision = "013_sp_ingest_columns"
branch_labels = None
depends_on = None


# The FK has to be named explicitly. On PostgreSQL ``batch_alter_table``
# passes straight through to ``ALTER TABLE ... ADD COLUMN`` and the server
# names the constraint itself, which is why this shipped and ran fine on
# the VM. SQLite has no such ALTER, so batch mode copies the table into a
# new one and replays its constraints — and an unnamed FK there fails with
# ``ValueError: Constraint must have a name``. Naming it makes the same
# revision runnable on both backends; it does not change the shape of the
# relationship the model declares.
FK_NAME = "fk_sharepoint_sync_jobs_workspace_id"


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _column_exists(bind, "sharepoint_sync_jobs", "workspace_id"):
        # Already added out-of-band (e.g. via manual ALTER TABLE); do
        # not double-apply. This keeps the migration idempotent on envs
        # that patched the column by hand before this catch-up shipped.
        return
    with op.batch_alter_table("sharepoint_sync_jobs") as batch:
        batch.add_column(
            sa.Column(
                "workspace_id",
                sa.String(length=36),
                sa.ForeignKey("workspaces.id", name=FK_NAME),
                nullable=True,
            )
        )
    op.create_index(
        "ix_sharepoint_sync_jobs_workspace_id",
        "sharepoint_sync_jobs",
        ["workspace_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "sharepoint_sync_jobs", "workspace_id"):
        return
    op.drop_index(
        "ix_sharepoint_sync_jobs_workspace_id",
        table_name="sharepoint_sync_jobs",
    )
    with op.batch_alter_table("sharepoint_sync_jobs") as batch:
        batch.drop_column("workspace_id")
