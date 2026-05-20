"""Canonical /capabilities endpoints — Catalog + economics knobs.

The seed catalog (5-10 universal capabilities) is provisioned by the
`skills_registry.seed_capabilities()` helper at startup and exposed here
as `/catalog`. Workspaces can override pricing / value / SLA.
"""
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.workspace import Workspace
from app.services.catalog_visibility import (
    capability_is_visible,
    visibility_label,
    visible_capabilities,
    workspace_catalog_policy,
)

router = APIRouter()


class CapabilityCreate(BaseModel):
    slug: str
    name: str
    description: str = ""
    tier: str = "universal"
    industry: Optional[str] = None
    input_unit: str = "request"
    output_unit: str = "answer"
    skill_ids: List[str] = []
    pricing: Dict[str, Any] = {"unit": "per_outcome", "unit_price": 0.0, "currency": "USD"}
    value_per_outcome: Optional[float] = None
    confidence_threshold: Optional[float] = None
    sla: Dict[str, Any] = {}
    roi_model: Dict[str, Any] = {}


class CapabilityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tier: Optional[str] = None
    industry: Optional[str] = None
    skill_ids: Optional[List[str]] = None
    pricing: Optional[Dict[str, Any]] = None
    value_per_outcome: Optional[float] = None
    confidence_threshold: Optional[float] = None
    sla: Optional[Dict[str, Any]] = None
    roi_model: Optional[Dict[str, Any]] = None


def _serialize(c: Capability, workspace: Workspace | None = None) -> Dict[str, Any]:
    policy = workspace_catalog_policy(workspace) if workspace else None
    return {
        "id": c.id,
        "slug": c.slug,
        "name": c.name,
        "description": c.description,
        "tier": c.tier,
        "industry": c.industry,
        "input_unit": c.input_unit,
        "output_unit": c.output_unit,
        "skill_ids": c.skill_ids or [],
        "pricing": c.pricing or {},
        "value_per_outcome": c.value_per_outcome,
        "confidence_threshold": c.confidence_threshold,
        "sla": c.sla or {},
        "roi_model": c.roi_model or {},
        "is_seeded": c.is_seeded == "Y",
        "workspace_scope": "global" if c.workspace_id is None else "workspace",
        "workspace_visibility": visibility_label(c, workspace, policy) if workspace else None,
    }


@router.get("/catalog")
async def get_catalog(
    tier: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Seed catalog rows visible to the current workspace."""
    q = db.query(Capability).filter(Capability.workspace_id.is_(None), Capability.is_seeded == "Y")
    if tier:
        q = q.filter(Capability.tier == tier)
    policy = workspace_catalog_policy(workspace)
    rows = visible_capabilities(q.order_by(Capability.name.asc()).all(), workspace, policy)
    return {
        "capabilities": [_serialize(c, workspace) for c in rows],
        "catalog_policy": {
            "allowed_industries": sorted(policy.allowed_industries),
            "show_universal": policy.show_universal,
        },
    }


@router.get("")
async def list_capabilities(
    tier: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    q = db.query(Capability).filter(
        (Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None))
    )
    if tier:
        q = q.filter(Capability.tier == tier)
    policy = workspace_catalog_policy(workspace)
    rows = visible_capabilities(q.order_by(Capability.tier.asc(), Capability.name.asc()).all(), workspace, policy)
    return {
        "capabilities": [_serialize(c, workspace) for c in rows],
        "catalog_policy": {
            "allowed_industries": sorted(policy.allowed_industries),
            "show_universal": policy.show_universal,
        },
    }


@router.post("")
async def create_capability(
    body: CapabilityCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    if db.query(Capability).filter(Capability.slug == body.slug).first():
        raise HTTPException(409, "Slug already exists")
    c = Capability(id=str(uuid4()), workspace_id=workspace.id, **body.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return _serialize(c, workspace)


@router.get("/{cap_id}")
async def get_capability(
    cap_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    c = db.query(Capability).filter(
        Capability.id == cap_id,
        ((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None))),
    ).first()
    if not c:
        raise HTTPException(404, "Capability not found")
    if not capability_is_visible(c, workspace):
        raise HTTPException(404, "Capability not found")
    return _serialize(c, workspace)


@router.patch("/{cap_id}")
async def update_capability(
    cap_id: str,
    body: CapabilityUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    c = db.query(Capability).filter(
        Capability.id == cap_id, Capability.workspace_id == workspace.id
    ).first()
    if not c:
        raise HTTPException(404, "Capability not found (or not editable in this workspace)")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return _serialize(c, workspace)
