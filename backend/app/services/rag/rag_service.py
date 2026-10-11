"""RAG service facade.

Thin wrapper over the existing `AgentOrchestrator.process_request` stream
that aggregates the chunks into a single `{answer, citations,
decision_steps, meta}` payload. This is the canonical entry point used
by the skills registry (``llm_rag_answer_v1``), by system-run
invocations, and by any caller that wants the non-streamed result of
the RAG engine.

Keeping this facade shallow (rather than reimplementing the
orchestrator) guarantees the cockpit sees exactly the same reasoning
trail as the live chat endpoint.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


def _get_orchestrator():
    """Resolve the orchestrator registered by `app.main` at startup."""
    from app.api.v1.endpoints.agents import get_orchestrator  # circular-safe lazy import

    return get_orchestrator()


async def answer(
    query: str,
    context_id: Optional[str] = None,
    *,
    workspace_id: Optional[str] = None,
    workspace_slug: Optional[str] = None,
    session_id: Optional[str] = None,
    rag_mode_override: Optional[str] = None,
    prompt_type: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    top_k: Optional[int] = None,
    candidate_pool_k: Optional[int] = None,
    synthesis_k: Optional[int] = None,
    source_display_k: Optional[int] = None,
    latency_profile: Optional[str] = None,
    retrieval_profile: Optional[str] = None,
    deep_retrieval: Optional[bool] = None,
    retrieval_filters: Optional[Dict[str, Any]] = None,
    knowledge_scope: Optional[str] = None,
    context_collection: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    system_prompt: Optional[str] = None,
    extra_preferences: Optional[Dict[str, Any]] = None,
    token_sink: Optional[Callable[[str], None]] = None,
    collection_identity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run one RAG request end-to-end and return an aggregated payload.

    This is the facade that canonical skills + programmatic callers use.
    The HTTP chat endpoints keep streaming directly from the orchestrator;
    this helper simply consumes that stream and folds it back into a dict.

    When ``token_sink`` is provided (Vague D / D2), every ``chunk_type =
    text`` segment is also forwarded to the sink in arrival order, so
    the Run engine can rebroadcast the answer token-by-token through
    the SSE bus without breaking the aggregated return contract used
    by non-streaming callers.
    """
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        logger.warning("rag_service.answer: orchestrator not initialised")
        return {
            "answer": "",
            "citations": [],
            "decision_steps": [],
            "meta": {
                "error": "orchestrator_unavailable",
                "rag_mode": rag_mode_override,
                "prompt_type": prompt_type,
            },
        }

    agent_preferences: Dict[str, Any] = dict(extra_preferences or {})
    if model or provider:
        model_prefs = dict(agent_preferences.get("model_preferences") or {})
        if model:
            model_prefs["model"] = model
        if provider:
            model_prefs["provider"] = provider
        agent_preferences["model_preferences"] = model_prefs

    request_dict: Dict[str, Any] = {
        "query": query,
        "agent_preferences": agent_preferences or {},
    }
    if context_id:
        request_dict["context_id"] = context_id
    if workspace_id:
        request_dict["workspace_id"] = workspace_id
    if workspace_slug:
        request_dict["workspace_slug"] = workspace_slug
    if session_id:
        request_dict["session_id"] = session_id
    if rag_mode_override:
        request_dict["rag_pipeline_mode"] = rag_mode_override
    if prompt_type:
        request_dict["prompt_type"] = prompt_type
    if top_k is not None:
        request_dict["top_k"] = top_k
    if candidate_pool_k is not None:
        request_dict["candidate_pool_k"] = candidate_pool_k
    if synthesis_k is not None:
        request_dict["synthesis_k"] = synthesis_k
    if source_display_k is not None:
        request_dict["source_display_k"] = source_display_k
    if latency_profile:
        request_dict["latency_profile"] = latency_profile
    if retrieval_profile:
        request_dict["retrieval_profile"] = retrieval_profile
    if deep_retrieval is not None:
        request_dict["deep_retrieval"] = bool(deep_retrieval)
    if retrieval_filters:
        request_dict["retrieval_filters"] = dict(retrieval_filters)
    if knowledge_scope:
        request_dict["knowledge_scope"] = knowledge_scope
    if context_collection:
        request_dict["context_collection"] = context_collection
    if temperature is not None:
        request_dict["temperature"] = temperature
    if max_tokens is not None:
        request_dict["max_tokens"] = max_tokens
    if system_prompt:
        request_dict["system_prompt"] = system_prompt
    if collection_identity:
        # Signed by ``collection_access``; retrieval verifies it and otherwise
        # reads open collections only.
        request_dict["collection_identity"] = dict(collection_identity)
    try:
        from app.services.rag.context import apply_retrieval_profile_to_request

        apply_retrieval_profile_to_request(request_dict)
    except Exception as exc:  # noqa: BLE001 - the orchestrator still applies the same policy before search.
        logger.warning("rag_service.answer: retrieval budget preflight failed", error=str(exc))

    from app.services.rag.project_references import using_workspace_id_project_scheme

    try:
        with using_workspace_id_project_scheme(workspace_id):
            return await _answer_with_orchestrator(
                orchestrator,
                request_dict,
                rag_mode_override=rag_mode_override,
                prompt_type=prompt_type,
                token_sink=token_sink,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("rag_service.answer: orchestrator stream failed", error=str(exc))
        return {
            "id": None,
            "answer": "",
            "citations": [],
            "reasoning_trace": None,
            "decision_steps": [],
            "meta": {
                "rag_mode": rag_mode_override,
                "prompt_type": prompt_type,
                "error": str(exc),
            },
        }


async def _answer_with_orchestrator(
    orchestrator,
    request_dict: Dict[str, Any],
    *,
    rag_mode_override: Optional[str],
    prompt_type: Optional[str],
    token_sink: Optional[Callable[[str], None]],
) -> Dict[str, Any]:
    text_parts: List[str] = []
    reasoning_trace: Any = None
    sources: Any = None
    decision_steps: List[Dict[str, Any]] = []
    first_id: Optional[str] = None
    meta: Dict[str, Any] = {
        "rag_mode": rag_mode_override,
        "prompt_type": prompt_type,
    }
    retrieval_details: Dict[str, Any] = {}
    rag_context: Any = None

    try:
        stream = orchestrator.process_request(request_dict)
        try:
            async for chunk in stream:
                if first_id is None:
                    first_id = chunk.get("id")
                if chunk.get("chunk_type") == "text":
                    content = chunk.get("content", "")
                    text_parts.append(content)
                    if token_sink is not None and content:
                        try:
                            token_sink(content)
                        except Exception:  # noqa: BLE001
                            logger.debug(
                                "rag_service.answer: token_sink raised, dropping chunk",
                                exc_info=True,
                            )
                if chunk.get("reasoning_trace"):
                    reasoning_trace = chunk.get("reasoning_trace")
                if chunk.get("sources"):
                    sources = chunk.get("sources")
                if chunk.get("chunk_type") == "retrieval":
                    details = chunk.get("details")
                    if isinstance(details, dict):
                        retrieval_details.update(
                            {key: value for key, value in details.items() if value is not None}
                        )
                    if chunk.get("rag_context"):
                        rag_context = chunk.get("rag_context")
                if chunk.get("chunk_type") == "decision_step" and chunk.get("decision_step"):
                    step = chunk.get("decision_step")
                    existing = next(
                        (i for i, ds in enumerate(decision_steps) if ds.get("id") == step.get("id")),
                        None,
                    )
                    if existing is not None:
                        decision_steps[existing] = step
                    else:
                        decision_steps.append(step)
                if chunk.get("is_final"):
                    break
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                await close()
    except Exception as exc:  # noqa: BLE001
        logger.exception("rag_service.answer: orchestrator stream failed", error=str(exc))
        meta["error"] = str(exc)

    citations: List[Dict[str, Any]] = []
    if isinstance(sources, list):
        citations = sources
    elif isinstance(sources, dict):
        citations = sources.get("citations") or sources.get("items") or []
    if retrieval_details:
        meta["retrieval"] = retrieval_details
        for key in (
            "retrieval_scope",
            "retrieval_plan",
            "scope_confidence",
            "scope_reason",
            "dense_policy",
            "dense_only",
            "sparse_status",
            "sparse_backend",
            "sparse_fallback_reason",
            "retrieval_profile",
            "fallback_reason",
            "latency_budget",
            "score_threshold_applied",
            "deep_retrieval_recommended",
            "deep_job_id",
            "deep_poll_url",
            "deep_status",
            "retrieval_decision_trace",
        ):
            if key in retrieval_details:
                meta[key] = retrieval_details[key]
    if rag_context is not None:
        meta["rag_context"] = rag_context

    return {
        "id": first_id,
        "answer": "".join(text_parts),
        "citations": citations,
        "reasoning_trace": reasoning_trace,
        "decision_steps": decision_steps,
        "meta": meta,
    }
