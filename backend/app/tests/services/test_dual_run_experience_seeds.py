"""Lot 8 dual-run seeds: Andritz / Sentinel / Octocity / Mission Control."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa

from app.services.experience.dual_run_seeds import (
    repair_mutated_091_releases,
    seed_dual_run_experiences,
)
from app.services.experience.keys import (
    mission_nav_binding_key,
    ANDRITZ_FSE_KEY,
    ANDRITZ_RECHERCHE_KEY,
    CAPTURE_EXPERIENCE_SLUG,
    CLIENT360_EXPERIENCE_SLUG,
    FSE_EXPERIENCE_SLUG,
    MISSION_CONTROL_EXPERIENCE_SLUG,
    MISSION_INTELLIGENCE_KEY,
    OCTOCITY_EXPERIENCE_SLUG,
    OCTOCITY_INTELLIGENCE_KEY,
    RECHERCHE_EXPERIENCE_SLUG,
    SENTINEL_COCKPIT_KEY,
    SENTINEL_DECISIONS_KEY,
    SENTINEL_EXPERIENCE_SLUG,
    SENTINEL_INTELLIGENCE_KEY,
    SENTINEL_MAP_KEY,
)

FLOW_SHA = "a" * 64
INPUT_SHA = "b" * 64
CONTRACT = {
    "ingresses": [
        {
            "ingress_id": "source.request",
            "kind": "manual",
            "input_schema_sha256": INPUT_SHA,
            "input_schema": {"type": "object", "properties": {}},
        }
    ],
    "outputs": [],
}


def _schema(bind):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("settings", sa.JSON()),
    )
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("settings", sa.JSON()),
        sa.Column("flow_definition", sa.JSON()),
        sa.Column("published_flow_version_id", sa.String(36)),
    )
    versions = sa.Table(
        "system_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("flow_sha256", sa.String(64)),
        sa.Column("execution_contract", sa.JSON()),
    )
    bindings = sa.Table(
        "system_bindings",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("binding_key", sa.String(120), nullable=False),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("published_flow_version_id", sa.String(36), nullable=False),
        sa.Column("flow_sha256", sa.String(64), nullable=False),
        sa.Column("ingress_id", sa.String(160), nullable=False),
        sa.Column("input_schema_sha256", sa.String(64), nullable=False),
        sa.Column("output_schema_sha256", sa.String(64)),
        sa.Column("confirmation_policy", sa.String(32), nullable=False),
        sa.Column("on_unavailable", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "binding_key"),
    )
    experiences = sa.Table(
        "experiences",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("pattern", sa.String(32), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("theme", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "slug"),
    )
    drafts = sa.Table(
        "experience_draft_revisions",
        metadata,
        sa.Column("experience_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("binding_keys", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    releases = sa.Table(
        "experience_releases",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experience_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("release_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("bindings_snapshot", sa.JSON(), nullable=False),
        sa.Column("access_snapshot", sa.JSON(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("theme", sa.JSON(), nullable=False),
        sa.Column("renderer_version", sa.String(80), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    deployments = sa.Table(
        "experience_deployments",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experience_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("previous_release_id", sa.String(36)),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    metadata.create_all(bind)
    return workspaces, systems, versions, bindings, experiences, drafts, releases, deployments


@pytest.fixture()
def bind():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        yield connection


def _insert_workspace(bind, workspaces, *, workspace_id, slug, settings=None):
    bind.execute(
        workspaces.insert(),
        {"id": workspace_id, "slug": slug, "settings": settings or {}},
    )


def _insert_published_system(
    bind,
    systems,
    versions,
    *,
    system_id,
    workspace_id,
    name,
    version_id=None,
    settings=None,
    flow_definition=None,
):
    version_id = version_id or str(uuid4())
    bind.execute(
        systems.insert(),
        {
            "id": system_id,
            "workspace_id": workspace_id,
            "name": name,
            "settings": settings or {},
            "flow_definition": flow_definition or {},
            "published_flow_version_id": version_id,
        },
    )
    bind.execute(
        versions.insert(),
        {
            "id": version_id,
            "system_id": system_id,
            "workspace_id": workspace_id,
            "flow_sha256": FLOW_SHA,
            "execution_contract": CONTRACT,
        },
    )


def test_mission_nav_binding_key_follows_profile():
    assert mission_nav_binding_key("sentinel_government_v1", "presse") == SENTINEL_INTELLIGENCE_KEY
    assert mission_nav_binding_key("octocity_institutional_v1", "strategie") == "octocity.map"
    assert mission_nav_binding_key("", "agenda") == "mission.agenda"
    assert mission_nav_binding_key("sentinel_government_v1", "cockpit") == SENTINEL_COCKPIT_KEY
    assert mission_nav_binding_key("sentinel_government_v1", "decisions") == SENTINEL_DECISIONS_KEY


def test_seed_without_target_workspaces_is_a_no_op(bind):
    _schema(bind)
    seed_dual_run_experiences(bind)
    assert bind.execute(sa.text("SELECT COUNT(*) FROM experiences")).scalar() == 0
    assert bind.execute(sa.text("SELECT COUNT(*) FROM system_bindings")).scalar() == 0


def test_andritz_seeds_inventory_pointers_without_published_systems(bind):
    workspaces, _systems, _versions, bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces, workspace_id="ws-andritz", slug="andritz")

    seed_dual_run_experiences(bind)

    rows = bind.execute(sa.select(experiences.c.slug, experiences.c.theme)).all()
    by_slug = {row._mapping["slug"]: row._mapping["theme"] for row in rows}
    assert set(by_slug) == {
        RECHERCHE_EXPERIENCE_SLUG,
        CLIENT360_EXPERIENCE_SLUG,
        CAPTURE_EXPERIENCE_SLUG,
        FSE_EXPERIENCE_SLUG,
    }
    assert by_slug[RECHERCHE_EXPERIENCE_SLUG]["live_href"] == "/chat"
    assert by_slug[CLIENT360_EXPERIENCE_SLUG]["live_href"] == "/client360"
    assert by_slug[CAPTURE_EXPERIENCE_SLUG]["live_href"] == "/knowledge/capture"
    assert by_slug[FSE_EXPERIENCE_SLUG]["live_href"] == "/knowledge/interventions"
    assert bind.execute(sa.select(sa.func.count()).select_from(bindings)).scalar_one() == 0


def test_andritz_bindings_when_published_and_seed_is_idempotent(bind):
    (
        workspaces,
        systems,
        versions,
        bindings,
        experiences,
        _drafts,
        releases,
        _deployments,
    ) = _schema(bind)
    _insert_workspace(bind, workspaces, workspace_id="ws-andritz", slug="andritz")
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-chat",
        workspace_id="ws-andritz",
        name="Andritz Workspace Chat",
        flow_definition={"variant": "chat_transverse_v1"},
    )
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-fse",
        workspace_id="ws-andritz",
        name="Rapport d'intervention FSE",
        settings={"capture": {"template_id": "fse_intervention_v1"}},
    )

    seed_dual_run_experiences(bind)
    seed_dual_run_experiences(bind)

    keys = sorted(row[0] for row in bind.execute(sa.select(bindings.c.binding_key)).all())
    assert keys == [ANDRITZ_FSE_KEY, ANDRITZ_RECHERCHE_KEY]
    slugs = sorted(row[0] for row in bind.execute(sa.select(experiences.c.slug)).all())
    assert slugs == [
        CAPTURE_EXPERIENCE_SLUG,
        CLIENT360_EXPERIENCE_SLUG,
        FSE_EXPERIENCE_SLUG,
        RECHERCHE_EXPERIENCE_SLUG,
    ]
    assert bind.execute(sa.select(sa.func.count()).select_from(experiences)).scalar_one() == 4
    assert bind.execute(sa.select(sa.func.count()).select_from(bindings)).scalar_one() == 2
    assert {
        row[0]
        for row in bind.execute(sa.select(releases.c.renderer_version)).all()
    } == {"certified-components-0.2.0"}


def test_sentinel_and_octocity_are_separate_inventory_pointers(bind):
    workspaces, systems, versions, bindings, experiences, drafts, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces, workspace_id="ws-sentinel", slug="sentinel-ci")
    _insert_workspace(bind, workspaces, workspace_id="ws-octocity", slug="octocity-mission-room")
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-map",
        workspace_id="ws-sentinel",
        name="Carte Strategique Executive",
        flow_definition={"variant": "territorial_action_map"},
    )
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-cockpit",
        workspace_id="ws-sentinel",
        name="Government Mission Room",
        flow_definition={"variant": "government_mission_room"},
    )
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-decisions",
        workspace_id="ws-sentinel",
        name="Executive Instruction Drafting",
        flow_definition={"variant": "executive_instruction_drafting"},
    )
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-veille",
        workspace_id="ws-sentinel",
        name="Veille Presse & Signaux Faibles",
        flow_definition={"variant": "intelligence", "template_id": "sentinel-ci-intelligence"},
    )
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-oct-intel",
        workspace_id="ws-octocity",
        name="OCTAVE Open Intelligence",
        flow_definition={"variant": "octocity_intelligence"},
    )

    seed_dual_run_experiences(bind)
    seed_dual_run_experiences(bind)

    sentinel = bind.execute(
        sa.select(experiences.c.id, experiences.c.theme, experiences.c.pattern).where(
            experiences.c.slug == SENTINEL_EXPERIENCE_SLUG
        )
    ).one()
    octocity = bind.execute(
        sa.select(experiences.c.theme, experiences.c.pattern).where(
            experiences.c.slug == OCTOCITY_EXPERIENCE_SLUG
        )
    ).one()
    assert sentinel._mapping["theme"]["live_href"] == "/hypervisor/mission-room/cockpit"
    assert octocity._mapping["theme"]["live_href"] == "/hypervisor/mission-room/cockpit"
    assert sentinel._mapping["pattern"] == "mission_cockpit"
    keys = sorted(row[0] for row in bind.execute(sa.select(bindings.c.binding_key)).all())
    assert SENTINEL_MAP_KEY in keys
    assert SENTINEL_COCKPIT_KEY in keys
    assert SENTINEL_DECISIONS_KEY in keys
    assert SENTINEL_INTELLIGENCE_KEY in keys
    assert OCTOCITY_INTELLIGENCE_KEY in keys
    pages = bind.execute(
        sa.select(drafts.c.pages).where(drafts.c.experience_id == sentinel._mapping["id"])
    ).scalar_one()
    types = [item["type"] for item in pages["pages"][0]["components"]]
    assert types == [
        "header",
        "map_panel",
        "agenda_panel",
        "intelligence_feed",
        "decision_queue",
        "callout",
    ]


def test_mission_control_seeds_only_generic_mission_workspaces(bind):
    workspaces, systems, versions, bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(
        bind,
        workspaces,
        workspace_id="ws-generic",
        slug="acme-ops",
        settings={"mission_room": {"enabled": True, "profile": "generic"}},
    )
    _insert_workspace(
        bind,
        workspaces,
        workspace_id="ws-sentinel",
        slug="other-sentinel",
        settings={"mission_room": {"enabled": True, "profile": "sentinel_government_v1"}},
    )
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-intel",
        workspace_id="ws-generic",
        name="Open Intelligence",
        flow_definition={"variant": "intelligence"},
    )

    seed_dual_run_experiences(bind)

    slugs = [row[0] for row in bind.execute(sa.select(experiences.c.slug)).all()]
    assert slugs == [MISSION_CONTROL_EXPERIENCE_SLUG]
    theme = bind.execute(sa.select(experiences.c.theme)).scalar_one()
    assert theme["live_href"] == "/hypervisor/mission-room"
    keys = [row[0] for row in bind.execute(sa.select(bindings.c.binding_key)).all()]
    assert keys == [MISSION_INTELLIGENCE_KEY]


def test_existing_slug_is_left_alone(bind):
    workspaces, _systems, _versions, _bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces, workspace_id="ws-andritz", slug="andritz")
    bind.execute(
        experiences.insert(),
        {
            "id": "existing-recherche",
            "workspace_id": "ws-andritz",
            "name": "Operator Recherche",
            "slug": RECHERCHE_EXPERIENCE_SLUG,
            "pattern": "assistant",
            "languages": ["en"],
            "theme": {"live_href": "/custom"},
            "created_by": "operator",
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        },
    )

    seed_dual_run_experiences(bind)

    row = bind.execute(
        sa.select(experiences.c.name, experiences.c.theme).where(
            experiences.c.slug == RECHERCHE_EXPERIENCE_SLUG
        )
    ).one()
    assert row._mapping["name"] == "Operator Recherche"
    assert row._mapping["theme"]["live_href"] == "/custom"


def test_092_repairs_091_in_place_release_with_immutable_successor(bind):
    (
        workspaces,
        systems,
        versions,
        _bindings,
        experiences,
        drafts,
        releases,
        deployments,
    ) = _schema(bind)
    _insert_workspace(
        bind,
        workspaces,
        workspace_id="ws-repair",
        slug="repair-mission",
        settings={"mission_room": {"enabled": True, "profile": "generic"}},
    )
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id="sys-repair-intel",
        workspace_id="ws-repair",
        name="Open Intelligence",
        flow_definition={"variant": "intelligence"},
    )
    seed_dual_run_experiences(bind)
    experience_id = bind.execute(
        sa.select(experiences.c.id).where(
            experiences.c.slug == MISSION_CONTROL_EXPERIENCE_SLUG
        )
    ).scalar_one()
    original = bind.execute(
        sa.select(releases.c.id, releases.c.pages).where(
            releases.c.experience_id == experience_id,
            releases.c.release_number == 1,
        )
    ).one()
    assert any(
        item["type"] == "intelligence_feed"
        for item in original._mapping["pages"]["pages"][0]["components"]
    )

    repair_mutated_091_releases(bind)

    repaired = bind.execute(
        sa.select(
            releases.c.id,
            releases.c.release_number,
            releases.c.pages,
        )
        .where(releases.c.experience_id == experience_id)
        .order_by(releases.c.release_number)
    ).all()
    assert [row._mapping["release_number"] for row in repaired] == [1, 2]
    assert repaired[0]._mapping["id"] == original._mapping["id"]
    assert [
        item["type"]
        for item in repaired[0]._mapping["pages"]["pages"][0]["components"]
    ] == ["header", "callout"]
    assert "intelligence_feed" in {
        item["type"]
        for item in repaired[1]._mapping["pages"]["pages"][0]["components"]
    }
    deployment = bind.execute(
        sa.select(deployments.c.release_id, deployments.c.previous_release_id).where(
            deployments.c.experience_id == experience_id
        )
    ).one()
    assert deployment._mapping["release_id"] == repaired[1]._mapping["id"]
    assert deployment._mapping["previous_release_id"] == repaired[0]._mapping["id"]
    draft = bind.execute(
        sa.select(drafts.c.pages, drafts.c.revision).where(
            drafts.c.experience_id == experience_id
        )
    ).one()
    # 092 repairs immutable release history without overwriting or bumping the
    # current authoring draft.
    assert draft._mapping["revision"] == 1
    assert "intelligence_feed" in {
        item["type"]
        for item in draft._mapping["pages"]["pages"][0]["components"]
    }

    repair_mutated_091_releases(bind)
    assert bind.execute(
        sa.select(sa.func.count()).select_from(releases).where(
            releases.c.experience_id == experience_id
        )
    ).scalar_one() == 2
