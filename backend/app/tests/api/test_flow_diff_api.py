import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import flow_diffs as endpoint
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services.flow_contracts import canonical_sha256
from app.services.systems import flow_publication


def _flow(timeout: int, token: str) -> dict:
    return {
        "schema_version": 3,
        "io_mode": "overlay",
        "nodes": [
            {"id": "source", "kind": "source"},
            {
                "id": "task",
                "kind": "task",
                "config": {
                    "runtime_ref": "builtin:passthrough",
                    "timeout": timeout,
                    "api_token": token,
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "task", "kind": "data"},
            {"from": "task", "to": "sink", "kind": "data"},
        ],
    }


def _seed(db_session):
    workspace = Workspace(
        id="ws-flow-diff",
        slug="flow-diff",
        name="Flow diff",
        settings={"features": {"flow_publication_v1": True}},
    )
    user = User(
        id="user-flow-diff",
        username="flow-diff@example.invalid",
        email="flow-diff@example.invalid",
        role="admin",
    )
    system = System(
        id="system-flow-diff",
        workspace_id=workspace.id,
        name="Diff target",
        objective="test",
        status="active",
        flow_definition=_flow(10, "published-secret"),
    )
    db_session.add_all([workspace, user, system])
    db_session.commit()
    flow_publication.initialize_publication_state(
        db_session,
        system=system,
        workspace=workspace,
        actor=user.email,
    )
    db_session.commit()
    flow_publication.save_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        flow_definition=_flow(20, "draft-secret"),
        expected_revision=1,
        actor=user.email,
    )
    db_session.commit()
    return workspace, user, system


def _client(db_session, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/systems")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    return TestClient(app)


def test_flow_diff_resolves_published_and_draft_without_leaking_values(db_session) -> None:
    workspace, user, system = _seed(db_session)
    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/flow-diff",
        params={"base": "published", "target": "draft"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["base"]["identity"] == "published:1"
    assert payload["target"]["identity"] == "draft:2"
    assert payload["summary"]["behavioral"] == 1
    encoded = json.dumps(payload)
    assert "published-secret" not in encoded
    assert "draft-secret" not in encoded


def test_flow_diff_rejects_unknown_reference(db_session) -> None:
    workspace, user, system = _seed(db_session)
    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/flow-diff",
        params={"base": "published", "target": "version:not-a-number"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "FLOW_DIFF_REF_INVALID"


def test_flow_diff_exposes_frozen_contract_drift_without_schema_values(db_session) -> None:
    workspace, user, system = _seed(db_session)
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    contract = dict(version.execution_contract)
    contract["nodes"] = {
        "task": {
            "output_schema": {
                "type": "string",
                "description": "published-only-secret-marker",
            }
        }
    }
    contract.pop("contract_sha256", None)
    contract["contract_sha256"] = canonical_sha256(contract)
    version.execution_contract = contract
    db_session.commit()

    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/flow-diff",
        params={"base": "published", "target": "draft"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    contract_change = next(
        change
        for change in payload["changes"]
        if change["path"] == "execution_contract"
    )
    assert contract_change["impact"] == "breaking"
    assert "published-only-secret-marker" not in json.dumps(payload)
