"""Workspace-member application entitlements.

The entitlement layer is deliberately orthogonal to capability IAM: a member
must first be entitled to enter an application, then the existing RBAC/ABAC
rules continue to govern actions inside that application.  Workspaces that
have not enabled ``app_entitlements_v1`` retain their legacy membership-based
entry contract.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.schemas.canonical import WorkspaceApp

APP_ENTITLEMENTS_FEATURE = "app_entitlements_v1"
WORKSPACE_EXPERIENCE_FEATURE = "workspace_experience_v2"

CHAT_APP = WorkspaceApp.chat.value
CLIENT360_APP = WorkspaceApp.client360_pdr.value
KNOWLEDGE_CAPTURE_APP = WorkspaceApp.knowledge_capture.value
FSE_REPORTS_APP = WorkspaceApp.fse_reports.value

BUSINESS_APP_KEYS: tuple[str, ...] = tuple(app.value for app in WorkspaceApp)
_BUSINESS_APP_KEY_SET = frozenset(BUSINESS_APP_KEYS)
_APP_ENTITLEMENT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")


class WorkspaceEntitlementMutationConflictError(RuntimeError):
    """Raised when the workspace serialization row disappeared mid-request."""


def lock_workspace_for_app_entitlement_mutation(
    db: DBSession,
    workspace_id: str,
) -> Workspace:
    """Serialize membership/grant mutations with Blueprint application.

    The Workspace row is the shared transaction mutex. ``populate_existing``
    and the explicit settings refresh are intentional: callers commonly hold
    a Workspace instance loaded before waiting for the lock, while a Blueprint
    may have enabled entitlement enforcement in the meantime.

    The caller owns the transaction and must commit or roll it back only after
    every related membership and entitlement mutation is complete.
    """

    locked = (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if locked is None:
        raise WorkspaceEntitlementMutationConflictError(
            "Workspace disappeared before the membership mutation could be serialized"
        )
    db.refresh(locked, attribute_names=["settings"])
    return locked


def app_entitlements_enabled(workspace: Workspace | Any) -> bool:
    """Return whether missing application grants must deny access."""

    settings = getattr(workspace, "settings", None)
    features = settings.get("features") if isinstance(settings, Mapping) else None
    # This gate must agree with the frontend's literal-boolean contract. A
    # malformed string/integer value stays fail-safe in legacy-off mode rather
    # than creating a UI/API split where invitations omit required grants.
    return bool(isinstance(features, Mapping) and features.get(APP_ENTITLEMENTS_FEATURE) is True)


def registered_app_entitlement_keys() -> tuple[str, ...]:
    """Return keys declared by the immutable built-in manifest registry.

    Historical business keys remain first so gate-off payloads keep their
    exact order. Extra keys follow deterministically and require no database
    constraint migration when a new manifest version is checked in.
    """

    # Local import avoids making the foundational manifest compiler depend on
    # the membership entitlement service during module initialization.
    from app.services.workspace_app_manifests import BUILTIN_WORKSPACE_APP_MANIFESTS

    declared = {
        key
        for manifest in BUILTIN_WORKSPACE_APP_MANIFESTS.values()
        for key in manifest.as_dict()["entitlement_keys"]
    }
    return (*BUSINESS_APP_KEYS, *sorted(declared - _BUSINESS_APP_KEY_SET))


def normalize_app_entitlements(
    app_keys: Iterable[str] | None,
    *,
    allowed_keys: Iterable[str] | None = None,
) -> list[str]:
    """Validate, de-duplicate and canonically order application identifiers.

    By default the trust set is the checked-in manifest registry plus the four
    historical keys. Mutation paths may pass the entitlement keys from the
    apps effectively installed in one workspace for a stricter tenant gate.
    """

    if app_keys is None:
        return []
    allowed_source = (
        registered_app_entitlement_keys() if allowed_keys is None else allowed_keys
    )
    allowed = tuple(dict.fromkeys(allowed_source))
    allowed_set = frozenset(allowed)
    normalized: set[str] = set()
    for raw in app_keys:
        if not isinstance(raw, str):
            raise ValueError("Application entitlement keys must be strings")
        key = raw.strip()
        if _APP_ENTITLEMENT_KEY_RE.fullmatch(key) is None:
            raise ValueError(f"Invalid application entitlement: {key or '<empty>'}")
        if key not in allowed_set:
            raise ValueError(f"Unknown application entitlement: {key or '<empty>'}")
        normalized.add(key)
    return [key for key in allowed if key in normalized]


def _effective_workspace_entitlement_keys(
    db: DBSession,
    membership: WorkspaceMember,
) -> tuple[str, ...]:
    workspace = db.query(Workspace).filter(Workspace.id == membership.workspace_id).one_or_none()
    if workspace is None:
        raise ValueError("Workspace membership has no tenant")
    from app.services.workspace_app_runtime import (
        WorkspaceAppRuntimeError,
        installed_entitlement_keys,
        workspace_app_platform_enabled,
    )

    if not workspace_app_platform_enabled(workspace):
        return BUSINESS_APP_KEYS
    try:
        installed = installed_entitlement_keys(workspace, db=db)
    except WorkspaceAppRuntimeError as exc:
        raise ValueError("Installed Workspace App entitlement state is invalid") from exc
    registered_order = registered_app_entitlement_keys()
    return tuple(key for key in registered_order if key in installed)


def list_member_app_entitlements(
    db: DBSession,
    membership: WorkspaceMember,
) -> list[str]:
    """Return only registered application keys in their stable UI order."""

    try:
        allowed = _effective_workspace_entitlement_keys(db, membership)
    except ValueError:
        # Runtime drift must never turn an opaque or stale grant into visible
        # application access. Administrators can still repair the installation
        # state through the dedicated governance surface.
        return []
    rows = (
        db.query(WorkspaceMemberAppEntitlement.app_key)
        .filter(
            WorkspaceMemberAppEntitlement.workspace_member_id == membership.id,
            WorkspaceMemberAppEntitlement.app_key.in_(allowed),
        )
        .all()
        if allowed
        else []
    )
    granted = {str(row[0]) for row in rows}
    return [key for key in allowed if key in granted]


def member_has_app_entitlement(
    db: DBSession,
    membership: WorkspaceMember,
    app_key: str,
) -> bool:
    """Check one explicit grant without granting on role or platform status."""

    normalized = normalize_app_entitlements([app_key])
    if not normalized:
        return False
    return (
        db.query(WorkspaceMemberAppEntitlement.id)
        .filter(
            WorkspaceMemberAppEntitlement.workspace_member_id == membership.id,
            WorkspaceMemberAppEntitlement.app_key == normalized[0],
        )
        .first()
        is not None
    )


def replace_member_app_entitlements(
    db: DBSession,
    membership: WorkspaceMember,
    app_keys: Iterable[str] | None,
    *,
    granted_by_user_id: str | None,
    grant_source: str = "member_admin_api",
) -> list[str]:
    """Replace one member's grants atomically within the caller transaction."""

    # An enabled Workspace App platform makes installed manifests the sole
    # entitlement vocabulary. Gate-off deliberately preserves the historical
    # four-key contract even if more manifests exist in the global registry.
    allowed = _effective_workspace_entitlement_keys(db, membership)
    requested = normalize_app_entitlements(app_keys, allowed_keys=allowed)
    requested_set = set(requested)
    existing = (
        db.query(WorkspaceMemberAppEntitlement)
        .filter(WorkspaceMemberAppEntitlement.workspace_member_id == membership.id)
        .all()
    )
    by_key = {row.app_key: row for row in existing}

    for row in existing:
        if row.app_key not in requested_set:
            db.delete(row)

    now = datetime.utcnow()
    for app_key in requested:
        if app_key in by_key:
            continue
        db.add(
            WorkspaceMemberAppEntitlement(
                workspace_member_id=membership.id,
                app_key=app_key,
                granted_at=now,
                granted_by_user_id=granted_by_user_id,
                grant_source=grant_source,
            )
        )
    db.flush()
    return requested
