"""Tenant/identity boundaries, real registry transactions and asynchronous HTTP contract."""

import base64
import copy
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.endpoints import connections, secrets
from app.cli.migrate_connections import migrate_workspace
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.audit import AuditLog
from app.models.connector_connection import ConnectorConnection
from app.models.secret import Secret, SecretVersion
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.connection import ConnectionCreate, ConnectionUpdate
from app.services import secrets as registry
from app.services.connectors import connections as service
from app.services.connectors.profiles import (
    ConnectorProfile,
    ProfileError,
    get_profile,
    list_profiles,
)
from app.services.secrets.backends.base import reset_backends

PLAIN = "never-echo-this-password"


@pytest.fixture()
def setup(db_session, monkeypatch):
    monkeypatch.setattr(settings, "connector_framework_enabled", True)
    monkeypatch.setenv("SECRET_REGISTRY_FERNET_KEY", base64.urlsafe_b64encode(b"z" * 32).decode())
    monkeypatch.setattr(settings, "secret_registry_default_backend", "db")
    reset_backends()
    ws = Workspace(id=str(uuid4()), name="A", slug="connections-a")
    other = Workspace(id=str(uuid4()), name="B", slug="connections-b")
    users = [
        User(id=str(uuid4()), username=f"conn-{i}", email=f"conn-{i}@test.example", role="user")
        for i in range(3)
    ]
    db_session.add_all([ws, other, *users])
    db_session.flush()
    for workspace in (ws, other):
        for i, user in enumerate(users):
            db_session.add(
                WorkspaceMember(
                    workspace_id=workspace.id, user_id=user.id, role="owner" if i == 0 else "member"
                )
            )
    db_session.commit()
    meta = registry.create(
        db_session, scope="workspace", workspace_id=ws.id, name="pg", value=PLAIN, actor=users[0].id
    )
    yield ws, other, users, meta
    reset_backends()


def data(meta, **kwargs):
    return ConnectionCreate(
        name="ERP",
        profile_key="postgresql",
        values={"host": "db.example.test", "database": "erp", "username": "reader"},
        secret_refs={"password": meta["ref"]},
        **kwargs,
    )


def create(db, setup):
    ws, _, users, meta = setup
    row = service.create_connection(db, workspace_id=ws.id, actor=users[0].id, data=data(meta))
    db.commit()
    return row


def client(db, setup, user_index=0, workspace=None):
    ws, _, users, _ = setup
    app = FastAPI()
    app.include_router(connections.router, prefix="/connections")
    app.include_router(secrets.router, prefix="/secrets")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: users[user_index]
    app.dependency_overrides[get_current_workspace] = lambda: workspace or ws
    return TestClient(app)


def personal(db, setup, connection, user_index=1):
    ws, _, users, _ = setup
    user = users[user_index]
    meta = registry.create(
        db,
        scope="user",
        workspace_id=ws.id,
        user_id=user.id,
        name=f"conn-{connection.id}-access",
        value=f"personal-{user_index}",
        kind="token",
        actor=user.id,
    )
    grant = service.create_grant(
        db,
        connection,
        owner_user_id=user.id,
        token_refs={"access_token": meta["ref"]},
        scopes=["read"],
    )
    connection.values = {**connection.values, "auth_mode": "oauth_user"}
    db.commit()
    return grant, meta


def test_profiles_are_strict_and_not_qualification():
    assert {"postgresql", "sap_hana"} <= {p.key for p in list_profiles()}
    raw = get_profile("postgresql").model_dump()
    with pytest.raises(ValidationError):
        ConnectorProfile.model_validate(raw | {"on_connect": "DROP TABLE data"})
    changed = copy.deepcopy(raw)
    changed["parameters"] = [*changed["parameters"], changed["parameters"][0]]
    with pytest.raises(ValidationError):
        ConnectorProfile.model_validate(changed)
    assert not get_profile("sap_hana").capabilities.write_append


@pytest.mark.parametrize(
    "overrides",
    [
        {"port": True},
        {"port": 0},
        {"host": "https://db.test"},
        {"password": PLAIN},
        {"sslmode": "disable"},
        {"on_connect": "SELECT 1"},
    ],
)
def test_profile_refuses_coercion_unsafe_values_and_secrets(overrides):
    values = {"host": "db.example.test", "database": "erp", "username": "reader"} | overrides
    with pytest.raises(ProfileError):
        get_profile("postgresql").validate_values(values, {"password": "secret://workspace/pg"})


def test_registry_mandatory_even_for_demo(db_session, setup, monkeypatch):
    monkeypatch.delenv("SECRET_REGISTRY_FERNET_KEY")
    monkeypatch.delenv("CONNECTOR_SECRETS_FERNET_KEY", raising=False)
    monkeypatch.setattr(settings, "secret_registry_fernet_key", "")
    with pytest.raises(service.ConnectionError, match="CONNECTOR_REGISTRY_REQUIRED"):
        create(db_session, setup)
    assert db_session.query(ConnectorConnection).count() == 0


def test_multi_instance_scope_default_read_and_audit(db_session, setup):
    ws, other, users, meta = setup
    first = create(db_session, setup)
    second_data = data(meta).model_copy(update={"name": "Analytics"})
    service.create_connection(db_session, workspace_id=ws.id, actor=users[0].id, data=second_data)
    db_session.commit()
    assert first.access == "read" and first.values["sslmode"] == "verify-full"
    assert len(service.list_connections(db_session, ws.id)) == 2
    with pytest.raises(service.ConnectionError, match="CONNECTOR_NOT_FOUND"):
        service.get_connection(db_session, other.id, first.id)
    assert PLAIN not in json.dumps(service.serialize_connection(first), default=str)
    assert PLAIN not in json.dumps([r.details for r in db_session.query(AuditLog)], default=str)


def test_reference_lookup_cannot_cross_workspace_or_accept_personal_token(db_session, setup):
    ws, other, users, meta = setup
    with pytest.raises(service.ConnectionError, match="CONNECTOR_SECRET_UNAVAILABLE"):
        service.create_connection(
            db_session, workspace_id=other.id, actor=users[0].id, data=data(meta)
        )
    personal_meta = registry.create(
        db_session,
        scope="user",
        workspace_id=ws.id,
        user_id=users[0].id,
        name="token",
        value=PLAIN,
        actor=users[0].id,
    )
    with pytest.raises(service.ConnectionError, match="CONNECTOR_SECRET_SCOPE_VIOLATION"):
        service.create_connection(
            db_session, workspace_id=ws.id, actor=users[0].id, data=data(personal_meta)
        )


def test_revision_prevents_lost_update_and_deleted_connection_resurrection(db_session, setup):
    row = create(db_session, setup)
    actor = setup[2][0].id
    service.update_connection(
        db_session, row, actor=actor, data=ConnectionUpdate(revision=1, name="New name")
    )
    db_session.commit()
    with pytest.raises(service.ConnectionError, match="CONNECTOR_REVISION_CONFLICT"):
        service.update_connection(
            db_session, row, actor=actor, data=ConnectionUpdate(revision=1, name="Stale name")
        )
    db_session.rollback()
    assert row.name == "New name"
    service.delete_connection(db_session, row, actor=actor)
    db_session.commit()
    with pytest.raises(service.ConnectionError, match="CONNECTOR_NOT_FOUND"):
        service.resolve_credentials(db_session, row, user_id=actor)


def test_user_secrets_isolated_between_users_and_workspaces_and_revoke_on_removal(
    db_session, setup
):
    ws, other, users, _ = setup
    a, b = users[1:]
    meta = registry.create(
        db_session,
        scope="user",
        workspace_id=ws.id,
        user_id=a.id,
        name="same-name",
        value=PLAIN,
        actor=a.id,
    )
    registry.create(
        db_session,
        scope="user",
        workspace_id=other.id,
        user_id=a.id,
        name="same-name",
        value="other-workspace",
        actor=a.id,
    )
    registry.create(
        db_session,
        scope="user",
        workspace_id=ws.id,
        user_id=b.id,
        name="same-name",
        value="other-user",
        actor=b.id,
    )
    consumer = registry.SecretConsumer("connector", "test", workspace_id=ws.id, user_id=a.id)
    assert registry.resolve(db_session, meta["ref"], consumer=consumer).reveal() == PLAIN
    for user_id in (None, b.id, users[0].id):
        with pytest.raises(registry.SecretRegistryError, match="personal secret"):
            registry.resolve(
                db_session,
                meta["ref"],
                consumer=registry.SecretConsumer(
                    "connector", "test", workspace_id=ws.id, user_id=user_id
                ),
            )
    assert (
        registry.resolve(
            db_session,
            meta["ref"],
            consumer=registry.SecretConsumer(
                "connector", "test", workspace_id=other.id, user_id=a.id
            ),
        ).reveal()
        == "other-workspace"
    )
    db_session.query(WorkspaceMember).filter_by(workspace_id=ws.id, user_id=a.id).delete()
    db_session.commit()
    with pytest.raises(registry.SecretRegistryError):
        registry.resolve(db_session, meta["ref"], consumer=consumer)


def test_user_scope_metadata_api_denies_even_admin_and_does_not_echo_tokens(db_session, setup):
    own = client(db_session, setup, 1)
    response = own.post("/secrets", json={"scope": "user", "name": "oauth", "value": PLAIN})
    assert response.status_code == 201
    secret_id = response.json()["id"]
    for actor in (0, 2):
        other = client(db_session, setup, actor)
        assert other.get(f"/secrets/{secret_id}").status_code == 404
        assert (
            other.post(f"/secrets/{secret_id}/rotate", json={"value": "stolen"}).status_code == 404
        )
        assert other.get("/secrets?scope=user").json()["secrets"] == []
    assert own.get("/secrets?scope=user").json()["secrets"][0]["id"] == secret_id
    assert PLAIN not in response.text


def test_grants_cannot_be_reused_by_admin_another_user_or_scheduler(db_session, setup):
    row = create(db_session, setup)
    grant, _ = personal(db_session, setup, row)
    assert (
        service.resolve_credentials(db_session, row, user_id=setup[2][1].id)[
            "access_token"
        ].reveal()
        == "personal-1"
    )
    for user_id in (None, setup[2][0].id, setup[2][2].id):
        with pytest.raises(service.ConnectionError):
            service.resolve_credentials(db_session, row, user_id=user_id)
    service.revoke_grant(db_session, grant, actor=setup[2][0].id)
    db_session.commit()
    with pytest.raises(service.ConnectionError):
        service.resolve_credentials(db_session, row, user_id=setup[2][1].id)
    assert all(
        v.destroyed_at
        for v in db_session.query(SecretVersion).join(Secret).filter(Secret.scope == "user")
    )


def test_delegation_requires_owner_admin_approval_exact_published_version_and_expiry(
    db_session, setup
):
    ws, _, users, _ = setup
    row = create(db_session, setup)
    grant, _ = personal(db_session, setup, row)
    system = System(id=str(uuid4()), workspace_id=ws.id, name="Daily")
    version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=ws.id,
        version_number=1,
        flow_definition={},
        release_kind="publish",
    )
    db_session.add_all([system, version])
    db_session.flush()
    system.published_flow_version_id = version.id
    db_session.commit()
    with pytest.raises(service.ConnectionError):
        service.create_delegation(
            db_session,
            grant,
            actor=users[0].id,
            system_version_id=version.id,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    delegation = service.create_delegation(
        db_session,
        grant,
        actor=users[1].id,
        system_version_id=version.id,
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.commit()
    kwargs = dict(system_id=system.id, system_version_id=version.id, delegation_id=delegation.id)
    with pytest.raises(service.ConnectionError):
        service.resolve_credentials(db_session, row, **kwargs)
    with pytest.raises(service.ConnectionError):
        service.approve_delegation(db_session, delegation, actor=users[2])
    service.approve_delegation(db_session, delegation, actor=users[0])
    db_session.commit()
    assert (
        service.resolve_credentials(db_session, row, **kwargs)["access_token"].reveal()
        == "personal-1"
    )
    with pytest.raises(service.ConnectionError):
        service.resolve_credentials(
            db_session, row, **(kwargs | {"system_version_id": str(uuid4())})
        )
    delegation.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(service.ConnectionError):
        service.resolve_credentials(db_session, row, **kwargs)


def test_membership_cleanup_destroys_personal_tokens_and_delegations(db_session, setup):
    row = create(db_session, setup)
    grant, meta = personal(db_session, setup, row)
    service.revoke_user_grants(
        db_session, workspace_id=setup[0].id, user_id=setup[2][1].id, actor=setup[2][0].id
    )
    db_session.commit()
    assert grant.revoked_at is not None
    assert registry.get_metadata(db_session, meta["id"])["value_set"] is False


def test_connection_api_flag_permission_validation_and_tenant_isolation(
    db_session, setup, monkeypatch
):
    admin = client(db_session, setup)
    response = admin.post("/connections", json=data(setup[3]).model_dump())
    assert response.status_code == 201, response.text
    row_id = response.json()["id"]
    assert (
        next(
            p
            for p in admin.get("/connections/profiles").json()["profiles"]
            if p["key"] == "postgresql"
        )["certification"]
        == "unverified"
    )
    member = client(db_session, setup, 1)
    assert member.get(f"/connections/{row_id}").status_code == 200
    assert member.post("/connections", json=data(setup[3]).model_dump()).status_code == 403
    assert member.delete(f"/connections/{row_id}").status_code == 403
    assert member.post(f"/connections/{row_id}/test").status_code == 403
    assert (
        client(db_session, setup, workspace=setup[1]).get(f"/connections/{row_id}").status_code
        == 404
    )
    invalid = admin.post("/connections", json={**data(setup[3]).model_dump(), "password": PLAIN})
    assert invalid.status_code == 400 and PLAIN not in invalid.text
    monkeypatch.setattr(settings, "connector_framework_enabled", False)
    assert admin.get("/connections/profiles").status_code == 404
    assert admin.get("/connections").status_code == 404
    assert admin.get(f"/connections/{row_id}").status_code == 404


def test_dispatch_commits_only_public_run_and_returns_pending_handle(
    db_session, setup, monkeypatch
):
    from app.services import compute_runs
    from app.workers.celery_connectors import celery_connectors

    row = create(db_session, setup)
    sent = []
    monkeypatch.setattr(
        celery_connectors, "send_task", lambda *args, **kwargs: sent.append((args, kwargs))
    )
    response = client(db_session, setup).post(
        f"/connections/{row.id}/preview",
        json={"schema": "public", "table": "customers", "limit": 10},
    )
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["status"] == "queued"
    assert sent[0][1]["args"] == [result["id"]]
    assert PLAIN not in json.dumps(sent)
    assert (
        client(db_session, setup, 1).get(f"/connections/{row.id}/runs/{result['id']}").status_code
        == 404
    )
    assert (
        client(db_session, setup)
        .post(f"/connections/{row.id}/runs/{result['id']}/cancel")
        .status_code
        == 200
    )
    assert compute_runs.get_run(db_session, setup[0].id, result["id"]).cancel_requested


def test_legacy_dry_run_never_decrypts_or_writes_and_apply_is_idempotent(
    db_session, setup, monkeypatch
):
    from app.services.connectors.generic import service as legacy

    ws, _, _, _ = setup
    legacy.set_config(
        db_session,
        ws,
        "postgresql",
        {"host": "legacy.example.test", "database": "erp", "username": "reader", "password": PLAIN},
        actor=setup[2][0].id,
    )
    original_settings = copy.deepcopy(ws.settings)
    original_decrypt = legacy._decrypt_secret
    monkeypatch.setattr(legacy, "_decrypt_secret", lambda _: pytest.fail("dry-run decrypted"))
    before = (db_session.query(Secret).count(), db_session.query(AuditLog).count())
    assert migrate_workspace(db_session, ws.id)[0]["action"] == "would_migrate"
    assert before == (db_session.query(Secret).count(), db_session.query(AuditLog).count())
    assert db_session.query(ConnectorConnection).count() == 0
    monkeypatch.setattr(legacy, "_decrypt_secret", original_decrypt)
    assert migrate_workspace(db_session, ws.id, apply=True)[0]["action"] == "migrated"
    assert migrate_workspace(db_session, ws.id, apply=True)[0]["action"] == "already_migrated"
    assert db_session.query(ConnectorConnection).count() == 1
    db_session.refresh(ws)
    assert ws.settings == original_settings
    assert (
        db_session.query(AuditLog).filter_by(event_type="connection.legacy.migrated").count() == 1
    )


def test_registry_create_can_join_and_rollback_connection_unit_of_work(db_session, setup):
    ws, _, users, _ = setup
    before = db_session.query(Secret).count()
    registry.create(
        db_session,
        scope="workspace",
        workspace_id=ws.id,
        name="transaction-secret",
        value=PLAIN,
        actor=users[0].id,
        commit=False,
    )
    db_session.rollback()
    assert db_session.query(Secret).count() == before
    assert (
        not db_session.query(AuditLog)
        .filter(
            AuditLog.event_type == "secret.created",
            AuditLog.details["ref"].as_string() == "secret://workspace/transaction-secret",
        )
        .first()
    )


def test_cross_connection_token_reuse_with_pinned_version_is_refused(db_session, setup):
    row = create(db_session, setup)
    _, meta = personal(db_session, setup, row)
    other = service.create_connection(
        db_session,
        workspace_id=setup[0].id,
        actor=setup[2][0].id,
        data=data(setup[3]).model_copy(update={"name": "Second"}),
    )
    db_session.commit()
    with pytest.raises(service.ConnectionError, match="CONNECTOR_GRANT_TOKEN_REUSED"):
        service.create_grant(
            db_session,
            other,
            owner_user_id=setup[2][1].id,
            token_refs={"access_token": meta["ref"] + "#1"},
            scopes=["read"],
        )


def test_grant_revoke_api_owner_or_admin_only(db_session, setup):
    row = create(db_session, setup)
    grant, meta = personal(db_session, setup, row)
    url = f"/connections/{row.id}/grants/{grant.id}"
    assert client(db_session, setup, 2).delete(url).status_code == 404
    assert client(db_session, setup, 2).get(f"/connections/{row.id}/grants").json() == {
        "grants": []
    }
    response = client(db_session, setup, 0).get(f"/connections/{row.id}/grants")
    assert response.status_code == 200
    assert "token_refs" not in response.text and "personal-1" not in response.text
    assert client(db_session, setup, 0).delete(url).status_code == 200
    assert registry.get_metadata(db_session, meta["id"])["value_set"] is False


def test_hana_demo_migration_is_explicit_strict_and_unqualified(db_session, setup):
    ws = setup[0]
    ws.settings = {
        "connectors": {
            "sap_hana": {
                "host": "hana.example.test",
                "user": "demo",
                "demo_mode": True,
                "encrypt": True,
                "ssl_validate_certificate": True,
            }
        }
    }
    db_session.commit()
    migrate_workspace(db_session, ws.id, apply=True)
    row = db_session.query(ConnectorConnection).one()
    assert row.values["demo_mode"] is True and row.secret_refs == {}
    assert service.serialize_connection(row)["certification"] == "unverified"
    assert service.resolve_credentials(db_session, row, user_id=setup[2][0].id) == {}
