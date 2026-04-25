"""Run replay service — E1.5.2.

Re-runs a previously-completed Run with operator overrides applied to
the input. Surfaces from the review queue ("Re-run with override") and
from the run-detail view to let an operator try a different prompt /
RAG mode / model on the same question without leaving the queue.

Scope of MVP:

- **Chat-style runs** (``trigger="chat"`` or ``input_ref`` shaped as
  ``{"query": ...}``) are replayed by re-driving the orchestrator with
  a synthesized request. This covers the vast majority of review-queue
  candidates today (chat surface produces almost all auto-eval breaches).
- **System-style runs** (executed by ``run_engine.dag``) are NOT yet
  supported — the replay endpoint surfaces a 400 with a clear message
  pointing the operator to "Open run → Edit chain version → Re-launch"
  for now. Tracked in the journal as a follow-up tranche.

Override keys recognised on the body:

- ``query`` (str): replace the user prompt. NULL → keep parent prompt.
- ``rag_pipeline_mode`` (str): one of ``naive`` | ``hybrid`` | ``hah``
  | ``chah`` | ``auto``. Maps onto the chat orchestrator's existing
  per-query override path.
- ``model`` (str): swap the LLM. Sets ``agent_preferences.model_preferences.model``.
- ``provider`` (str): swap the LLM provider in the same payload.
- ``system_prompt`` (str): replace the system prompt verbatim.
- ``temperature`` (float): override sampling temperature.

Anything else in ``overrides`` is forwarded as-is into ``agent_preferences``
so future override keys don't require a service patch.

The new Run gets:

- ``parent_run_id`` set to the original
- ``trigger`` = ``"replay"``
- ``replay_overrides`` JSON = the original body.overrides dict
- ``schedule_eval`` fires the auto-eval loop on the new run, so the
  reviewer gets a score back to compare against the parent.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.run import Run
from app.services.audit_logger import emit_audit_event
from app.services.evaluation.auto_eval import schedule_eval


logger = get_logger(__name__)


class ReplayError(ValueError):
    """Raised on validation problems (missing parent input, unsupported
    trigger, malformed overrides). Endpoint maps to HTTP 400."""


# Keys we promote into the orchestrator request_dict directly (top-level).
_TOPLEVEL_KEYS = {
    "query",
    "rag_pipeline_mode",
    "rag_mode_override",
    "system_prompt",
    "prompt_type",
    "max_tokens",
    "temperature",
    "top_k",
    "similarity_threshold",
}


def _build_request_dict(
    *,
    parent: Run,
    workspace_slug: str,
    workspace_id: str,
    overrides: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the orchestrator request from the parent input + overrides.

    The merge rule is intentional: overrides win, parent fills the rest.
    Anything in overrides we don't recognise lands in
    ``agent_preferences`` so the orchestrator can pick it up if it
    knows the key, and silently ignore otherwise.
    """
    parent_input = parent.input_ref or {}
    base_query = parent_input.get("query") or parent_input.get("text") or ""
    if not isinstance(base_query, str) or not base_query.strip():
        # Defensive: a chat run *should* always carry a query string.
        raise ReplayError(
            "parent run has no replayable text input "
            "(input_ref.query or input_ref.text is empty)"
        )

    # Start from a minimal request dict with what every orchestrator
    # call needs.
    req: Dict[str, Any] = {
        "query": base_query,
        "workspace_slug": workspace_slug,
        "workspace_id": workspace_id,
        "stream": False,
        "include_reasoning": True,
        "include_sources": True,
    }

    # If the parent was scoped to a System, keep that scope on the replay.
    if parent.system_id:
        req["agent_id"] = parent.system_id

    # Apply top-level overrides.
    for k in _TOPLEVEL_KEYS:
        if k in overrides and overrides[k] is not None:
            req[k] = overrides[k]

    # Model / provider go into agent_preferences.model_preferences.
    model = overrides.get("model")
    provider = overrides.get("provider")
    if model or provider:
        prefs = req.setdefault("agent_preferences", {})
        mp = prefs.setdefault("model_preferences", {})
        if model:
            mp["model"] = model
        if provider:
            mp["provider"] = provider

    # Forward unknown override keys into agent_preferences for forward-compat.
    known = _TOPLEVEL_KEYS | {"model", "provider"}
    extras = {k: v for k, v in overrides.items() if k not in known and v is not None}
    if extras:
        prefs = req.setdefault("agent_preferences", {})
        prefs.setdefault("custom_overrides", {}).update(extras)

    return req


def _is_replayable_chat_run(parent: Run) -> bool:
    """Decide whether this Run can be replayed via the chat orchestrator.

    Returns ``True`` when the parent looks like a chat turn (has a
    ``query`` in input_ref, was triggered by chat or has no system /
    a system but no flow_snapshot indicating engine execution). The
    intent is conservative: when in doubt we say ``False`` so the
    operator gets a 400 with a clear "use the engine path instead"
    message rather than a silent miss-routing.
    """
    inp = parent.input_ref or {}
    if not isinstance(inp, dict):
        return False
    has_query = isinstance(inp.get("query") or inp.get("text"), str) and (
        (inp.get("query") or inp.get("text") or "").strip()
    )
    if not has_query:
        return False
    # Chat trigger is the canonical case.
    if (parent.trigger or "") == "chat":
        return True
    # Replay-of-replay is fine.
    if (parent.trigger or "") == "replay":
        return True
    # No system_id and a query → workspace-wide chat from another path. OK.
    if not parent.system_id:
        return True
    # System-scoped run that ran through the engine (flow_snapshot set
    # → DAG executed). Out of scope for MVP — tell the operator.
    if parent.flow_snapshot:
        return False
    # System-scoped chat (chat from /systems/:id surface). OK.
    return True


async def replay_run_async(
    *,
    db: DBSession,
    parent: Run,
    workspace_slug: str,
    overrides: Dict[str, Any],
    actor: Optional[str] = None,
    source_decision_id: Optional[str] = None,
    source_feedback_id: Optional[str] = None,
) -> Tuple[Run, str]:
    """Drive the orchestrator with the override-patched input and persist
    a new ``Run`` linked back to ``parent``. Returns ``(new_run, response_text)``.

    Errors during orchestration are captured on the new Run
    (status="failed", error=<repr>) so the audit trail matches reality.
    The eval scheduler is best-effort and is *not* invoked when the
    replay failed — there's nothing to score.
    """
    if (parent.status or "") not in ("completed", "failed"):
        raise ReplayError(
            f"parent run is still {parent.status!r}; only settled runs "
            "(completed | failed) can be replayed"
        )
    if not _is_replayable_chat_run(parent):
        raise ReplayError(
            "this run was executed by the system engine (DAG); replay-with-override "
            "is currently only wired for chat-style runs. Open the run and "
            "re-launch from the system page to retry an engine run."
        )

    request_dict = _build_request_dict(
        parent=parent,
        workspace_slug=workspace_slug,
        workspace_id=parent.workspace_id or "",
        overrides=overrides or {},
    )

    # Lazy import to avoid pulling the orchestrator into module-load
    # cycles during tests.
    from app.api.v1.endpoints.agents import get_orchestrator  # type: ignore

    orchestrator = get_orchestrator()
    if not orchestrator:
        raise ReplayError("orchestrator not initialised on this backend")

    started_at = datetime.utcnow()
    started_ts = time.time()

    chunks = []
    error_text: Optional[str] = None
    try:
        async for chunk in orchestrator.process_request(request_dict):
            chunks.append(chunk)
            if chunk.get("is_final"):
                break
    except Exception as exc:  # noqa: BLE001
        error_text = repr(exc)
        logger.error("run_replay: orchestrator failed", error=error_text)

    completed_at = datetime.utcnow()
    duration_ms = int((time.time() - started_ts) * 1000)

    response_text = "".join(
        c.get("content", "") for c in chunks if c.get("chunk_type") == "text"
    )
    sources = []
    reasoning_trace: Optional[Any] = None
    for c in chunks:
        if c.get("chunk_type") == "sources" and isinstance(c.get("sources"), list):
            sources = c["sources"]
        if c.get("chunk_type") == "reasoning_trace":
            reasoning_trace = c.get("reasoning_trace") or c.get("trace")

    new_run = Run(
        id=str(uuid.uuid4()),
        workspace_id=parent.workspace_id,
        system_id=parent.system_id,
        capability_id=parent.capability_id,
        status=("completed" if not error_text else "failed"),
        trigger="replay",
        parent_run_id=parent.id,
        replay_overrides=overrides or {},
        input_ref={"query": request_dict.get("query") or ""},
        output_ref={
            "response": response_text,
            "sources": sources or [],
            "reasoning_trace": reasoning_trace,
        },
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        error=error_text,
    )
    db.add(new_run)

    emit_audit_event(
        workspace_id=parent.workspace_id,
        event_type="run.replayed",
        actor=actor or "demo-user",
        details={
            "parent_run_id": parent.id,
            "new_run_id": new_run.id,
            "overrides": overrides or {},
            "source_decision_id": source_decision_id,
            "source_feedback_id": source_feedback_id,
            "status": new_run.status,
            "duration_ms": duration_ms,
        },
        db=db,
    )
    db.commit()

    if not error_text:
        try:
            schedule_eval(new_run.id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "run_replay: schedule_eval failed",
                run_id=new_run.id,
                error=str(exc),
            )

    return new_run, response_text
