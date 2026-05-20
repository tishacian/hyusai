from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat
from app.core.config import settings
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


def test_chat_stream_vigie_cockpit_60s_uses_deterministic_reply(db_session, monkeypatch):
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
    assert "Lecture 60 secondes" in response.text
    assert "Zone Nord" in response.text
    assert "L'Inter" in response.text
    assert "data: [DONE]" in response.text
    assert '"chunk_type": "retrieval"' not in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "vigie_quick_brief"
    assert run.output_ref["vigie_quick_reply"]["handler"] == "cockpit_60s"


def test_chat_stream_vigie_north_situation_does_not_emit_map_command(db_session, monkeypatch):
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
    assert "Zone Nord" in response.text
    assert "15h00" in response.text
    assert '"chunk_type": "map_command"' not in response.text
    assert '"chunk_type": "retrieval"' not in response.text
    assert "data: [DONE]" in response.text


def test_chat_stream_vigie_abidjan_port_has_text_reply_without_map_command(db_session, monkeypatch):
    workspace = Workspace(id="ws-sentinel-port", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Quel est le risque portuaire autour d'Abidjan ?",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "Port d'Abidjan" in response.text
    assert '"chunk_type": "map_command"' not in response.text
    assert '"chunk_type": "retrieval"' not in response.text
    assert "data: [DONE]" in response.text
