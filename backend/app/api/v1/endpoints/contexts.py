"""Canonical /contexts endpoints — versioned bag of state for a System.

D0 extension — the chat workspace surface can create *ephemeral* contexts
for drop-and-ask sessions: the client POSTs with `ephemeral=true` and
`ttl_hours=N`, we stamp `ttl_expires_at = now + ttl_hours`, and purge
opportunistically on every `GET /contexts`. A user can promote a session
context to permanent via `POST /contexts/{id}/persist`.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.context import Context
from app.models.workspace import Workspace

router = APIRouter()


class ContextBody(BaseModel):
    name: str = "default"
    system_id: Optional[str] = None
    data_refs: List[str] = []
    memory_refs: List[str] = []
    history_refs: List[str] = []
    environment_state: Dict[str, Any] = {}
    business_constraints: Dict[str, Any] = {}
    permissions: Dict[str, Any] = {}
    # D0 — ephemeral session contexts (drop-and-ask). When true, the
    # server stamps `ttl_expires_at = now + ttl_hours` and the context is
    # eligible for opportunistic purge.
    ephemeral: bool = False
    ttl_hours: int = Field(
        default=24,
        ge=1,
        le=24 * 30,
        description="TTL in hours, only honoured when ephemeral=true.",
    )


class ContextUpdate(BaseModel):
    """Partial update for a Context — every field optional so PATCH is idempotent.

    Distinct from `ContextBody` which is a *create* schema with defaults; a
    partial body lets the UI flip a single field (e.g. rename, add a data_ref)
    without round-tripping the full object.
    """
    name: Optional[str] = None
    system_id: Optional[str] = None
    data_refs: Optional[List[str]] = None
    memory_refs: Optional[List[str]] = None
    history_refs: Optional[List[str]] = None
    environment_state: Optional[Dict[str, Any]] = None
    business_constraints: Optional[Dict[str, Any]] = None
    permissions: Optional[Dict[str, Any]] = None


def _serialize(c: Context) -> Dict[str, Any]:
    return {
        "id": c.id,
        "system_id": c.system_id,
        "name": c.name,
        "version": c.version,
        "data_refs": c.data_refs or [],
        "memory_refs": c.memory_refs or [],
        "history_refs": c.history_refs or [],
        "environment_state": c.environment_state or {},
        "business_constraints": c.business_constraints or {},
        "permissions": c.permissions or {},
        "ephemeral": bool(c.ephemeral),
        "ttl_expires_at": c.ttl_expires_at.isoformat() if c.ttl_expires_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _purge_expired_ephemerals(db: DBSession, workspace_id: str) -> int:
    """Opportunistic cleanup: delete expired ephemeral contexts for the
    current workspace. Called from `GET /contexts` so we never accumulate
    stale session contexts without needing a background worker.

    Returns the number of purged rows (for logging / debug only).
    """
    now = datetime.utcnow()
    expired = (
        db.query(Context)
        .filter(
            Context.workspace_id == workspace_id,
            Context.ephemeral.is_(True),
            Context.ttl_expires_at.isnot(None),
            Context.ttl_expires_at < now,
        )
        .all()
    )
    if not expired:
        return 0
    for c in expired:
        db.delete(c)
    db.commit()
    return len(expired)


@router.get("")
async def list_contexts(
    system_id: Optional[str] = None,
    include_ephemeral: bool = True,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    # Opportunistic purge before listing — keeps the list honest without a
    # scheduled job. Safe to run on every call (it's a bounded delete on a
    # single index).
    _purge_expired_ephemerals(db, workspace.id)

    q = db.query(Context).filter(Context.workspace_id == workspace.id)
    if system_id:
        q = q.filter(Context.system_id == system_id)
    if not include_ephemeral:
        q = q.filter(Context.ephemeral.is_(False))
    rows = q.order_by(Context.updated_at.desc()).all()
    return {"contexts": [_serialize(c) for c in rows]}


@router.post("")
async def create_context(
    body: ContextBody,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    payload = body.model_dump(exclude={"ephemeral", "ttl_hours"})
    ttl_expires_at: Optional[datetime] = None
    if body.ephemeral:
        ttl_expires_at = datetime.utcnow() + timedelta(hours=body.ttl_hours)
    c = Context(
        id=str(uuid4()),
        workspace_id=workspace.id,
        ephemeral=body.ephemeral,
        ttl_expires_at=ttl_expires_at,
        **payload,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _serialize(c)


@router.post("/{ctx_id}/persist")
async def persist_ephemeral_context(
    ctx_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Promote an ephemeral (drop-and-ask) context to permanent.

    Idempotent — calling this on an already-permanent context is a no-op
    that returns the current serialization.
    """
    c = (
        db.query(Context)
        .filter(Context.id == ctx_id, Context.workspace_id == workspace.id)
        .first()
    )
    if not c:
        raise HTTPException(404, "Context not found")
    if c.ephemeral:
        c.ephemeral = False
        c.ttl_expires_at = None
        db.commit()
        db.refresh(c)
    return _serialize(c)


@router.get("/{ctx_id}")
async def get_context(
    ctx_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    c = db.query(Context).filter(Context.id == ctx_id, Context.workspace_id == workspace.id).first()
    if not c:
        raise HTTPException(404, "Context not found")
    return _serialize(c)


@router.patch("/{ctx_id}")
async def update_context(
    ctx_id: str,
    body: ContextUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    c = db.query(Context).filter(Context.id == ctx_id, Context.workspace_id == workspace.id).first()
    if not c:
        raise HTTPException(404, "Context not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    c.version = (c.version or 1) + 1
    db.commit()
    db.refresh(c)
    return _serialize(c)


@router.delete("/{ctx_id}", status_code=204)
async def delete_context(
    ctx_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Hard-delete a Context. Systems referencing this id keep the dangling
    ref but `GET /contexts/{id}` will 404; the cockpit clears the pin.
    """
    c = db.query(Context).filter(Context.id == ctx_id, Context.workspace_id == workspace.id).first()
    if not c:
        raise HTTPException(404, "Context not found")
    db.delete(c)
    db.commit()
    return None
