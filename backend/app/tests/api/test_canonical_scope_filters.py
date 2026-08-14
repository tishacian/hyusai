"""Workspace-safe scope filters for the canonical System and Run lists."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import runs, systems
from app.models.capability import Capability
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace


def _client(db_session, workspace: Workspace) -> TestClient:
    user = User(
        id="scope-test-admin",
        username="scope-test-admin",
        role="admin",
    )
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.include_router(runs.router, prefix="/runs")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_db] = lambda: db_session
    app.dependency_overrides[runs.get_current_workspace] = lambda: workspace
    app.dependency_overrides[runs.get_current_user] = lambda: user
    app.dependency_overrides[runs.get_db] = lambda: db_session
    return TestClient(app)


def _seed_scope_graph(
    db_session,
) -> tuple[Workspace, Capability, Capability, Capability]:
    workspace = Workspace(id="ws-scope", slug="scope", name="Scope")
    other_workspace = Workspace(id="ws-scope-other", slug="scope-other", name="Other")
    capability = Capability(
        id="cap-scope",
        workspace_id=workspace.id,
        slug="scope-capability",
        name="Scope capability",
    )
    sibling_capability = Capability(
        id="cap-scope-sibling",
        workspace_id=workspace.id,
        slug="scope-sibling-capability",
        name="Sibling capability",
    )
    other_capability = Capability(
        id="cap-scope-other",
        workspace_id=other_workspace.id,
        slug="scope-other-capability",
        name="Other capability",
    )
    systems_rows = [
        System(
            id="system-scope",
            workspace_id=workspace.id,
            capability_id=capability.id,
            name="Scoped system",
            status="active",
        ),
        System(
            id="system-scope-sibling",
            workspace_id=workspace.id,
            capability_id=sibling_capability.id,
            name="Sibling system",
            status="active",
        ),
        System(
            id="system-scope-other",
            workspace_id=other_workspace.id,
            capability_id=other_capability.id,
            name="Other system",
            status="active",
        ),
        System(
            id="system-scope-corrupt-capability",
            workspace_id=workspace.id,
            capability_id=other_capability.id,
            name="Corrupt capability edge",
            status="active",
        ),
    ]
    runs_rows = [
        Run(
            id="run-scope",
            workspace_id=workspace.id,
            system_id="system-scope",
            capability_id=capability.id,
            status="completed",
        ),
        Run(
            id="run-scope-inherited",
            workspace_id=workspace.id,
            system_id="system-scope",
            capability_id=None,
            status="completed",
        ),
        Run(
            id="run-scope-mismatch",
            workspace_id=workspace.id,
            system_id="system-scope",
            capability_id=sibling_capability.id,
            status="completed",
        ),
        Run(
            id="run-scope-systemless",
            workspace_id=workspace.id,
            system_id=None,
            capability_id=capability.id,
            status="completed",
        ),
        Run(
            id="run-scope-sibling",
            workspace_id=workspace.id,
            system_id="system-scope-sibling",
            capability_id=sibling_capability.id,
            status="completed",
        ),
        Run(
            id="run-scope-other",
            workspace_id=other_workspace.id,
            system_id="system-scope-other",
            capability_id=other_capability.id,
            status="completed",
        ),
        Run(
            id="run-cross-workspace-parent",
            workspace_id=workspace.id,
            system_id="system-scope-other",
            capability_id=other_capability.id,
            status="completed",
        ),
        Run(
            id="run-corrupt-capability-parent",
            workspace_id=workspace.id,
            system_id="system-scope-corrupt-capability",
            capability_id=other_capability.id,
            status="completed",
        ),
        Run(
            id="run-systemless-foreign-capability",
            workspace_id=workspace.id,
            system_id=None,
            capability_id=other_capability.id,
            status="completed",
        ),
    ]
    db_session.add_all(
        [
            workspace,
            other_workspace,
            capability,
            sibling_capability,
            other_capability,
            *systems_rows,
            *runs_rows,
        ]
    )
    db_session.commit()
    return workspace, capability, sibling_capability, other_capability


def test_list_systems_filters_by_capability_inside_current_workspace(db_session):
    workspace, capability, _sibling_capability, other_capability = _seed_scope_graph(db_session)
    client = _client(db_session, workspace)

    response = client.get("/systems", params={"capability_id": capability.id})

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["systems"]] == ["system-scope"]
    assert client.get("/systems", params={"capability_id": other_capability.id}).json() == {
        "systems": []
    }


def test_list_runs_filters_by_capability_inside_current_workspace(db_session):
    workspace, capability, sibling_capability, other_capability = _seed_scope_graph(db_session)
    client = _client(db_session, workspace)

    response = client.get("/runs", params={"capability_id": capability.id})

    assert response.status_code == 200
    assert {row["id"] for row in response.json()["runs"]} == {
        "run-scope",
        "run-scope-inherited",
        "run-scope-mismatch",
        "run-scope-systemless",
    }

    sibling_response = client.get("/runs", params={"capability_id": sibling_capability.id})
    assert {row["id"] for row in sibling_response.json()["runs"]} == {"run-scope-sibling"}

    combined_response = client.get(
        "/runs",
        params={"system_id": "system-scope", "capability_id": capability.id},
    )
    assert {row["id"] for row in combined_response.json()["runs"]} == {
        "run-scope",
        "run-scope-inherited",
        "run-scope-mismatch",
    }
    assert client.get(
        "/runs",
        params={
            "system_id": "system-scope-sibling",
            "capability_id": capability.id,
        },
    ).json() == {"runs": []}

    assert client.get("/runs", params={"capability_id": other_capability.id}).json() == {"runs": []}


def test_list_runs_rejects_a_cross_workspace_parent_for_system_scope(db_session):
    workspace, _capability, _sibling, _other = _seed_scope_graph(db_session)
    client = _client(db_session, workspace)

    assert client.get("/runs", params={"system_id": "system-scope-other"}).json() == {"runs": []}


def test_global_capabilities_remain_valid_scope_parents(db_session):
    workspace, _capability, _sibling, _other = _seed_scope_graph(db_session)
    global_capability = Capability(
        id="cap-scope-global",
        workspace_id=None,
        slug="scope-global-capability",
        name="Global capability",
        is_seeded="Y",
    )
    global_system = System(
        id="system-scope-global",
        workspace_id=workspace.id,
        capability_id=global_capability.id,
        name="Global capability system",
        status="active",
    )
    global_run = Run(
        id="run-scope-global",
        workspace_id=workspace.id,
        system_id=global_system.id,
        capability_id=None,
        status="completed",
    )
    db_session.add_all([global_capability, global_system, global_run])
    db_session.commit()
    client = _client(db_session, workspace)

    assert [
        row["id"]
        for row in client.get("/systems", params={"capability_id": global_capability.id}).json()[
            "systems"
        ]
    ] == [global_system.id]
    assert {
        row["id"]
        for row in client.get("/runs", params={"capability_id": global_capability.id}).json()[
            "runs"
        ]
    } == {global_run.id}


def test_list_runs_filters_by_ingress_origin(db_session):
    workspace = Workspace(id="ws-origin", slug="origin", name="Origin")
    tagged = Run(
        id="run-origin-experience",
        workspace_id=workspace.id,
        status="completed",
        input_ref={"_ingress": {"adapter": {"origin": "experience:expenses.submit"}}},
    )
    other = Run(
        id="run-origin-manual",
        workspace_id=workspace.id,
        status="completed",
        input_ref={"_ingress": {"adapter": {"origin": "manual"}}},
    )
    untagged = Run(
        id="run-origin-plain",
        workspace_id=workspace.id,
        status="completed",
        input_ref={},
    )
    db_session.add_all([workspace, tagged, other, untagged])
    db_session.commit()
    client = _client(db_session, workspace)

    matched = client.get("/runs", params={"origin": "experience:expenses.submit"})
    empty = client.get("/runs", params={"origin": "experience:missing"})

    assert matched.status_code == 200
    assert [row["id"] for row in matched.json()["runs"]] == ["run-origin-experience"]
    assert empty.json() == {"runs": []}


def test_list_runs_hitl_inbox_excludes_other_binding_origin(db_session):
    workspace = Workspace(id="ws-hitl-origin", slug="hitl-origin", name="HITL origin")
    ours = Run(
        id="run-hitl-nawa",
        workspace_id=workspace.id,
        status="hitl_pending",
        input_ref={"_ingress": {"adapter": {"origin": "experience:nawa.password_reset"}}},
    )
    other_app = Run(
        id="run-hitl-recon",
        workspace_id=workspace.id,
        status="hitl_pending",
        input_ref={"_ingress": {"adapter": {"origin": "experience:rapprochement.po.factures"}}},
    )
    untagged = Run(
        id="run-hitl-system",
        workspace_id=workspace.id,
        status="hitl_pending",
        input_ref={"_ingress": {"adapter": {"origin": "manual"}}},
    )
    db_session.add_all([workspace, ours, other_app, untagged])
    db_session.commit()
    client = _client(db_session, workspace)

    scoped = client.get(
        "/runs",
        params={"status": "hitl_pending", "origin": "experience:nawa.password_reset"},
    )
    both = client.get(
        "/runs",
        params=[
            ("status", "hitl_pending"),
            ("origin", "experience:nawa.password_reset"),
            ("origin", "experience:rapprochement.po.factures"),
        ],
    )

    assert scoped.status_code == 200
    assert [row["id"] for row in scoped.json()["runs"]] == ["run-hitl-nawa"]
    assert {row["id"] for row in both.json()["runs"]} == {"run-hitl-nawa", "run-hitl-recon"}
