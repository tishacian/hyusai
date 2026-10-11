"""Migration 089: publish unpublished NAWA flow, then bind; seed PO↔Invoice."""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3] / "alembic" / "versions" / "089_publish_nawa_recon.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_089", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return mod


MIG = _load_migration()
FLOW_SHA = "a" * 64
NAWA_FLOW = {
    "nodes": [
        {
            "id": "source.request",
            "kind": "source",
            "type": "source",
            "outputs": [
                {"name": "scenario", "schema": "string"},
                {"name": "case", "schema": "object"},
            ],
        },
        {"id": "sink.result", "kind": "sink", "config": {"output_schema": {"type": "object"}}},
    ],
    "edges": [{"from": "source.request", "to": "sink.result"}],
}
RECON_FLOW = {
    "nodes": [
        {
            "id": "source.manual",
            "kind": "source",
            "type": "source",
            "config": {
                "ingress_kind": "manual",
                "input_schema": {
                    "type": "object",
                    "properties": {"po_file_id": {"type": "string"}},
                },
            },
        },
        {"id": "sink.result", "kind": "sink", "config": {"output_schema": {"type": "object"}}},
    ],
    "edges": [{"from": "source.manual", "to": "sink.result"}],
}


class _SQLiteOps:
    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind


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
        sa.Column("objective", sa.Text()),
        sa.Column("capability_id", sa.String(36)),
        sa.Column("skill_ids", sa.JSON()),
        sa.Column("flow_definition", sa.JSON()),
        sa.Column("settings", sa.JSON()),
        sa.Column("execution_mode", sa.String(40)),
        sa.Column("execution_profile", sa.JSON()),
        sa.Column("coordination_pattern", sa.String(40)),
        sa.Column("status", sa.String(20)),
        sa.Column("created_by", sa.String(255)),
        sa.Column("default_model", sa.String(120)),
        sa.Column("retrieval_mode_default", sa.String(20)),
        sa.Column("blueprint_key", sa.String(120)),
        sa.Column("published_flow_version_id", sa.String(36)),
        sa.Column("published_by", sa.String(255)),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    versions = sa.Table(
        "system_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("flow_definition", sa.JSON()),
        sa.Column("configuration_snapshot", sa.JSON()),
        sa.Column("message", sa.Text()),
        sa.Column("rolled_back_from_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("flow_sha256", sa.String(64)),
        sa.Column("release_kind", sa.String(32)),
        sa.Column("draft_revision", sa.Integer()),
        sa.Column("execution_contract", sa.JSON()),
    )
    flow_drafts = sa.Table(
        "system_flow_drafts",
        metadata,
        sa.Column("system_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("flow_sha256", sa.String(64), nullable=False),
        sa.Column("base_published_version_id", sa.String(36)),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
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
    exp_drafts = sa.Table(
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
    skills = sa.Table(
        "skills",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("version", sa.String(20)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("type", sa.String(60)),
        sa.Column("certification_level", sa.String(20)),
        sa.Column("is_seeded", sa.String(1)),
        sa.Column("provider", sa.String(80)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    metadata.create_all(bind)
    return (
        workspaces,
        systems,
        versions,
        flow_drafts,
        bindings,
        experiences,
        exp_drafts,
        releases,
        deployments,
        skills,
    )


@pytest.fixture()
def bind(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        monkeypatch.setattr(MIG, "op", _SQLiteOps(connection))
        yield connection


def _insert_workspace(bind, workspaces, *, workspace_id="workspace-nawa", slug="nawa"):
    bind.execute(workspaces.insert(), {"id": workspace_id, "slug": slug, "settings": {}})


def _insert_unpublished_system(
    bind,
    systems,
    *,
    system_id="system-password-reset",
    workspace_id="workspace-nawa",
    name="Password Reset",
    settings=None,
    flow=None,
):
    now = datetime.utcnow()
    bind.execute(
        systems.insert(),
        {
            "id": system_id,
            "workspace_id": workspace_id,
            "name": name,
            "objective": name,
            "flow_definition": flow if flow is not None else NAWA_FLOW,
            "settings": settings if settings is not None else {"seed_origin": "065_nawa_itsd"},
            "execution_mode": "human_augmented",
            "status": "active",
            "created_by": "system:065_nawa_itsd",
            "blueprint_key": system_id,
            "published_flow_version_id": None,
            "created_at": now,
            "updated_at": now,
        },
    )


def _insert_published_system(
    bind,
    systems,
    versions,
    *,
    system_id="system-password-reset",
    workspace_id="workspace-nawa",
    name="Password Reset",
    settings=None,
    version_id="version-password-reset",
    flow=None,
):
    flow = flow if flow is not None else NAWA_FLOW
    contract = MIG.compile_seed_contract(flow)
    now = datetime.utcnow()
    bind.execute(
        systems.insert(),
        {
            "id": system_id,
            "workspace_id": workspace_id,
            "name": name,
            "objective": name,
            "flow_definition": flow,
            "settings": settings if settings is not None else {"seed_origin": "065_nawa_itsd"},
            "execution_mode": "human_augmented",
            "status": "active",
            "blueprint_key": system_id,
            "published_flow_version_id": version_id,
            "created_at": now,
            "updated_at": now,
        },
    )
    bind.execute(
        versions.insert(),
        {
            "id": version_id,
            "system_id": system_id,
            "workspace_id": workspace_id,
            "version_number": 1,
            "flow_definition": flow,
            "flow_sha256": FLOW_SHA,
            "execution_contract": contract,
            "created_at": now,
            "created_by": "test",
            "release_kind": "migration",
            "draft_revision": 1,
        },
    )


def test_upgrade_skips_already_published_password_reset(bind):
    workspaces, systems, versions, flow_drafts, bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces)
    _insert_published_system(bind, systems, versions)

    MIG.upgrade()
    MIG.upgrade()

    pointer = bind.execute(
        sa.select(systems.c.published_flow_version_id).where(
            systems.c.id == "system-password-reset"
        )
    ).scalar_one()
    assert pointer == "version-password-reset"
    assert (
        bind.execute(
            sa.select(sa.func.count())
            .select_from(versions)
            .where(versions.c.system_id == "system-password-reset")
        ).scalar_one()
        == 1
    )
    assert (
        bind.execute(
            sa.select(sa.func.count())
            .select_from(flow_drafts)
            .where(flow_drafts.c.system_id == "system-password-reset")
        ).scalar_one()
        == 0
    )
    keys = [row[0] for row in bind.execute(sa.select(bindings.c.binding_key)).all()]
    assert "nawa.password_reset" in keys
    slugs = [row[0] for row in bind.execute(sa.select(experiences.c.slug)).all()]
    assert "nawa-reset" in slugs


def test_upgrade_publishes_then_binds_unpublished_password_reset(bind):
    workspaces, systems, versions, flow_drafts, bindings, experiences, exp_drafts, *_rest = _schema(
        bind
    )
    _insert_workspace(bind, workspaces)
    _insert_unpublished_system(bind, systems)

    MIG.upgrade()

    system = bind.execute(
        sa.select(
            systems.c.published_flow_version_id,
            systems.c.published_by,
        ).where(systems.c.id == "system-password-reset")
    ).one()
    assert system._mapping["published_flow_version_id"]
    assert system._mapping["published_by"] == "system:089_publish_nawa_recon"
    version = bind.execute(
        sa.select(
            versions.c.id,
            versions.c.flow_sha256,
            versions.c.execution_contract,
            versions.c.release_kind,
        ).where(versions.c.system_id == "system-password-reset")
    ).one()
    assert version._mapping["id"] == system._mapping["published_flow_version_id"]
    assert len(version._mapping["flow_sha256"]) == 64
    assert version._mapping["release_kind"] == "migration"
    ingresses = version._mapping["execution_contract"]["ingresses"]
    assert ingresses[0]["ingress_id"] == "source.request"
    assert (
        bind.execute(
            sa.select(flow_drafts.c.system_id).where(
                flow_drafts.c.system_id == "system-password-reset"
            )
        ).scalar_one()
        == "system-password-reset"
    )
    binding = bind.execute(
        sa.select(bindings.c.binding_key, bindings.c.system_id).where(
            bindings.c.binding_key == "nawa.password_reset"
        )
    ).one()
    assert binding._mapping["binding_key"] == "nawa.password_reset"
    assert binding._mapping["system_id"] == "system-password-reset"
    reset = bind.execute(
        sa.select(experiences.c.slug, experiences.c.pattern, experiences.c.id).where(
            experiences.c.slug == "nawa-reset"
        )
    ).one()
    assert reset._mapping["pattern"] == "form_result"
    keys = bind.execute(
        sa.select(exp_drafts.c.binding_keys).where(
            exp_drafts.c.experience_id == reset._mapping["id"]
        )
    ).scalar_one()
    assert keys == ["nawa.password_reset"]


def test_upgrade_is_idempotent_after_publish(bind):
    workspaces, systems, _versions, _drafts, bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces)
    _insert_unpublished_system(bind, systems)

    MIG.upgrade()
    MIG.upgrade()

    assert bind.execute(sa.select(sa.func.count()).select_from(systems)).scalar_one() == 2
    keys = sorted(row[0] for row in bind.execute(sa.select(bindings.c.binding_key)).all())
    assert keys == ["nawa.password_reset", "rapprochement.po.factures"]
    slugs = sorted(row[0] for row in bind.execute(sa.select(experiences.c.slug)).all())
    assert slugs == ["nawa-reset", "rapprochement-po-factures"]


def test_upgrade_seeds_po_invoice_when_missing(bind):
    workspaces, systems, versions, _drafts, bindings, experiences, exp_drafts, _rel, deployments, *_rest = _schema(
        bind
    )
    _insert_workspace(bind, workspaces)
    _insert_unpublished_system(bind, systems)

    MIG.upgrade()

    recon = bind.execute(
        sa.select(
            systems.c.id,
            systems.c.name,
            systems.c.published_flow_version_id,
        ).where(systems.c.name == "PO vs Invoice Reconciliation")
    ).one()
    assert recon._mapping["published_flow_version_id"]
    version = bind.execute(
        sa.select(versions.c.execution_contract).where(
            versions.c.id == recon._mapping["published_flow_version_id"]
        )
    ).scalar_one()
    assert version["ingresses"][0]["ingress_id"] == "source.manual"
    assert bind.execute(
        sa.select(bindings.c.binding_key).where(bindings.c.binding_key == "rapprochement.po.factures")
    ).scalar_one()
    experience = bind.execute(
        sa.select(experiences.c.pattern, experiences.c.id).where(
            experiences.c.slug == "rapprochement-po-factures"
        )
    ).one()
    assert experience._mapping["pattern"] == "form_result"
    assert (
        bind.execute(
            sa.select(deployments.c.channel).where(
                deployments.c.experience_id == experience._mapping["id"]
            )
        ).scalar_one()
        == "pilot"
    )
    pages = bind.execute(
        sa.select(exp_drafts.c.binding_keys).where(
            exp_drafts.c.experience_id == experience._mapping["id"]
        )
    ).scalar_one()
    assert pages == ["rapprochement.po.factures"]


def test_upgrade_does_not_duplicate_published_recon(bind):
    workspaces, systems, versions, _drafts, bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces)
    _insert_unpublished_system(bind, systems)
    recon_id = str(uuid4())
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id=recon_id,
        version_id=str(uuid4()),
        name="PO vs Invoice Reconciliation",
        settings={},
        flow=RECON_FLOW,
    )

    MIG.upgrade()
    MIG.upgrade()

    names = [row[0] for row in bind.execute(sa.select(systems.c.name)).all()]
    assert names.count("PO vs Invoice Reconciliation") == 1
    assert bind.execute(sa.select(sa.func.count()).select_from(bindings)).scalar_one() == 2
    slugs = sorted(row[0] for row in bind.execute(sa.select(experiences.c.slug)).all())
    assert slugs == ["nawa-reset", "rapprochement-po-factures"]
