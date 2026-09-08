"""Canonical /capabilities endpoints — Catalog + economics knobs.

The seed catalog (5-10 universal capabilities) is provisioned by the
`skills_registry.seed_capabilities()` helper at startup and exposed here
as `/catalog`. Workspaces can override pricing / value / SLA.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.user import User
from app.models.workspace import Workspace
from app.services.catalog_visibility import (
    capability_is_visible,
    visibility_label,
    visible_capabilities,
    workspace_catalog_policy,
)
from app.services.iam.decision_plane import enforce_action
from app.services.iam.legacy_authority import legacy_object_action_allowed
from app.services.object_perspective import (
    build_capability_perspective,
    projection_feature_enabled,
)

router = APIRouter()


def _enforce_collection_read(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> None:
    """Resolve the collection boundary once; capability.read is role-scoped."""

    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capability",
        action="read",
        legacy_allowed=True,
        resource_attrs={"scope": "collection"},
    )


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


class ValueBasis(BaseModel):
    unit: Optional[str] = None
    hours_per_unit: Optional[float] = Field(default=None, ge=0)
    value_per_unit: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    declared_by: Optional[str] = None
    declared_at: Optional[str] = None
    status: Literal["declared", "measured", "none"] = "none"
    note: Optional[str] = None


class ValueBasisUpdate(BaseModel):
    unit: Optional[str] = None
    hours_per_unit: Optional[float] = Field(default=None, ge=0)
    value_per_unit: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    status: Literal["declared", "measured", "none"] = "declared"
    note: Optional[str] = None


def serialize_value_basis(
    raw: Any,
    *,
    default_unit: str | None = None,
    default_currency: str | None = None,
) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if status not in {"declared", "measured", "none"}:
        status = "none"
    unit = raw.get("unit") or default_unit
    currency = raw.get("currency") or default_currency
    return ValueBasis(
        unit=unit,
        hours_per_unit=_optional_float(raw.get("hours_per_unit")),
        value_per_unit=_optional_float(raw.get("value_per_unit")),
        currency=currency,
        declared_by=raw.get("declared_by"),
        declared_at=raw.get("declared_at"),
        status=status,
        note=raw.get("note"),
    ).model_dump()


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pricing_currency(capability: Capability) -> str:
    pricing = capability.pricing if isinstance(capability.pricing, dict) else {}
    return str(pricing.get("currency") or "USD")


def _value_basis_response(capability: Capability) -> dict[str, Any]:
    return {
        "capability_id": capability.id,
        "slug": capability.slug,
        "name": capability.name,
        "tier": capability.tier,
        "industry": capability.industry,
        "input_unit": capability.input_unit,
        "output_unit": capability.output_unit,
        "value_per_outcome": capability.value_per_outcome,
        "value_basis": serialize_value_basis(
            capability.value_basis,
            default_unit=capability.output_unit,
            default_currency=_pricing_currency(capability),
        ),
    }


def _visible_capability_or_404(
    db: DBSession,
    *,
    cap_id: str,
    workspace: Workspace,
) -> Capability:
    capability = (
        db.query(Capability)
        .filter(
            Capability.id == cap_id,
            ((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None))),
        )
        .first()
    )
    if capability is None or not capability_is_visible(capability, workspace):
        raise HTTPException(404, "Capability not found")
    return capability


def _actor_label(user: User) -> str:
    return user.email or user.username or user.id


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
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Seed catalog rows visible to the current workspace."""
    _enforce_collection_read(db, user=user, workspace=workspace)
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
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _enforce_collection_read(db, user=user, workspace=workspace)
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
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capability",
        action="admin",
        legacy_allowed=legacy_object_action_allowed(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capability",
            action="admin",
        ),
    )
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
    user: User = Depends(get_current_user),
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
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capability",
        action="read",
        legacy_allowed=True,
        resource_attrs={"capability_id": c.id},
    )
    return _serialize(c, workspace)


@router.get("/{cap_id}/perspective")
async def get_capability_perspective(
    cap_id: str,
    lens: Literal["build", "operate", "steer", "govern"],
    window: Literal["7d", "30d", "90d"] = "30d",
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return one validated projection of the same Capability object."""

    if not projection_feature_enabled(db, workspace, "capability"):
        raise HTTPException(
            410,
            {
                "code": "OBJECT_PROJECTION_REVOKED",
                "object_type": "capability",
            },
        )
    capability = db.query(Capability).filter(
        Capability.id == cap_id,
        ((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None))),
    ).first()
    if capability is None or not capability_is_visible(capability, workspace):
        raise HTTPException(404, "Capability perspective not found")
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capability",
        action="read",
        # Reaching this point means the existing workspace catalog policy
        # considers the Capability visible. Compat/shadow must preserve that
        # behaviour until this exact object/action is explicitly enforced.
        legacy_allowed=True,
        resource_attrs={"capability_id": capability.id},
    )
    return build_capability_perspective(
        db,
        workspace=workspace,
        user=user,
        capability=capability,
        lens=lens,
        window=window,
    )


@router.patch("/{cap_id}")
async def update_capability(
    cap_id: str,
    body: CapabilityUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    c = db.query(Capability).filter(
        Capability.id == cap_id, Capability.workspace_id == workspace.id
    ).first()
    if not c:
        raise HTTPException(404, "Capability not found (or not editable in this workspace)")
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capability",
        action="admin",
        legacy_allowed=legacy_object_action_allowed(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capability",
            action="admin",
        ),
        resource_attrs={"capability_id": c.id},
    )
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return _serialize(c, workspace)


@router.get("/{cap_id}/value-basis")
async def get_capability_value_basis(
    cap_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    capability = _visible_capability_or_404(db, cap_id=cap_id, workspace=workspace)
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capability",
        action="read",
        legacy_allowed=True,
        resource_attrs={"capability_id": capability.id},
    )
    return _value_basis_response(capability)


@router.put("/{cap_id}/value-basis")
async def put_capability_value_basis(
    cap_id: str,
    body: ValueBasisUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    capability = (
        db.query(Capability)
        .filter(Capability.id == cap_id, Capability.workspace_id == workspace.id)
        .first()
    )
    if not capability:
        raise HTTPException(404, "Capability not found (or not editable in this workspace)")
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capability",
        action="admin",
        legacy_allowed=legacy_object_action_allowed(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capability",
            action="admin",
        ),
        resource_attrs={"capability_id": capability.id},
    )
    stored = {
        "unit": body.unit or capability.output_unit,
        "hours_per_unit": body.hours_per_unit,
        "value_per_unit": body.value_per_unit,
        "currency": body.currency or _pricing_currency(capability),
        "declared_by": _actor_label(user),
        "declared_at": datetime.utcnow().isoformat(),
        "status": body.status,
        "note": body.note,
    }
    capability.value_basis = stored
    capability.value_per_outcome = body.value_per_unit
    db.commit()
    db.refresh(capability)
    return _value_basis_response(capability)
