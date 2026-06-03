"""Resolve retrieval profile (dense vs sparse+dense RRF) from R&D modes and heuristics.

When ``rag_hah_chah_enabled`` is True (settings), modes ``hah`` / ``chah`` are executed by
``pipeline_retrieval.retrieve_for_mode`` (backend strategy A). Legacy full ``CustomLLMChain``
still lives under ``src/`` (Streamlit).

The FastAPI demo maps:
- ``naive``     -> dense vector retrieval only (closest to "Naive RAG" in-service).
- ``hybrid``    -> sparse + dense retrieval with RRF when policy allows it.
- ``auto``      -> choose based on index size and query length.
- ``hah``/``chah`` -> dedicated pipelines when enabled; else hybrid fallback with explicit reason.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from app.core.config import settings

if TYPE_CHECKING:
    from app.services.rag.document_service import DocumentService


async def resolve_retrieval_mode(
    doc_svc: Optional["DocumentService"],
    query: str,
    mode: Optional[str],
    latency_profile: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """
    Returns:
        use_hybrid: whether to pass use_hybrid=True to DocumentService.search
        label: short UI label for decision steps
        reason: human-readable explanation
    """
    m = (mode or "auto").strip().lower()
    profile = (latency_profile or "").strip().lower()
    kb = 0
    count_unknown = False
    if doc_svc is not None:
        try:
            kb = await doc_svc.get_document_count()
        except Exception:
            count_unknown = True
            kb = 0
    dense = kb > int(settings.rag_dense_chunk_threshold)
    guarded_modes = {
        "auto",
        "hybrid",
        "rrf",
        "full",
        "hah",
        "hah_rag",
        "hah rag",
        "chah",
        "c-hah",
        "c_hah",
        "hahcomposite",
        "hah_composite",
    }
    if profile != "deep" and count_unknown and m in guarded_modes:
        return (
            False,
            "vector_only_count_unknown",
            "Vector count unavailable: interactive retrieval is bounded dense/vector-only to avoid sparse fan-out.",
        )
    if profile != "deep" and dense and m in guarded_modes:
        return (
            False,
            "fast_scoped_dense",
            f"Dense corpus policy: interactive retrieval is bounded dense/vector-only (index ~{kb} vectors).",
        )

    if m in ("hah", "hah_rag", "hah rag"):
        if settings.rag_hah_chah_enabled:
            return (
                True,
                "hah_backend",
                "HAH backend pipeline: layered, budget-aware retrieval + RRF merge (see pipeline_retrieval).",
            )
        return (
            True,
            "hybrid_rrf (HAH fallback)",
            "HAH backend disabled (RAG_HAH_CHAH_ENABLED=false); using sparse+dense RRF.",
        )
    if m in ("chah", "c-hah", "c_hah", "hahcomposite", "hah_composite"):
        if settings.rag_hah_chah_enabled:
            return (
                True,
                "chah_backend",
                "C-HAH backend pipeline: budgeted query variants over scoped layers + RRF merge.",
            )
        return (
            True,
            "hybrid_rrf (C-HAH fallback)",
            "C-HAH backend disabled (RAG_HAH_CHAH_ENABLED=false); using sparse+dense RRF.",
        )
    if m in ("naive", "naive_rag", "vector", "dense"):
        return (
            False,
            "vector_only",
            "Naive RAG (demo): dense vector retrieval only, no sparse/RRF.",
        )
    if m in ("hybrid", "rrf", "full"):
        return (
            True,
            "hybrid_rrf",
            "Hybrid retrieval: sparse + dense with RRF fusion.",
        )

    # auto
    q = query or ""
    q_len = len(q.strip())
    # Small corpus: dense-only often sufficient; cheaper and stable
    if kb > 0 and kb < 400 and q_len < 600:
        return (
            False,
            "vector_only (auto)",
            f"Auto: small index (~{kb} vectors) and moderate query length → vector-only.",
        )
    # Long query: lexical signal helps
    if q_len > 500:
        return (
            True,
            "hybrid_rrf (auto)",
            "Auto: long query -> enable sparse+dense RRF for lexical coverage.",
        )
    # Default
    return (
        True,
        "hybrid_rrf (auto)",
        f"Auto: default hybrid for recall (index ~{kb} vectors).",
    )
