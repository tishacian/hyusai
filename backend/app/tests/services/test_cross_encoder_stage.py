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


def _big_pool(n):
    chunks = [f"chunk {i}" for i in range(n)]
    scores = [1.0 - i * 0.001 for i in range(n)]
    metadatas = [{"document_filename": f"doc{i}.pdf"} for i in range(n)]
    return chunks, scores, metadatas


@pytest.mark.asyncio
async def test_deep_budget_timeout_keeps_policy_order(monkeypatch):
    monkeypatch.setattr(cross_encoder_stage, "_reranker_unavailable_reason", None)
    monkeypatch.setattr(cross_encoder_stage.settings, "rag_cross_encoder_budget_seconds_deep", 0.05)

    def slow_score(query, passages, *, model_name, max_length):
        time.sleep(0.5)
        return [0.9] * len(passages)

    monkeypatch.setattr(cross_encoder_stage, "_score_passages", slow_score)
    chunks, scores, metadatas = _pool()
    out_chunks, out_scores, out_metadatas, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="deep", allow_cross_encoder=True, top_k=5,
    )
    # Deep is now bounded: a slow score exceeds the budget and degrades to the
    # untouched policy order with a timeout diagnostic.
    assert out_chunks == chunks
    assert out_scores == scores
    assert out_metadatas == metadatas
    assert diag["cross_encoder_status"] == "timeout"


@pytest.mark.asyncio
async def test_deep_pool_is_capped(monkeypatch):
    monkeypatch.setattr(cross_encoder_stage, "_reranker_unavailable_reason", None)
    monkeypatch.setattr(cross_encoder_stage.settings, "rag_cross_encoder_max_candidates_deep", 3)
    monkeypatch.setattr(cross_encoder_stage.settings, "rag_cross_encoder_budget_seconds_deep", 25.0)
    captured: dict = {}

    def capture(query, passages, *, model_name, max_length):
        captured["count"] = len(passages)
        # Reverse the head pool so reordering is observable.
        return [float(i) for i in range(len(passages))]

    monkeypatch.setattr(cross_encoder_stage, "_score_passages", capture)
    chunks, scores, metadatas = _big_pool(6)
    out_chunks, _, _, diag = await rerank_with_cross_encoder(
        chunks, scores, metadatas,
        query="q", latency_profile="deep", allow_cross_encoder=True, top_k=10,
    )
    assert diag["cross_encoder_status"] == "applied"
    # Only the first 3 candidates are scored; the tail beyond the pool keeps order.
    assert captured["count"] == 3
    assert diag["cross_encoder_scored"] == 3
    # Tail (indices 3,4,5) is appended untouched after the reordered pool.
    assert out_chunks[-3:] == ["chunk 3", "chunk 4", "chunk 5"]
    # Pool of 3 reordered by descending CE score (scores were 0,1,2 -> idx 2,1,0).
    assert out_chunks[:3] == ["chunk 2", "chunk 1", "chunk 0"]


@pytest.mark.asyncio
async def test_balanced_unaffected_by_deep_settings(monkeypatch):
    monkeypatch.setattr(cross_encoder_stage, "_reranker_unavailable_reason", None)
    # Extreme deep settings must not leak into the balanced branch.
    monkeypatch.setattr(cross_encoder_stage.settings, "rag_cross_encoder_max_candidates_deep", 1)
    monkeypatch.setattr(cross_encoder_stage.settings, "rag_cross_encoder_budget_seconds_deep", 0.05)
    monkeypatch.setattr(cross_encoder_stage.settings, "rag_cross_encoder_max_length_deep", 8)
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
        query="q", latency_profile="balanced", allow_cross_encoder=True, top_k=5,
    )
    assert diag["cross_encoder_status"] == "applied"
    # Balanced uses its own settings, not the (extreme) deep ones.
    assert captured["model"] == cross_encoder_stage.settings.rag_cross_encoder_model_balanced
    assert captured["max_length"] == max(64, int(cross_encoder_stage.settings.rag_cross_encoder_max_length_balanced))
    # All 4 chunks scored (balanced max_candidates default 24 >= 4), not capped to 1.
    assert captured["count"] == 4
