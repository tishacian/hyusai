"""The reconciliation suite belongs to a capability, not to nobody.

The four skills shipped as a set, were categorised, and were then claimed by no
``SEED_CAPABILITIES`` entry — so catalog visibility reported them ``unclaimed``
and the Flow palette grouped them under "No capability". Only a per-workspace
``enabled_skills`` override ever reached them, which is the escape hatch rather
than the rule. These tests pin the carrier: platform-level (universal tier, no
industry), so no workspace loses sight of a skill it can use today, and applied
idempotently against a database that already holds the skills.
"""
from __future__ import annotations

from app.models.capability import Capability
from app.models.skill import Skill
from app.models.workspace import Workspace
from app.services.catalog_visibility import catalog_coverage
from app.services.skills_registry.seed import (
    SEED_CAPABILITIES,
    SEED_SKILLS,
    SKILL_CATEGORIES,
    seed_skills_and_capabilities,
)

CARRIER = "document_reconciliation"
RECONCILIATION_SLUGS = (
    "spreadsheet_table_extract_v1",
    "invoice_document_extract_v1",
    "line_items_reconcile_v1",
    "reconciliation_report_v1",
)


def _carrier() -> dict:
    return next(entry for entry in SEED_CAPABILITIES if entry["slug"] == CARRIER)


def _shipped_rows():
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


def test_the_carrier_is_platform_level_so_no_workspace_is_excluded_by_tier():
    entry = _carrier()

    assert entry["tier"] == "universal"
    assert entry.get("industry") is None
    for slug in RECONCILIATION_SLUGS:
        assert slug in entry["skill_slugs"]


def test_the_four_skills_are_carried_wherever_the_universal_tier_is_shown():
    capabilities, skills = _shipped_rows()

    for family in ("andritz", "sentinel_ci", "nawa"):
        coverage = catalog_coverage(
            workspace=Workspace(
                id=f"ws-{family}",
                slug=family,
                name=family.title(),
                settings={"family": family},
            ),
            capabilities=capabilities,
            skills=skills,
        )
        rows = {row["slug"]: row for row in coverage.skills}
        for slug in RECONCILIATION_SLUGS:
            assert rows[slug]["visible"] is True, (family, slug)
            assert rows[slug]["reason"] == "capability", (family, slug)
            assert CARRIER in rows[slug]["capabilities"], (family, slug)
        assert not any(
            slug in gap.skill_slugs
            for gap in coverage.gaps
            for slug in RECONCILIATION_SLUGS
        )


def test_a_workspace_hiding_the_universal_tier_keeps_its_own_override():
    """The carrier widens visibility; it must not become the only path to it."""

    capabilities, skills = _shipped_rows()
    workspace = Workspace(
        id="ws-curated",
        slug="curated",
        name="Curated",
        settings={
            "catalog": {
                "show_universal": False,
                "enabled_skills": ["line_items_reconcile_v1"],
            }
        },
    )

    coverage = catalog_coverage(workspace=workspace, capabilities=capabilities, skills=skills)
    rows = {row["slug"]: row for row in coverage.skills}

    assert rows["line_items_reconcile_v1"]["reason"] == "enabled_override"
    assert rows["reconciliation_report_v1"]["reason"] == "universal_hidden"


def test_the_carrier_adopts_skills_a_live_database_already_holds(db_session):
    """Production ran the seeder before this capability existed, so the rows are
    there with ids of their own and the carrier has to pick those up."""

    existing = {
        slug: Skill(
            id=f"live-{index}",
            slug=slug,
            name=slug,
            type="analysis",
            is_seeded="Y",
        )
        for index, slug in enumerate(RECONCILIATION_SLUGS)
    }
    db_session.add_all(existing.values())
    db_session.commit()

    first = seed_skills_and_capabilities(db_session)
    carrier = db_session.query(Capability).filter(Capability.slug == CARRIER).one()

    assert first["capabilities_added"] >= 1
    assert set(existing[slug].id for slug in RECONCILIATION_SLUGS) <= set(carrier.skill_ids)
    assert carrier.is_seeded == "Y"

    second = seed_skills_and_capabilities(db_session)

    assert second["capabilities_added"] == 0
    assert db_session.query(Capability).filter(Capability.slug == CARRIER).count() == 1
    assert (
        db_session.query(Capability).filter(Capability.slug == CARRIER).one().skill_ids
        == carrier.skill_ids
    )
