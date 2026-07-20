"""API contract for the gated, workspace-scoped System 360 projection."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems
from app.models.audit import AuditLog
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session) -> tuple[Workspace, Workspace, User, System, System]:
    enabled = {
        "features": {
            "cockpit_router_axes_v4": True,
            "system_360_projection_v1": True,
        }
    }
    workspace = Workspace(id="ws-perspective-api", slug="perspective-api", name="Perspective", settings=enabled)
    other = Workspace(id="ws-perspective-other", slug="perspective-other", name="Other", settings=enabled)
    user = User(
        id="user-perspective-api",
        username="perspective-api@test",
        email="perspective-api@test",
        role="admin",
    )
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="owner",
        role_template="workspace_owner",
    )
    system = System(
        id="system-perspective-api",
        workspace_id=workspace.id,
        name="Marked System",
        objective="Give four honest readings of the same object.",
        status="active",
        settings={"experience": {"system_360_canary": "v1"}},
        flow_definition={"schema_version": 3, "io_mode": "strict", "nodes": [], "edges": []},
    )
    foreign = System(
        id="system-perspective-foreign",
        workspace_id=other.id,
        name="Foreign System",
        status="active",
        settings={"experience": {"system_360_canary": "v1"}},
    )
    db_session.add_all([workspace, other, user, membership, system, foreign])
    db_session.commit()
    return workspace, other, user, system, foreign


def test_perspective_returns_requested_lens_for_marked_system(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)
    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/perspective",
        params={"lens": "build", "window": "7d"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["lens"] == "build"
    assert payload["window"] == "7d"
    assert payload["identity"]["workspace_id"] == workspace.id
    assert payload["identity"]["system_id"] == system.id


def test_perspective_is_fail_closed_across_workspaces(db_session):
    workspace, _other, user, _system, foreign = _seed(db_session)
    response = _client(db_session, workspace, user).get(
        f"/systems/{foreign.id}/perspective",
        params={"lens": "operate"},
    )

    assert response.status_code == 404


def test_perspective_validates_lens_and_window(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)
    client = _client(db_session, workspace, user)

    assert client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "hypervisor"},
    ).status_code == 422
    assert client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "build", "window": "365d"},
    ).status_code == 422


def test_perspective_requires_both_workspace_flags_and_system_marker(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)
    client = _client(db_session, workspace, user)

    workspace.settings = {"features": {"cockpit_router_axes_v4": True}}
    db_session.commit()
    assert client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "build"},
    ).status_code == 404


def test_patch_audits_only_changed_field_names(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)
    response = _client(db_session, workspace, user).patch(
        f"/systems/{system.id}",
        json={
            "objective": "Updated objective",
            "settings": {
                "experience": {"system_360_canary": "v1"},
                "private_note": "must-never-enter-audit",
            },
        },
    )

    assert response.status_code == 200
    event = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == "system.updated",
            AuditLog.agent_id == system.id,
        )
        .one()
    )
    assert event.actor == user.email
    assert event.details == {
        "system_id": system.id,
        "fields": ["objective", "settings"],
    }
    assert "must-never-enter-audit" not in str(event.details)
