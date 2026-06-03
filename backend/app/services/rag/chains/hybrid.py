"""Hybrid RAG chain — sparse + dense retrieval fused with RRF.

Feature-equivalent of the main branch of `src/customchain.py` + the
"HAH rag" pipeline it ships: two-pass layered retrieval with RRF-style
fusion. Under the hood this selects `rag_pipeline_mode='hah'` in the
retrieval pipeline (HAH = Hybrid Answer Harvesting).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.rag.rag_service import answer as _answer


async def answer_hybrid(
    query: str,
    context_id: Optional[str] = None,
    *,
    top_k: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run the hybrid chain — two-pass HAH retrieval + LLM answer."""
    result = await _answer(
        query=query,
        context_id=context_id,
        rag_mode_override="hah",
        top_k=top_k,
        **kwargs,
    )
    meta = result.setdefault("meta", {})
    meta["chain"] = "hybrid"
    return result
