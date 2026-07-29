"""Shared object-level read authorization for canonical Decisions.

Decision rows feed several read models.  Centralising their rollout decision
prevents Steer or Govern from becoming an authorization bypass and composes a
Run-scoped Decision with the effective visibility of its target Run.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.capability_access import readable_capabilities
from app.services.iam.decision_plane import emit_shadow_diff_summary, resolve_action
from app.services.run_access import readable_runs
from app.services.system_access import readable_systems


def decision_read_attrs(
    decision: Decision,
    *,
    target_run: Run | None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "decision_id": decision.id,
        "owner_user_id": (
            target_run.initiated_by_user_id if target_run is not None else None
        ),
    }
    if decision.scope == "run":
        attrs["run_id"] = decision.target_id
        if target_run is not None:
            attrs["system_id"] = target_run.system_id
            attrs["capability_id"] = target_run.capability_id
    elif decision.scope == "system":
        attrs["system_id"] = decision.target_id
    elif decision.scope == "capability":
        attrs["capability_id"] = decision.target_id
    return attrs


def readable_decisions(
    db: DBSession,
    *,
    decisions: Iterable[Decision],
    user: User,
    workspace: Workspace,
    visible_runs: Iterable[Run] | None = None,
) -> list[Decision]:
    """Filter Decisions through legacy visibility and authorization v2.

    ``visible_runs`` may be supplied by a projector that already passed its
    Run collection through :func:`readable_runs`.  When omitted, this helper
    resolves every referenced Run itself.  A Run-scoped Decision is always
    hidden when the target Run is missing, cross-tenant or not effectively
    readable, independently of the Decision candidate result.
    """

    scoped = [item for item in decisions if item.workspace_id == workspace.id]
    target_ids = {
        str(item.target_id)
        for item in scoped
        if item.scope == "run" and item.target_id
    }
    system_target_ids = {
        str(item.target_id)
        for item in scoped
        if item.scope == "system" and item.target_id
    }
    capability_target_ids = {
        str(item.target_id)
        for item in scoped
        if item.scope == "capability" and item.target_id
    }
    target_runs = (
        db.query(Run)
        .filter(Run.workspace_id == workspace.id, Run.id.in_(target_ids))
        .all()
        if target_ids
        else []
    )
    run_by_id = {item.id: item for item in target_runs}
    target_systems = (
        db.query(System)
        .filter(
            System.workspace_id == workspace.id,
            System.id.in_(system_target_ids),
        )
        .all()
        if system_target_ids
        else []
    )
    authorized_system_ids = {
        item.id
        for item in readable_systems(
            db,
            systems=target_systems,
            user=user,
            workspace=workspace,
        )
    }
    target_capabilities = (
        db.query(Capability)
        .filter(
            Capability.id.in_(capability_target_ids),
            (
                (Capability.workspace_id == workspace.id)
                | (Capability.workspace_id.is_(None))
            ),
        )
        .all()
        if capability_target_ids
        else []
    )
    authorized_capability_ids = {
        item.id
        for item in readable_capabilities(
            db,
            capabilities=target_capabilities,
            user=user,
            workspace=workspace,
        )
    }
    if visible_runs is None:
        authorized_run_ids = {
            item.id
            for item in readable_runs(
                db,
                runs=target_runs,
                user=user,
                workspace=workspace,
            )
        }
    else:
        authorized_run_ids = {
            item.id
            for item in visible_runs
            if item.workspace_id == workspace.id and item.id in target_ids
        }

    visible: list[Decision] = []
    resolutions = []
    for item in scoped:
        target_run = run_by_id.get(str(item.target_id)) if item.scope == "run" else None
        if item.scope == "run":
            target_visible = str(item.target_id) in authorized_run_ids
        elif item.scope == "system":
            target_visible = str(item.target_id) in authorized_system_ids
        elif item.scope == "capability":
            target_visible = str(item.target_id) in authorized_capability_ids
        else:
            target_visible = item.scope == "portfolio"
        resolution = resolve_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="decision",
            action="read",
            legacy_allowed=target_visible,
            resource_attrs=decision_read_attrs(item, target_run=target_run),
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((item.id, resolution))
        if target_visible and resolution.effective_allowed:
            visible.append(item)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="decision",
        action="read",
        resolutions=resolutions,
    )
    return visible
