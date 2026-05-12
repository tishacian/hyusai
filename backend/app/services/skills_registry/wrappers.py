"""Callable wrappers for canonical Skills.

Each wrapper translates a typed canonical-skill input into a real call
against the existing OmniRAG service layer. Wrappers are intentionally
thin — they never introduce new business logic.

Runtime status (returned by `bound_slugs()`) is tri-state:
 - ``bound``     : an actual implementation module is resolvable and will be invoked.
 - ``stub``      : a placeholder that logs + returns a degraded payload (no hard-fail).
 - ``unbound``   : no wrapper declared for that slug (falls through to `_unimplemented`).

The check happens lazily on first use, cached in
``_RESOLVED_STATUS`` so the admin `/skills/runtime-health` endpoint is
cheap to call. Imports of the underlying services stay lazy to avoid
pulling heavy deps at registry introspection time.
"""
from __future__ import annotations

import importlib
import base64
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)

SkillCallable = Callable[[Dict[str, Any], Optional[Dict[str, Any]]], Awaitable[Dict[str, Any]]]


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------
async def _unimplemented(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raise NotImplementedError(
        "This canonical skill has no runtime wrapper bound. Add it to `_REGISTRY` in "
        "`skills_registry/wrappers.py` or mark it as a stub."
    )


async def _stub(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Degraded placeholder for skills whose runtime is not yet available."""
    logger.info("skills_registry: stub invocation", payload_keys=list(payload.keys()))
    return {
        "status": "degraded",
        "warning": "runtime_unavailable",
        "input_echo": payload,
    }


# ---------------------------------------------------------------------------
# Concrete wrappers
# ---------------------------------------------------------------------------
async def _llm_rag_answer_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.rag_service import answer

    ctx = ctx or {}
    result = await answer(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        session_id=payload.get("session_id"),
        rag_mode_override=(
            payload.get("rag_pipeline_mode")
            or payload.get("rag_mode_override")
            or ctx.get("retrieval_mode_default")
        ),
        prompt_type=payload.get("prompt_type") or ctx.get("default_prompt_type"),
        model=payload.get("model") or ctx.get("default_model"),
        provider=payload.get("provider"),
        # Forward the run-engine sink so the orchestrator's text
        # chunks are rebroadcast as SSE token_delta events in real
        # time (Vague D / D2). Non-streaming callers simply don't pass
        # the sink and observe no behavioural change.
        token_sink=ctx.get("token_sink"),
    )
    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "decision_steps": result.get("decision_steps", []),
        "meta": result.get("meta", {}),
    }


async def _semantic_search_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.document_service import DocumentService
    from app.services.rag.pipeline_retrieval import retrieve_for_mode

    ctx = ctx or {}
    workspace_slug = ctx.get("workspace_slug")
    doc_svc = DocumentService(workspace_slug=workspace_slug)
    top_k = int(payload.get("top_k", 5))
    mode = payload.get("mode") or "hybrid"
    result = await retrieve_for_mode(
        doc_svc,
        payload["query"],
        mode=mode,
        top_k=top_k,
        use_hybrid=mode != "naive",
    )
    return {
        "results": [
            {"content": c, "score": s} for c, s in zip(result.chunks, result.scores)
        ],
        "pipeline": result.pipeline,
        "label": result.label,
        "reason": result.reason,
        "detail": result.detail,
    }


async def _document_ingestion_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.document_service import DocumentService

    ctx = ctx or {}
    doc_svc = DocumentService(workspace_slug=ctx.get("workspace_slug"))
    file_path = payload.get("file_path") or payload.get("filename")
    if not file_path:
        raise ValueError("document_ingestion_v1: 'file_path' or 'filename' required")
    result = await doc_svc.ingest_document(file_path)
    return {
        "doc_id": result.get("document_id"),
        "chunks": result.get("chunks_processed", 0),
        "status": result.get("status"),
    }


async def _eval_radar_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.evaluation.judge import get_judge_service

    judge = get_judge_service()
    evaluation = await judge.evaluate(
        query=payload.get("query", ""),
        response=payload["answer"],
        system_prompt=payload.get("system_prompt", ""),
        context_chunks=payload.get("context_chunks"),
        turn_number=payload.get("turn_number", 1),
    )
    return {
        "axes": evaluation.get("scores", {}),
        "overall": evaluation.get("composite_score"),
        "hallucination_rate": evaluation.get("hallucination_rate"),
        "drift_rate": evaluation.get("drift_rate"),
        "note": evaluation.get("overall_note"),
    }


async def _claim_audit_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.evaluation.judge import get_judge_service

    judge = get_judge_service()
    evaluation = await judge.evaluate(
        query=payload.get("query", ""),
        response=payload["answer"],
        system_prompt=payload.get("system_prompt", ""),
        context_chunks=payload.get("citations"),
        turn_number=payload.get("turn_number", 1),
    )
    audit = evaluation.get("claim_audit") or {}
    claims = audit.get("claims", [])
    supported = audit.get("supported", 0)
    total = max(1, len(claims))
    verdict = "supported" if supported / total >= 0.8 else "partial" if supported else "unsupported"
    return {
        "claims": claims,
        "verdict": verdict,
        "supported": supported,
        "unsupported": audit.get("unsupported", 0),
    }


async def _intelligence_batch_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.intelligence.batch import run_batch

    ctx = ctx or {}
    ingested = 0
    errors = 0
    events: list[str] = []
    target_id = (payload.get("target_id") or (payload.get("feed_ids") or [None])[0])
    async for event in run_batch(
        target_id=target_id,
        workspace_id=ctx.get("workspace_id"),
    ):
        kind = event.get("type") or event.get("status")
        if kind:
            events.append(str(kind))
        if event.get("type") == "article_stored":
            ingested += 1
        if event.get("type") == "error" or event.get("status") == "error":
            errors += 1
    return {"ingested": ingested, "errors": errors, "events": events}


async def _sharepoint_ingestion_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Real ingestion goes through the OAuth/MSAL flow in
    # `app.services.connectors.sharepoint_otp.ingester`. Triggering that
    # flow from a background skill still needs a tenant-scoped token
    # context, which is not currently passed in. Until the builder
    # surfaces that, we return a structured degraded response rather
    # than crash the run.
    logger.info(
        "sharepoint_ingestion_v1: degraded (missing tenant token context)",
        site_url=payload.get("site_url"),
    )
    return {
        "files": 0,
        "skipped": 0,
        "status": "degraded",
        "warning": "sharepoint_token_context_unavailable",
    }


async def _voice_transcribe_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider((payload.get("provider") or "cascade_openai"))
    audio_bytes = _audio_bytes_from_payload(payload)
    result = await provider.transcribe(
        audio_bytes,
        filename=payload.get("filename") or "recording.webm",
        content_type=payload.get("content_type") or "audio/webm",
    )
    return {
        "transcript": result.get("transcript") or result.get("text", ""),
        "text": result.get("text", ""),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "fallback": result.get("fallback", False),
    }


async def _voice_tts_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider((payload.get("provider") or "cascade_openai"))
    result = await provider.synthesize_bytes(
        payload["text"],
        voice=payload.get("voice") or "nova",
    )
    return {
        "audio_url": None,
        "audio_base64": result.get("audio_base64"),
        "content_type": result.get("content_type"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "bytes": result.get("bytes"),
    }


async def _voice_realtime_session_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import (
        build_openai_realtime_session,
        list_voice_runtime_providers,
        resolve_voice_runtime_slug,
    )

    ctx = ctx or {}
    provider = resolve_voice_runtime_slug(payload.get("provider") or ctx.get("voice_provider"))
    session = build_openai_realtime_session(
        model=payload.get("model"),
        voice=payload.get("voice") or "marin",
        instructions=payload.get("instructions"),
        input_language=payload.get("language") or payload.get("input_language"),
        output_language=payload.get("output_language"),
        capability=payload.get("capability") or "voice2voice_interaction",
        metadata={"transport": payload.get("transport") or "backend_ws"},
    )
    catalog = list_voice_runtime_providers()
    provider_meta = next((item for item in catalog.get("providers", []) if item.get("slug") == provider), None)
    return {
        "provider": provider,
        "model": payload.get("model"),
        "transport": payload.get("transport") or "backend_ws",
        "session": session if provider == "openai_realtime" else None,
        "capabilities": (provider_meta or {}).get("capabilities", {}),
        "fallback_policy": payload.get("fallback_policy") or "cascade_openai",
        "events": catalog.get("events", []),
    }


async def _voice_realtime_transcribe_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "cascade_openai")
    audio_bytes = _audio_bytes_from_payload(payload)
    result = await provider.transcribe(
        audio_bytes,
        filename=payload.get("filename") or "recording.webm",
        content_type=payload.get("content_type") or "audio/webm",
    )
    text = result.get("text") or result.get("transcript") or ""
    return {
        "transcript": text,
        "text": text,
        "text_events": [
            {"type": "text.partial", "text": text, "provider": result.get("provider")},
            {"type": "text.final", "text": text, "provider": result.get("provider")},
        ],
        "model": result.get("model"),
        "provider": result.get("provider"),
        "requested_provider": result.get("requested_provider") or payload.get("provider"),
        "fallback": result.get("fallback", False),
        "fallback_reason": result.get("fallback_reason"),
    }


async def _voice_realtime_speak_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "cascade_openai")
    result = await provider.synthesize_bytes(payload["text"], voice=payload.get("voice") or "nova")
    return {
        "audio_base64": result.get("audio_base64"),
        "content_type": result.get("content_type"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "requested_provider": result.get("requested_provider") or payload.get("provider"),
        "bytes": result.get("bytes"),
        "fallback": result.get("fallback", False),
        "events": [{"type": "audio.out", "bytes": result.get("bytes"), "provider": result.get("provider")}],
    }


async def _voice_realtime_translate_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "openai_realtime")
    if not provider.capabilities.get("translation"):
        return {
            "status": "degraded",
            "warning": "provider_capability_unsupported",
            "provider": provider.slug,
            "source_text": payload.get("text") or "",
            "translated_text": payload.get("text") or "",
        }
    return {
        "status": "deferred",
        "provider": provider.slug,
        "model": payload.get("model"),
        "source_language": payload.get("source_language") or payload.get("language"),
        "target_language": payload.get("target_language") or payload.get("output_language"),
        "events": ["translation.partial", "translation.final"],
    }


async def _voice_oracle_turn_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.knowledge_capture import evaluate_expert_answer

    evaluation = evaluate_expert_answer(
        answer=payload.get("answer") or payload.get("text") or "",
        question=payload.get("question"),
        gap=payload.get("gap"),
    )
    verdict = evaluation.get("verdict")
    action = "next_prompt" if verdict != "sufficient" else "capture_fact"
    return {
        "action": action,
        "evaluation": evaluation,
        "events": [{"type": "oracle.action", "action": action, "verdict": verdict}],
    }


def _audio_bytes_from_payload(payload: Dict[str, Any]) -> bytes:
    if payload.get("audio_bytes"):
        raw = payload["audio_bytes"]
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, str):
            return raw.encode("latin1")
        return bytes(raw)
    if payload.get("audio_base64"):
        return base64.b64decode(payload["audio_base64"])
    audio_ref = payload.get("audio_ref")
    if audio_ref:
        path = Path(audio_ref)
        if not path.exists() or not path.is_file():
            raise ValueError("voice_transcribe_v1: audio_ref does not resolve to a local file")
        return path.read_bytes()
    raise ValueError("voice_transcribe_v1: one of audio_bytes, audio_base64 or audio_ref is required")


async def _knowledge_gap_analysis_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.knowledge_capture import build_knowledge_gaps

    return {
        "gaps": build_knowledge_gaps(
            objective=payload["objective"],
            expert_profile=payload.get("expert_profile"),
            context_snapshot=payload.get("context") or {},
            knowledge_refs=payload.get("knowledge_refs") or [],
        )
    }


async def _expert_interview_plan_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.knowledge_capture import build_interview_plan

    return {
        "plan": build_interview_plan(
            objective=payload["objective"],
            expert_profile=payload.get("expert_profile"),
            duration_minutes=int(payload.get("duration_minutes") or 20),
            gaps=payload.get("gaps") or [],
            context_snapshot=payload.get("context") or {},
        )
    }


async def _expert_answer_evaluator_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.knowledge_capture import evaluate_expert_answer

    return evaluate_expert_answer(
        answer=payload["answer"],
        question=payload.get("question"),
        gap=payload.get("gap"),
    )


async def _capture_structuring_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # The persisted endpoint uses `structure_capture_payload` on an ORM
    # session. The skill contract also supports already-serialized session
    # payloads for DAG/runtime callers.
    session = payload["session"]
    transcript = session.get("transcript") or []
    evaluations = session.get("evaluations") or []
    captured_facts = session.get("captured_facts") or [
        {
            "id": f"fact-{turn.get('id')}",
            "text": turn.get("text", ""),
            "source": "expert_session",
            "confidence": next(
                (ev.get("score") for ev in evaluations if ev.get("turn_id") == turn.get("id")),
                0.5,
            ),
            "needs_review": True,
        }
        for turn in transcript
        if turn.get("speaker") == "expert"
    ]
    proposal = {
        "session_id": session.get("id"),
        "title": session.get("title"),
        "objective": session.get("objective"),
        "captured_facts": captured_facts,
        "open_questions": [
            {
                "gap_id": ev.get("gap_id"),
                "reason": ev.get("verdict"),
                "follow_up": ev.get("follow_up"),
            }
            for ev in evaluations
            if ev.get("verdict") != "sufficient"
        ],
        "transcript": transcript,
        "review": {"required": True},
    }
    return {"proposal": proposal}


async def _audit_log_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    event_id = str(uuid.uuid4())
    logger.info(
        "audit_log_v1: event",
        event_id=event_id,
        event_type=payload.get("event_type"),
        workspace_id=(ctx or {}).get("workspace_id"),
        ts=datetime.utcnow().isoformat(),
        details=payload.get("details") or {},
    )
    return {"id": event_id, "status": "recorded"}


async def _ollama_llm_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.model_clients.ollama_client import OllamaClient

    client = OllamaClient()
    model = payload.get("model") or "deepseek-r1:14b"
    result = await client.generate(model=model, prompt=payload["prompt"])
    return {
        "completion": result.get("response") or result.get("content", ""),
        "model": model,
    }


async def _azure_llm_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Azure OpenAI is OpenAI-compatible — reuse the OpenAI client.
    from app.services.model_clients.openai_client import OpenAIClient

    client = OpenAIClient()
    if not client.api_key:
        return {
            "completion": "",
            "status": "degraded",
            "warning": "openai_key_unavailable",
        }

    ctx = ctx or {}
    token_sink = ctx.get("token_sink")
    model = payload.get("model") or "gpt-4o-mini"
    prompt = payload["prompt"]

    # Stream token-by-token when the run engine provided a sink (Vague D
    # / D2). Every delta is pushed to the live SSE bus so the cockpit's
    # Execution terminal can render a typewriter effect; we also
    # accumulate the final text so the non-streaming contract
    # (`completion` field) keeps working for replay.
    if callable(token_sink):
        try:
            parts: list[str] = []
            async for chunk in client.stream(model=model, prompt=prompt):
                delta = chunk.get("delta") or ""
                if delta:
                    parts.append(delta)
                    token_sink(delta)
            return {
                "completion": "".join(parts),
                "model": model,
                "streamed": True,
            }
        except Exception as exc:  # noqa: BLE001 — fall back to non-streaming
            logger.warning(
                "azure_llm_v1: streaming failed, falling back",
                error=str(exc),
            )

    result = await client.generate(model=model, prompt=prompt)
    return {
        "completion": result.get("content", ""),
        "model": result.get("model"),
        "usage": result.get("usage", {}),
    }


async def _chain_naive_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.chains import answer_naive

    ctx = ctx or {}
    return await answer_naive(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        top_k=payload.get("top_k"),
    )


async def _chain_hybrid_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.chains import answer_hybrid

    ctx = ctx or {}
    return await answer_hybrid(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        top_k=payload.get("top_k"),
    )


async def _chain_mixed_hah_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.chains import answer_mixed_hah

    ctx = ctx or {}
    return await answer_mixed_hah(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        top_k=payload.get("top_k"),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# (slug -> (callable, expected_module_path|None, status_hint))
# ``expected_module_path`` is the module whose import must succeed for
# the wrapper to be considered `bound`. A ``None`` path means the
# wrapper is self-contained (loggers, stubs, in-process helpers).
_REGISTRY: Dict[str, Tuple[SkillCallable, Optional[str], str]] = {
    "llm_rag_answer_v1":       (_llm_rag_answer_v1,       "app.services.rag.rag_service",          "bound"),
    "semantic_search_v1":      (_semantic_search_v1,      "app.services.rag.pipeline_retrieval",   "bound"),
    "document_ingestion_v1":   (_document_ingestion_v1,   "app.services.rag.document_service",     "bound"),
    "eval_radar_v1":           (_eval_radar_v1,           "app.services.evaluation.judge",         "bound"),
    "claim_audit_v1":          (_claim_audit_v1,          "app.services.evaluation.judge",         "bound"),
    "intelligence_batch_v1":   (_intelligence_batch_v1,   "app.services.intelligence.batch",       "bound"),
    "sharepoint_ingestion_v1": (_sharepoint_ingestion_v1, None,                                    "stub"),
    "voice_transcribe_v1":     (_voice_transcribe_v1,     "app.services.voice_runtime",            "bound"),
    "voice_tts_v1":            (_voice_tts_v1,            "app.services.voice_runtime",            "bound"),
    "voice_realtime_session_v1": (_voice_realtime_session_v1, "app.services.voice_runtime",         "bound"),
    "voice_realtime_transcribe_v1": (_voice_realtime_transcribe_v1, "app.services.voice_runtime",   "bound"),
    "voice_realtime_speak_v1":  (_voice_realtime_speak_v1, "app.services.voice_runtime",            "bound"),
    "voice_realtime_translate_v1": (_voice_realtime_translate_v1, "app.services.voice_runtime",     "bound"),
    "voice_oracle_turn_v1":     (_voice_oracle_turn_v1,   "app.services.knowledge_capture",         "bound"),
    "knowledge_gap_analysis_v1": (_knowledge_gap_analysis_v1, "app.services.knowledge_capture",     "bound"),
    "expert_interview_plan_v1": (_expert_interview_plan_v1, "app.services.knowledge_capture",      "bound"),
    "expert_answer_evaluator_v1": (_expert_answer_evaluator_v1, "app.services.knowledge_capture",  "bound"),
    "capture_structuring_v1":  (_capture_structuring_v1,  "app.services.knowledge_capture",        "bound"),
    "audit_log_v1":            (_audit_log_v1,            None,                                    "bound"),
    "ollama_llm_v1":           (_ollama_llm_v1,           "app.services.model_clients.ollama_client", "bound"),
    "azure_llm_v1":            (_azure_llm_v1,            "app.services.model_clients.openai_client", "bound"),
    "chain_naive_v1":          (_chain_naive_v1,          "app.services.rag.chains.naive",         "bound"),
    "chain_hybrid_v1":         (_chain_hybrid_v1,         "app.services.rag.chains.hybrid",        "bound"),
    "chain_mixed_hah_v1":      (_chain_mixed_hah_v1,      "app.services.rag.chains.mixed_hah",     "bound"),
}

_RESOLVED_STATUS: Dict[str, str] = {}


def resolve(slug: str) -> SkillCallable:
    """Return the runtime callable bound to a skill slug.

    Unknown slugs fall through to ``_unimplemented``.
    """
    entry = _REGISTRY.get(slug)
    if entry is None:
        return _unimplemented
    return entry[0]


def runtime_status(slug: str) -> str:
    """Return ``bound`` | ``stub`` | ``unbound`` for a slug.

    Evaluates the dependency import on first call so we catch missing
    modules without forcing eager imports at startup.
    """
    if slug in _RESOLVED_STATUS:
        return _RESOLVED_STATUS[slug]
    entry = _REGISTRY.get(slug)
    if entry is None:
        _RESOLVED_STATUS[slug] = "unbound"
        return "unbound"
    _, module_path, hint = entry
    if module_path is None:
        _RESOLVED_STATUS[slug] = hint
        return hint
    try:
        importlib.import_module(module_path)
        _RESOLVED_STATUS[slug] = "bound"
        return "bound"
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "skills_registry: dependency import failed — marking stub",
            slug=slug,
            module=module_path,
            error=str(exc),
        )
        _RESOLVED_STATUS[slug] = "stub"
        return "stub"


def bound_slugs() -> Dict[str, str]:
    """Return `{slug: status}` for every registered skill (tri-state)."""
    return {slug: runtime_status(slug) for slug in _REGISTRY}


def registry_snapshot() -> Dict[str, Dict[str, Any]]:
    """Richer report for admin / observability endpoints."""
    snap: Dict[str, Dict[str, Any]] = {}
    for slug, (_fn, module_path, hint) in _REGISTRY.items():
        snap[slug] = {
            "status": runtime_status(slug),
            "declared_status": hint,
            "module": module_path,
        }
    return snap
