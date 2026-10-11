"""Migration 088: NAWA binding retry, inventory Experience, optional recon seed."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3] / "alembic" / "versions" / "088_xp_nawa_recon.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_088", path)
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
INPUT_SHA = "b" * 64
CONTRACT = {
    "ingresses": [
        {
            "ingress_id": "source.request",
            "kind": "manual",
            "input_schema_sha256": INPUT_SHA,
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }
    ],
    "outputs": [],
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
    )
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("settings", sa.JSON()),
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
def bind(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        monkeypatch.setattr(MIG, "op", _SQLiteOps(connection))
        yield connection


def _insert_workspace(bind, workspaces, *, workspace_id="workspace-nawa", slug="nawa"):
    bind.execute(workspaces.insert(), {"id": workspace_id, "slug": slug})


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
):
    bind.execute(
        systems.insert(),
        {
            "id": system_id,
            "workspace_id": workspace_id,
            "name": name,
            "settings": settings or {"seed_origin": "065_nawa_itsd"},
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


def test_upgrade_without_nawa_workspace_is_a_no_op(bind):
    tables = _schema(bind)
    _workspaces, _systems, _versions, bindings, experiences, *_rest = tables

    MIG.upgrade()

    assert bind.execute(sa.select(sa.func.count()).select_from(bindings)).scalar_one() == 0
    assert bind.execute(sa.select(sa.func.count()).select_from(experiences)).scalar_one() == 0


def test_upgrade_skips_unpublished_password_reset(bind):
    workspaces, systems, versions, bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces)
    bind.execute(
        systems.insert(),
        {
            "id": "system-password-reset",
            "workspace_id": "workspace-nawa",
            "name": "Password Reset",
            "settings": {"seed_origin": "065_nawa_itsd"},
            "published_flow_version_id": None,
        },
    )

    MIG.upgrade()

    assert bind.execute(sa.select(sa.func.count()).select_from(bindings)).scalar_one() == 0
    row = bind.execute(sa.select(experiences.c.slug, experiences.c.theme)).one()
    assert row._mapping["slug"] == "nawa"
    assert row._mapping["theme"]["live_href"] == "/nawa"


def test_upgrade_retries_binding_without_065_marker(bind):
    workspaces, systems, versions, bindings, experiences, drafts, releases, deployments = _schema(bind)
    _insert_workspace(bind, workspaces)
    _insert_published_system(bind, systems, versions, settings={})

    MIG.upgrade()

    binding = bind.execute(sa.select(bindings.c.binding_key, bindings.c.system_id)).one()
    assert binding._mapping["binding_key"] == "nawa.password_reset"
    assert binding._mapping["system_id"] == "system-password-reset"
    experience = bind.execute(
        sa.select(experiences.c.slug, experiences.c.name, experiences.c.pattern)
    ).one()
    assert experience._mapping["slug"] == "nawa"
    assert experience._mapping["name"] == "NAWA — IT Help Desk"
    assert experience._mapping["pattern"] == "assistant"
    draft = bind.execute(sa.select(drafts.c.binding_keys)).one()
    assert draft._mapping["binding_keys"] == ["nawa.password_reset"]
    assert bind.execute(sa.select(deployments.c.channel)).scalar_one() == "live"
    assert bind.execute(sa.select(releases.c.release_number)).scalar_one() == 1


def test_upgrade_is_idempotent_and_skips_existing_slug(bind):
    workspaces, systems, versions, bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces)
    _insert_published_system(bind, systems, versions)

    MIG.upgrade()
    MIG.upgrade()

    assert bind.execute(sa.select(sa.func.count()).select_from(bindings)).scalar_one() == 1
    assert bind.execute(sa.select(sa.func.count()).select_from(experiences)).scalar_one() == 1


def test_upgrade_skips_reconciliation_when_no_published_system(bind):
    workspaces, systems, versions, bindings, experiences, *_rest = _schema(bind)
    _insert_workspace(bind, workspaces)
    _insert_published_system(bind, systems, versions)

    MIG.upgrade()

    slugs = [row[0] for row in bind.execute(sa.select(experiences.c.slug)).all()]
    assert slugs == ["nawa"]
    keys = [row[0] for row in bind.execute(sa.select(bindings.c.binding_key)).all()]
    assert keys == ["nawa.password_reset"]


def test_upgrade_seeds_reconciliation_when_published_system_exists(bind):
    workspaces, systems, versions, bindings, experiences, drafts, releases, deployments = _schema(bind)
    _insert_workspace(bind, workspaces)
    _insert_published_system(bind, systems, versions)
    recon_id = str(uuid4())
    version_id = str(uuid4())
    _insert_published_system(
        bind,
        systems,
        versions,
        system_id=recon_id,
        version_id=version_id,
        name="PO vs Invoice Reconciliation",
        settings={},
    )

    MIG.upgrade()
    MIG.upgrade()

    keys = sorted(row[0] for row in bind.execute(sa.select(bindings.c.binding_key)).all())
    assert keys == ["nawa.password_reset", "rapprochement.po.factures"]
    slugs = sorted(row[0] for row in bind.execute(sa.select(experiences.c.slug)).all())
    assert slugs == ["nawa", "rapprochement-po-factures"]
    recon = bind.execute(
        sa.select(experiences.c.pattern, experiences.c.id).where(
            experiences.c.slug == "rapprochement-po-factures"
        )
    ).one()
    assert recon._mapping["pattern"] == "form_result"
    channel = bind.execute(
        sa.select(deployments.c.channel).where(
            deployments.c.experience_id == recon._mapping["id"]
        )
    ).scalar_one()
    assert channel == "pilot"
    pages = bind.execute(
        sa.select(drafts.c.pages, drafts.c.binding_keys).where(
            drafts.c.experience_id == recon._mapping["id"]
        )
    ).one()
    assert pages._mapping["binding_keys"] == ["rapprochement.po.factures"]
    types = [node["type"] for node in pages._mapping["pages"]["pages"][0]["components"]]
    assert types[:3] == ["header", "form", "action_button"]
    assert bind.execute(sa.select(sa.func.count()).select_from(experiences)).scalar_one() == 2
