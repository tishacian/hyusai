"""Authoritative tenant/catalog bindings for System authoring and runtime.

Capability and Skill rows deliberately live in a mixed registry: some rows
belong to one workspace while reusable catalog rows are global.  Two distinct
authority questions therefore exist and must not be conflated:

* discovery/create/import asks whether a row is visible in the workspace
  catalogue now (tier, industry and explicit catalogue configuration apply);
* runtime asks whether an already persisted System may execute its active
  binding (tenant lineage and explicit disables apply, but a later discovery
  filter must not silently revoke that binding).

The split is important for seeded business Systems.  For example, Andritz's
Client360 PDR uses a global client Capability and News Lab uses the global
finance Capability.  Their persisted bindings remain executable without
making those rows discoverable for new Andritz Systems.

The helpers are intentionally independent from FastAPI so API endpoints,
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


def _is_explicitly_disabled(
    *,
    row_id: str | None,
    slug: str | None,
    disabled: set[str],
) -> bool:
    """Return whether a catalogue override explicitly revokes one row."""

    keys = {
        str(value).strip().lower()
        for value in (row_id, slug)
        if value is not None and str(value).strip()
    }
    return bool(keys & disabled)


def _runtime_row_is_authorised(
    *,
    row_workspace_id: str | None,
    workspace: Workspace | None,
    row_id: str | None,
    slug: str | None,
    explicitly_disabled: set[str],
) -> bool:
    """Validate persisted binding lineage without re-running discovery rules.

    The persisted System foreign key (or its Capability fallback for Skills)
    is the active binding.  A row is executable only when it is global or
    owned by the same workspace, and an explicit ``hidden_*`` override always
    wins.  Tier/industry and ``enabled_*`` remain authoring concerns.
    """

    if _is_explicitly_disabled(
        row_id=row_id,
        slug=slug,
        disabled=explicitly_disabled,
    ):
        return False
    if workspace is None:
        return row_workspace_id is None
    return row_workspace_id in {None, workspace.id}


def _resolve_runtime_capability(
    db: DBSession,
    *,
    workspace: Workspace | None,
    capability_id: str | None,
) -> Capability | None:
    """Resolve the Capability actively bound to a persisted System."""

    if not capability_id:
        return None
    capability = db.query(Capability).filter(Capability.id == capability_id).first()
    if capability is None:
        raise SystemCatalogBindingError(
            "Persisted System Capability no longer exists",
            code="capability_not_visible",
            field="capability_id",
        )
    policy = workspace_catalog_policy(workspace) if workspace is not None else None
    if not _runtime_row_is_authorised(
        row_workspace_id=capability.workspace_id,
        workspace=workspace,
        row_id=capability.id,
        slug=capability.slug,
        explicitly_disabled=(policy.hidden_capabilities if policy is not None else set()),
    ):
        raise SystemCatalogBindingError(
            "Persisted System Capability is disabled or belongs to another workspace",
            code="capability_not_visible",
            field="capability_id",
        )
    return capability


def _resolve_runtime_skills(
    db: DBSession,
    *,
    workspace: Workspace | None,
    skill_ids: tuple[str, ...],
) -> tuple[Skill, ...]:
    """Resolve Skills actively bound by the System or its Capability."""

    if not skill_ids:
        return ()
    rows = db.query(Skill).filter(Skill.id.in_(skill_ids)).all()
    by_id = {str(row.id): row for row in rows}
    policy = workspace_catalog_policy(workspace) if workspace is not None else None
    ordered: list[Skill] = []
    for skill_id in skill_ids:
        skill = by_id.get(skill_id)
        if skill is None:
            raise SystemCatalogBindingError(
                "Persisted System Skill no longer exists",
                code="skill_not_visible",
                field="skill_ids",
            )
        if not _runtime_row_is_authorised(
            row_workspace_id=skill.workspace_id,
            workspace=workspace,
            row_id=skill.id,
            slug=skill.slug,
            explicitly_disabled=(policy.hidden_skills if policy is not None else set()),
        ):
            raise SystemCatalogBindingError(
                "Persisted System Skill is disabled or belongs to another workspace",
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
    """Resolve a complete prospective authoring binding or raise safely.

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


def _validate_persisted_system_workspace(
    *,
    workspace: Workspace | None,
    system: System,
) -> None:
    expected_workspace_id = workspace.id if workspace is not None else None
    if system.workspace_id != expected_workspace_id:
        raise SystemCatalogBindingError(
            "System must belong to the current workspace",
            code="system_workspace_mismatch",
            field="workspace_id",
        )


def resolve_persisted_system_authoring_bindings(
    db: DBSession,
    *,
    workspace: Workspace | None,
    system: System,
) -> ResolvedSystemCatalogBindings:
    """Revalidate a persisted row for Blueprint reuse/edit authoring.

    This deliberately retains discovery visibility semantics.  It must not be
    used by execution paths; those use
    :func:`resolve_persisted_system_catalog_bindings` below.
    """

    _validate_persisted_system_workspace(workspace=workspace, system=system)
    return resolve_system_catalog_bindings(
        db,
        workspace=workspace,
        system_id=system.id,
        capability_id=system.capability_id,
        skill_ids=system.skill_ids,
        adaptive_policy_id=system.adaptive_policy_id,
    )


def resolve_persisted_system_catalog_bindings(
    db: DBSession,
    *,
    workspace: Workspace | None,
    system: System,
) -> ResolvedSystemCatalogBindings:
    """Resolve the active execution contract of a persisted System.

    Runtime never re-applies tier or industry discovery filters.  It still
    fails closed on tenant lineage, missing rows, explicit catalogue disables
    and AdaptivePolicy ownership/scope.
    """

    _validate_persisted_system_workspace(workspace=workspace, system=system)
    capability = _resolve_runtime_capability(
        db,
        workspace=workspace,
        capability_id=system.capability_id,
    )
    explicit_skill_ids = _normalise_ids(system.skill_ids)
    effective_skill_ids = explicit_skill_ids or _normalise_ids(
        capability.skill_ids if capability is not None else None
    )
    skills = _resolve_runtime_skills(
        db,
        workspace=workspace,
        skill_ids=effective_skill_ids,
    )
    adaptive_policy = _resolve_adaptive_policy(
        db,
        workspace=workspace,
        system_id=system.id,
        capability_id=system.capability_id,
        adaptive_policy_id=system.adaptive_policy_id,
    )
    return ResolvedSystemCatalogBindings(
        capability=capability,
        skills=skills,
        effective_skill_ids=effective_skill_ids,
        adaptive_policy=adaptive_policy,
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
    "resolve_persisted_system_authoring_bindings",
    "resolve_persisted_system_catalog_bindings",
    "resolve_run_system_catalog_bindings",
    "resolve_system_catalog_bindings",
]
