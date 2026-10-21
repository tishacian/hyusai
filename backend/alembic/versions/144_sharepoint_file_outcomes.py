"""Persist bounded SharePoint download and ingestion receipts."""

import sqlalchemy as sa

from alembic import op

revision = "144_sharepoint_file_outcomes"
down_revision = "143_task_executions"
branch_labels = depends_on = None


def upgrade():
    op.add_column("sharepoint_sync_jobs", sa.Column("file_outcomes", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("sharepoint_sync_jobs", "file_outcomes")
