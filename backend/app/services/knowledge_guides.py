"""Versioned Markdown Knowledge guides.

Knowledge guides are human-authored context notes attached to a Knowledge
Scope or a collection. They complement raw documents: retrieval can use them
as query hints, the LLM sees them in the context block, and the UI can display
them as a distinct source type.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import uuid4
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.audit import AuditLog  # noqa: F401  (ensures model registration in tests)
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_guide import KnowledgeGuide
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.rag.knowledge_scopes import normalize_knowledge_scopes

GUIDE_TARGET_TYPES = {"collection", "scope"}
GUIDE_STATUSES = {"draft", "published", "archived"}
GUIDE_HINT_MAX_CHARS = 1200


def _actor(user: User | Any | None) -> str | None:
    return getattr(user, "email", None) or getattr(user, "username", None) or getattr(user, "id", None)


def _user_id(user: User | Any | None) -> str | None:
    return getattr(user, "id", None)


def _settings(workspace: Workspace) -> dict[str, Any]:
    return dict(workspace.settings or {}) if isinstance(workspace.settings, Mapping) else {}


def _normalize_status(status: str | None) -> str:
    normalized = str(status or "draft").strip().lower()
    if normalized not in GUIDE_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid guide status")
    return normalized


def _normalize_target_type(target_type: str | None) -> str:
    normalized = str(target_type or "").strip().lower()
    if normalized not in GUIDE_TARGET_TYPES:
        raise HTTPException(status_code=422, detail="Invalid guide target_type")
    return normalized


def _clean_text(value: Any, *, field: str, max_len: int | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail=f"Missing guide {field}")
    if max_len and len(text) > max_len:
        raise HTTPException(status_code=422, detail=f"Guide {field} is too long")
    return text


def _validate_target(
    db: Session,
    workspace: Workspace,
    *,
    target_type: str,
    target_ref: str,
) -> str:
    target_type = _normalize_target_type(target_type)
    target_ref = _clean_text(target_ref, field="target_ref", max_len=255)
    if target_type == "collection":
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id,
                KnowledgeCollection.slug == target_ref,
            )
            .first()
        )
        if not collection:
            raise HTTPException(status_code=404, detail="Knowledge collection not found")
        return collection.slug

    scopes = normalize_knowledge_scopes(_settings(workspace).get("knowledge_scopes"))
    if not any(scope["key"] == target_ref for scope in scopes):
        raise HTTPException(status_code=404, detail="Knowledge scope not found")
    return target_ref


def serialize_guide(guide: KnowledgeGuide, *, include_markdown: bool = True) -> dict[str, Any]:
    body = guide.markdown or ""
    payload = {
        "id": guide.id,
        "guide_key": guide.guide_key,
        "workspace_id": guide.workspace_id,
        "target_type": guide.target_type,
        "target_ref": guide.target_ref,
        "title": guide.title,
        "status": guide.status,
        "version": guide.version,
        "is_current": guide.is_current,
        "supersedes_id": guide.supersedes_id,
        "created_by_user_id": guide.created_by_user_id,
        "created_at": guide.created_at.isoformat() if guide.created_at else None,
        "published_at": guide.published_at.isoformat() if guide.published_at else None,
        "snippet": body[:280],
    }
    if include_markdown:
        payload["markdown"] = body
    return payload


def list_guides(
    db: Session,
    workspace: Workspace,
    *,
    target_type: str | None = None,
    target_ref: str | None = None,
    status: str | None = None,
    current_only: bool = True,
) -> list[KnowledgeGuide]:
    query = db.query(KnowledgeGuide).filter(KnowledgeGuide.workspace_id == workspace.id)
    if current_only:
        query = query.filter(KnowledgeGuide.is_current.is_(True))
    if target_type:
        query = query.filter(KnowledgeGuide.target_type == _normalize_target_type(target_type))
    if target_ref:
        query = query.filter(KnowledgeGuide.target_ref == str(target_ref).strip())
    if status:
        query = query.filter(KnowledgeGuide.status == _normalize_status(status))
    return query.order_by(KnowledgeGuide.target_type, KnowledgeGuide.target_ref, KnowledgeGuide.title).all()


def create_guide(
    db: Session,
    workspace: Workspace,
    *,
    target_type: str,
    target_ref: str,
    title: str,
    markdown: str,
    status: str = "draft",
    user: User | Any | None = None,
) -> KnowledgeGuide:
    target_type = _normalize_target_type(target_type)
    target_ref = _validate_target(db, workspace, target_type=target_type, target_ref=target_ref)
    status = _normalize_status(status)
    now = datetime.utcnow()
    guide = KnowledgeGuide(
        id=str(uuid4()),
        guide_key=str(uuid4()),
        workspace_id=workspace.id,
        target_type=target_type,
        target_ref=target_ref,
        title=_clean_text(title, field="title", max_len=255),
        markdown=_clean_text(markdown, field="markdown"),
        status=status,
        version=1,
        is_current=True,
        created_by_user_id=_user_id(user),
        created_at=now,
        published_at=now if status == "published" else None,
    )
    db.add(guide)
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="knowledge.guide.created",
        actor=_actor(user),
        details={
            "guide_key": guide.guide_key,
            "version": guide.version,
            "target_type": guide.target_type,
            "target_ref": guide.target_ref,
            "status": guide.status,
        },
        db=db,
    )
    db.commit()
    db.refresh(guide)
    return guide


def update_guide(
    db: Session,
    workspace: Workspace,
    guide_key: str,
    *,
    patch: dict[str, Any],
    user: User | Any | None = None,
) -> KnowledgeGuide:
    current = (
        db.query(KnowledgeGuide)
        .filter(
            KnowledgeGuide.workspace_id == workspace.id,
            KnowledgeGuide.guide_key == guide_key,
            KnowledgeGuide.is_current.is_(True),
        )
        .first()
    )
    if not current:
        raise HTTPException(status_code=404, detail="Knowledge guide not found")

    target_type = _normalize_target_type(patch.get("target_type") or current.target_type)
    target_ref = _validate_target(
        db,
        workspace,
        target_type=target_type,
        target_ref=patch.get("target_ref") or current.target_ref,
    )
    status = _normalize_status(patch.get("status") or current.status)
    now = datetime.utcnow()
    current.is_current = False
    db.add(current)
    next_version = KnowledgeGuide(
        id=str(uuid4()),
        guide_key=current.guide_key,
        workspace_id=workspace.id,
        target_type=target_type,
        target_ref=target_ref,
        title=_clean_text(patch.get("title", current.title), field="title", max_len=255),
        markdown=_clean_text(patch.get("markdown", current.markdown), field="markdown"),
        status=status,
        version=current.version + 1,
        is_current=True,
        supersedes_id=current.id,
        created_by_user_id=_user_id(user),
        created_at=now,
        published_at=now if status == "published" else None,
    )
    db.add(next_version)
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="knowledge.guide.updated",
        actor=_actor(user),
        details={
            "guide_key": current.guide_key,
            "from_version": current.version,
            "to_version": next_version.version,
            "target_type": next_version.target_type,
            "target_ref": next_version.target_ref,
            "status": next_version.status,
        },
        db=db,
    )
    db.commit()
    db.refresh(next_version)
    return next_version


def effective_guides(
    db: Session,
    *,
    workspace_id: str | None,
    scope_key: str | None = None,
    collection_slugs: list[str] | None = None,
) -> list[KnowledgeGuide]:
    if not workspace_id:
        return []
    filters: list[tuple[str, str]] = []
    if scope_key:
        filters.append(("scope", scope_key))
    for slug in collection_slugs or []:
        if slug:
            filters.append(("collection", str(slug)))
    if not filters:
        return []

    query = (
        db.query(KnowledgeGuide)
        .filter(
            KnowledgeGuide.workspace_id == workspace_id,
            KnowledgeGuide.is_current.is_(True),
            KnowledgeGuide.status == "published",
        )
    )
    rows = query.all()
    wanted = set(filters)
    selected: list[KnowledgeGuide] = []
    seen: set[str] = set()
    for row in rows:
        if (row.target_type, row.target_ref) not in wanted or row.guide_key in seen:
            continue
        seen.add(row.guide_key)
        selected.append(row)
    selected.sort(key=lambda item: (0 if item.target_type == "scope" else 1, item.title))
    return selected


def guide_query_hint(guides: list[KnowledgeGuide]) -> str:
    parts: list[str] = []
    for guide in guides[:4]:
        markdown = " ".join((guide.markdown or "").split())
        if markdown:
            parts.append(f"{guide.title}: {markdown[:GUIDE_HINT_MAX_CHARS]}")
    return "\n".join(parts)


def guide_context_entries(guides: list[KnowledgeGuide]) -> tuple[list[str], list[float], list[dict[str, Any]]]:
    chunks: list[str] = []
    scores: list[float] = []
    metadatas: list[dict[str, Any]] = []
    for guide in guides[:4]:
        markdown = (guide.markdown or "").strip()
        if not markdown:
            continue
        chunks.append(f"Knowledge guide: {guide.title}\n\n{markdown}")
        # Guides are advisory context, not raw evidence. Keep their retrieval
        # score intentionally low so factual spreadsheet/PDF chunks stay ahead
        # in source lists and citation ranking.
        scores.append(0.01)
        metadatas.append(
            {
                "source_type": "knowledge_guide",
                "type": "knowledge_guide",
                "retrieval_role": "advisory_context",
                "title": guide.title,
                "document_title": guide.title,
                "guide_key": guide.guide_key,
                "guide_version": guide.version,
                "target_type": guide.target_type,
                "target_ref": guide.target_ref,
            }
        )
    return chunks, scores, metadatas
