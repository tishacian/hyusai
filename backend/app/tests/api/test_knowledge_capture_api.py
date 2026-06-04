from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import knowledge_capture
from app.api.v1.endpoints.knowledge_capture import ProposalPublishRequest
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
    monkeypatch.setattr(knowledge_capture, "_allow_immature_ai_plan", lambda *args, **kwargs: True)
    return TestClient(app)


def test_publish_request_declares_unresolved_questions_flag():
    default_body = ProposalPublishRequest()
    explicit_body = ProposalPublishRequest(include_unresolved_questions=False)

    assert default_body.include_unresolved_questions is True
    assert explicit_body.include_unresolved_questions is False


def test_topic_plan_starts_without_approval_gate(db_session, monkeypatch):
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
            "plan_mode": "ai_plan",
        },
    )
    assert created.status_code == 200
    session = created.json()
    assert session["plan"]["schema_version"] == "topic_plan_v1"

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
            "plan_mode": "ai_plan",
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


def test_free_conversation_plan_via_api(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-free", name="KC API Free", slug="kc-api-free")
    user = User(id="user-kc-api-free", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Capture libre",
            "objective": "",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
            "capture_domain": "technical",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["plan"]["schema_version"] == "free_conversation_v1"
    assert body["metrics"]["unlimited_duration"] is True
    assert body["metrics"]["capture_domain"] == "technical"


def test_plan_creation_keeps_warm_cache_failures_non_blocking(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-warm-fail", name="KC API Warm Fail", slug="kc-api-warm-fail")
    user = User(id="user-kc-api-warm-fail", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    async def _fail_warm_cache(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("qdrant temporarily unavailable")

    monkeypatch.setattr(knowledge_capture, "warm_capture_context_cache", _fail_warm_cache)
    client = _client(db_session, workspace, user, monkeypatch)

    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Warm cache fallback",
            "objective": "Capture expert decisions despite warmup failure.",
            "duration_minutes": 20,
            "plan_mode": "free_conversation",
        },
    )

    assert created.status_code == 200
    assert created.json()["id"]


def test_provided_plan_via_api(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-provided", name="KC API Provided", slug="kc-api-provided")
    user = User(id="user-kc-api-provided", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Plan fourni API",
            "objective": "Capture expert.",
            "duration_minutes": 20,
            "plan_mode": "provided_plan",
            "provided_plan_text": "# Thème API\n## Sous-thème 1",
            "plan_source_kind": "pasted_text",
            "plan_source_filename": "atelier.txt",
            "plan_source_replaces_existing_plan": True,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["plan"]["mode"] == "provided_plan"
    assert body["plan"]["topics"]
    assert body["plan"]["dialogue"]["ready_to_finalize"] is True
    assert body["plan"]["plan_source"]["kind"] == "pasted_text"
    assert body["plan"]["plan_source"]["filename"] == "atelier.txt"
    assert body["plan"]["plan_source"]["replaces_existing_plan"] is True
    assert body["plan"]["plan_source"]["extracted_outline"] == [
        {"title": "Thème API", "subtopics": ["Sous-thème 1"]}
    ]


def test_closure_sheet_and_extend_endpoints(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-closure", name="KC API Closure", slug="kc-api-closure")
    user = User(id="user-kc-api-closure", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Closure API",
            "objective": "Capture expert decisions.",
            "duration_minutes": 20,
            "plan_mode": "free_conversation",
        },
    )
    session_id = created.json()["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")
    client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/turns",
        json={"speaker": "expert", "text": "Décision validée pour la ligne pilote."},
    )

    sheet = client.get(f"/api/v1/knowledge-capture/sessions/{session_id}/closure-sheet")
    assert sheet.status_code == 200
    body = sheet.json()
    assert "Fiche fin de session" in body["markdown"]
    assert body["captured_facts"]

    extended = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/extend",
        json={"action": "extend", "extension_minutes": 15},
    )
    assert extended.status_code == 200
    assert extended.json()["metrics"]["duration_extension_minutes"] == 15

    finished = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/closure",
        json={"action": "finish"},
    )
    assert finished.status_code == 200
    finish_body = finished.json()
    assert finish_body["action"] == "finish"
    assert finish_body["closure_sheet"]["markdown"]
    assert finish_body["session"]["status"] == "completed"


def test_conversation_step_accept_checks_proposal_review_permissions(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-conv-perm", name="KC API Conv Perm", slug="kc-api-conv-perm")
    user = User(id="user-kc-api-conv-perm", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    permission_calls = []

    def _record_permission(*args, **kwargs):
        permission_calls.append((kwargs.get("resource_kind"), kwargs.get("action")))

    app = FastAPI()
    app.include_router(knowledge_capture.router, prefix="/api/v1/knowledge-capture")
    app.dependency_overrides[knowledge_capture.get_current_workspace] = lambda: workspace
    app.dependency_overrides[knowledge_capture.get_current_user] = lambda: user
    app.dependency_overrides[knowledge_capture.get_db] = lambda: db_session
    monkeypatch.setattr(knowledge_capture, "enforce_permission", _record_permission)
    monkeypatch.setattr(knowledge_capture, "_allow_immature_ai_plan", lambda *args, **kwargs: True)
    client = TestClient(app)

    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Conversation API",
            "objective": "Capture expert troubleshooting decisions for production lines.",
            "expert_profile": "Senior field engineer",
            "duration_minutes": 20,
            "knowledge_refs": [],
            "plan_mode": "ai_plan",
        },
    ).json()
    session_id = created["id"]
    question_id = created["plan"]["questions"][0]["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")
    client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "api-conv-1",
            "question_id": question_id,
            "text": "Quand la ligne vibre après maintenance, je vérifie le rapport terrain et le CRM avant recalage.",
        },
    )
    proposal = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "api-conv-2",
            "question_id": question_id,
            "text": "Crée la proposition.",
        },
    ).json()
    client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "api-conv-3",
            "question_id": question_id,
            "last_proposal_id": proposal["proposal"]["id"],
            "text": "Oui je confirme.",
        },
    )
    permission_calls.clear()

    accepted = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "api-conv-4",
            "question_id": question_id,
            "last_proposal_id": proposal["proposal"]["id"],
            "text": "Oui valide.",
        },
    )

    assert accepted.status_code == 200
    assert ("knowledge_proposal", "review_decide") in permission_calls
    assert ("knowledge_proposal", "trigger_ingestion") in permission_calls
