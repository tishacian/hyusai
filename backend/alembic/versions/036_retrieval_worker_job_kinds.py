"""Add retrieval worker job kinds.

Revision ID: 036_retrieval_job_kinds
Revises: 035_qdrant_first
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "036_retrieval_job_kinds"
down_revision = "035_qdrant_first"
branch_labels = None
depends_on = None


NEW_KIND_CHECK = (
    "kind IN ('document_ingest_index', 'vector_reindex', 'bm25_rebuild', "
    "'rag_deep_retrieval', 'sparse_index_rebuild', 'summary_index_rebuild', "
    "'qdrant_sparse_reindex')"
)
OLD_KIND_CHECK = "kind IN ('document_ingest_index', 'vector_reindex', 'bm25_rebuild')"


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "worker_jobs"):
        return
    with op.batch_alter_table("worker_jobs") as batch:
        try:
            batch.drop_constraint("ck_worker_jobs_kind", type_="check")
        except Exception:
            pass
        batch.create_check_constraint("ck_worker_jobs_kind", NEW_KIND_CHECK)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "worker_jobs"):
        return
    with op.batch_alter_table("worker_jobs") as batch:
        try:
            batch.drop_constraint("ck_worker_jobs_kind", type_="check")
        except Exception:
            pass
        batch.create_check_constraint("ck_worker_jobs_kind", OLD_KIND_CHECK)
