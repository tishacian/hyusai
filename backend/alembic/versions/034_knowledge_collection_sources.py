"""Knowledge collection source inventory ledger.

Revision ID: 034_collection_sources
Revises: 033_macro_meeting
Create Date: 2026-06-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "034_collection_sources"
down_revision = "033_macro_meeting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_collection_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            sa.String(length=36),
            sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("source_kind", sa.String(length=80), nullable=False, server_default="document"),
        sa.Column("extension", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("mime_type", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("origin", sa.String(length=80), nullable=False, server_default="upload"),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("source_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "collection_id",
            "normalized_name",
            name="uq_knowledge_collection_sources_collection_name",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'ingesting', 'indexed', 'ready', 'error', 'deleted')",
            name="ck_knowledge_collection_sources_status",
        ),
    )
    op.create_index(
        "ix_knowledge_collection_sources_workspace_id",
        "knowledge_collection_sources",
        ["workspace_id"],
    )
    op.create_index(
        "ix_knowledge_collection_sources_collection_id",
        "knowledge_collection_sources",
        ["collection_id"],
    )
    op.create_index(
        "ix_knowledge_collection_sources_workspace_collection",
        "knowledge_collection_sources",
        ["workspace_id", "collection_id"],
    )
    op.create_index(
        "ix_knowledge_collection_sources_kind",
        "knowledge_collection_sources",
        ["workspace_id", "source_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_collection_sources_kind", table_name="knowledge_collection_sources")
    op.drop_index("ix_knowledge_collection_sources_workspace_collection", table_name="knowledge_collection_sources")
    op.drop_index("ix_knowledge_collection_sources_collection_id", table_name="knowledge_collection_sources")
    op.drop_index("ix_knowledge_collection_sources_workspace_id", table_name="knowledge_collection_sources")
    op.drop_table("knowledge_collection_sources")
