"""Labeling checkpoints cannot be forged through the generic job ledger API."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.endpoints import workspace_jobs
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.workspace_jobs import create_workspace_job


@pytest.fixture
def labeling_api(db_session):
    workspace = Workspace(id="label-workspace", slug="label-workspace", name="Label", mode="demo")
    user = User(id="label-user", username="label-user", email="label@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    app = FastAPI()
    app.include_router(workspace_jobs.router, prefix="/jobs")
    app.dependency_overrides[workspace_jobs.get_current_workspace] = lambda: workspace
    app.dependency_overrides[workspace_jobs.get_current_user] = lambda: user
    app.dependency_overrides[workspace_jobs.get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client, workspace, user


def test_generic_api_cannot_create_labeling_job(labeling_api, db_session):
    client, _, _ = labeling_api
    response = client.post("/jobs/", json={
        "kind": "llm_label_dataset", "title": "Forged checkpoint", "input_ref": {"source_id": "secret"},
    })
    assert response.status_code == 403
    assert db_session.query(WorkspaceJob).count() == 0


@pytest.mark.parametrize("status", ["running", "succeeded", "failed", "cancelled"])
def test_generic_api_cannot_mutate_labeling_checkpoint(labeling_api, db_session, status):
    client, workspace, user = labeling_api
    job = create_workspace_job(db_session, workspace, user, kind="llm_label_dataset", title="Labels", status="running")
    job.result = {"cursor": 10, "tokens": 1000}
    db_session.commit()
    response = client.post(f"/jobs/{job.id}/transition", json={
        "status": status, "progress": 100, "result": {"cursor": 100, "tokens": 0},
    })
    assert response.status_code == 403
    db_session.refresh(job)
    assert job.status == "running" and job.result == {"cursor": 10, "tokens": 1000}
    assert client.get(f"/jobs/{job.id}").status_code == 200


def test_labeling_job_read_stays_workspace_scoped(labeling_api, db_session):
    client, _, user = labeling_api
    other = Workspace(id="label-other", slug="label-other", name="Other", mode="demo")
    db_session.add(other)
    db_session.flush()
    job = create_workspace_job(db_session, other, user, kind="llm_label_dataset", title="Private")
    db_session.commit()
    assert client.get(f"/jobs/{job.id}").status_code == 404
    assert client.post(f"/jobs/{job.id}/transition", json={"status": "succeeded"}).status_code == 404
