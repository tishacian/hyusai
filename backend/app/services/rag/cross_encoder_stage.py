"""Budgeted cross-encoder rerank stage applied after RRF/policy fusion.

RRF scores are rank-fusion weights and per-origin scores live on different
scales (dense cosine vs BM25), so no similarity threshold can be applied
safely after fusion. The cross-encoder sigmoid score is scale-invariant in
[0, 1]: this stage reorders the fused pool by it and gates obvious noise,
under a strict latency contract:

- ``fast`` / ``oracle_fast``: never runs (profile contract).
- ``balanced`` (the chat path): top candidates only, short passages, hard
  time budget (``rag_cross_encoder_budget_seconds``); on timeout the policy
  order is kept untouched and a diagnostic is emitted.
- ``deep`` (async): a capped pool (``rag_cross_encoder_max_candidates_deep``),
  full passage length, under a generous budget
  (``rag_cross_encoder_budget_seconds_deep``, a fraction of the deep deadline);
  on timeout the policy order is kept untouched, same as balanced.

The model loads lazily in a worker thread; the first balanced request that
hits a cold model simply times out to the policy order while the load
completes in the background. A process-wide semaphore bounds concurrent
reranks so CPU saturation under load degrades to skips, not queueing.
"""
from __future__ import annotations

import asyncio
import time
import weakref
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_PASSAGE_MAX_CHARS = 2000  # safety cap before tokenizer truncation
_MIN_SURVIVORS = 3

_loop_semaphores: "weakref.WeakKeyDictionary[Any, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
_reranker_unavailable_reason: str | None = None


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _loop_semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, int(settings.rag_cross_encoder_max_concurrency)))
        _loop_semaphores[loop] = semaphore
    return semaphore


def _score_passages(query: str, passages: list[str], *, model_name: str, max_length: int) -> list[float]:
    """Blocking scoring call — runs in an executor thread."""
    from app.services.retrieval.reranker_config import RerankerConfig
    from app.services.retrieval.rerankers import make_reranker

    reranker = make_reranker(RerankerConfig(model_name=model_name, max_length=max_length))
    return reranker.score(query, passages)


def preload_cross_encoder() -> None:
    """Optional startup warm-up (rag_cross_encoder_preload)."""
    try:
        _score_passages(
            "warmup",
            ["warmup"],
            model_name=settings.rag_cross_encoder_model_balanced,
            max_length=64,
        )
        logger.info("Cross-encoder preloaded", model=settings.rag_cross_encoder_model_balanced)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cross-encoder preload failed", error=str(exc))


async def rerank_with_cross_encoder(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    query: str,
    latency_profile: str | None,
    allow_cross_encoder: bool,
    top_k: int,
    is_exempt_metadata=None,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Rerank the fused candidate pool; never degrade below the policy order.

    Returns the (possibly reordered/gated) aligned lists plus diagnostics
    (``cross_encoder_status``: applied | timeout | error | skipped_* …).
    Synthetic evidence (guides, exact table facts — identified by
    ``is_exempt_metadata``) keeps its position at the head and is never
    scored or dropped.
    """
    global _reranker_unavailable_reason

    def _diag(status: str, **extra: Any) -> dict[str, Any]:
        return {"cross_encoder_status": status, **extra}

    profile = str(latency_profile or "").strip().lower()
    if not settings.rag_cross_encoder_enabled:
        return chunks, scores, metadatas, _diag("disabled")
    if not allow_cross_encoder:
        return chunks, scores, metadatas, _diag("skipped_profile")
    if profile not in {"balanced", "deep"}:
        return chunks, scores, metadatas, _diag("skipped_fast")
    if _reranker_unavailable_reason:
        return chunks, scores, metadatas, _diag("unavailable", cross_encoder_error=_reranker_unavailable_reason)
    if not chunks or not str(query or "").strip():
        return chunks, scores, metadatas, _diag("skipped_empty")

    if profile == "deep":
        model_name = settings.rag_cross_encoder_model_deep
        max_length = max(64, int(settings.rag_cross_encoder_max_length_deep))
        budget_seconds: float | None = max(0.05, float(settings.rag_cross_encoder_budget_seconds_deep))
        pool = min(len(chunks), max(1, int(settings.rag_cross_encoder_max_candidates_deep)))
    else:
        model_name = settings.rag_cross_encoder_model_balanced
        max_length = max(64, int(settings.rag_cross_encoder_max_length_balanced))
        budget_seconds = max(0.05, float(settings.rag_cross_encoder_budget_seconds))
        pool = max(1, int(settings.rag_cross_encoder_max_candidates))

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
    if not candidate_idx:
        return chunks, scores, metadatas, _diag("skipped_no_candidates")

    passages = [str(chunks[i] or "")[:_PASSAGE_MAX_CHARS] for i in candidate_idx]
    started = time.perf_counter()
    semaphore = _semaphore()
    if semaphore.locked():
        # Concurrency cap hit: skipping is cheaper and safer than queueing
        # rerank work behind other requests on the chat path.
        return chunks, scores, metadatas, _diag("skipped_concurrency")
    async with semaphore:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            None,
            lambda: _score_passages(query, passages, model_name=model_name, max_length=max_length),
        )
        try:
            if budget_seconds is not None:
                ce_scores = await asyncio.wait_for(asyncio.shield(future), timeout=budget_seconds)
            else:
                ce_scores = await future
        except (TimeoutError, asyncio.TimeoutError):
            # The thread keeps loading/scoring in the background, so the next
            # request usually hits a warm model. Keep the policy order now.
            return chunks, scores, metadatas, _diag(
                "timeout",
                cross_encoder_budget_seconds=budget_seconds,
                cross_encoder_model=model_name,
            )
        except ImportError as exc:
            _reranker_unavailable_reason = str(exc)
            logger.warning("Cross-encoder unavailable", error=str(exc))
            return chunks, scores, metadatas, _diag("unavailable", cross_encoder_error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cross-encoder rerank failed", error=str(exc))
            return chunks, scores, metadatas, _diag("error", cross_encoder_error=str(exc))

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if len(ce_scores) != len(candidate_idx):
        return chunks, scores, metadatas, _diag("error", cross_encoder_error="score_alignment_mismatch")

    threshold = max(0.0, min(1.0, float(settings.rag_cross_encoder_threshold)))
    ranked = sorted(zip(candidate_idx, ce_scores), key=lambda item: item[1], reverse=True)
    min_survivors = min(max(1, int(top_k or 0) or _MIN_SURVIVORS), _MIN_SURVIVORS, len(ranked))
    survivors = [(i, s) for i, s in ranked if s >= threshold]
    if len(survivors) < min_survivors:
        survivors = ranked[:min_survivors]
    dropped = len(ranked) - len(survivors)

    ordered_idx = head_idx + [i for i, _ in survivors] + tail_idx
    new_chunks: list[str] = []
    new_scores: list[float] = []
    new_metadatas: list[dict[str, Any]] = []
    ce_by_idx = {i: float(s) for i, s in zip(candidate_idx, ce_scores)}
    for index in ordered_idx:
        metadata = dict(metadatas[index] if index < len(metadatas) else {})
        if index in ce_by_idx:
            metadata["cross_encoder_score"] = round(ce_by_idx[index], 4)
        new_chunks.append(chunks[index])
        new_scores.append(float(scores[index]) if index < len(scores) else 0.0)
        new_metadatas.append(metadata)

    return new_chunks, new_scores, new_metadatas, _diag(
        "applied",
        cross_encoder_model=model_name,
        cross_encoder_ms=elapsed_ms,
        cross_encoder_scored=len(candidate_idx),
        cross_encoder_filtered=dropped,
        cross_encoder_threshold=threshold,
    )
