"""Workspace Knowledge Scope endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.document_intelligence import DocumentQueryEngine
from app.services.iam.app_entitlements import (
    WorkspaceEntitlementMutationConflictError,
    lock_workspace_for_app_entitlement_mutation,
)
from app.services.knowledge_guides import (
    create_guide,
    effective_guides,
    list_guides,
    serialize_guide,
    update_guide,
)
from app.services.rag.knowledge_scopes import (
    normalize_knowledge_scopes,
    sanitize_scope,
)
from app.services.systems.bootstrap import ensure_workspace_chat_system_default
from app.services.table_intelligence import TableQueryEngine

router = APIRouter()


class KnowledgeScopePayload(BaseModel):
    key: str
    label: str | None = None
    description: str | None = None
    collection_slugs: list[str] = Field(default_factory=list)
    default_mode: str | None = None
    top_k: int | None = None
    is_default: bool = False
    table_profile_key: str | None = None
    document_profile_key: str | None = None


class KnowledgeScopesPatch(BaseModel):
    scopes: list[KnowledgeScopePayload]


class KnowledgeGuideCreate(BaseModel):
    target_type: str = Field(..., description="collection or scope")
    target_ref: str = Field(..., description="Collection slug or Knowledge Scope key")
    title: str
    markdown: str
    status: str = "draft"


class KnowledgeGuidePatch(BaseModel):
    target_type: str | None = None
    target_ref: str | None = None
    title: str | None = None
    markdown: str | None = None
    status: str | None = None


class TableQueryRequest(BaseModel):
    collection_or_scope: str | None = None
    question: str
    mode: str = "auto"
    filters: dict[str, Any] = Field(default_factory=dict)
    system_id: str | None = None
    table_profile_key: str | None = None
    include_evidence: bool = True


class DocumentQueryRequest(BaseModel):
    collection_or_scope: str | None = None
    question: str
    mode: str = "auto"
    filters: dict[str, Any] = Field(default_factory=dict)
    system_id: str | None = None
    document_profile_key: str | None = None
    include_evidence: bool = True


def _require_workspace_admin(db: Session, user: User, workspace: Workspace) -> None:
    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
        .populate_existing()
        .first()
    )
    if not membership or not is_admin_template(
        getattr(membership, "role_template", None), membership.role
    ):
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})


def _collection_stats(db: Session, workspace_id: str) -> dict[str, dict[str, Any]]:
    from app.services.knowledge_collections import collection_inventory

    rows = (
        db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == workspace_id).all()
    )
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        inventory = collection_inventory(db, collection=row, include_sources=False)
        stats[row.slug] = {
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "document_count": row.document_count,
            "chunk_count": row.chunk_count,
            "source_count": inventory.get("source_count"),
            "source_kind_counts": inventory.get("by_kind") or {},
            "source_extension_counts": inventory.get("by_extension") or {},
        }
    return stats


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


@router.get("/guides")
def list_knowledge_guides(
    target_type: str | None = Query(default=None),
    target_ref: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_only: bool = Query(default=True),
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    guides = list_guides(
        db,
        workspace,
        target_type=target_type,
        target_ref=target_ref,
        status=status,
        current_only=current_only,
    )
    return {
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "items": [serialize_guide(guide) for guide in guides],
    }


@router.get("/guides/effective")
def list_effective_knowledge_guides(
    knowledge_scope: str | None = Query(default=None),
    collection_slug: list[str] | None = Query(default=None),
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    guides = effective_guides(
        db,
        workspace_id=workspace.id,
        scope_key=knowledge_scope,
        collection_slugs=collection_slug or [],
    )
    return {
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "items": [serialize_guide(guide) for guide in guides],
    }


@router.post("/guides")
def create_knowledge_guide(
    payload: KnowledgeGuideCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workspace_admin(db, user, workspace)
    guide = create_guide(
        db,
        workspace,
        target_type=payload.target_type,
        target_ref=payload.target_ref,
        title=payload.title,
        markdown=payload.markdown,
        status=payload.status,
        user=user,
    )
    return serialize_guide(guide)


@router.patch("/guides/{guide_key}")
def patch_knowledge_guide(
    guide_key: str,
    payload: KnowledgeGuidePatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workspace_admin(db, user, workspace)
    guide = update_guide(
        db,
        workspace,
        guide_key,
        patch=payload.model_dump(exclude_unset=True),
        user=user,
    )
    return serialize_guide(guide)


@router.patch("/scopes")
def patch_knowledge_scopes(
    payload: KnowledgeScopesPatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
    except WorkspaceEntitlementMutationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _require_workspace_admin(db, user, workspace)
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
    # The always-on chat System folds its manifest's retrieval_defaults on
    # every turn; refresh it here so a scope edit (top_k, mode) is the budget
    # actually used instead of a stale snapshot from the last seed run.
    ensure_workspace_chat_system_default(db, workspace.id)
    return _serialize_scopes(workspace=workspace, db=db)


@router.post("/table-query")
def query_table_knowledge(
    payload: TableQueryRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    """Run analytic lookup/aggregation over structured table facts."""
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="question is required")
    engine = TableQueryEngine(db)
    return engine.query(
        workspace=workspace,
        question=payload.question,
        collection_or_scope=payload.collection_or_scope,
        mode=payload.mode,
        filters=payload.filters,
        system_id=payload.system_id,
        table_profile_key=payload.table_profile_key,
        include_evidence=payload.include_evidence,
    )


@router.post("/document-query")
def query_document_knowledge(
    payload: DocumentQueryRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    """Run structured lookup over document facts from manuals/procedures."""
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="question is required")
    engine = DocumentQueryEngine(db)
    return engine.query(
        workspace=workspace,
        question=payload.question,
        collection_or_scope=payload.collection_or_scope,
        mode=payload.mode,
        filters=payload.filters,
        system_id=payload.system_id,
        document_profile_key=payload.document_profile_key,
        include_evidence=payload.include_evidence,
    )
