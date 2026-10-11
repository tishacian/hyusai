"""Secrets API: permissions per scope, tenant isolation, no value in any response."""

from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth, secrets
from app.core.auth import get_current_workspace
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.secrets import SecretConsumer, resolve
from app.services.secrets.backends.base import reset_backends

VALUE = "sk-api-value-never-echoed"
VALUE_2 = "sk-api-value-rotated-never-echoed"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("SECRET_REGISTRY_FERNET_KEY", base64.urlsafe_b64encode(b"a" * 32).decode())
    reset_backends()
    yield
    reset_backends()


def _user(db_session, role="user") -> User:
    user = User(
        id=str(uuid4()),
        username=f"secrets-{uuid4().hex[:8]}",
        email=f"secrets-{uuid4().hex[:8]}@example.test",
        role=role,
    )
    db_session.add(user)
    return user


def _workspace(db_session) -> Workspace:
    ws = Workspace(id=str(uuid4()), name="Secrets", slug=f"secrets-{uuid4().hex[:8]}", settings={})
    db_session.add(ws)
    return ws


@pytest.fixture()
def seed(db_session):
    ws, other_ws = _workspace(db_session), _workspace(db_session)
    owner, member, platform_admin = _user(db_session), _user(db_session), _user(db_session, "admin")
    db_session.flush()
    system = System(id=str(uuid4()), workspace_id=ws.id, name="Sys")
    foreign_system = System(id=str(uuid4()), workspace_id=other_ws.id, name="Other")
    db_session.add_all(
        [
            system,
            foreign_system,
            WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner", role_template=WORKSPACE_OWNER),
            WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="member"),
            WorkspaceMember(workspace_id=other_ws.id, user_id=owner.id, role="owner", role_template=WORKSPACE_OWNER),
        ]
    )
    db_session.commit()
    return {
        "ws": ws,
        "other_ws": other_ws,
        "owner": owner,
        "member": member,
        "platform_admin": platform_admin,
        "system": system,
        "foreign_system": foreign_system,
    }


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(secrets.router, prefix="/secrets")
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


def _create(client, **extra):
    body = {"name": "openai-key", "value": VALUE, "kind": "api_key", **extra}
    return client.post("/secrets", json=body)


def test_workspace_admin_lifecycle_never_returns_the_value(db_session, seed):
    client = _client(db_session, seed["ws"], seed["owner"])
    created = _create(client, description="LLM")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["ref"] == "secret://workspace/openai-key"
    assert body["value_set"] is True
    secret_id = body["id"]

    rotated = client.post(f"/secrets/{secret_id}/rotate", json={"value": VALUE_2})
    assert rotated.status_code == 200 and rotated.json()["current_version"] == 2
    listed = client.get("/secrets")
    assert [s["name"] for s in listed.json()["secrets"]] == ["openai-key"]
    detail = client.get(f"/secrets/{secret_id}")
    assert [v["version"] for v in detail.json()["versions"]] == [1, 2]

    destroyed_v1 = client.delete(f"/secrets/{secret_id}", params={"version": 1})
    assert destroyed_v1.status_code == 200
    disabled = client.post(f"/secrets/{secret_id}/disable")
    assert disabled.json()["disabled_at"] is not None
    assert client.get("/secrets").json()["secrets"] == []
    assert len(client.get("/secrets", params={"include_disabled": True}).json()["secrets"]) == 1
    destroyed = client.delete(f"/secrets/{secret_id}")
    assert destroyed.json()["value_set"] is False

    for response in (created, rotated, listed, detail, destroyed_v1, disabled, destroyed):
        assert VALUE not in response.text and VALUE_2 not in response.text


def test_member_cannot_list_or_mutate(db_session, seed):
    secret_id = _create(_client(db_session, seed["ws"], seed["owner"])).json()["id"]
    client = _client(db_session, seed["ws"], seed["member"])
    assert client.get("/secrets").status_code == 403
    assert _create(client, name="other").status_code == 403
    assert client.get(f"/secrets/{secret_id}").status_code == 403
    assert client.post(f"/secrets/{secret_id}/rotate", json={"value": VALUE_2}).status_code == 403
    assert client.post(f"/secrets/{secret_id}/disable").status_code == 403
    assert client.delete(f"/secrets/{secret_id}").status_code == 403


def test_secret_of_another_workspace_is_not_found(db_session, seed):
    secret_id = _create(_client(db_session, seed["ws"], seed["owner"])).json()["id"]
    client = _client(db_session, seed["other_ws"], seed["owner"])
    assert client.get(f"/secrets/{secret_id}").status_code == 404
    assert client.post(f"/secrets/{secret_id}/disable").status_code == 404
    assert client.get("/secrets").json()["secrets"] == []


def test_platform_scope_is_reserved_to_platform_admins(db_session, seed):
    owner = _client(db_session, seed["ws"], seed["owner"])
    assert _create(owner, scope="platform").status_code == 403
    assert owner.get("/secrets", params={"scope": "platform"}).status_code == 403
    admin = _client(db_session, seed["ws"], seed["platform_admin"])
    created = _create(admin, scope="platform", name="hf-platform")
    assert created.status_code == 201
    assert created.json()["ref"] == "secret://platform/hf-platform"
    assert owner.get(f"/secrets/{created.json()['id']}").status_code == 403
    assert admin.get("/secrets", params={"scope": "platform"}).json()["can_manage_platform"] is True


def test_system_scope_stays_inside_the_workspace(db_session, seed):
    client = _client(db_session, seed["ws"], seed["owner"])
    created = _create(client, scope="system", system_id=seed["system"].id)
    assert created.status_code == 201
    assert created.json()["ref"] == f"secret://system/{seed['system'].id}/openai-key"
    listed = client.get("/secrets", params={"scope": "system", "system_id": seed["system"].id})
    assert len(listed.json()["secrets"]) == 1
    assert _create(client, scope="system", system_id=seed["foreign_system"].id).status_code == 404
    member = _client(db_session, seed["ws"], seed["member"])
    assert _create(member, scope="system", system_id=seed["system"].id, name="x").status_code == 403


def test_errors_carry_codes_and_never_echo_the_body(db_session, seed):
    client = _client(db_session, seed["ws"], seed["owner"])
    assert _create(client).status_code == 201
    taken = _create(client)
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "SECRET_NAME_TAKEN"
    bad_name = _create(client, name="Not A Slug")
    assert bad_name.status_code == 400
    unknown = _create(client, name="ok", extra_field=1)
    assert unknown.status_code == 400
    wrong_type = client.post("/secrets", json={"name": "num", "value": 12345})
    assert wrong_type.status_code == 400
    not_object = client.post("/secrets", json=[VALUE])
    assert not_object.status_code == 400
    for response in (taken, bad_name, unknown, not_object):
        assert VALUE not in response.text


def test_missing_key_fails_closed_with_503(db_session, seed, monkeypatch):
    monkeypatch.delenv("SECRET_REGISTRY_FERNET_KEY", raising=False)
    reset_backends()
    response = _create(_client(db_session, seed["ws"], seed["owner"]))
    assert response.status_code == 503
    assert VALUE not in response.text


def test_consumers_come_from_resolution_audit(db_session, seed):
    client = _client(db_session, seed["ws"], seed["owner"])
    secret_id = _create(client).json()["id"]
    consumer = SecretConsumer(kind="connector", id="openai", workspace_id=seed["ws"].id)
    for _ in range(2):
        resolve(db_session, "secret://workspace/openai-key", consumer=consumer)
    response = client.get(f"/secrets/{secret_id}/consumers")
    assert response.status_code == 200
    consumers = response.json()["consumers"]
    assert len(consumers) == 1
    assert consumers[0]["kind"] == "connector" and consumers[0]["count"] == 2
    assert VALUE not in json.dumps(consumers)
