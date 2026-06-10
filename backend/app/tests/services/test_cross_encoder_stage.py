import asyncio
import time

import pytest

from app.services.rag import cross_encoder_stage
from app.services.rag.cross_encoder_stage import rerank_with_cross_encoder


def _pool():
    chunks = ["guide synthetic", "weak chunk", "strong chunk", "medium chunk"]
    scores = [1.0, 0.016, 0.015, 0.014]
    metadatas = [
        {"source_type": "knowledge_guide"},
        {"document_filename": "a.pdf"},
        {"document_filename": "b.pdf"},
        {"document_filename": "c.pdf"},
    ]
    return chunks, scores, metadatas


def _exempt(meta):
    return str(meta.get("source_type") or "") == "knowledge_guide"


@pytest.mark.asyncio
async def test_fast_profile_never_reranks(monkeypatch):
    chunks, scores, metadatas = _pool()
    out_chunks, _, _, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="fast", allow_cross_encoder=True, top_k=5,
    )
    assert out_chunks == chunks
    assert diag["cross_encoder_status"] == "skipped_fast"


@pytest.mark.asyncio
async def test_profile_contract_gating(monkeypatch):
    chunks, scores, metadatas = _pool()
    _, _, _, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="balanced", allow_cross_encoder=False, top_k=5,
    )
    assert diag["cross_encoder_status"] == "skipped_profile"


@pytest.mark.asyncio
async def test_balanced_rerank_reorders_and_gates(monkeypatch):
    monkeypatch.setattr(cross_encoder_stage, "_reranker_unavailable_reason", None)
    # weak=0.05 (below threshold 0.2), strong=0.9, medium=0.4
    monkeypatch.setattr(
        cross_encoder_stage,
        "_score_passages",
        lambda query, passages, *, model_name, max_length: [0.05, 0.9, 0.4],
    )
    chunks, scores, metadatas = _pool()
    out_chunks, out_scores, out_metadatas, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="balanced", allow_cross_encoder=True, top_k=2,
        is_exempt_metadata=_exempt,
    )
    assert diag["cross_encoder_status"] == "applied"
    # Exempt guide stays at the head; survivors ordered by CE score; the weak
    # chunk below threshold is dropped (min survivors = min(top_k, 3) = 2).
    assert out_chunks == ["guide synthetic", "strong chunk", "medium chunk"]
    assert diag["cross_encoder_filtered"] == 1
    assert out_metadatas[1]["cross_encoder_score"] == 0.9
    assert "cross_encoder_score" not in out_metadatas[0]


@pytest.mark.asyncio
async def test_min_survivors_protected_even_below_threshold(monkeypatch):
    monkeypatch.setattr(cross_encoder_stage, "_reranker_unavailable_reason", None)
    monkeypatch.setattr(
        cross_encoder_stage,
        "_score_passages",
        lambda query, passages, *, model_name, max_length: [0.01, 0.02, 0.03],
    )
    chunks, scores, metadatas = _pool()
    out_chunks, _, _, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="balanced", allow_cross_encoder=True, top_k=8,
        is_exempt_metadata=_exempt,
    )
    assert diag["cross_encoder_status"] == "applied"
    # All below threshold, but min(top_k, 3) = 3 survivors are kept.
    assert len(out_chunks) == 4  # guide + 3 survivors


@pytest.mark.asyncio
async def test_budget_timeout_keeps_policy_order(monkeypatch):
    monkeypatch.setattr(cross_encoder_stage, "_reranker_unavailable_reason", None)
    monkeypatch.setattr(cross_encoder_stage.settings, "rag_cross_encoder_budget_seconds", 0.05)

    def slow_score(query, passages, *, model_name, max_length):
        time.sleep(0.5)
        return [0.9] * len(passages)

    monkeypatch.setattr(cross_encoder_stage, "_score_passages", slow_score)
    chunks, scores, metadatas = _pool()
    out_chunks, _, _, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="balanced", allow_cross_encoder=True, top_k=5,
    )
    assert out_chunks == chunks
    assert diag["cross_encoder_status"] == "timeout"


@pytest.mark.asyncio
async def test_scoring_error_keeps_policy_order(monkeypatch):
    monkeypatch.setattr(cross_encoder_stage, "_reranker_unavailable_reason", None)

    def broken(query, passages, *, model_name, max_length):
        raise RuntimeError("boom")

    monkeypatch.setattr(cross_encoder_stage, "_score_passages", broken)
    chunks, scores, metadatas = _pool()
    out_chunks, _, _, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="balanced", allow_cross_encoder=True, top_k=5,
    )
    assert out_chunks == chunks
    assert diag["cross_encoder_status"] == "error"


@pytest.mark.asyncio
async def test_deep_profile_runs_without_budget(monkeypatch):
    monkeypatch.setattr(cross_encoder_stage, "_reranker_unavailable_reason", None)
    captured: dict = {}

    def capture(query, passages, *, model_name, max_length):
        captured["model"] = model_name
        captured["max_length"] = max_length
        captured["count"] = len(passages)
        return [0.5] * len(passages)

    monkeypatch.setattr(cross_encoder_stage, "_score_passages", capture)
    chunks, scores, metadatas = _pool()
    _, _, _, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="deep", allow_cross_encoder=True, top_k=5,
    )
    assert diag["cross_encoder_status"] == "applied"
    assert captured["max_length"] == 512
    assert captured["count"] == len(chunks)  # full pool, no exempt fn given
