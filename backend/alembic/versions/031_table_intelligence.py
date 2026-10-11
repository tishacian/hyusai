"""Table intelligence fact store.

Revision ID: 031_table_intelligence
Revises: 030_knowledge_guides
Create Date: 2026-05-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "031_table_intelligence"
down_revision = "030_knowledge_guides"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "systems" in tables and not _has_column(inspector, "systems", "settings"):
        op.add_column("systems", sa.Column("settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        op.alter_column("systems", "settings", server_default=None)

    if "knowledge_table_facts" in tables:
        return

    op.create_table(
        "knowledge_table_facts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_id", sa.String(length=36), sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_slug", sa.String(length=120), nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=True),
        sa.Column("document_filename", sa.Text(), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("sheet_name", sa.String(length=255), nullable=True),
        sa.Column("table_region_id", sa.String(length=255), nullable=True),
        sa.Column("semantic_type", sa.String(length=64), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("column_index", sa.Integer(), nullable=True),
        sa.Column("cell_ref", sa.String(length=64), nullable=True),
        sa.Column("cell_range", sa.String(length=128), nullable=True),
        sa.Column("row_label", sa.Text(), nullable=True),
        sa.Column("column_header", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("measure", sa.Text(), nullable=True),
        sa.Column("value_raw", sa.Text(), nullable=True),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=128), nullable=True),
        sa.Column("qualifiers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("semantic_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_table_facts_workspace_id", "knowledge_table_facts", ["workspace_id"])
    op.create_index("ix_knowledge_table_facts_collection_id", "knowledge_table_facts", ["collection_id"])
    op.create_index("ix_knowledge_table_facts_collection_slug", "knowledge_table_facts", ["collection_slug"])
    op.create_index("ix_knowledge_table_facts_document_id", "knowledge_table_facts", ["document_id"])
    op.create_index("ix_knowledge_table_facts_sheet_name", "knowledge_table_facts", ["sheet_name"])
    op.create_index("ix_knowledge_table_facts_table_region_id", "knowledge_table_facts", ["table_region_id"])
    op.create_index("ix_knowledge_table_facts_semantic_type", "knowledge_table_facts", ["semantic_type"])
    op.create_index("ix_knowledge_table_facts_row_index", "knowledge_table_facts", ["row_index"])
    op.create_index("ix_knowledge_table_facts_cell_ref", "knowledge_table_facts", ["cell_ref"])
    op.create_index("ix_knowledge_table_facts_value_numeric", "knowledge_table_facts", ["value_numeric"])
    op.create_index("ix_knowledge_table_facts_unit", "knowledge_table_facts", ["unit"])
    op.create_index("ix_knowledge_table_facts_workspace_collection", "knowledge_table_facts", ["workspace_id", "collection_slug"])
    op.create_index("ix_knowledge_table_facts_collection_type", "knowledge_table_facts", ["collection_id", "semantic_type"])
    op.create_index("ix_knowledge_table_facts_measure_subject", "knowledge_table_facts", ["measure", "subject"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_table_facts" in inspector.get_table_names():
        op.drop_table("knowledge_table_facts")
    if "systems" in inspector.get_table_names() and _has_column(inspector, "systems", "settings"):
        op.drop_column("systems", "settings")
