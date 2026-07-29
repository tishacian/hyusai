"""FastAPI helpers for workspace IAM enforcement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.app_entitlements import (
    app_entitlements_enabled,
    member_has_app_entitlement,
    normalize_app_entitlements,
)
from app.services.iam.config_service import is_iam_enforced_for_workspace
from app.services.iam.engine import AuthorizationEngine, Decision
from app.services.workspace_app_runtime import (
    WorkspaceAppRuntimeError,
    installed_entitlement_keys,
    workspace_app_api_path_allowed,
    workspace_app_platform_enabled,
)


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


def workspace_app_not_installed_exception() -> HTTPException:
    """Hide missing and invalid app topology behind the same 404 contract."""

    return HTTPException(
        status_code=404,
        detail={"code": "WORKSPACE_APP_NOT_FOUND"},
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
    attrs = resource_attrs or {}
    use_knowledge_capture_v2 = attrs.get("capability") == "expert_knowledge_capture"
    decision = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action=action,
        resource_attrs=attrs,
        audit_prefix=audit_prefix,
        # When the candidate plane is active it owns the effective decision;
        # do not emit a contradictory legacy denial before it resolves.
        audit_denials=(enforced and not use_knowledge_capture_v2),
    )
    if use_knowledge_capture_v2:
        # Local import avoids the dependency cycle: decision_plane evaluates
        # candidate manifests through ``evaluate_permission`` above.
        from app.services.iam.decision_plane import enforce_candidate_permission

        enforce_candidate_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind=resource_kind,
            action=action,
            legacy_allowed=(decision.allowed if enforced else True),
            resource_attrs=attrs,
            candidate_manifest="expert_knowledge_capture_v2",
        )
        return decision
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

    return require_any_app_entitlement(app_key)


def require_any_app_entitlement(*app_keys: str):
    """Like :func:`require_app_entitlement` but grants entry if any key matches.

    Used when multiple surfaces share an API router (e.g. knowledge-capture and
    fse-reports both hit ``/api/v1/knowledge-capture``).
    """

    normalized = normalize_app_entitlements(list(app_keys))
    if not normalized:
        raise ValueError("At least one application entitlement key is required")
    primary_app_key = normalized[0]

    async def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        workspace: Workspace = Depends(get_current_workspace),
        db: DBSession = Depends(get_db),
    ) -> AppEntitlementContext:
        if workspace_app_platform_enabled(workspace):
            try:
                present_entitlements = installed_entitlement_keys(workspace, db=db)
            except WorkspaceAppRuntimeError as exc:
                raise workspace_app_not_installed_exception() from exc
            if not set(normalized).intersection(present_entitlements):
                raise workspace_app_not_installed_exception()
            try:
                path_allowed = workspace_app_api_path_allowed(
                    workspace,
                    request.url.path,
                    db=db,
                    entitlement_keys=normalized,
                )
            except WorkspaceAppRuntimeError as exc:
                raise workspace_app_not_installed_exception() from exc
            if not path_allowed:
                raise workspace_app_not_installed_exception()

        # Once Workspace App runtime authority is active, manifest-declared
        # entry entitlements are authoritative as well.  Treating the legacy
        # flag as the only enforcement switch would make a malformed rollout
        # permissive even though the installed manifest and API-prefix gates
        # are otherwise valid.
        enforced = app_entitlements_enabled(workspace) or workspace_app_platform_enabled(
            workspace
        )
        if not enforced:
            return AppEntitlementContext(
                user=user,
                workspace=workspace,
                membership=None,
                app_key=primary_app_key,
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
        granted_key = next(
            (key for key in normalized if member_has_app_entitlement(db, membership, key)),
            None,
        )
        if granted_key is None:
            raise app_entitlement_denied_exception(primary_app_key)
        return AppEntitlementContext(
            user=user,
            workspace=workspace,
            membership=membership,
            app_key=granted_key,
            enforced=True,
            granted=True,
        )

    return dependency
