"""HTTP governance proves controls cannot be bypassed by direct callers."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_governance, ml_models
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.tabular import MLModelApiKey
from app.services.ml_governance import admit
from app.tests.services.test_ml_governance import subject as subject


@pytest.fixture
def client(db_session, subject):
    workspace, user, _, _ = subject
    app = FastAPI()
    app.include_router(ml_models.router, prefix="/ml-models")
    app.include_router(ml_governance.router, prefix="/ml-governance")
    app.dependency_overrides[ml_models.get_current_workspace] = lambda: workspace
    app.dependency_overrides[ml_models.get_current_user] = lambda: user
    app.dependency_overrides[ml_models.get_db] = lambda: db_session
    return TestClient(app)


@pytest.mark.parametrize("role", ["workspace_viewer", "workspace_contributor"])
@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("post", "/keys", {}),
        ("post", "/champion", None),
        ("post", "/publish", {}),
        ("delete", "", None),
    ],
)
def test_direct_mutations_refuse_insufficient_roles(
    client, db_session, subject, role, method, suffix, body
):
    _, _, member, model = subject
    member.role_template = role
    db_session.commit()
    response = client.request(method, f"/ml-models/{model.id}{suffix}", json=body)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "ML_FORBIDDEN_ACTION"
    assert db_session.query(MLModelApiKey).count() == 0


def test_policy_is_capped_audited_and_reports_inactive_retention(
    client, db_session, subject, monkeypatch
):
    monkeypatch.setattr(settings, "ml_retention_enabled", False)
    result = client.get("/ml-governance").json()
    assert result["retention_enabled"] is False
    result["policy"]["predict_requests_per_minute"] = 999999
    response = client.put("/ml-governance/policy", json=result["policy"])
    assert response.status_code == 200
    assert (
        response.json()["policy"]["predict_requests_per_minute"]
        == settings.ml_predict_rate_per_minute
    )
    audit = db_session.query(AuditLog).filter_by(event_type="ml.model.policy_changed").one()
    assert audit.actor == subject[1].id and audit.details["before"]


def test_key_audit_identifies_credential_without_secret(client, db_session, subject):
    response = client.post(f"/ml-models/{subject[3].id}/keys", json={"name": "Integration"})
    assert response.status_code == 200, response.text
    key = response.json()["key"]
    audit = db_session.query(AuditLog).filter_by(event_type="ml.model.key_created").one()
    assert audit.details["after"]["key_id"] == key["id"]
    assert audit.details["client_ip"] == "testclient"
    assert key["secret"] not in str(audit.details)


def test_rate_refusal_has_retry_after(client, db_session, subject, monkeypatch):
    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 1)

    def predict(db, model, rows, **kwargs):
        admit(db, model, rows=len(rows), now=datetime(2026, 10, 15, 12, 0, 5))
        return {"predictions": [1]}

    monkeypatch.setattr(ml_models, "predict_rows", predict)
    url = f"/ml-models/{subject[3].id}/predict"
    key = client.post(f"/ml-models/{subject[3].id}/keys", json={}).json()["key"]
    headers = {"X-API-Key": key["secret"]}
    assert client.post(url, headers=headers, json={"inputs": [{"x": 1}]}).status_code == 200
    response = client.post(url, headers=headers, json={"inputs": [{"x": 1}]})
    assert response.status_code == 429 and response.headers["Retry-After"] == "55"


def test_failed_audit_prevents_key_creation(client, db_session, subject, monkeypatch):
    from app.services import ml_permissions

    monkeypatch.setattr(ml_permissions, "emit_audit_event", lambda **_: None)
    response = client.post(f"/ml-models/{subject[3].id}/keys", json={})
    assert response.status_code == 503
    db_session.rollback()
    assert db_session.query(MLModelApiKey).count() == 0


def test_batch_feedback_selects_one_retained_sample(client, db_session, subject):
    from app.models.ml_feedback import MLPredictionFeedback
    from app.services.tabular_predict import journal_call

    model = subject[3]
    identifier = journal_call(
        db_session,
        requested=model,
        served=model,
        caller="session",
        rows=[{"x": 1}, {"x": 2}],
        answers=[{"prediction": 1}, {"prediction": 2}],
        duration_ms=2,
    )
    url = f"/ml-models/{model.id}"
    response = client.post(url + "/feedback", json={"prediction_id": identifier, "label": "3"})
    assert (
        response.status_code == 422
        and response.json()["detail"]["code"] == "ML_FEEDBACK_SAMPLE_REQUIRED"
    )
    samples = client.get(url + "/predictions/" + identifier).json()["prediction"]["samples"]
    assert len(samples) == 2 and samples[0]["sample_id"] != samples[1]["sample_id"]
    response = client.post(
        url + "/feedback",
        json={"prediction_id": identifier, "sample_id": samples[1]["sample_id"], "label": "3"},
    )
    assert response.status_code == 200, response.text
    feedback = db_session.query(MLPredictionFeedback).one()
    assert feedback.sample_index == 1 and feedback.label == "3.0"


def test_legacy_readiness_is_visible_without_granting_training_or_keys(
    client, db_session, subject, monkeypatch
):
    _, _, member, model = subject
    member.role_template = "workspace_viewer"
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    model.is_champion = True
    db_session.commit()
    response = client.get(f"/ml-models/{model.id}")
    assert response.status_code == 200, response.text
    serving = response.json()["serving"]
    assert serving["callable"] is False and serving["is_serving"] is True
    assert serving["readiness"]["action"] == "retrain"
    assert serving["refusal"]["code"] == "ML_ARTIFACT_LEGACY_UNSUPPORTED"
    assert serving["permissions"]["train"] is False
    assert serving["permissions"]["keys"] is False
    assert serving["keys"] == []


def test_readiness_never_exposes_another_workspace_model(client, db_session, subject):
    from uuid import uuid4

    from app.models.workspace import Workspace

    foreign = Workspace(name="Other", slug="other-" + uuid4().hex, settings={})
    db_session.add(foreign)
    db_session.flush()
    subject[3].workspace_id = foreign.id
    db_session.commit()
    response = client.get(f"/ml-models/{subject[3].id}")
    assert response.status_code == 404
    assert "serving" not in response.json()
