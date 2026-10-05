"""Source edges pin real reader dependencies; references never contain credentials."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.services.chains.dag_validator import validate_flow
from app.services.connectors.generic.postgresql_claims import CLAIM_RESOURCES
from app.services.ecommerce_flow_sources import with_data_sources
from app.services.flow_data_sources import (
    bound_data_sources,
    connector_reference,
    require_postgresql_binding,
)

BLUEPRINT = (
    Path(__file__).resolve().parents[2] / "resources/flows/showcase_ecommerce_claims_v1.json"
)


def flow():
    return json.loads(BLUEPRINT.read_text())


def test_luma_links_sql_to_investigation_and_live_action_recheck():
    graph = with_data_sources(flow(), ["luma-regles", "luma-preuves"])
    assert not [issue.to_dict() for issue in validate_flow(graph) if issue.level == "error"]
    assert not [issue for issue in validate_flow(graph) if issue.code == "asset_no_collection"]
    sources = bound_data_sources(graph, "loop.investigate")
    assert len(sources) == 3
    pg = require_postgresql_binding(
        SimpleNamespace(flow_snapshot=graph), sources, resources=CLAIM_RESOURCES
    )
    assert pg["node_id"] == "asset.postgresql"
    assert (
        require_postgresql_binding(
            SimpleNamespace(flow_snapshot=graph),
            bound_data_sources(graph, "task.simulate"),
            resources=CLAIM_RESOURCES,
        )
        == pg
    )
    assert with_data_sources(graph, ["luma-regles", "luma-preuves"]) == graph


@pytest.mark.parametrize("change", ["edge", "table", "source", "mode"])
def test_luma_missing_dependency_fails_before_any_sql(change):
    graph = flow()
    if change == "edge":
        graph["edges"] = [e for e in graph["edges"] if e["from"] != "asset.postgresql"]
    elif change == "table":
        graph["nodes"][0]["config"]["resources"].pop()
    elif change == "source":
        graph["nodes"] = [node for node in graph["nodes"] if node["id"] != "asset.postgresql"]
    else:
        graph["nodes"][0]["config"]["read_mode"] = "reference"
    with pytest.raises(ValueError, match="CLAIM_DATA_SOURCE"):
        require_postgresql_binding(
            SimpleNamespace(flow_snapshot=graph),
            bound_data_sources(graph, "loop.investigate"),
            resources=CLAIM_RESOURCES,
        )
    assert any(issue.code == "data_source_invalid" for issue in validate_flow(graph))


@pytest.mark.parametrize(
    "patch",
    [
        {"password": "must-not-be-stored"},
        {"host": "db.example.test"},
        {"connector_id": "unknown"},
        {"read_mode": {}},
        {"resources": [{"schema": "public", "table": "orders", "sql": "SELECT 1"}]},
    ],
)
def test_source_contract_rejects_credentials_connection_values_and_caller_sql(patch):
    source = flow()["nodes"][0]
    source["config"].update(patch)
    with pytest.raises(ValueError, match="DATA_SOURCE"):
        connector_reference(source)
    assert any(
        issue.code == "data_source_invalid"
        for issue in validate_flow({"nodes": [source], "edges": []})
    )


@pytest.mark.asyncio
async def test_sql_snapshot_records_frozen_source_and_refuses_missing_binding(monkeypatch):
    from app.services import ecommerce_claims as claims

    graph = flow()
    run = SimpleNamespace(flow_snapshot=graph)
    monkeypatch.setattr(claims, "_run", lambda *_: (object(), run, {}, "RC-1043"))
    reader = Mock(
        return_value={
            "data": {"context": [{"claim_id": "RC-1043"}]},
            "provenance": {"read_mode": "live", "snapshot_sha256": "measured"},
        }
    )
    monkeypatch.setattr(claims.pg, "snapshot", reader)
    db = Mock()
    with pytest.raises(ValueError, match="BINDING_REQUIRED"):
        await claims.invoke("snapshot", {}, {"db": db})
    reader.assert_not_called()
    sources = bound_data_sources(graph, "loop.investigate")
    result = await claims.invoke("snapshot", {}, {"db": db, "_flow_data_sources": sources})
    assert result["provenance"]["flow_data_source"] == sources[0]
    assert result["provenance"]["snapshot_sha256"] == "measured"


@pytest.mark.asyncio
@pytest.mark.parametrize("sources", [[], [{"collection_slug": "another-collection"}]])
async def test_declared_document_sources_cannot_fall_back_to_implicit_retrieval(
    monkeypatch, sources
):
    from app.services import ecommerce_claims as claims
    from app.services.skills_registry import wrappers

    graph = with_data_sources(flow(), ["luma-maison-regles"])
    # Even deleting every document edge must not enable legacy implicit reads.
    graph["edges"] = [e for e in graph["edges"] if not e["from"].startswith("asset.collection.")]
    run = SimpleNamespace(flow_snapshot=graph)
    monkeypatch.setattr(
        claims,
        "_sources",
        lambda *_: [(None, None, SimpleNamespace(slug="luma-maison-regles"))],
    )
    retrieval = Mock()
    monkeypatch.setattr(wrappers, "_semantic_search_v1", retrieval)
    with pytest.raises(ValueError, match="CLAIM_SOURCE_OUTSIDE_FLOW_BINDING"):
        await claims._evidence(
            None,
            None,
            run,
            {},
            {"provenance": {"snapshot_sha256": "facts"}},
            "policy",
            {"_flow_data_sources": sources},
        )
    retrieval.assert_not_called()


@pytest.mark.asyncio
async def test_dag_delivers_frozen_references_and_overrides_caller_forgery(db_session, monkeypatch):
    from app.models.run import Run
    from app.models.skill import Skill
    from app.models.system import System
    from app.services.run_engine import engine
    from app.services.run_engine.dag import execute_run_dag

    source = flow()["nodes"][0]
    graph = {
        "schema_version": 3,
        "nodes": [
            {"id": "request", "type": "source", "kind": "source"},
            source,
            {
                "id": "reader",
                "type": "task",
                "kind": "task",
                "config": {"skill_slug": "source_test_reader"},
            },
            {"id": "answer", "type": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "request", "to": "reader"},
            {"from": "asset.postgresql", "to": "reader"},
            {"from": "reader", "to": "answer"},
        ],
    }
    skill = Skill(
        id=str(uuid4()),
        slug="source_test_reader",
        version="1",
        name="Source reader",
        input_schema={},
        output_schema={},
        execution={"mode": "sync"},
        pricing={},
    )
    system = System(
        id=str(uuid4()),
        name="Source bindings",
        objective="Test",
        status="active",
        skill_ids=[skill.id],
        flow_definition=copy.deepcopy(graph),
    )
    db_session.add_all([skill, system])
    db_session.commit()
    run = Run(
        id=str(uuid4()),
        system_id=system.id,
        status="pending",
        flow_snapshot=copy.deepcopy(graph),
        input_ref={"_flow_data_sources": [{"connector_id": "forged"}]},
    )
    db_session.add(run)
    db_session.commit()
    # Mutable System edits cannot change a Run's pinned reference.
    system.flow_definition = {**graph, "nodes": graph["nodes"][1:]}
    db_session.commit()
    seen = []

    async def reader(_, ctx):
        seen.extend(ctx["_flow_data_sources"])
        return {"read": True}

    monkeypatch.setattr(engine, "resolve_skill", lambda _: reader)
    await execute_run_dag(run.id)
    db_session.refresh(run)
    assert run.status == "completed", run.error
    assert seen == [connector_reference(source)]
    assert any(
        cp.get("node_id") == "asset.postgresql" and cp.get("kind") == "node_end"
        for cp in run.checkpoints
    )


def test_upgrade_is_reviewable_atomic_and_retargets_work_to_new_immutable_version(
    db_session, monkeypatch
):
    from app.models.experience import ExperienceDeployment, ExperienceRelease
    from app.models.system_version import SystemVersion
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember
    from app.services import ecommerce_claims as claims
    from app.services import ecommerce_install as install_module
    from app.services.ecommerce_source_upgrade import upgrade
    from app.services.experience import bindings

    workspace = Workspace(id=str(uuid4()), name="Luma", slug="source-upgrade-qa", settings={})
    actor = User(
        id=str(uuid4()), username="source-upgrade-owner", email="source-upgrade@example.test"
    )
    db_session.add_all([workspace, actor])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=actor.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        install_module.pg,
        "snapshot",
        lambda *_: {"data": {"documents": []}, "provenance": {"snapshot_sha256": "snapshot"}},
    )
    monkeypatch.setattr(claims, "_sources", lambda *_: [])
    legacy = flow()
    legacy["nodes"] = [n for n in legacy["nodes"] if n["kind"] != "asset"]
    legacy["edges"] = [e for e in legacy["edges"] if e["from"] != "asset.postgresql"]
    legacy.pop("runtime_contract")
    monkeypatch.setattr(install_module, "with_data_sources", lambda *_: legacy)
    protocol = json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "docs/demo-runs/showcase-ecommerce/fixtures/benchmark/protocol.json"
        ).read_text()
    )
    installed = install_module.install(
        db_session,
        workspace,
        actor,
        policy_sha256="a" * 64,
        source_collections=["luma-regles"],
        benchmark=protocol,
    )
    db_session.commit()
    old_version = db_session.get(SystemVersion, installed["published_flow_version_id"])
    old_flow = copy.deepcopy(old_version.flow_definition)
    from app.models.system import System
    from app.services.systems import flow_publication

    system = db_session.get(System, installed["system_id"])
    state = flow_publication.flow_state(db_session, system=system, workspace=workspace)
    positioned = copy.deepcopy(old_flow)
    positioned.update(
        {
            "collections": [],
            "rag_mode": "OmniRAG",
            "canonical_rag_mode": "chah",
            "context_reused": False,
        }
    )
    positioned["nodes"][0]["position"] = {"x": 0, "y": 66}
    flow_publication.save_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        flow_definition=positioned,
        expected_revision=state["draft"]["revision"],
        actor=actor.email,
    )
    db_session.commit()
    kwargs = {
        "system_id": installed["system_id"],
        "expected_flow_sha256": old_version.flow_sha256,
        "expected_release_id": installed["release_id"],
        "channel": "pilot",
    }
    reviewed = upgrade(db_session, workspace, actor, **kwargs)
    assert reviewed["changed"] and not reviewed["applied"]
    assert (
        db_session.get(ExperienceDeployment, installed["deployment_id"]).release_id
        == installed["release_id"]
    )
    with pytest.raises(ValueError, match="FLOW_CHANGED"):
        upgrade(
            db_session, workspace, actor, **{**kwargs, "expected_flow_sha256": "0" * 64}, apply=True
        )
    with pytest.raises(ValueError, match="TARGET_NOT_REVIEWED"):
        upgrade(db_session, workspace, actor, **kwargs, apply=True)
    result = upgrade(
        db_session,
        workspace,
        actor,
        **kwargs,
        apply=True,
        expected_target_sha256=reviewed["flow_sha256"],
    )
    db_session.commit()
    binding = bindings.get_binding(
        db_session, workspace_id=workspace.id, binding_key="showcase.claims.investigate"
    )
    release = db_session.get(ExperienceRelease, result["release_id"])
    assert binding.published_flow_version_id == result["published_flow_version_id"]
    assert (
        release.bindings_snapshot[0]["published_flow_version_id"]
        == binding.published_flow_version_id
    )
    assert db_session.get(SystemVersion, old_version.id).flow_definition == old_flow
    assert (
        db_session.get(ExperienceDeployment, installed["deployment_id"]).release_id
        == result["release_id"]
    )
    new_flow = db_session.get(SystemVersion, result["published_flow_version_id"]).flow_definition
    assert (
        db_session.get(SystemVersion, result["published_flow_version_id"]).flow_sha256
        == reviewed["flow_sha256"]
    )
    assert next(n for n in new_flow["nodes"] if n["id"] == "source.request")["position"] == {
        "x": 0,
        "y": 66,
    }
    assert (
        next(n for n in new_flow["nodes"] if n["id"] == "asset.postgresql")["position"]["x"] == -360
    )


def test_upgrade_refuses_unpublished_business_edits():
    from app.services.ecommerce_flow_sources import reviewed_source_base

    published, draft = flow(), flow()
    next(n for n in draft["nodes"] if n["id"] == "loop.investigate")["config"]["budget"][
        "max_turns"
    ] = 99
    with pytest.raises(ValueError, match="UNPUBLISHED_DRAFT"):
        reviewed_source_base(published, draft)
