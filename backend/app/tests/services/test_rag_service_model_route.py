from __future__ import annotations

import pytest

from app.services.rag import rag_service


class _Orchestrator:
    def __init__(self):
        self.request = None

    async def process_request(self, request):
        self.request = request
        yield {"chunk_type": "text", "content": "grounded", "is_final": True}


@pytest.mark.asyncio
async def test_provider_qualified_model_is_split_for_orchestrator(monkeypatch):
    orchestrator = _Orchestrator()
    monkeypatch.setattr(rag_service, "_get_orchestrator", lambda: orchestrator)

    result = await rag_service.answer(
        "question",
        model="anthropic:claude-opus-5",
        workspace_id="workspace-1",
    )

    assert result["answer"] == "grounded"
    assert orchestrator.request["agent_preferences"]["model_preferences"] == {
        "provider": "anthropic",
        "model": "claude-opus-5",
    }


@pytest.mark.asyncio
async def test_rag_service_preserves_structured_generation_failure(monkeypatch):
    class FailedOrchestrator:
        async def process_request(self, request):
            yield {
                "chunk_type": "error",
                "content": "Credentials are invalid.",
                "error": {
                    "code": "credentials_invalid",
                    "message": "Credentials are invalid.",
                    "retryable": False,
                },
                "is_final": True,
            }

    monkeypatch.setattr(rag_service, "_get_orchestrator", FailedOrchestrator)

    result = await rag_service.answer("question", model="anthropic:claude-opus-5")

    assert result["answer"] == ""
    assert result["meta"]["error"]["code"] == "credentials_invalid"
