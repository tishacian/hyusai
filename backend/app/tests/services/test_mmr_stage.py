import asyncio
import time

import numpy as np
import pytest

from app.services.rag import mmr_stage
from app.services.rag.mmr_stage import diversify_with_mmr


def _pool():
    chunks = ["guide synthetic", "near duplicate one", "near duplicate two", "distinct topic"]
    scores = [1.0, 0.9, 0.85, 0.5]
    metadatas = [
        {"source_type": "knowledge_guide"},
        {"document_filename": "a.pdf", "cross_encoder_score": 0.9},
        {"document_filename": "a2.pdf", "cross_encoder_score": 0.85},
        {"document_filename": "b.pdf", "cross_encoder_score": 0.5},
    ]
    return chunks, scores, metadatas


def _exempt(meta):
    return str(meta.get("source_type") or "") == "knowledge_guide"


def _fake_embeddings(near_dup_sim: float = 0.99):
    # near-duplicates almost colinear, distinct chunk orthogonal
    base = np.array([1.0, 0.0, 0.0])
    dup = np.array([near_dup_sim, np.sqrt(max(0.0, 1 - near_dup_sim**2)), 0.0])
    distinct = np.array([0.0, 0.0, 1.0])
    return np.stack([base, dup, distinct]).astype(np.float32)


@pytest.mark.asyncio
async def test_disabled_flag_skips(monkeypatch):
    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_enabled", False)
    chunks, scores, metadatas = _pool()
    out, _, _, diag = await diversify_with_mmr(
        chunks, scores, metadatas, query="q", latency_profile="balanced", limit=3
    )
    assert out == chunks
    assert diag["mmr_status"] == "disabled"


@pytest.mark.asyncio
async def test_fast_profile_never_runs(monkeypatch):
    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_enabled", True)
    chunks, scores, metadatas = _pool()
    _, _, _, diag = await diversify_with_mmr(
        chunks, scores, metadatas, query="q", latency_profile="fast", limit=3
    )
    assert diag["mmr_status"] == "skipped_fast"


@pytest.mark.asyncio
async def test_exact_match_query_skips(monkeypatch):
    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_enabled", True)
    monkeypatch.setattr(mmr_stage, "_query_requires_exact_match", lambda _q: True)
    chunks, scores, metadatas = _pool()
    _, _, _, diag = await diversify_with_mmr(
        chunks, scores, metadatas, query="réf KD724", latency_profile="balanced", limit=3
    )
    assert diag["mmr_status"] == "skipped_exact_match"


@pytest.mark.asyncio
async def test_mmr_promotes_distinct_chunk_over_near_duplicate(monkeypatch):
    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_enabled", True)
    monkeypatch.setattr(mmr_stage, "_query_requires_exact_match", lambda _q: False)

    async def fake_embed(texts):
        assert len(texts) == 3  # guide is exempt, never embedded
        return _fake_embeddings()

    monkeypatch.setattr(mmr_stage, "_embed_chunks", fake_embed)
    chunks, scores, metadatas = _pool()
    out_chunks, _, out_metas, diag = await diversify_with_mmr(
        chunks, scores, metadatas, query="quels essais ?", latency_profile="balanced", limit=2,
        is_exempt_metadata=_exempt,
    )
    assert diag["mmr_status"] == "applied"
    # Exempt guide keeps the head; the distinct topic beats the near-duplicate
    # for the second MMR slot despite its lower relevance.
    assert out_chunks[0] == "guide synthetic"
    assert out_chunks[1] == "near duplicate one"
    assert out_chunks[2] == "distinct topic"
    # Nothing dropped, only reordered.
    assert sorted(out_chunks) == sorted(chunks)
    assert len(out_metas) == len(metadatas)


@pytest.mark.asyncio
async def test_timeout_keeps_original_order(monkeypatch):
    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_enabled", True)
    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_budget_seconds", 0.05)
    monkeypatch.setattr(mmr_stage, "_query_requires_exact_match", lambda _q: False)

    async def slow_embed(texts):
        await asyncio.sleep(0.5)
        return _fake_embeddings()

    monkeypatch.setattr(mmr_stage, "_embed_chunks", slow_embed)
    chunks, scores, metadatas = _pool()
    out_chunks, _, _, diag = await diversify_with_mmr(
        chunks, scores, metadatas, query="q", latency_profile="balanced", limit=3,
        is_exempt_metadata=_exempt,
    )
    assert out_chunks == chunks
    assert diag["mmr_status"] == "timeout"


@pytest.mark.asyncio
async def test_embedding_error_keeps_original_order(monkeypatch):
    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_enabled", True)
    monkeypatch.setattr(mmr_stage, "_query_requires_exact_match", lambda _q: False)

    async def broken(texts):
        raise RuntimeError("boom")

    monkeypatch.setattr(mmr_stage, "_embed_chunks", broken)
    chunks, scores, metadatas = _pool()
    out_chunks, _, _, diag = await diversify_with_mmr(
        chunks, scores, metadatas, query="q", latency_profile="balanced", limit=3,
        is_exempt_metadata=_exempt,
    )
    assert out_chunks == chunks
    assert diag["mmr_status"] == "error"


@pytest.mark.asyncio
async def test_deep_profile_runs_without_budget(monkeypatch):
    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_enabled", True)
    monkeypatch.setattr(mmr_stage, "_query_requires_exact_match", lambda _q: False)

    async def slowish_embed(texts):
        await asyncio.sleep(0.05)
        return _fake_embeddings()

    monkeypatch.setattr(mmr_stage.settings, "rag_mmr_budget_seconds", 0.01)
    monkeypatch.setattr(mmr_stage, "_embed_chunks", slowish_embed)
    chunks, scores, metadatas = _pool()
    _, _, _, diag = await diversify_with_mmr(
        chunks, scores, metadatas, query="q", latency_profile="deep", limit=3,
        is_exempt_metadata=_exempt,
    )
    assert diag["mmr_status"] == "applied"
