"""Vector store selection helpers for RAG sync and retrieval paths."""
from __future__ import annotations

from typing import Any

from app.core.config import settings


def resolve_vector_db_type(app_settings: dict[str, Any] | None = None) -> str:
    """Resolve the effective vector store without letting legacy FAISS defaults win.

    ``get_resolved_settings`` may still merge old preset rows that contain
    ``ragVectorDBType = faiss``. Qdrant is now the application default; FAISS is
    kept for explicit legacy/migration calls, but automatic RAG paths should not
    silently fall back to it.
    """
    app_settings = app_settings or {}
    configured = (app_settings.get("ragVectorDBType") or "").strip().lower()
    default = (getattr(settings, "default_vector_db_type", None) or "").strip().lower()
    if configured and configured != "faiss":
        return configured
    return default or "qdrant"
