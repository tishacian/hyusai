"""Shared object-level read authorization for canonical Capabilities."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.user import User
from app.models.workspace import Workspace
from app.services.iam.decision_plane import (
    ActionResolution,
    emit_shadow_diff_summary,
    resolve_action,
)


def resolve_capability_read(
    db: DBSession,
    *,
    capability: Capability,
    user: User,
    workspace: Workspace,
    audit_shadow_diff: bool = True,
    audit_shadow_evidence: bool = True,
) -> ActionResolution:
    return resolve_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capability",
        action="read",
        legacy_allowed=True,
        resource_attrs={"capability_id": capability.id},
        audit_shadow_diff=audit_shadow_diff,
        audit_shadow_evidence=audit_shadow_evidence,
    )


def readable_capabilities(
    db: DBSession,
    *,
    capabilities: Iterable[Capability],
    user: User,
    workspace: Workspace,
) -> list[Capability]:
    visible: list[Capability] = []
    resolutions: list[tuple[str, ActionResolution]] = []
    for capability in capabilities:
        resolution = resolve_capability_read(
            db,
            capability=capability,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((capability.id, resolution))
        if resolution.effective_allowed:
            visible.append(capability)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="capability",
        action="read",
        resolutions=resolutions,
    )
    return visible


__all__ = ["readable_capabilities", "resolve_capability_read"]
