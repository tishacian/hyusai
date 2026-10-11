"""Canonical RAG Preset — multi-scope configuration for Retrieval/Generation.

Revision ID: 009_rag_presets
Revises: 008_workspace_mode
Create Date: 2026-04-21

Vague A — P0. Turn the AppSettings singleton into a catalog of RAG Presets
scoped by workspace / capability / system. The legacy `app_settings` table
stays in place and the `/api/v1/settings` endpoints keep working (they are
now a thin proxy over the workspace default preset), so clients (including
the current Angular frontend) don't have to migrate in lock-step.

Data migration: for every existing `app_settings` row we create one preset
row with scope=workspace, is_default=true, cloning the camelCase payload
into `config`.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "009_rag_presets"
down_revision = "008_workspace_mode"
branch_labels = None
depends_on = None


# Columns cloned from `app_settings` into the preset `config` JSON.
# Mirrored from `SettingsService._settings_to_dict` so the compat proxy
# doesn't need any translation table — the payload is already camelCase.
_SETTING_TO_CAMEL: list[tuple[str, str, Any]] = [
    ("default_model", "defaultModel", "gpt-4o"),
    ("default_provider", "defaultProvider", "openai"),
    ("temperature", "temperature", 0.3),
    ("max_tokens", "maxTokens", 4000),
    ("top_k", "topK", 5),
    ("preferred_agents", "preferredAgents", []),
    ("enable_rag", "enableRAG", True),
    ("enable_reasoning", "enableReasoning", True),
    ("enable_search", "enableSearch", False),
    ("rag_top_k", "ragTopK", 5),
    ("rag_similarity_threshold", "ragSimilarityThreshold", 0.2),
    ("rag_collection_name", "ragCollectionName", "documents"),
    ("rag_use_hybrid_search", "ragUseHybridSearch", True),
    ("rag_vector_weight", "ragVectorWeight", 0.7),
    ("rag_bm25_weight", "ragBM25Weight", 0.3),
    ("rag_vector_db_type", "ragVectorDBType", "faiss"),
    ("rag_chunking_method", "ragChunkingMethod", "recursive_character"),
    ("rag_chunk_size", "ragChunkSize", 1000),
    ("rag_chunk_overlap", "ragChunkOverlap", 200),
    ("enable_streaming", "enableStreaming", True),
    ("streaming_speed", "streamingSpeed", "normal"),
    ("theme", "theme", "light"),
    ("font_size", "fontSize", "medium"),
    ("show_reasoning_traces", "showReasoningTraces", True),
    ("show_sources", "showSources", True),
    ("auto_expand_reasoning", "autoExpandReasoning", False),
    ("api_url", "apiUrl", "http://localhost:8000/api/v1"),
    ("api_timeout", "apiTimeout", 30000),
    ("enable_caching", "enableCaching", True),
    ("cache_ttl", "cacheTTL", 3600),
    ("enable_rate_limiting", "enableRateLimiting", True),
    ("rate_limit_per_minute", "rateLimitPerMinute", 60),
    ("ollama_base_url", "ollamaBaseUrl", "http://localhost:11434"),
    ("ollama_num_ctx", "ollamaNumCtx", 32768),
    ("ollama_rope_scale", "ollamaRopeScale", None),
    ("ollama_rope_alpha", "ollamaRopeAlpha", None),
]


def upgrade() -> None:
    op.create_table(
        "rag_presets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        # Scope enforced by application code + optional DB check constraint
        # below. Kept as plain String to avoid cross-dialect ENUM pain.
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "scope IN ('workspace', 'capability', 'system')",
            name="ck_rag_presets_scope",
        ),
    )

    op.create_index(
        "ix_rag_presets_scope", "rag_presets", ["scope", "scope_id"]
    )

    # Unique index: only one `is_default=true` preset per (scope, scope_id).
    # Use a partial index where supported (postgres/sqlite); fall back to
    # application-enforced uniqueness elsewhere.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect in {"postgresql", "sqlite"}:
        op.execute(
            "CREATE UNIQUE INDEX uq_rag_presets_default_per_scope "
            "ON rag_presets (scope, scope_id) WHERE is_default = true"
        )
    # MySQL etc. — the service enforces uniqueness in a transaction.

    # Data migration: clone every app_settings row into a default workspace preset.
    _seed_from_app_settings(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name in {"postgresql", "sqlite"}:
        op.execute("DROP INDEX IF EXISTS uq_rag_presets_default_per_scope")
    op.drop_index("ix_rag_presets_scope", table_name="rag_presets")
    op.drop_table("rag_presets")


def _seed_from_app_settings(bind) -> None:
    """Copy existing `app_settings` rows into workspace-scope default presets."""
    inspector = sa.inspect(bind)
    if "app_settings" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("app_settings")}

    select_cols = [col for col, _, _ in _SETTING_TO_CAMEL if col in existing_columns]
    if not select_cols:
        return
    select_cols += ["workspace_id"]

    rows = bind.execute(
        sa.text(f"SELECT {', '.join(select_cols)} FROM app_settings")
    ).mappings().all()

    if not rows:
        return

    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    insert_stmt = sa.text(
        """
        INSERT INTO rag_presets
          (id, name, scope, scope_id, workspace_id, config, is_default,
           created_at, updated_at)
        VALUES
          (:id, :name, 'workspace', :scope_id, :workspace_id,
           :config, true, :created_at, :updated_at)
        """
    )

    for row in rows:
        config: Dict[str, Any] = {}
        for db_col, camel_key, default in _SETTING_TO_CAMEL:
            if db_col in row:
                value = row[db_col]
            else:
                value = default
            config[camel_key] = value

        workspace_id = row.get("workspace_id")
        bind.execute(
            insert_stmt,
            {
                "id": str(uuid4()),
                "name": "Default",
                "scope_id": workspace_id,
                "workspace_id": workspace_id,
                "config": json.dumps(config),
                "created_at": now,
                "updated_at": now,
            },
        )
