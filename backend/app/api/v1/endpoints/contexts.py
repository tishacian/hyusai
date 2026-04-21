"""Canonical /contexts endpoints — versioned bag of state for a System."""
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("")
async def list_contexts(
    system_id: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    q = db.query(Context).filter(Context.workspace_id == workspace.id)
    if system_id:
        q = q.filter(Context.system_id == system_id)
    rows = q.order_by(Context.updated_at.desc()).all()
    return {"contexts": [_serialize(c) for c in rows]}


@router.post("")
async def create_context(
    body: ContextBody,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    c = Context(id=str(uuid4()), workspace_id=workspace.id, **body.model_dump())
    db.add(c)
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
    body: ContextBody,
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
