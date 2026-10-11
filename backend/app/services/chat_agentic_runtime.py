"""Production adapter between the chat surface and a governed Agentic DAG."""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chat_execution_policy import ChatExecutionDecision
from app.services.rag.decision_trace import build_retrieval_decision_trace
from app.services.run_engine.dag import execute_run_dag
from app.services.run_engine.events import bus as event_bus
from app.services.systems import flow_ingress, flow_publication

logger = get_logger(__name__)

RETRIEVAL_SKILLS = frozenset({"semantic_search_v1", "multi_hop_retrieve_v1"})
POLICY_FAILURE_PREFIXES = ("membrane_", "policy_", "hitl_")
TECHNICAL_RETRIEVAL_MARKERS = (
    "unavailable",
    "deadline",
    "timeout",
    "error",
    "exception",
    "connection",
    "backend",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _answer_from_output(output_ref: Any) -> str:
    output = _as_dict(output_ref)
    for key in ("answer", "response", "clarifying_question", "reason"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalise_sources(value: Any) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(value), start=1):
        if not isinstance(raw, Mapping):
            continue
        raw_source = dict(raw)
        metadata = _as_dict(raw_source.get("metadata"))
        title = (
            raw_source.get("title")
            or raw_source.get("filename")
            or raw_source.get("document")
            or metadata.get("document_title")
            or metadata.get("document_filename")
            or metadata.get("filename")
            or f"Source {index}"
        )
        # Never return the raw vector-store metadata object: it can contain
        # internal paths/object keys. Project only the public citation schema.
        source = {
            "index": raw_source.get("index") or index,
            "id": raw_source.get("id") or raw_source.get("chunk_id"),
            "source_id": raw_source.get("source_id")
            or raw_source.get("chunk_id")
            or raw_source.get("id"),
            "document": raw_source.get("document") or str(title),
            "title": str(title),
            "filename": raw_source.get("filename")
            or metadata.get("document_filename")
            or metadata.get("filename"),
            "document_id": raw_source.get("document_id")
            or metadata.get("document_id")
            or metadata.get("doc_id"),
            "collection": raw_source.get("collection")
            or metadata.get("collection")
            or metadata.get("collection_name")
            or metadata.get("collection_slug"),
            "page": raw_source.get("page") or metadata.get("page") or metadata.get("page_number"),
            "snippet": str(raw_source.get("snippet") or "")[:1000] or None,
            "score": raw_source.get("score"),
        }
        sources.append(source)
    return sources


def _collection_from_row(row: Mapping[str, Any]) -> Optional[str]:
    metadata = _as_dict(row.get("metadata"))
    value = (
        row.get("collection")
        or metadata.get("collection")
        or metadata.get("collection_name")
        or metadata.get("collection_slug")
    )
    return str(value) if value else None


def _retrieval_contract(system: System, run_input: Any = None) -> dict[str, Any]:
    snapshotted = _as_dict(_as_dict(run_input).get("retrieval_contract"))
    return snapshotted or _as_dict(_as_dict(system.settings).get("retrieval_contract"))


def agentic_timeout_seconds(system: System) -> float:
    """Effective deadline, intentionally below the 45s membrane post-check."""

    profile = _as_dict(system.execution_profile)
    try:
        value = float(profile.get("max_runtime_s") or 40.0)
    except (TypeError, ValueError):
        value = 40.0
    return max(1.0, min(44.0, value))


def _create_legacy_chat_run(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    payload: Mapping[str, Any],
    initiated_by_user_id: str | None,
    trigger: str,
) -> Run:
    """Isolated pre-publication path, reachable only while the P1 flag is off."""

    if flow_publication.flow_publication_enabled(workspace):
        raise RuntimeError("legacy chat Run creation is disabled by Flow publication")
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        initiated_by_user_id=initiated_by_user_id,
        system_id=system.id,
        capability_id=getattr(system, "capability_id", None),
        input_ref=deepcopy(dict(payload)),
        flow_snapshot=deepcopy(system.flow_definition or {}),
        status="pending",
        trigger=trigger,
    )
    db.add(run)
    db.flush()
    return run


def create_chat_adapter_run(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    payload: Mapping[str, Any],
    initiated_by_user_id: str | None = None,
    session_id: str | None = None,
    adapter_evidence: Mapping[str, Any] | None = None,
    trigger: str = "chat_agentic",
) -> Run:
    """Create one chat Run through the feature-selected execution authority.

    A publication-enabled workspace never falls through to the mutable legacy
    snapshot.  The published ingress boundary owns ingress selection and
    freezes the version, graph hash, executable contract and surface on the
    Run before the engine can open its separate session.
    """

    if system.workspace_id != workspace.id:
        raise ValueError("chat executor System does not belong to the workspace")
    if flow_publication.flow_publication_enabled(workspace):
        run = flow_ingress.create_published_ingress_run(
            db,
            system_id=system.id,
            workspace=workspace,
            ingress_id=None,
            kind="chat",
            payload=payload,
            initiated_by_user_id=initiated_by_user_id,
            runner_session_id=session_id,
            adapter_evidence={
                **deepcopy(dict(adapter_evidence or {})),
                "surface": "chat",
                "adapter_version": 1,
                "session_bound": bool(session_id),
            },
            trigger=trigger,
        )
    else:
        run = _create_legacy_chat_run(
            db,
            workspace=workspace,
            system=system,
            payload=payload,
            initiated_by_user_id=initiated_by_user_id,
            trigger=trigger,
        )
    db.commit()
    db.refresh(run)
    return run


def create_agentic_chat_run(
    db: DBSession,
    *,
    decision: ChatExecutionDecision,
    workspace_id: str,
    workspace_slug: str,
    user_id: Optional[str],
    session_id: Optional[str],
    query: str,
    conversation_history: list[dict[str, Any]],
    salient_entities: Optional[dict[str, Any]],
    request_context: dict[str, Any],
) -> Run:
    """Create the canonical Run before the engine opens its own DB session."""

    system = decision.executor_system
    if system is None:
        raise ValueError("agentic executor System is required")
    workspace = (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id)
        .populate_existing()
        .one_or_none()
    )
    if workspace is None:
        raise ValueError("chat workspace is required")
    if workspace.slug != workspace_slug:
        raise ValueError("chat workspace slug does not match its workspace id")
    chat_turn_id = str(uuid.uuid4())
    runtime_fields = {
        key: request_context.get(key)
        for key in (
            "top_k",
            "candidate_pool_k",
            "synthesis_k",
            "source_display_k",
            "latency_profile",
            "retrieval_profile",
            "deep_retrieval",
            "rag_pipeline_mode",
            "grounding_mode",
            "grounding_policy",
            "system_prompt",
        )
        if request_context.get(key) is not None
    }
    return create_chat_adapter_run(
        db,
        workspace=workspace,
        system=system,
        initiated_by_user_id=user_id,
        session_id=session_id,
        payload={
            "query": query,
            "conversation_history": conversation_history,
            "salient_entities": salient_entities or {},
            "workspace_slug": workspace_slug,
            "session_id": session_id,
            "user_id": user_id,
            "assistant_profile": request_context.get("assistant_profile"),
            "knowledge_scope": request_context.get("knowledge_scope"),
            "source_policy": request_context.get("source_policy"),
            "context_id": request_context.get("context_id"),
            "context_mode": request_context.get("context_mode"),
            "response_language": request_context.get("response_language"),
            "answer_profile": request_context.get("answer_profile"),
            "answer_profile_decision": request_context.get("answer_profile_decision"),
            "answer_policy": request_context.get("answer_policy"),
            "surface_system_id": request_context.get("surface_system_id"),
            "chat_turn_id": chat_turn_id,
            "chat_execution": decision.ledger(),
            "retrieval_contract": deepcopy(decision.retrieval_contract or {}),
            **runtime_fields,
        },
        adapter_evidence={
            "policy_version": decision.policy_version,
            "policy_mode": decision.mode,
        },
    )


async def iter_agentic_run_events(
    run_id: str,
    *,
    timeout_seconds: float,
) -> AsyncIterator[dict[str, Any]]:
    """Execute and consume the in-process bus in the same request/worker."""

    subscriber = event_bus.subscribe(run_id)
    execution_task: Optional[asyncio.Task[dict[str, Any]]] = asyncio.create_task(
        asyncio.wait_for(execute_run_dag(run_id), timeout=timeout_seconds)
    )
    event_task: Optional[asyncio.Task[Optional[dict[str, Any]]]] = None
    try:
        while True:
            if event_task is None:
                event_task = asyncio.create_task(subscriber.next_event())
            waiting: set[asyncio.Task[Any]] = {event_task}
            if execution_task is not None:
                waiting.add(execution_task)
            done, _ = await asyncio.wait(
                waiting,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if event_task in done:
                event = event_task.result()
                event_task = None
                if event is None:
                    # ``close`` can enqueue the sentinel one event-loop tick
                    # before the executor coroutine returns. Await it so a
                    # completed/HITL Run is never cancelled in ``finally``.
                    if execution_task is not None:
                        await execution_task
                        execution_task = None
                    break
                elif event.get("kind") != "token_delta":
                    # Generation tokens are speculative until response_eval,
                    # self-correction and egress have settled.
                    yield event
            if execution_task is not None and execution_task in done:
                # Do not stop here: node_end/run_end checkpoints and the close
                # sentinel may already be queued behind this task.
                await execution_task
                execution_task = None
                # Defensive for an engine early-return that did not open or
                # close a channel; queued events still drain before sentinel.
                event_bus.close(run_id)
    except TimeoutError:
        logger.warning("agentic chat execution timed out", run_id=run_id, timeout=timeout_seconds)
        if execution_task is not None and not execution_task.done():
            execution_task.cancel()
        if execution_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await execution_task
        execution_task = None
        # Cancellation terminalizes the Run and closes the channel. Drain its
        # persisted terminal checkpoints outside the execution deadline before
        # surfacing the timeout decision.
        if event_task is not None:
            if not event_task.done():
                event_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await event_task
            event_task = None
        while True:
            try:
                event = await asyncio.wait_for(subscriber.next_event(), timeout=1.0)
            except TimeoutError:
                break
            if event is None:
                break
            if event.get("kind") != "token_delta":
                yield event
        yield {
            "kind": "execution_timeout",
            "run_id": run_id,
            "timeout_seconds": timeout_seconds,
        }
    finally:
        if event_task is not None and not event_task.done():
            event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await event_task
        if execution_task is not None and not execution_task.done():
            execution_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await execution_task
        await subscriber.aclose()


_NODE_TYPES = {
    "source.request": "query_analysis",
    "plan.thinking": "thought",
    "decision.route_mode": "routing",
    "task.retrieve_fast": "retrieve",
    "task.retrieve_balanced": "retrieve",
    "task.retrieve_deep": "retrieve",
    "task.retrieve_multihop": "retrieve",
    "join.retrieval": "retrieve",
    "task.generate": "synthesis",
    "task.response_eval": "evaluation",
    "decision.verdict": "evaluation",
    "task.self_correct": "synthesis",
    "decision.egress_gate": "evaluation",
    "decision.deliver": "routing",
}


def agentic_event_chunks(event: Mapping[str, Any], *, run_id: str) -> list[dict[str, Any]]:
    """Map run-engine checkpoints to the append-only chat SSE contract."""

    kind = str(event.get("kind") or "")
    if kind == "execution_timeout":
        return [
            {
                "chunk_type": "decision_step",
                "decision_step": {
                    "id": f"agentic:{run_id}:timeout",
                    "type": "evaluation",
                    "status": "warning",
                    "title": "Budget agentique atteint",
                    "description": "Bascule contrôlée vers le moteur classique.",
                    "metrics": {"timeout_seconds": event.get("timeout_seconds")},
                },
                "run_id": run_id,
                "is_final": False,
            }
        ]
    if kind not in {"node_start", "node_end", "run_start", "run_end"}:
        return []
    node_id = "run" if kind in {"run_start", "run_end"} else str(event.get("node_id") or kind)
    status = "active" if kind in {"run_start", "node_start"} else "completed"
    if event.get("status") in {"failed", "cancelled"} or event.get("error"):
        status = "error"
    step_type = _NODE_TYPES.get(node_id, "thought")
    skipped = kind == "node_end" and event.get("status") == "skipped"
    title = str(event.get("label") or node_id.replace(".", " ").replace("_", " ").title())
    metrics = {
        key: event.get(key)
        for key in ("skill_slug", "latency_ms", "cost", "chosen_branch", "status")
        if event.get(key) is not None
    }
    chunks = [
        {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": f"agentic:{run_id}:{node_id}",
                "type": step_type,
                "status": status,
                "title": title,
                "description": (
                    "Branche non retenue par le routeur"
                    if skipped
                    else "Exécution du graphe gouverné Agentium"
                ),
                "duration": event.get("latency_ms"),
                "metrics": metrics,
            },
            "run_id": run_id,
            "route": "agentic",
            "is_final": False,
        }
    ]
    if step_type == "retrieve" and kind == "node_start":
        chunks.append(
            {
                "chunk_type": "retrieval",
                "phase": "started",
                "content": "",
                "message": "Recherche agentique dans le corpus autorisé",
                "details": {"route": "agentic", "node_id": node_id},
                "run_id": run_id,
                "is_final": False,
            }
        )
    return chunks


@dataclass
class AgenticChatOutcome:
    run_id: str
    status: str
    answer: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    fallback_reason: Optional[str] = None
    policy_terminal: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and bool(self.answer) and not self.policy_terminal

    @property
    def should_fallback(self) -> bool:
        return not self.succeeded and not self.policy_terminal


def load_agentic_chat_outcome(
    db: DBSession,
    *,
    run_id: str,
    system: System,
) -> AgenticChatOutcome:
    """Read the terminal sink, retrieval proof and policy state in one place."""

    db.expire_all()
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        return AgenticChatOutcome(
            run_id=run_id,
            status="failed",
            fallback_reason="agentic_run_missing",
        )
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run_id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    by_slug: dict[str, list[SkillInvocation]] = {}
    for invocation in invocations:
        by_slug.setdefault(str(invocation.skill_slug or ""), []).append(invocation)
    output = _as_dict(run.output_ref)
    sources = _normalise_sources(output.get("citations") or output.get("sources"))
    answer = _answer_from_output(output)
    plan_output = (
        _as_dict((by_slug.get("chat_agentic_plan_v1") or [None])[-1].output_ref)
        if by_slug.get("chat_agentic_plan_v1")
        else {}
    )
    eval_output = (
        _as_dict((by_slug.get("response_eval_v1") or [None])[-1].output_ref)
        if by_slug.get("response_eval_v1")
        else {}
    )
    retrieval_outputs = [
        _as_dict(invocation.output_ref)
        for slug in RETRIEVAL_SKILLS
        for invocation in by_slug.get(slug, [])
        if invocation.status == "completed"
    ]
    collections_touched: list[str] = []
    raw_chunks = 0
    retrieval_scope = None
    retrieval_failure_reasons: list[str] = []
    stage_timings: dict[str, Any] = {}
    for invocation in invocations:
        if invocation.latency_ms is not None:
            stage_timings[str(invocation.skill_slug or invocation.id)] = float(
                invocation.latency_ms
            )
    for retrieval in retrieval_outputs:
        retrieval_reason = str(retrieval.get("fallback_reason") or "").strip().lower()
        if retrieval_reason:
            retrieval_failure_reasons.append(retrieval_reason)
        try:
            raw_chunks += int(
                retrieval.get("raw_chunks_retrieved") or len(_as_list(retrieval.get("results")))
            )
        except (TypeError, ValueError):
            pass
        retrieval_scope = retrieval_scope or retrieval.get("retrieval_scope")
        for value in _as_list(retrieval.get("collections_touched")):
            collection = str(value).strip()
            if collection and collection not in collections_touched:
                collections_touched.append(collection)
        for row in _as_list(retrieval.get("results")):
            if isinstance(row, Mapping):
                collection = _collection_from_row(row)
                if collection and collection not in collections_touched:
                    collections_touched.append(collection)
    for source in sources:
        collection = _collection_from_row(source)
        if collection and collection not in collections_touched:
            collections_touched.append(collection)

    contract = _retrieval_contract(system, run.input_ref)
    expected_collection = contract.get("collection") or contract.get("primary_collection")
    outside = [
        item for item in collections_touched if expected_collection and item != expected_collection
    ]
    failed_invocations = [item for item in invocations if item.status in {"failed", "cancelled"}]
    policy_terminal = (
        run.status in {"hitl_pending", "debug_pending"}
        or str(run.error or "").startswith(POLICY_FAILURE_PREFIXES)
        or str(run.decision or "") == "hitl_escalated"
    )
    retrieval_attempted = bool(retrieval_outputs)
    technical_retrieval_failure = any(
        marker in reason
        for reason in retrieval_failure_reasons
        for marker in TECHNICAL_RETRIEVAL_MARKERS
    )
    fallback_reason: Optional[str] = None
    effective_status = str(run.status or "failed")
    if outside:
        # A source outside the declared corpus is a grounding-policy stop, not
        # a reason to expose the speculative draft or widen to classic search.
        answer = (
            "Je ne peux pas diffuser cette réponse : les preuves récupérées "
            "sortent de la collection autorisée."
        )
        sources = []
        effective_status = "completed"
        policy_terminal = True
        fallback_reason = "retrieval_collection_contract_breach"
        run.status = "failed"
        run.error = fallback_reason
    elif run.status in {"hitl_pending", "debug_pending"}:
        answer = "Cette réponse nécessite une validation experte avant d’être diffusée."
        sources = []
        effective_status = "completed"
    elif policy_terminal:
        answer = "Cette réponse a été retenue par les règles de gouvernance Agentium."
        sources = []
        effective_status = "completed"
        fallback_reason = str(run.error or "agentic_policy_blocked")
    elif run.status != "completed":
        fallback_reason = str(run.error or f"agentic_run_{run.status}")
    elif failed_invocations:
        effective_status = "failed"
        fallback_reason = "agentic_skill_failed"
    elif (
        expected_collection
        and retrieval_attempted
        and raw_chunks == 0
        and not sources
        and technical_retrieval_failure
    ):
        effective_status = "failed"
        fallback_reason = "agentic_retrieval_unavailable"
    elif expected_collection and retrieval_attempted and raw_chunks == 0 and not sources:
        # The contract explicitly says ``empty_bound_collection=abstain``.
        # Classic fallback would silently violate the authoritative boundary.
        answer = (
            f"Je n’ai trouvé aucune preuve exploitable dans la collection "
            f"{expected_collection} pour répondre de façon documentée."
        )
        sources = []
        effective_status = "completed"
        policy_terminal = True
        fallback_reason = "authoritative_collection_empty"
    elif not answer:
        effective_status = "failed"
        fallback_reason = "agentic_answer_empty"
    elif output.get("answer") and not sources:
        # The governed runtime is citation-required. Falling back after an
        # uncited draft would bypass the same membrane in a different engine.
        answer = "Je ne peux pas fournir de réponse documentée sans source vérifiable."
        sources = []
        effective_status = "completed"
        policy_terminal = True
        fallback_reason = "agentic_answer_without_citations"

    execution = _as_dict(_as_dict(run.input_ref).get("execution"))
    chat_execution = _as_dict(_as_dict(run.input_ref).get("chat_execution"))
    terminal_route = "agentic"
    if policy_terminal and run.status in {"hitl_pending", "debug_pending"}:
        terminal_route = "agentic_review"
    elif policy_terminal and fallback_reason == "authoritative_collection_empty":
        terminal_route = "agentic_abstain"
    elif policy_terminal:
        terminal_route = "agentic_blocked"
    retrieval_plan = {
        "mode": plan_output.get("mode"),
        "retrieval": plan_output.get("retrieval"),
        "sub_queries": plan_output.get("sub_queries") or [],
    }
    retrieval_metrics = {
        "pipeline": "agentic_dag",
        "raw_chunks_retrieved": raw_chunks,
        "candidate_counts": {"chunks_retrieved": raw_chunks},
        "collections_touched": collections_touched,
        "collection": expected_collection,
        "expected_collection": expected_collection,
        "retrieval_plan": retrieval_plan,
        "retrieval_scope": retrieval_scope,
        "stage_timings": stage_timings,
        "fallback_reason": fallback_reason,
    }
    retrieval_decision_trace = build_retrieval_decision_trace(
        request=_as_dict(run.input_ref),
        context={
            "collection": expected_collection,
            "collections_touched": collections_touched,
            "source_policy": _as_dict(run.input_ref).get("source_policy"),
        },
        metrics=retrieval_metrics,
    )
    metadata = {
        "route": terminal_route,
        "chat_turn_id": _as_dict(run.input_ref).get("chat_turn_id"),
        "chat_execution": chat_execution,
        "flow_revision": execution.get("flow_revision")
        or _as_dict(system.settings).get("flow_revision"),
        "flow_sha256": execution.get("flow_sha256"),
        "answer_profile": plan_output.get("answer_profile")
        or _as_dict(run.input_ref).get("answer_profile"),
        "retrieval_plan": retrieval_plan,
        "retrieval_scope": retrieval_scope,
        "retrieval_decision_trace": retrieval_decision_trace,
        "retrieval_metrics": retrieval_metrics,
        "collections_touched": collections_touched,
        "quality": eval_output,
        "fallback_reason": fallback_reason,
        "sources": sources,
    }
    run.output_ref = {
        **output,
        **metadata,
        "answer": answer,
        "sources": sources,
        "chat_adapter_finalized": True,
    }
    db.commit()
    return AgenticChatOutcome(
        run_id=run_id,
        status=effective_status,
        answer=answer,
        sources=sources,
        metadata=metadata,
        fallback_reason=fallback_reason,
        policy_terminal=policy_terminal,
    )


def mark_agentic_fallback(
    db: DBSession,
    *,
    run_id: str,
    reason: str,
) -> dict[str, Any]:
    """Annotate the attempt so its classic continuation is explainable."""

    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        return {"agentic_attempt_run_id": run_id, "fallback_reason": reason}
    output = _as_dict(run.output_ref)
    execution = _as_dict(output.get("chat_execution"))
    execution.update({"fallback": "classic", "fallback_reason": reason})
    run.output_ref = {**output, "chat_execution": execution, "fallback_reason": reason}
    db.commit()
    return {
        "agentic_attempt_run_id": run_id,
        "fallback_reason": reason,
        "chat_turn_id": _as_dict(run.input_ref).get("chat_turn_id"),
    }


def finalize_resumed_agentic_chat(run_id: str) -> Optional[AgenticChatOutcome]:
    """Replace a persisted HITL placeholder after the immutable Run resumes."""

    from app.db.base import SessionLocal
    from app.models.user import Message
    from app.models.user import Session as ChatSession
    from app.services.evaluation.auto_eval import schedule_eval
    from app.services.industrial_answer_profile import apply_answer_policy_to_text

    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id, Run.trigger == "chat_agentic").first()
        if run is None or run.status not in {"completed", "failed"}:
            return None
        if (
            _as_dict(run.output_ref).get("chat_adapter_finalized") is True
            and _as_dict(run.output_ref).get("resumed_after_hitl") is True
        ):
            # Acks-late redelivery may replay the durable post-resume hook.
            # The first successful finalization is authoritative.
            return None
        system = db.query(System).filter(System.id == run.system_id).first()
        if system is None:
            return None
        system_settings = _as_dict(system.settings)
        system_flow = _as_dict(run.flow_snapshot or system.flow_definition)
        if (
            system.workspace_id != run.workspace_id
            or system_settings.get("system_type") != "chat_agentic"
            or system_flow.get("variant") != "chat_agentic_thinking_v1"
        ):
            logger.warning(
                "refusing resumed chat finalization for an untrusted System",
                run_id=run_id,
                system_id=system.id,
            )
            return None

        decision_status = next(
            (
                str(checkpoint.get("decision_status") or "")
                for checkpoint in reversed(_as_list(run.checkpoints))
                if isinstance(checkpoint, Mapping) and checkpoint.get("kind") == "hitl_resume"
            ),
            "",
        )
        rejected = decision_status == "rejected"
        if rejected:
            outcome = AgenticChatOutcome(
                run_id=run.id,
                status="completed",
                answer="La réponse a été rejetée lors de la validation experte.",
                sources=[],
                metadata={"route": "agentic_review_rejected", "hitl_decision": "rejected"},
                fallback_reason="hitl_rejected",
                policy_terminal=True,
            )
        else:
            outcome = load_agentic_chat_outcome(db, run_id=run_id, system=system)
        run = db.query(Run).filter(Run.id == run_id).one()
        run_input = _as_dict(run.input_ref)
        if rejected:
            content = outcome.answer
            violations = []
        elif outcome.succeeded or outcome.policy_terminal:
            content, violations = apply_answer_policy_to_text(
                outcome.answer,
                answer_policy=_as_dict(run_input.get("answer_policy")) or None,
                profile_decision=_as_dict(run_input.get("answer_profile_decision")) or None,
            )
        else:
            content = (
                "La reprise après validation experte n’a pas pu produire une "
                "réponse documentée. Vous pouvez relancer la question."
            )
            violations = []
        adapter = _as_dict(run_input.get("chat_adapter"))
        message_id = adapter.get("assistant_message_id")
        session_id = adapter.get("session_id")
        adapter_token = adapter.get("token")
        message = None
        if (
            message_id
            and session_id
            and adapter.get("origin") == "chat_endpoint_v1"
            and isinstance(adapter_token, str)
            and adapter_token
        ):
            message_query = (
                db.query(Message)
                .join(ChatSession, ChatSession.id == Message.session_id)
                .filter(
                    Message.id == message_id,
                    Message.session_id == session_id,
                    Message.role == "assistant",
                    ChatSession.workspace_id == run.workspace_id,
                )
            )
            if run.initiated_by_user_id:
                message_query = message_query.filter(
                    ChatSession.user_id == run.initiated_by_user_id
                )
            else:
                message_query = message_query.filter(ChatSession.user_id.is_(None))
            candidate = message_query.first()
            candidate_meta = _as_dict(candidate.meta_data) if candidate is not None else {}
            if (
                candidate is not None
                and candidate_meta.get("run_id") == run.id
                and candidate_meta.get("chat_adapter_token") == adapter_token
            ):
                message = candidate

        if message_id and message is None:
            safe_reason = "chat_adapter_provenance_invalid"
            logger.warning(
                "refusing resumed chat message update with invalid provenance",
                run_id=run.id,
                message_id=message_id,
            )
            run.output_ref = {
                **_as_dict(run.output_ref),
                "answer": "La validation experte est terminée, mais le message lié n’a pas pu être vérifié.",
                "sources": [],
                "fallback_reason": safe_reason,
                "chat_adapter_finalized": False,
            }
            adapter.update({"resumed": True, "finalization_error": safe_reason})
            run.input_ref = {**run_input, "chat_adapter": adapter}
            db.commit()
            return AgenticChatOutcome(
                run_id=run.id,
                status="completed",
                answer=str(_as_dict(run.output_ref).get("answer") or ""),
                sources=[],
                metadata={"route": "agentic_blocked"},
                fallback_reason=safe_reason,
                policy_terminal=True,
            )
        message_metadata = {
            "run_id": run.id,
            "route": outcome.metadata.get("route") or "agentic",
            "sources": outcome.sources,
            "retrieval_metrics": outcome.metadata.get("retrieval_metrics") or {},
            "retrieval_decision_trace": outcome.metadata.get("retrieval_decision_trace"),
            "answer_policy_violations": violations,
            "resumed_after_hitl": True,
            "hitl_decision": decision_status or None,
        }
        if message is not None:
            message.content = content
            message.meta_data = {**_as_dict(message.meta_data), **message_metadata}
        if rejected:
            # A rejected draft is outside the publication boundary.  Replace
            # the whole public output envelope rather than merging it so stale
            # citations, snippets or alternate answer keys cannot survive.
            run.output_ref = {
                "answer": content,
                "sources": [],
                "route": "agentic_review_rejected",
                "fallback_reason": "hitl_rejected",
                "hitl_decision": "rejected",
                "assistant_message_id": message_id,
                "answer_policy_violations": [],
                "chat_adapter_finalized": True,
                "resumed_after_hitl": True,
            }
            run.decision = "hitl_rejected"
        else:
            run.output_ref = {
                **_as_dict(run.output_ref),
                **outcome.metadata,
                "answer": content,
                "sources": outcome.sources,
                "assistant_message_id": message_id,
                "answer_policy_violations": violations,
                "chat_adapter_finalized": True,
                "resumed_after_hitl": True,
            }
        adapter.update({"policy_terminal": outcome.policy_terminal, "resumed": True})
        run.input_ref = {**run_input, "chat_adapter": adapter}
        db.commit()
        if outcome.succeeded and not rejected:
            try:
                schedule_eval(run.id)
            except Exception as exc:  # noqa: BLE001 - asynchronous best effort
                logger.warning(
                    "agentic resumed chat auto-eval scheduling failed",
                    run_id=run.id,
                    error=str(exc),
                )
        return AgenticChatOutcome(
            run_id=outcome.run_id,
            status=outcome.status,
            answer=content,
            sources=outcome.sources,
            metadata=outcome.metadata,
            fallback_reason=outcome.fallback_reason,
            policy_terminal=outcome.policy_terminal,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
