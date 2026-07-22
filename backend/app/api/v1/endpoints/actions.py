"""Transverse Agentium action manifests and execution API."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import enforce_permission
from app.db.base import get_db
from app.models.expert_capture import ExpertCaptureSession
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.actions.registry import (
    catalog_action_manifests,
    effective_action_manifests,
    execute_action,
    resolve_action,
)
from app.services.iam.decision_plane import enforce_action, resolve_manifest_permission

router = APIRouter()


def _enforce_action_read(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    resource_attrs: dict[str, Any],
) -> None:
    """Preserve the legacy manifest gate, then apply exact v2 rollout."""

    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="action",
        action="read",
        resource_attrs=resource_attrs,
        audit_prefix="action",
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="action",
        action="read",
        legacy_allowed=True,
        resource_attrs=resource_attrs,
    )


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
    system_id: Optional[str] = None
    confirm: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/manifests")
async def list_action_manifests(
    surface: Optional[str] = Query(default=None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _enforce_action_read(
        db,
        workspace=workspace,
        user=user,
        resource_attrs={"capability": "agentium_actions"},
    )
    effective_ids = {
        manifest.action_id for manifest in effective_action_manifests(workspace, surface=surface)
    }
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
    system = _resolve_system(db, workspace, system_id)
    _enforce_action_read(
        db,
        workspace=workspace,
        user=user,
        resource_attrs={
            "capability": "agentium_actions",
            "system_id": system.id if system else None,
            "capability_id": system.capability_id if system else None,
        },
    )
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
    system = _resolve_system(db, workspace, body.system_id)
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="action",
        action="resolve",
        resource_attrs={
            "capability": "agentium_actions",
            "surface": body.surface,
            "system_id": system.id if system else None,
            "capability_id": system.capability_id if system else None,
        },
        audit_prefix="action",
    )
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
    system = _resolve_system(db, workspace, body.system_id)
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="action",
        action="execute",
        resource_attrs={
            "capability": "agentium_actions",
            "surface": body.surface,
            "action_id": body.action_id,
            "system_id": system.id if system else None,
            "capability_id": system.capability_id if system else None,
        },
        audit_prefix="action",
    )
    manifest = next(
        (
            item
            for item in effective_action_manifests(
                workspace,
                surface=body.surface,
                assistant_profile=body.assistant_profile,
                system=system,
            )
            if item.action_id == body.action_id
        ),
        None,
    )
    if manifest is not None:
        manifest_attrs = _manifest_resource_attrs(
            db,
            workspace=workspace,
            manifest_permission=manifest.required_permission,
            payload=body.payload,
            system=system,
        )
        resolution = resolve_manifest_permission(
            db,
            user=user,
            workspace=workspace,
            required_permission=manifest.required_permission,
            legacy_allowed=True,
            capability_manifest=manifest.capability_template,
            action_id=manifest.action_id,
            resource_attrs={
                "workspace_id": workspace.id,
                "system_id": system.id if system else None,
                "capability_id": system.capability_id if system else None,
                "capability": manifest.capability_template,
                "action_id": manifest.action_id,
                **manifest_attrs,
            },
        )
        if not resolution.effective_allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "WORKSPACE_PERMISSION_DENIED",
                    "message": "Action manifest permission denied",
                    "reason": resolution.reason,
                    "policy_id": resolution.policy_id,
                    "mode": resolution.mode,
                },
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
        system=system,
    )
    db.commit()
    return result


def _resolve_system(
    db: DBSession, workspace: Workspace, system_id: Optional[str]
) -> Optional[System]:
    if not system_id:
        return None
    system = (
        db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    )
    if not system:
        raise HTTPException(status_code=404, detail="System not found")
    return system


def _manifest_resource_attrs(
    db: DBSession,
    *,
    workspace: Workspace,
    manifest_permission: str,
    payload: dict[str, Any],
    system: Optional[System],
) -> dict[str, Any]:
    """Load persisted owner evidence for resource-scoped ActionManifests."""

    if not manifest_permission.startswith("capture_session."):
        return {}
    raw_session_id = payload.get("capture_session_id") or payload.get("session_id")
    if not isinstance(raw_session_id, str) or not raw_session_id.strip():
        return {}
    session = (
        db.query(ExpertCaptureSession)
        .filter(
            ExpertCaptureSession.id == raw_session_id.strip(),
            ExpertCaptureSession.workspace_id == workspace.id,
        )
        .one_or_none()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Capture session not found")
    if system is not None and session.system_id not in {None, system.id}:
        raise HTTPException(status_code=409, detail="Capture session/System mismatch")
    return {
        "capture_session_id": session.id,
        "owner_user_id": session.created_by_user_id,
        "system_id": session.system_id or (system.id if system else None),
        "capability_id": session.capability_id,
    }


def _demo_safe(workspace: Workspace) -> bool:
    settings = workspace.settings or {}
    return bool(
        workspace.mode == "demo"
        or settings.get("demo_safe") is True
        or settings.get("demo_safe_mode") is True
        or settings.get("hide_provider_details") is True
    )
