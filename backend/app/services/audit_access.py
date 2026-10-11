"""Canonical read authorization for workspace audit evidence."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session as DBSession

from app.core.iam.roles import WORKSPACE_REVIEWER, is_admin_template, normalize_role_template
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.decision_plane import ActionResolution, enforce_action, resolve_action


def _membership(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> WorkspaceMember | None:
    return (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .one_or_none()
    )


def legacy_audit_read_allowed(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> bool:
    """Governance audit has never been an ordinary contributor payload."""

    if getattr(user, "role", None) == "admin":
        return True
    membership = _membership(db, user=user, workspace=workspace)
    if membership is None:
        return False
    role = normalize_role_template(membership.role_template, membership.role)
    return role == WORKSPACE_REVIEWER or is_admin_template(role, membership.role)


def resolve_audit_read(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_attrs: dict | None = None,
    audit_shadow_diff: bool = True,
    audit_shadow_evidence: bool = True,
) -> ActionResolution:
    return resolve_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="audit_log",
        action="read",
        legacy_allowed=legacy_audit_read_allowed(db, user=user, workspace=workspace),
        resource_attrs=resource_attrs or {},
        audit_shadow_diff=audit_shadow_diff,
        audit_shadow_evidence=audit_shadow_evidence,
    )


def enforce_audit_read(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> ActionResolution:
    return enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="audit_log",
        action="read",
        legacy_allowed=legacy_audit_read_allowed(db, user=user, workspace=workspace),
        resource_attrs={"workspace_id": workspace.id},
    )


def readable_audit_logs(
    db: DBSession,
    *,
    logs: Iterable[AuditLog],
    user: User,
    workspace: Workspace,
) -> tuple[list[AuditLog], bool]:
    """Return authorized rows and whether existing evidence was restricted."""

    scoped = [row for row in logs if row.workspace_id == workspace.id]
    resolution = resolve_audit_read(
        db,
        user=user,
        workspace=workspace,
        resource_attrs={"workspace_id": workspace.id, "scope": "projection"},
    )
    if resolution.effective_allowed:
        return scoped, False
    return [], bool(scoped)


__all__ = [
    "enforce_audit_read",
    "legacy_audit_read_allowed",
    "readable_audit_logs",
    "resolve_audit_read",
]
