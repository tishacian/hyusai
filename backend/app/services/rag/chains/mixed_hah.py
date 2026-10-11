"""Composite HAH (C-HAH) RAG chain — parallel query variants + RRF fusion.

Feature-equivalent of `src/customchainmixedhah.py`: parallel multi-
strategy retrieval that runs several query rephrasings concurrently
and merges their hits via RRF before answering. Selects
`rag_pipeline_mode='chah'` in the retrieval pipeline.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.rag.rag_service import answer as _answer


async def answer_mixed_hah(
    query: str,
    context_id: Optional[str] = None,
    *,
    top_k: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run the composite HAH (mixed) chain — parallel variants + fusion."""
    result = await _answer(
        query=query,
        context_id=context_id,
        rag_mode_override="chah",
        top_k=top_k,
        **kwargs,
    )
    meta = result.setdefault("meta", {})
    meta["chain"] = "mixed_hah"
    return result
