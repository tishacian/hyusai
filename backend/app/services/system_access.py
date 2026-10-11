"""Shared object-level read authorization for canonical Systems."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session as DBSession

from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.iam.decision_plane import (
    ActionResolution,
    emit_shadow_diff_summary,
    resolve_action,
)


def system_read_attrs(system: System) -> dict[str, str | None]:
    return {
        "system_id": system.id,
        "capability_id": system.capability_id,
    }


def resolve_system_read(
    db: DBSession,
    *,
    system: System,
    user: User,
    workspace: Workspace,
    legacy_allowed: bool = True,
    audit_shadow_diff: bool = True,
    audit_shadow_evidence: bool = True,
) -> ActionResolution:
    return resolve_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="read",
        legacy_allowed=legacy_allowed,
        resource_attrs=system_read_attrs(system),
        audit_shadow_diff=audit_shadow_diff,
        audit_shadow_evidence=audit_shadow_evidence,
    )


def readable_systems(
    db: DBSession,
    *,
    systems: Iterable[System],
    user: User,
    workspace: Workspace,
) -> list[System]:
    visible: list[System] = []
    resolutions: list[tuple[str, ActionResolution]] = []
    for system in systems:
        if system.workspace_id != workspace.id:
            continue
        resolution = resolve_system_read(
            db,
            system=system,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((system.id, resolution))
        if resolution.effective_allowed:
            visible.append(system)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="system",
        action="read",
        resolutions=resolutions,
    )
    return visible


__all__ = ["readable_systems", "resolve_system_read", "system_read_attrs"]
