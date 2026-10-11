"""An exclusion is three problems with three different fixes.

Reported as one, it reads as a per-skill problem and is not one. Andritz sees
28 of 85 skills: 36 of the missing ones are held by government capabilities it
does not allow, 9 by regulated_translation, and 12 are claimed by no
capability at all. Two decisions move 45 skills; the per-skill overrides can
only ever move the 12. This pins that decomposition, because it is the whole
argument for ranking levers instead of listing toggles.
"""
from __future__ import annotations

from app.models.capability import Capability
from app.models.skill import Skill
from app.models.workspace import Workspace
from app.services.catalog_visibility import (
    capability_visibility,
    catalog_coverage,
    workspace_catalog_policy,
)


def _workspace(slug: str, *, settings: dict | None = None) -> Workspace:
    return Workspace(id=f"ws-{slug}", slug=slug, name=slug.title(), settings=settings or {})


def _cap(slug, *, tier="universal", industry=None, workspace_id=None, skill_ids=()):
    return Capability(
        id=f"cap-{slug}",
        slug=slug,
        name=slug.replace("_", " ").title(),
        tier=tier,
        industry=industry,
        workspace_id=workspace_id,
        skill_ids=list(skill_ids),
    )


def _skill(slug, *, category="Analysis", workspace_id=None):
    return Skill(
        id=f"skill-{slug}",
        slug=slug,
        name=slug.replace("_", " ").title(),
        category=category,
        workspace_id=workspace_id,
    )


def _gaps(coverage) -> dict[tuple[str, str], tuple[str, ...]]:
    return {(gap.lever, gap.key): gap.skill_slugs for gap in coverage.gaps}


def test_one_reason_code_resolves_into_the_levers_that_close_it():
    workspace = _workspace("andritz", settings={"family": "andritz"})
    universal = _skill("expert_answer_v1")
    government = _skill("mission_command_v1")
    translation = _skill("certified_translation_v1")
    unclaimed = _skill("causal_drill_v1")
    capabilities = [
        _cap("expert_capture", skill_ids=[universal.id]),
        _cap("aya_voice", tier="industry", industry="government", skill_ids=[government.id]),
        _cap(
            "regulated_translation",
            tier="industry",
            industry="regulated_translation",
            skill_ids=[translation.id],
        ),
    ]

    coverage = catalog_coverage(
        workspace=workspace,
        capabilities=capabilities,
        skills=[universal, government, translation, unclaimed],
    )

    assert coverage.visible == 1
    # The row states its own lever, so the histogram already decomposes.
    assert coverage.filtered_reasons == {"industry_not_allowed": 2, "unclaimed": 1}
    assert _gaps(coverage) == {
        ("industry", "government"): ("mission_command_v1",),
        ("industry", "regulated_translation"): ("certified_translation_v1",),
        ("unclaimed", ""): ("causal_drill_v1",),
    }


def test_gaps_are_ranked_by_how_many_skills_the_lever_releases():
    """An admin should read the two decisions worth 45 skills before the
    twelve rows only an override can reach."""

    workspace = _workspace("andritz", settings={"family": "andritz"})
    government = [_skill(f"gov_{index}_v1") for index in range(4)]
    legal = [_skill("legal_v1")]
    unclaimed = [_skill("orphan_v1"), _skill("orphan_2_v1")]
    capabilities = [
        _cap("aya", tier="industry", industry="government", skill_ids=[s.id for s in government]),
        _cap("legal", tier="industry", industry="legal", skill_ids=[s.id for s in legal]),
    ]

    coverage = catalog_coverage(
        workspace=workspace,
        capabilities=capabilities,
        skills=[*government, *legal, *unclaimed],
    )

    assert [(gap.lever, gap.key, len(gap.skill_slugs)) for gap in coverage.gaps] == [
        ("industry", "government", 4),
        ("unclaimed", "", 2),
        ("industry", "legal", 1),
    ]
    assert coverage.gaps[0].capability_slugs == ("aya",)


def test_a_skill_two_carriers_hold_back_is_offered_under_both_levers():
    """Each gap answers "what appears if I do this", so the same skill counts
    for every lever that would surface it."""

    workspace = _workspace("andritz", settings={"family": "andritz"})
    shared = _skill("shared_v1")
    capabilities = [
        _cap("gov", tier="industry", industry="government", skill_ids=[shared.id]),
        _cap("hidden_universal", skill_ids=[shared.id]),
    ]
    workspace.settings = {
        "family": "andritz",
        "catalog": {"hidden_capabilities": ["hidden_universal"]},
    }

    coverage = catalog_coverage(workspace=workspace, capabilities=capabilities, skills=[shared])

    assert _gaps(coverage) == {
        ("industry", "government"): ("shared_v1",),
        ("capability", "hidden_universal"): ("shared_v1",),
    }
    assert coverage.total - coverage.visible == 1


def test_hiding_the_universal_tier_is_reported_as_its_own_lever():
    workspace = _workspace("andritz", settings={"catalog": {"show_universal": False}})
    skill = _skill("expert_answer_v1")

    coverage = catalog_coverage(
        workspace=workspace,
        capabilities=[_cap("expert_capture", skill_ids=[skill.id])],
        skills=[skill],
    )

    assert _gaps(coverage) == {("universal", ""): ("expert_answer_v1",)}


def test_a_carrier_owned_by_another_workspace_is_never_a_lever():
    """Nothing an admin can toggle here reaches it, so it belongs with the
    unclaimed rows rather than promising a fix that does not exist."""

    workspace = _workspace("andritz")
    skill = _skill("foreign_carried_v1")
    foreign = _cap("sentinel_only", workspace_id="ws-sentinel-ci", skill_ids=[skill.id])

    coverage = catalog_coverage(workspace=workspace, capabilities=[foreign], skills=[skill])

    assert _gaps(coverage) == {("unclaimed", ""): ("foreign_carried_v1",)}


def test_coverage_by_category_reports_what_the_workspace_can_actually_do():
    workspace = _workspace("andritz", settings={"family": "andritz"})
    seen = _skill("retrieve_v1", category="Retrieval")
    unseen = _skill("classify_v1", category="Analysis")

    coverage = catalog_coverage(
        workspace=workspace,
        capabilities=[_cap("expert_capture", skill_ids=[seen.id])],
        skills=[seen, unseen],
    )

    assert [item.to_dict() for item in coverage.categories] == [
        {"category": "Analysis", "total": 1, "visible": 0},
        {"category": "Retrieval", "total": 1, "visible": 1},
    ]


def test_an_override_is_reported_as_effective_redundant_or_dangling():
    """`enabled_skills` is the only lever production actually carries, and it
    was written by an app. An admin must be able to tell which entries still
    decide anything."""

    workspace = _workspace(
        "nawa",
        settings={
            "catalog": {
                "enabled_skills": ["rpa_dispatch_v1", "already_carried_v1", "typo_v1"],
                "hidden_skills": ["retired_v1"],
            }
        },
    )
    dispatched = _skill("rpa_dispatch_v1")
    carried = _skill("already_carried_v1")
    retired = _skill("retired_v1")

    coverage = catalog_coverage(
        workspace=workspace,
        capabilities=[_cap("universal", skill_ids=[carried.id, retired.id])],
        skills=[dispatched, carried, retired],
        override_sources={"rpa_dispatch_v1": "app:rpa_bridge"},
    )

    assert [
        (item.kind, item.slug, item.status, item.source) for item in coverage.overrides
    ] == [
        ("enabled", "already_carried_v1", "redundant", "admin"),
        ("enabled", "rpa_dispatch_v1", "effective", "app:rpa_bridge"),
        ("enabled", "typo_v1", "dangling", "admin"),
        ("hidden", "retired_v1", "effective", "admin"),
    ]


def test_hiding_what_is_already_invisible_is_reported_as_deciding_nothing():
    """The screen will create these entries, so it has to be able to say which
    of them actually retires a skill."""

    workspace = _workspace(
        "andritz",
        settings={"catalog": {"hidden_skills": ["carried_v1", "never_carried_v1", "owned_v1"]}},
    )
    carried = _skill("carried_v1")
    never_carried = _skill("never_carried_v1")
    owned = _skill("owned_v1", workspace_id=workspace.id)

    coverage = catalog_coverage(
        workspace=workspace,
        capabilities=[_cap("universal", skill_ids=[carried.id])],
        skills=[carried, never_carried, owned],
        override_sources={},
    )

    assert [(item.slug, item.status) for item in coverage.overrides] == [
        ("carried_v1", "effective"),
        # No capability claims it, so the hide changes nothing.
        ("never_carried_v1", "redundant"),
        # A workspace's own Skill is visible by default, so the hide retires it.
        ("owned_v1", "effective"),
    ]


def test_an_explicitly_empty_industry_list_is_a_decision_not_an_absence():
    """The family defaults are inferred only until an admin states otherwise;
    inferring them back would make the screen refuse to save."""

    inferred = _workspace("sentinel-ci", settings={"family": "sentinel_ci"})
    stated = _workspace(
        "sentinel-ci",
        settings={"family": "sentinel_ci", "catalog": {"allowed_industries": []}},
    )

    assert workspace_catalog_policy(inferred).allowed_industries == {"government"}
    assert workspace_catalog_policy(inferred).industries_configured is False
    assert workspace_catalog_policy(stated).allowed_industries == set()
    assert workspace_catalog_policy(stated).industries_configured is True


def test_a_missing_industry_key_still_infers_exactly_as_before():
    """The only behaviour that moves is a stored empty list, which nothing but
    the new write path can produce."""

    for stored in ({}, {"allowed_industries": None}, {"allowed_industries": ""}):
        workspace = _workspace("andritz", settings={"family": "andritz", "catalog": stored})
        assert workspace_catalog_policy(workspace).allowed_industries == {
            "manufacturing",
            "industrial",
            "process_industry",
            "pulp_paper",
        }


def _seeded_rows():
    """The shipped registry, without a database: coverage is pure."""

    from app.services.skills_registry.seed import (
        SEED_CAPABILITIES,
        SEED_SKILLS,
        SKILL_CATEGORIES,
    )

    skills = [
        Skill(
            id=f"skill-{entry['slug']}",
            slug=entry["slug"],
            name=entry["name"],
            category=SKILL_CATEGORIES.get(entry["slug"], "Other"),
        )
        for entry in SEED_SKILLS
    ]
    known = {skill.slug for skill in skills}
    capabilities = [
        Capability(
            id=f"cap-{entry['slug']}",
            slug=entry["slug"],
            name=entry["name"],
            tier=entry["tier"],
            industry=entry.get("industry"),
            skill_ids=[f"skill-{slug}" for slug in entry["skill_slugs"] if slug in known],
        )
        for entry in SEED_CAPABILITIES
    ]
    return capabilities, skills


def test_the_shipped_registry_hides_skills_by_tier_decision_not_by_curation():
    """The claim the whole surface rests on, checked against what we ship.

    The gaps partition the exclusions exactly — no skill in the shipped
    registry is held by two levers, so the counts can be read as a plan, and
    the reason each row states agrees with them. What an override can reach is
    a property of the registry rather than of the workspace: the same twelve
    unclaimed skills, whichever family asks. Industry decisions are what scale.
    """

    capabilities, skills = _seeded_rows()
    unclaimed_per_family = set()
    for family in ("andritz", "sentinel_ci"):
        workspace = _workspace(family, settings={"family": family})
        allowed = workspace_catalog_policy(workspace).allowed_industries

        coverage = catalog_coverage(
            workspace=workspace,
            capabilities=capabilities,
            skills=skills,
        )

        filtered = coverage.total - coverage.visible
        gaps = {(gap.lever, gap.key): len(gap.skill_slugs) for gap in coverage.gaps}
        assert sum(gaps.values()) == filtered
        assert set(gaps) == {
            ("industry", key)
            for key in ("government", "regulated_translation")
            if key not in allowed
        } | {("unclaimed", "")}
        assert coverage.filtered_reasons == {
            "industry_not_allowed": filtered - gaps[("unclaimed", "")],
            "unclaimed": gaps[("unclaimed", "")],
        }
        unclaimed_per_family.add(gaps[("unclaimed", "")])

    assert len(unclaimed_per_family) == 1, (
        "the rows only a per-skill override can reach must depend on the "
        "registry, not on which workspace is asking"
    )


def test_a_workspace_allowing_no_industry_is_mostly_fixed_by_allowing_one():
    """Andritz sees a third of the registry. Two tier decisions close most of
    that, and the per-skill overrides can only ever reach the remainder — so
    the screen ranks levers instead of listing 57 toggles."""

    capabilities, skills = _seeded_rows()
    workspace = _workspace("andritz", settings={"family": "andritz"})

    coverage = catalog_coverage(workspace=workspace, capabilities=capabilities, skills=skills)

    filtered = coverage.total - coverage.visible
    by_lever: dict[str, int] = {}
    for gap in coverage.gaps:
        by_lever[gap.lever] = by_lever.get(gap.lever, 0) + len(gap.skill_slugs)
    assert by_lever["industry"] > filtered / 2
    assert coverage.gaps[0].lever == "industry", "the ranking must lead with the tier decision"


def test_every_capability_states_why_it_is_or_is_not_visible():
    workspace = _workspace(
        "andritz",
        settings={
            "family": "andritz",
            "catalog": {
                "enabled_capabilities": ["finance_brief"],
                "hidden_capabilities": ["expert_capture"],
            },
        },
    )
    policy = workspace_catalog_policy(workspace)

    def _reason(cap):
        return capability_visibility(cap, workspace, policy).reason

    assert _reason(_cap("expert_capture")) == "hidden_override"
    assert _reason(_cap("owned", workspace_id=workspace.id)) == "workspace_owned"
    assert _reason(_cap("foreign", workspace_id="ws-other")) == "other_workspace"
    assert _reason(_cap("finance_brief", tier="industry", industry="finance")) == "enabled_override"
    assert _reason(_cap("universal_row")) == "universal"
    assert _reason(_cap("gov", tier="industry", industry="government")) == "industry_not_allowed"
    assert _reason(_cap("demo", tier="client")) == "client_not_enabled"
