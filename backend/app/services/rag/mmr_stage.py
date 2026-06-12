"""Budgeted embedding-aware MMR diversification (RAGGER Eq. 16).

Replaces the per-document round-robin with true Maximal Marginal Relevance:
``MMR(d) = λ·rel(d) − (1−λ)·max_{d'∈S} sim(d, d')`` where the redundancy term
uses chunk embeddings. Contract mirrors ``_diversify_aligned_by_document``:
the stage REORDERS (diverse picks first, remainder after) and never drops.

Latency contract (same shape as cross_encoder_stage):
- ``fast``: never runs — callers fall back to the round-robin.
- ``balanced``: pool capped at ``rag_mmr_max_candidates``, embeddings computed
  under ``rag_mmr_budget_seconds`` (timeout → round-robin order untouched).
- ``deep``: full pool, no budget.

Two domain guards:
- exempt evidence (guides, table facts, exact hits — ``is_exempt_metadata``)
  keeps its position at the head and is never scored;
- exact-reference queries ("réf KD724") skip MMR entirely: diversifying an
  exact lookup is counter-productive.

Relevance term: ``cross_encoder_score`` when the CE stage ran (better and
free), else the aligned scores min-max normalised. Embeddings only feed the
redundancy term.
"""
from __future__ import annotations

import asyncio
import time
import weakref
from typing import Any, Callable

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_CHUNK_EMBED_MAX_CHARS = 1200

_loop_semaphores: "weakref.WeakKeyDictionary[Any, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _loop_semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(2)
        _loop_semaphores[loop] = semaphore
    return semaphore


async def _embed_chunks(texts: list[str]) -> np.ndarray:
    from app.services.embedding.embedder import get_shared_embedder

    return await get_shared_embedder().embed_batch(
        [str(text or "")[:_CHUNK_EMBED_MAX_CHARS] for text in texts]
    )


def _relevance_scores(
    candidate_idx: list[int],
    scores: list[float],
    metadatas: list[dict[str, Any]],
) -> list[float]:
    ce_scores: list[float | None] = []
    for index in candidate_idx:
        metadata = metadatas[index] if index < len(metadatas) else {}
        raw = (metadata or {}).get("cross_encoder_score")
        try:
            ce_scores.append(float(raw) if raw is not None else None)
        except (TypeError, ValueError):
            ce_scores.append(None)
    if all(value is not None for value in ce_scores) and ce_scores:
        return [float(value) for value in ce_scores]  # type: ignore[arg-type]
    # Fallback: min-max normalise the aligned (fusion) scores — their absolute
    # scale is meaningless but their order is the policy/CE order.
    raw_scores = [float(scores[i]) if i < len(scores) else 0.0 for i in candidate_idx]
    low, high = min(raw_scores), max(raw_scores)
    if high <= low:
        return [1.0 - rank / max(1, len(raw_scores)) for rank in range(len(raw_scores))]
    return [(value - low) / (high - low) for value in raw_scores]


def _mmr_order(relevance: list[float], embeddings: np.ndarray, *, lam: float, target: int) -> list[int]:
    """Greedy MMR over candidate positions; returns positions in pick order."""
    count = len(relevance)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = embeddings / norms
    sims = unit @ unit.T
    remaining = list(range(count))
    picked: list[int] = []
    while remaining and len(picked) < target:
        best_pos = None
        best_score = -np.inf
        for pos in remaining:
            redundancy = max((float(sims[pos][p]) for p in picked), default=0.0)
            score = lam * relevance[pos] - (1.0 - lam) * redundancy
            if score > best_score:
                best_score = score
                best_pos = pos
        picked.append(best_pos)  # type: ignore[arg-type]
        remaining.remove(best_pos)  # type: ignore[arg-type]
    return picked


def _query_requires_exact_match(query: str) -> bool:
    try:
        from app.services.rag.lexical_retrieval import analyze_query

        return bool(analyze_query(query or "").requires_exact_match)
    except Exception:  # noqa: BLE001
        return False


async def diversify_with_mmr(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    query: str,
    latency_profile: str | None,
    limit: int,
    is_exempt_metadata: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    def _diag(status: str, **extra: Any) -> dict[str, Any]:
        return {"mmr_status": status, **extra}

    profile = str(latency_profile or "").strip().lower()
    if not settings.rag_mmr_enabled:
        return chunks, scores, metadatas, _diag("disabled")
    if profile not in {"balanced", "deep"}:
        return chunks, scores, metadatas, _diag("skipped_fast")
    if not chunks or len(chunks) <= 2:
        return chunks, scores, metadatas, _diag("skipped_empty")
    if _query_requires_exact_match(query):
        return chunks, scores, metadatas, _diag("skipped_exact_match")

    pool = len(chunks) if profile == "deep" else max(2, int(settings.rag_mmr_max_candidates))
    budget_seconds = None if profile == "deep" else max(0.05, float(settings.rag_mmr_budget_seconds))
    exempt = is_exempt_metadata or (lambda _meta: False)

    head_idx: list[int] = []
    candidate_idx: list[int] = []
    for index in range(min(pool, len(chunks))):
        metadata = metadatas[index] if index < len(metadatas) else {}
        if exempt(metadata or {}):
            head_idx.append(index)
        else:
            candidate_idx.append(index)
    tail_idx = list(range(min(pool, len(chunks)), len(chunks)))
    if len(candidate_idx) <= 2:
        return chunks, scores, metadatas, _diag("skipped_no_candidates")

    started = time.perf_counter()
    async with _semaphore():
        future = _embed_chunks([chunks[i] for i in candidate_idx])
        try:
            if budget_seconds is not None:
                embeddings = await asyncio.wait_for(asyncio.shield(asyncio.ensure_future(future)), budget_seconds)
            else:
                embeddings = await future
        except (TimeoutError, asyncio.TimeoutError):
            return chunks, scores, metadatas, _diag(
                "timeout", mmr_budget_seconds=budget_seconds
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MMR embedding failed", error=str(exc))
            return chunks, scores, metadatas, _diag("error", mmr_error=str(exc))

    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.shape[0] != len(candidate_idx):
        return chunks, scores, metadatas, _diag("error", mmr_error="embedding_alignment_mismatch")

    lam = max(0.0, min(1.0, float(settings.rag_mmr_lambda)))
    relevance = _relevance_scores(candidate_idx, scores, metadatas)
    target = min(max(1, int(limit or 1)), len(candidate_idx))
    picked_positions = _mmr_order(relevance, embeddings, lam=lam, target=target)
    picked_idx = [candidate_idx[pos] for pos in picked_positions]
    picked_set = set(picked_idx)
    rest_idx = [i for i in candidate_idx if i not in picked_set]

    ordered = [*head_idx, *picked_idx, *rest_idx, *tail_idx]
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return (
        [chunks[i] for i in ordered],
        [scores[i] if i < len(scores) else 0.0 for i in ordered],
        [metadatas[i] if i < len(metadatas) else {} for i in ordered],
        _diag(
            "applied",
            mmr_ms=elapsed_ms,
            mmr_lambda=lam,
            mmr_pool=len(candidate_idx),
            mmr_selected=len(picked_idx),
        ),
    )
