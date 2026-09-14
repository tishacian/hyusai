"""SharePoint sync → RAG ingest wiring (Vague E / E4.1).

Revision ID: 013_sp_ingest_columns
Revises: 012a_sp_sync_jobs
Create Date: 2026-04-25

Why: E4.1 closes the gap between "SharePoint sync materialises files on
disk" and "those files are searchable by the RAG pipeline". A completed
sync now pipes each downloaded file through
:meth:`DocumentService.ingest_document`, so we need to remember per-job:

- ``ingested_count`` — documents successfully vectorised + indexed.
- ``ingest_failed_count`` — documents the parser/embedder could not
  process (bad PDF, unsupported extension, parser crash). Operators can
  spot-check these without relying on logs.
- ``collection_name`` — which logical collection the files landed in
  (default ``documents`` to match the upload-from-browser flow). Lets
  the UI show "→ documents" on the job card without a second round-trip.

All additive, nullable or defaulted. No data migration needed on
existing jobs (they simply display ``0 / 0 / NULL``).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "013_sp_ingest_columns"
down_revision = "012a_sp_sync_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sharepoint_sync_jobs") as batch:
        batch.add_column(
            sa.Column(
                "ingested_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "ingest_failed_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "collection_name",
                sa.String(length=100),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("sharepoint_sync_jobs") as batch:
        batch.drop_column("collection_name")
        batch.drop_column("ingest_failed_count")
        batch.drop_column("ingested_count")
