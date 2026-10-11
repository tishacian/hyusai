"""Generic document intelligence fact store.

Revision ID: 032_document_intelligence
Revises: 031_table_intelligence
Create Date: 2026-05-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "032_document_intelligence"
down_revision = "031_table_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_document_facts" in inspector.get_table_names():
        return

    op.create_table(
        "knowledge_document_facts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_id", sa.String(length=36), sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_slug", sa.String(length=120), nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=True),
        sa.Column("document_filename", sa.Text(), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("semantic_type", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("predicate", sa.String(length=128), nullable=True),
        sa.Column("value_raw", sa.Text(), nullable=True),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=128), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("table_index", sa.Integer(), nullable=True),
        sa.Column("evidence_locator", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("qualifiers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("semantic_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.65"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "workspace_id",
        "collection_id",
        "collection_slug",
        "document_id",
        "document_type",
        "semantic_type",
        "predicate",
        "value_numeric",
        "unit",
        "page",
        "paragraph_index",
    ):
        op.create_index(f"ix_knowledge_document_facts_{column}", "knowledge_document_facts", [column])
    op.create_index("ix_knowledge_document_facts_workspace_collection", "knowledge_document_facts", ["workspace_id", "collection_slug"])
    op.create_index("ix_knowledge_document_facts_collection_type", "knowledge_document_facts", ["collection_id", "semantic_type"])
    op.create_index("ix_knowledge_document_facts_subject_predicate", "knowledge_document_facts", ["subject", "predicate"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_document_facts" in inspector.get_table_names():
        op.drop_table("knowledge_document_facts")
