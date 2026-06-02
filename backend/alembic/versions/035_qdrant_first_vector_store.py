"""Qdrant-first vector store defaults.

Revision ID: 035_qdrant_first
Revises: 034_collection_sources
Create Date: 2026-06-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "035_qdrant_first"
down_revision = "034_collection_sources"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "app_settings"):
        with op.batch_alter_table("app_settings") as batch:
            batch.alter_column(
                "rag_vector_db_type",
                existing_type=sa.String(length=20),
                server_default="qdrant",
            )
        op.execute(
            "UPDATE app_settings "
            "SET rag_vector_db_type = 'qdrant' "
            "WHERE rag_vector_db_type IS NULL OR lower(rag_vector_db_type) = 'faiss'"
        )

    if _table_exists(inspector, "rag_presets"):
        dialect = bind.dialect.name
        if dialect == "postgresql":
            op.execute(
                """
                UPDATE rag_presets
                SET config = jsonb_set(
                    COALESCE(config::jsonb, '{}'::jsonb),
                    '{ragVectorDBType}',
                    '"qdrant"'::jsonb,
                    true
                )::json
                WHERE config IS NULL
                   OR lower(COALESCE(config->>'ragVectorDBType', 'faiss')) = 'faiss'
                """
            )
        elif dialect == "sqlite":
            op.execute(
                """
                UPDATE rag_presets
                SET config = json_set(COALESCE(config, '{}'), '$.ragVectorDBType', 'qdrant')
                WHERE config IS NULL
                   OR lower(COALESCE(json_extract(config, '$.ragVectorDBType'), 'faiss')) = 'faiss'
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "app_settings"):
        with op.batch_alter_table("app_settings") as batch:
            batch.alter_column(
                "rag_vector_db_type",
                existing_type=sa.String(length=20),
                server_default="faiss",
            )
