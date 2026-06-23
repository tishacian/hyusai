from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import knowledge_capture
from app.api.v1.endpoints.knowledge_capture import ProposalPublishRequest
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
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


def _client_with_permissions(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_capture.router, prefix="/api/v1/knowledge-capture")
    app.dependency_overrides[knowledge_capture.get_current_workspace] = lambda: workspace
    app.dependency_overrides[knowledge_capture.get_current_user] = lambda: user
    app.dependency_overrides[knowledge_capture.get_db] = lambda: db_session
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


def test_reviewer_can_create_and_start_capture_when_iam_enforced(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-kc-api-reviewer-create",
        name="KC API Reviewer Create",
        slug="kc-api-reviewer-create",
        settings={"features": {"iam_enforced": True}},
    )
    reviewer = User(
        id="user-kc-api-reviewer-create",
        username="reviewer-create",
        email="reviewer-create@example.test",
    )
    db_session.add_all(
        [
            workspace,
            reviewer,
            WorkspaceMember(
                user_id=reviewer.id,
                workspace_id=workspace.id,
                role="member",
                role_template="workspace_reviewer",
            ),
        ]
    )
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    async def _noop_warm_cache(*args, **kwargs):  # noqa: ARG001
        return {"status": "skipped", "reason": "unit-test"}

    def _noop_background_warm_cache(*args, **kwargs):  # noqa: ARG001
        return None

    monkeypatch.setattr(knowledge_capture, "warm_capture_context_cache", _noop_warm_cache)
    monkeypatch.setattr(knowledge_capture, "_run_warm_capture_context_cache", _noop_background_warm_cache)

    client = _client_with_permissions(db_session, workspace, reviewer)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Capture reviewer",
            "objective": "Capturer une observation terrain en mode reviewer.",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["created_by_user_id"] == reviewer.id
    assert body["plan"]["schema_version"] == "free_conversation_v1"

    started = client.post(f"/api/v1/knowledge-capture/sessions/{body['id']}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "active"


def test_free_conversation_api_conversation_step_records_turn_and_closure(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-free-conv-step", name="KC API Free Conv Step", slug="kc-api-free-conv-step")
    user = User(id="user-kc-api-free-conv-step", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    async def _noop_warm_cache(*args, **kwargs):  # noqa: ARG001
        return {"status": "skipped", "reason": "unit-test"}

    monkeypatch.setattr(knowledge_capture, "warm_capture_context_cache", _noop_warm_cache)
    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Capture libre conversation",
            "objective": "Capturer une décision terrain sans plan imposé.",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
        },
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    started = client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")
    assert started.status_code == 200

    answer = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "free-conv-api-1",
            "text": "Sur la ligne pilote, on réduit la vitesse du convoyeur après nettoyage humide.",
        },
    )

    assert answer.status_code == 200
    answer_body = answer.json()
    assert answer_body["intent"] == "answer_ready"
    assert answer_body["action_taken"] == "turn_appended"
    assert answer_body["turn"]["turn_kind"] == "answer"
    assert "vitesse du convoyeur" in answer_body["turn"]["text"]

    events = client.get(
        f"/api/v1/knowledge-capture/sessions/{session_id}/events",
        params={"event_type": "conversation_intent_detected"},
    )
    assert events.status_code == 200
    intent_events = events.json()["events"]
    assert len(intent_events) == 1
    assert intent_events[0]["source"] == "conversation_only"
    assert intent_events[0]["metadata"]["intent"] == "answer_ready"
    assert intent_events[0]["metadata"]["client_turn_id"] == "free-conv-api-1"

    closure = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "free-conv-api-2",
            "text": "C'est terminé pour aujourd'hui.",
        },
    )

    assert closure.status_code == 200
    closure_body = closure.json()
    assert closure_body["intent"] == "session_complete"
    assert closure_body["action_taken"] == "closure_sheet_generated"
    assert closure_body["requires_confirmation"] is True
    assert closure_body["confirmation_target"] == "session_closure"
    assert closure_body["closure_sheet"]["markdown"]
    assert closure_body["session"]["metrics"]["session_end_pending"] is True


def test_capture_document_view_api_records_active_view(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-doc-view", name="KC API Doc View", slug="kc-api-doc-view")
    user = User(id="user-kc-api-doc-view", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Capture libre documentée",
            "objective": "Capturer une observation située dans un support.",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
        },
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")

    viewed = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/documents/view",
        json={
            "document_id": "manual-pdf",
            "collection": "capture-session-docs",
            "filename": "manuel.pdf",
            "title": "Manuel ligne BBA",
            "page": 7,
            "association_mode": "active_view",
        },
    )

    assert viewed.status_code == 200
    body = viewed.json()
    assert body["active_view"]["kind"] == "capture_document_ref"
    assert body["active_view"]["document_id"] == "manual-pdf"
    assert body["active_view"]["page"] == 7
    assert body["event"]["event_type"] == "capture_document_viewed"
    assert body["event"]["source"] == "capture_document"
    assert body["event"]["metadata"]["filename"] == "manuel.pdf"

    listed = client.get(f"/api/v1/knowledge-capture/sessions/{session_id}/documents")
    assert listed.status_code == 200
    listed_body = listed.json()
    assert listed_body["collection"] == "capture-session-docs"
    assert listed_body["active_view"]["document_id"] == "manual-pdf"
    assert listed_body["active_view"]["page"] == 7


def test_capture_text_turn_api_preserves_document_refs(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-doc-turn", name="KC API Doc Turn", slug="kc-api-doc-turn")
    user = User(id="user-kc-api-doc-turn", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Capture texte documentée",
            "objective": "Capturer une règle terrain référencée à une slide.",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
        },
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")
    active_ref = {
        "document_id": "deck-spl",
        "collection": "capture-session-docs",
        "filename": "support.pptx",
        "title": "Support SPL",
        "slide": 3,
        "association_mode": "active_view",
    }

    turn = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/turns",
        json={
            "speaker": "expert",
            "input_modality": "text",
            "client_turn_id": "doc-turn-1",
            "text": "Sur cette slide, la séquence impose de purger trente secondes avant redémarrage.",
            "document_refs": [active_ref],
            "visual_context": active_ref,
        },
    )

    assert turn.status_code == 200
    turn_body = turn.json()
    assert turn_body["turn"]["input_modality"] == "text"
    assert len(turn_body["turn"]["document_refs"]) == 1
    assert turn_body["turn"]["document_refs"][0]["document_id"] == "deck-spl"
    assert turn_body["turn"]["document_refs"][0]["slide"] == 3

    events = client.get(
        f"/api/v1/knowledge-capture/sessions/{session_id}/events",
        params={"event_type": "expert_turn_finalized"},
    )
    assert events.status_code == 200
    finalized = events.json()["events"][0]
    assert finalized["source"] == "expert_text"
    assert finalized["metadata"]["document_refs"][0]["filename"] == "support.pptx"
    assert finalized["metadata"]["document_refs"][0]["slide"] == 3


def test_capture_document_upload_api_queues_document_without_worker_side_effects(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.knowledge_collection import KnowledgeCollectionSource, WorkerJob
    from app.services.knowledge_collections import get_collection_or_404, original_key
    from app.services.object_store import get_object_store

    monkeypatch.setattr(settings, "document_ingest_async_enabled", True)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    workspace = Workspace(id="ws-kc-api-doc-upload", name="KC API Doc Upload", slug="kc-api-doc-upload")
    user = User(id="user-kc-api-doc-upload", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    dispatched: list[tuple[str, str, dict]] = []

    def _fake_dispatch(_db, job, *, allow_inline_fallback=True):  # noqa: ANN001, ARG001
        dispatched.append((job.id, job.kind, dict(job.result or {})))
        return f"task-{job.id}"

    monkeypatch.setattr(knowledge_capture, "dispatch_worker_job", _fake_dispatch)
    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Capture avec upload document",
            "objective": "Capturer une observation avec support uploadé.",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
        },
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")

    uploaded = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/documents",
        files=[
            ("files", ("manuel.pdf", b"%PDF-1.4\ncapture document\n", "application/pdf")),
            ("files", ("photo.png", b"\x89PNG\r\n\x1a\ncapture image\n", "image/png")),
        ],
    )

    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body["collection"] == f"capture-session-{session_id}"
    documents_by_name = {doc["filename"]: doc for doc in body["documents"]}
    assert set(documents_by_name) == {"manuel.pdf", "photo.png"}
    assert {doc["status"] for doc in documents_by_name.values()} == {"queued"}
    assert {doc["chunks_processed"] for doc in documents_by_name.values()} == {0}
    job_id = documents_by_name["manuel.pdf"]["job_id"]
    assert job_id
    assert documents_by_name["photo.png"]["job_id"] == job_id
    assert dispatched == [(job_id, "document_ingest_index", {
        "ingest_options": {
            "mode": "incremental",
            "document_names": ["manuel.pdf", "photo.png"],
            "capture_session_id": session_id,
        }
    })]

    collection = get_collection_or_404(db_session, workspace_id=workspace.id, collection_ref=body["collection"])
    assert get_object_store().exists(original_key(collection, "manuel.pdf"))
    assert get_object_store().exists(original_key(collection, "photo.png"))
    sources = (
        db_session.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.workspace_id == workspace.id,
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.filename.in_(["manuel.pdf", "photo.png"]),
        )
        .all()
    )
    assert {source.filename for source in sources} == {"manuel.pdf", "photo.png"}
    assert {source.status for source in sources} == {"queued"}
    assert {source.origin for source in sources} == {"capture_session_upload"}
    assert {source.source_metadata["capture_session_id"] for source in sources} == {session_id}
    job = db_session.query(WorkerJob).filter(WorkerJob.id == job_id).one()
    assert job.kind == "document_ingest_index"
    assert job.result["ingest_options"]["document_names"] == ["manuel.pdf", "photo.png"]

    events = client.get(
        f"/api/v1/knowledge-capture/sessions/{session_id}/events",
        params={"event_type": "capture_document_uploaded"},
    )
    assert events.status_code == 200
    upload_events = events.json()["events"]
    assert len(upload_events) == 2
    assert {event["source"] for event in upload_events} == {"capture_document"}
    assert {event["metadata"]["filename"] for event in upload_events} == {"manuel.pdf", "photo.png"}
    assert {event["metadata"]["job_id"] for event in upload_events} == {job_id}


def test_free_conversation_proposal_endpoint_returns_structured_topic(db_session, monkeypatch):
    import app.services.knowledge_capture as kc_service

    workspace = Workspace(id="ws-kc-api-free-proposal", name="KC API Free Proposal", slug="kc-api-free-proposal")
    user = User(id="user-kc-api-free-proposal", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    finalize_calls: list[str] = []

    async def _fast_finalize(db, *, workspace_id, session_id, created_by_user_id=None, **_kwargs):
        finalize_calls.append(session_id)
        return kc_service.create_update_proposal(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            created_by_user_id=created_by_user_id,
        )

    monkeypatch.setattr(knowledge_capture, "finalize_capture", _fast_finalize)
    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Capture libre rapport",
            "objective": "Capturer un retour terrain sans plan.",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
        },
    )
    session_id = created.json()["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")
    client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/turns",
        json={"speaker": "expert", "text": "La pompe doit être purgée deux minutes avant redémarrage terrain."},
    )

    response = client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/proposal")

    assert response.status_code == 200
    assert finalize_calls == [session_id]
    topics = response.json()["proposal"]["plan_structure"]["topics"]
    assert topics[0]["topic_id"] == "session"
    assert topics[0]["title"] == "Synthèse de la capture"


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


def test_free_conversation_closure_finish_returns_structured_proposal(db_session, monkeypatch):
    import app.services.knowledge_capture as kc_service

    workspace = Workspace(id="ws-kc-api-free-closure", name="KC API Free Closure", slug="kc-api-free-closure")
    user = User(id="user-kc-api-free-closure", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    finalize_calls: list[str] = []

    async def _fast_finalize(db, *, workspace_id, session_id, created_by_user_id=None, **_kwargs):
        finalize_calls.append(session_id)
        return kc_service.create_update_proposal(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            created_by_user_id=created_by_user_id,
        )

    monkeypatch.setattr(knowledge_capture, "finalize_capture", _fast_finalize)
    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Capture libre clôture",
            "objective": "Capturer un retour terrain sans plan.",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
        },
    )
    session_id = created.json()["id"]
    client.post(f"/api/v1/knowledge-capture/sessions/{session_id}/start")
    client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/turns",
        json={"speaker": "expert", "text": "Le convoyeur doit rester à vitesse réduite après nettoyage humide."},
    )

    response = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/closure",
        json={"action": "finish"},
    )

    assert response.status_code == 200
    body = response.json()
    assert finalize_calls == [session_id]
    assert body["action"] == "finish"
    assert body["session"]["status"] == "completed"
    topics = body["proposal"]["proposal"]["plan_structure"]["topics"]
    assert topics[0]["topic_id"] == "session"
    assert topics[0]["title"] == "Synthèse de la capture"


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


def test_admin_lists_all_members_capture_sessions(db_session, monkeypatch):
    """A workspace admin browses every member's capture sessions read-only, and
    each row carries the author label + turn count the unified admin view needs."""
    from app.models.expert_capture import ExpertCaptureSession
    from app.models.workspace import WorkspaceMember

    workspace = Workspace(id="ws-kc-admin-list", name="KC Admin List", slug="kc-admin-list")
    author_a = User(id="user-kc-author-a", username="aa", email="aa@example.test")
    author_b = User(id="user-kc-author-b", username="bb", email="bb@example.test")
    admin = User(id="user-kc-admin", username="adm", email="adm@example.test")
    db_session.add_all([workspace, author_a, author_b, admin])
    db_session.add(
        WorkspaceMember(
            user_id=admin.id,
            workspace_id=workspace.id,
            role="admin",
            role_template="workspace_admin",
        )
    )
    db_session.add_all(
        [
            ExpertCaptureSession(
                id="cap-a",
                workspace_id=workspace.id,
                created_by_user_id=author_a.id,
                title="Session A",
                objective="Objectif A",
                status="completed",
                transcript=[
                    {"id": "t1", "speaker": "expert", "text": "Réponse 1"},
                    {"id": "t2", "speaker": "expert", "text": "Réponse 2"},
                ],
            ),
            ExpertCaptureSession(
                id="cap-b",
                workspace_id=workspace.id,
                created_by_user_id=author_b.id,
                title="Correction B",
                objective="Objectif B",
                status="chat_correction",
            ),
        ]
    )
    db_session.commit()

    client = _client(db_session, workspace, admin, monkeypatch)
    listed = client.get("/api/v1/knowledge-capture/sessions")
    assert listed.status_code == 200
    by_id = {row["id"]: row for row in listed.json()["sessions"]}
    assert {"cap-a", "cap-b"} <= set(by_id)
    assert by_id["cap-a"]["created_by_label"] == "aa@example.test"
    assert by_id["cap-a"]["turn_count"] == 2
    assert by_id["cap-b"]["created_by_label"] == "bb@example.test"
    assert by_id["cap-b"]["turn_count"] == 0


def test_contributor_only_sees_own_capture_sessions(db_session, monkeypatch):
    """A contributor (default IAM flag) only sees their own capture sessions,
    confirming the admin path above genuinely widens visibility."""
    from app.models.expert_capture import ExpertCaptureSession
    from app.models.workspace import WorkspaceMember

    workspace = Workspace(id="ws-kc-contrib-list", name="KC Contrib List", slug="kc-contrib-list")
    author_a = User(id="user-kc-contrib-a", username="ca", email="ca@example.test")
    author_b = User(id="user-kc-contrib-b", username="cb", email="cb@example.test")
    db_session.add_all([workspace, author_a, author_b])
    db_session.add(
        WorkspaceMember(
            user_id=author_a.id,
            workspace_id=workspace.id,
            role="member",
            role_template="workspace_contributor",
        )
    )
    db_session.add_all(
        [
            ExpertCaptureSession(
                id="cap-mine",
                workspace_id=workspace.id,
                created_by_user_id=author_a.id,
                title="Ma session",
                objective="Objectif",
                status="completed",
            ),
            ExpertCaptureSession(
                id="cap-foreign",
                workspace_id=workspace.id,
                created_by_user_id=author_b.id,
                title="Session voisine",
                objective="Objectif",
                status="completed",
            ),
        ]
    )
    db_session.commit()

    client = _client(db_session, workspace, author_a, monkeypatch)
    listed = client.get("/api/v1/knowledge-capture/sessions")
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()["sessions"]}
    assert "cap-mine" in ids
    assert "cap-foreign" not in ids


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


def test_conversation_step_accept_denied_keeps_proposal_pending(db_session, monkeypatch):
    workspace = Workspace(id="ws-kc-api-conv-deny", name="KC API Conv Deny", slug="kc-api-conv-deny")
    user = User(id="user-kc-api-conv-deny", username="operator", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    def _deny_ingestion(*args, **kwargs):
        if kwargs.get("resource_kind") == "knowledge_proposal" and kwargs.get("action") == "trigger_ingestion":
            raise HTTPException(status_code=403, detail="WORKSPACE_PERMISSION_DENIED")

    app = FastAPI()
    app.include_router(knowledge_capture.router, prefix="/api/v1/knowledge-capture")
    app.dependency_overrides[knowledge_capture.get_current_workspace] = lambda: workspace
    app.dependency_overrides[knowledge_capture.get_current_user] = lambda: user
    app.dependency_overrides[knowledge_capture.get_db] = lambda: db_session
    monkeypatch.setattr(knowledge_capture, "enforce_permission", _deny_ingestion)
    monkeypatch.setattr(knowledge_capture, "_allow_immature_ai_plan", lambda *args, **kwargs: True)
    client = TestClient(app)

    created = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": "Conversation API denied",
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
            "client_turn_id": "api-conv-deny-1",
            "question_id": question_id,
            "text": "Quand la ligne vibre après maintenance, je vérifie le rapport terrain avant recalage.",
        },
    )
    proposal = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "api-conv-deny-2",
            "question_id": question_id,
            "text": "Crée la proposition.",
        },
    ).json()
    client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "api-conv-deny-3",
            "question_id": question_id,
            "last_proposal_id": proposal["proposal"]["id"],
            "text": "Oui je confirme.",
        },
    )

    denied = client.post(
        f"/api/v1/knowledge-capture/sessions/{session_id}/conversation-step",
        json={
            "client_turn_id": "api-conv-deny-4",
            "question_id": question_id,
            "last_proposal_id": proposal["proposal"]["id"],
            "text": "Oui valide.",
        },
    )

    assert denied.status_code == 403
    reloaded = client.get(
        "/api/v1/knowledge-capture/proposals",
        params={"session_id": session_id},
    )
    assert reloaded.status_code == 200
    assert reloaded.json()["proposals"][0]["status"] == "pending_review"
