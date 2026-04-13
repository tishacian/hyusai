"""Unit tests for HAH/C-HAH-like pipeline retrieval (mocked DocumentService)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.pipeline_retrieval import (
    _merge_rrf,
    _query_variants,
    retrieve_chah_like,
    retrieve_for_mode,
    retrieve_hah_like,
)


def _mk_result(content: str, score: float, rank: int = 0) -> dict:
    return {
        "content": content,
        "combined_score": score,
        "score": score,
        "metadata": {},
        "id": f"id-{rank}",
    }


def test_merge_rrf_dedupes_and_orders():
    a = [
        _mk_result("chunk a unique longer text", 0.9, 0),
        _mk_result("chunk b longer text here", 0.5, 1),
    ]
    b = [
        _mk_result("chunk a unique longer text", 0.4, 0),
        _mk_result("chunk c longer text here ok", 0.8, 1),
    ]
    merged = _merge_rrf([a, b], top_k=3)
    assert len(merged) == 3
    contents = [m["content"] for m in merged]
    assert "chunk a unique longer text" in contents
    assert "chunk b longer text here" in contents
    assert "chunk c longer text here ok" in contents


def test_query_variants_short_query():
    assert _query_variants("hello") == ["hello"]


def test_query_variants_long_splits():
    long_q = "word " * 20
    v = _query_variants(long_q)
    assert len(v) >= 2
    assert v[0] == long_q.strip()


@pytest.mark.asyncio
async def test_retrieve_hah_like_two_passes():
    doc = MagicMock()
    pass1 = [_mk_result("first pass context about policy", 0.8, 0)]
    pass2 = [_mk_result("second pass refinement", 0.7, 0)]
    doc.search = AsyncMock(side_effect=[pass1, pass2])

    out = await retrieve_hah_like(doc, "What is the policy?", top_k=2)
    assert out.pipeline == "hah_backend"
    assert doc.search.await_count == 2
    assert len(out.chunks) >= 1


@pytest.mark.asyncio
async def test_retrieve_chah_like_parallel():
    doc = MagicMock()
    r1 = [_mk_result("alpha chunk content long enough for merge", 0.9, 0)]
    # parallel: one call per variant — mock returns same for simplicity
    doc.search = AsyncMock(return_value=r1)

    out = await retrieve_chah_like(doc, "What are the requirements for deployment?", top_k=3)
    assert out.pipeline == "chah_backend"
    assert doc.search.called
    assert len(out.chunks) >= 1


@pytest.mark.asyncio
async def test_retrieve_for_mode_hah_disabled_falls_back():
    doc = MagicMock()
    doc.search = AsyncMock(return_value=[_mk_result("x", 0.5, 0)])

    out = await retrieve_for_mode(
        doc,
        "q",
        "hah",
        top_k=3,
        use_hybrid=True,
        hah_chah_enabled=False,
    )
    assert out.pipeline == "hybrid"
    doc.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_for_mode_naive():
    doc = MagicMock()
    doc.search = AsyncMock(return_value=[_mk_result("n", 0.3, 0)])

    out = await retrieve_for_mode(
        doc,
        "q",
        "naive",
        top_k=2,
        use_hybrid=False,
        hah_chah_enabled=True,
    )
    assert out.pipeline == "naive"
    doc.search.assert_awaited_once_with("q", top_k=2, use_hybrid=False)
