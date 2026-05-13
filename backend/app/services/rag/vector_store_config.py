"""Vector store selection helpers for RAG sync and retrieval paths."""
from __future__ import annotations

from typing import Any

from app.core.config import settings


def resolve_vector_db_type(app_settings: dict[str, Any] | None = None) -> str:
    """Resolve the effective vector store without letting legacy FAISS defaults win.

    ``get_resolved_settings`` merges every workspace preset with a legacy default
    dict that still contains ``ragVectorDBType = faiss``. On Docker/VM deployments
    the infrastructure source of truth is ``DEFAULT_VECTOR_DB_TYPE``; otherwise a
    workspace that never explicitly chose FAISS may silently index into the wrong
    store. Non-FAISS preset values remain explicit overrides.
    """
    app_settings = app_settings or {}
    configured = (app_settings.get("ragVectorDBType") or "").strip().lower()
    default = (getattr(settings, "default_vector_db_type", None) or "").strip().lower()
    if configured and configured != "faiss":
        return configured
    return default or configured or "faiss"
