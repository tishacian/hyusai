"""Metadata-only navigation search, filtered before counts and pagination."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.connector_connection import ConnectorConnection
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.user import User
from app.models.workspace import Workspace
from app.services.collection_access import can_read_collection, get_membership

router = APIRouter()


@router.get("/search")
def search(
    q: str = Query(min_length=2, max_length=160),
    limit: int = Query(default=30, ge=1, le=50),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return only metadata the same principal may open in the current workspace."""
    membership = get_membership(db, workspace=workspace, user_id=user.id)
    if not membership or not user.is_active or not workspace.is_active or workspace.deleted_at:
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})
    term = q.strip()
    results: list[dict] = []
    if len(term) < 2:
        return {"results": results, "has_more": False}
    pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    scope = {"id": workspace.id, "slug": workspace.slug, "name": workspace.name}

    def add(kind, row_id, label, route, hint=""):
        results.append(
            {
                "kind": kind,
                "id": row_id,
                "label": label,
                "route": route,
                "hint": hint,
                "workspace": scope,
            }
        )

    collections = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            or_(
                KnowledgeCollection.name.ilike(pattern, escape="\\"),
                KnowledgeCollection.slug.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(KnowledgeCollection.name, KnowledgeCollection.id)
    )
    for row in collections.yield_per(100):
        if can_read_collection(membership, row):
            add("collection", row.id, row.name, "/knowledge/" + quote(row.slug, safe=""))
            if len(results) > limit:
                break

    if len(results) <= limit:
        documents = (
            db.query(KnowledgeCollectionSource, KnowledgeCollection)
            .join(
                KnowledgeCollection,
                KnowledgeCollectionSource.collection_id == KnowledgeCollection.id,
            )
            .filter(
                KnowledgeCollectionSource.workspace_id == workspace.id,
                KnowledgeCollection.workspace_id == workspace.id,
                KnowledgeCollectionSource.status != "deleted",
                KnowledgeCollectionSource.filename.ilike(pattern, escape="\\"),
            )
            .order_by(KnowledgeCollectionSource.filename, KnowledgeCollectionSource.id)
        )
        for source, collection in documents.yield_per(100):
            if can_read_collection(membership, collection):
                route = (
                    "/knowledge/"
                    + quote(collection.slug, safe="")
                    + "?"
                    + urlencode({"facet": "sources", "q": source.filename})
                )
                add("document", source.id, source.filename, route, collection.name)
                if len(results) > limit:
                    break

    if len(results) <= limit and settings.connector_framework_enabled:
        connections = (
            db.query(ConnectorConnection)
            .filter(
                ConnectorConnection.workspace_id == workspace.id,
                ConnectorConnection.disabled_at.is_(None),
                ConnectorConnection.name.ilike(pattern, escape="\\"),
            )
            .order_by(ConnectorConnection.name, ConnectorConnection.id)
            .limit(limit + 1 - len(results))
        )
        for connection in connections:
            add(
                "connection",
                connection.id,
                connection.name,
                "/connectors/connections?" + urlencode({"connection_id": connection.id}),
            )

    return {"results": results[:limit], "has_more": len(results) > limit}
