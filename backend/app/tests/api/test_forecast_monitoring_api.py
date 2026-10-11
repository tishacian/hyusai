"""Association is administrator-owned; reading observed quality stays accessible."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_models
from app.models.workspace import Workspace
from app.tests.services.test_forecast_monitoring import observed, actuals  # noqa: F401
from app.tests.services.test_ml_training import enabled, store  # noqa: F401

@pytest.fixture()
def api(db_session, observed):
    app = FastAPI()
    app.include_router(ml_models.router, prefix="/models")
    app.dependency_overrides[ml_models.get_current_workspace] = lambda: observed.workspace
    app.dependency_overrides[ml_models.get_current_user] = lambda: observed.owner
    app.dependency_overrides[ml_models.get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client

def test_read_associate_and_refresh_contract(api, db_session, observed):
    path = f"/models/{observed.model.id}/monitoring"
    initial = api.get(path)
    assert initial.status_code == 200
    assert initial.json()["monitoring"]["forecast_actuals"]["status"] == "unconfigured"
    dataset = actuals(db_session, observed)
    response = api.post(path + "/actuals", json={"dataset_id": dataset.id, "follow_latest": True})
    assert response.status_code == 200, response.text
    report = response.json()["monitoring"]["forecast_actuals"]
    assert report["can_configure"] and report["dataset"]["id"] == dataset.id
    assert report["dataset"]["follow_latest"] and report["overall"]["count"] == 0
    assert api.get(path).json()["monitoring"]["forecast_actuals"]["dataset"]["sha256"]

@pytest.mark.parametrize("role", ["workspace_contributor", "workspace_viewer", "workspace_reviewer", "viewer"])
def test_only_admins_can_bind_actuals(api, db_session, observed, role):
    observed.member.role_template = role
    db_session.commit()
    dataset = actuals(db_session, observed)
    path = f"/models/{observed.model.id}/monitoring"
    assert not api.get(path).json()["monitoring"]["forecast_actuals"]["can_configure"]
    assert api.post(path + "/actuals", json={"dataset_id": dataset.id}).status_code == 403

def test_cross_workspace_dataset_and_model_are_invisible(api, db_session, observed):
    dataset = actuals(db_session, observed)
    other = Workspace(id=str(uuid4()), slug=uuid4().hex, name="Other")
    db_session.add(other)
    dataset.workspace_id = other.id
    db_session.commit()
    path = f"/models/{observed.model.id}/monitoring/actuals"
    assert api.post(path, json={"dataset_id": dataset.id}).status_code == 404
    observed.model.workspace_id = other.id
    db_session.commit()
    assert api.post(path, json={"dataset_id": dataset.id}).status_code == 404

@pytest.mark.parametrize("body", [{"follow_latest": True}, {"dataset_id": "12345678", "follow_latest": "true"},
                                   {"dataset_id": "12345678", "sha256": "untrusted"}])
def test_association_rejects_coercion_and_caller_provenance(api, observed, body):
    assert api.post(f"/models/{observed.model.id}/monitoring/actuals", json=body).status_code == 422

def test_tabular_models_keep_existing_report_and_refuse_association(api, db_session, observed):
    observed.model.family = "tabular"
    observed.model.task = "regression"
    db_session.commit()
    dataset = actuals(db_session, observed)
    path = f"/models/{observed.model.id}/monitoring"
    assert api.get(path).status_code == 200
    assert "forecast_actuals" not in api.get(path).json()["monitoring"]
    assert api.post(path + "/actuals", json={"dataset_id": dataset.id}).status_code == 409
