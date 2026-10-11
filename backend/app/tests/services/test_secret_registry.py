"""Secret registry: CRUD, rotation, scopes, audit, fail-closed and SecretValue."""

from __future__ import annotations

import base64
import copy
import json
import pickle
from datetime import datetime, timedelta

import pytest

from app.models.audit import AuditLog
from app.models.secret import Secret, SecretVersion
from app.models.system import System
from app.models.workspace import Workspace
from app.services.secrets import (
    SecretConsumer,
    SecretRegistryError,
    SecretValue,
    create,
    destroy,
    disable,
    get_backend,
    list_metadata,
    parse_ref,
    resolve,
    rotate,
)
from app.services.secrets.backends.base import SecretBackend, reset_backends

PLAIN = "sk-test-value-0001"
PLAIN_2 = "sk-test-value-0002"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("SECRET_REGISTRY_FERNET_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
    reset_backends()
    yield
    reset_backends()


@pytest.fixture()
def ws(db_session):
    a = Workspace(id="sec-ws-a", slug="sec-a", name="A")
    b = Workspace(id="sec-ws-b", slug="sec-b", name="B")
    db_session.add_all([a, b])
    db_session.flush()
    sys_a = System(id="sec-sys-a", workspace_id=a.id, name="Sys A")
    db_session.add(sys_a)
    db_session.commit()
    return a, b, sys_a


def _consumer(workspace_id=None, system_id=None):
    return SecretConsumer(
        kind="test", id="t1", workspace_id=workspace_id, system_id=system_id, run_id="run-1"
    )


def test_parse_ref():
    assert parse_ref("secret://workspace/hf-token").scope == "workspace"
    ref = parse_ref("secret://system/sys-1/api#3")
    assert (ref.scope, ref.system_id, ref.name, ref.version) == ("system", "sys-1", "api", 3)
    assert str(ref) == "secret://system/sys-1/api#3"
    assert str(parse_ref("secret://platform/hf")) == "secret://platform/hf"
    for bad in ["", "secret://other/x", "secret://workspace/", "secret://workspace/Up", "x#1"]:
        with pytest.raises(SecretRegistryError) as exc:
            parse_ref(bad)
        assert exc.value.code == "SECRET_INVALID_REF"


def test_secret_value_never_leaks():
    value = SecretValue(PLAIN)
    assert str(value) == "***" and PLAIN not in repr(value) and f"{value}" == "***"
    assert value.reveal() == PLAIN
    with pytest.raises(TypeError):
        json.dumps({"v": value})
    with pytest.raises(TypeError):
        pickle.dumps(value)
    assert copy.deepcopy(value) is value
    with pytest.raises(AttributeError):
        value._value = "x"


def test_create_resolve_rotate_and_audit(db_session, ws):
    a, _, _ = ws
    meta = create(
        db_session,
        scope="workspace",
        workspace_id=a.id,
        name="hf-token",
        kind="token",
        value=PLAIN,
        actor="user:1",
        metadata={"provider": "hf"},
    )
    assert meta["ref"] == "secret://workspace/hf-token"
    assert meta["value_set"] is True and meta["current_version"] == 1
    assert PLAIN not in json.dumps(meta, default=str)

    row = db_session.query(SecretVersion).filter_by(secret_id=meta["id"]).one()
    assert row.ciphertext and PLAIN not in row.ciphertext

    got = resolve(db_session, meta["ref"], consumer=_consumer(a.id))
    assert isinstance(got, SecretValue) and got.reveal() == PLAIN

    rotated = rotate(db_session, meta["id"], value=PLAIN_2, actor="user:1")
    assert rotated["current_version"] == 2 and rotated["rotated_at"] is not None
    assert resolve(db_session, meta["ref"], consumer=_consumer(a.id)).reveal() == PLAIN_2
    assert resolve(db_session, meta["ref"] + "#1", consumer=_consumer(a.id)).reveal() == PLAIN

    db_session.expire_all()
    events = [e.event_type for e in db_session.query(AuditLog).filter_by(workspace_id=a.id)]
    for expected in ("secret.created", "secret.rotated", "secret.resolved"):
        assert expected in events
    for entry in db_session.query(AuditLog).filter(AuditLog.event_type.like("secret.%")):
        dumped = json.dumps(entry.details, default=str)
        assert PLAIN not in dumped and PLAIN_2 not in dumped
    resolved = db_session.query(AuditLog).filter_by(event_type="secret.resolved").first().details
    assert resolved["consumer"]["run_id"] == "run-1"


def test_names_unique_per_owner(db_session, ws):
    a, b, _ = ws
    create(db_session, scope="workspace", workspace_id=a.id, name="k", value=PLAIN, actor="u")
    create(db_session, scope="workspace", workspace_id=b.id, name="k", value=PLAIN, actor="u")
    create(db_session, scope="platform", name="k", value=PLAIN, actor="u")
    for kwargs in ({"scope": "workspace", "workspace_id": a.id}, {"scope": "platform"}):
        with pytest.raises(SecretRegistryError) as exc:
            create(db_session, name="k", value=PLAIN, actor="u", **kwargs)
        assert exc.value.code == "SECRET_NAME_TAKEN"
    with pytest.raises(SecretRegistryError):
        create(
            db_session, scope="workspace", workspace_id=a.id, name="Bad Name", value="x", actor="u"
        )
    with pytest.raises(SecretRegistryError):
        create(db_session, scope="workspace", workspace_id=a.id, name="empty", value="", actor="u")


def test_scope_isolation(db_session, ws):
    a, b, sys_a = ws
    create(db_session, scope="workspace", workspace_id=a.id, name="k", value=PLAIN, actor="u")
    with pytest.raises(SecretRegistryError) as exc:
        resolve(db_session, "secret://workspace/k", consumer=_consumer(b.id))
    assert exc.value.code == "SECRET_NOT_FOUND"
    with pytest.raises(SecretRegistryError) as exc:
        resolve(db_session, "secret://workspace/k", consumer=_consumer(None))
    assert exc.value.code == "SECRET_SCOPE_VIOLATION"

    sys_meta = create(
        db_session, scope="system", system_id=sys_a.id, name="s", value=PLAIN, actor="u"
    )
    assert sys_meta["workspace_id"] == a.id
    assert sys_meta["ref"] == f"secret://system/{sys_a.id}/s"
    assert (
        resolve(db_session, sys_meta["ref"], consumer=_consumer(a.id, sys_a.id)).reveal() == PLAIN
    )
    for consumer in (_consumer(a.id, "other-system"), _consumer(b.id)):
        with pytest.raises(SecretRegistryError) as exc:
            resolve(db_session, sys_meta["ref"], consumer=consumer)
        assert exc.value.code == "SECRET_SCOPE_VIOLATION"
    db_session.expire_all()
    assert db_session.query(AuditLog).filter_by(event_type="secret.resolve_denied").count() >= 2

    with pytest.raises(SecretRegistryError):
        create(
            db_session,
            scope="system",
            system_id=sys_a.id,
            workspace_id=b.id,
            name="x",
            value="v",
            actor="u",
        )

    platform = create(db_session, scope="platform", name="hf", value=PLAIN, actor="admin")
    assert resolve(db_session, platform["ref"], consumer=_consumer(b.id)).reveal() == PLAIN

    names = [m["name"] for m in list_metadata(db_session, scope="workspace", workspace_id=a.id)]
    assert names == ["k"]
    assert [m["name"] for m in list_metadata(db_session, scope="system", system_id=sys_a.id)] == [
        "s"
    ]


def test_disable_destroy_and_expiry(db_session, ws):
    a, _, _ = ws
    meta = create(
        db_session, scope="workspace", workspace_id=a.id, name="k", value=PLAIN, actor="u"
    )
    rotate(db_session, meta["id"], value=PLAIN_2, actor="u")
    destroy(db_session, meta["id"], actor="u", version=1)
    with pytest.raises(SecretRegistryError) as exc:
        resolve(db_session, "secret://workspace/k#1", consumer=_consumer(a.id))
    assert exc.value.code == "SECRET_VERSION_DESTROYED"
    assert resolve(db_session, "secret://workspace/k", consumer=_consumer(a.id)).reveal() == PLAIN_2

    disabled = disable(db_session, meta["id"], actor="u")
    assert disabled["disabled_at"] is not None
    assert list_metadata(db_session, scope="workspace", workspace_id=a.id) == []
    with pytest.raises(SecretRegistryError) as exc:
        resolve(db_session, "secret://workspace/k", consumer=_consumer(a.id))
    assert exc.value.code == "SECRET_DISABLED"
    with pytest.raises(SecretRegistryError):
        rotate(db_session, meta["id"], value="v", actor="u")

    final = destroy(db_session, meta["id"], actor="u")
    assert final["value_set"] is False
    assert all(
        v.ciphertext is None
        for v in db_session.query(SecretVersion).filter_by(secret_id=meta["id"])
    )
    db_session.expire_all()
    events = {e.event_type for e in db_session.query(AuditLog).filter_by(workspace_id=a.id)}
    assert {"secret.disabled", "secret.destroyed"} <= events

    exp = create(
        db_session,
        scope="workspace",
        workspace_id=a.id,
        name="old",
        value=PLAIN,
        actor="u",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )
    with pytest.raises(SecretRegistryError) as exc:
        resolve(db_session, exp["ref"], consumer=_consumer(a.id))
    assert exc.value.code == "SECRET_EXPIRED"


def test_fail_closed_without_key_or_backend(db_session, ws, monkeypatch):
    a, _, _ = ws
    meta = create(
        db_session, scope="workspace", workspace_id=a.id, name="k", value=PLAIN, actor="u"
    )
    monkeypatch.delenv("SECRET_REGISTRY_FERNET_KEY")
    monkeypatch.delenv("CONNECTOR_SECRETS_FERNET_KEY", raising=False)
    with pytest.raises(SecretRegistryError) as exc:
        resolve(db_session, meta["ref"], consumer=_consumer(a.id))
    assert exc.value.code == "SECRET_KEY_NOT_CONFIGURED"
    with pytest.raises(SecretRegistryError):
        create(db_session, scope="workspace", workspace_id=a.id, name="k2", value=PLAIN, actor="u")
    assert db_session.query(Secret).filter_by(name="k2").count() == 0

    monkeypatch.setenv("CONNECTOR_SECRETS_FERNET_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
    assert resolve(db_session, meta["ref"], consumer=_consumer(a.id)).reveal() == PLAIN


def test_openbao_stub_fails_closed(db_session, ws):
    a, _, _ = ws
    assert isinstance(get_backend("openbao"), SecretBackend)
    assert get_backend("openbao").health()["ok"] is False
    with pytest.raises(SecretRegistryError) as exc:
        create(
            db_session,
            scope="workspace",
            workspace_id=a.id,
            name="bao",
            value=PLAIN,
            actor="u",
            backend="openbao",
        )
    assert exc.value.code == "SECRET_BACKEND_UNAVAILABLE"
    db_session.rollback()

    # A row already on openbao must never be served from the db backend.
    secret = Secret(
        scope="workspace",
        workspace_id=a.id,
        owner_key=a.id,
        name="bao",
        kind="token",
        backend="openbao",
        current_version=1,
        meta={},
    )
    db_session.add(secret)
    db_session.flush()
    db_session.add(SecretVersion(secret_id=secret.id, version=1, backend_ref="agentium/x#1"))
    db_session.commit()
    with pytest.raises(SecretRegistryError) as exc:
        resolve(db_session, "secret://workspace/bao", consumer=_consumer(a.id))
    assert exc.value.code == "SECRET_BACKEND_UNAVAILABLE"
    with pytest.raises(SecretRegistryError) as exc:
        get_backend("nope")
    assert exc.value.code == "SECRET_BACKEND_UNAVAILABLE"


def test_migration_upgrade_matches_models_and_downgrades():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "124_secret_registry.py"
    spec = importlib.util.spec_from_file_location("migration_124_secret_registry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == path.stem and len(module.revision) <= 32
    assert module.down_revision == "123_huggingface_connector"

    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        meta = sa.MetaData()
        sa.Table("workspaces", meta, sa.Column("id", sa.String(36), primary_key=True))
        sa.Table("systems", meta, sa.Column("id", sa.String(36), primary_key=True))
        meta.create_all(bind)
        ops = Operations(MigrationContext.configure(bind))
        original = module.op
        module.op = ops
        try:
            module.upgrade()
            inspector = sa.inspect(bind)
            for model in (Secret, SecretVersion):
                db_cols = {c["name"] for c in inspector.get_columns(model.__tablename__)}
                assert db_cols == {c.name for c in model.__table__.columns}
            module.downgrade()
            assert not {"secrets", "secret_versions"} & set(sa.inspect(bind).get_table_names())
        finally:
            module.op = original
