from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.endpoints import ml_models, workspace_jobs
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.tests.services.test_ml_shadow import pair  # noqa: F401


@pytest.fixture
def api(db_session, pair):
    user = User(id=str(uuid4()), username="shadow-" + uuid4().hex, email=uuid4().hex + "@example.test", role="user")
    db_session.add(user)
    db_session.flush()
    member = WorkspaceMember(workspace_id=pair[0].id, user_id=user.id, role="member", role_template="workspace_contributor")
    db_session.add(member)
    db_session.commit()
    app = FastAPI()
    app.include_router(ml_models.router, prefix="/models")
    app.include_router(workspace_jobs.router, prefix="/jobs")
    for module in (ml_models, workspace_jobs):
        app.dependency_overrides[module.get_current_workspace] = lambda: pair[0]
        app.dependency_overrides[module.get_current_user] = lambda: user
        app.dependency_overrides[module.get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client, user, member


def test_config_is_explicit_preserves_train_params_and_visible_without_predictions(api, pair, db_session):
    client, _, _ = api
    model = pair[1]
    model.params_json = {"knobs": {"max_iter": 20}, "mlops": {"monitoring": {"enabled": True}}}
    db_session.commit()
    result = client.get(f"/models/{model.id}/monitoring").json()["monitoring"]
    assert result["window"]["predictions"] == 0
    assert result["shadow"]["config"]["enabled"] is False and result["shadow"]["can_configure"] is True
    response = client.post(f"/models/{model.id}/shadow", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["shadow"]["config"] == {"enabled": True, "sample_percent": 10, "timeout_s": 15}
    db_session.refresh(model)
    assert model.params_json["knobs"] == {"max_iter": 20}
    assert model.params_json["mlops"]["monitoring"] == {"enabled": True}


@pytest.mark.parametrize("role", ["workspace_viewer", "workspace_reviewer", "viewer"])
def test_read_only_roles_cannot_configure(api, pair, db_session, role):
    client, _, member = api
    member.role_template, member.role = (role, "member") if role.startswith("workspace_") else (None, role)
    db_session.commit()
    response = client.post(f"/models/{pair[1].id}/shadow", json={"enabled": True})
    assert response.status_code == 403
    assert client.get(f"/models/{pair[1].id}/monitoring").json()["monitoring"]["shadow"]["can_configure"] is False


@pytest.mark.parametrize("body", [{"enabled": "true"}, {"enabled": True, "sample_percent": 0},
    {"enabled": True, "sample_percent": 101}, {"enabled": True, "timeout_s": 61}, {"enabled": True, "timeout_s": True},
    {"enabled": True, "challenger_id": "forged"}])
def test_limits_and_extra_authority_fields_are_rejected(api, pair, body):
    assert api[0].post(f"/models/{pair[1].id}/shadow", json=body).status_code == 422


def test_cross_workspace_and_non_tabular_model_are_refused(api, pair, db_session):
    client, _, _ = api
    other = Workspace(id=str(uuid4()), slug=uuid4().hex, name="Private")
    db_session.add(other)
    db_session.flush()
    pair[2].workspace_id = other.id
    db_session.commit()
    assert client.post(f"/models/{pair[2].id}/shadow", json={"enabled": True}).status_code == 404
    pair[1].family, pair[1].task = "forecasting", "forecasting"
    db_session.commit()
    assert client.post(f"/models/{pair[1].id}/shadow", json={"enabled": True}).status_code == 409


def test_shadow_job_is_not_forgeable_or_mutable_via_generic_api(api, pair, db_session):
    client, user, _ = api
    assert client.post("/jobs/", json={"kind": "ml_shadow", "title": "Forged"}).status_code == 403
    job = WorkspaceJob(workspace_id=pair[0].id, kind="ml_shadow", title="Real", created_by_user_id=user.id, status="queued")
    db_session.add(job)
    db_session.commit()
    assert client.post(f"/jobs/{job.id}/transition", json={"status": "completed", "result": {"predictions": []}}).status_code == 403

