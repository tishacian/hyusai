"""P1 durable operator Runner boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import flow_runner as endpoint
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import Session as SessionModel
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication


def _flow() -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
        "additionalProperties": False,
    }
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "manual.input",
                "kind": "source",
                "config": {"ingress_kind": "manual", "input_schema": schema},
            },
            {
                "id": "http.input",
                "kind": "source",
                "config": {"ingress_kind": "http", "input_schema": schema},
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [
            {"from": "manual.input", "to": "result", "kind": "data"},
            {"from": "http.input", "to": "result", "kind": "data"},
        ],
    }


def _seed(db_session, *, enabled: bool = True):
    workspace = Workspace(
        id="ws-runner",
        slug="runner",
        name="Runner",
        settings={
            "features": {
                "flow_publication_v1": enabled,
                "flow_v3_dag_authoritative": True,
            }
        },
    )
    user = User(
        id="user-runner",
        username="runner@example.invalid",
        email="runner@example.invalid",
        role="admin",
    )
    other = User(
        id="user-other",
        username="other@example.invalid",
        email="other@example.invalid",
        role="admin",
    )
    flow = _flow()
    system = System(
        id="system-runner",
        workspace_id=workspace.id,
        name="Published runner",
        objective="test",
        flow_definition=flow,
        status="active",
    )
    db_session.add_all([workspace, user, other, system])
    db_session.flush()
    contract = flow_publication.compile_execution_contract(db_session, flow, workspace)
    version = SystemVersion(
        id="version-runner",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        release_kind="publish",
        draft_revision=1,
        execution_contract=contract,
        message="published",
        created_by=user.email,
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    system.published_by = user.email
    system.published_at = datetime.utcnow()
    db_session.commit()
    return workspace, user, other, system, version


def _client(db_session, workspace: Workspace, user: User, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/systems")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    monkeypatch.setattr(endpoint, "schedule_run", lambda _run_id: None)
    return TestClient(app)


def test_runner_is_feature_gated_without_creating_state(db_session, monkeypatch) -> None:
    workspace, user, _other, system, _version = _seed(db_session, enabled=False)
    client = _client(db_session, workspace, user, monkeypatch)

    response = client.get(f"/systems/{system.id}/runner")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "FLOW_PUBLICATION_DISABLED"
    assert db_session.query(SessionModel).count() == 0


def test_runner_session_is_durable_typed_and_exposes_only_published_manual_ingress(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, _other, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)

    created = client.post(
        f"/systems/{system.id}/runner/sessions",
        json={"title": "Password resets"},
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["published"]["published_flow_version_id"] == version.id
    assert body["published"]["flow_sha256"] == version.flow_sha256
    assert body["published"]["runtime_mode"] == "dag_strict"
    assert [row["ingress_id"] for row in body["published"]["ingresses"]] == [
        "manual.input"
    ]
    assert "flow_definition" not in body["published"]
    assert "draft" not in body

    session_id = body["session"]["id"]
    db_session.expire_all()
    persisted = db_session.get(SessionModel, session_id)
    assert persisted is not None
    assert persisted.user_id == user.id
    assert persisted.workspace_id == workspace.id
    assert persisted.meta_data == {
        "kind": "flow_runner",
        "schema_version": 1,
        "system_id": system.id,
    }

    overview = client.get(f"/systems/{system.id}/runner")
    assert overview.status_code == 200
    assert [row["id"] for row in overview.json()["sessions"]] == [session_id]
    resumed = client.get(f"/systems/{system.id}/runner/sessions/{session_id}")
    assert resumed.status_code == 200
    assert resumed.json()["runs"] == []


def test_invalid_runner_input_and_stale_evidence_create_zero_runs(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, _other, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    session = client.post(f"/systems/{system.id}/runner/sessions", json={}).json()[
        "session"
    ]
    endpoint_url = f"/systems/{system.id}/runner/sessions/{session['id']}/runs"
    before = db_session.query(Run).count()

    invalid = client.post(
        endpoint_url,
        json={
            "ingress_id": "manual.input",
            "payload": {"query": 42},
            "expected_published_version_id": version.id,
            "expected_flow_sha256": version.flow_sha256,
        },
    )
    stale = client.post(
        endpoint_url,
        json={
            "ingress_id": "manual.input",
            "payload": {"query": "reset"},
            "expected_published_version_id": "stale-version",
            "expected_flow_sha256": version.flow_sha256,
        },
    )
    debugger_smuggle = client.post(
        endpoint_url,
        json={
            "ingress_id": "manual.input",
            "payload": {"query": "reset", "_debug": {"mode": "step"}},
            "expected_published_version_id": version.id,
            "expected_flow_sha256": version.flow_sha256,
        },
    )

    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "INGRESS_PAYLOAD_INVALID"
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "PUBLISHED_FLOW_VERSION_MISMATCH"
    assert debugger_smuggle.status_code == 422
    assert debugger_smuggle.json()["detail"]["code"] == "RUN_DEBUG_SURFACE_FORBIDDEN"
    assert db_session.query(Run).count() == before


def test_runner_executes_published_evidence_and_lists_only_its_session_runs(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, _other, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    session = client.post(f"/systems/{system.id}/runner/sessions", json={}).json()[
        "session"
    ]

    response = client.post(
        f"/systems/{system.id}/runner/sessions/{session['id']}/runs",
        json={
            "ingress_id": "manual.input",
            "payload": {"query": "reset password"},
            "expected_published_version_id": version.id,
            "expected_flow_sha256": version.flow_sha256,
        },
    )

    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    persisted = db_session.get(Run, run_id)
    assert persisted is not None
    assert persisted.runner_session_id == session["id"]
    assert persisted.initiated_by_user_id == user.id
    assert persisted.published_flow_version_id == version.id
    assert persisted.flow_sha256 == version.flow_sha256
    assert persisted.execution_surface == "published_manual"
    assert persisted.input_ref["_ingress"]["adapter"] == {
        "surface": "operator_runner"
    }

    detail = client.get(
        f"/systems/{system.id}/runner/sessions/{session['id']}"
    ).json()
    assert [row["id"] for row in detail["runs"]] == [run_id]
    assert detail["runs"][0]["runtime_mode"] == "dag_strict"


def test_runner_session_access_is_owner_only_and_fails_as_not_found(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, other, system, _version = _seed(db_session)
    owner_client = _client(db_session, workspace, user, monkeypatch)
    session_id = owner_client.post(
        f"/systems/{system.id}/runner/sessions", json={}
    ).json()["session"]["id"]
    other_client = _client(db_session, workspace, other, monkeypatch)

    read = other_client.get(
        f"/systems/{system.id}/runner/sessions/{session_id}"
    )
    execute = other_client.post(
        f"/systems/{system.id}/runner/sessions/{session_id}/runs",
        json={
            "ingress_id": "manual.input",
            "payload": {"query": "forbidden"},
            "expected_published_version_id": "version-runner",
            "expected_flow_sha256": canonical_flow_sha256(_flow()),
        },
    )

    assert read.status_code == 404
    assert execute.status_code == 404
    assert db_session.query(Run).count() == 0


def test_runner_system_and_session_are_not_disclosed_across_tenants(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, _other, system, _version = _seed(db_session)
    owner_client = _client(db_session, workspace, user, monkeypatch)
    session_id = owner_client.post(
        f"/systems/{system.id}/runner/sessions", json={}
    ).json()["session"]["id"]
    foreign_workspace = Workspace(
        id="ws-foreign-runner",
        slug="foreign-runner",
        name="Foreign Runner",
        settings={"features": {"flow_publication_v1": True}},
    )
    db_session.add(foreign_workspace)
    db_session.commit()
    foreign_client = _client(db_session, foreign_workspace, user, monkeypatch)

    overview = foreign_client.get(f"/systems/{system.id}/runner")
    session = foreign_client.get(
        f"/systems/{system.id}/runner/sessions/{session_id}"
    )

    assert overview.status_code == 404
    assert session.status_code == 404


def test_archived_runner_session_cannot_accept_a_run(db_session, monkeypatch) -> None:
    workspace, user, _other, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    session_id = client.post(
        f"/systems/{system.id}/runner/sessions", json={}
    ).json()["session"]["id"]
    persisted = db_session.get(SessionModel, session_id)
    assert persisted is not None
    persisted.status = "archived"
    db_session.commit()

    response = client.post(
        f"/systems/{system.id}/runner/sessions/{session_id}/runs",
        json={
            "ingress_id": "manual.input",
            "payload": {"query": "should not execute"},
            "expected_published_version_id": version.id,
            "expected_flow_sha256": version.flow_sha256,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RUNNER_SESSION_INACTIVE"
    assert db_session.query(Run).count() == 0


def test_runner_preserves_managed_agentic_admin_execution_guard(
    db_session,
    monkeypatch,
) -> None:
    workspace, _admin, viewer, system, version = _seed(db_session)
    viewer.role = "viewer"
    client = _client(db_session, workspace, viewer, monkeypatch)
    session_id = client.post(
        f"/systems/{system.id}/runner/sessions",
        json={},
    ).json()["session"]["id"]
    workspace.settings = {
        **workspace.settings,
        "_migration_059_andritz_agentic_default_state": {
            "revision": "059_andritz_agentic_default",
            "schema": 1,
            "system_id": system.id,
        },
    }
    db_session.commit()

    response = client.post(
        f"/systems/{system.id}/runner/sessions/{session_id}/runs",
        json={
            "ingress_id": "manual.input",
            "payload": {"query": "forbidden"},
            "expected_published_version_id": version.id,
            "expected_flow_sha256": version.flow_sha256,
        },
    )

    assert response.status_code == 403
    assert db_session.query(Run).count() == 0
