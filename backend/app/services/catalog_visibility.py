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
    # ``allowed_industries`` is inferred from the workspace family until an
    # admin states it. A curation surface must be able to say which of the two
    # it is displaying, or the admin cannot tell a decision from a default.
    industries_configured: bool = False

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

    # A stored list is authoritative even when empty: an admin who allows no
    # industry must not silently get the inferred family defaults back.
    configured = catalog.get("allowed_industries")
    industries_configured = isinstance(configured, (list, tuple, set))
    allowed_industries = (
        _string_set(configured) if industries_configured
        else _string_set(configured) or _inferred_industries(workspace)
    )

    return WorkspaceCatalogPolicy(
        show_universal=_bool(catalog.get("show_universal"), True),
        show_unconfigured_industries=_bool(catalog.get("show_unconfigured_industries"), False),
        allowed_industries=allowed_industries,
        enabled_capabilities=_string_set(catalog.get("enabled_capabilities")),
        hidden_capabilities=_string_set(catalog.get("hidden_capabilities")),
        enabled_skills=_string_set(catalog.get("enabled_skills")),
        hidden_skills=_string_set(catalog.get("hidden_skills")),
        industries_configured=industries_configured,
    )


@dataclass(frozen=True)
class CapabilityVisibility:
    """Why one Capability is, or is not, on a workspace catalog surface.

    A Skill is invisible mostly because no visible Capability claims it, so
    explaining a Skill means explaining its carriers. ``reason`` is the stable
    machine code that names which lever governs this row:

    ``workspace_owned``        defined by this workspace
    ``enabled_override``       listed in ``settings.catalog.enabled_capabilities``
    ``universal``              universal tier, shown here
    ``industry_allowed``       industry tier, and the industry is allowed here
    ``industry_unconfigured``  shown because unconfigured industries are shown
    ``hidden_override``        listed in ``settings.catalog.hidden_capabilities``
    ``other_workspace``        defined by a different workspace
    ``universal_hidden``       universal tier, but this workspace hides universal
    ``industry_not_allowed``   industry tier, and the industry is not allowed here
    ``client_not_enabled``     global client/demo row, never implicit
    """

    visible: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"visible": self.visible, "reason": self.reason}


def capability_visibility(
    capability: Capability,
    workspace: Workspace,
    policy: WorkspaceCatalogPolicy | None = None,
) -> CapabilityVisibility:
    policy = policy or workspace_catalog_policy(workspace)
    slug = str(capability.slug or "")
    cap_id = str(capability.id or "")
    if slug in policy.hidden_capabilities or cap_id in policy.hidden_capabilities:
        return CapabilityVisibility(False, "hidden_override")
    if capability.workspace_id == workspace.id:
        return CapabilityVisibility(True, "workspace_owned")
    if capability.workspace_id is not None:
        return CapabilityVisibility(False, "other_workspace")
    if slug in policy.enabled_capabilities or cap_id in policy.enabled_capabilities:
        return CapabilityVisibility(True, "enabled_override")

    tier = str(capability.tier or "universal").lower()
    industry = str(capability.industry or "").lower()
    if tier == "universal":
        if policy.show_universal:
            return CapabilityVisibility(True, "universal")
        return CapabilityVisibility(False, "universal_hidden")
    if tier == "industry":
        if industry and industry in policy.allowed_industries:
            return CapabilityVisibility(True, "industry_allowed")
        if policy.show_unconfigured_industries:
            return CapabilityVisibility(True, "industry_unconfigured")
        return CapabilityVisibility(False, "industry_not_allowed")
    if tier == "client":
        # Global client/demo rows must be explicitly enabled for a workspace.
        return CapabilityVisibility(False, "client_not_enabled")
    return CapabilityVisibility(False, "unknown_tier")


def capability_is_visible(capability: Capability, workspace: Workspace, policy: WorkspaceCatalogPolicy | None = None) -> bool:
    return capability_visibility(capability, workspace, policy).visible


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


# Which lever closes the gap left by an invisible carrier. ``industry`` and
# ``universal`` are single tier decisions that move dozens of skills at once;
# ``capability`` names one row to enable or un-hide.
_LEVER_BY_CAPABILITY_REASON = {
    "industry_not_allowed": "industry",
    "universal_hidden": "universal",
    "hidden_override": "capability",
    "client_not_enabled": "capability",
    "unknown_tier": "capability",
}


@dataclass(frozen=True)
class CoverageGap:
    """A set of skills held back by one lever, and the lever's identity.

    ``lever`` is ``industry`` (allow ``key``), ``universal`` (show the
    universal tier), ``capability`` (enable or un-hide ``key``) or
    ``unclaimed`` — no capability reachable from this workspace claims these
    skills at all, so no tier decision will ever surface them.

    A skill blocked by several carriers appears under each lever that would
    surface it, because each answers "what shows up if I do this".
    """

    lever: str
    key: str
    skill_slugs: tuple[str, ...]
    capability_slugs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "lever": self.lever,
            "key": self.key,
            "skills": len(self.skill_slugs),
            "skill_slugs": list(self.skill_slugs),
            "capabilities": list(self.capability_slugs),
        }


@dataclass(frozen=True)
class CatalogOverride:
    """One entry of ``enabled_skills`` / ``hidden_skills``, and its worth.

    ``status`` is ``effective`` (removing it would change what this workspace
    sees), ``redundant`` (it agrees with what the catalog already decided, so
    it decides nothing) or ``dangling`` (no such skill in the registry).
    ``source`` names the enabled Workspace App that wrote the entry, or
    ``admin`` when curation is the only explanation for it.
    """

    kind: str
    entry: str
    slug: str
    name: str
    status: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "entry": self.entry,
            "slug": self.slug,
            "name": self.name,
            "status": self.status,
            "source": self.source,
        }


@dataclass(frozen=True)
class CategoryCoverage:
    category: str
    total: int
    visible: int

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "total": self.total, "visible": self.visible}


@dataclass(frozen=True)
class CatalogCoverage:
    """What this workspace sees of the Skill catalog, and why not the rest.

    The per-skill overrides are dormant in production while workspaces see a
    third of the registry, because visibility is not decided per skill: it is
    decided by which capabilities are visible and which skills they claim.
    This report ranks the levers by how many skills each one releases, so the
    overrides stay what they are — an escape hatch for the remainder.
    """

    policy: WorkspaceCatalogPolicy
    total: int
    visible: int
    filtered_reasons: dict[str, int]
    categories: tuple[CategoryCoverage, ...]
    gaps: tuple[CoverageGap, ...]
    overrides: tuple[CatalogOverride, ...]
    skills: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "total": self.total,
                "visible": self.visible,
                "filtered": self.total - self.visible,
                "filtered_reasons": dict(sorted(self.filtered_reasons.items())),
            },
            "policy": {
                **self.policy.to_dict(),
                "allowed_industries_source": (
                    "configured" if self.policy.industries_configured else "inferred"
                ),
            },
            "categories": [item.to_dict() for item in self.categories],
            "gaps": [gap.to_dict() for gap in self.gaps],
            "overrides": [override.to_dict() for override in self.overrides],
            "skills": list(self.skills),
        }


def catalog_coverage(
    *,
    workspace: Workspace,
    capabilities: Iterable[Capability],
    skills: Iterable[Skill],
    policy: WorkspaceCatalogPolicy | None = None,
    override_sources: dict[str, str] | None = None,
) -> CatalogCoverage:
    """Resolve the catalog surface and the lever behind every exclusion."""

    policy = policy or workspace_catalog_policy(workspace)
    sources = override_sources or {}
    cap_rows = list(capabilities)
    skill_rows = list(skills)

    cap_decisions = {
        str(cap.id): capability_visibility(cap, workspace, policy) for cap in cap_rows
    }
    visible_caps = [cap for cap in cap_rows if cap_decisions[str(cap.id)].visible]
    visible_skill_ids = visible_skill_ids_from_capabilities(visible_caps)
    visible_index = skill_capability_index(visible_caps)
    all_carriers: dict[str, list[Capability]] = {}
    for cap in cap_rows:
        for skill_id in cap.skill_ids or []:
            if skill_id:
                all_carriers.setdefault(str(skill_id), []).append(cap)

    visible_count = 0
    filtered_reasons: dict[str, int] = {}
    category_totals: dict[str, int] = {}
    category_visible: dict[str, int] = {}
    # (lever, key) -> (skill slugs, capability slugs)
    gap_skills: dict[tuple[str, str], set[str]] = {}
    gap_caps: dict[tuple[str, str], set[str]] = {}
    rows: list[dict[str, Any]] = []

    for skill in skill_rows:
        decision = skill_visibility(
            skill,
            workspace,
            visible_skill_ids,
            policy,
            capability_index=visible_index,
        )
        slug = str(skill.slug or "")
        category = str(skill.category or "Other")
        category_totals[category] = category_totals.get(category, 0) + 1
        carriers = all_carriers.get(str(skill.id), [])
        if decision.visible:
            visible_count += 1
            category_visible[category] = category_visible.get(category, 0) + 1
        else:
            filtered_reasons[decision.reason] = filtered_reasons.get(decision.reason, 0) + 1
        if decision.reason == "no_visible_capability":
            for lever, key, cap_slug in _levers_for(carriers, cap_decisions):
                gap_skills.setdefault((lever, key), set()).add(slug)
                if cap_slug:
                    gap_caps.setdefault((lever, key), set()).add(cap_slug)
        rows.append(
            {
                "slug": slug,
                "name": skill.name,
                "category": category,
                **decision.to_dict(),
                "carriers": sorted(
                    {str(cap.slug or cap.id or "") for cap in carriers}
                ),
            }
        )

    gaps = tuple(
        sorted(
            (
                CoverageGap(
                    lever=lever,
                    key=key,
                    skill_slugs=tuple(sorted(slugs)),
                    capability_slugs=tuple(sorted(gap_caps.get((lever, key), set()))),
                )
                for (lever, key), slugs in gap_skills.items()
            ),
            key=lambda gap: (-len(gap.skill_slugs), gap.lever, gap.key),
        )
    )
    categories = tuple(
        CategoryCoverage(category, total, category_visible.get(category, 0))
        for category, total in sorted(category_totals.items())
    )
    return CatalogCoverage(
        policy=policy,
        total=len(skill_rows),
        visible=visible_count,
        filtered_reasons=filtered_reasons,
        categories=categories,
        gaps=gaps,
        overrides=_audit_overrides(
            policy,
            skill_rows,
            workspace=workspace,
            visible_skill_ids=visible_skill_ids,
            sources=sources,
        ),
        skills=tuple(rows),
    )


def _levers_for(
    carriers: Iterable[Capability],
    cap_decisions: dict[str, CapabilityVisibility],
) -> list[tuple[str, str, str]]:
    """Map a skill's invisible carriers to the levers that would surface it."""

    levers: list[tuple[str, str, str]] = []
    for cap in carriers:
        decision = cap_decisions[str(cap.id)]
        lever = _LEVER_BY_CAPABILITY_REASON.get(decision.reason)
        if lever is None:
            # ``other_workspace`` carriers can never be reached from here.
            continue
        cap_slug = str(cap.slug or cap.id or "")
        industry = str(cap.industry or "").lower()
        if lever == "industry" and not industry:
            # Nothing to allow: the row itself has to be enabled by name.
            lever = "capability"
        if lever == "industry":
            key = industry
        elif lever == "universal":
            key = ""
        else:
            key = cap_slug
        levers.append((lever, key, cap_slug))
    if not levers:
        return [("unclaimed", "", "")]
    return levers


def _audit_overrides(
    policy: WorkspaceCatalogPolicy,
    skills: Iterable[Skill],
    *,
    workspace: Workspace,
    visible_skill_ids: set[str],
    sources: dict[str, str],
) -> tuple[CatalogOverride, ...]:
    by_key: dict[str, Skill] = {}
    for skill in skills:
        by_key[str(skill.slug or "").lower()] = skill
        by_key[str(skill.id or "").lower()] = skill

    out: list[CatalogOverride] = []
    for kind, entries in (("enabled", policy.enabled_skills), ("hidden", policy.hidden_skills)):
        for entry in sorted(entries):
            skill = by_key.get(entry)
            if skill is None:
                status, slug, name = "dangling", entry, ""
            else:
                slug = str(skill.slug or "")
                name = str(skill.name or "")
                # Would the row be visible if this entry were removed?
                otherwise_visible = (
                    skill.workspace_id == workspace.id
                    or str(skill.id) in visible_skill_ids
                    or (
                        kind == "hidden"
                        and (slug in policy.enabled_skills or str(skill.id) in policy.enabled_skills)
                    )
                )
                effective = otherwise_visible if kind == "hidden" else not otherwise_visible
                status = "effective" if effective else "redundant"
            out.append(
                CatalogOverride(
                    kind=kind,
                    entry=entry,
                    slug=slug,
                    name=name,
                    status=status,
                    source=sources.get(slug) or sources.get(entry) or "admin",
                )
            )
    return tuple(out)


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
