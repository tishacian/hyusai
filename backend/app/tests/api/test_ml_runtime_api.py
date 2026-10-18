"""M4.2 HTTP surface: workspace scoping, strict admin rights and safe projections."""

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_runtime as api
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.ml_requalification import MLRuntimeAttestation
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.resources.ml_artifact_contract import runtime_versions
from app.services import ml_requalification as service
from app.services.ml.artifacts import artifact_fingerprint, runtime_digest


def _artifact(**runtime):
    return {
        "contract_version": 1,
        "family": "tabular",
        "serialization": "skops",
        "trust_profile": "tabular-skops-v1",
        "runtime": {**runtime_versions("tabular", "skops"), **runtime},
        "trusted_types": [],
        "files": {"MLmodel": "0" * 64},
        "file_sizes": {"MLmodel": 1},
        "total_bytes": 1,
    }


@pytest.fixture
def case(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ml_rbac_enforced", False)
    ws = Workspace(name="Runtime", slug="runtime-" + uuid4().hex)
    user = User(
        id=str(uuid4()),
        username="runtime-" + uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add_all([ws, user])
    db_session.flush()
    member = WorkspaceMember(
        workspace_id=ws.id, user_id=user.id, role="admin", role_template="workspace_admin"
    )
    # An older producer: this reader differs on scikit-learn only.
    artifact = _artifact(**{"scikit-learn": "0.0.1"})
    model = MLModel(
        workspace_id=ws.id,
        name="Runtime",
        slug="runtime",
        version=2,
        task="classification",
        family="tabular",
        algo="gradient_boosting",
        target="y",
        status="ready",
        metrics_json={"artifact": artifact, "evaluation": {"status": "stored", "sha256": "e" * 64}},
    )
    db_session.add_all([member, model])
    db_session.flush()
    sha = "a" * 64
    model.metrics_json = {
        **model.metrics_json,
        "runtime_reference": {
            "status": "stored",
            "schema": service.SCHEMA,
            "sha256": sha,
            "key": service.reference_key(ws.id, model.id, sha),
            "bytes": 10,
            "rows": 7,
            "artifact_fingerprint": artifact_fingerprint(artifact),
            "producer_runtime": artifact["runtime"],
            "partition_sha256": "e" * 64,
            "captured_at": "2026-10-16T10:00:00",
            "captured_by": "system:training",
        },
    }
    db_session.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/ml-models")
    app.dependency_overrides[api.get_current_workspace] = lambda: ws
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_db] = lambda: db_session
    dispatched = []
    monkeypatch.setattr(service, "_dispatch", lambda job_id, model: dispatched.append(job_id))
    return TestClient(app), ws, user, member, model, dispatched


def _attestation(db, model, *, verdict="qualified"):
    artifact = model.metrics_json["artifact"]
    reader = runtime_versions("tabular", "skops")
    row = MLRuntimeAttestation(
        workspace_id=model.workspace_id,
        model_id=model.id,
        artifact_fingerprint=artifact_fingerprint(artifact),
        producer_runtime=artifact["runtime"],
        reader_runtime=reader,
        reader_digest=runtime_digest(reader),
        reference_sha256="a" * 64,
        rows_compared=7,
        metrics={"label_disagreements": 0, "max_abs_proba_diff": 0.0},
        tolerances=service.tolerances(),
        verdict=verdict,
        error_code=None if verdict == "qualified" else "ML_REQUALIFICATION_OUTPUT_MISMATCH",
        actor="someone",
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    return row


def test_state_names_the_gap_without_storage_locations_or_rows(case):
    client, _, _, member, model, _ = case
    member.role_template = "workspace_viewer"
    body = client.get(f"/ml-models/{model.id}/runtime").json()
    assert body["status"] == "requalification_required"
    assert body["differences"] == [
        {
            "package": "scikit-learn",
            "producer": "0.0.1",
            "reader": runtime_versions("tabular", "skops")["scikit-learn"],
        }
    ]
    assert body["reference"] == {
        "status": "stored",
        "rows": 7,
        "sha256": "a" * 64,
        "captured_at": "2026-10-16T10:00:00",
        "captured_by": "system:training",
    }
    assert body["can_requalify"] is True and body["can_capture"] is False
    assert "key" not in str(body["reference"]) and "workspaces/" not in str(body)


@pytest.mark.parametrize(
    "role", ["workspace_viewer", "workspace_contributor", "workspace_reviewer"]
)
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/runtime/reference"),
        ("post", "/runtime/requalify"),
        ("delete", "/runtime/attestations/any"),
    ],
)
def test_mutations_are_admin_only_even_in_report_mode(db_session, case, role, method, path):
    client, _, _, member, model, dispatched = case
    member.role_template = role
    db_session.commit()
    response = getattr(client, method)(f"/ml-models/{model.id}{path}")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ML_FORBIDDEN_ACTION"
    assert not dispatched
    assert not db_session.query(WorkspaceJob).count()


def test_another_workspace_model_is_never_resolved(db_session, case):
    client, _, _, _, model, dispatched = case
    other = Workspace(name="Other", slug="other-" + uuid4().hex)
    db_session.add(other)
    db_session.flush()
    model.workspace_id = other.id
    db_session.commit()
    assert client.get(f"/ml-models/{model.id}/runtime").status_code == 404
    assert client.post(f"/ml-models/{model.id}/runtime/requalify").status_code == 404
    assert not dispatched


def test_requalify_queues_one_job_per_model_artifact_and_reader(db_session, case):
    client, _, user, _, model, dispatched = case
    first = client.post(f"/ml-models/{model.id}/runtime/requalify")
    assert first.status_code == 202
    body = first.json()
    assert body["started"] is True and body["job"]["status"] == "queued"
    assert body["runtime"]["jobs"]["ml_requalification"]["id"] == body["job"]["id"]
    second = client.post(f"/ml-models/{model.id}/runtime/requalify").json()
    assert second["started"] is False and second["job"]["id"] == body["job"]["id"]
    assert dispatched == [body["job"]["id"]]
    job = db_session.get(WorkspaceJob, body["job"]["id"])
    assert job.created_by_user_id == user.id
    assert job.input_ref["reader_digest"] == runtime_digest(runtime_versions("tabular", "skops"))


def test_capture_under_another_runtime_is_refused_with_a_code(case):
    client, _, _, _, model, dispatched = case
    response = client.post(f"/ml-models/{model.id}/runtime/reference")
    # The reference already exists for this artifact: nothing to start.
    assert response.status_code == 202 and response.json()["started"] is False
    model.metrics_json = {
        key: value for key, value in model.metrics_json.items() if key != "runtime_reference"
    }
    response = client.post(f"/ml-models/{model.id}/runtime/reference")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED"
    assert not dispatched


def test_revoke_is_audited_idempotent_and_refuses_failed_attempts(db_session, case):
    client, ws, user, _, model, _ = case
    active = _attestation(db_session, model)
    failed = _attestation(db_session, model, verdict="failed")
    state = client.get(f"/ml-models/{model.id}/runtime").json()
    assert state["status"] == "attested"
    assert [item["id"] for item in state["attestations"]][0] == active.id
    response = client.delete(f"/ml-models/{model.id}/runtime/attestations/{active.id}")
    assert response.status_code == 200
    assert response.json()["attestation"]["active"] is False
    assert response.json()["runtime"]["status"] == "requalification_required"
    again = client.delete(f"/ml-models/{model.id}/runtime/attestations/{active.id}")
    assert again.status_code == 200
    events = db_session.query(AuditLog).filter_by(
        event_type="ml.model.attestation_revoke", workspace_id=ws.id
    )
    assert events.count() == 1 and events.one().actor == user.id
    refused = client.delete(f"/ml-models/{model.id}/runtime/attestations/{failed.id}")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "ML_ATTESTATION_NOT_ACTIVE"
    assert client.delete(f"/ml-models/{model.id}/runtime/attestations/unknown").status_code == 404
