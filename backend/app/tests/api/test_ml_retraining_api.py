"""Admin scheduling, version/workspace isolation and protected proposal authority."""
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.endpoints import ml_models, workspace_jobs
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.tests.services.test_ml_retraining import case  # noqa: F401
from app.tests.services.test_ml_training import enabled, store  # noqa: F401


@pytest.fixture()
def api(db_session, case):
    app=FastAPI()
    for module, prefix in ((ml_models,"/models"),(workspace_jobs,"/jobs")):
        app.include_router(module.router,prefix=prefix)
        app.dependency_overrides[module.get_current_workspace]=lambda:case.workspace
        app.dependency_overrides[module.get_current_user]=lambda:case.owner
        app.dependency_overrides[module.get_db]=lambda:db_session
    with TestClient(app) as client:
        yield client


def test_admin_updates_schedule_and_reads_contract(api,case,db_session):
    response=api.post(f"/models/{case.model.id}/monitoring/policy",json={"enabled":True,"interval_minutes":1440,"propose_retraining":True})
    assert response.status_code==200,response.text
    scheduled=response.json()["monitoring"]["scheduled"]
    assert scheduled["can_configure"] and scheduled["policy"]["interval_minutes"]==1440
    assert scheduled["policy"]["schedule_id"]==case.schedule.id
    assert scheduled["proposals"]==[]


@pytest.mark.parametrize("role",["workspace_contributor","workspace_viewer","workspace_reviewer","viewer"])
def test_non_admins_read_but_cannot_schedule(api,case,db_session,role):
    case.member.role_template=role
    db_session.commit()
    assert not api.get(f"/models/{case.model.id}/monitoring").json()["monitoring"]["scheduled"]["can_configure"]
    assert api.post(f"/models/{case.model.id}/monitoring/policy",json={"enabled":False}).status_code==403


@pytest.mark.parametrize("body",[{"enabled":"true"},{"enabled":True,"interval_minutes":1},
    {"enabled":True,"interval_minutes":True},{"enabled":True,"system_id":"fake"}])
def test_policy_has_bounded_intervals_and_no_caller_owned_authority(api,case,body):
    assert api.post(f"/models/{case.model.id}/monitoring/policy",json=body).status_code==422


def test_other_workspaces_are_invisible(api,case,db_session):
    other=Workspace(id=str(uuid4()),slug=uuid4().hex,name="Elsewhere")
    db_session.add(other)
    case.model.workspace_id=other.id
    db_session.commit()
    assert api.post(f"/models/{case.model.id}/monitoring/policy",json={"enabled":False}).status_code==404
    assert api.get(f"/models/{case.model.id}/monitoring").status_code==404


@pytest.mark.parametrize("kind",["ml_monitoring","ml_retraining"])
def test_generic_jobs_cannot_forge_or_rewrite_monitoring_authority(api,case,db_session,kind):
    assert api.post("/jobs/",json={"kind":kind,"title":"Forged"}).status_code==403
    job=WorkspaceJob(workspace_id=case.workspace.id,kind=kind,title="Real",status="queued",created_by_user_id=case.owner.id)
    db_session.add(job)
    db_session.commit()
    assert api.post(f"/jobs/{job.id}/transition",json={"status":"completed","result":{"decision_id":"forged"}}).status_code==403


def test_admin_can_stop_a_schedule_when_its_model_is_no_longer_ready(api,case,db_session):
    case.model.status="failed"
    db_session.commit()
    response=api.get(f"/models/{case.model.id}/monitoring")
    assert response.json()["monitoring"]["scheduled"]["supported"] is True
    assert api.post(f"/models/{case.model.id}/monitoring/policy",json={"enabled":True}).status_code==409
    assert api.post(f"/models/{case.model.id}/monitoring/policy",json={"enabled":False}).status_code==200
    db_session.refresh(case.schedule)
    assert not case.schedule.enabled
