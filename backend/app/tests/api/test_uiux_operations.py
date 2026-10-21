"""UI/UX lot 7: explicit lifecycle receipts, tenant-safe evidence and launches."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from app.api.v1.endpoints import auth, tasks
from app.models.connector_connection import ConnectorConnection
from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

# Preserve the real ASGI transport before tests replace the identity-provider client.
HTTP_CLIENT = httpx.AsyncClient


def seed(db, role="workspace_owner"):
    user = User(id="ops-user", username="ops-user", keycloak_sub="kc-ops-user")
    workspace = Workspace(id="ops-ws", slug="ops-ws", name="Operations")
    db.add_all([user, workspace])
    db.flush()
    db.add(
        WorkspaceMember(
            user_id=user.id, workspace_id=workspace.id, role="owner", role_template=role
        )
    )
    db.commit()
    return user, workspace


def client(db, user, workspace=None, endpoint=auth):
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/test")

    async def current_db():
        return db

    async def current_user():
        return user

    async def current_workspace():
        return workspace

    app.dependency_overrides[endpoint.get_db] = current_db
    app.dependency_overrides[endpoint.get_current_user] = current_user
    if workspace is not None:
        app.dependency_overrides[endpoint.get_current_workspace] = current_workspace

    class Client:
        def request(self, method, path, **kwargs):
            async def run():
                async with HTTP_CLIENT(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as transport:
                    return await transport.request(method, path, **kwargs)

            return asyncio.run(run())

        def get(self, path, **kwargs):
            return self.request("GET", path, **kwargs)

        def post(self, path, **kwargs):
            return self.request("POST", path, **kwargs)

        def delete(self, path, **kwargs):
            return self.request("DELETE", path, **kwargs)

    return Client()


def fake_identity(monkeypatch):
    async def token():
        return "fixture-token"

    class Identity:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def delete(self, *args, **kwargs):
            return SimpleNamespace(status_code=204)

    monkeypatch.setattr(auth, "_get_admin_token", token)
    monkeypatch.setattr(auth.httpx, "AsyncClient", Identity)


def test_account_deletion_receipt_distinguishes_identity_and_profile(db_session, monkeypatch):
    user, _ = seed(db_session)
    fake_identity(monkeypatch)
    response = client(db_session, user).delete("/test/me")
    assert response.status_code == 200
    receipt = response.json()["receipt"]
    assert (
        receipt["identity_deleted"]
        and receipt["profile_deleted"]
        and receipt["connections_revoked"]
    )
    assert "shared_workspaces" in receipt["retained"]


def test_partial_account_deletion_is_never_reported_as_success(db_session, monkeypatch):
    user, _ = seed(db_session)
    fake_identity(monkeypatch)

    def fail():
        raise RuntimeError("simulated local commit failure")

    monkeypatch.setattr(db_session, "commit", fail)
    response = client(db_session, user).delete("/test/me")
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "ACCOUNT_DELETE_PARTIAL"
    assert detail["receipt"]["identity_deleted"] is True
    assert detail["receipt"]["profile_deleted"] is False


def test_restore_returns_connections_until_current_real_test_succeeds(db_session):
    user, workspace = seed(db_session)
    workspace.is_active = False
    workspace.deleted_at = datetime.utcnow() - timedelta(days=1)
    connection = ConnectorConnection(
        id="ops-connection",
        workspace_id=workspace.id,
        name="ERP",
        profile_key="postgresql",
        profile_version=1,
        created_by=user.id,
    )
    db_session.add(connection)
    db_session.commit()
    c = client(db_session, user)
    response = c.post("/test/workspaces/ops-ws/restore")
    assert response.status_code == 200, response.text
    assert response.json()["connections"] == [
        {"id": connection.id, "name": "ERP", "status": "reconnect_required"}
    ]
    connection.last_test = {
        "connected": True,
        "source": "real",
        "connection_revision": connection.revision,
    }
    db_session.commit()
    assert (
        c.get("/test/workspaces/ops-ws/reconnection-status").json()["connections"][0]["status"]
        == "verified"
    )
    connection.revision += 1
    db_session.commit()
    assert (
        c.get("/test/workspaces/ops-ws/reconnection-status").json()["connections"][0]["status"]
        == "reconnect_required"
    )


def test_restore_after_retention_is_refused(db_session):
    user, workspace = seed(db_session)
    workspace.is_active = False
    workspace.deleted_at = datetime.utcnow() - timedelta(days=31)
    db_session.commit()
    response = client(db_session, user).post("/test/workspaces/ops-ws/restore")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "WORKSPACE_RESTORE_EXPIRED"


def test_mission_creation_does_not_start_a_worker_and_foreign_tasks_are_404(
    db_session, monkeypatch
):
    user, workspace = seed(db_session)
    dispatched = []
    monkeypatch.setattr(tasks, "dispatch_execution", lambda value: dispatched.append(value))
    c = client(db_session, user, workspace, tasks)
    result = c.post("/test", json={"description": "Review the delivery"})
    assert result.status_code == 200 and result.json()["status"] == "pending"
    assert dispatched == [] and db_session.query(TaskExecution).count() == 0
    foreign = Workspace(id="foreign-ops", slug="foreign-ops", name="Foreign")
    db_session.add(foreign)
    db_session.flush()
    db_session.add(
        Task(id="foreign-mission", workspace_id=foreign.id, title="Hidden", description="Hidden")
    )
    db_session.commit()
    assert c.get("/test/foreign-mission").status_code == 404
    assert c.post("/test/foreign-mission/run", json={}).status_code == 404
    assert c.get("/test/missing").status_code == 404


def test_viewer_cannot_compose_or_launch(db_session):
    user, workspace = seed(db_session, "workspace_viewer")
    c = client(db_session, user, workspace, tasks)
    assert c.post("/test", json={"description": "No write"}).status_code == 403


def test_relaunch_detail_never_labels_previous_deliverable_as_current(db_session):
    from app.services.tasks.execution import checkpoint, claim_execution, queue_execution

    user, workspace = seed(db_session)
    task = Task(
        id="relaunch",
        workspace_id=workspace.id,
        title="Report",
        description="Goal",
        status="pending",
    )
    db_session.add(task)
    db_session.commit()
    old = queue_execution(db_session, task, user.id)
    db_session.commit()
    fence = claim_execution(db_session, old.id)
    checkpoint(
        db_session,
        old.id,
        fence,
        {
            "type": "task_complete",
            "steps": [],
            "artifacts": {"report": "Previous"},
            "progress": 100,
        },
    )
    new = queue_execution(db_session, task, user.id, confirm_rerun=True)
    db_session.commit()
    response = client(db_session, user, workspace, tasks).get("/test/relaunch")
    detail = response.json()
    assert detail["status"] == "queued" and detail["progress"] == 0 and detail["artifacts"] == {}
    assert detail["execution_id"] == new.id
    assert (
        next(item for item in detail["executions"] if item["id"] == old.id)["artifacts"]["report"]
        == "Previous"
    )


def test_value_loop_permissions_match_the_effective_role(db_session):
    from app.api.v1.endpoints.value_loop import _ui_permissions
    from app.models.system import System

    user, workspace = seed(db_session, "workspace_reviewer")
    system = System(id="permission-system", workspace_id=workspace.id, name="Review system")
    db_session.add(system)
    db_session.commit()
    permissions = _ui_permissions(db_session, workspace, system, user, "scenario")
    assert permissions == {
        "create": False,
        "simulate": False,
        "approve": True,
        "act": False,
        "measure": True,
    }
    member = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one()
    member.role_template = "workspace_viewer"
    db_session.commit()
    assert not any(_ui_permissions(db_session, workspace, system, user, "scenario").values())


def test_drafting_mission_refuses_an_ignored_system_selection(db_session):
    user, workspace = seed(db_session)
    response = client(db_session, user, workspace, tasks).post(
        "/test", json={"description": "Draft a report", "agent_id": "system-selection"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MISSION_SYSTEM_EXECUTION_UNSUPPORTED"
    assert db_session.query(Task).count() == 0
