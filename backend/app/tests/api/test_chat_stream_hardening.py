from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat
from app.core.config import settings
from app.models.context import Context
from app.models.run import Run
from app.models.workspace import Workspace
from app.services.workspace_maps import ensure_workspace_map_seed


def _client(db_session, workspace: Workspace, orchestrator, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(chat.router, prefix="/chat")
    app.dependency_overrides[chat.get_current_workspace] = lambda: workspace
    app.dependency_overrides[chat.get_current_user] = lambda: None
    app.dependency_overrides[chat.get_db] = lambda: db_session
    monkeypatch.setattr(chat, "get_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(chat, "schedule_eval", lambda _run_id: None)
    return TestClient(app)


class HappyOrchestrator:
    async def process_request(self, _request):
        yield {
            "chunk_type": "retrieval",
            "phase": "started",
            "content": "",
            "details": {
                "duration_ms": 0,
                "chunks_retrieved": 0,
                "collection": "documents",
                "vector_db": "faiss",
                "pipeline": "hybrid",
                "task_id": None,
            },
            "is_final": False,
        }
        yield {
            "chunk_type": "retrieval",
            "phase": "completed",
            "content": "",
            "details": {
                "duration_ms": 12,
                "chunks_retrieved": 1,
                "collection": "documents",
                "vector_db": "faiss",
                "pipeline": "hybrid",
                "task_id": "task-1",
                "fallback": False,
            },
            "rag_context": {
                "chunks": ["context"],
                "scores": [0.9],
                "metadatas": [{"document_title": "Manual"}],
                "metrics": {"duration_ms": 12, "chunks_retrieved": 1},
            },
            "is_final": False,
        }
        yield {
            "chunk_type": "text",
            "content": "answer",
            "sources": [{"title": "Manual"}],
            "is_final": False,
        }
        yield {"chunk_type": "text", "content": "", "is_final": True}


class SlowOrchestrator:
    async def process_request(self, _request):
        await asyncio.sleep(0.05)
        yield {"chunk_type": "text", "content": "too late", "is_final": True}


class CapturingOrchestrator:
    def __init__(self):
        self.last_request = None

    async def process_request(self, request):
        self.last_request = request
        yield {"chunk_type": "text", "content": "context answer", "is_final": False}
        yield {"chunk_type": "text", "content": "", "is_final": True}


def test_chat_stream_emits_stable_retrieval_eval_and_persists_run(db_session, monkeypatch):
    workspace = Workspace(id="ws-chat", name="Chat", slug="chat")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": "What is in the manual?"},
    )

    assert response.status_code == 200
    body = response.text
    assert '"chunk_type": "retrieval"' in body
    assert '"phase": "started"' in body
    assert '"phase": "completed"' in body
    assert '"chunk_type": "eval_pending"' in body
    assert "data: [DONE]" in body

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.output_ref["response"] == "answer"
    assert run.output_ref["retrieval_worker_task_id"] == "task-1"
    assert run.output_ref["retrieval_metrics"]["chunks_retrieved"] == 1
    assert run.output_ref["rag_context"]["chunks"] == ["context"]


def test_chat_stream_uses_selected_context_collection(db_session, monkeypatch):
    workspace = Workspace(id="ws-context-chat", name="Context Chat", slug="context-chat")
    db_session.add(workspace)
    db_session.add(
        Context(
            id="ctx-context-chat",
            workspace_id=workspace.id,
            name="NON-WOVENS France Excel pilot",
            environment_state={"collection": "andritz-non-wovens-france-excel-pilot"},
            data_refs=["andritz-non-wovens-france-excel-pilot"],
        )
    )
    db_session.commit()
    orchestrator = CapturingOrchestrator()

    response = _client(db_session, workspace, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={"query": "Diametre B ?", "context_id": "ctx-context-chat"},
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert orchestrator.last_request["context_collection"] == "andritz-non-wovens-france-excel-pilot"
    assert orchestrator.last_request["context"]["context_id"] == "ctx-context-chat"
    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.output_ref["context_id"] == "ctx-context-chat"


def test_chat_stream_unknown_context_returns_controlled_error(db_session, monkeypatch):
    workspace = Workspace(id="ws-missing-context", name="Missing Context", slug="missing-context")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": "Anything", "context_id": "ctx-does-not-exist"},
    )

    assert response.status_code == 200
    assert '"code": "CHAT_CONTEXT_NOT_FOUND"' in response.text
    assert "data: [DONE]" in response.text
    assert db_session.query(Run).filter(Run.workspace_id == workspace.id).count() == 0


def test_chat_stream_timeout_returns_controlled_error(db_session, monkeypatch):
    monkeypatch.setattr(settings, "chat_stream_timeout_seconds", 0.01)
    workspace = Workspace(id="ws-timeout", name="Timeout", slug="timeout")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, SlowOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": "Will this timeout?"},
    )

    assert response.status_code == 200
    assert '"code": "CHAT_STREAM_TIMEOUT"' in response.text
    assert "data: [DONE]" in response.text
    assert db_session.query(Run).filter(Run.workspace_id == workspace.id).count() == 0


def test_chat_stream_vigie_map_query_emits_map_command(db_session, monkeypatch):
    workspace = Workspace(id="ws-sentinel-map", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Montre-moi la zone nord sur la carte",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert '"chunk_type": "map_command"' in response.text
    assert '"target": "zone-nord"' in response.text
    assert '"chunk_type": "map_state_updated"' in response.text
    assert "data: [DONE]" in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "map_command"
    assert run.output_ref["map_command"]["target"] == "zone-nord"


def test_chat_stream_vigie_signals_uses_fast_mission_room_reply(db_session, monkeypatch):
    workspace = Workspace(id="ws-sentinel-vigie", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Quels signaux nécessitent une attention cabinet aujourd'hui ?",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "attention cabinet" in response.text
    assert '"chunk_type": "text"' in response.text
    assert "data: [DONE]" in response.text
    assert '"chunk_type": "retrieval"' not in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "vigie_quick_brief"
    assert run.output_ref["knowledge_scope"] == "vigie"


def test_chat_stream_vigie_cockpit_60s_routes_to_priority_summary(db_session, monkeypatch):
    """``Donne-moi le cockpit 60 secondes`` must reach the registry resolver
    (``aya.priority_summary`` → ``briefing_priorities_v1``), not a hardcoded
    cockpit shortcut. The narrative comes from ``ATTENTION_REQUIRED`` so the
    Napié cause-racine wording propagates automatically.
    """
    workspace = Workspace(id="ws-sentinel-cockpit", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Donne-moi le cockpit 60 secondes",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "prioritaires" in response.text.lower()
    assert '"chunk_type": "action_result"' in response.text
    assert '"aya.priority_summary"' in response.text
    assert '"chunk_type": "retrieval"' not in response.text
    assert "data: [DONE]" in response.text
    assert "Konate" not in response.text
    assert "Burkina" not in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "action_registry"


def test_chat_stream_vigie_north_situation_drills_to_napie(db_session, monkeypatch):
    """``Quelle est la situation au nord ?`` must drill the causal chain via
    ``aya.explain_why`` and surface the Centre Drones Napié narrative — the
    old hardcoded Konaté/Burkina/CEDEAO Mission Room reply is gone.
    """
    workspace = Workspace(id="ws-sentinel-north", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "AYA, quelle est la situation au nord ?",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert '"chunk_type": "action_result"' in response.text
    assert '"aya.explain_why"' in response.text
    assert ("Napi" in response.text) or ("proj-drone-centre-napie" in response.text)
    assert '"chunk_type": "map_command"' not in response.text
    assert '"chunk_type": "retrieval"' not in response.text
    assert "data: [DONE]" in response.text
    assert "Konate" not in response.text
    assert "Burkina" not in response.text


def test_chat_stream_vigie_brief_operationnel_projet_nord_focuses_napie(db_session, monkeypatch):
    """``Brief opérationnel · Projet sensible · Nord`` card prompt must focus
    the map on the Napié project via ``aya.focus_zone_with_project`` — no
    Konaté/Burkina fallback narrative."""
    workspace = Workspace(id="ws-sentinel-brief", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "AYA, donne-moi le brief opérationnel pour Projet sensible · Nord avec sources et action recommandée.",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert '"aya.focus_zone_with_project"' in response.text
    assert "Napi" in response.text
    assert "Aerostar" in response.text
    assert '"chunk_type": "map_command"' in response.text
    assert "data: [DONE]" in response.text
    assert "Konate" not in response.text
    assert "Burkina" not in response.text


def test_chat_stream_registry_priority_summary(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-sentinel-priority",
        name="SENTINEL-CI",
        slug="sentinel-ci",
        mode="demo",
        settings={"actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]}},
    )
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Aya, fais moi un résumé des sujets prioritaires",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "prioritaires" in response.text.lower()
    assert '"chunk_type": "action_result"' in response.text
    assert '"chunk_type": "retrieval"' not in response.text
    assert "data: [DONE]" in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "action_registry"


def test_chat_stream_registry_maritime_then_oui_draft(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-sentinel-maritime",
        name="SENTINEL-CI",
        slug="sentinel-ci",
        mode="demo",
        settings={"actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]}},
    )
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()
    client = _client(db_session, workspace, HappyOrchestrator(), monkeypatch)

    maritime = client.post(
        "/chat/stream",
        json={
            "query": "Montre moi le trafic maritime à destination d'Abidjan",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )
    assert maritime.status_code == 200
    assert '"effect": "assistant-propose"' in maritime.text
    assert "data: [DONE]" in maritime.text

    confirm = client.post(
        "/chat/stream",
        json={
            "query": "oui",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )
    assert confirm.status_code == 200
    assert '"effect": "assistant-draft-open"' in confirm.text
    assert "dedouanement" in confirm.text.lower()
    assert "data: [DONE]" in confirm.text


def test_chat_stream_registry_next_meeting_navigates_agenda(db_session, monkeypatch):
    from app.services.workspace_calendar import ensure_calendar_seed

    workspace = Workspace(
        id="ws-sentinel-next",
        name="SENTINEL-CI",
        slug="sentinel-ci",
        mode="demo",
        settings={"actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]}},
    )
    db_session.add(workspace)
    db_session.commit()
    ensure_calendar_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "OK Aya, quel est mon prochain RDV ?",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "Nawa" in response.text
    assert '"effect": "assistant-navigate"' in response.text
    assert "/hypervisor/mission-room/agenda" in response.text
    assert "data: [DONE]" in response.text
