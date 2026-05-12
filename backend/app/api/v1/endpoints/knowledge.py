"""Workspace Knowledge Scope endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services.rag.knowledge_scopes import (
    normalize_knowledge_scopes,
    sanitize_scope,
)

router = APIRouter()


class KnowledgeScopePayload(BaseModel):
    key: str
    label: str | None = None
    description: str | None = None
    collection_slugs: list[str] = Field(default_factory=list)
    default_mode: str | None = None
    top_k: int | None = None
    is_default: bool = False


class KnowledgeScopesPatch(BaseModel):
    scopes: list[KnowledgeScopePayload]


def _collection_stats(db: Session, workspace_id: str) -> dict[str, dict[str, Any]]:
    rows = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace_id)
        .all()
    )
    return {
        row.slug: {
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "document_count": row.document_count,
            "chunk_count": row.chunk_count,
        }
        for row in rows
    }


def _serialize_scopes(
    *,
    workspace: Workspace,
    db: Session,
) -> dict[str, Any]:
    scopes = normalize_knowledge_scopes((workspace.settings or {}).get("knowledge_scopes"))
    stats = _collection_stats(db, workspace.id)
    enriched = []
    for scope in scopes:
        enriched.append(
            {
                **scope,
                "collections": [
                    {
                        "slug": slug,
                        **(stats.get(slug) or {"status": "external_or_empty"}),
                    }
                    for slug in scope["collection_slugs"]
                ],
            }
        )
    default_key = next((scope["key"] for scope in enriched if scope.get("is_default")), None)
    return {
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "default": default_key or (enriched[0]["key"] if enriched else None),
        "scopes": enriched,
    }


@router.get("/scopes")
def list_knowledge_scopes(
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    return _serialize_scopes(workspace=workspace, db=db)


@router.patch("/scopes")
def patch_knowledge_scopes(
    payload: KnowledgeScopesPatch,
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    scopes = []
    for raw in payload.scopes:
        scope = sanitize_scope(raw.model_dump())
        if not scope:
            raise HTTPException(status_code=422, detail="Invalid knowledge scope")
        scopes.append(scope)
    if scopes and not any(scope.get("is_default") for scope in scopes):
        scopes[0]["is_default"] = True

    settings = dict(workspace.settings or {})
    settings["knowledge_scopes"] = scopes
    workspace.settings = settings
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return _serialize_scopes(workspace=workspace, db=db)

