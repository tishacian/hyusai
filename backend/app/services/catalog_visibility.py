"""Workspace-scoped visibility rules for Capabilities and Skills.

The registry is intentionally global: Agentium can seed reusable universal,
industry and demo capabilities once. The product surface, however, must be
workspace-scoped so an Andritz operator does not browse SENTINEL-CI government
building blocks, and vice versa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.models.capability import Capability
from app.models.skill import Skill
from app.models.workspace import Workspace


@dataclass(frozen=True)
class WorkspaceCatalogPolicy:
    show_universal: bool = True
    show_unconfigured_industries: bool = False
    allowed_industries: set[str] = field(default_factory=set)
    enabled_capabilities: set[str] = field(default_factory=set)
    hidden_capabilities: set[str] = field(default_factory=set)
    enabled_skills: set[str] = field(default_factory=set)
    hidden_skills: set[str] = field(default_factory=set)


def workspace_catalog_policy(workspace: Workspace) -> WorkspaceCatalogPolicy:
    """Resolve catalog visibility for one workspace.

    Preferred configuration lives in ``workspace.settings.catalog``:

    ``allowed_industries``: explicit industry slugs such as ``government``.
    ``enabled_capabilities`` / ``hidden_capabilities``: slug overrides.
    ``enabled_skills`` / ``hidden_skills``: skill slug overrides.

    When no explicit industries are configured we infer only well-known demo
    defaults. This keeps legacy workspaces usable while preventing broad
    cross-workspace leakage of industry-specific demo surfaces.
    """

    settings = workspace.settings or {}
    catalog = _as_dict(settings.get("catalog") or settings.get("capability_catalog"))

    configured_industries = _string_set(catalog.get("allowed_industries"))
    allowed_industries = configured_industries or _inferred_industries(workspace)

    return WorkspaceCatalogPolicy(
        show_universal=_bool(catalog.get("show_universal"), True),
        show_unconfigured_industries=_bool(catalog.get("show_unconfigured_industries"), False),
        allowed_industries=allowed_industries,
        enabled_capabilities=_string_set(catalog.get("enabled_capabilities")),
        hidden_capabilities=_string_set(catalog.get("hidden_capabilities")),
        enabled_skills=_string_set(catalog.get("enabled_skills")),
        hidden_skills=_string_set(catalog.get("hidden_skills")),
    )


def capability_is_visible(capability: Capability, workspace: Workspace, policy: WorkspaceCatalogPolicy | None = None) -> bool:
    policy = policy or workspace_catalog_policy(workspace)
    slug = str(capability.slug or "")
    cap_id = str(capability.id or "")
    if slug in policy.hidden_capabilities or cap_id in policy.hidden_capabilities:
        return False
    if capability.workspace_id == workspace.id:
        return True
    if capability.workspace_id is not None:
        return False
    if slug in policy.enabled_capabilities or cap_id in policy.enabled_capabilities:
        return True

    tier = str(capability.tier or "universal").lower()
    industry = str(capability.industry or "").lower()
    if tier == "universal":
        return policy.show_universal
    if tier == "industry":
        return policy.show_unconfigured_industries or bool(industry and industry in policy.allowed_industries)
    if tier == "client":
        # Global client/demo rows must be explicitly enabled for a workspace.
        return False
    return False


def visible_capabilities(
    capabilities: Iterable[Capability],
    workspace: Workspace,
    policy: WorkspaceCatalogPolicy | None = None,
) -> list[Capability]:
    policy = policy or workspace_catalog_policy(workspace)
    return [cap for cap in capabilities if capability_is_visible(cap, workspace, policy)]


def visible_skill_ids_from_capabilities(capabilities: Iterable[Capability]) -> set[str]:
    skill_ids: set[str] = set()
    for cap in capabilities:
        for skill_id in cap.skill_ids or []:
            if skill_id:
                skill_ids.add(str(skill_id))
    return skill_ids


def skill_is_visible(
    skill: Skill,
    workspace: Workspace,
    visible_skill_ids: set[str],
    policy: WorkspaceCatalogPolicy | None = None,
) -> bool:
    policy = policy or workspace_catalog_policy(workspace)
    slug = str(skill.slug or "")
    skill_id = str(skill.id or "")
    if slug in policy.hidden_skills or skill_id in policy.hidden_skills:
        return False
    if skill.workspace_id == workspace.id:
        return True
    if skill.workspace_id is not None:
        return False
    if slug in policy.enabled_skills or skill_id in policy.enabled_skills:
        return True
    return str(skill.id) in visible_skill_ids


def visibility_label(capability: Capability, workspace: Workspace, policy: WorkspaceCatalogPolicy | None = None) -> str:
    """Small UI/debug label explaining why a visible capability is shown."""

    policy = policy or workspace_catalog_policy(workspace)
    slug = str(capability.slug or "")
    if capability.workspace_id == workspace.id:
        return "workspace"
    if slug in policy.enabled_capabilities:
        return "enabled"
    tier = str(capability.tier or "universal").lower()
    if tier == "universal":
        return "universal"
    if tier == "industry":
        return f"industry:{capability.industry or 'unknown'}"
    return tier or "catalog"


def _inferred_industries(workspace: Workspace) -> set[str]:
    settings = workspace.settings or {}
    declared = _string_set(settings.get("industries") or settings.get("industry"))
    if declared:
        return declared

    slug = (workspace.slug or "").lower()
    name = (workspace.name or "").lower()
    if slug == "sentinel-ci" or "sentinel" in slug or "sentinel" in name:
        return {"government"}
    if slug == "andritz" or "andritz" in slug or "andritz" in name:
        return {"manufacturing", "industrial", "process_industry", "pulp_paper"}
    return set()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {item.strip().lower() for item in value.split(",") if item.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return set()


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
