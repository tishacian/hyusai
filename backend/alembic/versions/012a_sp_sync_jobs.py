"""Create sharepoint_sync_jobs — the table 013/014 assumed already existed.

Revision ID: 012a_sp_sync_jobs
Revises: 012_chat_runs_nullable_sys
Create Date: 2026-09-13

Background: the table was never created by a migration. It entered the
schema through ``Base.metadata.create_all`` at startup (commit
``0b4090d`` — "persist sync jobs in SQL for multi-worker uvicorn"),
back when the legacy/demo startup mode reconciled the ORM against the
database on every boot. Every environment that existed then already
had the table, so the two migrations that followed could alter it
without anyone noticing there was nothing to alter:

- ``013_sp_ingest_columns`` batch-adds ``ingested_count`` /
  ``ingest_failed_count`` / ``collection_name``;
- ``014_sp_workspace_id`` adds ``workspace_id`` (itself a catch-up for
  the same class of drift, at column granularity).

On a database built purely from migrations — a clean bootstrap, or the
``startup_reconciliation=disabled`` deployment mode where Alembic is
the only schema author — ``alembic upgrade head`` dies at 013 with
``no such table: sharepoint_sync_jobs`` and stamps nothing past 012.

This revision restores the missing link in the chain, inserted between
012 and 013 so the table exists before anything alters it. The columns
below are the table as ``create_all`` built it at that point in
history: the model minus the three columns 013 adds and the
``workspace_id`` 014 adds. ``status`` is included — it has been on the
model since the table's first commit, so legacy tables carry it, and
no migration has ever added it.

Replay safety: existing databases already carry the table, and they
are stamped well past this point, so Alembic never walks through here
for them. The existence guard covers the remaining case — a database
sitting at exactly 012 with a ``create_all`` table already present —
and makes a re-run after a partial failure a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "012a_sp_sync_jobs"
down_revision = "012_chat_runs_nullable_sys"
branch_labels = None
depends_on = None


TABLE = "sharepoint_sync_jobs"
SESSION_KEY_INDEX = "ix_sharepoint_sync_jobs_session_key"


def _table_exists(bind) -> bool:
    return TABLE in set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if _table_exists(op.get_bind()):
        # Created out-of-band by the legacy startup reconciliation. Leave
        # it alone: 013 and 014 layer onto it exactly as they were
        # written to, and its rows are live sync history.
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_key", sa.String(length=255), nullable=False),
        sa.Column("auth_mode", sa.String(length=16), nullable=False),
        # "running" | "completed" | "failed"
        sa.Column("state", sa.String(length=20), nullable=False),
        # Refined status once the job terminates; NULL while running.
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("progress", sa.String(length=120), nullable=True),
        # Nullable with no server default, matching the model: the zeros
        # are Python-side defaults, which create_all never emitted as DDL.
        sa.Column("files_total", sa.Integer(), nullable=True),
        sa.Column("files_downloaded", sa.Integer(), nullable=True),
        sa.Column("bytes_total", sa.Integer(), nullable=True),
        sa.Column("login_required_detail", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("output_dir", sa.Text(), nullable=True),
        sa.Column("folder_server_relative_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(SESSION_KEY_INDEX, TABLE, ["session_key"])


def downgrade() -> None:
    # Guarded so a downgrade past a database that never reached here is
    # a no-op rather than a crash. Note this drops the table whoever
    # created it, including a legacy create_all one — same posture as
    # 014, which drops workspace_id without asking who added it.
    # Operators rolling back below 012a lose sync history.
    if not _table_exists(op.get_bind()):
        return
    op.drop_index(SESSION_KEY_INDEX, table_name=TABLE)
    op.drop_table(TABLE)
