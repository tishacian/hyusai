"""Workspace IAM administration and dry-run evaluation API."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import (
    current_membership,
    evaluate_permission,
    permission_denied_exception,
)
from app.core.iam.roles import (
    CANONICAL_WORKSPACE_ROLES,
    WORKSPACE_OWNER,
    legacy_role_for_template,
    normalize_role_template,
)
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.app_entitlements import (
    WorkspaceEntitlementMutationConflictError,
    list_member_app_entitlements,
    lock_workspace_for_app_entitlement_mutation,
    normalize_app_entitlements,
    replace_member_app_entitlements,
)
from app.services.iam.config_service import (
    effective_role_flags,
    is_iam_enforced_for_workspace,
    load_iam_config,
    patch_iam_config,
)
from app.services.iam.engine import AuthorizationEngine
from app.services.iam.manifest import CAPTURE_MANIFEST, iter_permissions

router = APIRouter()


class IamConfigPatch(BaseModel):
    role_flags: Optional[dict[str, Any]] = None
    capability_overrides: Optional[dict[str, Any]] = None


class MemberIamUpdate(BaseModel):
    role_template: str
    custom_labels: list[str] = Field(default_factory=list)
    app_entitlements: Optional[list[str]] = None


class IamEvaluateRequest(BaseModel):
    subject_user_id: Optional[str] = None
    resource_kind: str
    action: str
    resource_attrs: dict[str, Any] = Field(default_factory=dict)


def _member_payload(
    db: DBSession, membership: WorkspaceMember, current_user_id: str
) -> dict[str, Any]:
    user = db.query(User).filter(User.id == membership.user_id).first()
    return {
        "user_id": membership.user_id,
        "email": user.email if user else None,
        "username": user.username if user else membership.user_id,
        "role": membership.role,
        "role_template": normalize_role_template(
            getattr(membership, "role_template", None),
            membership.role,
        ),
        "custom_labels": membership.custom_labels or [],
        "app_entitlements": list_member_app_entitlements(db, membership),
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
        "is_current_user": membership.user_id == current_user_id,
    }


def _admin_gate(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str = "policy",
    action: str = "manage_policies",
    membership: WorkspaceMember | None = None,
) -> None:
    decision = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action=action,
        resource_attrs={"capability": CAPTURE_MANIFEST.capability_id},
        membership=membership,
    )
    if not decision.allowed:
        raise permission_denied_exception(decision)


@router.get("/summary")
async def iam_summary(
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    _admin_gate(
        db, user=user, workspace=workspace, resource_kind="workspace", action="manage_members"
    )
    members = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id)
        .order_by(WorkspaceMember.joined_at.asc())
        .all()
    )
    config = load_iam_config(db, workspace.id, create=True, updated_by_user_id=user.id)
    db.commit()
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "enforcement": is_iam_enforced_for_workspace(workspace),
        "config": {
            "version": config.version if config else 1,
            "role_flags": effective_role_flags(config),
            "capability_overrides": (config.capability_overrides or {}) if config else {},
        },
        "members": [_member_payload(db, member, user.id) for member in members],
    }


@router.get("/matrix")
async def iam_matrix(
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    membership = current_membership(db, user, workspace)
    if not membership:
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_ACCESS_DENIED"})
    config = load_iam_config(db, workspace.id, create=False)
    role_template = normalize_role_template(
        getattr(membership, "role_template", None), membership.role
    )
    permissions = []
    engine = AuthorizationEngine()
    for rule in iter_permissions():
        decision = engine.evaluate(
            db,
            user=user,
            workspace=workspace,
            membership=membership,
            resource_kind=rule.resource_kind,
            action=rule.action,
            resource_attrs={
                "capability": CAPTURE_MANIFEST.capability_id,
                "owner_user_id": user.id if "owner_match" in rule.conditions else None,
            },
            audit_denials=False,
        )
        permissions.append(
            {
                "resource_kind": rule.resource_kind,
                "action": rule.action,
                "roles": list(rule.roles),
                "conditions": list(rule.conditions),
                "policy_id": rule.resolved_policy_id(CAPTURE_MANIFEST.capability_id),
                "allowed_for_subject": decision.allowed,
            }
        )
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "subject_user_id": user.id,
        "role_template": role_template,
        "custom_labels": membership.custom_labels or [],
        "role_flags": effective_role_flags(config),
        "enforcement": is_iam_enforced_for_workspace(workspace),
        "permissions": permissions,
    }


@router.patch("/config")
async def patch_config(
    body: IamConfigPatch,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    _admin_gate(db, user=user, workspace=workspace)
    config = patch_iam_config(
        db,
        workspace_id=workspace.id,
        role_flags=body.role_flags,
        capability_overrides=body.capability_overrides,
        updated_by_user_id=user.id,
    )
    db.commit()
    return {
        "version": config.version,
        "role_flags": effective_role_flags(config),
        "capability_overrides": config.capability_overrides or {},
    }


@router.put("/members/{user_id}")
async def update_member_iam(
    user_id: str,
    body: MemberIamUpdate,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    _admin_gate(
        db, user=user, workspace=workspace, resource_kind="workspace", action="manage_members"
    )
    try:
        requested_app_entitlements = (
            normalize_app_entitlements(body.app_entitlements)
            if body.app_entitlements is not None
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_APP_ENTITLEMENT",
                "message": str(exc),
            },
        ) from exc
    if body.role_template not in CANONICAL_WORKSPACE_ROLES:
        raise HTTPException(status_code=400, detail="Unknown role_template")
    if body.role_template == WORKSPACE_OWNER:
        raise HTTPException(status_code=400, detail="Use transfer ownership to assign owner")

    try:
        workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
    except WorkspaceEntitlementMutationConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKSPACE_MEMBERSHIP_MUTATION_CONFLICT",
                "message": str(exc),
            },
        ) from exc
    # Authority may have changed while this request waited behind a Blueprint.
    caller_membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .populate_existing()
        .first()
    )
    _admin_gate(
        db,
        user=user,
        workspace=workspace,
        resource_kind="workspace",
        action="manage_members",
        membership=caller_membership,
    )

    target = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == workspace.id)
        .populate_existing()
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    target_role = normalize_role_template(getattr(target, "role_template", None), target.role)
    if target_role == WORKSPACE_OWNER:
        caller_role = normalize_role_template(
            getattr(caller_membership, "role_template", None) if caller_membership else None,
            caller_membership.role if caller_membership else None,
        )
        if target.user_id == user.id:
            raise HTTPException(
                status_code=400,
                detail="Your own owner role is managed through ownership transfer",
            )
        if caller_role != WORKSPACE_OWNER:
            raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})
        owner_count = sum(
            1
            for member in db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace.id)
            .populate_existing()
            .all()
            if normalize_role_template(getattr(member, "role_template", None), member.role)
            == WORKSPACE_OWNER
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="At least one workspace owner must remain")

    target.role_template = body.role_template
    target.role = legacy_role_for_template(body.role_template)
    target.custom_labels = body.custom_labels
    if requested_app_entitlements is not None:
        replace_member_app_entitlements(
            db,
            target,
            requested_app_entitlements,
            granted_by_user_id=user.id,
            grant_source="iam_member_update",
        )
    db.commit()
    db.refresh(target)
    return {"status": "ok", "member": _member_payload(db, target, user.id)}


@router.post("/evaluate")
async def evaluate_iam(
    body: IamEvaluateRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    _admin_gate(db, user=user, workspace=workspace)
    subject = user
    if body.subject_user_id and body.subject_user_id != user.id:
        subject = db.query(User).filter(User.id == body.subject_user_id).first()
        if not subject:
            raise HTTPException(status_code=404, detail="Subject user not found")
    decision = evaluate_permission(
        db,
        user=subject,
        workspace=workspace,
        resource_kind=body.resource_kind,
        action=body.action,
        resource_attrs={
            "capability": CAPTURE_MANIFEST.capability_id,
            **(body.resource_attrs or {}),
        },
        audit_denials=False,
    )
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "policy_id": decision.policy_id,
        "subject_user_id": subject.id,
        "resource_kind": body.resource_kind,
        "action": body.action,
        "resource_attrs": body.resource_attrs,
    }
