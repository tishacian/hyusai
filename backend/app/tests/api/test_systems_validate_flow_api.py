"""Hash-bound, non-mutating Flow analyser API."""

from __future__ import annotations

import copy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_engine.execution_contract import canonical_flow_sha256


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session) -> tuple[Workspace, User, System]:
    workspace = Workspace(
        id="ws-flow-analyser",
        name="Flow analyser",
        slug="flow-analyser",
        settings={"features": {"flow_v3_dag_authoritative": True}},
    )
    user = User(
        id="user-flow-analyser",
        username="flow-analyser@example.invalid",
        email="flow-analyser@example.invalid",
        role="admin",
    )
    system = System(
        id="system-flow-analyser",
        workspace_id=workspace.id,
        name="Analyser target",
        objective="test",
        flow_definition={"nodes": [], "edges": []},
        status="draft",
    )
    db_session.add_all([workspace, user, system])
    db_session.commit()
    return workspace, user, system


def _strict_decision_flow(*, bind_value: bool = True) -> dict:
    """A strict v3 graph whose Decision routes on a name it actually binds.

    Strict resolution keeps only ``inputs_map`` / ``passthrough_inputs``, so
    without the binding the Decision reads ``value`` out of an empty payload
    and every branch loses to the default. ``bind_value=False`` reproduces
    that graph for the tests that assert the warning.
    """
    config: dict = {
        "branches": [
            {"label": "yes", "condition": "value == True"},
            {"label": "no", "condition": "value == False"},
        ],
        "default_branch": "no",
    }
    if bind_value:
        config["inputs_map"] = {"value": {"node_id": "source", "path": ["value"]}}
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "variable_namespaces": [],
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "decision", "kind": "decision", "config": config},
            {"id": "result", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "decision", "kind": "data"},
            {
                "from": "decision",
                "to": "result",
                "kind": "branch",
                "branch_label": "yes",
            },
            {
                "from": "decision",
                "to": "result",
                "kind": "branch",
                "branch_label": "no",
            },
        ],
    }


def test_validate_flow_returns_server_hash_and_runtime_without_mutation(db_session) -> None:
    workspace, user, system = _seed(db_session)
    before = copy.deepcopy(system.flow_definition)
    flow = _strict_decision_flow()

    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/validate-flow",
        json={"flow_definition": flow},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "flow_sha256": canonical_flow_sha256(flow),
        "analyzer_version": "flow-analyzer/1",
        "runtime_mode": "dag_strict",
        "valid": True,
        "issues": [],
    }
    db_session.refresh(system)
    assert system.flow_definition == before


def test_validate_flow_warns_on_a_strict_decision_that_binds_nothing(db_session) -> None:
    """The same graph minus the binding is a flow that cannot route.

    ``apply_inputs_map`` in strict mode keeps only the declared ports, so the
    Decision receives ``{}``, both predicates compare against a missing name
    and the default branch always wins. The run engine reports this as a
    ``decision_input_unbound`` checkpoint; the analyser has to say so at
    authoring time, and only as a warning — an unbound name must not block Save.
    """
    workspace, user, system = _seed(db_session)
    flow = _strict_decision_flow(bind_value=False)

    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/validate-flow",
        json={"flow_definition": flow},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert [(issue["code"], issue["level"]) for issue in payload["issues"]] == [
        ("decision_condition_unbound", "warn"),
        ("decision_condition_unbound", "warn"),
    ]
    assert all("'value'" in issue["message"] for issue in payload["issues"])
    assert {issue["node_id"] for issue in payload["issues"]} == {"decision"}


def test_validate_flow_binds_invalid_diagnostics_to_submitted_hash(db_session) -> None:
    workspace, user, system = _seed(db_session)
    flow = _strict_decision_flow()
    flow["nodes"][1]["config"]["branches"][0]["condition"] = ""

    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/validate-flow",
        json={"flow_definition": flow},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["flow_sha256"] == canonical_flow_sha256(flow)
    assert payload["valid"] is False
    assert payload["issues"][0]["code"] == "decision_condition_invalid"
    assert payload["issues"][0]["node_id"] == "decision"


def test_validate_flow_reports_malformed_graph_elements_without_500(db_session) -> None:
    workspace, user, system = _seed(db_session)
    flow = {"nodes": [None, {"id": " valid "}], "edges": [None]}

    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/validate-flow",
        json={"flow_definition": flow},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["flow_sha256"] == canonical_flow_sha256(flow)
    assert payload["valid"] is False
    assert [issue["code"] for issue in payload["issues"]] == [
        "node_invalid",
        "node_invalid",
        "edge_invalid",
    ]
    assert payload["issues"][2]["edge_index"] == 0


def test_validate_flow_rejects_unknown_http_fields(db_session) -> None:
    workspace, user, system = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/validate-flow",
        json={"flow_definition": _strict_decision_flow(), "stale_revision": 7},
    )
    assert response.status_code == 422
