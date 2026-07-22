from __future__ import annotations

import asyncio

from app.api.v1.endpoints import chat
from app.models.user import User
from app.models.workspace import Workspace


def test_registry_chat_wrapper_forwards_resolved_system_to_executor(monkeypatch):
    workspace = Workspace(
        id="ws-chat-action-wiring",
        slug="chat-action-wiring",
        name="Chat action wiring",
        settings={},
    )
    user = User(
        id="user-chat-action-wiring",
        username="chat-action-wiring",
        email="chat-action-wiring@example.test",
    )
    captured: list[dict] = []

    async def _handle(*_args, **kwargs):
        captured.append(kwargs)
        return {"action": "authorized", "content": "ok"}

    monkeypatch.setattr(chat, "handle_registry_chat_action", _handle)

    result = asyncio.run(
        chat._try_registry_chat_action(
            object(),
            workspace,
            user,
            query="AYA",
            assistant_profile="vigie_executive",
            session_id="session-123",
            knowledge_scope="scope-123",
            system_id="system-resolved-123",
        )
    )

    assert result == {"action": "authorized", "content": "ok"}
    assert captured == [
        {
            "query": "AYA",
            "assistant_profile": "vigie_executive",
            "session_id": "session-123",
            "knowledge_scope": "scope-123",
            "system_id": "system-resolved-123",
        }
    ]
