"""Volet 2 — inline chat correction -> pending_review proposal.

Focused unit tests for the expert-fiche chat-correction capture path:
proposal status + provenance metadata, the voice audit event, the
``chat_correct`` RBAC rule, the per-workspace feature-flag gate (403) and the
deterministic teaching detector the ``/chat`` surface routes through it.
"""
from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import knowledge_capture as kc_endpoint
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_REVIEWER
from app.models.expert_capture import ExpertCaptureSession, KnowledgeUpdateProposal
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.engine import AuthorizationEngine
from app.services.knowledge_capture import (
    create_chat_correction_proposal,
    is_teaching_utterance,
    list_capture_events,
)


class _FakeStore:
    """In-memory object store stand-in (key + write_bytes) for audio retention."""

    def __init__(self) -> None:
        self.writes: dict[str, bytes] = {}

    def key(self, *parts: object) -> str:
        return "/".join(str(p).strip("/") for p in parts if str(p).strip("/"))

    def write_bytes(self, key: str, content: bytes) -> str:
        self.writes[key] = content
        return key


@pytest.mark.parametrize(
    "text",
    [
        # The two production messages of the Andritz session (typo included).
        "Pour un J1 on instale toujours une toile 2310PW",
        "Pour ta connaissance, merci de noter que sur un convoyeur J1, "
        "on installe une toile 2310 PW",
        "À retenir : sur un convoyeur J1 la toile est une 2310PW",
        "Sache que la toile du convoyeur J1 est une 2310PW",
        "Pour info, la distance C1-J1 est de 2 mètres sur cette ligne",
    ],
)
def test_teaching_utterance_detects_expert_assertions(text):
    assert is_teaching_utterance(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # Plain questions must keep the retrieval path.
        "quelle est la référence de la toile du convoyeur j1",
        "Compare les consignes J2S et Scorpio",
        # Interrogative forms win over a teaching lead-in.
        "Pour ta connaissance, quelle est la toile du J1 ?",
        "Est-ce qu'on installe toujours une toile 2310PW sur un J1",
        "Peux-tu noter que la toile du J1 est une 2310PW ?",
        # A keyword or a bare assertion is not enough on its own.
        "On installe la toile 2310PW demain sur la ligne",
        "La toile du convoyeur J1 est une 2310PW",
        "pour info",
        "merci",
        "",
    ],
)
def test_teaching_utterance_ignores_questions_and_plain_messages(text):
    assert is_teaching_utterance(text) is False


def _seed_workspace_user(db_session, *, ws_id: str, slug: str, user_id: str) -> tuple[Workspace, User]:
    workspace = Workspace(id=ws_id, name=ws_id, slug=slug)
    user = User(id=user_id, username="expert", email="expert@demo.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def test_chat_correction_proposal_is_pending_review_with_provenance(db_session):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-meta", slug="andritz", user_id="user-cc-meta"
    )

    proposal, session = create_chat_correction_proposal(
        db_session,
        workspace=workspace,
        user=user,
        query="Quelle est la pression nominale de la pompe X ?",
        assistant_answer="Environ 5 bar.",
        correction_text="La pression nominale est 7 bar, pas 5 bar.",
        sources=[{"title": "Manuel pompe X", "url": "https://docs/x"}],
        source_policy={"expert_fiche_collection": "andritz-validated-fiches"},
    )

    assert proposal.status == "pending_review"
    assert session.status == "chat_correction"
    assert session.objective == "Quelle est la pression nominale de la pompe X ?"

    recommended = proposal.proposal["recommended_ingestion"]
    meta = recommended["metadata"]
    assert meta["source_type"] == "expert_fiche"
    assert meta["origin"] == "chat_correction"
    assert meta["input_modality"] == "text"
    assert meta["expert_name"] == "expert@demo.test"
    assert meta["question"] == "Quelle est la pression nominale de la pompe X ?"
    assert meta["sources"] == [{"title": "Manuel pompe X", "url": "https://docs/x"}]
    # Default publication destination = resolved expert-fiche collection.
    assert meta["publication_destination"] == "andritz-validated-fiches"
    assert proposal.proposal["publication"]["destination"] == "andritz-validated-fiches"
    assert "7 bar" in recommended["content"]
    # Text path leaves no audio_ref behind.
    assert "audio_ref" not in meta


def test_chat_correction_voice_records_voice_event(db_session):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-voice", slug="andritz", user_id="user-cc-voice"
    )
    audio_ref = "workspaces/ws-cc-voice/expert-fiche-captures/andritz-expert-fiche/abc123/audio.webm"

    proposal, session = create_chat_correction_proposal(
        db_session,
        workspace=workspace,
        user=user,
        query="Question posée à l'oral ?",
        assistant_answer="Réponse initiale.",
        correction_text="Texte relu et corrigé par l'expert.",
        transcript_raw="texte brut issu de la transcription",
        audio_ref=audio_ref,
        input_modality="voice",
    )

    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=session.id)
    voice_events = [event for event in events if event.source == "voice"]
    assert len(voice_events) == 1
    event = voice_events[0]
    assert event.text_raw == "texte brut issu de la transcription"
    assert event.text_amended == "Texte relu et corrigé par l'expert."
    assert event.audio_ref == audio_ref

    meta = proposal.proposal["recommended_ingestion"]["metadata"]
    assert meta["input_modality"] == "voice"
    assert meta["audio_ref"] == audio_ref


def test_chat_correct_rule_allows_reviewer_denies_contributor(db_session):
    reviewer_ws = Workspace(id="ws-cc-rev", name="rev", slug="cc-rev")
    reviewer = User(id="user-cc-rev", username="rev", email="rev@demo.test")
    reviewer_membership = WorkspaceMember(
        user_id=reviewer.id,
        workspace_id=reviewer_ws.id,
        role="member",
        role_template=WORKSPACE_REVIEWER,
    )
    contributor_ws = Workspace(id="ws-cc-con", name="con", slug="cc-con")
    contributor = User(id="user-cc-con", username="con", email="con@demo.test")
    contributor_membership = WorkspaceMember(
        user_id=contributor.id,
        workspace_id=contributor_ws.id,
        role="member",
        role_template=WORKSPACE_CONTRIBUTOR,
    )
    db_session.add_all(
        [reviewer_ws, reviewer, reviewer_membership, contributor_ws, contributor, contributor_membership]
    )
    db_session.commit()

    engine = AuthorizationEngine()
    allowed = engine.evaluate(
        db_session,
        user=reviewer,
        workspace=reviewer_ws,
        membership=reviewer_membership,
        resource_kind="knowledge_proposal",
        action="chat_correct",
        resource_attrs={"capability": "expert_knowledge_capture"},
        audit_denials=False,
    )
    denied = engine.evaluate(
        db_session,
        user=contributor,
        workspace=contributor_ws,
        membership=contributor_membership,
        resource_kind="knowledge_proposal",
        action="chat_correct",
        resource_attrs={"capability": "expert_knowledge_capture"},
        audit_denials=False,
    )

    assert allowed.allowed is True
    assert denied.allowed is False
    # No chat_correct rule grants the contributor role -> deny by default.
    assert denied.reason == "IAM_DENY_BY_DEFAULT"


def _client(db_session, workspace: Workspace, user: User, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(kc_endpoint.router, prefix="/api/v1/knowledge-capture")
    app.dependency_overrides[kc_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[kc_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[kc_endpoint.get_db] = lambda: db_session
    monkeypatch.setattr(kc_endpoint, "enforce_permission", lambda *args, **kwargs: None)
    return TestClient(app)


def test_chat_correction_endpoint_403_when_feature_flag_off(db_session, monkeypatch):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-off", slug="andritz", user_id="user-cc-off"
    )
    monkeypatch.setattr(kc_endpoint, "_resolve_chat_source_policy", lambda db, ws: {})

    client = _client(db_session, workspace, user, monkeypatch)
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={"query": "q", "answer": "a", "correction": "c"},
    )

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


def test_chat_correction_endpoint_rejects_blank_correction_without_side_effects(db_session, monkeypatch):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-blank", slug="andritz", user_id="user-cc-blank"
    )
    monkeypatch.setattr(
        kc_endpoint,
        "_resolve_chat_source_policy",
        lambda db, ws: {"expert_fiche_correction_enabled": True},
    )
    fake_store = _FakeStore()
    monkeypatch.setattr(kc_endpoint, "get_object_store", lambda: fake_store)

    client = _client(db_session, workspace, user, monkeypatch)
    audio_b64 = base64.b64encode(b"fake-webm-audio").decode("ascii")
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={
            "query": "Quelle pression ?",
            "answer": "5 bar",
            "correction": " \n\t ",
            "input_modality": "voice",
            "transcript_raw": "silence transcrit",
            "audio_base64": audio_b64,
            "audio_content_type": "audio/webm",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Chat correction cannot be empty."
    assert fake_store.writes == {}
    assert (
        db_session.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.workspace_id == workspace.id)
        .count()
        == 0
    )
    assert (
        db_session.query(ExpertCaptureSession)
        .filter(ExpertCaptureSession.workspace_id == workspace.id)
        .count()
        == 0
    )


def test_chat_correction_endpoint_happy_path_stores_audio(db_session, monkeypatch):
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-cc-on", slug="andritz", user_id="user-cc-on"
    )
    monkeypatch.setattr(
        kc_endpoint,
        "_resolve_chat_source_policy",
        lambda db, ws: {"expert_fiche_correction_enabled": True},
    )
    fake_store = _FakeStore()
    monkeypatch.setattr(kc_endpoint, "get_object_store", lambda: fake_store)

    client = _client(db_session, workspace, user, monkeypatch)
    audio_b64 = base64.b64encode(b"fake-webm-audio").decode("ascii")
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={
            "query": "Quelle pression ?",
            "answer": "5 bar",
            "correction": "7 bar en réalité.",
            "input_modality": "voice",
            "transcript_raw": "sept bar en realite",
            "audio_base64": audio_b64,
            "audio_content_type": "audio/webm",
            "sources": [{"title": "Manuel"}],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending_review"
    assert data["collection"] == "andritz-expert-fiche"
    assert data["review_queue_url"].endswith("status=pending_review")
    assert data["proposal_id"]

    # Audio bytes were persisted under the resolved expert-fiche collection.
    assert len(fake_store.writes) == 1
    stored_key = next(iter(fake_store.writes))
    assert "andritz-expert-fiche" in stored_key
    assert stored_key.endswith("audio.webm")

    proposal = (
        db_session.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == data["proposal_id"])
        .first()
    )
    meta = proposal.proposal["recommended_ingestion"]["metadata"]
    assert meta["input_modality"] == "voice"
    assert meta["audio_ref"] == stored_key
