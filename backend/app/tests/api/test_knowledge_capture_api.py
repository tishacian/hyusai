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


def test_archive_and_unarchive_session(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-archive", name="KC API Archive", slug="kc-api-archive")
    user = User(id="user-kc-api-archive", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Archive me",
            "objective": "Capture expert decisions.",
            "duration_minutes": 20,
            "plan_mode": "free_conversation",
        },
    )
    session_id = created.json()["id"]

    archived = client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/archive")
    assert archived.status_code == 200
    body = archived.json()
    assert body["archived"] is True
    assert body["metrics"]["archived"] is True

    # Hidden from the default listing, visible with include_archived.
    default_list = client.get("/api/v1/knowledge-capture/sessions").json()["sessions"]
    assert all(row["id"] != session_id for row in default_list)
    full_list = client.get("/api/v1/knowledge-capture/sessions", params={"include_archived": "true"}).json()["sessions"]
    assert any(row["id"] == session_id for row in full_list)

    restored = client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/unarchive")
    assert restored.status_code == 200
    assert restored.json()["archived"] is False
    default_list = client.get("/api/v1/knowledge-capture/sessions").json()["sessions"]
    assert any(row["id"] == session_id for row in default_list)


def test_delete_session(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-delete", name="KC API Delete", slug="kc-api-delete")
    user = User(id="user-kc-api-delete", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Delete me",
            "objective": "Capture expert decisions.",
            "duration_minutes": 20,
            "plan_mode": "free_conversation",
        },
    )
    session_id = created.json()["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")
    client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/turns",
        json={"speaker": "expert", "text": "Une décision importante à supprimer."},
    )

    deleted = client.delete(f"/api/v1/knowledge-capture/sessions/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    missing = client.get(f"/api/v1/knowledge-capture/sessions/{session_id}")
    assert missing.status_code == 404
    listing = client.get("/api/v1/knowledge-capture/sessions").json()["sessions"]
    assert all(row["id"] != session_id for row in listing)


def test_list_proposals_filters_by_session_id(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-prop-filter", name="KC API Prop Filter", slug="kc-api-prop-filter")
    user = User(id="user-kc-api-prop-filter", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Proposal filter",
            "objective": "Capture expert decisions.",
            "duration_minutes": 20,
            "plan_mode": "free_conversation",
        },
    )
    session_id = created.json()["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")
    client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/turns",
        json={"speaker": "expert", "text": "Procédure validée sur la ligne pilote en cas de vibration."},
    )
    proposal = client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/proposal")
    assert proposal.status_code == 200

    scoped = client.get("/api/v1/knowledge-capture/proposals", params={"session_id": session_id}).json()["proposals"]
    assert scoped
    assert all(row["session_id"] == session_id for row in scoped)

    none = client.get("/api/v1/knowledge-capture/proposals", params={"session_id": "missing-session"}).json()["proposals"]
    assert none == []


def test_list_published_fiches_returns_workspace_outputs(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-fiches", name="KC API Fiches", slug="kc-api-fiches")
    author = User(id="user-kc-api-fiches-author", username="author", email="author@example.test")
    reviewer = User(id="user-kc-api-fiches-reviewer", username="reviewer", email="reviewer@example.test")
    db_session.add_all([workspace, author, reviewer])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    from app.models.expert_capture import ExpertCaptureSession, KnowledgeUpdateProposal

    session = ExpertCaptureSession(
        id="session-published-fiche",
        workspace_id=workspace.id,
        title="Published session",
        objective="Capture objective",
        created_by_user_id=author.id,
        status="completed",
    )
    proposal = KnowledgeUpdateProposal(
        id="proposal-published-fiche",
        workspace_id=workspace.id,
        session_id=session.id,
        status="published",
        created_by_user_id=author.id,
        reviewer_user_id=reviewer.id,
        proposal={
            "title": "Published session",
            "recommended_ingestion": {
                "title": "Published session",
                "content": "Procédure validée sur la ligne pilote.",
                "metadata": {
                    "source": "expert_capture_session",
                    "capture_session_id": session.id,
                    "proposal_id": "proposal-published-fiche",
                    "publication_category": "technical",
                    "publication_destination": "capture-knowledge",
                    "collection_slug": "capture-knowledge",
                },
            },
            "open_questions": [
                {"follow_up": "Qui valide ?", "status": "open"},
                {"follow_up": "Déjà traité", "status": "answered"},
            ],
            "publication": {
                "final_title": "Fiche maintenance ligne pilote",
                "category": "technical",
                "destination": "capture-knowledge",
                "collection_slug": "capture-knowledge",
                "document_id": "doc-published-fiche",
                "chunks_processed": 4,
                "published_at": "2026-06-01T10:00:00",
            },
        },
    )
    db_session.add_all([session, proposal])
    db_session.commit()

    client = _client(db_session, workspace, reviewer, monkeypatch)
    response = client.get("/api/v1/knowledge-capture/fiches")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["fiches"]) == 1
    fiche = payload["fiches"][0]
    assert fiche["proposal_id"] == "proposal-published-fiche"
    assert fiche["title"] == "Fiche maintenance ligne pilote"
    assert fiche["category"] == "technical"
    assert fiche["destination"] == "capture-knowledge"
    assert fiche["document_id"] == "doc-published-fiche"
    assert fiche["chunks_processed"] == 4
    assert fiche["open_questions_count"] == 1
    assert fiche["author"]["id"] == author.id
    assert fiche["published_by"]["id"] == reviewer.id
    assert fiche["session_owned_by_current_user"] is False

    filtered = client.get(
        "/api/v1/knowledge-capture/fiches",
        params={"q": "maintenance", "category": "technical"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1

    missing = client.get("/api/v1/knowledge-capture/fiches", params={"q": "introuvable"})
    assert missing.status_code == 200
    assert missing.json()["total"] == 0


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
