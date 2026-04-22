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
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    system_prompt: Optional[str] = None,
    extra_preferences: Optional[Dict[str, Any]] = None,
    token_sink: Optional[Callable[[str], None]] = None,
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
    if temperature is not None:
        request_dict["temperature"] = temperature
    if max_tokens is not None:
        request_dict["max_tokens"] = max_tokens
    if system_prompt:
        request_dict["system_prompt"] = system_prompt

    text_parts: List[str] = []
    reasoning_trace: Any = None
    sources: Any = None
    decision_steps: List[Dict[str, Any]] = []
    first_id: Optional[str] = None
    meta: Dict[str, Any] = {
        "rag_mode": rag_mode_override,
        "prompt_type": prompt_type,
    }

    try:
        async for chunk in orchestrator.process_request(request_dict):
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("rag_service.answer: orchestrator stream failed", error=str(exc))
        meta["error"] = str(exc)

    citations: List[Dict[str, Any]] = []
    if isinstance(sources, list):
        citations = sources
    elif isinstance(sources, dict):
        citations = sources.get("citations") or sources.get("items") or []

    return {
        "id": first_id,
        "answer": "".join(text_parts),
        "citations": citations,
        "reasoning_trace": reasoning_trace,
        "decision_steps": decision_steps,
        "meta": meta,
    }
