"""Workspace-level Knowledge Scope resolution.

A scope is a lightweight workspace setting which groups several knowledge
collections under a product-facing name. Retrieval remains tenant-isolated by
the vector store factory because each collection is opened with the current
workspace slug.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.workspace import Workspace

COLLECTION_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")

# Safe constant used when no usable workspace slug is available to derive the
# per-workspace expert fiche collection default.
EXPERT_FICHE_COLLECTION_FALLBACK = "expert-fiche"


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_key(value: Any) -> str:
    return str(value or "").strip()


def _clean_collection_slugs(value: Any) -> list[str]:
    slugs: list[str] = []
    raw_values = value if isinstance(value, list) else []
    for item in raw_values:
        slug = _safe_key(item)
        if not slug or not COLLECTION_SLUG_RE.match(slug):
            continue
        if slug not in slugs:
            slugs.append(slug)
    return slugs


def sanitize_scope(raw: Any) -> dict[str, Any] | None:
    """Return a canonical scope dict or ``None`` for invalid input."""
    data = _as_mapping(raw)
    key = _safe_key(data.get("key"))
    if not key or not COLLECTION_SLUG_RE.match(key):
        return None

    collections = _clean_collection_slugs(data.get("collection_slugs"))
    if not collections:
        return None

    default_mode = _safe_key(data.get("default_mode") or data.get("rag_mode") or "auto")
    if default_mode not in {"auto", "naive", "hybrid", "hah", "chah"}:
        default_mode = "auto"

    try:
        top_k = int(data.get("top_k") or 0)
    except (TypeError, ValueError):
        top_k = 0

    return {
        "key": key,
        "label": _safe_key(data.get("label")) or key.replace("_", " ").title(),
        "description": _safe_key(data.get("description")),
        "collection_slugs": collections,
        "default_mode": default_mode,
        "top_k": top_k if top_k > 0 else None,
        "is_default": bool(data.get("is_default")),
        "table_profile_key": _safe_key(data.get("table_profile_key")) or None,
        "document_profile_key": _safe_key(data.get("document_profile_key")) or None,
    }


def normalize_knowledge_scopes(raw_scopes: Any) -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = []
    for item in raw_scopes if isinstance(raw_scopes, list) else []:
        scope = sanitize_scope(item)
        if scope and not any(existing["key"] == scope["key"] for existing in scopes):
            scopes.append(scope)
    return scopes


def fallback_scope(collection_slug: str, *, key: str = "workspace_default") -> dict[str, Any]:
    safe_collection = collection_slug if COLLECTION_SLUG_RE.match(collection_slug) else "documents"
    return {
        "key": key,
        "label": "Workspace default",
        "description": "",
        "collection_slugs": [safe_collection],
        "default_mode": "auto",
        "top_k": None,
        "is_default": True,
        "table_profile_key": None,
        "document_profile_key": None,
    }


def select_scope(
    scopes: list[dict[str, Any]],
    requested_key: str | None,
    fallback_collection: str,
) -> dict[str, Any]:
    if requested_key:
        for scope in scopes:
            if scope["key"] == requested_key:
                return scope
    for scope in scopes:
        if scope.get("is_default"):
            return scope
    if scopes:
        return scopes[0]
    return fallback_scope(fallback_collection)


def resolve_knowledge_scope(
    *,
    workspace_id: str | None,
    requested_key: str | None,
    fallback_collection: str,
    db: Session | None = None,
) -> dict[str, Any]:
    """Resolve the effective Knowledge Scope for a chat request.

    ``db`` is optional so the Celery worker and the inline chat path can share
    this helper without leaking a session dependency through the orchestrator.
    """
    if not workspace_id:
        return fallback_scope(fallback_collection)

    should_close = db is None
    session = db or SessionLocal()
    try:
        workspace = session.query(Workspace).filter(Workspace.id == workspace_id).first()
        settings = _as_mapping(workspace.settings if workspace else {})
        scopes = normalize_knowledge_scopes(settings.get("knowledge_scopes"))
        return select_scope(scopes, requested_key, fallback_collection)
    finally:
        if should_close:
            session.close()


def _workspace_slug(workspace: Any) -> str:
    """Best-effort slug read from an ORM object or a mapping-like workspace."""
    slug = getattr(workspace, "slug", None)
    if slug is None and isinstance(workspace, Mapping):
        slug = workspace.get("slug")
    return _safe_key(slug)


def _sanitize_collection_slug(value: Any) -> str:
    """Coerce an arbitrary string into a COLLECTION_SLUG_RE-valid slug.

    Invalid characters are replaced with ``-``, leading non-alphanumerics are
    trimmed (the first char must be alphanumeric) and the result is truncated to
    120 chars. Returns ``""`` when nothing valid remains.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", _safe_key(value))
    cleaned = cleaned.lstrip("_.-")[:120]
    return cleaned if cleaned and COLLECTION_SLUG_RE.match(cleaned) else ""


def resolve_expert_fiche_collection(workspace: Any, source_policy: Any) -> str:
    """Resolve the destination collection slug for validated expert fiches.

    Decision (plan Volet 1): reuse the workspace capture publication collection
    by default, configurable per workspace. Pointing ``expert_fiche_collection``
    (in the chat ``source_policy``) at an existing capture publication collection
    slug makes the two share storage.

    Resolution order:
      1. ``source_policy["expert_fiche_collection"]`` when present and slug-valid.
      2. A deterministic per-workspace default ``f"{workspace.slug}-expert-fiche"``
         sanitized to satisfy COLLECTION_SLUG_RE.
      3. ``EXPERT_FICHE_COLLECTION_FALLBACK`` when no usable workspace slug exists.

    This volet only resolves the slug; it does not wire scope inclusion or the
    ranking boost (Volet 3).
    """
    policy = _as_mapping(source_policy)
    configured = _safe_key(policy.get("expert_fiche_collection"))
    if configured and COLLECTION_SLUG_RE.match(configured):
        return configured

    workspace_slug = _workspace_slug(workspace)
    if workspace_slug:
        default_slug = _sanitize_collection_slug(f"{workspace_slug}-expert-fiche")
        if default_slug:
            return default_slug

    return EXPERT_FICHE_COLLECTION_FALLBACK
