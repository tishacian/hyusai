"""Product policy routes retain Work access, validation and atomic audit."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ecommerce_claims as endpoint
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.audit import AuditLog
from app.services.ecommerce import policy_settings
from app.tests.services.test_claim_resolution_policy import configured
from app.tests.services.test_claim_resolution_policy import policy_workspace as policy_workspace


@pytest.fixture()
def client(db_session, policy_workspace, monkeypatch):
    workspace, user, *_ = policy_workspace
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/claims")
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(endpoint.work, "_require_enabled", lambda *_: None)
    monkeypatch.setattr(endpoint.work, "_enforce_consume", lambda *_, **__: None)
    monkeypatch.setattr(endpoint.work, "_resolve_for_user", lambda *_, **__: None)
    return TestClient(app)


def test_policy_read_is_a_product_route_and_does_not_probe_postgres(client, policy_workspace):
    *_, snapshot_reader, _ = policy_workspace
    response = client.get("/claims/policy")
    assert response.status_code == 200, response.text
    assert response.json()["policy"]["manager_approval_above"] == "300.00"
    assert response.json()["can_configure"] is True
    snapshot_reader.assert_not_called()


def test_policy_write_commits_audited_settings_and_rejects_stale_editor(
    client, db_session, policy_workspace
):
    current = client.get("/claims/policy").json()
    body = {
        "expected_sha256": current["sha256"],
        "policy": configured(manager_approval_above="25").model_dump(),
    }
    response = client.put("/claims/policy", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    assert (
        db_session.query(AuditLog).filter_by(event_type="claims.resolution_policy.updated").count()
        == 1
    )
    response = client.put("/claims/policy", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CLAIM_POLICY_CONFLICT"
    assert client.get("/claims/policy").json()["policy"]["manager_approval_above"] == "25.00"


def test_read_only_workspace_member_cannot_write(client, db_session, policy_workspace):
    _, _, member, snapshot_reader, _ = policy_workspace
    member.role_template = "workspace_reviewer"
    db_session.commit()
    current = client.get("/claims/policy").json()
    assert current["can_configure"] is False
    response = client.put(
        "/claims/policy",
        json={"expected_sha256": current["sha256"], "policy": configured().model_dump()},
    )
    assert response.status_code == 403
    snapshot_reader.assert_not_called()


def test_unreadable_policy_document_is_not_exposed_or_saved(client, db_session, policy_workspace):
    workspace, user, _, _, sources = policy_workspace
    current = policy_settings.read(db_session, workspace, user)
    sources.side_effect = HTTPException(404, detail="private collection")
    response = client.put(
        "/claims/policy",
        json={"expected_sha256": current["sha256"], "policy": configured().model_dump()},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "CLAIM_POLICY_DOCUMENT_UNAVAILABLE"}}
    assert policy_settings.read(db_session, workspace, user)["sha256"] == current["sha256"]
    assert (
        db_session.query(AuditLog).filter_by(event_type="claims.resolution_policy.updated").count()
        == 0
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": True},
        {"policy": {"financial_execution": "live"}},
        {"expected_sha256": "unknown"},
    ],
)
def test_malformed_policy_payload_never_reads_sources(client, policy_workspace, changes):
    *_, snapshot_reader, _ = policy_workspace
    current = client.get("/claims/policy").json()
    response = client.put(
        "/claims/policy",
        json={"expected_sha256": current["sha256"], "policy": configured().model_dump(), **changes},
    )
    assert response.status_code == 422
    snapshot_reader.assert_not_called()


@pytest.mark.parametrize("method", ["get", "put"])
def test_work_access_is_required_before_policy_read_or_write(
    client, policy_workspace, monkeypatch, method
):
    *_, snapshot_reader, _ = policy_workspace
    gate = Mock(side_effect=HTTPException(403, detail={"code": "WORK_CONSUME_DENIED"}))
    monkeypatch.setattr(endpoint.work, "_enforce_consume", gate)
    kwargs = (
        {}
        if method == "get"
        else {"json": {"expected_sha256": "a" * 64, "policy": configured().model_dump()}}
    )
    response = getattr(client, method)("/claims/policy", **kwargs)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORK_CONSUME_DENIED"
    gate.assert_called_once()
    snapshot_reader.assert_not_called()
