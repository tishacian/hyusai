"""Additive/backfill contract for Flow publication migration 077."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "077_flow_publication_v1.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_077", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


def _schema(connection):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("settings", sa.JSON()),
    )
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("flow_definition", sa.JSON()),
        sa.Column("created_by", sa.String(255)),
        sa.Column("published_flow_version_id", sa.String(36)),
        sa.Column("published_by", sa.String(255)),
        sa.Column("published_at", sa.DateTime()),
    )
    versions = sa.Table(
        "system_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
        sa.Column("configuration_snapshot", sa.JSON()),
        sa.Column("message", sa.Text()),
        sa.Column("rolled_back_from_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("created_by", sa.String(255)),
        sa.Column("flow_sha256", sa.String(64)),
        sa.Column("release_kind", sa.String(32)),
        sa.Column("draft_revision", sa.Integer()),
        sa.Column("execution_contract", sa.JSON()),
    )
    drafts = sa.Table(
        "system_flow_drafts",
        metadata,
        sa.Column("system_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("flow_sha256", sa.String(64), nullable=False),
        sa.Column("base_published_version_id", sa.String(36)),
        sa.Column("updated_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    metadata.create_all(connection)
    return workspaces, systems, versions, drafts


def test_revision_extends_current_head() -> None:
    assert MIG.revision == "077_flow_publication_v1"
    assert MIG.down_revision == "076_decision_scenario_lineage"
    assert len(MIG.revision) <= 32


def test_backfill_reuses_exact_immutable_version_without_rewriting_it() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    flow = {"schema_version": 3, "nodes": [], "edges": []}
    with engine.begin() as connection:
        workspaces, systems, versions, drafts = _schema(connection)
        connection.execute(workspaces.insert(), {"id": "ws", "settings": {}})
        connection.execute(
            systems.insert(),
            {
                "id": "system",
                "workspace_id": "ws",
                "flow_definition": flow,
                "created_by": "legacy",
            },
        )
        connection.execute(
            versions.insert(),
            {
                "id": "version-exact",
                "system_id": "system",
                "workspace_id": "ws",
                "version_number": 7,
                "flow_definition": flow,
                "created_by": "legacy",
                "flow_sha256": None,
                "release_kind": None,
            },
        )

        MIG._backfill(connection)

        assert connection.execute(sa.select(sa.func.count()).select_from(versions)).scalar_one() == 1
        historical = connection.execute(sa.select(versions)).mappings().one()
        assert historical["id"] == "version-exact"
        assert historical["flow_sha256"] is None
        assert historical["release_kind"] is None
        system = connection.execute(sa.select(systems)).mappings().one()
        assert system["flow_definition"] == flow
        assert system["published_flow_version_id"] == "version-exact"
        draft = connection.execute(sa.select(drafts)).mappings().one()
        assert draft["flow_definition"] == flow
        assert draft["revision"] == 1
        assert draft["base_published_version_id"] == "version-exact"


def test_backfill_appends_only_when_no_exact_version_exists() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    published = {"schema_version": 3, "label": "published", "nodes": [], "edges": []}
    old = {"schema_version": 3, "label": "old", "nodes": [], "edges": []}
    with engine.begin() as connection:
        workspaces, systems, versions, drafts = _schema(connection)
        connection.execute(workspaces.insert(), {"id": "ws", "settings": {}})
        connection.execute(
            systems.insert(),
            {
                "id": "system",
                "workspace_id": "ws",
                "flow_definition": published,
                "created_by": "legacy",
            },
        )
        connection.execute(
            versions.insert(),
            {
                "id": "version-old",
                "system_id": "system",
                "workspace_id": "ws",
                "version_number": 4,
                "flow_definition": old,
                "created_by": "legacy",
            },
        )

        MIG._backfill(connection)

        rows = connection.execute(
            sa.select(versions).order_by(versions.c.version_number)
        ).mappings().all()
        assert len(rows) == 2
        assert rows[0]["flow_definition"] == old
        assert rows[1]["version_number"] == 5
        assert rows[1]["flow_definition"] == published
        assert rows[1]["release_kind"] == "migration"
        assert rows[1]["execution_contract"] is None
        pointer = connection.execute(
            sa.select(systems.c.published_flow_version_id)
        ).scalar_one()
        assert pointer == rows[1]["id"]
        assert connection.execute(sa.select(drafts.c.flow_definition)).scalar_one() == published
