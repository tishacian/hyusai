"""Knowledge collections and worker job ledger.

Revision ID: 025_kc_worker_jobs
Revises: 024_secure_deposit
Create Date: 2026-05-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "025_kc_worker_jobs"
down_revision = "024_secure_deposit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_collections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("document_names", sa.JSON(), nullable=False),
        sa.Column("vector_collection_name", sa.String(length=255), nullable=False),
        sa.Column("artifact_prefix", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("chunking_method", sa.String(length=100), nullable=True),
        sa.Column("chunking_params", sa.JSON(), nullable=True),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('created', 'queued', 'ingesting', 'embedding', 'ready', 'error')",
            name="ck_knowledge_collections_status",
        ),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_knowledge_collections_workspace_slug"),
    )
    op.create_index("ix_knowledge_collections_workspace_id", "knowledge_collections", ["workspace_id"])
    op.create_index(
        "ix_knowledge_collections_workspace_status",
        "knowledge_collections",
        ["workspace_id", "status"],
    )

    op.create_table(
        "worker_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_id", sa.String(length=36), sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('document_ingest_index', 'vector_reindex', 'bm25_rebuild')",
            name="ck_worker_jobs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_worker_jobs_status",
        ),
    )
    op.create_index("ix_worker_jobs_workspace_id", "worker_jobs", ["workspace_id"])
    op.create_index("ix_worker_jobs_collection_id", "worker_jobs", ["collection_id"])
    op.create_index("ix_worker_jobs_celery_task_id", "worker_jobs", ["celery_task_id"])
    op.create_index("ix_worker_jobs_workspace_status", "worker_jobs", ["workspace_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_worker_jobs_workspace_status", table_name="worker_jobs")
    op.drop_index("ix_worker_jobs_celery_task_id", table_name="worker_jobs")
    op.drop_index("ix_worker_jobs_collection_id", table_name="worker_jobs")
    op.drop_index("ix_worker_jobs_workspace_id", table_name="worker_jobs")
    op.drop_table("worker_jobs")

    op.drop_index("ix_knowledge_collections_workspace_status", table_name="knowledge_collections")
    op.drop_index("ix_knowledge_collections_workspace_id", table_name="knowledge_collections")
    op.drop_table("knowledge_collections")
