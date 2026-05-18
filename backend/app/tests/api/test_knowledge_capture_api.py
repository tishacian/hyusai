from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import knowledge_capture
from app.models.user import User
from app.models.workspace import Workspace
from app.services.skills_registry.seed import seed_skills_and_capabilities


def _client(db_session, workspace: Workspace, user: User, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_capture.router, prefix="/api/v1/knowledge-capture")
    app.dependency_overrides[knowledge_capture.get_current_workspace] = lambda: workspace
    app.dependency_overrides[knowledge_capture.get_current_user] = lambda: user
    app.dependency_overrides[knowledge_capture.get_db] = lambda: db_session
    monkeypatch.setattr(knowledge_capture, "enforce_permission", lambda *args, **kwargs: None)
    return TestClient(app)


def test_topic_plan_requires_patchable_approval_before_start(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api", name="KC API", slug="kc-api")
    user = User(id="user-kc-api", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Topic plan API",
            "objective": "Capture expert troubleshooting decisions for production lines.",
            "expert_profile": "Senior field engineer",
            "duration_minutes": 20,
            "knowledge_refs": [],
        },
    )
    assert created.status_code == 200
    session = created.json()
    assert session["plan"]["schema_version"] == "topic_plan_v1"

    blocked = client.post(f"/api/v1/knowledge-capture/sessions/{session['id']}/start")
    assert blocked.status_code == 400
    assert "approved" in blocked.json()["detail"]

    plan = session["plan"]
    plan["topics"][0]["title"] = "Validated field decisions"
    plan["topics"][0]["subtopics"][0]["questions"][0]["question"] = (
        "Quelle décision terrain doit être documentée pour la prochaine revue ?"
    )
    amended = client.patch(
        f"/api/v1/knowledge-capture/sessions/{session['id']}/plan",
        json={"plan": plan},
    )
    assert amended.status_code == 200
    amended_body = amended.json()
    assert amended_body["plan"]["review"]["status"] == "edited"
    assert amended_body["plan"]["questions"][0]["path_label"].startswith("Validated field decisions")

    approved = client.post(f"/api/v1/knowledge-capture/sessions/{session['id']}/plan/approve")
    assert approved.status_code == 200
    assert approved.json()["plan"]["review"]["status"] == "approved"

    started = client.post(f"/api/v1/knowledge-capture/sessions/{session['id']}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "active"


def test_topic_plan_patch_rejects_empty_question_set(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-invalid", name="KC API Invalid", slug="kc-api-invalid")
    user = User(id="user-kc-api-invalid", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "objective": "Capture expert troubleshooting decisions for production lines.",
            "duration_minutes": 20,
            "knowledge_refs": [],
        },
    )
    plan = created.json()["plan"]
    plan["topics"][0]["subtopics"][0]["questions"] = []

    response = client.patch(
        f"/api/v1/knowledge-capture/sessions/{created.json()['id']}/plan",
        json={"plan": plan},
    )

    assert response.status_code == 400
    assert "question" in response.json()["detail"]
