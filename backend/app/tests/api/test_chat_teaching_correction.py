"""Step 3 — a teaching turn on ``/chat`` becomes an expert fiche, not a query.

Production trace (Andritz session ``ab4586f9``): right after a refusal the
expert typed "Pour ta connaissance, ... on installe une toile 2310 PW". Both
teaching messages were replanned as fresh RAG queries
(``dense_policy=fast_scoped_dense_auto`` /
``fallback_reason=dense_unscoped_fast_policy``), so the user got the density
banner plus an async Deep Retrieval on unrelated PDFs and no fiche was ever
created. These tests pin the branch that consumes such a turn through the same
proposal path as the "Corriger" button, and the gates that keep it narrow.
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat
from app.api.v1.endpoints import knowledge_capture as kc_endpoint
from app.core.iam.roles import WORKSPACE_REVIEWER
from app.models.expert_capture import KnowledgeUpdateProposal
from app.models.run import Run
from app.models.user import Message, User
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace, WorkspaceMember

TEACHING = (
    "Pour ta connaissance, merci de noter que sur un convoyeur J1, "
    "on installe une toile 2310 PW"
)
QUESTION = "Quelle est la référence de la toile du convoyeur J1 ?"
REFUSAL = "Je ne trouve pas cette information dans les sources disponibles."


class _ExplodingOrchestrator:
    async def process_request(self, _request):
        raise AssertionError("a captured teaching turn must not reach retrieval")


class _CapturingOrchestrator:
    def __init__(self):
        self.last_request = None

    async def process_request(self, request):
        self.last_request = request
        yield {"chunk_type": "text", "content": "context answer", "is_final": False}
        yield {"chunk_type": "text", "content": "", "is_final": True}


def _client(db_session, workspace: Workspace, user: User, orchestrator, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(chat.router, prefix="/chat")
    app.dependency_overrides[chat.get_current_workspace] = lambda: workspace
    app.dependency_overrides[chat.get_current_user] = lambda: user
    app.dependency_overrides[chat.get_db] = lambda: db_session
    monkeypatch.setattr(chat, "get_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(chat, "schedule_eval", lambda _run_id: None)
    return TestClient(app)


def _allow_chat_correction(monkeypatch, *, permitted: bool = True, enabled: bool = True) -> None:
    """Stand in for the two production gates (IAM rule + workspace flag)."""

    def _enforce(*_args, **_kwargs):
        if not permitted:
            raise HTTPException(status_code=403, detail="denied")
        return None

    monkeypatch.setattr(kc_endpoint, "enforce_permission", _enforce)
    monkeypatch.setattr(
        kc_endpoint,
        "_resolve_chat_source_policy",
        lambda _db, _ws: {
            "expert_fiche_correction_enabled": enabled,
            # Review ON keeps this suite focused on the chat branch; the
            # auto-publish variant is covered by test_expert_review_disable.
            "expert_review_required": True,
        },
    )


def _seed_answered_session(db_session, *, slug: str) -> tuple[Workspace, User, ChatSession]:
    """A workspace whose chat session already holds a question + an answer."""
    workspace = Workspace(id=f"ws-{slug}", name=slug, slug=slug)
    user = User(
        id=f"user-{slug}",
        username=f"pascal-{slug}",
        email=f"pascal-{slug}@andritz.test",
        role="admin",
        is_active=True,
    )
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="member",
        role_template=WORKSPACE_REVIEWER,
    )
    session = ChatSession(
        id=f"sess-{slug}",
        user_id=user.id,
        workspace_id=workspace.id,
        status="active",
    )
    db_session.add_all([workspace, user, membership, session])
    db_session.add_all(
        [
            Message(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role="user",
                content=QUESTION,
                meta_data={},
            ),
            Message(
                id="msg-refusal",
                session_id=session.id,
                role="assistant",
                content=REFUSAL,
                meta_data={"sources": [{"title": "AVA200 SPL"}]},
            ),
        ]
    )
    db_session.commit()
    return workspace, user, session


def _proposals(db_session, workspace: Workspace) -> list[KnowledgeUpdateProposal]:
    return (
        db_session.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.workspace_id == workspace.id)
        .all()
    )


def test_chat_stream_teaching_creates_fiche_without_retrieval(db_session, monkeypatch):
    workspace, user, session = _seed_answered_session(db_session, slug="teach-stream")
    _allow_chat_correction(monkeypatch)

    response = _client(db_session, workspace, user, _ExplodingOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": TEACHING, "session_id": session.id},
    )

    assert response.status_code == 200
    body = response.text
    assert "J'ai bien pris en compte votre correction" in body
    assert '"expert_correction"' in body
    # The turn never reaches retrieval: no density banner, no auto Deep Search.
    assert '"chunk_type": "retrieval"' not in body
    assert '"phase": "deep_queued"' not in body
    assert "data: [DONE]" in body

    proposal = _proposals(db_session, workspace)[0]
    recommended = proposal.proposal["recommended_ingestion"]
    assert proposal.status == "pending_review"
    assert recommended["metadata"]["origin"] == "chat_correction"
    # The fiche pairs the refused question with the fact the expert dictated.
    assert recommended["metadata"]["question"] == QUESTION
    assert "2310 PW" in recommended["content"]

    messages = (
        db_session.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.timestamp.asc())
        .all()
    )
    # The teaching turn stays in the thread, ahead of its acknowledgement.
    assert messages[-2].role == "user"
    assert messages[-2].content == TEACHING
    assert messages[-2].meta_data["expert_teaching"] is True
    assert messages[-2].meta_data["salient_entities"]["positions"] == ["J1"]
    ack = messages[-1]
    assert ack.role == "assistant"
    assert ack.meta_data["kind"] == "expert_correction_ack"
    assert ack.meta_data["proposal_id"] == proposal.id
    assert ack.meta_data["source_message_id"] == "msg-refusal"
    assert ack.meta_data["trigger"] == "chat_teaching"
    assert ack.meta_data["salient_entities"]["positions"] == ["J1"]

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "expert_teaching_correction"
    assert run.output_ref["expert_correction"]["proposal_id"] == proposal.id


def test_chat_completion_teaching_returns_acknowledgement(db_session, monkeypatch):
    workspace, user, session = _seed_answered_session(db_session, slug="teach-completion")
    _allow_chat_correction(monkeypatch)

    response = _client(db_session, workspace, user, _ExplodingOrchestrator(), monkeypatch).post(
        "/chat/completion",
        json={"query": TEACHING, "session_id": session.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["sources"] == []
    assert "J'ai bien pris en compte votre correction" in payload["content"]
    assert payload["expert_correction"]["status"] == "pending_review"
    assert payload["expert_correction"]["proposal_id"] == _proposals(db_session, workspace)[0].id


def test_chat_stream_question_keeps_the_retrieval_path(db_session, monkeypatch):
    workspace, user, session = _seed_answered_session(db_session, slug="teach-question")
    _allow_chat_correction(monkeypatch)
    orchestrator = _CapturingOrchestrator()

    response = _client(db_session, workspace, user, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={"query": QUESTION, "session_id": session.id},
    )

    assert response.status_code == 200
    assert "context answer" in response.text
    assert orchestrator.last_request["query"] == QUESTION
    assert _proposals(db_session, workspace) == []


def test_chat_stream_teaching_without_permission_stays_plain_chat(db_session, monkeypatch):
    workspace, user, session = _seed_answered_session(db_session, slug="teach-denied")
    _allow_chat_correction(monkeypatch, permitted=False)
    orchestrator = _CapturingOrchestrator()

    response = _client(db_session, workspace, user, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={"query": TEACHING, "session_id": session.id},
    )

    assert response.status_code == 200
    assert "context answer" in response.text
    assert _proposals(db_session, workspace) == []
    # The message is answered normally, never dropped.
    assert orchestrator.last_request["query"] == TEACHING
    assert (
        db_session.query(Message)
        .filter(Message.session_id == session.id, Message.content == TEACHING)
        .count()
        == 1
    )


def test_chat_stream_teaching_without_previous_answer_stays_plain_chat(db_session, monkeypatch):
    workspace = Workspace(id="ws-teach-first", name="first", slug="teach-first")
    user = User(id="user-teach-first", username="first", email="first@andritz.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    _allow_chat_correction(monkeypatch)
    orchestrator = _CapturingOrchestrator()

    response = _client(db_session, workspace, user, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={"query": TEACHING},
    )

    assert response.status_code == 200
    assert "context answer" in response.text
    # Nothing to correct in a brand-new session -> no fiche.
    assert _proposals(db_session, workspace) == []


def test_chat_stream_teaching_with_feature_flag_off_stays_plain_chat(db_session, monkeypatch):
    workspace, user, session = _seed_answered_session(db_session, slug="teach-flag-off")
    _allow_chat_correction(monkeypatch, enabled=False)
    orchestrator = _CapturingOrchestrator()

    response = _client(db_session, workspace, user, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={"query": TEACHING, "session_id": session.id},
    )

    assert response.status_code == 200
    assert "context answer" in response.text
    assert _proposals(db_session, workspace) == []


def test_source_anchor_texts_prefer_payload_filename_over_display_title():
    texts = chat._source_anchor_texts(
        {
            "title": "Spare Parts List_BBA120.pdf",
            "filename": "Manual_BBA120__Spare part list__Spare Parts List_BBA120.pdf",
            "metadata": {
                "document_filename": "Manual_BBA120__Spare part list__Spare Parts List_BBA120.pdf",
            },
        }
    )

    assert texts[0] == "Manual_BBA120__Spare part list__Spare Parts List_BBA120.pdf"
    assert "Spare Parts List_BBA120.pdf" in texts


def test_turn_salient_entities_persists_a_station_only_follow_up():
    entities = chat._turn_salient_entities("et sur le J1 ?")

    assert entities == {"references": [], "positions": ["J1"], "documents": []}


def test_turn_salient_entities_carries_positions_and_documents_forward():
    entities = chat._turn_salient_entities(
        "et maintenant ?",
        previous={
            "references": ["ACJ100"],
            "positions": ["J1"],
            "documents": ["A__ACJ100__V.1.Conveyor J1.pdf"],
        },
    )

    assert entities["references"] == ["ACJ100"]
    assert entities["positions"] == ["J1"]
    assert entities["documents"] == ["A__ACJ100__V.1.Conveyor J1.pdf"]


def test_latest_salient_entities_reads_a_teaching_user_turn():
    class _Msg:
        def __init__(self, role, meta):
            self.role = role
            self.meta_data = meta

    entities = chat._latest_salient_entities(
        [
            _Msg("assistant", {"sources": []}),
            _Msg(
                "user",
                {"expert_teaching": True, "salient_entities": {"positions": ["J1"]}},
            ),
        ]
    )

    assert entities == {"positions": ["J1"]}
