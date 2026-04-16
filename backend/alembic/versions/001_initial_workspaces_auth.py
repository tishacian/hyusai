"""Initial schema with workspaces and auth

Revision ID: 001_initial
Revises:
Create Date: 2026-04-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("settings", sa.JSON(), server_default=sa.text("'{}'")),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("keycloak_sub", sa.String(255), unique=True, nullable=True, index=True),
        sa.Column("role", sa.String(50), server_default="user"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("role", sa.String(50), server_default="member"),
        sa.Column("joined_at", sa.DateTime()),
        sa.UniqueConstraint("user_id", "workspace_id", name="uq_user_workspace"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True, index=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("last_activity", sa.DateTime()),
        sa.Column("meta_data", sa.JSON(), server_default=sa.text("'{}'")),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime()),
        sa.Column("meta_data", sa.JSON(), server_default=sa.text("'{}'")),
    )

    op.create_table(
        "app_settings",
        sa.Column("id", sa.String(50), primary_key=True, server_default="default"),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True, index=True),
        sa.Column("default_model", sa.String(100), server_default="gpt-4o"),
        sa.Column("default_provider", sa.String(50), server_default="openai"),
        sa.Column("temperature", sa.Float(), server_default="0.3"),
        sa.Column("max_tokens", sa.Integer(), server_default="4000"),
        sa.Column("top_k", sa.Integer(), server_default="5"),
        sa.Column("preferred_agents", sa.JSON(), server_default=sa.text("'[]'")),
        sa.Column("enable_rag", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("enable_reasoning", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("enable_search", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("rag_top_k", sa.Integer(), server_default="5"),
        sa.Column("rag_similarity_threshold", sa.Float(), server_default="0.2"),
        sa.Column("rag_collection_name", sa.String(100), server_default="documents"),
        sa.Column("rag_use_hybrid_search", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("rag_vector_weight", sa.Float(), server_default="0.7"),
        sa.Column("rag_bm25_weight", sa.Float(), server_default="0.3"),
        sa.Column("rag_vector_db_type", sa.String(20), server_default="faiss"),
        sa.Column("rag_chunking_method", sa.String(50), server_default="recursive_character"),
        sa.Column("rag_chunk_size", sa.Integer(), server_default="1000"),
        sa.Column("rag_chunk_overlap", sa.Integer(), server_default="200"),
        sa.Column("enable_streaming", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("streaming_speed", sa.String(20), server_default="normal"),
        sa.Column("theme", sa.String(20), server_default="light"),
        sa.Column("font_size", sa.String(20), server_default="medium"),
        sa.Column("show_reasoning_traces", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("show_sources", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("auto_expand_reasoning", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("api_url", sa.String(500), server_default="http://localhost:8000/api/v1"),
        sa.Column("api_timeout", sa.Integer(), server_default="30000"),
        sa.Column("enable_caching", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("cache_ttl", sa.Integer(), server_default="3600"),
        sa.Column("enable_rate_limiting", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default="60"),
        sa.Column("ollama_base_url", sa.String(500), server_default="http://localhost:11434"),
        sa.Column("ollama_num_ctx", sa.Integer(), server_default="32768"),
        sa.Column("ollama_rope_scale", sa.Float(), nullable=True),
        sa.Column("ollama_rope_alpha", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("id", "workspace_id", name="uq_settings_workspace"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True, index=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor", sa.String(255), server_default="demo-user"),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'")),
        sa.Column("trace_id", sa.String(36), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("severity", sa.String(20), server_default="info"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("created_by", sa.String(255), server_default="demo-user"),
        sa.Column("steps", sa.JSON(), server_default=sa.text("'[]'")),
        sa.Column("artifacts", sa.JSON(), server_default=sa.text("'{}'")),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("total_duration_ms", sa.Float(), nullable=True),
    )

    op.create_table(
        "evaluation_scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True, index=True),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("turn_number", sa.Integer(), server_default="0"),
        sa.Column("query", sa.String(2000), nullable=True),
        sa.Column("scores", sa.JSON(), server_default=sa.text("'{}'")),
        sa.Column("composite_score", sa.Float(), server_default="0.0"),
        sa.Column("hallucination_rate", sa.Float(), server_default="0.0"),
        sa.Column("drift_rate", sa.Float(), server_default="0.0"),
        sa.Column("claim_audit", sa.JSON(), server_default=sa.text("'{}'")),
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "feed_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("category", sa.String(100), server_default="general"),
        sa.Column("refresh_interval", sa.Integer(), server_default="3600"),
        sa.Column("last_fetched", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("article_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "feed_articles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(2000), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime()),
        sa.Column("embedded", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("analysis", sa.JSON(), nullable=True),
        sa.Column("relevance_score", sa.Float(), server_default="0.0"),
        sa.Column("safety_flag", sa.String(20), server_default="clear"),
    )

    op.create_table(
        "semantic_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("keywords", sa.JSON(), server_default=sa.text("'[]'")),
        sa.Column("relevance_threshold", sa.Float(), server_default="0.3"),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "safety_filters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), server_default="warn"),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("safety_filters")
    op.drop_table("semantic_targets")
    op.drop_table("feed_articles")
    op.drop_table("feed_sources")
    op.drop_table("evaluation_scores")
    op.drop_table("tasks")
    op.drop_table("audit_logs")
    op.drop_table("app_settings")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("workspace_members")
    op.drop_table("users")
    op.drop_table("workspaces")
