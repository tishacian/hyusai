"""FastAPI helpers for workspace IAM enforcement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.config_service import is_iam_enforced_for_workspace
from app.services.iam.app_entitlements import (
    app_entitlements_enabled,
    member_has_app_entitlement,
    normalize_app_entitlements,
)
from app.services.iam.engine import AuthorizationEngine, Decision


@dataclass(frozen=True)
class PermissionContext:
    user: User
    workspace: Workspace
    membership: Optional[WorkspaceMember]
    decision: Decision


@dataclass(frozen=True)
class AppEntitlementContext:
    user: User
    workspace: Workspace
    membership: Optional[WorkspaceMember]
    app_key: str
    enforced: bool
    granted: bool


def current_membership(db: DBSession, user: User, workspace: Workspace) -> Optional[WorkspaceMember]:
    return (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
        .first()
    )


def permission_denied_exception(decision: Decision) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "WORKSPACE_PERMISSION_DENIED",
            "message": "Workspace permission denied",
            "reason": decision.reason,
            "policy_id": decision.policy_id,
        },
    )


def app_entitlement_denied_exception(app_key: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "WORKSPACE_APP_ACCESS_DENIED",
            "message": "Workspace application access denied",
            "app_key": app_key,
        },
    )


def evaluate_permission(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str,
    action: str,
    resource_attrs: Optional[Dict[str, Any]] = None,
    membership: Optional[WorkspaceMember] = None,
    audit_prefix: str = "iam",
    audit_denials: bool = True,
) -> Decision:
    return AuthorizationEngine().evaluate(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind=resource_kind,
        action=action,
        resource_attrs=resource_attrs,
        audit_prefix=audit_prefix,
        audit_denials=audit_denials,
    )


def enforce_permission(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str,
    action: str,
    resource_attrs: Optional[Dict[str, Any]] = None,
    audit_prefix: str = "iam",
) -> Decision:
    enforced = is_iam_enforced_for_workspace(workspace)
    decision = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action=action,
        resource_attrs=resource_attrs,
        audit_prefix=audit_prefix,
        audit_denials=enforced,
    )
    if enforced and not decision.allowed:
        raise permission_denied_exception(decision)
    return decision


def require_permission(
    resource_kind: str,
    action: str,
    *,
    static_attrs: Optional[Dict[str, Any]] = None,
    audit_prefix: str = "iam",
):
    async def dependency(
        user: User = Depends(get_current_user),
        workspace: Workspace = Depends(get_current_workspace),
        db: DBSession = Depends(get_db),
    ) -> PermissionContext:
        membership = current_membership(db, user, workspace)
        decision = enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind=resource_kind,
            action=action,
            resource_attrs=static_attrs or {},
            audit_prefix=audit_prefix,
        )
        return PermissionContext(user=user, workspace=workspace, membership=membership, decision=decision)

    return dependency


def require_app_entitlement(app_key: str):
    """Feature-gated, fail-closed application entry dependency.

    This is an outer application gate only.  Existing endpoint-level IAM
    dependencies still decide which operations an entitled member may perform.
    """

    normalized = normalize_app_entitlements([app_key])
    if len(normalized) != 1:
        raise ValueError("Exactly one application entitlement key is required")
    canonical_app_key = normalized[0]

    async def dependency(
        user: User = Depends(get_current_user),
        workspace: Workspace = Depends(get_current_workspace),
        db: DBSession = Depends(get_db),
    ) -> AppEntitlementContext:
        enforced = app_entitlements_enabled(workspace)
        if not enforced:
            return AppEntitlementContext(
                user=user,
                workspace=workspace,
                membership=None,
                app_key=canonical_app_key,
                enforced=False,
                granted=True,
            )

        membership = current_membership(db, user, workspace)
        if membership is None:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "WORKSPACE_ACCESS_DENIED",
                    "message": "Not a member of this workspace",
                },
            )
        if not member_has_app_entitlement(db, membership, canonical_app_key):
            raise app_entitlement_denied_exception(canonical_app_key)
        return AppEntitlementContext(
            user=user,
            workspace=workspace,
            membership=membership,
            app_key=canonical_app_key,
            enforced=True,
            granted=True,
        )

    return dependency
