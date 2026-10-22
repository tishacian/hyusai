"""A builder observing old executions must not inherit today's Flow identity."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import runs
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_engine.execution_contract import canonical_flow_sha256


def _client(db, workspace, user):
    app = FastAPI()
    app.include_router(runs.router, prefix="/runs")
    app.dependency_overrides[runs.get_current_workspace] = lambda: workspace
    app.dependency_overrides[runs.get_current_user] = lambda: user
    app.dependency_overrides[runs.get_db] = lambda: db
    return TestClient(app)


def _context(db):
    workspace = Workspace(id="observe-ws", slug="observe", name="Observe")
    user = User(id="observe-user", username="observe-user", role="admin", is_active=True)
    system = System(
        id="observe-system",
        workspace_id=workspace.id,
        name="Observe",
        flow_definition={"nodes": [{"id": "new-draft-node", "kind": "sink"}], "edges": []},
        published_flow_version_id="current-publication",
    )
    db.add_all([workspace, user, system])
    db.commit()
    return workspace, user, system


def test_list_and_detail_retain_execution_identity_when_the_flow_changes(db_session):
    workspace, user, system = _context(db_session)
    snapshot = {"nodes": [{"id": "forecast", "kind": "task", "label": "Prévision"}], "edges": []}
    digest = canonical_flow_sha256(snapshot)
    now = datetime(2026, 10, 22, 10)
    old = Run(
        id="old-observed-run",
        workspace_id=workspace.id,
        system_id=system.id,
        flow_version_id="old-publication",
        flow_sha256=digest,
        flow_snapshot=snapshot,
        execution_surface="published_manual",
        status="completed",
        started_at=now,
        completed_at=now + timedelta(seconds=1),
    )
    legacy = Run(
        id="legacy-observed-run",
        workspace_id=workspace.id,
        system_id=system.id,
        flow_snapshot=None,
        status="completed",
        started_at=now - timedelta(days=1),
    )
    db_session.add_all([old, legacy])
    db_session.commit()
    client = _client(db_session, workspace, user)

    listing = client.get("/runs", params={"system_id": system.id})
    assert listing.status_code == 200, listing.text
    rows = {item["id"]: item for item in listing.json()["runs"]}
    detail = client.get(f"/runs/{old.id}")
    assert detail.status_code == 200, detail.text
    for payload in (rows[old.id], detail.json()):
        assert payload["flow_version_id"] == "old-publication"
        assert payload["flow_sha256"] == digest
        assert payload["execution_surface"] == "published_manual"
        assert "flow_snapshot" not in payload
    assert rows[legacy.id]["flow_version_id"] is None
    assert rows[legacy.id]["flow_sha256"] is None
    assert rows[legacy.id]["execution_surface"] is None
    assert system.flow_definition["nodes"][0]["id"] == "new-draft-node"
    assert system.published_flow_version_id == "current-publication"
    assert old.flow_snapshot == snapshot


def test_new_provenance_does_not_expose_foreign_run(db_session):
    workspace, user, system = _context(db_session)
    foreign = Workspace(id="foreign-observe-ws", slug="foreign-observe", name="Foreign")
    foreign_system = System(id="foreign-observe-system", workspace_id=foreign.id, name="Foreign")
    foreign_run = Run(
        id="foreign-observed-run",
        workspace_id=foreign.id,
        system_id=foreign_system.id,
        flow_version_id="private-version",
        flow_sha256="a" * 64,
        status="completed",
    )
    db_session.add_all([foreign, foreign_system, foreign_run])
    db_session.commit()
    client = _client(db_session, workspace, user)
    assert client.get(f"/runs/{foreign_run.id}").status_code == 404
    for identifier in (system.id, foreign_system.id):
        result = client.get("/runs", params={"system_id": identifier})
        assert result.status_code == 200
        assert result.json()["runs"] == []


def test_held_result_keeps_provenance_but_masks_invocation_inputs_and_outputs(db_session):
    workspace, user, system = _context(db_session)
    run = Run(
        id="held-observed-run",
        workspace_id=workspace.id,
        system_id=system.id,
        flow_version_id="held-version",
        flow_sha256="b" * 64,
        status="hitl_pending",
        checkpoints=[{"kind": "hitl_pause", "node_id": "approval", "membrane_egress": True}],
    )
    invocation = SkillInvocation(
        id="held-observed-invocation",
        run_id=run.id,
        skill_slug="workspace_llm_v1",
        status="completed",
        input_ref={"prompt": "held input"},
        output_ref={"answer": "held output"},
        trace={"node_id": "answer"},
    )
    db_session.add_all([run, invocation])
    db_session.commit()
    response = _client(db_session, workspace, user).get(f"/runs/{run.id}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["result_held"] is True
    assert result["flow_version_id"] == "held-version"
    assert result["flow_sha256"] == "b" * 64
    assert result["invocations"][0]["input_ref"] == {}
    assert result["invocations"][0]["output_ref"] == {}
    assert result["invocations"][0]["trace"]["node_id"] == "answer"
