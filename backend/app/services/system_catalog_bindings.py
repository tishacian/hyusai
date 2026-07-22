"""Authoritative tenant/catalog bindings for executable Systems.

Capability and Skill rows deliberately live in a mixed registry: some rows
belong to one workspace while reusable catalog rows are global.  A bare
foreign key is therefore not sufficient authority to attach a row to a
System.  This module resolves every executable catalog reference through the
same visibility policy used by the catalog APIs and validates the optional
AdaptivePolicy against the prospective System scope.

The helper is intentionally independent from FastAPI so API endpoints,
Blueprint apply and every runtime entry point can share the exact contract.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.policy import AdaptivePolicy
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.catalog_visibility import (
    WorkspaceCatalogPolicy,
    capability_is_visible,
    skill_is_visible,
    visible_capabilities,
    visible_skill_ids_from_capabilities,
    workspace_catalog_policy,
)


class SystemCatalogBindingError(ValueError):
    """A System reference is absent, invisible or scoped to another object."""

    def __init__(self, message: str, *, code: str, field: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True)
class ResolvedSystemCatalogBindings:
    """Rows authorised for one prospective or persisted System."""

    capability: Capability | None
    skills: tuple[Skill, ...]
    effective_skill_ids: tuple[str, ...]
    adaptive_policy: AdaptivePolicy | None


def _normalise_ids(values: Iterable[str] | None) -> tuple[str, ...]:
    """Materialise references without changing their persisted identity."""

    return tuple(str(raw) if raw is not None else "" for raw in values or ())


def _resolve_capability(
    db: DBSession,
    *,
    workspace: Workspace | None,
    capability_id: str | None,
) -> Capability | None:
    if not capability_id:
        return None
    capability = db.query(Capability).filter(Capability.id == capability_id).first()
    if capability is None:
        raise SystemCatalogBindingError(
            "Capability is not available in the current workspace catalog",
            code="capability_not_visible",
            field="capability_id",
        )
    if workspace is None:
        # Legacy unscoped tests/data have no tenant whose policy could grant a
        # workspace-owned row.  Only a genuinely global row is safe there.
        visible = capability.workspace_id is None
    else:
        visible = capability_is_visible(
            capability,
            workspace,
            workspace_catalog_policy(workspace),
        )
    if not visible:
        raise SystemCatalogBindingError(
            "Capability is not available in the current workspace catalog",
            code="capability_not_visible",
            field="capability_id",
        )
    return capability


def _visible_skill_context(
    db: DBSession,
    workspace: Workspace | None,
) -> tuple[set[str], WorkspaceCatalogPolicy | None]:
    if workspace is None:
        return set(), None
    policy = workspace_catalog_policy(workspace)
    candidates = (
        db.query(Capability)
        .filter(
            or_(
                Capability.workspace_id == workspace.id,
                Capability.workspace_id.is_(None),
            )
        )
        .all()
    )
    visible = visible_capabilities(candidates, workspace, policy)
    return visible_skill_ids_from_capabilities(visible), policy


def _resolve_skills(
    db: DBSession,
    *,
    workspace: Workspace | None,
    skill_ids: tuple[str, ...],
) -> tuple[Skill, ...]:
    if not skill_ids:
        return ()
    rows = db.query(Skill).filter(Skill.id.in_(skill_ids)).all()
    by_id = {str(row.id): row for row in rows}
    visible_skill_ids, policy = _visible_skill_context(db, workspace)
    ordered: list[Skill] = []
    for skill_id in skill_ids:
        skill = by_id.get(skill_id)
        if skill is None:
            raise SystemCatalogBindingError(
                "Skill is not available in the current workspace catalog",
                code="skill_not_visible",
                field="skill_ids",
            )
        if workspace is None:
            visible = skill.workspace_id is None
        else:
            visible = skill_is_visible(
                skill,
                workspace,
                visible_skill_ids,
                policy,
            )
        if not visible:
            raise SystemCatalogBindingError(
                "Skill is not available in the current workspace catalog",
                code="skill_not_visible",
                field="skill_ids",
            )
        ordered.append(skill)
    return tuple(ordered)


def _resolve_adaptive_policy(
    db: DBSession,
    *,
    workspace: Workspace | None,
    system_id: str | None,
    capability_id: str | None,
    adaptive_policy_id: str | None,
) -> AdaptivePolicy | None:
    if not adaptive_policy_id:
        return None
    workspace_id = workspace.id if workspace is not None else None
    policy = (
        db.query(AdaptivePolicy)
        .filter(
            AdaptivePolicy.id == adaptive_policy_id,
            AdaptivePolicy.workspace_id == workspace_id,
        )
        .first()
    )
    if policy is None:
        raise SystemCatalogBindingError(
            "AdaptivePolicy must belong to the current workspace",
            code="adaptive_policy_workspace_mismatch",
            field="adaptive_policy_id",
        )

    scope = str(policy.scope or "").strip().lower()
    target_id = str(policy.target_id) if policy.target_id is not None else None
    valid = False
    if scope == "":
        # Pre-scope policies were workspace-owned.  Keep them readable without
        # broadening them beyond that already validated owner.
        valid = True
    elif scope == "system":
        valid = bool(system_id and target_id == system_id)
    elif scope == "capability":
        valid = bool(capability_id and target_id == capability_id)
    elif scope == "portfolio":
        valid = target_id in {None, workspace_id}
    if not valid:
        raise SystemCatalogBindingError(
            "AdaptivePolicy scope does not match the prospective System",
            code="adaptive_policy_scope_mismatch",
            field="adaptive_policy_id",
        )
    return policy


def resolve_system_catalog_bindings(
    db: DBSession,
    *,
    workspace: Workspace | None,
    system_id: str | None,
    capability_id: str | None,
    skill_ids: Iterable[str] | None,
    adaptive_policy_id: str | None,
) -> ResolvedSystemCatalogBindings:
    """Resolve a complete prospective System binding or raise safely.

    An empty System ``skill_ids`` list has always meant "use the bound
    Capability's canonical skills" in the sequential engine.  The validator
    applies visibility to that effective fallback too, preventing a visible
    Capability from smuggling a hidden or foreign Skill into execution.
    """

    capability = _resolve_capability(
        db,
        workspace=workspace,
        capability_id=capability_id,
    )
    explicit_skill_ids = _normalise_ids(skill_ids)
    effective_skill_ids = explicit_skill_ids or _normalise_ids(
        capability.skill_ids if capability is not None else None
    )
    skills = _resolve_skills(
        db,
        workspace=workspace,
        skill_ids=effective_skill_ids,
    )
    adaptive_policy = _resolve_adaptive_policy(
        db,
        workspace=workspace,
        system_id=system_id,
        capability_id=capability_id,
        adaptive_policy_id=adaptive_policy_id,
    )
    return ResolvedSystemCatalogBindings(
        capability=capability,
        skills=skills,
        effective_skill_ids=effective_skill_ids,
        adaptive_policy=adaptive_policy,
    )


def resolve_persisted_system_catalog_bindings(
    db: DBSession,
    *,
    workspace: Workspace | None,
    system: System,
) -> ResolvedSystemCatalogBindings:
    """Runtime/Blueprint convenience wrapper for a persisted System."""

    expected_workspace_id = workspace.id if workspace is not None else None
    if system.workspace_id != expected_workspace_id:
        raise SystemCatalogBindingError(
            "System must belong to the current workspace",
            code="system_workspace_mismatch",
            field="workspace_id",
        )
    return resolve_system_catalog_bindings(
        db,
        workspace=workspace,
        system_id=system.id,
        capability_id=system.capability_id,
        skill_ids=system.skill_ids,
        adaptive_policy_id=system.adaptive_policy_id,
    )


def resolve_run_system_catalog_bindings(
    db: DBSession,
    *,
    workspace: Workspace | None,
    system: System,
    run: Run,
) -> ResolvedSystemCatalogBindings:
    """Validate the immutable Run→System tenant/catalog identity boundary."""

    if run.system_id != system.id or run.workspace_id != system.workspace_id:
        raise SystemCatalogBindingError(
            "Run and System must belong to the same workspace",
            code="run_system_workspace_mismatch",
            field="workspace_id",
        )
    if run.capability_id is not None and run.capability_id != system.capability_id:
        raise SystemCatalogBindingError(
            "Run capability does not match its System",
            code="run_system_capability_mismatch",
            field="capability_id",
        )
    return resolve_persisted_system_catalog_bindings(
        db,
        workspace=workspace,
        system=system,
    )


__all__ = [
    "ResolvedSystemCatalogBindings",
    "SystemCatalogBindingError",
    "resolve_persisted_system_catalog_bindings",
    "resolve_run_system_catalog_bindings",
    "resolve_system_catalog_bindings",
]
