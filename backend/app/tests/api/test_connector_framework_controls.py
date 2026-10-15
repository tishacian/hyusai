"""Administrative connector actions stay gated, tenant-scoped and non-echoing."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import connector_governance, connector_watches, connector_writes
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.connector_connection import ConnectorConnection
from app.models.connector_sync import ConnectorWatch
from app.models.system import System
from app.services.connectors import writes
from app.tests.services.test_connection_registry import setup as connection_setup
from app.tests.services.test_connector_writes import prepare, successful_preview
from app.tests.services.test_connector_writes import seeded as write_setup

setup = connection_setup
seeded = write_setup


def api(db, user, workspace):
    app = FastAPI()
    app.include_router(connector_writes.router, prefix="/connector-writes")
    app.include_router(connector_watches.router, prefix="/connector-watches")
    app.include_router(connector_governance.router, prefix="/connector-governance")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/connector-watches", None),
        ("POST", "/connector-watches", {}),
        ("DELETE", "/connector-watches/id", None),
        ("POST", "/connector-writes", {}),
        ("GET", "/connector-writes/id", None),
        ("POST", "/connector-writes/id/approve", {}),
        ("POST", "/connector-writes/id/execute", None),
        ("GET", "/connector-governance/network-exceptions", None),
    ],
)
def test_framework_false_closes_every_control_family(
    db_session, setup, monkeypatch, method, path, body
):
    monkeypatch.setattr(settings, "connector_framework_enabled", False)
    response = api(db_session, setup[2][0], setup[0]).request(method, path, json=body)
    assert (
        response.status_code == 404
        and response.json()["detail"]["code"] == "CONNECTOR_FRAMEWORK_DISABLED"
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/connector-watches", None),
        ("POST", "/connector-watches", {}),
        ("DELETE", "/connector-watches/id", None),
        ("POST", "/connector-writes", {}),
        ("GET", "/connector-writes/id", None),
        ("POST", "/connector-writes/id/approve", {}),
        ("POST", "/connector-writes/id/execute", None),
    ],
)
def test_workspace_member_cannot_read_contracts_or_mutate_controls(
    db_session, setup, method, path, body
):
    response = api(db_session, setup[2][1], setup[0]).request(method, path, json=body)
    assert response.status_code == 403


def test_workspace_owner_cannot_issue_platform_network_exceptions(db_session, setup):
    response = api(db_session, setup[2][0], setup[0]).post(
        "/connector-governance/network-exceptions",
        json={
            "workspace_id": setup[0].id,
            "cidr": "10.0.0.1/32",
            "ports": [5432],
            "reason": "workspace preference",
            "expires_at": "2030-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 403


def test_write_approval_exact_digest_then_dispatch_requires_separate_action(
    db_session, seeded, monkeypatch
):
    monkeypatch.setattr(settings, "connector_framework_enabled", True)
    ws, admin, _, _, _ = seeded
    row = prepare(db_session, seeded)
    db_session.commit()
    client = api(db_session, admin, ws)
    mismatch = client.post(
        f"/connector-writes/{row.id}/approve", json={"contract_digest": "f" * 64}
    )
    assert mismatch.status_code == 409 and row.state == "prepared"
    writes.compute_runs.dispatch_run.assert_not_called()
    missing_preview = client.post(
        f"/connector-writes/{row.id}/approve", json={"contract_digest": row.contract_digest}
    )
    assert missing_preview.status_code == 409
    assert missing_preview.json()["detail"]["code"] == "CONNECTOR_WRITE_PREVIEW_REQUIRED"
    successful_preview(db_session, seeded, row)
    db_session.commit()
    response = client.post(
        f"/connector-writes/{row.id}/approve", json={"contract_digest": row.contract_digest}
    )
    assert response.status_code == 200 and response.json()["state"] == "approved"
    writes.compute_runs.dispatch_run.assert_not_called()
    response = client.post(f"/connector-writes/{row.id}/execute")
    assert response.status_code == 202 and response.json()["compute_run_id"]
    writes.compute_runs.dispatch_run.assert_called_once()


def test_bad_request_never_echoes_credential_shaped_extra_input(db_session, setup):
    value = "not-a-real-secret-but-never-echo-this"
    response = api(db_session, setup[2][0], setup[0]).post(
        "/connector-writes", json={"password": value}
    )
    assert response.status_code == 400 and value not in response.text


def test_watch_is_scoped_and_invalid_prefix_is_closed_error(db_session, setup):
    ws, other, users, _ = setup
    connection = ConnectorConnection(
        id=str(uuid4()),
        workspace_id=ws.id,
        name="Object watch fixture",
        profile_key="s3",
        profile_version=1,
        values={"bucket": "bucket", "prefix": "approved"},
        secret_refs={},
        access="read",
        created_by=users[0].id,
    )
    system = System(id=str(uuid4()), workspace_id=ws.id, name="Destination")
    db_session.add_all([connection, system])
    db_session.commit()
    body = {
        "connection_id": connection.id,
        "system_id": system.id,
        "prefix": "approved/daily",
        "interval_s": 300,
    }
    client = api(db_session, users[0], ws)
    rejected = client.post("/connector-watches", json=body | {"prefix": "../outside"})
    assert rejected.status_code == 400
    assert db_session.query(ConnectorWatch).count() == 0
    created = client.post("/connector-watches", json=body)
    assert created.status_code == 201, created.text
    identity = created.json()["id"]
    assert api(db_session, users[0], other).get("/connector-watches").json() == []
    assert (
        api(db_session, users[0], other).delete("/connector-watches/" + identity).status_code == 404
    )
    assert client.delete("/connector-watches/" + identity).json()["enabled"] is False
