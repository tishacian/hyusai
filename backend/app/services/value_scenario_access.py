"""Shared read authorization for authoritative value-loop scenarios."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from sqlalchemy.orm import Session as DBSession

from app.core.iam.dependencies import current_membership
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_OWNER,
    WORKSPACE_REVIEWER,
    WORKSPACE_VIEWER,
    normalize_role_template,
)
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.value_loop import ValueScenario
from app.models.workspace import Workspace
from app.services.iam.decision_plane import (
    ActionResolution,
    emit_shadow_diff_summary,
    resolve_action,
)
from app.services.run_access import resolve_run_read, run_is_visible
from app.services.system_access import resolve_system_read

ALL_MEMBER_ROLES = {
    WORKSPACE_VIEWER,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
}


def resolve_value_scenario_read(
    db: DBSession,
    *,
    scenario: ValueScenario,
    user: User,
    workspace: Workspace,
    audit_shadow_diff: bool = True,
    audit_shadow_evidence: bool = True,
) -> ActionResolution:
    membership = current_membership(db, user, workspace)
    role = (
        normalize_role_template(membership.role_template, membership.role)
        if membership is not None
        else ""
    )
    source_run = (
        db.query(Run)
        .filter(
            Run.id == scenario.source_run_id,
            Run.workspace_id == workspace.id,
            Run.system_id == scenario.system_id,
        )
        .one_or_none()
    )
    system = (
        db.query(System)
        .filter(
            System.id == scenario.system_id,
            System.workspace_id == workspace.id,
        )
        .one_or_none()
    )
    system_readable = bool(
        system is not None
        and resolve_system_read(
            db,
            system=system,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        ).effective_allowed
    )
    source_readable = bool(
        source_run is not None
        and run_is_visible(db, run=source_run, user=user, workspace=workspace)
        and resolve_run_read(
            db,
            run=source_run,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        ).effective_allowed
    )
    resolution = resolve_action(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="value_scenario",
        action="read",
        legacy_allowed=(
            role in ALL_MEMBER_ROLES and source_readable and system_readable
        ),
        resource_attrs={
            "scenario_id": scenario.id,
            "system_id": scenario.system_id,
            "run_id": scenario.source_run_id,
            "owner_user_id": (
                source_run.initiated_by_user_id if source_run is not None else None
            ),
        },
        audit_shadow_diff=audit_shadow_diff,
        audit_shadow_evidence=audit_shadow_evidence,
    )
    if resolution.effective_allowed and not system_readable:
        return replace(
            resolution,
            effective_allowed=False,
            mismatch=resolution.legacy_allowed,
            reason="composed_system_read_denied",
        )
    if resolution.effective_allowed and not source_readable:
        return replace(
            resolution,
            effective_allowed=False,
            mismatch=resolution.legacy_allowed,
            reason="composed_source_run_read_denied",
        )
    return resolution


def readable_value_scenarios(
    db: DBSession,
    *,
    scenarios: Iterable[ValueScenario],
    user: User,
    workspace: Workspace,
) -> list[ValueScenario]:
    visible: list[ValueScenario] = []
    resolutions: list[tuple[str, ActionResolution]] = []
    for scenario in scenarios:
        if scenario.workspace_id != workspace.id:
            continue
        resolution = resolve_value_scenario_read(
            db,
            scenario=scenario,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((scenario.id, resolution))
        if resolution.effective_allowed:
            visible.append(scenario)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="value_scenario",
        action="read",
        resolutions=resolutions,
    )
    return visible


__all__ = ["readable_value_scenarios", "resolve_value_scenario_read"]
