"""Backfill contract for the default-posture migration 081."""

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
        / "081_flow_publication_default_posture.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_081", path)
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

FLOW = {"schema_version": 3, "nodes": [], "edges": []}


def _schema(connection):
    metadata = sa.MetaData()
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("flow_definition", sa.JSON()),
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
    return systems, versions, drafts


def _upgrade(connection) -> None:
    MIG.op.get_bind = lambda: connection
    MIG.upgrade()


def _downgrade(connection) -> None:
    MIG.op.get_bind = lambda: connection
    MIG.downgrade()


def test_revision_extends_current_head() -> None:
    assert MIG.revision == "081_flow_publication_baseline"
    assert MIG.down_revision == "080_trigger_event_claims"


def test_post_077_system_receives_pointer_and_draft_reusing_exact_version() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        connection.execute(
            systems.insert(),
            {"id": "system", "workspace_id": "ws", "flow_definition": FLOW},
        )
        connection.execute(
            versions.insert(),
            {
                "id": "version-exact",
                "system_id": "system",
                "workspace_id": "ws",
                "version_number": 3,
                "flow_definition": FLOW,
                "created_by": "legacy",
            },
        )

        _upgrade(connection)

        assert (
            connection.execute(sa.select(sa.func.count()).select_from(versions)).scalar_one() == 1
        )
        version = connection.execute(sa.select(versions)).mappings().one()
        assert version["id"] == "version-exact"
        assert version["flow_definition"] == FLOW
        # The runner refuses a published version with no exact digest, so the
        # reused snapshot gets one without its immutable payload changing.
        assert version["flow_sha256"] == MIG._sha256(FLOW)

        system = connection.execute(sa.select(systems)).mappings().one()
        assert system["published_flow_version_id"] == "version-exact"
        assert system["published_by"] == MIG.ACTOR
        assert system["flow_definition"] == FLOW

        draft = connection.execute(sa.select(drafts)).mappings().one()
        assert draft["revision"] == 1
        assert draft["flow_definition"] == FLOW
        assert draft["base_published_version_id"] == "version-exact"
        assert draft["flow_sha256"] == MIG._sha256(FLOW)


def test_appends_baseline_without_contract_when_no_exact_version_exists() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    old = {"schema_version": 3, "label": "old", "nodes": [], "edges": []}
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        connection.execute(
            systems.insert(),
            {"id": "system", "workspace_id": "ws", "flow_definition": FLOW},
        )
        connection.execute(
            versions.insert(),
            {
                "id": "version-old",
                "system_id": "system",
                "workspace_id": "ws",
                "version_number": 9,
                "flow_definition": old,
                "created_by": "legacy",
            },
        )

        _upgrade(connection)

        rows = (
            connection.execute(sa.select(versions).order_by(versions.c.version_number))
            .mappings()
            .all()
        )
        assert [row["version_number"] for row in rows] == [9, 10]
        appended = rows[1]
        assert appended["flow_definition"] == FLOW
        assert appended["release_kind"] == "migration"
        # Contracts compile from mutable Skills, which Alembic must not read.
        assert appended["execution_contract"] is None
        pointer = connection.execute(
            sa.select(systems.c.published_flow_version_id)
        ).scalar_one()
        assert pointer == appended["id"]


def test_system_with_pointer_but_no_draft_keeps_its_published_version() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        connection.execute(
            systems.insert(),
            {
                "id": "system",
                "workspace_id": "ws",
                "flow_definition": FLOW,
                "published_flow_version_id": "version-published",
                "published_by": "operator",
            },
        )
        connection.execute(
            versions.insert(),
            {
                "id": "version-published",
                "system_id": "system",
                "workspace_id": "ws",
                "version_number": 2,
                "flow_definition": FLOW,
                "created_by": "operator",
                "flow_sha256": MIG._sha256(FLOW),
                "release_kind": "publish",
            },
        )

        _upgrade(connection)

        system = connection.execute(sa.select(systems)).mappings().one()
        assert system["published_flow_version_id"] == "version-published"
        assert system["published_by"] == "operator"
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(versions)).scalar_one() == 1
        )
        draft = connection.execute(sa.select(drafts)).mappings().one()
        assert draft["base_published_version_id"] == "version-published"
        assert draft["revision"] == 1


def test_upgrade_is_idempotent_and_leaves_a_complete_system_untouched() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        connection.execute(
            systems.insert(),
            {
                "id": "system",
                "workspace_id": "ws",
                "flow_definition": FLOW,
                "published_flow_version_id": "version-published",
                "published_by": "operator",
            },
        )
        connection.execute(
            versions.insert(),
            {
                "id": "version-published",
                "system_id": "system",
                "workspace_id": "ws",
                "version_number": 1,
                "flow_definition": FLOW,
                "created_by": "operator",
                "flow_sha256": MIG._sha256(FLOW),
                "release_kind": "publish",
            },
        )
        connection.execute(
            drafts.insert(),
            {
                "system_id": "system",
                "workspace_id": "ws",
                "flow_definition": FLOW,
                "revision": 4,
                "flow_sha256": MIG._sha256(FLOW),
                "base_published_version_id": "version-published",
                "updated_by": "editor",
            },
        )

        _upgrade(connection)
        _upgrade(connection)

        draft = connection.execute(sa.select(drafts)).mappings().one()
        assert draft["revision"] == 4
        assert draft["updated_by"] == "editor"
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(versions)).scalar_one() == 1
        )


def test_downgrade_removes_only_rows_this_migration_authored() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        systems, versions, drafts = _schema(connection)
        # Separate statements: executemany compiles the INSERT from the first
        # mapping's keys and would silently drop the pointer columns.
        connection.execute(
            systems.insert(),
            {"id": "backfilled", "workspace_id": "ws", "flow_definition": FLOW},
        )
        connection.execute(
            systems.insert(),
            {
                "id": "edited",
                "workspace_id": "ws",
                "flow_definition": FLOW,
                "published_flow_version_id": "version-owned",
                "published_by": "operator",
            },
        )
        connection.execute(
            versions.insert(),
            {
                "id": "version-owned",
                "system_id": "edited",
                "workspace_id": "ws",
                "version_number": 1,
                "flow_definition": FLOW,
                "created_by": "operator",
                "flow_sha256": MIG._sha256(FLOW),
                "release_kind": "publish",
            },
        )

        _upgrade(connection)
        # An editor saves onto the draft the backfill just created.
        connection.execute(
            drafts.update()
            .where(drafts.c.system_id == "edited")
            .values(revision=2, updated_by="editor")
        )

        _downgrade(connection)

        remaining = {
            row["system_id"]: row
            for row in connection.execute(sa.select(drafts)).mappings().all()
        }
        assert set(remaining) == {"edited"}
        assert remaining["edited"]["revision"] == 2

        pointers = {
            row["id"]: row["published_flow_version_id"]
            for row in connection.execute(sa.select(systems)).mappings().all()
        }
        assert pointers["backfilled"] is None
        assert pointers["edited"] == "version-owned"
