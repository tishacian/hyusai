"""External runners API: feature gate, admin-only writes, tenant isolation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth, remote_runners
from app.core.auth import get_current_workspace
from app.core.config import settings
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "remote_runners_enabled", True)
    monkeypatch.setattr(settings, "remote_runner_local_transport_enabled", True)


@pytest.fixture()
def seed(db_session):
    def user():
        row = User(
            id=str(uuid4()),
            username=f"rr-{uuid4().hex[:8]}",
            email=f"rr-{uuid4().hex[:8]}@example.test",
            role="user",
        )
        db_session.add(row)
        return row

    ws = Workspace(id=str(uuid4()), name="Runners", slug=f"rr-{uuid4().hex[:8]}", settings={})
    other = Workspace(id=str(uuid4()), name="Other", slug=f"rr-{uuid4().hex[:8]}", settings={})
    db_session.add_all([ws, other])
    owner, member = user(), user()
    db_session.flush()
    db_session.add_all(
        [
            WorkspaceMember(
                workspace_id=ws.id, user_id=owner.id, role="owner", role_template=WORKSPACE_OWNER
            ),
            WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="member"),
            WorkspaceMember(
                workspace_id=other.id, user_id=owner.id, role="owner", role_template=WORKSPACE_OWNER
            ),
        ]
    )
    db_session.commit()
    return {"ws": ws, "other": other, "owner": owner, "member": member}


def _client(db_session, workspace, user):
    app = FastAPI()
    app.include_router(remote_runners.router, prefix="/remote-runners")
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


def _runner_body(tmp_path):
    return {
        "slug": "gpu-box",
        "name": "GPU box",
        "transport": "local",
        "host": "localhost",
        "username": "agentium",
        "host_key": "unused",
        "key_secret_ref": "secret://workspace/gpu-key",
        "work_root": str(tmp_path / "work"),
        "allowed_commands": ["agentium.sleep"],
    }


def test_disabled_feature_has_no_routes(db_session, seed, monkeypatch):
    monkeypatch.setattr(settings, "remote_runners_enabled", False)
    response = _client(db_session, seed["ws"], seed["owner"]).get("/remote-runners")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "REMOTE_RUNNERS_DISABLED"


def test_admin_declares_runner_and_submits_job(db_session, seed, tmp_path):
    client = _client(db_session, seed["ws"], seed["owner"])
    created = client.post("/remote-runners", json=_runner_body(tmp_path))
    assert created.status_code == 201, created.text
    runner = created.json()
    assert runner["allowed_commands"] == ["agentium.sleep"]
    keys = {item["key"] for item in client.get("/remote-runners/catalog").json()}
    assert {"agentium.probe", "agentium.sleep"} <= keys
    job = client.post(
        f"/remote-runners/{runner['id']}/jobs",
        json={"command": "agentium.sleep", "params": {"seconds": 1}},
    )
    assert job.status_code == 202, job.text
    assert job.json()["status"] == "queued"
    denied = client.post(f"/remote-runners/{runner['id']}/jobs", json={"command": "agentium.probe"})
    assert (denied.status_code, denied.json()["detail"]["code"]) == (
        403,
        "REMOTE_COMMAND_NOT_ALLOWED",
    )
    shell = client.post(
        f"/remote-runners/{runner['id']}/jobs",
        json={"command": "agentium.sleep", "shell": "rm -rf /"},
    )
    assert shell.status_code == 400
    cancelled = client.post(f"/remote-runners/jobs/{job.json()['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    duplicate = client.post("/remote-runners", json=_runner_body(tmp_path))
    assert (duplicate.status_code, duplicate.json()["detail"]["code"]) == (
        409,
        "REMOTE_RUNNER_SLUG_TAKEN",
    )


def test_member_reads_but_cannot_write(db_session, seed, tmp_path):
    owner = _client(db_session, seed["ws"], seed["owner"])
    runner = owner.post("/remote-runners", json=_runner_body(tmp_path)).json()
    member = _client(db_session, seed["ws"], seed["member"])
    assert member.get("/remote-runners").status_code == 200
    assert member.post("/remote-runners", json=_runner_body(tmp_path)).status_code == 403
    assert (
        member.post(
            f"/remote-runners/{runner['id']}/jobs", json={"command": "agentium.sleep"}
        ).status_code
        == 403
    )
    assert member.post(f"/remote-runners/{runner['id']}/probe").status_code == 403


def test_other_workspace_cannot_see_runner_or_job(db_session, seed, tmp_path):
    owner = _client(db_session, seed["ws"], seed["owner"])
    runner = owner.post("/remote-runners", json=_runner_body(tmp_path)).json()
    job = owner.post(
        f"/remote-runners/{runner['id']}/jobs", json={"command": "agentium.sleep"}
    ).json()
    foreign = _client(db_session, seed["other"], seed["owner"])
    assert foreign.get("/remote-runners").json() == []
    assert foreign.get(f"/remote-runners/jobs/{job['id']}").status_code == 404
    assert (
        foreign.post(
            f"/remote-runners/{runner['id']}/jobs", json={"command": "agentium.sleep"}
        ).status_code
        == 404
    )
    assert (
        foreign.patch(f"/remote-runners/{runner['id']}", json={"enabled": False}).status_code == 404
    )
