"""Published ingress HTTP boundary stays feature-gated and manual-only."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import flow_ingresses as endpoint
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
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
        id="ws-ingress-api",
        slug="ingress-api",
        name="Ingress API",
        settings={"features": {"flow_publication_v1": enabled}},
    )
    admin = User(
        id="user-ingress-admin",
        username="ingress-admin@example.invalid",
        email="ingress-admin@example.invalid",
        role="admin",
    )
    viewer = User(
        id="user-ingress-viewer",
        username="ingress-viewer@example.invalid",
        email="ingress-viewer@example.invalid",
        role="viewer",
    )
    flow = _flow()
    system = System(
        id="system-ingress-api",
        workspace_id=workspace.id,
        name="Published ingress API",
        objective="test",
        status="active",
        flow_definition=flow,
    )
    db_session.add_all([workspace, admin, viewer, system])
    db_session.flush()
    contract = flow_publication.compile_execution_contract(db_session, flow, workspace)
    version = SystemVersion(
        id="version-ingress-api",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        release_kind="publish",
        draft_revision=1,
        execution_contract=contract,
        message="published",
        created_by=admin.email,
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    system.published_by = admin.email
    system.published_at = datetime.utcnow()
    db_session.commit()
    return workspace, admin, viewer, system, version


def _client(db_session, workspace: Workspace, user: User, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/systems")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    monkeypatch.setattr(endpoint, "schedule_run", lambda _run_id: None)
    return TestClient(app)


def _run_body(version: SystemVersion, *, kind: str = "manual") -> dict[str, Any]:
    return {
        "kind": kind,
        "payload": {"query": "reset password"},
        "expected_published_version_id": version.id,
        "expected_flow_sha256": version.flow_sha256,
    }


def test_ingress_api_is_feature_gated_before_read_or_run(
    db_session,
    monkeypatch,
) -> None:
    workspace, admin, _viewer, system, version = _seed(db_session, enabled=False)
    client = _client(db_session, workspace, admin, monkeypatch)

    listed = client.get(f"/systems/{system.id}/ingresses")
    executed = client.post(
        f"/systems/{system.id}/ingresses/manual.input/runs",
        json=_run_body(version),
    )

    assert listed.status_code == 404
    assert listed.json()["detail"]["code"] == "FLOW_PUBLICATION_DISABLED"
    assert executed.status_code == 404
    assert executed.json()["detail"]["code"] == "FLOW_PUBLICATION_DISABLED"
    assert db_session.query(Run).count() == 0


@pytest.mark.parametrize("kind", ["chat", "http", "schedule", "event"])
def test_operator_ingress_cannot_impersonate_adapter_kind(
    db_session,
    monkeypatch,
    kind: str,
) -> None:
    workspace, admin, _viewer, system, version = _seed(db_session)
    response = _client(db_session, workspace, admin, monkeypatch).post(
        f"/systems/{system.id}/ingresses/http.input/runs",
        json=_run_body(version, kind=kind),
    )

    assert response.status_code == 422
    assert db_session.query(Run).count() == 0


def test_operator_ingress_cannot_smuggle_builder_debugger_controls(
    db_session,
    monkeypatch,
) -> None:
    workspace, admin, _viewer, system, version = _seed(db_session)
    body = _run_body(version)
    body["payload"]["_debug"] = {"mode": "step"}

    response = _client(db_session, workspace, admin, monkeypatch).post(
        f"/systems/{system.id}/ingresses/manual.input/runs",
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "RUN_DEBUG_SURFACE_FORBIDDEN"
    assert db_session.query(Run).count() == 0


def test_manual_ingress_requires_strong_pointer_and_freezes_published_run(
    db_session,
    monkeypatch,
) -> None:
    workspace, admin, _viewer, system, version = _seed(db_session)
    client = _client(db_session, workspace, admin, monkeypatch)

    missing_pointer = client.post(
        f"/systems/{system.id}/ingresses/manual.input/runs",
        json={**_run_body(version), "expected_published_version_id": None},
    )
    accepted = client.post(
        f"/systems/{system.id}/ingresses/manual.input/runs",
        json=_run_body(version),
    )

    assert missing_pointer.status_code == 422
    assert accepted.status_code == 201, accepted.text
    run = db_session.get(Run, accepted.json()["id"])
    assert run is not None
    assert run.execution_surface == "published_manual"
    assert run.published_flow_version_id == version.id
    assert run.flow_sha256 == version.flow_sha256


def test_managed_agentic_system_keeps_admin_only_execution_guard(
    db_session,
    monkeypatch,
) -> None:
    workspace, _admin, viewer, system, version = _seed(db_session)
    workspace.settings = {
        **workspace.settings,
        "_migration_059_andritz_agentic_default_state": {
            "revision": "059_andritz_agentic_default",
            "schema": 1,
            "system_id": system.id,
        },
    }
    db_session.commit()

    response = _client(db_session, workspace, viewer, monkeypatch).post(
        f"/systems/{system.id}/ingresses/manual.input/runs",
        json=_run_body(version),
    )

    assert response.status_code == 403
    assert db_session.query(Run).count() == 0
