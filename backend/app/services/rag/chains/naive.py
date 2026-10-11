"""Naive RAG chain — single-pass vector retrieval + LLM answer.

Matches the legacy `src/customchain_naive.py` behaviour at the feature
level (no multi-pass, no query rewriting, no rerank). Implementation
simply forces `rag_pipeline_mode='naive'` + `use_hybrid=False` on the
retrieval side.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.rag.rag_service import answer as _answer


async def answer_naive(
    query: str,
    context_id: Optional[str] = None,
    *,
    top_k: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run the naive chain — plain vector similarity, single pass."""
    result = await _answer(
        query=query,
        context_id=context_id,
        rag_mode_override="naive",
        top_k=top_k,
        **kwargs,
    )
    meta = result.setdefault("meta", {})
    meta["chain"] = "naive"
    return result
