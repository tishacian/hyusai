"""M4.1 API composed with the hard M1 authorization/audit dependency."""

import io
import zipfile
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_exports as api
from app.models.audit import AuditLog
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.tabular_datasets import TabularError

permissions = pytest.importorskip(
    "app.services.ml_permissions", reason="M4.1 must be assembled after M1"
)


@pytest.fixture
def case(db_session, monkeypatch):
    ws = Workspace(name="Export", slug="export-" + uuid4().hex)
    user = User(
        id=str(uuid4()),
        username="export-" + uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
    )
    db_session.add_all([ws, user])
    db_session.flush()
    member = WorkspaceMember(
        workspace_id=ws.id, user_id=user.id, role="admin", role_template="workspace_admin"
    )
    model = MLModel(
        workspace_id=ws.id,
        name="Export",
        slug="export",
        version=3,
        task="classification",
        family="tabular",
        algo="logistic",
        target="y",
        status="ready",
        metrics_json={"artifact": {"fixture": "authorized"}},
    )
    db_session.add_all([member, model])
    db_session.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/ml-models")
    app.dependency_overrides[api.get_current_workspace] = lambda: ws
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_db] = lambda: db_session
    paths = []

    def build(row, folder, attested=()):
        paths.append(folder)
        target = folder / "fixture.zip"
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("README.md", "fixture verified separately")
        return target, {
            "artifact_fingerprint": api.artifact_fingerprint(row.metrics_json["artifact"]),
            "archive_sha256": "a" * 64,
            "archive_bytes": target.stat().st_size,
            "model_version": row.version,
            "attestations": sorted(item["id"] for item in attested),
        }

    monkeypatch.setattr(api, "build_export", build)
    return TestClient(app), ws, user, member, model, paths


def test_admin_export_is_audited_before_response_and_cleaned(db_session, case):
    client, ws, user, _, model, paths = case
    response = client.get(f"/ml-models/{model.id}/export")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-archive-sha256"] == "a" * 64
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read("README.md")
    assert not paths[0].exists()
    event = (
        db_session.query(AuditLog).filter_by(event_type="ml.model.export", workspace_id=ws.id).one()
    )
    assert event.actor == user.id
    assert event.details["version"] == 3
    assert event.details["after"]["archive_sha256"] == "a" * 64


@pytest.mark.parametrize(
    "role", ["workspace_viewer", "workspace_contributor", "workspace_reviewer"]
)
def test_export_is_admin_only_even_in_permission_report_mode(db_session, case, role):
    client, _, _, member, model, paths = case
    member.role_template = role
    db_session.commit()
    response = client.get(f"/ml-models/{model.id}/export")
    assert response.status_code == 403
    assert not paths


def test_export_never_resolves_another_workspace(db_session, case):
    client, _, _, _, model, paths = case
    other = Workspace(name="Other", slug="other-" + uuid4().hex)
    db_session.add(other)
    db_session.flush()
    model.workspace_id = other.id
    db_session.commit()
    assert client.get(f"/ml-models/{model.id}/export").status_code == 404
    assert not paths


def test_audit_failure_returns_no_archive_and_cleans(case, monkeypatch):
    client, _, _, _, model, paths = case

    def fail(*a, **k):
        raise TabularError(
            code="ML_AUDIT_UNAVAILABLE", message="Audit unavailable", status_code=503
        )

    monkeypatch.setattr(permissions, "audit", fail)
    assert client.get(f"/ml-models/{model.id}/export").status_code == 503
    assert not paths[0].exists()


def test_permission_revocation_during_copy_refuses_and_cleans(db_session, case, monkeypatch):
    client, _, _, member, model, paths = case
    original = api.build_export

    def revoke(*a, **k):
        result = original(*a, **k)
        member.role_template = "workspace_viewer"
        db_session.commit()
        return result

    monkeypatch.setattr(api, "build_export", revoke)
    assert client.get(f"/ml-models/{model.id}/export").status_code == 403
    assert not paths[0].exists()


def test_changed_artifact_during_copy_is_not_audited_as_export(db_session, case, monkeypatch):
    client, ws, _, _, model, paths = case
    original = api.build_export

    def replace(*a, **k):
        result = original(*a, **k)
        model.metrics_json = {"artifact": {"fixture": "changed"}}
        db_session.commit()
        return result

    monkeypatch.setattr(api, "build_export", replace)
    response = client.get(f"/ml-models/{model.id}/export")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ML_EXPORT_SOURCE_CHANGED"
    assert not paths[0].exists()
    assert (
        not db_session.query(AuditLog)
        .filter_by(event_type="ml.model.export", workspace_id=ws.id)
        .count()
    )


def test_response_cleans_temporary_archive_on_disconnected_client():
    import asyncio
    import tempfile
    from pathlib import Path

    from starlette.requests import ClientDisconnect

    temporary = tempfile.TemporaryDirectory(prefix="ml-export-disconnect-")
    folder = Path(temporary.name)
    archive = folder / "fixture.zip"
    archive.write_bytes(b"fixture")
    response = api._ExportResponse(archive, temporary=temporary)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_):
        raise OSError("disconnected")

    with pytest.raises((ClientDisconnect, OSError)):
        asyncio.run(
            response(
                {
                    "type": "http",
                    "method": "GET",
                    "asgi": {"spec_version": "2.4"},
                    "extensions": {},
                    "headers": [],
                },
                receive,
                send,
            )
        )
    assert not folder.exists()


def test_revoked_attestation_during_copy_is_not_exported(db_session, case, monkeypatch):
    """M4.2: the archive leaves only with the attestations still active."""
    from datetime import datetime

    from app.models.ml_requalification import MLRuntimeAttestation

    client, ws, _, _, model, paths = case
    row = MLRuntimeAttestation(
        workspace_id=ws.id,
        model_id=model.id,
        artifact_fingerprint=api.artifact_fingerprint(model.metrics_json["artifact"]),
        producer_runtime={"scikit-learn": "old"},
        reader_runtime={"scikit-learn": "new"},
        reader_digest="d" * 64,
        reference_sha256="r" * 64,
        rows_compared=1,
        metrics={},
        tolerances={},
        verdict="qualified",
        actor="admin",
        created_at=datetime.utcnow(),
    )
    db_session.add(row)
    db_session.commit()
    original = api.build_export
    seen = []

    def revoke(row_, folder, attested=()):
        seen.append([item["id"] for item in attested])
        result = original(row_, folder, attested)
        row.revoked_at = datetime.utcnow()
        db_session.commit()
        return result

    monkeypatch.setattr(api, "build_export", revoke)
    response = client.get(f"/ml-models/{model.id}/export")
    assert seen == [[row.id]]
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ML_EXPORT_SOURCE_CHANGED"
    assert not paths[0].exists()
