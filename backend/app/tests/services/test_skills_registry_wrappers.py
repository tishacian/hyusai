from __future__ import annotations

import pytest

from app.services.skills_registry.seed import SEED_SKILLS
from app.services.skills_registry import wrappers


@pytest.mark.asyncio
async def test_semantic_search_wrapper_uses_planned_rag_context(monkeypatch):
    seen: dict = {}

    async def fake_retrieve_rag_context(request):
        seen.update(request)
        return {
            "chunks": ["planned evidence"],
            "scores": [0.91],
            "metadatas": [{"document_filename": "manual.pdf"}],
            "pipeline": "hybrid",
            "label": "hybrid_rrf",
            "reason": "planned retrieval",
            "detail": "bounded by planner",
            "metrics": {
                "retrieval_scope": {"filters": {"project_code": "ACJ100"}},
                "scope_confidence": 0.82,
                "scope_reason": "Project code inferred",
                "dense_policy": "fast_scoped_dense",
                "fallback_reason": None,
                "latency_budget": {"profile": "balanced", "candidate_pool_k": 80},
            },
        }

    monkeypatch.setattr(
        "app.services.rag.context.retrieve_rag_context",
        fake_retrieve_rag_context,
    )

    result = await wrappers._semantic_search_v1(
        {
            "query": "cherche la procedure ACJ100",
            "top_k": 12,
            "candidate_pool_k": 20,
            "source_display_k": 4,
            "mode": "chah",
            "deep_retrieval": True,
            "collection": "andritz-notices-techniques-spl-pilot",
            "retrieval_filters": {"project_code": "ACJ100"},
        },
        {
            "workspace_id": "ws-1",
            "workspace_slug": "andritz",
            "latency_profile": "balanced",
        },
    )

    assert seen["query"] == "cherche la procedure ACJ100"
    assert seen["workspace_id"] == "ws-1"
    assert seen["workspace_slug"] == "andritz"
    assert seen["context_collection"] == "andritz-notices-techniques-spl-pilot"
    assert seen["rag_pipeline_mode"] == "chah"
    assert seen["latency_profile"] == "deep"
    assert seen["candidate_pool_k"] == 20
    assert seen["source_display_k"] == 4
    assert seen["deep_retrieval"] is True
    assert seen["latency_budget"]["profile"] == "deep"
    assert seen["retrieval_filters"] == {"project_code": "ACJ100"}
    assert result["results"] == [
        {
            "content": "planned evidence",
            "score": 0.91,
            "metadata": {"document_filename": "manual.pdf"},
        }
    ]
    assert result["retrieval_scope"] == {"filters": {"project_code": "ACJ100"}}
    assert result["scope_confidence"] == 0.82
    assert result["dense_policy"] == "fast_scoped_dense"
    assert result["latency_budget"] == {"profile": "balanced", "candidate_pool_k": 80}


def test_seed_rag_skills_expose_retrieval_policy_contract():
    by_slug = {entry["slug"]: entry for entry in SEED_SKILLS}
    expected_slugs = {
        "llm_rag_answer_v1",
        "semantic_search_v1",
        "chain_naive_v1",
        "chain_hybrid_v1",
        "chain_mixed_hah_v1",
    }
    expected_properties = {
        "top_k",
        "candidate_pool_k",
        "synthesis_k",
        "source_display_k",
        "rag_pipeline_mode",
        "latency_profile",
        "retrieval_profile",
        "deep_retrieval",
        "knowledge_scope",
        "collection",
        "collection_name",
        "context_collection",
        "retrieval_filters",
    }

    for slug in expected_slugs:
        properties = by_slug[slug]["input_schema"]["properties"]
        assert expected_properties <= set(properties)

    assert by_slug["semantic_search_v1"]["execution"]["timeout_ms"] == 8_000
    assert "sparse+dense" in by_slug["semantic_search_v1"]["description"]


@pytest.mark.asyncio
async def test_semantic_search_wrapper_defaults_to_fast_latency(monkeypatch):
    seen: dict = {}

    async def fake_retrieve_rag_context(request):
        seen.update(request)
        return {
            "chunks": [],
            "scores": [],
            "metadatas": [],
            "pipeline": "none",
            "label": "none",
            "reason": "empty",
            "detail": "empty",
            "metrics": {},
        }

    monkeypatch.setattr(
        "app.services.rag.context.retrieve_rag_context",
        fake_retrieve_rag_context,
    )

    await wrappers._semantic_search_v1({"query": "de quelles donnees disposes-tu ?"}, {})

    assert seen["latency_profile"] == "fast"
    assert seen["rag_pipeline_mode"] == "auto"


@pytest.mark.asyncio
async def test_llm_rag_answer_wrapper_forwards_scope_and_budget(monkeypatch):
    captured: dict = {}

    class FakeOrchestrator:
        async def process_request(self, request):
            captured.update(request)
            yield {
                "chunk_type": "retrieval",
                "phase": "completed",
                "details": {
                    "dense_policy": "fast_scoped_dense",
                    "fallback_reason": "sparse_unavailable",
                    "retrieval_scope": {"filters": {"project_code": "ACJ100"}},
                    "scope_confidence": 0.87,
                    "latency_budget": {"profile": "balanced", "candidate_pool_k": 80},
                },
                "rag_context": {"chunks": ["evidence"], "scores": [0.8], "metadatas": []},
                "is_final": False,
            }
            yield {"chunk_type": "text", "content": "answer", "is_final": False}
            yield {"chunk_type": "text", "content": "", "is_final": True}

    monkeypatch.setattr(
        "app.services.rag.rag_service._get_orchestrator",
        lambda: FakeOrchestrator(),
    )

    result = await wrappers._llm_rag_answer_v1(
        {
            "query": "Explique la procedure ACJ100",
            "rag_pipeline_mode": "chah",
            "top_k": 99,
            "candidate_pool_k": 999,
            "latency_profile": "balanced",
            "retrieval_profile": "chat",
            "collection": "andritz-notices-techniques-spl-pilot",
            "retrieval_filters": {"project_code": "ACJ100"},
        },
        {
            "workspace_id": "ws-1",
            "workspace_slug": "andritz",
        },
    )

    assert result["answer"] == "answer"
    assert captured["workspace_id"] == "ws-1"
    assert captured["workspace_slug"] == "andritz"
    assert captured["rag_pipeline_mode"] == "chah"
    assert captured["top_k"] == 12
    assert captured["candidate_pool_k"] == 80
    assert captured["latency_profile"] == "balanced"
    assert captured["retrieval_profile"] == "chat"
    assert captured["latency_budget"]["profile"] == "balanced"
    assert captured["latency_budget"]["candidate_pool_k"] == 80
    assert captured["context_collection"] == "andritz-notices-techniques-spl-pilot"
    assert captured["retrieval_filters"] == {"project_code": "ACJ100"}
    assert result["meta"]["dense_policy"] == "fast_scoped_dense"
    assert result["meta"]["fallback_reason"] == "sparse_unavailable"
    assert result["meta"]["retrieval_scope"] == {"filters": {"project_code": "ACJ100"}}
    assert result["meta"]["latency_budget"] == {"profile": "balanced", "candidate_pool_k": 80}
    assert result["meta"]["rag_context"]["chunks"] == ["evidence"]


@pytest.mark.asyncio
async def test_chain_wrappers_forward_retrieval_policy_fields(monkeypatch):
    captured: dict = {}

    class FakeOrchestrator:
        async def process_request(self, request):
            captured.update(request)
            yield {"chunk_type": "text", "content": "chain answer", "is_final": True}

    monkeypatch.setattr(
        "app.services.rag.rag_service._get_orchestrator",
        lambda: FakeOrchestrator(),
    )

    result = await wrappers._chain_mixed_hah_v1(
        {
            "query": "Audit SPL",
            "top_k": 12,
            "candidate_pool_k": 80,
            "latency_profile": "deep",
            "deep_retrieval": True,
            "collection_name": "andritz-notices-techniques-spl-pilot",
            "retrieval_filters": {"source_kind": "markup"},
        },
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )

    assert result["answer"] == "chain answer"
    assert captured["rag_pipeline_mode"] == "chah"
    assert captured["top_k"] == 12
    assert captured["candidate_pool_k"] == 80
    assert captured["latency_profile"] == "deep"
    assert captured["deep_retrieval"] is True
    assert captured["context_collection"] == "andritz-notices-techniques-spl-pilot"
    assert captured["retrieval_filters"] == {"source_kind": "markup"}
