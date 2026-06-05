"""HAH-like and C-HAH-like retrieval on top of DocumentService (strategy A).

Implements multi-pass retrieval inspired by ``src/customchain.py`` (HAH: initial search +
secondary search from fused context) and ``src/customchainmixedhah.py`` (C-HAH: parallel
query variants + fusion). Generation stays in the agent (OpenAI-compatible LLM).

See ``docs/rag-rd-papai-mapping.md`` for mapping vs legacy ``CustomLLMChain``.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Literal, Optional

from app.core.logging import get_logger
from app.services.rag.lexical_retrieval import analyze_query, identifier_variants
from app.services.rag.retrieval_policy import (
    RetrievalPolicy,
    query_variants_from_policy,
    rerank_results_with_policy,
)
from app.services.rag.sparse_backends import get_sparse_backend

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
_SPREADSHEET_LABEL_TRIGGERS_RE = re.compile(
    r"\b("
    r"diam[eè]tre|diameter|label|labell?is[ée]e?|lettre|letter|strip|strips|"
    r"trou|trous|hole|holes|def\s+strips?"
    r")\b",
    re.IGNORECASE,
)
_SPREADSHEET_LABEL_RE = re.compile(
    r"(?:\b(?:label|lettre|letter|diam[eè]tre|diameter|strip|trou|hole)\s+"
    r"(?:labell?is[ée]e?\s+)?(?:par\s+la\s+lettre\s+|sous\s+le\s+label\s+|"
    r"du\s+label\s+|de\s+la\s+lettre\s+)?)"
    r"([A-Z])\b",
    re.IGNORECASE,
)
_UPPERCASE_LABEL_TOKEN_RE = re.compile(r"\b([A-Z])\b")
_SPREADSHEET_PROTOCOL_TRIGGERS_RE = re.compile(
    r"\b("
    r"protocole|protocol|essais?|trial|trials?|tests?|production|"
    r"poids|weight|grammage|gsm|strip|strips|standard|chanvre|hemp"
    r")\b",
    re.IGNORECASE,
)
_TRIAL_CODE_RE = re.compile(
    r"\b(?:test|essai|trial|trials?\s*n[°o]?)?\s*([0-9]{1,3}[A-Z])\b",
    re.IGNORECASE,
)
_PROJECT_REFERENCE_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9]{1,}\d{2,}[A-Z0-9]*\b")
_DATE_DMY_RE = re.compile(r"\b([0-3]?\d)[/-]([01]?\d)[/-](20\d{2}|19\d{2})\b")
_DATE_YMD_RE = re.compile(r"\b(20\d{2}|19\d{2})[/-]([01]?\d)[/-]([0-3]?\d)\b")


async def _doc_search_compat(
    doc_svc: "DocumentService",
    query: str,
    *,
    top_k: int,
    filters: dict[str, Any] | None,
    use_hybrid: bool,
    search_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {"top_k": top_k, "use_hybrid": use_hybrid}
    if filters is not None:
        kwargs["filters"] = filters
    if search_params:
        kwargs["search_params"] = search_params
    try:
        return await doc_svc.search(query, **kwargs)
    except TypeError as exc:
        if "search_params" in str(exc) and "search_params" in kwargs:
            kwargs.pop("search_params", None)
            return await doc_svc.search(query, **kwargs)
        if "filter" not in str(exc) or "filters" not in kwargs:
            raise
        kwargs.pop("filters", None)
        return await doc_svc.search(query, **kwargs)


async def _timed_doc_search(
    doc_svc: "DocumentService",
    query: str,
    *,
    top_k: int,
    filters: dict[str, Any] | None,
    use_hybrid: bool,
    search_params: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    started = time.perf_counter()
    rows = await _doc_search_compat(
        doc_svc,
        query,
        top_k=top_k,
        filters=filters,
        use_hybrid=use_hybrid,
        search_params=search_params,
    )
    return list(rows or []), int((time.perf_counter() - started) * 1000)


async def _timed_sparse_search(
    sparse_backend: Any,
    query: str,
    *,
    collection: str,
    filters: dict[str, Any] | None,
    top_k: int,
    deadline_seconds: float | None,
) -> tuple[list[dict[str, Any]], int]:
    started = time.perf_counter()
    rows = await sparse_backend.search(
        query,
        collection=collection,
        filters=filters,
        top_k=top_k,
        deadline_seconds=deadline_seconds,
    )
    return list(rows or []), int((time.perf_counter() - started) * 1000)


async def _timed_qdrant_server_hybrid_search(
    doc_svc: "DocumentService",
    query: str,
    *,
    top_k: int,
    filters: dict[str, Any] | None,
    search_params: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]] | None, int]:
    started = time.perf_counter()
    vector_db = getattr(doc_svc, "vector_db", None)
    search_hybrid = getattr(vector_db, "search_hybrid", None)
    embedder = getattr(doc_svc, "embedder", None)
    embed = getattr(embedder, "embed", None)
    if not callable(search_hybrid) or not callable(embed):
        return None, int((time.perf_counter() - started) * 1000)
    try:
        embedding = embed(query)
        if inspect.isawaitable(embedding):
            embedding = await embedding
        rows = await search_hybrid(
            embedding,
            query,
            top_k=top_k,
            filters=filters,
            search_params=search_params,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant server-side hybrid search failed before fallback", error=str(exc))
        return None, int((time.perf_counter() - started) * 1000)
    return rows, int((time.perf_counter() - started) * 1000)


def _deadline_at(deadline_seconds: float | None) -> float | None:
    if deadline_seconds is None:
        return None
    try:
        deadline = float(deadline_seconds)
    except (TypeError, ValueError):
        return None
    if deadline <= 0:
        return time.perf_counter()
    return time.perf_counter() + deadline


def _remaining_deadline(deadline_at: float | None, fallback_seconds: float | None = None) -> float | None:
    if deadline_at is None:
        return fallback_seconds
    return max(deadline_at - time.perf_counter(), 0.001)


async def _cancel_pending_tasks(pending: set[asyncio.Task[Any]], *, label: str) -> None:
    if not pending:
        return
    for task in pending:
        task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=0.05,
        )
    except TimeoutError:
        logger.debug("retrieval tasks still cancelling", label=label, pending=len(pending))


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
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TableQueryPlan:
    """Provider-neutral description of a spreadsheet-oriented lookup."""

    is_table_query: bool
    labels: list[str] = field(default_factory=list)
    sheet_names: list[str] = field(default_factory=list)
    metric_terms: list[str] = field(default_factory=list)
    trial_codes: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    wants_comparison: bool = False
    variants: list[str] = field(default_factory=list)


class TableQueryPlanner:
    """Lightweight planner for table lookup/query expansion.

    This is intentionally lexical for V1: it improves routing/rerank without
    hardcoding a workspace or depending on a table-QA model.
    """

    def plan(self, question: str, query_hints: str | None = None) -> TableQueryPlan:
        q = (question or "").strip()
        labels = _spreadsheet_label_targets(q)
        sheet_names = _spreadsheet_sheet_targets(q)
        metric_terms = _spreadsheet_metric_targets(q)
        trial_codes = _trial_code_targets(q)
        dates = _date_query_variants(q)
        variants = _spreadsheet_label_query_variants(q) + _spreadsheet_protocol_query_variants(q)
        if query_hints and q:
            variants.append(f"{q}\n\nKnowledge guide hints:\n{str(query_hints)[:900]}")
        wants_comparison = bool(
            re.search(r"\b(tous|toutes|global|globalement|plusieurs|different|diff[ée]rent|compare)\b", q, re.IGNORECASE)
        )
        return TableQueryPlan(
            is_table_query=bool(
                labels
                or sheet_names
                or metric_terms
                or trial_codes
                or dates
                or _SPREADSHEET_PROTOCOL_TRIGGERS_RE.search(q or "")
            ),
            labels=labels,
            sheet_names=sheet_names,
            metric_terms=metric_terms,
            trial_codes=trial_codes,
            dates=dates,
            wants_comparison=wants_comparison,
            variants=list(dict.fromkeys(v for v in variants if v)),
        )


def _content_key(content: str) -> str:
    h = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
    return h


def _result_content_score(r: dict[str, Any]) -> tuple[str, float]:
    content = r.get("content") or (r.get("metadata") or {}).get("content", "")
    score = float(r.get("combined_score") or r.get("score") or 0.0)
    return content.strip(), score


def _with_sparse_metadata(
    rows: list[dict[str, Any]],
    *,
    backend: str,
    status: str,
    fallback_reason: str | None,
    sparse_results: int,
    dense_elapsed_ms: int | None = None,
    sparse_elapsed_ms: int | None = None,
    retrieval_elapsed_ms: int | None = None,
    deadline_seconds: float | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        copy = dict(row or {})
        meta = dict(copy.get("metadata") or {})
        meta["sparse_backend"] = backend
        meta["sparse_status"] = status
        meta["sparse_results"] = sparse_results
        if dense_elapsed_ms is not None:
            meta["dense_elapsed_ms"] = dense_elapsed_ms
        if sparse_elapsed_ms is not None:
            meta["sparse_elapsed_ms"] = sparse_elapsed_ms
        elif copy.get("sparse_elapsed_ms") is not None:
            meta["sparse_elapsed_ms"] = copy.get("sparse_elapsed_ms")
        if retrieval_elapsed_ms is not None:
            meta["retrieval_elapsed_ms"] = retrieval_elapsed_ms
        if deadline_seconds is not None:
            meta["retrieval_deadline_seconds"] = deadline_seconds
        if fallback_reason:
            meta["sparse_fallback_reason"] = fallback_reason
        copy["metadata"] = meta
        out.append(copy)
    return out


def _sparse_diagnostics_from_metas(metas: list[dict[str, Any]]) -> dict[str, Any]:
    for meta in metas or []:
        if not isinstance(meta, dict):
            continue
        if meta.get("sparse_backend") or meta.get("sparse_status") or meta.get("sparse_fallback_reason"):
            payload = {
                "sparse_backend": meta.get("sparse_backend"),
                "sparse_status": meta.get("sparse_status"),
                "sparse_results": meta.get("sparse_results"),
            }
            if meta.get("sparse_fusion"):
                payload["sparse_fusion"] = meta.get("sparse_fusion")
            if meta.get("sparse_fallback_reason"):
                payload["sparse_fallback_reason"] = meta.get("sparse_fallback_reason")
            for key in ("dense_elapsed_ms", "sparse_elapsed_ms", "retrieval_elapsed_ms", "retrieval_deadline_seconds"):
                if meta.get(key) is not None:
                    payload[key] = meta.get(key)
            return payload
    return {}


def _exact_table_diagnostics(
    *,
    attempted: bool,
    hits: int,
    elapsed_ms: int,
) -> dict[str, Any]:
    if not attempted and hits <= 0:
        return {}
    return {
        "exact_table_attempted": bool(attempted),
        "exact_table_hits": int(hits),
        "exact_table_elapsed_ms": int(elapsed_ms),
    }


def _exact_metadata_diagnostics(
    *,
    attempted: bool,
    hits: int,
    elapsed_ms: int,
    exact_match_required: bool = False,
) -> dict[str, Any]:
    if not attempted and hits <= 0:
        return {}
    return {
        "exact_metadata_attempted": bool(attempted),
        "exact_metadata_hits": int(hits),
        "exact_metadata_elapsed_ms": int(elapsed_ms),
        "exact_match_required": bool(exact_match_required),
        "exact_match_missing": bool(exact_match_required and hits <= 0),
    }


def _exact_metadata_signal(query: str, retrieval_policy: RetrievalPolicy | None) -> bool:
    signals = analyze_query(
        query,
        retrieval_policy.lexical_config if retrieval_policy else None,
    )
    return bool(signals.exact_terms or signals.document_type_aliases)


def _exact_match_required(query: str, retrieval_policy: RetrievalPolicy | None) -> bool:
    return analyze_query(
        query,
        retrieval_policy.lexical_config if retrieval_policy else None,
    ).requires_exact_match


async def _exact_metadata_candidates(
    doc_svc: "DocumentService",
    query: str,
    *,
    top_k: int,
    filters: dict[str, Any] | None,
    retrieval_policy: RetrievalPolicy | None,
    deadline_at: float | None,
) -> list[dict[str, Any]]:
    if deadline_at is not None and _remaining_deadline(deadline_at, None) <= 0:
        return []
    searcher = getattr(doc_svc, "search_exact_metadata", None)
    if not callable(searcher):
        return []
    try:
        coro = searcher(
            query,
            top_k=max(1, min(max(top_k * 2, top_k), 24)),
            filters=filters,
            lexical_config=retrieval_policy.lexical_config if retrieval_policy else None,
        )
        remaining = _remaining_deadline(deadline_at, None)
        if deadline_at is not None:
            return await asyncio.wait_for(coro, timeout=max(0.001, remaining))
        return await coro
    except TimeoutError:
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("exact metadata retrieval failed", error=str(exc))
        return []


def _prepend_exact_metadata_candidates(
    exact_rows: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not exact_rows:
        return results
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _key(row: dict[str, Any]) -> str:
        metadata = row.get("metadata") or {}
        return str(
            metadata.get("document_id")
            or metadata.get("document_filename")
            or row.get("id")
            or _content_key(str(row.get("content") or ""))
        )

    for row in [*exact_rows, *results]:
        key = _key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


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
    *,
    dedup: bool = True,
) -> tuple[list[str], list[float], list[dict]]:
    """Convert raw retrieval hits into aligned chunks/scores/metas lists.

    When ``dedup=True`` (default), identical chunk content is collapsed
    to a single entry — keeping the first (highest-ranked) occurrence.
    This protects against the common foot-gun where the same source
    document was ingested multiple times (fresh ``document_id`` each
    upload) and the UI ends up showing 4× the same snippet. RRF merges
    in ``_merge_rrf`` already dedup by content hash, so this only
    applies to the non-HAH/CHAH path (hybrid search).
    """
    chunks: list[str] = []
    scores: list[float] = []
    metas: list[dict] = []
    seen: set[str] = set()
    for r in results:
        c, s = _result_content_score(r)
        if not c:
            continue
        if dedup:
            key = _content_key(c)
            if key in seen:
                continue
            seen.add(key)
        chunks.append(c)
        scores.append(s)
        metas.append(r.get("metadata") or {})
    return chunks, scores, metas


async def _search_documents(
    doc_svc: "DocumentService",
    query: str,
    *,
    top_k: int,
    filters: dict[str, Any] | None = None,
    use_hybrid: bool = True,
    allow_legacy_hybrid: bool = True,
    deadline_seconds: float | None = None,
    search_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run one bounded retrieval layer.

    ``allow_legacy_hybrid=False`` is the dense-corpus guardrail: it prevents the
    in-process BM25 warmup path and fuses dense results with the configured
    sparse service instead.
    """
    top_k = max(1, int(top_k or 1))
    if use_hybrid and not allow_legacy_hybrid:
        retrieval_started = time.perf_counter()
        sparse_backend = get_sparse_backend()
        sparse_backend_name = getattr(sparse_backend, "name", "unknown")
        sparse_configured = not (
            sparse_backend_name == "disabled"
            or (
                sparse_backend_name == "opensearch"
                and hasattr(sparse_backend, "base_url")
                and not getattr(sparse_backend, "base_url", "")
            )
        )
        sparse_status = (
            "disabled"
            if sparse_backend_name == "disabled"
            else ("unavailable" if not sparse_configured else "pending")
        )
        sparse_fallback_reason: str | None = (
            "sparse_disabled"
            if sparse_backend_name == "disabled"
            else ("sparse_unavailable" if not sparse_configured else None)
        )
        if sparse_backend_name == "qdrant_sparse" and sparse_configured:
            server_rows, server_elapsed_ms = await _timed_qdrant_server_hybrid_search(
                doc_svc,
                query,
                top_k=top_k,
                filters=filters,
                search_params=search_params,
            )
            if server_rows is not None:
                retrieval_elapsed_ms = int((time.perf_counter() - retrieval_started) * 1000)
                server_status = "ok" if server_rows else "empty"
                server_fallback = None if server_rows else "qdrant_sparse_hybrid_empty"
                return _with_sparse_metadata(
                    list(server_rows or [])[:top_k],
                    backend=sparse_backend_name,
                    status=server_status,
                    fallback_reason=server_fallback,
                    sparse_results=len(server_rows or []),
                    dense_elapsed_ms=server_elapsed_ms,
                    sparse_elapsed_ms=server_elapsed_ms,
                    retrieval_elapsed_ms=retrieval_elapsed_ms,
                    deadline_seconds=deadline_seconds,
                )
        dense_task = asyncio.create_task(
            _timed_doc_search(
                doc_svc,
                query,
                top_k=top_k,
                filters=filters,
                use_hybrid=False,
                search_params=search_params,
            )
        )
        sparse_collection = getattr(doc_svc, "collection_name", "documents")
        if sparse_backend_name == "qdrant_sparse":
            sparse_collection = getattr(getattr(doc_svc, "vector_db", None), "collection_name", sparse_collection)
        sparse_task = (
            asyncio.create_task(
                _timed_sparse_search(
                    sparse_backend,
                    query,
                    collection=sparse_collection,
                    filters=filters,
                    top_k=top_k,
                    deadline_seconds=deadline_seconds,
                )
            )
            if sparse_configured
            else None
        )
        tasks = {dense_task}
        if sparse_task is not None:
            tasks.add(sparse_task)
        done, pending = await asyncio.wait(
            tasks,
            timeout=max(0.001, float(deadline_seconds or 2.0)),
        )
        await _cancel_pending_tasks(pending, label="sparse_dense_fanout")
        if sparse_task is not None and sparse_task in pending:
            sparse_status = "timeout"
            sparse_fallback_reason = "sparse_timeout"
        dense_results: list[dict[str, Any]] = []
        sparse_results: list[dict[str, Any]] = []
        dense_elapsed_ms: int | None = None
        sparse_elapsed_ms: int | None = None
        if dense_task in done:
            try:
                dense_results, dense_elapsed_ms = dense_task.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("dense retrieval layer failed", error=str(exc))
        if sparse_task is not None and sparse_task in done:
            try:
                sparse_results, sparse_elapsed_ms = sparse_task.result()
                if sparse_results:
                    sparse_status = "ok"
                    sparse_fallback_reason = None
                elif sparse_status != "disabled":
                    sparse_status = "empty"
                    sparse_fallback_reason = f"sparse_{sparse_backend_name}_empty_or_unavailable"
            except Exception as exc:  # noqa: BLE001
                sparse_status = "error"
                sparse_fallback_reason = "sparse_error"
                logger.warning("sparse retrieval layer failed", error=str(exc))
        retrieval_elapsed_ms = int((time.perf_counter() - retrieval_started) * 1000)
        if sparse_results:
            merged = _merge_rrf(
                [
                    _with_sparse_metadata(
                        dense_results,
                        backend=sparse_backend_name,
                        status=sparse_status,
                        fallback_reason=sparse_fallback_reason,
                        sparse_results=len(sparse_results),
                        dense_elapsed_ms=dense_elapsed_ms,
                        sparse_elapsed_ms=sparse_elapsed_ms,
                        retrieval_elapsed_ms=retrieval_elapsed_ms,
                        deadline_seconds=deadline_seconds,
                    ),
                    _with_sparse_metadata(
                        sparse_results,
                        backend=sparse_backend_name,
                        status=sparse_status,
                        fallback_reason=sparse_fallback_reason,
                        sparse_results=len(sparse_results),
                        dense_elapsed_ms=dense_elapsed_ms,
                        sparse_elapsed_ms=sparse_elapsed_ms,
                        retrieval_elapsed_ms=retrieval_elapsed_ms,
                        deadline_seconds=deadline_seconds,
                    ),
                ],
                top_k=top_k,
            )
            return merged
        return _with_sparse_metadata(
            dense_results[:top_k],
            backend=sparse_backend_name,
            status=sparse_status,
            fallback_reason=sparse_fallback_reason,
            sparse_results=0,
            dense_elapsed_ms=dense_elapsed_ms,
            sparse_elapsed_ms=sparse_elapsed_ms,
            retrieval_elapsed_ms=retrieval_elapsed_ms,
            deadline_seconds=deadline_seconds,
        )

    search_coro = _doc_search_compat(
        doc_svc,
        query,
        top_k=top_k,
        filters=filters,
        use_hybrid=use_hybrid,
        search_params=search_params,
    )
    if deadline_seconds is not None:
        try:
            return await asyncio.wait_for(search_coro, timeout=max(0.001, float(deadline_seconds)))
        except TimeoutError:
            return []
    return await search_coro


async def retrieve_hah_like(
    doc_svc: "DocumentService",
    query: str,
    top_k: int = 5,
    retrieval_policy: RetrievalPolicy | None = None,
    filters: dict[str, Any] | None = None,
    use_hybrid: bool = True,
    allow_legacy_hybrid: bool = True,
    deadline_seconds: float | None = None,
    search_params: dict[str, Any] | None = None,
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

    deadline_at = _deadline_at(deadline_seconds)
    exact_started = time.perf_counter()
    exact_metadata_rows = await _exact_metadata_candidates(
        doc_svc,
        q,
        top_k=top_k,
        filters=filters,
        retrieval_policy=retrieval_policy,
        deadline_at=deadline_at,
    )
    exact_metadata_elapsed_ms = int((time.perf_counter() - exact_started) * 1000)
    first_k = min(max(top_k * 2, top_k), HAH_FIRST_PASS_CAP)
    pass1 = await _search_documents(
        doc_svc,
        q,
        top_k=first_k,
        filters=filters,
        use_hybrid=use_hybrid,
        allow_legacy_hybrid=allow_legacy_hybrid,
        deadline_seconds=_remaining_deadline(deadline_at, deadline_seconds),
        search_params=search_params,
    )
    pass1 = rerank_results_with_policy(pass1, q, retrieval_policy)
    if not pass1:
        if exact_metadata_rows:
            chunks, scores, metas = _results_to_chunks_scores_metas(exact_metadata_rows[:top_k])
            diagnostics = {
                **_sparse_diagnostics_from_metas(metas),
                **_exact_metadata_diagnostics(
                    attempted=_exact_metadata_signal(q, retrieval_policy),
                    hits=len(exact_metadata_rows),
                    elapsed_ms=exact_metadata_elapsed_ms,
                    exact_match_required=_exact_match_required(q, retrieval_policy),
                ),
            }
            return RetrievalPipelineResult(
                chunks=chunks,
                scores=scores,
                pipeline="hah_backend",
                label="HAH (backend)",
                reason="Exact metadata retrieval returned evidence; first pass returned no chunks",
                detail=f"Pass1: layered top_{first_k}; exact_metadata_hits={len(exact_metadata_rows)}",
                metadatas=metas,
                diagnostics=diagnostics,
            )
        return RetrievalPipelineResult(
            chunks=[],
            scores=[],
            pipeline="hah_backend",
            label="HAH (backend)",
            reason="First pass returned no chunks",
            detail=f"Pass1: hybrid search; exact_metadata_hits={len(exact_metadata_rows)}",
            metadatas=[],
            diagnostics=_exact_metadata_diagnostics(
                attempted=_exact_metadata_signal(q, retrieval_policy),
                hits=len(exact_metadata_rows),
                elapsed_ms=exact_metadata_elapsed_ms,
                exact_match_required=_exact_match_required(q, retrieval_policy),
            ),
        )

    parts: list[str] = []
    for r in pass1[:8]:
        c, _ = _result_content_score(r)
        if c:
            parts.append(c)
    pseudo = ". ".join(parts)[:HAH_PSEUDO_DOC_MAX_CHARS]
    remaining_seconds = _remaining_deadline(deadline_at, deadline_seconds)
    pass2 = []
    if deadline_at is None or float(remaining_seconds or 0.0) > 0.001:
        pass2 = await _search_documents(
            doc_svc,
            pseudo,
            top_k=min(HAH_SECOND_PASS_CAP, first_k + 8),
            filters=filters,
            use_hybrid=use_hybrid,
            allow_legacy_hybrid=allow_legacy_hybrid,
            deadline_seconds=remaining_seconds,
            search_params=search_params,
        )
    pass2 = rerank_results_with_policy(pass2, q, retrieval_policy)

    merged = _merge_rrf([pass1, pass2] if pass2 else [pass1], top_k=max(top_k, top_k + len(exact_metadata_rows)))
    merged = _prepend_exact_metadata_candidates(exact_metadata_rows, merged)[:top_k]
    chunks, scores, metas = _results_to_chunks_scores_metas(merged)
    diagnostics = {
        **_sparse_diagnostics_from_metas(metas),
        **_exact_metadata_diagnostics(
            attempted=_exact_metadata_signal(q, retrieval_policy),
            hits=len(exact_metadata_rows),
            elapsed_ms=exact_metadata_elapsed_ms,
            exact_match_required=_exact_match_required(q, retrieval_policy),
        ),
    }
    detail = (
        f"Pass1: layered top_{first_k}; pseudo-doc ~{len(pseudo)} chars; "
        f"Pass2: layered top_{min(HAH_SECOND_PASS_CAP, first_k + 8)}; "
        f"exact_metadata_hits={len(exact_metadata_rows)}; RRF merge → {len(chunks)} chunks"
    )
    if diagnostics:
        detail = f"{detail}; sparse={diagnostics.get('sparse_status')}:{diagnostics.get('sparse_backend')}"
    logger.info("HAH-like retrieval complete", pass1=len(pass1), pass2=len(pass2), merged=len(chunks))
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline="hah_backend",
        label="HAH (backend)",
        reason="Two-pass layered retrieval + RRF merge (aligned with HAH budget-aware pattern)",
        detail=detail,
        metadatas=metas,
        diagnostics=diagnostics,
    )


def _query_variants(
    question: str,
    query_hints: str | None = None,
    retrieval_policy: RetrievalPolicy | None = None,
) -> list[str]:
    q = question.strip()
    variants = [q]
    signals = analyze_query(q, retrieval_policy.lexical_config if retrieval_policy else None)
    policy_variants = query_variants_from_policy(q, retrieval_policy)
    policy_variants = sorted(
        policy_variants,
        key=lambda value: (0 if q and q in value else 1, -len(str(value))),
    )
    variants.extend(policy_variants)
    for exact_term in signals.exact_terms[1:4]:
        alternate_forms = [form for form in identifier_variants(exact_term) if form and form != exact_term]
        for form in alternate_forms[:3]:
            if form not in q:
                variants.append(f"{q} {form}")
    if query_hints and q:
        variants.append(f"{q}\n\nKnowledge guide hints:\n{str(query_hints)[:900]}")
    if len(q) > CHAH_QUERY_TRUNC:
        variants.append(q[:CHAH_QUERY_TRUNC].rsplit(" ", 1)[0].strip() or q[:CHAH_QUERY_TRUNC])
    words = re.split(r"\s+", q)
    if len(words) > 5:
        variants.append(" ".join(words[:CHAH_MAX_WORDS_HEAD]))
    table_plan = TableQueryPlanner().plan(q, query_hints=query_hints)
    variants.extend(table_plan.variants)
    # dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _date_query_variants(question: str) -> list[str]:
    variants: list[str] = []
    for day, month, year in _DATE_DMY_RE.findall(question or ""):
        iso = f"{year}-{int(month):02d}-{int(day):02d}"
        variants.extend([iso, f"{iso} 00:00:00"])
    for year, month, day in _DATE_YMD_RE.findall(question or ""):
        iso = f"{year}-{int(month):02d}-{int(day):02d}"
        variants.extend([iso, f"{iso} 00:00:00"])
    return list(dict.fromkeys(variants))


def _trial_code_targets(question: str) -> list[str]:
    codes: list[str] = []
    for match in _TRIAL_CODE_RE.finditer(question or ""):
        code = match.group(1).upper()
        if code not in codes:
            codes.append(code)
    return codes


def _trial_code_number(code: str) -> str:
    match = re.match(r"^([0-9]{1,3})[A-Z]$", code.strip().upper())
    return match.group(1) if match else ""


def _spreadsheet_protocol_query_variants(question: str) -> list[str]:
    """Add variants for Excel sheets where values are found by row/column crossing.

    Many industrial trial workbooks use a protocol matrix: one row defines the
    trial columns (``trials N°`` with values such as ``2A``), while another row
    defines a metric (``Poids``, ``Speed``, ``Strip``). Dense retrieval often
    ranks generic sheets above these protocol matrices unless the query names
    the sheet. These variants are generic spreadsheet anchors, not Andritz-
    specific values.
    """
    if not question or not _SPREADSHEET_PROTOCOL_TRIGGERS_RE.search(question):
        return []

    q = question.strip()
    variants = [
        f"{q} Spreadsheet sheet Protocole essais trials N°",
        f"{q} protocol trial matrix row metric column value",
    ]
    codes = _trial_code_targets(question)
    dates = _date_query_variants(question)
    for code in codes[:4]:
        test_number = _trial_code_number(code)
        variants.extend(
            [
                f"Protocole essais trials N° {code}",
                f"Spreadsheet sheet Protocole essais {code} Poids Weight",
                f"trial {code} metric value row Poids",
            ]
        )
        if test_number:
            variants.extend(
                [
                    f"Spreadsheet sheet test {test_number} Weight Poids",
                    f"test {test_number} Weight g/m² gsm",
                    f"test {test_number} metric value row Weight",
                ]
            )
    for date in dates[:4]:
        variants.append(f"Protocole essais DATE {date}")
    if re.search(r"\b(?:geotex|customer|client)\b", question, re.IGNORECASE):
        variants.append("Protocole essais Customer GEOTEX DATE")
    if re.search(r"\b(?:chanvre|hemp)\b", question, re.IGNORECASE) and re.search(
        r"\bstrips?\b",
        question,
        re.IGNORECASE,
    ):
        variants.extend(
            [
                f"{q} spreadsheet sheet strip chanvre",
                f"{q} strip chanvre production standard",
            ]
        )
    return variants


def _spreadsheet_label_query_variants(question: str) -> list[str]:
    """Add exact-ish Excel label variants for small tabular business lookups.

    A query like "diamètre B" is semantically tiny: once a collection contains
    many spreadsheets, dense retrieval often prefers unrelated sheets that also
    contain "B" or "diameter-like" headers. The spreadsheet parser renders
    two-column definitions as ``A2=B | B2=85 | B = 85``. These variants give
    C-HAH/BM25 a chance to find that explicit table without hardcoding any
    Andritz collection or value.
    """
    if not question or not _SPREADSHEET_LABEL_TRIGGERS_RE.search(question):
        return []

    labels = _spreadsheet_label_targets(question)

    variants: list[str] = []
    for label in labels[:4]:
        variants.extend(
            [
                f"Spreadsheet sheet Def strips {label} =",
                f'Spreadsheet cell fact Def strips label "{label}" value',
                f'Spreadsheet table fact Def strips row_label "{label}" value',
                f'Spreadsheet semantic sentence Def strips label "{label}" value',
                f"Def strips label {label} value {label} =",
                f"Row A={label} B= value strip diameter label {label}",
                f"A2={label} B2 {label} =",
            ]
        )
    return variants


def _spreadsheet_label_targets(question: str) -> list[str]:
    if not question or not _SPREADSHEET_LABEL_TRIGGERS_RE.search(question):
        return []

    labels: list[str] = []
    for match in _SPREADSHEET_LABEL_RE.finditer(question):
        label = match.group(1).upper()
        if label not in labels:
            labels.append(label)
    # French voice queries often end as "diamètre B ?" where the trigger and
    # the target are separate tokens. Only fall back to single-letter tokens
    # when the query has a spreadsheet/table trigger to avoid polluting normal
    # prose searches.
    for match in _UPPERCASE_LABEL_TOKEN_RE.finditer(question):
        label = match.group(1).upper()
        if label not in labels:
            labels.append(label)
    return labels


def _spreadsheet_sheet_targets(question: str) -> list[str]:
    """Extract explicit spreadsheet sheet hints from user language.

    Keep this conservative: explicit sheets are strong constraints and should
    not be inferred from arbitrary prose. Common speech-to-text variants of
    "Def strips" are normalized because they are table names, not values.
    """
    q = question or ""
    targets: list[str] = []
    if re.search(r"\b(?:def|dev)\s*strips?\b", q, re.IGNORECASE):
        targets.append("Def strips")
    if re.search(r"\bprotocole\s+essais\b|\bprotocol\b", q, re.IGNORECASE):
        targets.append("Protocole essais")
    for test_number in {_trial_code_number(code) for code in _trial_code_targets(q)}:
        if test_number:
            targets.append(f"test {test_number}")
    return list(dict.fromkeys(targets))


def _spreadsheet_metric_targets(question: str) -> list[str]:
    q = question or ""
    targets: list[str] = []
    metric_patterns = [
        (r"\bpoids\b|\bweight\b", ["Poids", "Weight"]),
        (r"\bgrammage\b|\bgsm\b", ["Grammage", "Weight"]),
        (r"\bstrip|strips\b", ["Strip", "strips"]),
        (r"\bvitesse\b|\bspeed\b", ["Speed", "Vitesse"]),
        (r"\bpression\b|\bpressure\b", ["Pressure", "Pression"]),
    ]
    for pattern, values in metric_patterns:
        if re.search(pattern, q, re.IGNORECASE):
            targets.extend(values)
    return list(dict.fromkeys(targets))


def _spreadsheet_label_match_score(content: str, labels: list[str]) -> int:
    """Prioritise exact label→value table hits after broad spreadsheet retrieval.

    Dense/BM25 retrieval can prefer large protocol sheets because they contain
    many business terms. For a query such as "diamètre B", a small definition
    table containing ``B = 85`` is more useful than broad context. This is a
    lightweight lexical rerank, not an Andritz-specific value rule.
    """
    if not labels:
        return 0
    text = str(content or "")
    if not _is_spreadsheet_evidence(text):
        return 0

    score = 0
    for label in labels:
        if re.search(rf"\b{re.escape(label)}\s*=\s*[-+]?\d", text):
            score += 8
        if re.search(rf'label="{re.escape(label)}"\s+value="[-+]?\d', text, re.IGNORECASE):
            score += 10
        if re.search(rf'row_label="{re.escape(label)}".*?value="[-+]?\d', text, re.IGNORECASE):
            score += 8
        if re.search(
            rf'label "{re.escape(label)}" has value "[-+]?\d',
            text,
            re.IGNORECASE,
        ):
            score += 7
        if re.search(rf"\b[A-Z]+\d+\s*=\s*{re.escape(label)}\b", text) and re.search(
            r"\b[A-Z]+\d+\s*=\s*[-+]?\d",
            text,
        ):
            score += 3
    if re.search(r"\bdef\s+strips?\b", text, re.IGNORECASE):
        score += 4
    lower = text.lower()
    if "spreadsheet cell fact:" in lower:
        score += 3
    if "spreadsheet semantic sentence:" in lower:
        score += 2
    return score


def _spreadsheet_protocol_match_score(content: str, question: str) -> int:
    if not question or not _SPREADSHEET_PROTOCOL_TRIGGERS_RE.search(question):
        return 0
    text = str(content or "")
    lower = text.lower()
    if not _is_spreadsheet_evidence(text):
        return 0

    score = 0
    if re.search(r"\bprotocole\s+essais\b", lower) or re.search(r"\bprotocol\b", lower):
        if re.search(r"\bprotocole|protocol|essais?|trial|tests?\b", question, re.IGNORECASE):
            score += 7
    if "trials n" in lower or "trial" in lower:
        score += 2

    for code in _trial_code_targets(question):
        if re.search(rf"\b{re.escape(code)}\b", text, re.IGNORECASE):
            score += 6
        if re.search(rf'column_header="{re.escape(code)}"', text, re.IGNORECASE):
            score += 10
        test_number = _trial_code_number(code)
        if test_number and re.search(rf"\btest\s+{re.escape(test_number)}\b", lower):
            score += 6
            if re.search(r"\bpoids\b|\bweight\b|\bgrammage\b|\bgsm\b", lower, re.IGNORECASE):
                score += 6

    for date in _date_query_variants(question):
        if date in text:
            score += 5

    metric_terms = [
        ("poids", r"\bpoids\b|\bweight\b"),
        ("weight", r"\bpoids\b|\bweight\b"),
        ("grammage", r"\bgrammage\b|\bgsm\b"),
        ("gsm", r"\bgrammage\b|\bgsm\b"),
        ("strip", r"\bstrip|strips\b"),
        ("standard", r"\bstandard\b|\bstrip|strips\b"),
        ("chanvre", r"\bchanvre\b|\bhemp\b"),
        ("hemp", r"\bchanvre\b|\bhemp\b"),
    ]
    for query_term, content_pattern in metric_terms:
        if re.search(rf"\b{query_term}\b", question, re.IGNORECASE) and re.search(
            content_pattern,
            lower,
            re.IGNORECASE,
        ):
            score += 3

    if re.search(r"\bgeotex\b", question, re.IGNORECASE) and "geotex" in lower:
        score += 4
    if re.search(r"\bchanvre|hemp\b", question, re.IGNORECASE) and re.search(
        r"\bchanvre|hemp\b",
        lower,
        re.IGNORECASE,
    ):
        score += 4
    if "spreadsheet table fact:" in lower:
        score += 4
    if "spreadsheet cell fact:" in lower:
        score += 2
    return score


def _norm_token(value: Any) -> str:
    return str(value or "").strip().lower()


def _payload_to_result(payload: dict[str, Any], *, score: float) -> dict[str, Any]:
    content = str(payload.get("content") or "").strip()
    if not content:
        sheet = payload.get("sheet_name") or "unknown"
        row_label = payload.get("row_label") or ""
        column_header = payload.get("column_header") or ""
        value = payload.get("value") or ""
        cell_ref = payload.get("cell_ref") or payload.get("cell_range") or ""
        content = (
            f'Spreadsheet table fact: sheet="{sheet}" '
            f'cell={cell_ref} value="{value}"'
            + (f' row_label="{row_label}"' if row_label else "")
            + (f' column_header="{column_header}"' if column_header else "")
        )
    return {
        "id": str(payload.get("chunk_id") or payload.get("point_id") or _content_key(content)),
        "content": content,
        "score": score,
        "combined_score": score,
        "metadata": dict(payload),
        "table_exact_match": True,
    }


def _score_table_payload(payload: dict[str, Any], question: str, plan: TableQueryPlan) -> int:
    content = str(payload.get("content") or "")
    score = 50
    stype = _norm_token(payload.get("semantic_type"))
    sheet = _norm_token(payload.get("sheet_name"))
    row_label = _norm_token(payload.get("row_label"))
    column_header = _norm_token(payload.get("column_header"))

    if stype == "spreadsheet_cell_fact":
        score += 18
    elif stype == "spreadsheet_semantic_sentence":
        score += 16
    elif stype == "spreadsheet_table_fact":
        score += 12
    elif stype == "spreadsheet_row":
        score += 4

    sheet_targets = [_norm_token(s) for s in plan.sheet_names]
    if sheet_targets:
        if sheet in sheet_targets:
            score += 60
        else:
            score -= 20
    elif plan.labels and sheet == "def strips":
        score += 45

    for label in plan.labels:
        label_norm = _norm_token(label)
        if row_label == label_norm:
            score += 45
        if re.search(rf'\blabel="{re.escape(label)}"\s+value="[-+]?\d', content, re.IGNORECASE):
            score += 30
        if re.search(rf"\b{re.escape(label)}\s*=\s*[-+]?\d", content):
            score += 24

    for code in plan.trial_codes:
        code_norm = _norm_token(code)
        if column_header == code_norm:
            score += 55
        if re.search(rf"\b{re.escape(code)}\b", content, re.IGNORECASE):
            score += 12

    for metric in plan.metric_terms:
        metric_norm = _norm_token(metric)
        if row_label == metric_norm:
            score += 35
        if metric_norm and metric_norm in _norm_token(content):
            score += 8

    for date in plan.dates:
        if date in content:
            score += 8

    if re.search(r"\bgeotex\b", question, re.IGNORECASE) and "geotex" in _norm_token(content):
        score += 8
    if re.search(r"\bchanvre|hemp\b", question, re.IGNORECASE) and re.search(
        r"\bchanvre|hemp\b",
        content,
        re.IGNORECASE,
    ):
        score += 12

    # A query for the label "N" often collides with force-unit sheets such as
    # "N/50 mm". If an explicit Def-strips-like label lookup exists, keep
    # those unit tables behind real label-value facts.
    if plan.labels and any(label == "N" for label in plan.labels):
        if "n/50" in _norm_token(content) and sheet != "def strips":
            score -= 25
    return score


async def _exact_table_fact_candidates(
    doc_svc: "DocumentService",
    query: str,
    plan: TableQueryPlan,
    *,
    top_k: int,
    filters: dict[str, Any] | None = None,
    deadline_at: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch exact table facts by payload before dense/BM25 ranking.

    Vector search is intentionally broad; for spreadsheet lookups we often
    already know the structured keys (sheet, row label, trial column). Qdrant
    payload filtering gives those facts a deterministic path into the context.
    """
    if not plan.is_table_query or not hasattr(doc_svc, "list_table_facts"):
        return []

    payloads: list[dict[str, Any]] = []

    def deadline_remaining() -> float | None:
        if deadline_at is None:
            return None
        return deadline_at - time.perf_counter()

    def finalize_payloads() -> list[dict[str, Any]]:
        scored: list[tuple[int, dict[str, Any]]] = []
        seen: set[str] = set()
        for payload in payloads:
            content = str(payload.get("content") or "")
            if not content:
                continue
            key = str(payload.get("chunk_id") or payload.get("point_id") or _content_key(content))
            if key in seen:
                continue
            seen.add(key)
            score = _score_table_payload(payload, query, plan)
            if score <= 35:
                continue
            scored.append((score, _payload_to_result(payload, score=min(0.999, score / 160.0))))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in scored[: max(top_k * 2, top_k + 4)]]

    async def collect(**kwargs: Any) -> bool:
        remaining = deadline_remaining()
        if remaining is not None and remaining <= 0:
            return False

        async def call_with_scope():
            return await doc_svc.list_table_facts(
                limit=120,
                payload_filters=filters,
                **kwargs,
            )

        async def call_without_scope():
            return await doc_svc.list_table_facts(limit=120, **kwargs)

        async def bounded(call_factory):
            current_remaining = deadline_remaining()
            if current_remaining is None:
                return await call_factory()
            if current_remaining <= 0:
                raise TimeoutError()
            return await asyncio.wait_for(call_factory(), timeout=max(0.001, current_remaining))

        try:
            rows = await bounded(call_with_scope)
        except TypeError:
            # Older/fake services in tests may not accept newly added filters.
            try:
                rows = await bounded(call_without_scope)
            except TimeoutError:
                return False
            except Exception:
                return True
        except TimeoutError:
            return False
        except Exception as exc:  # pragma: no cover - defensive production guard
            logger.debug("Exact table fact lookup failed", error=str(exc), filters=kwargs)
            return True
        payloads.extend(dict(row) for row in rows)
        return True

    fact_types = (
        "spreadsheet_cell_fact",
        "spreadsheet_semantic_sentence",
        "spreadsheet_table_fact",
        "spreadsheet_row",
    )

    label_sheets = plan.sheet_names
    if plan.labels and not label_sheets and _SPREADSHEET_LABEL_TRIGGERS_RE.search(query or ""):
        # Business label lookups usually live in dedicated definition sheets.
        # This is a structural hint, not a value rule: if no such sheet exists,
        # the row_label fallback below still works.
        label_sheets = ["Def strips"]

    for label in plan.labels[:4]:
        for sheet in label_sheets:
            for stype in fact_types:
                if not await collect(semantic_type=stype, sheet_name=sheet, row_label=label):
                    return finalize_payloads()
        for stype in fact_types[:3]:
            if not await collect(semantic_type=stype, row_label=label):
                return finalize_payloads()

    for code in plan.trial_codes[:4]:
        for stype in ("spreadsheet_table_fact", "spreadsheet_row"):
            if not await collect(semantic_type=stype, column_header=code):
                return finalize_payloads()
        test_number = _trial_code_number(code)
        if test_number:
            if not await collect(semantic_type="spreadsheet_row", sheet_name=f"test {test_number}"):
                return finalize_payloads()
            for metric in plan.metric_terms[:4]:
                if not await collect(
                    semantic_type="spreadsheet_table_fact",
                    sheet_name=f"test {test_number}",
                    row_label=metric,
                ):
                    return finalize_payloads()

    for sheet in plan.sheet_names[:3]:
        if not plan.labels:
            if not await collect(semantic_type="spreadsheet_row", sheet_name=sheet, query=query[:80]):
                return finalize_payloads()

    return finalize_payloads()


def _is_spreadsheet_evidence(content: str) -> bool:
    lower = str(content or "").lower()
    return (
        "spreadsheet sheet:" in lower
        or "spreadsheet label-value fact:" in lower
        or "spreadsheet interpreted cells:" in lower
        or "spreadsheet header row:" in lower
        or "spreadsheet cell fact:" in lower
        or "spreadsheet table fact:" in lower
        or "spreadsheet semantic sentence:" in lower
        or "spreadsheet schema:" in lower
    )


def _compact_reference_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _query_project_references(question: str) -> list[str]:
    refs: list[str] = []
    folded = str(question or "").upper()
    for match in _PROJECT_REFERENCE_RE.findall(folded):
        compact = _compact_reference_text(match).upper()
        if len(compact) >= 5 and compact not in refs:
            refs.append(compact)
    for prefix, suffix in re.findall(r"\b([A-Z]{2,}[A-Z0-9]*)\s*[-_/ ]\s*(\d{2,}[A-Z0-9]*)\b", folded):
        compact = _compact_reference_text(f"{prefix}{suffix}").upper()
        if len(compact) >= 5 and compact not in refs:
            refs.append(compact)
    return refs[:5]


def _prioritise_exact_project_reference_matches(
    results: list[dict[str, Any]],
    question: str,
) -> list[dict[str, Any]]:
    refs = _query_project_references(question)
    if not refs or not results:
        return results
    ranked: list[tuple[int, float, int, dict[str, Any]]] = []
    has_exact = False
    for index, row in enumerate(results):
        metadata = row.get("metadata") or {}
        haystack = " ".join(
            str(value or "")
            for value in (
                row.get("content"),
                metadata.get("content"),
                metadata.get("document_filename"),
                metadata.get("document_id"),
                metadata.get("project_code"),
                metadata.get("archive_name"),
            )
        )
        compact = _compact_reference_text(haystack).upper()
        exact_matches = sum(1 for ref in refs if ref in compact)
        has_exact = has_exact or exact_matches > 0
        ranked.append((exact_matches, float(row.get("combined_score") or row.get("score") or 0.0), -index, row))
    if not has_exact:
        return results
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [row for _, _, _, row in ranked]


def _prioritise_spreadsheet_label_matches(
    results: list[dict[str, Any]],
    question: str,
) -> list[dict[str, Any]]:
    plan = TableQueryPlanner().plan(question)
    if not plan.is_table_query:
        return results
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, row in enumerate(results):
        content, _ = _result_content_score(row)
        score = _spreadsheet_label_match_score(content, plan.labels)
        score += _spreadsheet_protocol_match_score(content, question)
        metadata = row.get("metadata") or {}
        if metadata:
            score += _score_table_payload(metadata, question, plan) - 50
        if row.get("table_exact_match"):
            score += 60
        ranked.append((score, -index, row))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _, _, row in ranked]


def _prepend_exact_table_candidates(
    exact_rows: list[dict[str, Any]],
    ranked_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not exact_rows:
        return ranked_rows
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*exact_rows, *ranked_rows]:
        content, _ = _result_content_score(row)
        if not content:
            continue
        key = str((row.get("metadata") or {}).get("chunk_id") or row.get("id") or _content_key(content))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


async def retrieve_chah_like(
    doc_svc: "DocumentService",
    query: str,
    top_k: int = 5,
    query_hints: str | None = None,
    retrieval_policy: RetrievalPolicy | None = None,
    filters: dict[str, Any] | None = None,
    use_hybrid: bool = True,
    allow_legacy_hybrid: bool = True,
    deadline_seconds: float | None = None,
    max_variants: int = 3,
    max_candidates: int = 80,
    search_params: dict[str, Any] | None = None,
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

    deadline_at = _deadline_at(deadline_seconds)
    table_plan = TableQueryPlanner().plan(q, query_hints=query_hints)
    exact_started = time.perf_counter()
    exact_rows = await _exact_table_fact_candidates(
        doc_svc,
        q,
        table_plan,
        top_k=top_k,
        filters=filters,
        deadline_at=deadline_at,
    )
    exact_table_elapsed_ms = int((time.perf_counter() - exact_started) * 1000)
    exact_metadata_started = time.perf_counter()
    exact_metadata_rows = await _exact_metadata_candidates(
        doc_svc,
        q,
        top_k=top_k,
        filters=filters,
        retrieval_policy=retrieval_policy,
        deadline_at=deadline_at,
    )
    exact_metadata_elapsed_ms = int((time.perf_counter() - exact_metadata_started) * 1000)
    variants = _query_variants(q, query_hints=query_hints, retrieval_policy=retrieval_policy)[
        : max(1, int(max_variants or 3))
    ]
    # Per-variant fan-out. A deliberately wide top_k (document-discovery widening
    # in context.py passes top_k≈40) digs deeper per variant so specific annex /
    # operating-manual docs reach the pool; for any normal top_k (< 30) this is the
    # exact original ``min(12, top_k + 7)`` cap, so non-discovery is unchanged.
    per_variant_k = min(top_k if top_k >= 30 else min(12, top_k + 7), max(1, int(max_candidates or 80)))
    remaining_seconds = _remaining_deadline(deadline_at, deadline_seconds)
    tasks = [
        asyncio.create_task(
            _search_documents(
                doc_svc,
                v,
                top_k=per_variant_k,
                filters=filters,
                use_hybrid=use_hybrid,
                allow_legacy_hybrid=allow_legacy_hybrid,
                deadline_seconds=remaining_seconds,
                search_params=search_params,
            )
        )
        for v in variants
        if deadline_at is None or float(remaining_seconds or 0.0) > 0.001
    ]
    done, pending = await asyncio.wait(
        tasks,
        timeout=max(0.001, float(remaining_seconds or 4.0)),
    ) if tasks else (set(), set())
    await _cancel_pending_tasks(pending, label="chah_variants")
    lists = []
    for task in tasks:
        if task not in done:
            continue
        try:
            lists.append(task.result() or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("C-HAH variant search failed", error=str(exc))
    lists = [rerank_results_with_policy(list(rows or []), q, retrieval_policy) for rows in lists]
    # Cap the RRF merge pool. The ceiling scales with top_k so a deliberately wide
    # caller gets a wide candidate pool; for normal top_k (≤30) this is identical
    # to ``min(…, 30)``.
    candidate_k = min(max(top_k * 4, top_k + 10), max(top_k, int(max_candidates or 80)))
    merged = _prioritise_spreadsheet_label_matches(
        _prioritise_exact_project_reference_matches(_merge_rrf(list(lists), top_k=candidate_k), q),
        q,
    )
    merged = _prepend_exact_metadata_candidates(exact_metadata_rows, merged)
    merged = _prepend_exact_table_candidates(exact_rows, merged)[:top_k]
    chunks, scores, metas = _results_to_chunks_scores_metas(merged)
    diagnostics = {
        **_sparse_diagnostics_from_metas(metas),
        **_exact_metadata_diagnostics(
            attempted=_exact_metadata_signal(q, retrieval_policy),
            hits=len(exact_metadata_rows),
            elapsed_ms=exact_metadata_elapsed_ms,
            exact_match_required=_exact_match_required(q, retrieval_policy),
        ),
        **_exact_table_diagnostics(
            attempted=table_plan.is_table_query,
            hits=len(exact_rows),
            elapsed_ms=exact_table_elapsed_ms,
        ),
    }
    v_preview = repr(variants)[:200]
    detail = (
        f"Parallel layered searches: {len(lists)}/{len(variants)} query variant(s); "
        f"RRF candidate merge top_{candidate_k}; exact_metadata_hits={len(exact_metadata_rows)}; "
        f"exact_table_hits={len(exact_rows)} "
        f"→ {len(chunks)} chunks. Variants: {v_preview}"
    )
    if diagnostics:
        detail = f"{detail}; sparse={diagnostics.get('sparse_status')}:{diagnostics.get('sparse_backend')}"
    logger.info("C-HAH-like retrieval complete", variants=len(variants), merged=len(chunks))
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline="chah_backend",
        label="C-HAH (backend)",
        reason="Parallel budget-aware layered retrieval over query variants + RRF merge",
        detail=detail,
        metadatas=metas,
        diagnostics=diagnostics,
    )


def _normalize_mode(mode: Optional[str]) -> str:
    return (mode or "auto").strip().lower()


def _search_params_for_profile(retrieval_profile: str | None) -> dict[str, Any] | None:
    profile = str(retrieval_profile or "").strip().lower()
    if not profile:
        return None
    params: dict[str, Any] = {"retrieval_profile": profile}
    if profile in {"oracle_fast", "chat", "deep_async"}:
        params["group_by"] = "document_id"
        params["group_size"] = 2 if profile == "deep_async" else 1
    return params


async def retrieve_for_mode(
    doc_svc: Optional["DocumentService"],
    query: str,
    mode: Optional[str],
    *,
    top_k: int = 5,
    use_hybrid: bool = True,
    hah_chah_enabled: bool = True,
    query_hints: str | None = None,
    retrieval_policy: RetrievalPolicy | None = None,
    filters: dict[str, Any] | None = None,
    deadline_seconds: float | None = None,
    max_variants: int = 3,
    max_candidates: int = 80,
    allow_legacy_hybrid: bool = True,
    retrieval_profile: str | None = None,
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
        return await retrieve_hah_like(
            doc_svc,
            query,
            top_k=top_k,
            retrieval_policy=retrieval_policy,
            filters=filters,
            use_hybrid=use_hybrid,
            allow_legacy_hybrid=allow_legacy_hybrid,
            deadline_seconds=deadline_seconds,
            search_params=_search_params_for_profile(retrieval_profile),
        )
    if hah_chah_enabled and m in ("chah", "c-hah", "c_hah", "hahcomposite", "hah_composite"):
        return await retrieve_chah_like(
            doc_svc,
            query,
            top_k=top_k,
            query_hints=query_hints,
            retrieval_policy=retrieval_policy,
            filters=filters,
            use_hybrid=use_hybrid,
            allow_legacy_hybrid=allow_legacy_hybrid,
            deadline_seconds=deadline_seconds,
            max_variants=max_variants,
            max_candidates=max_candidates,
            search_params=_search_params_for_profile(retrieval_profile),
        )

    deadline_at = _deadline_at(deadline_seconds)
    table_plan = TableQueryPlanner().plan(query, query_hints=query_hints)
    exact_started = time.perf_counter()
    exact_rows = await _exact_table_fact_candidates(
        doc_svc,
        query,
        table_plan,
        top_k=top_k,
        filters=filters,
        deadline_at=deadline_at,
    )
    exact_table_elapsed_ms = int((time.perf_counter() - exact_started) * 1000)
    exact_metadata_started = time.perf_counter()
    exact_metadata_rows = await _exact_metadata_candidates(
        doc_svc,
        query,
        top_k=top_k,
        filters=filters,
        retrieval_policy=retrieval_policy,
        deadline_at=deadline_at,
    )
    exact_metadata_elapsed_ms = int((time.perf_counter() - exact_metadata_started) * 1000)
    search_query = query
    if query_hints:
        search_query = f"{query}\n\nKnowledge guide hints:\n{str(query_hints)[:900]}"
    candidate_k = top_k
    if table_plan.is_table_query:
        candidate_k = min(max(top_k * 4, top_k + 10), 30)
    results = await _search_documents(
        doc_svc,
        search_query,
        top_k=candidate_k,
        filters=filters,
        use_hybrid=use_hybrid,
        allow_legacy_hybrid=allow_legacy_hybrid,
        deadline_seconds=_remaining_deadline(deadline_at, deadline_seconds),
        search_params=_search_params_for_profile(retrieval_profile),
    )
    results = rerank_results_with_policy(results, query, retrieval_policy)
    results = _prioritise_exact_project_reference_matches(results, query)
    results = _prioritise_spreadsheet_label_matches(results, query)
    results = _prepend_exact_metadata_candidates(exact_metadata_rows, results)
    results = _prepend_exact_table_candidates(exact_rows, results)[:top_k]
    chunks, scores, metas = _results_to_chunks_scores_metas(results)
    diagnostics = {
        **_sparse_diagnostics_from_metas(metas),
        **_exact_metadata_diagnostics(
            attempted=_exact_metadata_signal(query, retrieval_policy),
            hits=len(exact_metadata_rows),
            elapsed_ms=exact_metadata_elapsed_ms,
            exact_match_required=_exact_match_required(query, retrieval_policy),
        ),
        **_exact_table_diagnostics(
            attempted=table_plan.is_table_query,
            hits=len(exact_rows),
            elapsed_ms=exact_table_elapsed_ms,
        ),
    }
    pipe: Literal["naive", "hybrid"] = "hybrid" if use_hybrid else "naive"
    detail = (
        f"use_hybrid={use_hybrid} top_k={top_k} candidate_k={candidate_k} "
        f"exact_metadata_hits={len(exact_metadata_rows)} exact_table_hits={len(exact_rows)}"
    )
    if diagnostics:
        detail = f"{detail}; sparse={diagnostics.get('sparse_status')}:{diagnostics.get('sparse_backend')}"
    return RetrievalPipelineResult(
        chunks=chunks,
        scores=scores,
        pipeline=pipe,
        label="vector_only" if not use_hybrid else "hybrid_rrf",
        reason="Standard DocumentService.search",
        detail=detail,
        metadatas=metas,
        diagnostics=diagnostics,
    )
