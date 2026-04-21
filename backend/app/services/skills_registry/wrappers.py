"""Callable wrappers for canonical Skills.

Each wrapper translates a typed canonical-skill input into an actual
call against the existing OmniRAG service layer. The mapping is kept
here (not in the seed metadata) so the registry can be queried before
the runtime is wired in Phase 6.

The `resolve(slug)` helper returns an async callable with the signature:

    async def invoke(payload: dict, *, ctx: dict | None = None) -> dict

Wrappers are intentionally thin — they never introduce new business
logic. If the underlying service does not exist yet the wrapper is
marked `UNIMPLEMENTED` and raises `NotImplementedError` at call time.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

SkillCallable = Callable[[Dict[str, Any], Optional[Dict[str, Any]]], Awaitable[Dict[str, Any]]]


async def _unimplemented(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raise NotImplementedError(
        "This canonical skill has no runtime wrapper bound yet. Wire it in Phase 6 (runtime engine)."
    )


# -- Concrete wrappers (lazy-imported so importing this module stays light). --

async def _llm_rag_answer_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Lazy import to avoid heavy deps when the registry is only introspected.
    try:
        from app.services.rag.rag_service import answer  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    result = await answer(query=payload["query"], context_id=payload.get("context_id"))
    return {
        "answer": result.get("answer"),
        "citations": result.get("citations", []),
        "decision_steps": result.get("decision_steps", []),
    }


async def _semantic_search_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.retrieval.retrieval_service import search  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    results = await search(query=payload["query"], top_k=payload.get("top_k", 5))
    return {"results": results}


async def _eval_radar_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.evaluation.evaluation_service import radar  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await radar(answer=payload["answer"], ground_truth=payload.get("ground_truth"))


async def _claim_audit_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.evaluation.evaluation_service import claim_audit  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await claim_audit(answer=payload["answer"], citations=payload.get("citations", []))


async def _intelligence_batch_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.intelligence.intelligence_service import run_batch  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await run_batch(feed_ids=payload.get("feed_ids") or [])


async def _sharepoint_ingestion_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.connectors.sharepoint import sync_library  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await sync_library(site_url=payload["site_url"], library=payload.get("library"))


async def _document_ingestion_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.document_parser.ingest import ingest_file  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await ingest_file(filename=payload["filename"], collection=payload.get("collection"))


async def _voice_transcribe_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.connectors.voice import transcribe  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await transcribe(audio_ref=payload["audio_ref"])


async def _voice_tts_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.connectors.voice import synthesize  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await synthesize(text=payload["text"], voice=payload.get("voice"))


async def _audit_log_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Audit writes through the existing tracing service when available.
    try:
        from app.services.tracing.audit import write_event  # type: ignore
    except Exception:
        return {"id": "noop", "warning": "audit service unavailable"}
    return await write_event(event_type=payload["event_type"], details=payload.get("details") or {})


async def _ollama_llm_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.model_clients.ollama_client import generate  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await generate(prompt=payload["prompt"], model=payload.get("model"))


async def _azure_llm_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from app.services.model_clients.azure_client import generate  # type: ignore
    except Exception:
        return await _unimplemented(payload, ctx)
    return await generate(prompt=payload["prompt"], model=payload.get("model"))


_REGISTRY: Dict[str, SkillCallable] = {
    "llm_rag_answer_v1": _llm_rag_answer_v1,
    "semantic_search_v1": _semantic_search_v1,
    "document_ingestion_v1": _document_ingestion_v1,
    "eval_radar_v1": _eval_radar_v1,
    "claim_audit_v1": _claim_audit_v1,
    "intelligence_batch_v1": _intelligence_batch_v1,
    "sharepoint_ingestion_v1": _sharepoint_ingestion_v1,
    "voice_transcribe_v1": _voice_transcribe_v1,
    "voice_tts_v1": _voice_tts_v1,
    "audit_log_v1": _audit_log_v1,
    "ollama_llm_v1": _ollama_llm_v1,
    "azure_llm_v1": _azure_llm_v1,
}


def resolve(slug: str) -> SkillCallable:
    """Return the runtime callable bound to a skill slug.

    Unknown slugs fall through to `_unimplemented` so callers never crash
    on a KeyError — they get a NotImplementedError at call time instead.
    """
    return _REGISTRY.get(slug, _unimplemented)


def bound_slugs() -> Dict[str, bool]:
    """Returns {slug: is_real} for observability / admin debug endpoints."""
    return {slug: fn is not _unimplemented for slug, fn in _REGISTRY.items()}
