"""HAH-like and C-HAH-like retrieval on top of DocumentService (strategy A).

Implements multi-pass retrieval inspired by ``src/customchain.py`` (HAH: initial search +
secondary search from fused context) and ``src/customchainmixedhah.py`` (C-HAH: parallel
query variants + fusion). Generation stays in the agent (OpenAI-compatible LLM).

See ``docs/rag-rd-papai-mapping.md`` for mapping vs legacy ``CustomLLMChain``.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Literal, Optional

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.services.rag.document_service import DocumentService

logger = get_logger(__name__)

# Tunables (keep latency bounded on large KBs)
HAH_FIRST_PASS_CAP = 15
HAH_PSEUDO_DOC_MAX_CHARS = 2000
HAH_SECOND_PASS_CAP = 20
CHAH_QUERY_TRUNC = 120
CHAH_MAX_WORDS_HEAD = 12
RRF_K = 60


@dataclass
class RetrievalPipelineResult:
    """Unified contract for ``retrieve_for_mode``."""

    chunks: List[str]
    scores: List[float]
    pipeline: Literal[
        "naive",
        "hybrid",
        "hah_backend",
        "chah_backend",
        "fallback_hybrid",
    ]
    label: str
    reason: str
    detail: str
    # Per-chunk metadata kept in lockstep with ``chunks``/``scores`` so the
    # caller can build real citations (document title, page, docmeta keywords)
    # instead of the legacy "Policy chunk N" placeholder. ``default_factory``
    # keeps back-compat for callers that only read chunks/scores.
    metadatas: List[dict] = field(default_factory=list)


def _content_key(content: str) -> str:
    h = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
    return h


def _result_content_score(r: dict[str, Any]) -> tuple[str, float]:
    content = r.get("content") or (r.get("metadata") or {}).get("content", "")
    score = float(r.get("combined_score") or r.get("score") or 0.0)
    return content.strip(), score


def _merge_rrf(result_lists: List[List[dict[str, Any]]], top_k: int) -> List[dict[str, Any]]:
    """Simple RRF merge across multiple ranked lists (same idea as hybrid fusion)."""
    agg: dict[str, float] = {}
    best_row: dict[str, dict[str, Any]] = {}
    for results in result_lists:
        for rank, r in enumerate(results):
            content, _ = _result_content_score(r)
            if not content or len(content) < 10:
                continue
            key = _content_key(content)
            contrib = 1.0 / (RRF_K + rank + 1)
            agg[key] = agg.get(key, 0.0) + contrib
            if key not in best_row:
                best_row[key] = {
                    "content": content,
                    "combined_score": float(r.get("combined_score") or r.get("score") or 0.0),
                    "metadata": r.get("metadata") or {},
                }
            # keep higher raw combined score for display
            prev = best_row[key]["combined_score"]
            cur = float(r.get("combined_score") or r.get("score") or 0.0)
            if cur > prev:
                best_row[key]["combined_score"] = cur
                best_row[key]["metadata"] = r.get("metadata") or best_row[key]["metadata"]

    ordered = sorted(agg.keys(), key=lambda k: agg[k], reverse=True)[:top_k]
    out: List[dict[str, Any]] = []
    for key in ordered:
        row = best_row[key].copy()
        row["combined_score"] = agg[key]
        row["rrf_score"] = agg[key]
        out.append(row)
    return out


def _results_to_chunks_scores(results: List[dict[str, Any]]) -> tuple[list[str], list[float]]:
    chunks: list[str] = []
    scores: list[float] = []
    for r in results:
        c, s = _result_content_score(r)
        if c:
            chunks.append(c)
            scores.append(s)
    return chunks, scores


def _results_to_chunks_scores_metas(
    results: List[dict[str, Any]],
) -> tuple[list[str], list[float], list[dict]]:
    """Same as ``_results_to_chunks_scores`` but preserves per-chunk metadata."""
    chunks: list[str] = []
    scores: list[float] = []
    metas: list[dict] = []
    for r in results:
        c, s = _result_content_score(r)
        if c:
            chunks.append(c)
            scores.append(s)
            metas.append(r.get("metadata") or {})
    return chunks, scores, metas


async def retrieve_hah_like(
    doc_svc: "DocumentService",
    query: str,
    top_k: int = 5,
) -> RetrievalPipelineResult:
    """Two-pass retrieval: query → contexts → pseudo-document → second search → RRF merge.

    Mirrors the non-trivial path in ``CustomLLMChain.invoke_async`` (initial search +
    ``search_similar_texts`` on fused filtered context), adapted to ``DocumentService.search``.
    """
    q = (query or "").strip()
    if not q:
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="hah_backend",
            label="HAH (backend)",
            reason="Empty query",
            detail="No search performed",
            metadatas=[],
        )

    first_k = min(max(top_k * 2, top_k), HAH_FIRST_PASS_CAP)
    pass1 = await doc_svc.search(q, top_k=first_k, use_hybrid=True)
    if not pass1:
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="hah_backend",
            label="HAH (backend)",
            reason="First pass returned no chunks",
            detail="Pass1: hybrid search",
            metadatas=[],
        )

    parts: list[str] = []
    for r in pass1[:8]:
        c, _ = _result_content_score(r)
        if c:
            parts.append(c)
    pseudo = ". ".join(parts)[:HAH_PSEUDO_DOC_MAX_CHARS]
    pass2 = await doc_svc.search(pseudo, top_k=min(HAH_SECOND_PASS_CAP, first_k + 8), use_hybrid=True)

    merged = _merge_rrf([pass1, pass2] if pass2 else [pass1], top_k=top_k)
    chunks, scores, metas = _results_to_chunks_scores_metas(merged)
    detail = (
        f"Pass1: hybrid top_{first_k}; pseudo-doc ~{len(pseudo)} chars; "
        f"Pass2: hybrid top_{min(HAH_SECOND_PASS_CAP, first_k + 8)}; RRF merge → {len(chunks)} chunks"
    )
    logger.info("HAH-like retrieval complete", pass1=len(pass1), pass2=len(pass2), merged=len(chunks))
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline="hah_backend",
        label="HAH (backend)",
        reason="Two-pass hybrid retrieval + RRF merge (aligned with customchain invoke_async pattern)",
        detail=detail,
        metadatas=metas,
    )


def _query_variants(question: str) -> list[str]:
    q = question.strip()
    variants = [q]
    if len(q) > CHAH_QUERY_TRUNC:
        variants.append(q[:CHAH_QUERY_TRUNC].rsplit(" ", 1)[0].strip() or q[:CHAH_QUERY_TRUNC])
    words = re.split(r"\s+", q)
    if len(words) > 5:
        variants.append(" ".join(words[:CHAH_MAX_WORDS_HEAD]))
    # dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


async def retrieve_chah_like(
    doc_svc: "DocumentService",
    query: str,
    top_k: int = 5,
) -> RetrievalPipelineResult:
    """Parallel retrieval over query variants + RRF merge (C-HAH-like).

    Inspired by composite / multi-strategy retrieval in ``customchainmixedhah`` (parallel
    plans + fusion), without importing ``src``.
    """
    q = (query or "").strip()
    if not q:
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="chah_backend",
            label="C-HAH (backend)",
            reason="Empty query",
            detail="No search performed",
            metadatas=[],
        )

    variants = _query_variants(q)
    searches = [doc_svc.search(v, top_k=min(12, top_k + 7), use_hybrid=True) for v in variants]
    lists = await asyncio.gather(*searches)
    merged = _merge_rrf(list(lists), top_k=top_k)
    chunks, scores, metas = _results_to_chunks_scores_metas(merged)
    v_preview = repr(variants)[:200]
    detail = (
        f"Parallel hybrid searches: {len(variants)} query variant(s); "
        f"RRF merge → {len(chunks)} chunks. Variants: {v_preview}"
    )
    logger.info("C-HAH-like retrieval complete", variants=len(variants), merged=len(chunks))
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline="chah_backend",
        label="C-HAH (backend)",
        reason="Parallel hybrid retrieval over query variants + RRF merge",
        detail=detail,
        metadatas=metas,
    )


def _normalize_mode(mode: Optional[str]) -> str:
    return (mode or "auto").strip().lower()


async def retrieve_for_mode(
    doc_svc: Optional["DocumentService"],
    query: str,
    mode: Optional[str],
    *,
    top_k: int = 5,
    use_hybrid: bool = True,
    hah_chah_enabled: bool = True,
) -> RetrievalPipelineResult:
    """
    Single entry for RAG retrieval by pipeline mode.

    - ``hah`` / ``chah`` : dedicated backend pipelines when ``hah_chah_enabled``.
    - Otherwise: single ``DocumentService.search`` (naive vs hybrid via ``use_hybrid``).
    """
    if doc_svc is None:
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="fallback_hybrid",
            label="none",
            reason="DocumentService unavailable",
            detail="RAG disabled",
            metadatas=[],
        )

    m = _normalize_mode(mode)

    if hah_chah_enabled and m in ("hah", "hah_rag", "hah rag"):
        return await retrieve_hah_like(doc_svc, query, top_k=top_k)
    if hah_chah_enabled and m in ("chah", "c-hah", "c_hah", "hahcomposite", "hah_composite"):
        return await retrieve_chah_like(doc_svc, query, top_k=top_k)

    results = await doc_svc.search(query, top_k=top_k, use_hybrid=use_hybrid)
    chunks, scores, metas = _results_to_chunks_scores_metas(results)
    pipe: Literal["naive", "hybrid"] = "hybrid" if use_hybrid else "naive"
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline=pipe,
        label="vector_only" if not use_hybrid else "hybrid_rrf",
        reason="Standard DocumentService.search",
        detail=f"use_hybrid={use_hybrid} top_k={top_k}",
        metadatas=metas,
    )
