from __future__ import annotations

import pytest

from app.agents.rag_agent import RAGAgent
from app.services.system_prompts.types import SystemPromptType


class _FakeStream:
    def __init__(self):
        self._done = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._done:
            raise StopAsyncIteration
        self._done = True
        return {"content": "planned answer", "done": True}


class _FakeOllamaClient:
    def stream(self, **kwargs):  # noqa: ARG002
        return _FakeStream()


class _FakeModelService:
    ollama_client = _FakeOllamaClient()


@pytest.mark.asyncio
async def test_rag_agent_uses_planned_retrieval_context(monkeypatch):
    seen: dict = {}

    monkeypatch.setattr(
        "app.agents.rag_agent.get_resolved_settings",
        lambda **kwargs: {  # noqa: ARG005
            "defaultModel": "test-model",
            "ragCollectionName": "andritz-notices-techniques-spl-pilot",
            "ragTopK": 50,
            "ragPipelineMode": "chah",
            "ragCandidatePoolK": 120,
            "ragSynthesisK": 48,
            "ragSourceDisplayK": 24,
        },
    )

    async def fake_retrieve_rag_context(request):
        seen.update(request)
        return {
            "chunks": ["planned evidence"],
            "scores": [0.91],
            "metadatas": [
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "document_filename": "manual.pdf",
                }
            ],
            "pipeline": "catalogue_inventory",
            "metrics": {
                "dense_policy": "catalogue_inventory",
                "candidate_pool_k": 20,
            },
        }

    monkeypatch.setattr(
        "app.services.rag.context.retrieve_rag_context",
        fake_retrieve_rag_context,
    )

    agent = object.__new__(RAGAgent)
    agent.model_service = _FakeModelService()

    events = [
        event
        async for event in agent.process(
            {
                "query": "de quelles donnees disposes-tu ?",
                "workspace_slug": "andritz",
            }
        )
    ]

    assert seen["query"] == "de quelles donnees disposes-tu ?"
    assert seen["workspace_slug"] == "andritz"
    assert seen["top_k"] == 8
    assert seen["latency_profile"] == "fast"
    assert seen["candidate_pool_k"] == 20
    assert seen["latency_budget"]["candidate_pool_k"] == 20

    retrieval_steps = [
        event["decision_step"]
        for event in events
        if event.get("chunk_type") == "decision_step"
        and event.get("decision_step", {}).get("type") == "retrieve"
    ]
    assert retrieval_steps[-1]["status"] == "completed"
    assert "catalogue_inventory" in retrieval_steps[-1]["title"]

    first_text = next(event for event in events if event.get("chunk_type") == "text")
    assert first_text["sources"][0]["id"] == "chunk-1"
    assert first_text["sources"][0]["metadata"]["document_filename"] == "manual.pdf"


def test_reasoning_template_places_current_evidence_after_stale_history():
    agent = object.__new__(RAGAgent)

    prompt = agent._render_reasoning_template(
        SystemPromptType.FACTUAL,
        "How many annual leave days are provided?",
        "Employees receive 22 paid working days of annual leave.",
        [
            {
                "role": "assistant",
                "content": "Employees receive 35 paid working days of annual leave.",
            }
        ],
    )

    assert prompt is not None
    assert prompt.index("35 paid") < prompt.index("22 paid")
    assert prompt.index("22 paid") < prompt.index("current retrieved context is authoritative")
    assert "ignore the stale answer" in prompt


def test_default_rag_prompt_marks_current_context_authoritative():
    agent = object.__new__(RAGAgent)

    prompt = agent._construct_prompt(
        "How many annual leave days are provided?",
        "Employees receive 22 paid working days of annual leave.",
        [{"role": "assistant", "content": "The allowance is 35 days."}],
    )

    assert prompt.index("35 days") < prompt.index("22 paid")
    assert "current retrieved context is authoritative" in prompt
