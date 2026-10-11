"""Atomic data migration contract for the explicit Andritz Decisions."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "078_andritz_decision_contract.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_078", path)
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


def _current_flow() -> dict:
    path = (
        Path(__file__).resolve().parents[2]
        / "resources"
        / "flows"
        / "andritz_chat_agentic_v3.json"
    )
    return deepcopy(json.loads(path.read_text(encoding="utf-8"))["flow_definition"])


def _old_flow() -> dict:
    flow = _current_flow()
    route = next(node for node in flow["nodes"] if node["id"] == "decision.route_mode")
    route["config"]["branches"] = [
        branch
        for branch in route["config"]["branches"]
        if branch["label"] != "balanced"
    ]
    deliver = next(node for node in flow["nodes"] if node["id"] == "decision.deliver")
    deliver["config"]["branches"] = [
        branch
        for branch in deliver["config"]["branches"]
        if branch["label"] != "deliver"
    ]
    flow["edges"] = [
        edge
        for edge in flow["edges"]
        if not (
            edge.get("from") == "decision.verdict"
            and edge.get("to") == "join.answer"
            and edge.get("branch_label") == "strong"
        )
    ]
    return flow


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
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
        sa.Column("published_flow_version_id", sa.String(36)),
        sa.Column("published_by", sa.String(255)),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
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
        sa.Column("updated_at", sa.DateTime()),
    )
    metadata.create_all(connection)
    return workspaces, systems, versions, drafts


def _workspace_settings() -> dict:
    return {
        "family": "andritz",
        MIG.ROLLOUT_MARKER: {
            "revision": "059_andritz_agentic_default",
            "schema": 1,
            "system_id": "system-agentic",
            "applied": {"flow_revision": MIG.OLD_FLOW_REVISION},
        },
    }


def _seed(connection, *, flow: dict, custom: bool = False):
    workspaces, systems, versions, drafts = _schema(connection)
    connection.execute(
        workspaces.insert(),
        {"id": "workspace-andritz", "settings": _workspace_settings()},
    )
    connection.execute(
        systems.insert(),
        {
            "id": "system-agentic",
            "workspace_id": "workspace-andritz",
            "settings": {
                "system_type": MIG.SYSTEM_TYPE,
                "flow_revision": MIG.OLD_FLOW_REVISION,
                "custom": custom,
            },
            "flow_definition": flow,
            "published_flow_version_id": "version-old",
            "published_by": "migration-077",
        },
    )
    connection.execute(
        versions.insert(),
        {
            "id": "version-old",
            "system_id": "system-agentic",
            "workspace_id": "workspace-andritz",
            "version_number": 1,
            "flow_definition": flow,
            "created_by": "migration-077",
            "flow_sha256": MIG._flow_sha256(flow),
            "release_kind": "migration",
            "draft_revision": 1,
        },
    )
    connection.execute(
        drafts.insert(),
        {
            "system_id": "system-agentic",
            "workspace_id": "workspace-andritz",
            "flow_definition": flow,
            "revision": 1,
            "flow_sha256": MIG._flow_sha256(flow),
            "base_published_version_id": "version-old",
            "updated_by": "migration-077",
        },
    )
    return workspaces, systems, versions, drafts


def test_revision_extends_publication_migration_and_artifacts_are_pinned() -> None:
    assert MIG.revision == "078_andritz_decision_contract"
    assert MIG.down_revision == "077_flow_publication_v1"
    assert len(MIG.revision) <= 32
    assert MIG._contract_sha256(_old_flow()) == MIG.OLD_CONTRACT_SHA256
    assert MIG._contract_sha256(_current_flow()) == MIG.NEW_CONTRACT_SHA256


def test_upgrade_appends_published_version_updates_clean_draft_and_round_trips() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    old_flow = _old_flow()
    with engine.begin() as connection:
        workspaces, systems, versions, drafts = _seed(connection, flow=old_flow)

        MIG._upgrade(connection)

        system = connection.execute(sa.select(systems)).mappings().one()
        assert system["flow_definition"] == _current_flow()
        assert system["published_flow_version_id"] != "version-old"
        assert system["settings"]["flow_revision"] == MIG.NEW_FLOW_REVISION
        state = system["settings"][MIG.STATE_KEY]
        assert state["graph_changed"] is True
        assert state["draft_upgraded"] is True
        assert state["old_published_version_id"] == "version-old"
        assert connection.execute(sa.select(sa.func.count()).select_from(versions)).scalar_one() == 2
        old_version = connection.execute(
            sa.select(versions).where(versions.c.id == "version-old")
        ).mappings().one()
        assert old_version["flow_definition"] == old_flow
        draft = connection.execute(sa.select(drafts)).mappings().one()
        assert draft["flow_definition"] == _current_flow()
        assert draft["revision"] == 2
        assert draft["base_published_version_id"] == system["published_flow_version_id"]
        marker = connection.execute(sa.select(workspaces.c.settings)).scalar_one()
        assert marker[MIG.ROLLOUT_MARKER]["applied"]["flow_revision"] == MIG.NEW_FLOW_REVISION

        MIG._downgrade(connection)

        restored = connection.execute(sa.select(systems)).mappings().one()
        assert restored["flow_definition"] == old_flow
        assert restored["published_flow_version_id"] == "version-old"
        assert restored["settings"]["flow_revision"] == MIG.OLD_FLOW_REVISION
        assert MIG.STATE_KEY not in restored["settings"]
        restored_draft = connection.execute(sa.select(drafts)).mappings().one()
        assert restored_draft["flow_definition"] == old_flow
        assert restored_draft["revision"] == 3
        assert connection.execute(sa.select(sa.func.count()).select_from(versions)).scalar_one() == 2


def test_fresh_install_with_current_graph_advances_revision_without_version_churn() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _workspaces, systems, versions, drafts = _seed(
            connection,
            flow=_current_flow(),
        )

        MIG._upgrade(connection)

        system = connection.execute(sa.select(systems)).mappings().one()
        assert system["published_flow_version_id"] == "version-old"
        assert system["settings"][MIG.STATE_KEY]["graph_changed"] is False
        assert connection.execute(sa.select(sa.func.count()).select_from(versions)).scalar_one() == 1
        assert connection.execute(sa.select(drafts.c.revision)).scalar_one() == 1


def test_unrecognized_graph_is_left_byte_for_byte_untouched() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    custom = _old_flow()
    custom["nodes"][0]["config"] = {"operator_extension": True}
    with engine.begin() as connection:
        workspaces, systems, versions, drafts = _seed(
            connection,
            flow=custom,
            custom=True,
        )
        before_workspace = connection.execute(sa.select(workspaces)).mappings().one()
        before_system = connection.execute(sa.select(systems)).mappings().one()
        before_versions = connection.execute(sa.select(versions)).mappings().all()
        before_draft = connection.execute(sa.select(drafts)).mappings().one()

        MIG._upgrade(connection)

        assert connection.execute(sa.select(workspaces)).mappings().one() == before_workspace
        assert connection.execute(sa.select(systems)).mappings().one() == before_system
        assert connection.execute(sa.select(versions)).mappings().all() == before_versions
        assert connection.execute(sa.select(drafts)).mappings().one() == before_draft
