"""Migration contract tests for the Nawa ITSD password-reset surface (065).

The migration runs on a production database where the ``nawa`` workspace may
not exist yet, so the "no workspace" case is a first-class test, not an edge
case. The rest of the suite pins the three claims the deployment relies on:
additive, idempotent, and blind to every other workspace.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest
import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3] / "alembic" / "versions" / "065_nawa_itsd.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_065", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return mod


MIG = _load_migration()


class _SQLiteOps:
    """Run data changes while leaving CHECK DDL to PostgreSQL deployment tests."""

    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind

    @contextmanager
    def batch_alter_table(self, _table_name):
        yield types.SimpleNamespace(
            drop_constraint=lambda *args, **kwargs: None,
            create_check_constraint=lambda *args, **kwargs: None,
        )


def _schema(bind):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("settings", sa.JSON()),
    )
    members = sa.Table(
        "workspace_members",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
    )
    entitlements = sa.Table(
        "workspace_member_app_entitlements",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_member_id", sa.Integer(), nullable=False),
        sa.Column("app_key", sa.String(80), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("granted_by_user_id", sa.String(36)),
        sa.Column("grant_source", sa.String(80), nullable=False),
        sa.UniqueConstraint(
            "workspace_member_id",
            "app_key",
            name="uq_workspace_member_app_entitlement",
        ),
    )
    capabilities = sa.Table(
        "capabilities",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False),
    )
    skills = sa.Table(
        "skills",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("version", sa.String(20)),
        sa.Column("name", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("type", sa.String(80)),
        sa.Column("certification_level", sa.String(40)),
        sa.Column("is_seeded", sa.String(1)),
        sa.Column("provider", sa.String(80)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("objective", sa.Text()),
        sa.Column("capability_id", sa.String(36)),
        sa.Column("skill_ids", sa.JSON()),
        sa.Column("flow_definition", sa.JSON()),
        sa.Column("settings", sa.JSON()),
        sa.Column("execution_mode", sa.String(80)),
        sa.Column("execution_profile", sa.JSON()),
        sa.Column("coordination_pattern", sa.String(80)),
        sa.Column("status", sa.String(40)),
        sa.Column("created_by", sa.String(255)),
        sa.Column("default_model", sa.String(120)),
        sa.Column("retrieval_mode_default", sa.String(40)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    metadata.create_all(bind)
    return workspaces, members, entitlements, capabilities, skills, systems


@pytest.fixture()
def bind(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        monkeypatch.setattr(MIG, "op", _SQLiteOps(connection))
        yield connection


def _seed_nawa(bind, tables, *, members=(1, 2), settings=None):
    workspaces, member_table, _ent, capabilities, _skills, _systems = tables
    bind.execute(
        workspaces.insert(),
        {"id": "workspace-nawa", "slug": MIG.NAWA_SLUG, "settings": settings},
    )
    if members:
        bind.execute(
            member_table.insert(),
            [{"id": mid, "workspace_id": "workspace-nawa"} for mid in members],
        )
    bind.execute(
        capabilities.insert(),
        {"id": "capability-assistant", "slug": MIG.CAPABILITY_SLUG},
    )


def test_upgrade_without_a_nawa_workspace_is_a_no_op(bind):
    """The workspace is created by the operator, possibly after this runs."""
    tables = _schema(bind)
    _workspaces, _members, entitlements, _caps, _skills, systems = tables

    MIG.upgrade()  # must not raise

    assert bind.execute(sa.select(sa.func.count()).select_from(systems)).scalar_one() == 0
    assert (
        bind.execute(sa.select(sa.func.count()).select_from(entitlements)).scalar_one() == 0
    )


def test_upgrade_seeds_the_system_entitlements_and_navigation(bind):
    tables = _schema(bind)
    workspaces, _members, entitlements, _caps, skills, systems = tables
    _seed_nawa(bind, tables)

    MIG.upgrade()

    grants = bind.execute(sa.select(entitlements)).mappings().all()
    assert {row["workspace_member_id"] for row in grants} == {1, 2}
    assert {row["app_key"] for row in grants} == {MIG.NAWA_APP_KEY}
    assert {row["grant_source"] for row in grants} == {MIG.SEED_ORIGIN}

    profile = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["navigation_profile"]
    assert profile["primary_surfaces"] == ["chat", MIG.NAWA_APP_KEY]
    assert profile["default_route"] == "/nawa/itsd"
    # NOT the business shell: it whitelists the paths it serves, and the run
    # trace and the Flow Builder are not on that list.
    assert profile["key"] == "standard"

    # The flow binds skills that no Capability exposes; the workspace has to
    # name them itself or they resolve to nothing in its catalogue.
    catalog = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["catalog"]
    assert set(MIG.CATALOG_ENABLED_SKILLS) <= set(catalog["enabled_skills"])
    assert {"azure_llm_v1", "response_eval_v1", "rpa_dispatch_v1"} <= set(
        catalog["enabled_skills"]
    )

    system = bind.execute(sa.select(systems)).mappings().one()
    assert system["name"] == MIG.SYSTEM_NAME
    assert system["status"] == "active"
    assert system["capability_id"] == "capability-assistant"
    assert system["settings"]["seed_origin"] == MIG.SEED_ORIGIN
    assert system["settings"]["assistant_name"] == "NAWA WE"
    assert system["settings"]["surface"] == MIG.NAWA_APP_KEY

    # Walked by the DAG engine: schema_version >= 2 plus real control nodes.
    flow = system["flow_definition"]
    assert flow["schema_version"] >= 2
    kinds = {node["kind"] for node in flow["nodes"]}
    assert "decision" in kinds and "hitl" in kinds

    # The fallback twin travels with the System so the switch is one PATCH.
    fallback = system["settings"]["fallback_flow_definition"]
    assert [n["id"] for n in fallback["nodes"]] == [n["id"] for n in flow["nodes"]]
    assert not any(
        (n.get("config") or {}).get("skill_slug") == "azure_llm_v1"
        for n in fallback["nodes"]
    )

    # Both flows resolved every skill_slug to a real skills row.
    seeded = {
        row._mapping["slug"]: row._mapping["id"]
        for row in bind.execute(sa.select(skills.c.slug, skills.c.id)).all()
    }
    assert set(seeded) == set(MIG.CATALOG_ENABLED_SKILLS)
    assert set(system["skill_ids"]) == set(seeded.values())
    for node in flow["nodes"]:
        slug = (node.get("config") or {}).get("skill_slug")
        if slug:
            assert node["config"]["skill_id"] == seeded[slug]


def test_upgrade_never_touches_the_feature_flags(bind):
    """`features` is where the connector flags live. Provisioning the RPA
    bridge from here would turn the incident scenario into a silent success —
    the failure would only surface on stage. This migration has no business in
    that key, and must round-trip it byte for byte."""
    tables = _schema(bind)
    workspaces, _members, _ent, _caps, _skills, _systems = tables
    features = {"rpa_bridge": False, "some_other_flag": True}
    _seed_nawa(
        bind,
        tables,
        settings={"features": deepcopy(features), "catalog": {"family": "generic"}},
    )

    MIG.upgrade()

    settings = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()
    assert settings["features"] == features
    # The whole-settings write is a read-modify-write: only these keys may ever
    # appear or change.
    assert set(settings) == {
        "features",
        "catalog",
        "navigation_profile",
        "platform_brand",
        MIG.MIGRATION_MARKER_KEY,
    }


def test_upgrade_merges_the_catalog_without_dropping_its_family(bind):
    """`catalog` is not ours to replace: it also carries `family`, and losing
    it would silently re-scope the workspace's whole resolved catalogue."""
    tables = _schema(bind)
    workspaces, _members, _ent, _caps, _skills, _systems = tables
    _seed_nawa(
        bind,
        tables,
        settings={
            "catalog": {
                "family": "generic",
                # Already enabled by an operator, in another case: the reader
                # lower-cases every entry, so this is the same skill.
                "enabled_skills": ["Azure_LLM_v1", "some_other_skill_v1"],
            }
        },
    )

    MIG.upgrade()
    MIG.upgrade()

    catalog = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["catalog"]
    assert catalog["family"] == "generic"
    assert "some_other_skill_v1" in catalog["enabled_skills"]
    # Case-insensitive union: no duplicate, and the operator's spelling wins.
    assert "Azure_LLM_v1" in catalog["enabled_skills"]
    assert "azure_llm_v1" not in catalog["enabled_skills"]
    lowered = [s.lower() for s in catalog["enabled_skills"]]
    assert len(lowered) == len(set(lowered))
    assert {s.lower() for s in MIG.CATALOG_ENABLED_SKILLS} <= set(lowered)


def test_upgrade_is_idempotent(bind):
    tables = _schema(bind)
    workspaces, _members, entitlements, _caps, skills, systems = tables
    _seed_nawa(bind, tables)

    MIG.upgrade()
    MIG.upgrade()

    assert bind.execute(sa.select(sa.func.count()).select_from(systems)).scalar_one() == 1
    assert (
        bind.execute(sa.select(sa.func.count()).select_from(entitlements)).scalar_one() == 2
    )
    assert bind.execute(sa.select(sa.func.count()).select_from(skills)).scalar_one() == len(
        MIG.CATALOG_ENABLED_SKILLS
    )
    profile = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["navigation_profile"]
    assert profile["primary_surfaces"] == ["chat", MIG.NAWA_APP_KEY]


def test_upgrade_preserves_an_existing_profile_and_other_workspaces(bind):
    tables = _schema(bind)
    workspaces, members, entitlements, _caps, _skills, systems = tables
    _seed_nawa(
        bind,
        tables,
        settings={
            "navigation_profile": {
                "key": "standard",
                "default_route": "/nawa/itsd/password-reset",
                "primary_surfaces": ["chat"],
                "advanced_access": "hidden",
            }
        },
    )
    bind.execute(
        workspaces.insert(),
        {"id": "workspace-other", "slug": "andritz", "settings": {"features": {}}},
    )
    bind.execute(members.insert(), {"id": 9, "workspace_id": "workspace-other"})

    MIG.upgrade()

    profile = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["navigation_profile"]
    # Operator-authored keys survive; only the surface list is extended, in the
    # canonical app order `normalize_app_entitlements` enforces.
    assert profile["advanced_access"] == "hidden"
    assert profile["default_route"] == "/nawa/itsd/password-reset"
    assert profile["primary_surfaces"] == ["chat", MIG.NAWA_APP_KEY]

    other = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-other")
    ).scalar_one()
    assert other == {"features": {}}
    assert 9 not in {
        row._mapping["workspace_member_id"]
        for row in bind.execute(sa.select(entitlements)).all()
    }
    assert bind.execute(
        sa.select(sa.func.count())
        .select_from(systems)
        .where(systems.c.workspace_id == "workspace-other")
    ).scalar_one() == 0


def test_upgrade_brands_the_platform_chrome_for_this_workspace_only(bind):
    """The title bar and the browser tab are shared by every workspace, so the
    white-label switch is a per-workspace setting. Andritz must come out of this
    migration exactly as it went in, still wearing the Agentium chrome."""
    tables = _schema(bind)
    workspaces, members, _ent, _caps, _skills, _systems = tables
    _seed_nawa(bind, tables, settings={})
    bind.execute(
        workspaces.insert(),
        {"id": "workspace-other", "slug": "andritz", "settings": {"features": {}}},
    )
    bind.execute(members.insert(), {"id": 11, "workspace_id": "workspace-other"})

    MIG.upgrade()

    brand = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["platform_brand"]
    assert brand == MIG.PLATFORM_BRAND
    # Both fields are required by the frontend reader: half a declaration would
    # mix the customer name with our mark.
    assert brand["label"] and brand["emblem"]
    other = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-other")
    ).scalar_one()
    assert "platform_brand" not in other


def test_upgrade_keeps_an_operator_authored_brand(bind):
    tables = _schema(bind)
    workspaces, _members, _ent, _caps, _skills, _systems = tables
    authored = {"label": "NAWA", "emblem": "/assets/nawa/other.png", "home": "/nawa/itsd"}
    _seed_nawa(bind, tables, settings={"platform_brand": deepcopy(authored)})

    MIG.upgrade()
    assert bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["platform_brand"] == authored

    # ...and a brand we did not write is not ours to remove either.
    MIG.downgrade()
    assert bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["platform_brand"] == authored


def test_downgrade_removes_the_brand_it_wrote(bind):
    tables = _schema(bind)
    workspaces, _members, _ent, _caps, _skills, _systems = tables
    _seed_nawa(bind, tables, settings={})

    MIG.upgrade()
    MIG.downgrade()

    settings = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()
    assert "platform_brand" not in settings


def test_upgrade_leaves_an_operator_authored_system_alone(bind):
    """Name collisions must not hijack a System we did not create."""
    tables = _schema(bind)
    _workspaces, _members, _ent, _caps, _skills, systems = tables
    _seed_nawa(bind, tables)
    bind.execute(
        systems.insert(),
        {
            "id": "system-operator",
            "workspace_id": "workspace-nawa",
            "name": MIG.SYSTEM_NAME,
            "settings": {"seed_origin": "operator"},
            "flow_definition": {},
            "status": "active",
        },
    )

    MIG.upgrade()

    rows = bind.execute(sa.select(systems).order_by(systems.c.id)).mappings().all()
    assert len(rows) == 2
    untouched = next(row for row in rows if row["id"] == "system-operator")
    assert untouched["flow_definition"] == {}
    assert untouched["settings"] == {"seed_origin": "operator"}


def test_downgrade_retires_without_deleting_history(bind):
    tables = _schema(bind)
    workspaces, _members, entitlements, _caps, _skills, systems = tables
    _seed_nawa(bind, tables)

    MIG.upgrade()
    MIG.downgrade()

    assert (
        bind.execute(sa.select(sa.func.count()).select_from(entitlements)).scalar_one() == 0
    )
    # The System row survives so its runs and audit events stay readable.
    assert bind.execute(sa.select(systems.c.status)).scalar_one() == "retired"
    profile = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()["navigation_profile"]
    assert MIG.NAWA_APP_KEY not in profile["primary_surfaces"]
    settings = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()
    assert "catalog" not in settings
