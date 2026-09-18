"""Frozen HTTP contract of ``POST /api/v1/assistant/turns``.

Two other surfaces are built against this shape without being able to read the
implementation, so the response keys are asserted exhaustively here on purpose.
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import assistant as assistant_endpoint
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.assistant import MAX_SESSION_CONTEXT_CHARS
from app.services.assistant import engine as assistant_engine


class FakeToolClient:
    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.api_key = "test"
        self.calls: list[dict] = []

    async def complete_with_tools(self, model, messages, *, tools=None, **kwargs):
        self.calls.append({"tools": tools, "prompt": messages[0]["content"]})
        return self.script.pop(0)


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(assistant_endpoint.router, prefix="/assistant")
    app.dependency_overrides[assistant_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[assistant_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[assistant_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session) -> tuple[Workspace, User]:
    workspace = Workspace(
        id="ws-assistant-api",
        name="Assistant API",
        slug="assistant-api",
        settings={
            "knowledge_scopes": [
                {"key": "itsd", "collection_slugs": ["itsd-knowledge"], "is_default": True}
            ],
            "assistant": {
                "persona": "Tu es l'assistant ITSD.",
                "knowledge_scope": "itsd",
                "allowed_tools": ["search_knowledge"],
            },
        },
    )
    user = User(id="user-assistant-api", username="api@datategy.test")
    db_session.add_all(
        [
            workspace,
            user,
            WorkspaceMember(
                user_id=user.id,
                workspace_id=workspace.id,
                role="member",
                role_template="workspace_contributor",
            ),
        ]
    )
    db_session.commit()
    return workspace, user


def test_a_turn_returns_the_full_render_contract(db_session, monkeypatch):
    workspace, user = _seed(db_session)

    async def fake_retrieve(request):
        return {
            "chunks": ["Ouvrez un ticket ITSD."],
            "scores": [0.9],
            "metadatas": [
                {
                    "chunk_id": "chunk-9",
                    "document_filename": "itsd.md",
                    "document_id": "doc-9",
                    "collection": "itsd-knowledge",
                    "page": 2,
                }
            ],
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", fake_retrieve)
    monkeypatch.setattr(
        assistant_engine,
        "build_model_client",
        lambda config: FakeToolClient(
            [
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_a",
                            "name": "search_knowledge",
                            "arguments": {"query": "mot de passe"},
                            "arguments_json": json.dumps({"query": "mot de passe"}),
                        }
                    ],
                    "finish_reason": "tool_calls",
                    "usage": {},
                },
                {
                    "content": "Ouvrez un ticket ITSD.",
                    "tool_calls": [],
                    "finish_reason": "stop",
                    "usage": {"total_tokens": 42},
                },
            ]
        ),
    )

    response = _client(db_session, workspace, user).post(
        "/assistant/turns",
        json={
            "text": "comment réinitialiser mon mot de passe ?",
            "surface": "text",
            "session_context": {"route_hint": "password_reset"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "session_id",
        "message_id",
        "answer",
        "citations",
        "tool_calls",
        "model",
        "surface",
        "tool_turns",
        "finish_reason",
        "usage",
        "config",
        "object_context",
    }
    assert body["answer"] == "Ouvrez un ticket ITSD."
    assert body["surface"] == "text"
    assert body["tool_turns"] == 1
    assert body["finish_reason"] == "stop"
    assert body["usage"] == {"total_tokens": 42}
    assert body["config"] == {
        "configured": True,
        "knowledge_scope": "itsd",
        "allowed_tools": ["search_knowledge"],
    }
    assert body["object_context"] == {}
    assert body["citations"] == [
        {
            "index": 1,
            "id": "chunk-9",
            "title": "itsd.md",
            "filename": "itsd.md",
            "document_id": "doc-9",
            "collection": "itsd-knowledge",
            "page": 2,
        }
    ]
    assert set(body["tool_calls"][0]) == {
        "id",
        "name",
        "arguments",
        "ok",
        "error",
        "result",
        "duration_ms",
    }
    assert body["tool_calls"][0]["name"] == "search_knowledge"
    assert body["tool_calls"][0]["ok"] is True
    assert body["tool_calls"][0]["error"] is None
    assert body["tool_calls"][0]["arguments"] == {"query": "mot de passe"}
    assert body["session_id"] and body["message_id"]


def test_the_returned_session_id_continues_the_same_thread(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    monkeypatch.setattr(
        assistant_engine,
        "build_model_client",
        lambda config: FakeToolClient(
            [{"content": "ok", "tool_calls": [], "finish_reason": "stop", "usage": {}}]
        ),
    )
    client = _client(db_session, workspace, user)

    first = client.post("/assistant/turns", json={"text": "un"}).json()
    second = client.post(
        "/assistant/turns",
        json={"text": "deux", "session_id": first["session_id"]},
    ).json()

    assert second["session_id"] == first["session_id"]
    assert second["message_id"] != first["message_id"]


def test_an_unknown_session_id_is_a_404_with_a_stable_code(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    monkeypatch.setattr(
        assistant_engine,
        "build_model_client",
        lambda config: FakeToolClient(
            [{"content": "ok", "tool_calls": [], "finish_reason": "stop", "usage": {}}]
        ),
    )

    response = _client(db_session, workspace, user).post(
        "/assistant/turns",
        json={"text": "salut", "session_id": "nope"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "assistant_session_not_found"


def test_an_unavailable_model_plane_is_a_503_with_a_stable_code(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    workspace.settings = {**workspace.settings, "assistant": {"provider": "ollama"}}
    db_session.commit()

    response = _client(db_session, workspace, user).post(
        "/assistant/turns",
        json={"text": "salut"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "assistant_unavailable"


def test_an_empty_text_is_rejected_by_validation(db_session):
    workspace, user = _seed(db_session)

    response = _client(db_session, workspace, user).post("/assistant/turns", json={"text": ""})

    assert response.status_code == 422


def test_unknown_request_fields_are_rejected(db_session):
    workspace, user = _seed(db_session)

    response = _client(db_session, workspace, user).post(
        "/assistant/turns",
        json={"text": "salut", "workspace_id": "ws-other"},
    )

    assert response.status_code == 422


def test_a_session_context_larger_than_the_voice_lane_accepts_is_rejected(db_session):
    """One ceiling for both lanes, so a catalogue is not lane-dependent.

    The voice gateway drops an ``assistant.context`` push past
    ``MAX_SESSION_CONTEXT_CHARS``; without the same bound here the typed lane
    took an unbounded dictionary into the prompt builder and the session row.
    """
    workspace, user = _seed(db_session)
    oversized = {"service_catalog": [{"slug": "s", "summary": "x" * MAX_SESSION_CONTEXT_CHARS}]}

    response = _client(db_session, workspace, user).post(
        "/assistant/turns",
        json={"text": "salut", "session_context": oversized},
    )

    assert response.status_code == 422
    assert "session_context" in json.dumps(response.json())


def test_a_session_context_within_the_ceiling_is_accepted(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    monkeypatch.setattr(
        assistant_engine,
        "build_model_client",
        lambda config: FakeToolClient(
            [{"content": "ok", "tool_calls": [], "finish_reason": "stop", "usage": {}}]
        ),
    )
    # The real NAWA catalogue is a little over 30 kB; the ceiling is 256 kB.
    context = {"service_catalog": [{"slug": "s", "summary": "x" * 30_000}]}

    response = _client(db_session, workspace, user).post(
        "/assistant/turns",
        json={"text": "salut", "session_context": context},
    )

    assert response.status_code == 200


def test_a_run_object_context_is_authorized_and_derives_pilot_scope(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    db_session.add(System(id="system-open", workspace_id=workspace.id, name="Open System"))
    db_session.flush()
    db_session.add(
        Run(
            id="run-open",
            workspace_id=workspace.id,
            system_id="system-open",
            initiated_by_user_id=user.id,
            trigger="manual",
            status="completed",
        )
    )
    db_session.commit()
    client = FakeToolClient([
        {"content": "This run completed.", "tool_calls": [], "finish_reason": "stop", "usage": {}}
    ])
    monkeypatch.setattr(assistant_engine, "build_model_client", lambda config: client)

    response = _client(db_session, workspace, user).post(
        "/assistant/turns",
        json={
            "text": "Explain this run",
            "surface": "pilot",
            "request_id": "context-run-open",
            "system_ids": [],
            "session_context": {
                "object_context": {
                    "type": "run",
                    "id": "run-open",
                    "run_id": "run-open",
                    "node_id": "summary",
                }
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["object_context"] == {
        "type": "run",
        "id": "run-open",
        "system_id": "system-open",
        "run_id": "run-open",
        "node_id": "summary",
    }
    assert "Open object context" in client.calls[0].get("prompt", "")


def test_an_object_context_from_another_workspace_is_rejected(db_session):
    workspace, user = _seed(db_session)
    other = Workspace(id="ws-other", name="Other", slug="other")
    other_system = System(id="system-other", workspace_id=other.id, name="Other System")
    db_session.add_all([other, other_system])
    db_session.commit()

    response = _client(db_session, workspace, user).post(
        "/assistant/turns",
        json={
            "text": "Explain this system",
            "surface": "pilot",
            "request_id": "context-other",
            "system_ids": [],
            "session_context": {"object_context": {"type": "system", "id": "system-other"}},
        },
    )

    assert response.status_code == 404
