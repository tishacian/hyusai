"""Transverse Agentium action manifests and execution API."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import enforce_permission
from app.db.base import get_db
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.actions.registry import (
    catalog_action_manifests,
    effective_action_manifests,
    execute_action,
    resolve_action,
)


router = APIRouter()


class ActionResolveRequest(BaseModel):
    text: str = Field(default="", max_length=8000)
    surface: str = "chat"
    assistant_profile: Optional[str] = None
    system_id: Optional[str] = None


class ActionExecuteRequest(BaseModel):
    action_id: str
    text: str = ""
    surface: str = "chat"
    assistant_profile: Optional[str] = None
    confirm: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/manifests")
async def list_action_manifests(
    surface: Optional[str] = Query(default=None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="action",
        action="read",
        resource_attrs={"capability": "agentium_actions"},
        audit_prefix="action",
    )
    effective_ids = {manifest.action_id for manifest in effective_action_manifests(workspace, surface=surface)}
    demo_safe = _demo_safe(workspace)
    manifests = [
        manifest.to_payload(
            visible=manifest.action_id in effective_ids,
            inherited_from=manifest.pack,
            demo_safe=demo_safe,
        )
        for manifest in catalog_action_manifests(workspace)
        if not surface or surface in manifest.surfaces
    ]
    return {"manifests": manifests}


@router.get("/effective")
async def list_effective_actions(
    surface: Optional[str] = Query(default=None),
    assistant_profile: Optional[str] = Query(default=None),
    system_id: Optional[str] = Query(default=None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="action",
        action="read",
        resource_attrs={"capability": "agentium_actions"},
        audit_prefix="action",
    )
    system = _resolve_system(db, workspace, system_id)
    demo_safe = _demo_safe(workspace)
    actions = [
        manifest.to_payload(inherited_from=manifest.pack, demo_safe=demo_safe)
        for manifest in effective_action_manifests(
            workspace,
            surface=surface,
            assistant_profile=assistant_profile,
            system=system,
        )
    ]
    return {
        "actions": actions,
        "inheritance_order": ["system", "assistant_profile", "workspace", "capability", "global"],
    }


@router.post("/resolve")
async def resolve_transverse_action(
    body: ActionResolveRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="action",
        action="resolve",
        resource_attrs={"capability": "agentium_actions", "surface": body.surface},
        audit_prefix="action",
    )
    system = _resolve_system(db, workspace, body.system_id)
    resolution = resolve_action(
        workspace,
        text=body.text,
        surface=body.surface,
        assistant_profile=body.assistant_profile,
        system=system,
    )
    return resolution.to_payload(demo_safe=_demo_safe(workspace))


@router.post("/execute")
async def execute_transverse_action(
    body: ActionExecuteRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="action",
        action="execute",
        resource_attrs={"capability": "agentium_actions", "surface": body.surface, "action_id": body.action_id},
        audit_prefix="action",
    )
    result = execute_action(
        db,
        workspace,
        user,
        action_id=body.action_id,
        text=body.text,
        surface=body.surface,
        assistant_profile=body.assistant_profile,
        confirm=body.confirm,
        payload=body.payload,
    )
    db.commit()
    return result


def _resolve_system(db: DBSession, workspace: Workspace, system_id: Optional[str]) -> Optional[System]:
    if not system_id:
        return None
    system = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not system:
        raise HTTPException(status_code=404, detail="System not found")
    return system


def _demo_safe(workspace: Workspace) -> bool:
    settings = workspace.settings or {}
    return bool(
        workspace.mode == "demo"
        or settings.get("demo_safe") is True
        or settings.get("demo_safe_mode") is True
        or settings.get("hide_provider_details") is True
    )
