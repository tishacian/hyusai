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

    def to_dict(self) -> dict[str, Any]:
        """The levers a workspace admin can act on, in a stable order."""

        return {
            "show_universal": self.show_universal,
            "show_unconfigured_industries": self.show_unconfigured_industries,
            "allowed_industries": sorted(self.allowed_industries),
            "enabled_capabilities": sorted(self.enabled_capabilities),
            "hidden_capabilities": sorted(self.hidden_capabilities),
            "enabled_skills": sorted(self.enabled_skills),
            "hidden_skills": sorted(self.hidden_skills),
        }


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


def skill_capability_index(capabilities: Iterable[Capability]) -> dict[str, tuple[str, ...]]:
    """Map each skill id to the capability slugs that carry it."""

    index: dict[str, list[str]] = {}
    for cap in capabilities:
        cap_slug = str(cap.slug or cap.id or "")
        for skill_id in cap.skill_ids or []:
            if skill_id:
                index.setdefault(str(skill_id), []).append(cap_slug)
    return {skill_id: tuple(sorted(set(slugs))) for skill_id, slugs in index.items()}


@dataclass(frozen=True)
class SkillVisibility:
    """Why one Skill is, or is not, part of a workspace catalog surface.

    A workspace routinely sees half of the global registry. The rule that
    produces that number is stable, but it was invisible to the product, so
    the missing entries read as arbitrary. ``reason`` is the stable machine
    code a client surface can turn into a sentence:

    ``workspace_owned``         defined by this workspace
    ``enabled_override``        listed in ``settings.catalog.enabled_skills``
    ``capability``              carried by a capability visible here
    ``hidden_override``         listed in ``settings.catalog.hidden_skills``
    ``other_workspace``         defined by a different workspace
    ``no_visible_capability``   global, but no visible capability carries it
    """

    visible: bool
    reason: str
    capability_slugs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "visible": self.visible,
            "reason": self.reason,
            "capabilities": list(self.capability_slugs),
        }


def skill_visibility(
    skill: Skill,
    workspace: Workspace,
    visible_skill_ids: set[str],
    policy: WorkspaceCatalogPolicy | None = None,
    *,
    capability_index: dict[str, tuple[str, ...]] | None = None,
) -> SkillVisibility:
    policy = policy or workspace_catalog_policy(workspace)
    slug = str(skill.slug or "")
    skill_id = str(skill.id or "")
    carriers = (capability_index or {}).get(skill_id, ())
    if slug in policy.hidden_skills or skill_id in policy.hidden_skills:
        return SkillVisibility(False, "hidden_override")
    if skill.workspace_id == workspace.id:
        return SkillVisibility(True, "workspace_owned")
    if skill.workspace_id is not None:
        return SkillVisibility(False, "other_workspace")
    if slug in policy.enabled_skills or skill_id in policy.enabled_skills:
        return SkillVisibility(True, "enabled_override", carriers)
    if skill_id in visible_skill_ids:
        return SkillVisibility(True, "capability", carriers)
    return SkillVisibility(False, "no_visible_capability")


def skill_is_visible(
    skill: Skill,
    workspace: Workspace,
    visible_skill_ids: set[str],
    policy: WorkspaceCatalogPolicy | None = None,
) -> bool:
    return skill_visibility(skill, workspace, visible_skill_ids, policy).visible


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

    from app.services.workspace_features import workspace_family

    family = workspace_family(workspace)
    if family == "sentinel_ci":
        return {"government"}
    if family == "andritz":
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
