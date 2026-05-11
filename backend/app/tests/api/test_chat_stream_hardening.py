from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat
from app.core.config import settings
from app.models.run import Run
from app.models.workspace import Workspace


def _client(db_session, workspace: Workspace, orchestrator, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(chat.router, prefix="/chat")
    app.dependency_overrides[chat.get_current_workspace] = lambda: workspace
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
