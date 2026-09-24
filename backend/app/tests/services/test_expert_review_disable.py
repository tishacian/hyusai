"""Disable expert-review workflow — auto-publish, acknowledgement, capture.

Covers the per-workspace ``source_policy.expert_review_required`` gate:

* chat correction with review OFF -> ``published`` + ``source_type=expert_fiche``;
* review ON (default) -> ``pending_review`` (non-regression);
* the conversational acknowledgement is persisted as a
  ``Message(role="assistant", kind="expert_correction_ack")`` when a chat
  ``session_id`` is present, and skipped otherwise;
* the thematic synthesis has a deterministic fallback when no LLM is configured;
* system capture with review OFF is auto-validated but not published without
  an explicit publication action.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import knowledge_capture as kc_endpoint
from app.models.context import Context
from app.models.expert_capture import KnowledgeUpdateProposal
from app.models.user import Message, Session as ChatSession, User
from app.models.workspace import Workspace
from app.services.knowledge_capture import (
    _fallback_chat_correction_theme,
    append_turn,
    approve_capture_plan,
    build_chat_correction_acknowledgement,
    create_capture_plan,
    is_expert_review_required,
    summarize_chat_correction_theme,
)
from app.services.skills_registry.seed import seed_skills_and_capabilities


class _FakeDocumentService:
    """Captures the ingest metadata so provenance can be asserted."""

    captured: dict = {}

    def __init__(self, **_: object) -> None:
        pass

    async def ingest_document(self, *_: object, document_metadata: dict | None = None, **__: object) -> dict:
        _FakeDocumentService.captured = dict(document_metadata or {})
        return {"document_id": "doc-autopublish", "chunks_processed": 2, "status": "success"}

    async def get_document_count(self) -> int:
        # Publication records the collection's vector total in its source ledger.
        return 2


def _seed_workspace_user(db_session, *, ws_id: str, slug: str, user_id: str, settings=None):
    workspace = Workspace(id=ws_id, name=ws_id, slug=slug, settings=settings or {})
    user = User(id=user_id, username="expert", email="expert@demo.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def _client(db_session, workspace: Workspace, user: User, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(kc_endpoint.router, prefix="/api/v1/knowledge-capture")
    app.dependency_overrides[kc_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[kc_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[kc_endpoint.get_db] = lambda: db_session
    monkeypatch.setattr(kc_endpoint, "enforce_permission", lambda *args, **kwargs: None)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Flag resolver
# ---------------------------------------------------------------------------


def test_is_expert_review_required_honours_override_then_global():
    from app.core.config import settings as app_config

    # Per-workspace override wins, both truthy and falsey.
    assert is_expert_review_required({"expert_review_required": False}) is False
    assert is_expert_review_required({"expert_review_required": True}) is True
    # Absent -> global default (True).
    assert is_expert_review_required({}) is app_config.kc_expert_review_required
    assert is_expert_review_required(None) is app_config.kc_expert_review_required


# ---------------------------------------------------------------------------
# Chat correction — review OFF auto-publishes
# ---------------------------------------------------------------------------


def test_chat_correction_review_off_auto_publishes(db_session, monkeypatch):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-autopub", slug="andritz", user_id="user-cc-autopub"
    )
    monkeypatch.setattr(
        kc_endpoint,
        "_resolve_chat_source_policy",
        lambda db, ws: {
            "expert_fiche_correction_enabled": True,
            "expert_review_required": False,
            "expert_fiche_collection": "andritz-validated-fiches",
        },
    )
    monkeypatch.setattr("app.services.rag.document_service.DocumentService", _FakeDocumentService)

    client = _client(db_session, workspace, user, monkeypatch)
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={
            "query": "Quelle est la pression nominale de la pompe KD724 ?",
            "answer": "Environ 5 bar.",
            "correction": "La pression nominale est 7 bar, pas 5 bar.",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "published"
    assert data["document_id"] == "doc-autopublish"
    assert data["acknowledgement"]
    assert "pris en compte" in data["acknowledgement"]
    assert data["summary"]
    # No chat session_id -> no acknowledgement Message persisted.
    assert data["ack_message_id"] is None

    proposal = (
        db_session.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == data["proposal_id"])
        .first()
    )
    assert proposal.status == "published"
    # The provenance marker carried through to ingestion.
    assert _FakeDocumentService.captured["source_type"] == "expert_fiche"
    assert _FakeDocumentService.captured["origin"] == "chat_correction"


def test_chat_correction_review_on_stays_pending_review(db_session, monkeypatch):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-review-on", slug="andritz", user_id="user-cc-review-on"
    )
    # expert_review_required absent -> global default True -> non-regression.
    monkeypatch.setattr(
        kc_endpoint,
        "_resolve_chat_source_policy",
        lambda db, ws: {"expert_fiche_correction_enabled": True},
    )

    client = _client(db_session, workspace, user, monkeypatch)
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={"query": "q", "answer": "a", "correction": "c bien précise."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending_review"
    assert data["document_id"] is None
    proposal = (
        db_session.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == data["proposal_id"])
        .first()
    )
    assert proposal.status == "pending_review"


# ---------------------------------------------------------------------------
# Conversational acknowledgement persistence
# ---------------------------------------------------------------------------


def test_chat_correction_acknowledgement_persisted_with_session_id(db_session, monkeypatch):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-ack", slug="andritz", user_id="user-cc-ack"
    )
    chat_session = ChatSession(id="chat-sess-ack", workspace_id=workspace.id, user_id=user.id)
    db_session.add(chat_session)
    db_session.commit()
    monkeypatch.setattr(
        kc_endpoint,
        "_resolve_chat_source_policy",
        lambda db, ws: {"expert_fiche_correction_enabled": True},
    )

    client = _client(db_session, workspace, user, monkeypatch)
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={
            "query": "Quelle pression ?",
            "answer": "5 bar",
            "correction": "7 bar en réalité.",
            "session_id": "chat-sess-ack",
            "message_id": "msg-42",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ack_message_id"]
    assert data["acknowledgement"]

    message = (
        db_session.query(Message)
        .filter(Message.id == data["ack_message_id"])
        .first()
    )
    assert message is not None
    assert message.role == "assistant"
    assert message.session_id == "chat-sess-ack"
    assert message.content == data["acknowledgement"]
    assert message.meta_data["kind"] == "expert_correction_ack"
    assert message.meta_data["proposal_id"] == data["proposal_id"]
    assert message.meta_data["status"] == data["status"]
    assert message.meta_data["source_message_id"] == "msg-42"


def test_chat_correction_no_message_persisted_without_session_id(db_session, monkeypatch):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-nosess", slug="andritz", user_id="user-cc-nosess"
    )
    monkeypatch.setattr(
        kc_endpoint,
        "_resolve_chat_source_policy",
        lambda db, ws: {"expert_fiche_correction_enabled": True},
    )

    client = _client(db_session, workspace, user, monkeypatch)
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={"query": "q", "answer": "a", "correction": "c détaillée."},
    )

    assert response.status_code == 200
    assert response.json()["ack_message_id"] is None
    assert db_session.query(Message).count() == 0


# ---------------------------------------------------------------------------
# Thematic synthesis — deterministic fallback
# ---------------------------------------------------------------------------


async def test_summarize_chat_correction_theme_falls_back_without_llm():
    # No OPENAI_API_KEY in the test env -> deterministic fallback, no network.
    theme = await summarize_chat_correction_theme(
        "Quelle est la pression nominale de la pompe KD724 ?",
        "La pression nominale est 7 bar, pas 5 bar.",
    )
    assert theme == _fallback_chat_correction_theme(
        "Quelle est la pression nominale de la pompe KD724 ?",
        "La pression nominale est 7 bar, pas 5 bar.",
    )
    assert theme
    assert "pression" in theme


def test_fallback_theme_truncates_long_corrections():
    long_correction = " ".join(f"mot{i}" for i in range(40))
    theme = _fallback_chat_correction_theme("question", long_correction)
    assert theme.endswith("…")
    assert len(theme.split()) <= 13  # 12 words + the trailing ellipsis token


def test_acknowledgement_wording_published_vs_pending():
    published = build_chat_correction_acknowledgement("la pression nominale", published=True)
    pending = build_chat_correction_acknowledgement("la pression nominale", published=False)
    assert published == "J'ai bien pris en compte votre correction : la pression nominale."
    assert "envoyée en revue" in pending


# ---------------------------------------------------------------------------
# System capture — review OFF auto-validates but does not publish
# ---------------------------------------------------------------------------


def _seed_capture_session(db_session, workspace, *, context):
    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture revue désactivée",
        objective="Publier automatiquement une capture test.",
        expert_profile="Responsable maintenance",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        plan_mode="ai_plan",
        allow_ai_plan=True,
    )
    session = approve_capture_plan(
        db_session, workspace_id=workspace.id, session_id=session.id, actor_user_id="test-user"
    )
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text="La cadence nominale de la ligne est de 120 mètres par minute.",
    )
    return session


def test_capture_proposal_review_off_auto_accepts_without_publishing(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-cap-autopub",
        name="Capture Autopublish",
        slug="capture-autopub",
        settings={"source_policy": {"expert_review_required": False}},
    )
    context = Context(
        id="ctx-cap-autopub",
        workspace_id=workspace.id,
        name="Capture",
        environment_state={"collection": "capture-autopub-knowledge"},
    )
    db_session.add_all([workspace, context])
    user = User(id="user-cap-autopub", username="expert", email="cap@demo.test")
    db_session.add(user)
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    _FakeDocumentService.captured = {}
    monkeypatch.setattr("app.services.rag.document_service.DocumentService", _FakeDocumentService)

    session = _seed_capture_session(db_session, workspace, context=context)

    client = _client(db_session, workspace, user, monkeypatch)
    response = client.post(f"/api/v1/knowledge-capture/sessions/{session.id}/proposal")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert _FakeDocumentService.captured == {}
    proposal = (
        db_session.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == data["id"])
        .first()
    )
    assert proposal is not None
    assert proposal.status == "accepted"
    assert not ((proposal.proposal or {}).get("publication") or {}).get("published_at")


def test_capture_proposal_review_on_stays_pending(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-cap-review-on",
        name="Capture Review On",
        slug="capture-review-on",
        settings={},
    )
    context = Context(
        id="ctx-cap-review-on",
        workspace_id=workspace.id,
        name="Capture",
        environment_state={"collection": "capture-review-on-knowledge"},
    )
    db_session.add_all([workspace, context])
    user = User(id="user-cap-review-on", username="expert", email="cap2@demo.test")
    db_session.add(user)
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    session = _seed_capture_session(db_session, workspace, context=context)

    client = _client(db_session, workspace, user, monkeypatch)
    response = client.post(f"/api/v1/knowledge-capture/sessions/{session.id}/proposal")

    assert response.status_code == 200
    assert response.json()["status"] == "pending_review"
