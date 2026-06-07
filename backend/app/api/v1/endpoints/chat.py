"""Chat/completion endpoints.

Every successful chat turn persists a canonical :class:`Run` so the
auto-eval loop (``schedule_eval → evaluate_run_async``) fires on the
reply. See ``docs/vague-e-plan.md`` 2026-04-25 journal for the product
decision: chat is not a second-class surface, its traffic is the main
driver of Impact + quality metrics, so it must participate in the
same Run ledger as explicit ``/runs/launch`` triggers.
"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.logging import get_logger
from app.core.monitoring import metrics_collector
from app.core.validation import QueryValidator, ResponseValidator
from app.core.errors import ValidationError
from app.core.settings_manager import get_resolved_settings
from app.db.base import get_db
from app.models.run import Run
from app.models.system import System
from app.models.context import Context
from app.models.user import Message, Session as ChatSession, User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.api.v1.endpoints.agents import get_orchestrator
from app.services.evaluation.auto_eval import schedule_eval
from app.services.evaluation.canonical_answer_service import (
    find_canonical_answer,
    record_hit,
)
from app.services.action_plans import action_context_for_chat
from app.services.actions import handle_registry_chat_action, handle_transverse_chat_action
from app.services.chat_grounding import resolve_grounding_policy
from app.services.chat_trivial_bypass import TrivialBypass, maybe_trivial_bypass
from app.services.visual_intelligence import handle_visual_chat_query, visual_context_for_chat
from app.services.workspace_maps import handle_map_chat_query
from app.services.workspace_calendar import calendar_context_for_chat, handle_calendar_chat_action
from app.services.mission_room import briefing_payload, cockpit_payload, news_payload, source_index
logger = get_logger(__name__)
router = APIRouter()
query_validator = QueryValidator()
response_validator = ResponseValidator()


class ChatRequest(BaseModel):
    """Chat completion request"""
    query: str
    session_id: Optional[str] = None
    # System (papAI canonical entity) the chat is scoped to — used to
    # bind the resulting Run to a System for preset resolution +
    # per-System Impact aggregation. Front sends
    # ``agent_id: this.systemId()`` from chat-panel.component.ts;
    # can be NULL for workspace-wide chats (Run is still created).
    agent_id: Optional[str] = None
    agent_preferences: Optional[Dict[str, Any]] = None
    stream: bool = True
    include_reasoning: bool = True
    include_sources: bool = True
    max_tokens: Optional[int] = 2000
    temperature: Optional[float] = 0.3
    top_k: Optional[int] = None
    candidate_pool_k: Optional[int] = None
    synthesis_k: Optional[int] = None
    source_display_k: Optional[int] = None
    latency_profile: Optional[Literal["fast", "balanced", "deep"]] = None
    retrieval_profile: Optional[str] = None
    deep_retrieval: Optional[bool] = None
    retrieval_filters: Optional[Dict[str, Any]] = None
    similarity_threshold: Optional[float] = None
    system_prompt: Optional[str] = None
    # RAG mode: auto | naive | hybrid | hah | chah — see docs/rag-rd-papai-mapping.md
    rag_pipeline_mode: Optional[str] = None
    # Per-query retrieval override (alias of rag_pipeline_mode used by the
    # cockpit chip selector — takes precedence over workspace settings).
    rag_mode_override: Optional[str] = None
    # Reasoning template (factual | analytical | comparative | causal |
    # hypothetical | trivial | auto). When unset or "auto" the orchestrator
    # runs the mode_selector heuristic.
    prompt_type: Optional[str] = None
    # Workspace-scoped Knowledge Scope aggregating one or more collections.
    knowledge_scope: Optional[str] = None
    # Optional Context row selected by the UI. When it carries an
    # ``environment_state.collection`` (or ``knowledge_scope``), retrieval is
    # grounded on that source while the session/run ledger keeps the Context
    # id for replay.
    context_id: Optional[str] = None
    # How a selected session Context interacts with Knowledge Scope retrieval:
    # ``replace`` = use session docs only, ``combine`` = search both the
    # selected Knowledge Scope and the session docs collection.
    context_mode: Optional[str] = None
    # Product-facing assistant profile. It does not bypass backend policy; it
    # carries UI/prompt intent into the Run ledger for audit and replay.
    assistant_profile: Optional[str] = None
    # Answer grounding policy requested by chat-first surfaces. ``balanced`` is
    # intentionally scoped by backend policy and may be downgraded to ``strict``
    # for workspace facts, documents, actions, or sensitive/current claims.
    grounding_mode: Optional[Literal["strict", "balanced"]] = None
    # Deep Search refinement context. These are system/UI supplied hints so the
    # async worker can preserve the shape of the fast answer without asking the
    # user to restate their intent.
    parent_message_id: Optional[str] = None
    previous_answer: Optional[str] = None


def _resolve_system_id(
    db: Session,
    workspace_id: str,
    candidate: Optional[str],
) -> Optional[str]:
    """Validate ``candidate`` as a System FK the current workspace owns.

    Returns the id if it resolves to a real System row scoped to the
    workspace, otherwise ``None``. Prevents cross-workspace FK leaks
    (a malicious client sending another tenant's system_id) and
    gracefully degrades when the front sends a stale id after a
    System was deleted — the Run is still persisted, just unscoped.
    """
    if not candidate:
        return None
    row = (
        db.query(System.id)
        .filter(System.id == candidate, System.workspace_id == workspace_id)
        .first()
    )
    return row[0] if row else None


def _user_id(user: Optional[User]) -> Optional[str]:
    return str(getattr(user, "id", "") or "") or None


def _chat_session_belongs_to_scope(
    db: Session,
    *,
    workspace_id: str,
    user_id: Optional[str],
    candidate: Optional[str],
) -> bool:
    """Return whether a chat session is owned by the current user/workspace."""
    if not candidate:
        return True
    row = (
        db.query(ChatSession.id)
        .filter(
            ChatSession.id == candidate,
            ChatSession.workspace_id == workspace_id,
            ChatSession.status == "active",
        )
    )
    if user_id:
        row = row.filter(ChatSession.user_id == user_id)
    else:
        row = row.filter(ChatSession.user_id.is_(None))
    row = row.first()
    return bool(row)


def _chat_context_signature(payload: Dict[str, Any]) -> str:
    return "|".join(
        str(part)
        for part in (
            payload.get("agent_id") or payload.get("system_id") or "workspace",
            payload.get("context_id") or "no-context",
            payload.get("assistant_profile") or "default-profile",
            payload.get("knowledge_scope") or "workspace-scope",
            payload.get("context_mode") or "no-session-docs",
        )
    )[:512]


def _chat_title_from_query(query: str) -> str:
    title = " ".join(str(query or "").split())
    if not title:
        return "Nouvelle conversation"
    return title[:77].rstrip() + "..." if len(title) > 80 else title


def _ensure_chat_session(
    db: Session,
    *,
    workspace: Workspace,
    user: User,
    request_payload: Dict[str, Any],
) -> ChatSession:
    candidate = request_payload.get("session_id")
    if candidate:
        query = db.query(ChatSession).filter(
            ChatSession.id == candidate,
            ChatSession.workspace_id == workspace.id,
            ChatSession.status == "active",
        )
        user_id = _user_id(user)
        query = query.filter(ChatSession.user_id == user_id) if user_id else query.filter(ChatSession.user_id.is_(None))
        session = query.first()
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return session
    now = datetime.utcnow()
    user_id = _user_id(user)
    signature = _chat_context_signature(request_payload)
    latest_query = db.query(ChatSession).filter(
        ChatSession.workspace_id == workspace.id,
        ChatSession.status == "active",
        ChatSession.context_signature == signature,
    )
    latest_query = latest_query.filter(ChatSession.user_id == user_id) if user_id else latest_query.filter(ChatSession.user_id.is_(None))
    latest = latest_query.order_by(ChatSession.last_activity.desc()).first()
    if latest and (request_payload.get("reuse_latest_session") is not False):
        request_payload["session_id"] = latest.id
        return latest
    context = {
        "system_id": request_payload.get("agent_id"),
        "context_id": request_payload.get("context_id"),
        "context_mode": request_payload.get("context_mode"),
        "assistant_profile": request_payload.get("assistant_profile"),
        "grounding_mode": request_payload.get("grounding_mode"),
        "knowledge_scope": request_payload.get("knowledge_scope"),
        "created_from": "chat_api",
    }
    session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=user_id,
        workspace_id=workspace.id,
        title=None,
        status="active",
        context_signature=signature,
        created_at=now,
        last_activity=now,
        meta_data=context,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    request_payload["session_id"] = session.id
    return session


def _touch_chat_session(
    db: Session,
    session: Optional[ChatSession],
    *,
    query: Optional[str] = None,
) -> None:
    if not session:
        return
    session.last_activity = datetime.utcnow()
    if query and not session.title:
        session.title = _chat_title_from_query(query)


def _resolve_chat_context(
    db: Session,
    *,
    workspace_id: str,
    candidate: Optional[str],
) -> Optional[Context]:
    """Return a workspace-owned Context for chat grounding/audit."""
    if not candidate:
        return None
    return (
        db.query(Context)
        .filter(Context.id == candidate, Context.workspace_id == workspace_id)
        .first()
    )


def _apply_context_to_chat_request(
    request_dict: Dict[str, Any],
    context: Optional[Context],
) -> None:
    """Fold a selected Context into the orchestrator request payload.

    A Context can select either a workspace Knowledge Scope
    (``environment_state.knowledge_scope``) or a direct collection
    (``environment_state.collection``). When ``context_mode=combine`` and the
    UI also selected a Knowledge Scope, the retrieval profile searches both
    layers.
    """
    if not context:
        return
    state = context.environment_state or {}
    data_refs = context.data_refs or []
    request_dict["context_id"] = context.id
    request_context = request_dict.setdefault("context", {})
    request_context.update(
        {
            "context_id": context.id,
            "context_name": context.name,
            "data_refs": data_refs,
            "environment_state": state,
        }
    )
    if isinstance(state, dict):
        knowledge_scope = state.get("knowledge_scope")
        collection = state.get("collection")
        if collection:
            request_dict["context_collection"] = str(collection)
        if not request_dict.get("knowledge_scope") and knowledge_scope:
            request_dict["knowledge_scope"] = str(knowledge_scope)


def _int_budget(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def _apply_retrieval_budget_policy(request_dict: Dict[str, Any]) -> None:
    """Clamp retrieval fan-out before any orchestrator sees the request."""
    agent_preferences = request_dict.get("agent_preferences") if isinstance(request_dict.get("agent_preferences"), dict) else {}
    raw_profile = str(request_dict.get("latency_profile") or agent_preferences.get("latency_profile") or "").strip().lower()
    if request_dict.get("deep_retrieval") or raw_profile == "deep":
        profile = "deep"
    elif raw_profile == "balanced":
        profile = "balanced"
    else:
        profile = "fast"

    explicit_top_k = request_dict.get("top_k") is not None
    explicit_budget = any(
        request_dict.get(key) is not None
        for key in ("candidate_pool_k", "synthesis_k", "source_display_k")
    )
    if profile == "deep":
        top_default = 8
        source_default = 8
        synthesis_default = 24
        candidate_default = 80
    elif profile == "balanced":
        top_default = 8
        source_default = 8
        synthesis_default = 16
        candidate_default = 40
    else:
        top_default = 5
        source_default = 5
        synthesis_default = 12
        candidate_default = 20

    top_k = _int_budget(request_dict.get("top_k"), top_default)
    source_display_default = top_k if explicit_top_k else min(max(top_k, source_default), 24 if profile != "fast" else 8)
    source_display_k = _int_budget(request_dict.get("source_display_k"), source_display_default)
    synthesis_base = top_k if explicit_top_k and not explicit_budget else max(top_k, source_display_k, synthesis_default)
    synthesis_k = _int_budget(request_dict.get("synthesis_k"), synthesis_base)
    candidate_base = top_k if explicit_top_k and not explicit_budget else max(synthesis_k, candidate_default)
    candidate_pool_k = _int_budget(request_dict.get("candidate_pool_k"), candidate_base)

    if profile == "fast":
        top_k = min(top_k, 8)
        source_display_k = min(source_display_k, 8)
        synthesis_k = min(max(synthesis_k, source_display_k), 12)
        candidate_pool_k = min(max(candidate_pool_k, synthesis_k), 20)
    elif profile == "balanced":
        top_k = min(top_k, 12)
        source_display_k = min(source_display_k, 24)
        synthesis_k = min(max(synthesis_k, source_display_k), 24)
        candidate_pool_k = min(max(candidate_pool_k, synthesis_k), 80)
    else:
        top_k = min(top_k, 24)
        source_display_k = min(source_display_k, 24)
        synthesis_k = min(max(synthesis_k, source_display_k), 48)
        candidate_pool_k = min(max(candidate_pool_k, synthesis_k), 200)

    request_dict["latency_profile"] = profile
    request_dict["top_k"] = top_k
    request_dict["source_display_k"] = source_display_k
    request_dict["synthesis_k"] = synthesis_k
    request_dict["candidate_pool_k"] = candidate_pool_k
    request_dict["latency_budget"] = {
        "profile": profile,
        "deadline_seconds": (
            settings.rag_deep_retrieval_deadline_seconds
            if profile == "deep"
            else min(settings.rag_fast_retrieval_deadline_seconds * 2, 20.0)
            if profile == "balanced"
            else settings.rag_fast_retrieval_deadline_seconds
        ),
        "top_k": top_k,
        "candidate_pool_k": candidate_pool_k,
    }


def _persist_trivial_bypass_turn(
    db: Session,
    *,
    workspace: Workspace,
    request: ChatRequest,
    query: str,
    bypass: TrivialBypass,
) -> Optional[str]:
    metadata = {
        "trivial_bypass": True,
        "retrieval_metrics": bypass.metadata(),
    }
    if request.session_id:
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="user",
                content=request.query,
                meta_data={},
            )
        )
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="assistant",
                content=bypass.content,
                meta_data=metadata,
            )
        )
        session = db.query(ChatSession).filter(ChatSession.id == request.session_id).first()
        if session:
            _touch_chat_session(db, session, query=query)
    now = datetime.utcnow()
    run_id = _persist_chat_run(
        db,
        workspace_id=workspace.id,
        system_id=_resolve_system_id(db, workspace.id, request.agent_id),
        query=query,
        response_text=bypass.content,
        sources=[],
        reasoning_trace=None,
        started_at=now,
        completed_at=now,
        duration_ms=0.0,
        trigger="trivial_bypass",
        schedule=False,
        extra_output={
            **metadata,
            "assistant_profile": request.assistant_profile,
            "knowledge_scope": request.knowledge_scope,
            "retrieval_fallback": False,
            "deep_retrieval_recommended": False,
        },
    )
    db.commit()
    return run_id


def _trivial_bypass_completion_payload(run_id: Optional[str], bypass: TrivialBypass) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "content": bypass.content,
        "reasoning_trace": None,
        "sources": [],
        "retrieval_metrics": bypass.metadata(),
        "trivial_bypass": True,
        "deep_retrieval_recommended": False,
        "status": "completed",
    }


def _can_apply_trivial_bypass(
    db: Session,
    *,
    workspace: Workspace,
    request: ChatRequest,
) -> bool:
    """Do not steal short confirmation turns from the action layer."""
    try:
        from app.services.actions.executor import get_awaiting_state

        awaiting = get_awaiting_state(db, workspace, session_id=request.session_id)
        return not bool(awaiting)
    except Exception as exc:  # noqa: BLE001 - bypass is optional.
        logger.debug("chat: trivial bypass awaiting-state check failed", error=str(exc))
        return False


def _persist_chat_run(
    db: Session,
    *,
    workspace_id: str,
    system_id: Optional[str],
    query: str,
    response_text: str,
    sources: Any,
    reasoning_trace: Any,
    started_at: datetime,
    completed_at: datetime,
    duration_ms: Optional[float],
    trigger: str = "chat",
    schedule: bool = True,
    extra_output: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Persist a canonical Run for a completed chat turn + kick off eval.

    Returns the run id, or ``None`` if the Run couldn't be created (we
    swallow errors to keep chat bulletproof — audit trail is best-effort,
    a failed insert must never break the user's reply). The auto-eval
    loop is fire-and-forget: ``schedule_eval`` returns immediately and
    the judge pass runs on a background task/thread.
    """
    if not response_text.strip():
        return None
    try:
        run = Run(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            system_id=system_id,
            status="completed",
            input_ref={"query": query},
            output_ref={
                "response": response_text,
                "sources": sources or [],
                "reasoning_trace": reasoning_trace or None,
                **(extra_output or {}),
            },
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            trigger=trigger,
        )
        db.add(run)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("chat: failed to persist Run", error=str(exc))
        return None

    if schedule:
        # Fire-and-forget — will no-op if the workspace preset is disabled,
        # or if sample_rate excluded this turn.
        try:
            schedule_eval(run.id)
        except Exception as exc:  # noqa: BLE001
            logger.error("chat: schedule_eval failed", run_id=run.id, error=str(exc))

    return run.id


def _canonical_answer_hit(db: Session, *, workspace_id: str, query: str):
    """Return a canonical answer match and record the hit in the session."""
    match = find_canonical_answer(db, workspace_id=workspace_id, query=query)
    if not match:
        return None
    row, score = match
    record_hit(db, canonical_answer=row, query=query, score=score)
    return row, score


def _sse_data(payload: Any) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _sse_done() -> str:
    return "data: [DONE]\n\n"


def _error_chunk(
    code: str,
    content: str,
    *,
    recoverable: bool = False,
    details: Optional[Dict[str, Any]] = None,
    is_final: bool = True,
) -> Dict[str, Any]:
    return {
        "chunk_type": "error",
        "code": code,
        "content": content,
        "recoverable": recoverable,
        "details": details or {},
        "is_final": is_final,
    }


def _collect_chat_chunk(
    chunk: Dict[str, Any],
    *,
    full_content: list[str],
    decision_steps: list[Dict[str, Any]],
    state: Dict[str, Any],
) -> None:
    if chunk.get("chunk_type") == "text":
        full_content.append(chunk.get("content", ""))
    if chunk.get("reasoning_trace"):
        state["reasoning_trace"] = chunk.get("reasoning_trace")
    if chunk.get("sources"):
        state["sources"] = chunk.get("sources")
    if chunk.get("chunk_type") == "retrieval":
        details = chunk.get("details") or {}
        if chunk.get("rag_context"):
            state["rag_context"] = chunk.get("rag_context")
        if details:
            state["retrieval_metrics"] = details
        if details.get("task_id"):
            state["retrieval_worker_task_id"] = details.get("task_id")
        if details.get("fallback"):
            state["retrieval_fallback"] = details.get("fallback_reason") or True
        if details.get("scope"):
            state["knowledge_scope"] = details.get("scope")
        if details.get("collections_touched"):
            state["collections_touched"] = details.get("collections_touched")
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
            "latency_budget",
            "score_threshold_applied",
            "deep_retrieval_recommended",
            "deep_job_id",
            "deep_poll_url",
            "deep_status",
        ):
            if details.get(key) is not None:
                state[key] = details.get(key)
    if chunk.get("chunk_type") == "decision_step" and chunk.get("decision_step"):
        decision_step = chunk.get("decision_step")
        existing_index = next(
            (i for i, ds in enumerate(decision_steps) if ds.get("id") == decision_step.get("id")),
            None,
        )
        if existing_index is not None:
            decision_steps[existing_index] = decision_step
        else:
            decision_steps.append(decision_step)


def _retrieval_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    metrics = state.get("retrieval_metrics")
    return metrics if isinstance(metrics, dict) else {}


def _retrieval_fallback_reason(state: Dict[str, Any]) -> Optional[Any]:
    fallback = state.get("retrieval_fallback")
    if isinstance(fallback, str) and fallback:
        return fallback
    reason = _retrieval_metrics(state).get("fallback_reason")
    return reason if reason else None


def _dense_fast_degraded_reply(state: Dict[str, Any]) -> Optional[str]:
    metrics = _retrieval_metrics(state)
    dense_policy = str(state.get("dense_policy") or metrics.get("dense_policy") or "")
    fallback_reason = str(_retrieval_fallback_reason(state) or "")
    if dense_policy != "fast_scoped_dense_auto" or fallback_reason != "dense_unscoped_fast_policy":
        return None
    scope = state.get("retrieval_scope") if isinstance(state.get("retrieval_scope"), dict) else {}
    try:
        source_count = int(scope.get("source_count") or metrics.get("source_count") or 0)
    except (TypeError, ValueError):
        source_count = 0
    try:
        chunk_count = int(scope.get("chunk_count") or metrics.get("chunk_count") or 0)
    except (TypeError, ValueError):
        chunk_count = 0
    parts = [
        "Cette collection est trop dense pour une recherche globale instantanee.",
        "J'ai donc evite le balayage complet des chunks et garde Quick Ask sur un perimetre sur.",
    ]
    if source_count or chunk_count:
        parts.insert(
            1,
            f"Inventaire detecte: {source_count:,} sources et {chunk_count:,} chunks.".replace(",", " "),
        )
    if state.get("deep_job_id"):
        parts.append("Un Deep Retrieval est deja en file pour raffiner la reponse en arriere-plan.")
    else:
        parts.append("Je lance un Deep Retrieval asynchrone pour raffiner la reponse sans bloquer le chat.")
    return " ".join(parts)


_SYSTEM_RETRIEVAL_FILTER_KEYS = {
    "collection",
    "collection_slug",
    "document_id",
    "document_filename",
    "source_kind",
    "extension",
    "status",
    "project_code",
    "archive_name",
    "language",
}


def _clean_system_retrieval_filter_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        out: list[Any] = []
        for item in value:
            cleaned = _clean_system_retrieval_filter_value(item)
            if cleaned is not None and cleaned not in out:
                out.append(cleaned)
        return out or None
    return None


def _inferred_scope_filters(state: Dict[str, Any]) -> Dict[str, Any]:
    scope = state.get("retrieval_scope")
    if not isinstance(scope, dict):
        metrics_scope = _retrieval_metrics(state).get("retrieval_scope")
        scope = metrics_scope if isinstance(metrics_scope, dict) else {}
    raw_filters = scope.get("filters") if isinstance(scope, dict) else {}
    if not isinstance(raw_filters, dict):
        return {}
    filters: Dict[str, Any] = {}
    for key, value in raw_filters.items():
        if key not in _SYSTEM_RETRIEVAL_FILTER_KEYS:
            continue
        cleaned = _clean_system_retrieval_filter_value(value)
        if cleaned is not None:
            filters[key] = cleaned
    return filters


def _merge_inferred_retrieval_filters(
    request_dict: Dict[str, Any],
    state: Dict[str, Any],
) -> tuple[Dict[str, Any], list[str]]:
    inferred = _inferred_scope_filters(state)
    if not inferred:
        return {}, []
    existing = (
        dict(request_dict.get("retrieval_filters"))
        if isinstance(request_dict.get("retrieval_filters"), dict)
        else {}
    )
    merged = dict(existing)
    forwarded: list[str] = []
    for key, value in inferred.items():
        if key in merged and _clean_system_retrieval_filter_value(merged.get(key)) is not None:
            continue
        merged[key] = value
        forwarded.append(key)
    request_dict["retrieval_filters"] = merged
    return merged, forwarded


def _should_queue_auto_deep_retrieval(request_dict: Dict[str, Any], state: Dict[str, Any]) -> bool:
    if not settings.rag_auto_deep_retrieval_enabled:
        return False
    if request_dict.get("deep_retrieval") or request_dict.get("latency_profile") == "deep":
        return False
    if state.get("deep_job_id"):
        return False

    metrics = _retrieval_metrics(state)
    dense_policy = str(state.get("dense_policy") or metrics.get("dense_policy") or "")
    fallback_reason = _retrieval_fallback_reason(state)
    recommended = bool(
        state.get("deep_retrieval_recommended")
        or metrics.get("deep_retrieval_recommended")
        or fallback_reason in {
            "retrieval_deadline_exceeded",
            "worker_timeout",
            "worker_error",
            "dense_unscoped_fast_policy",
        }
    )
    if not recommended:
        return False

    try:
        confidence = float(state.get("scope_confidence") or metrics.get("scope_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        chunks_retrieved = int(metrics.get("chunks_retrieved") or 0)
    except (TypeError, ValueError):
        chunks_retrieved = 0
    no_context = bool(metrics.get("no_context") or chunks_retrieved == 0)
    degraded_reasons = {
        "retrieval_deadline_exceeded",
        "worker_timeout",
        "worker_error",
        "document_service_unavailable",
    }
    if str(fallback_reason or "") in degraded_reasons:
        return True
    if dense_policy.startswith("fast_scoped_dense") and no_context:
        return confidence < float(settings.rag_auto_deep_retrieval_min_confidence)
    if dense_policy == "fast_scoped_dense_auto":
        return bool(settings.rag_auto_deep_retrieval_dense_unscoped)
    return False


def _compact_job_text(value: Any, *, max_chars: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _compact_job_sources(sources: Any, *, limit: int = 8) -> list[Dict[str, Any]]:
    if not isinstance(sources, list):
        return []
    allowed = (
        "id",
        "document_id",
        "title",
        "filename",
        "source",
        "source_name",
        "collection",
        "collection_name",
        "collection_slug",
        "page",
        "score",
        "source_kind",
        "extension",
        "project_code",
        "archive_name",
        "snippet",
        "content",
        "text",
        "metadata",
    )
    metadata_allowed = {
        "chunk_id",
        "chunk_index",
        "document_id",
        "document_title",
        "document_filename",
        "source_kind",
        "extension",
        "project_code",
        "archive_name",
        "language",
        "status",
        "page",
        "section",
        "section_title",
    }
    compact: list[Dict[str, Any]] = []
    for raw in sources[: max(0, limit)]:
        if not isinstance(raw, dict):
            continue
        item: Dict[str, Any] = {}
        for key in allowed:
            value = raw.get(key)
            if value is None:
                continue
            if key in {"snippet", "content", "text"}:
                item[key] = _compact_job_text(value)
            elif key == "metadata" and isinstance(value, dict):
                item[key] = {
                    meta_key: meta_value
                    for meta_key, meta_value in value.items()
                    if meta_key in metadata_allowed and meta_value is not None
                }
            elif isinstance(value, (str, int, float, bool)):
                item[key] = value
        if item:
            compact.append(item)
    return compact


def _queue_auto_deep_retrieval_job(
    *,
    db: Session,
    workspace: Workspace,
    user: Optional[User],
    request_dict: Dict[str, Any],
    state: Dict[str, Any],
    partial_answer: Optional[str] = None,
    partial_sources: Any = None,
    parent_message_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not _should_queue_auto_deep_retrieval(request_dict, state):
        return None

    from app.models.knowledge_collection import KnowledgeCollection
    from app.services.rag.context import get_retrieval_profile
    from app.services.workspace_jobs import create_workspace_job, dispatch_workspace_job, serialize_job

    payload = dict(request_dict)
    payload["latency_profile"] = "deep"
    payload["deep_retrieval"] = True
    payload["auto_deep_retrieval"] = True
    _, forwarded_filter_keys = _merge_inferred_retrieval_filters(payload, state)
    for key in ("top_k", "candidate_pool_k", "synthesis_k", "source_display_k"):
        payload.pop(key, None)
    _apply_retrieval_budget_policy(payload)
    profile = get_retrieval_profile(payload)
    collection_ref = profile.get("collection")
    collection = None
    if collection_ref:
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                ((KnowledgeCollection.slug == collection_ref) | (KnowledgeCollection.id == collection_ref)),
                KnowledgeCollection.workspace_id == workspace.id,
            )
            .first()
        )
    session_id = str(payload.get("session_id") or "")
    message_id = None
    if session_id:
        placeholder = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Recherche approfondie lancée pour affiner cette réponse.",
            meta_data={
                "deep_status": "queued",
                "deep_stage": "queued",
                "deep_poll_url": None,
                "parent_message_id": parent_message_id,
                "sources": [],
            },
        )
        db.add(placeholder)
        db.flush()
        message_id = placeholder.id
    compact_sources = _compact_job_sources(partial_sources)
    partial_result: Dict[str, Any] = {}
    if partial_answer and partial_answer.strip():
        answer_preview = " ".join(partial_answer.split())
        partial_result["answer_preview"] = answer_preview[:3997] + "..." if len(answer_preview) > 4000 else answer_preview
    if compact_sources:
        partial_result["sources_preview"] = compact_sources
    metrics = _retrieval_metrics(state)
    fallback_reason = _retrieval_fallback_reason(state)
    if metrics:
        partial_result["retrieval_summary"] = {
            "chunks_retrieved": metrics.get("chunks_retrieved"),
            "fallback_reason": fallback_reason,
            "dense_policy": state.get("dense_policy") or metrics.get("dense_policy"),
            "scope_confidence": state.get("scope_confidence") or metrics.get("scope_confidence"),
        }
    job = create_workspace_job(
        db,
        workspace,
        user,
        title=f"Deep Search · {str(payload.get('query') or '')[:96]}",
        input_ref={
            "request": payload,
            "latency_profile": "deep",
            "trigger": "auto_fast_refinement",
            "partial_result": partial_result or None,
            "parent_retrieval": {
                "dense_policy": state.get("dense_policy"),
                "scope_confidence": state.get("scope_confidence"),
                "scope_reason": state.get("scope_reason"),
                "fallback_reason": fallback_reason,
                "retrieval_scope": state.get("retrieval_scope"),
                "inferred_filters_forwarded": bool(forwarded_filter_keys),
                "forwarded_filter_keys": forwarded_filter_keys,
            },
        },
        collection_id=collection.id if collection else None,
        kind="rag_deep_retrieval",
        session_id=session_id or None,
        parent_message_id=parent_message_id,
        message_id=message_id,
        status="queued",
    )
    if message_id:
        placeholder.meta_data = {
            **(placeholder.meta_data or {}),
            "workspace_job_id": job.id,
            "deep_job_id": job.id,
            "deep_poll_url": f"/workspace-jobs/{job.id}",
        }
    db.commit()
    task_id = dispatch_workspace_job(db, workspace, job, allow_inline_fallback=False)
    db.commit()
    refreshed = db.query(WorkspaceJob).filter(WorkspaceJob.id == job.id).first() or job
    state["deep_job_id"] = refreshed.id
    state["deep_poll_url"] = f"/workspace-jobs/{refreshed.id}"
    state["deep_status"] = refreshed.status
    state["deep_retrieval_recommended"] = True
    serialized = serialize_job(refreshed)
    return {
        "deep_job_id": refreshed.id,
        "deep_task_id": task_id,
        "deep_poll_url": state["deep_poll_url"],
        "deep_status": refreshed.status,
        "deep_progress": refreshed.progress,
        "deep_stage": serialized.get("stage"),
        "message_id": message_id,
    }


def _vigie_executive_quick_reply(
    db: Session,
    workspace: Workspace,
    query: str,
    *,
    assistant_profile: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Return a generic data-driven fallback reply for vigie_executive prompts.

    This is intentionally a **safety net only**. Business-specific narratives
    (zone Nord, port, presse, agenda…) MUST be expressed as Action Manifest
    phrases in ``app.services.actions.registry`` (pack ``sentinel_ci_aya_v1``)
    and routed through ``handle_registry_chat_action`` so the executor stays
    the single source of dynamic narrative. When the resolver finds no match
    and the query is clearly a generic briefing-style ask, we return a
    consolidated 3-signal summary built from ``news_payload``/``cockpit_payload``
    (no hardcoded narrative).
    """
    if assistant_profile != "vigie_executive":
        return None
    normalized = query.lower()
    trigger_terms = (
        "signal",
        "signaux",
        "attention cabinet",
        "alerte",
        "alertes",
        "synthese",
        "synthèse",
        "veille",
    )
    if not any(term in normalized for term in trigger_terms):
        return None

    news = news_payload(workspace, db)
    cockpit = cockpit_payload(workspace, db)
    briefing = briefing_payload(workspace)
    alerts = (news.get("executive_alerts") or news.get("signals") or cockpit.get("latest_alerts") or [])[:3]
    note = news.get("briefing_note") or {}
    source_health = news.get("source_health") or {}
    sources_catalog = news.get("sources") or cockpit.get("sources") or source_index()
    source_lookup = {str(item.get("id")): item for item in sources_catalog if item.get("id")}

    lines = ["Monsieur le Vice Premier Ministre, trois signaux méritent une attention cabinet aujourd'hui :"]
    if alerts:
        for idx, alert in enumerate(alerts, start=1):
            title = alert.get("title") or "Signal à qualifier"
            impact = alert.get("impact_ci") or alert.get("summary") or alert.get("why_it_matters") or ""
            action = alert.get("recommended_action") or "Qualifier le signal avant décision."
            confidence = alert.get("confidence")
            confidence_txt = f" Confiance {round(float(confidence) * 100)}%." if isinstance(confidence, (int, float)) else ""
            lines.append(f"{idx}. {title} — {impact} Action proposée : {action}.{confidence_txt}")
    else:
        for idx, bullet in enumerate((note.get("bullets") or briefing.get("key_points") or [])[:3], start=1):
            lines.append(f"{idx}. {bullet}")

    decisions = note.get("decisions_expected") or briefing.get("decisions_expected") or []
    if decisions:
        lines.append("")
        lines.append("Décisions attendues : " + " ; ".join(str(item) for item in decisions[:3]) + ".")

    if source_health:
        coverage = source_health.get("coverage_label") or "sources qualifiées disponibles"
        run_id = source_health.get("last_run_id")
        lines.append("")
        lines.append(f"Couverture : {coverage}" + (f" · dernier run {run_id}" if run_id else "") + ".")

    source_ids = []
    for alert in alerts:
        source_ids.extend([str(item) for item in (alert.get("sources") or [])])
    sources = [
        {
            "title": source_lookup.get(source_id, {}).get("label") or source_id,
            "source_label": source_lookup.get(source_id, {}).get("label") or source_id,
            "kind": source_lookup.get(source_id, {}).get("kind") or "mission_room",
            "confidence": source_lookup.get(source_id, {}).get("confidence"),
        }
        for source_id in source_ids[:5]
    ]
    if not sources:
        sources = [{"title": "Mission Room SENTINEL-CI", "source_label": "Briefing souverain", "kind": "mission_room"}]

    return {
        "content": "\n".join(lines),
        "sources": sources,
        "details": {
            "live_news_used": bool(source_health.get("live_news_used")),
            "last_run_id": source_health.get("last_run_id"),
            "alert_count": len(alerts),
        },
    }


async def _try_registry_chat_action(
    db: Session,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str],
    session_id: Optional[str] = None,
    knowledge_scope: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return await handle_registry_chat_action(
        db,
        workspace,
        user,
        query=query,
        assistant_profile=assistant_profile,
        session_id=session_id,
        knowledge_scope=knowledge_scope,
    )


@router.post("/completion")
async def chat_completion(
    request: ChatRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Non-streaming chat completion (scoped to current workspace)."""
    try:
        chat_session = _ensure_chat_session(
            db,
            workspace=workspace,
            user=user,
            request_payload=request.model_dump(),
        )
        request.session_id = chat_session.id

        chat_context = _resolve_chat_context(
            db,
            workspace_id=workspace.id,
            candidate=request.context_id,
        )
        if request.context_id and chat_context is None:
            raise HTTPException(status_code=404, detail="Chat context not found")

        empty_bypass = maybe_trivial_bypass(request.query)
        if (
            empty_bypass
            and not str(request.query or "").strip()
            and _can_apply_trivial_bypass(db, workspace=workspace, request=request)
        ):
            run_id = _persist_trivial_bypass_turn(
                db,
                workspace=workspace,
                request=request,
                query="",
                bypass=empty_bypass,
            )
            return _trivial_bypass_completion_payload(run_id, empty_bypass)

        # Validate query
        try:
            validated_query = query_validator.validate(request.query)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

        trivial_bypass = maybe_trivial_bypass(validated_query)
        if trivial_bypass and _can_apply_trivial_bypass(db, workspace=workspace, request=request):
            run_id = _persist_trivial_bypass_turn(
                db,
                workspace=workspace,
                request=request,
                query=validated_query,
                bypass=trivial_bypass,
            )
            return _trivial_bypass_completion_payload(run_id, trivial_bypass)
        
        canonical = None if (request.context_id or request.knowledge_scope) else _canonical_answer_hit(
            db,
            workspace_id=workspace.id,
            query=validated_query,
        )
        if canonical:
            canonical_answer, match_score = canonical
            content = canonical_answer.answer
            if request.session_id:
                db.add(
                    Message(
                        id=str(uuid.uuid4()),
                        session_id=request.session_id,
                        role="user",
                        content=request.query,
                        meta_data={},
                    )
                )
                db.add(
                    Message(
                        id=str(uuid.uuid4()),
                        session_id=request.session_id,
                        role="assistant",
                        content=content,
                        meta_data={
                            "canonical_answer_id": canonical_answer.id,
                            "canonical_answer_score": match_score,
                        },
                    )
                )
                db.commit()
            run_completed_at = datetime.utcnow()
            run_id = _persist_chat_run(
                db,
                workspace_id=workspace.id,
                system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                query=validated_query,
                response_text=content,
                sources=[],
                reasoning_trace=None,
                started_at=run_completed_at,
                completed_at=run_completed_at,
                duration_ms=0.0,
                trigger="canonical_answer",
                schedule=False,
                extra_output={
                    "canonical_answer_id": canonical_answer.id,
                    "canonical_answer_score": match_score,
                },
            )
            db.commit()
            return {
                "id": canonical_answer.id,
                "run_id": run_id,
                "content": content,
                "reasoning_trace": None,
                "sources": [],
                "status": "completed",
                "canonical_answer_hit": True,
                "canonical_answer_id": canonical_answer.id,
                "canonical_answer_score": match_score,
            }

        registry_action = await _try_registry_chat_action(
            db,
            workspace,
            user,
            query=validated_query,
            assistant_profile=request.assistant_profile,
            session_id=request.session_id,
            knowledge_scope=request.knowledge_scope,
        )
        if registry_action:
            content = registry_action["content"]
            run_completed_at = datetime.utcnow()
            run_id = _persist_chat_run(
                db,
                workspace_id=workspace.id,
                system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                query=validated_query,
                response_text=content,
                sources=registry_action.get("sources") or [],
                reasoning_trace=None,
                started_at=run_completed_at,
                completed_at=run_completed_at,
                duration_ms=0.0,
                trigger="action_registry",
                extra_output={
                    "registry_action": registry_action,
                    "action_effects": registry_action.get("action_effects") or [],
                    "assistant_profile": request.assistant_profile,
                    "knowledge_scope": request.knowledge_scope,
                    "session_id": request.session_id,
                },
            )
            db.commit()
            return {
                "run_id": run_id,
                "content": content,
                "sources": registry_action.get("sources") or [],
                "status": "completed",
                "registry_action": registry_action,
            }

        calendar_action = handle_calendar_chat_action(
            db,
            workspace,
            user,
            query=validated_query,
            assistant_profile=request.assistant_profile,
        )
        if calendar_action:
            content = calendar_action["content"]
            run_completed_at = datetime.utcnow()
            run_id = _persist_chat_run(
                db,
                workspace_id=workspace.id,
                system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                query=validated_query,
                response_text=content,
                sources=[{"title": "Agenda institutionnel", "source_label": "Agenda institutionnel", "kind": "calendar"}],
                reasoning_trace=None,
                started_at=run_completed_at,
                completed_at=run_completed_at,
                duration_ms=0.0,
                trigger="calendar_action",
                extra_output={
                    "calendar_action": calendar_action,
                    "assistant_profile": request.assistant_profile,
                    "knowledge_scope": request.knowledge_scope,
                },
            )
            db.commit()
            return {
                "run_id": run_id,
                "content": content,
                "sources": [{"title": "Agenda institutionnel", "kind": "calendar"}],
                "status": "completed",
                "calendar_action": calendar_action,
            }

        action_plan_action = handle_transverse_chat_action(
            db,
            workspace,
            user,
            query=validated_query,
            assistant_profile=request.assistant_profile,
        )
        if action_plan_action:
            content = action_plan_action["content"]
            run_completed_at = datetime.utcnow()
            run_id = _persist_chat_run(
                db,
                workspace_id=workspace.id,
                system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                query=validated_query,
                response_text=content,
                sources=[{"title": "Actions cabinet", "source_label": "Actions cabinet", "kind": "action_plan"}],
                reasoning_trace=None,
                started_at=run_completed_at,
                completed_at=run_completed_at,
                duration_ms=0.0,
                trigger="action_plan",
                extra_output={
                    "action_plan_action": action_plan_action,
                    "assistant_profile": request.assistant_profile,
                    "knowledge_scope": request.knowledge_scope,
                },
            )
            db.commit()
            return {
                "run_id": run_id,
                "content": content,
                "sources": [{"title": "Actions cabinet", "kind": "action_plan"}],
                "status": "completed",
                "action_plan_action": action_plan_action,
            }

        visual_action = handle_visual_chat_query(
            db,
            workspace,
            user,
            query=validated_query,
            assistant_profile=request.assistant_profile,
        )
        if visual_action:
            content = visual_action["content"]
            run_completed_at = datetime.utcnow()
            run_id = _persist_chat_run(
                db,
                workspace_id=workspace.id,
                system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                query=validated_query,
                response_text=content,
                sources=[{"title": "Flux visuels institutionnels", "source_label": "Flux visuels institutionnels", "kind": "visual_stream"}],
                reasoning_trace=None,
                started_at=run_completed_at,
                completed_at=run_completed_at,
                duration_ms=0.0,
                trigger="visual_observation",
                extra_output={
                    "visual_action": visual_action,
                    "assistant_profile": request.assistant_profile,
                    "knowledge_scope": request.knowledge_scope,
                },
            )
            db.commit()
            return {
                "run_id": run_id,
                "content": content,
                "sources": [{"title": "Flux visuels institutionnels", "kind": "visual_stream"}],
                "status": "completed",
                "visual_action": visual_action,
            }

        map_action = handle_map_chat_query(
            db,
            workspace,
            user,
            query=validated_query,
            assistant_profile=request.assistant_profile,
        )
        if map_action:
            content = map_action["content"]
            run_completed_at = datetime.utcnow()
            run_id = _persist_chat_run(
                db,
                workspace_id=workspace.id,
                system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                query=validated_query,
                response_text=content,
                sources=map_action.get("sources") or [{"title": "Carte strategique", "kind": "workspace_map"}],
                reasoning_trace=None,
                started_at=run_completed_at,
                completed_at=run_completed_at,
                duration_ms=0.0,
                trigger="map_command",
                extra_output={
                    "map_action": map_action,
                    "map_command": map_action.get("command"),
                    "assistant_profile": request.assistant_profile,
                    "knowledge_scope": request.knowledge_scope,
                },
            )
            db.commit()
            return {
                "run_id": run_id,
                "content": content,
                "sources": map_action.get("sources") or [{"title": "Carte strategique", "kind": "workspace_map"}],
                "status": "completed",
                "map_action": map_action,
            }

        vigie_reply = _vigie_executive_quick_reply(
            db,
            workspace,
            validated_query,
            assistant_profile=request.assistant_profile,
        )
        if vigie_reply:
            content = vigie_reply["content"]
            sources = vigie_reply.get("sources") or []
            run_completed_at = datetime.utcnow()
            run_id = _persist_chat_run(
                db,
                workspace_id=workspace.id,
                system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                query=validated_query,
                response_text=content,
                sources=sources,
                reasoning_trace=None,
                started_at=run_completed_at,
                completed_at=run_completed_at,
                duration_ms=0.0,
                trigger="vigie_quick_brief",
                extra_output={
                    "assistant_profile": request.assistant_profile,
                    "knowledge_scope": request.knowledge_scope,
                    "vigie_quick_reply": vigie_reply.get("details") or {},
                },
            )
            db.commit()
            return {
                "run_id": run_id,
                "content": content,
                "sources": sources,
                "status": "completed",
                "vigie_quick_reply": vigie_reply.get("details") or {},
            }

        orchestrator = get_orchestrator()
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        
        # Load resolved preset config for defaults (workspace-scoped).
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        
        request_dict = request.model_dump()
        request_dict["query"] = validated_query
        request_dict["workspace_slug"] = workspace.slug
        request_dict["workspace_id"] = workspace.id
        _apply_context_to_chat_request(request_dict, chat_context)
        if request.assistant_profile == "vigie_executive":
            request_dict.setdefault("context", {})["workspace_calendar"] = calendar_context_for_chat(db, workspace)
            request_dict.setdefault("context", {})["workspace_actions"] = action_context_for_chat(db, workspace)
            request_dict.setdefault("context", {})["workspace_visual_observations"] = visual_context_for_chat(db, workspace)
        grounding_policy = resolve_grounding_policy(
            query=validated_query,
            workspace=workspace,
            assistant_profile=request.assistant_profile,
            requested_mode=request.grounding_mode,
            context_id=request.context_id,
        )
        request_dict["grounding_policy"] = grounding_policy
        request_dict["grounding_mode"] = grounding_policy["mode"]

        # If the cockpit sent a per-query override, promote it onto the
        # legacy pipeline-mode key so downstream code picks it up without
        # changing its signature.
        if request.rag_mode_override:
            request_dict["rag_pipeline_mode"] = request.rag_mode_override

        # Apply settings defaults if not provided
        if not request_dict.get("agent_preferences"):
            request_dict["agent_preferences"] = {}
        if not request_dict["agent_preferences"].get("preferred_agents"):
            request_dict["agent_preferences"]["preferred_agents"] = app_settings.get("preferredAgents", [])
        if not request_dict["agent_preferences"].get("model_preferences"):
            request_dict["agent_preferences"]["model_preferences"] = {}
        if not request_dict["agent_preferences"]["model_preferences"].get("model"):
            request_dict["agent_preferences"]["model_preferences"]["model"] = app_settings.get("defaultModel") or settings.default_model
        if not request_dict["agent_preferences"]["model_preferences"].get("provider"):
            request_dict["agent_preferences"]["model_preferences"]["provider"] = app_settings.get("defaultProvider") or settings.default_provider
        
        # Apply default temperature and max_tokens from settings
        if request.max_tokens is None:
            request_dict["max_tokens"] = app_settings.get("maxTokens", 2000)
        if request.temperature is None:
            request_dict["temperature"] = app_settings.get("temperature", 0.7)
        _apply_retrieval_budget_policy(request_dict)
        chunks = []
        decision_steps = []  # Collect decision pipeline steps
        import time
        pipeline_start_time = None
        chunk_state: Dict[str, Any] = {
            "reasoning_trace": None,
            "sources": None,
            "rag_context": None,
            "retrieval_metrics": None,
            "retrieval_worker_task_id": None,
            "retrieval_fallback": None,
            "knowledge_scope": None,
            "collections_touched": None,
            "retrieval_scope": None,
            "retrieval_plan": None,
            "scope_confidence": None,
            "scope_reason": None,
            "dense_policy": None,
            "dense_only": None,
            "sparse_status": None,
            "sparse_backend": None,
            "sparse_fallback_reason": None,
            "retrieval_profile": None,
            "latency_budget": None,
            "score_threshold_applied": None,
            "deep_retrieval_recommended": None,
            "deep_job_id": None,
            "deep_poll_url": None,
            "deep_status": None,
            "grounding_policy": grounding_policy,
        }
        full_content: list[str] = []
        run_started_at = datetime.utcnow()
        run_started_ts = time.time()

        async for chunk in orchestrator.process_request(request_dict):
            chunks.append(chunk)
            _collect_chat_chunk(
                chunk,
                full_content=full_content,
                decision_steps=decision_steps,
                state=chunk_state,
            )
            if chunk.get("chunk_type") == "decision_step" and pipeline_start_time is None:
                pipeline_start_time = time.time()
            
            if chunk.get("is_final"):
                break
        
        # Calculate pipeline total time
        if pipeline_start_time:
            pipeline_total_time = int((time.time() - pipeline_start_time) * 1000)
        else:
            pipeline_total_time = None
        
        # Combine chunks
        content = "".join(full_content)
        
        # Validate response
        try:
            response_validator.validate(content)
        except ValidationError as e:
            logger.warning("Response validation warning", error=str(e))
            # Don't fail, just log warning

        deep_job_payload = None
        try:
            deep_job_payload = _queue_auto_deep_retrieval_job(
                db=db,
                workspace=workspace,
                user=user,
                request_dict=request_dict,
                state=chunk_state,
                partial_answer=content,
                partial_sources=chunk_state.get("sources"),
            )
        except Exception as exc:  # noqa: BLE001 - deep refinement must never break chat.
            logger.warning("Auto deep retrieval queue failed", error=str(exc))
        fallback_reason = _retrieval_fallback_reason(chunk_state)
        
        # Save messages to database if session_id provided
        if request.session_id:
            # Save user message
            user_message = Message(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="user",
                content=request.query,
                meta_data={}
            )
            db.add(user_message)
            
            # Build meta_data with decision steps
            meta_data = {
                "reasoning_trace": chunk_state["reasoning_trace"],
                "sources": chunk_state["sources"],
                "context_id": request.context_id,
                "context_mode": request.context_mode,
                "knowledge_scope": request_dict.get("knowledge_scope") or chunk_state.get("knowledge_scope"),
                "grounding_mode": grounding_policy["mode"],
                "grounding_policy": grounding_policy,
                "retrieval_scope": chunk_state.get("retrieval_scope"),
                "retrieval_plan": chunk_state.get("retrieval_plan"),
                "scope_confidence": chunk_state.get("scope_confidence"),
                "scope_reason": chunk_state.get("scope_reason"),
                "dense_policy": chunk_state.get("dense_policy"),
                "dense_only": chunk_state.get("dense_only"),
                "sparse_status": chunk_state.get("sparse_status"),
                "sparse_backend": chunk_state.get("sparse_backend"),
                "sparse_fallback_reason": chunk_state.get("sparse_fallback_reason"),
                "retrieval_profile": chunk_state.get("retrieval_profile"),
                "retrieval_fallback": chunk_state.get("retrieval_fallback"),
                "fallback_reason": fallback_reason,
                "latency_budget": chunk_state.get("latency_budget"),
                "score_threshold_applied": chunk_state.get("score_threshold_applied"),
                "deep_retrieval_recommended": chunk_state.get("deep_retrieval_recommended"),
                "deep_job_id": chunk_state.get("deep_job_id"),
                "deep_poll_url": chunk_state.get("deep_poll_url"),
                "deep_status": chunk_state.get("deep_status"),
            }
            
            # Add decision steps if any were collected
            if decision_steps:
                meta_data["decision_steps"] = decision_steps
                if pipeline_total_time is not None:
                    meta_data["decision_pipeline_total_time"] = pipeline_total_time
            
            # Save assistant message
            assistant_message = Message(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="assistant",
                content=content,
                meta_data=meta_data
            )
            db.add(assistant_message)
            db.commit()

        # Persist a canonical Run for this chat turn and kick the
        # auto-eval loop — every chat reply participates in the same
        # ledger as explicit /runs/launch triggers.
        run_completed_at = datetime.utcnow()
        run_id = _persist_chat_run(
            db,
            workspace_id=workspace.id,
            system_id=_resolve_system_id(db, workspace.id, request.agent_id),
            query=validated_query,
            response_text=content,
            sources=chunk_state["sources"],
            reasoning_trace=chunk_state["reasoning_trace"],
            started_at=run_started_at,
            completed_at=run_completed_at,
            duration_ms=(time.time() - run_started_ts) * 1000.0,
            extra_output={
                "rag_context": chunk_state["rag_context"],
                "retrieval_metrics": chunk_state["retrieval_metrics"],
                "retrieval_worker_task_id": chunk_state["retrieval_worker_task_id"],
                "retrieval_fallback": chunk_state["retrieval_fallback"],
                "fallback_reason": fallback_reason,
                "knowledge_scope": request_dict.get("knowledge_scope") or chunk_state.get("knowledge_scope"),
                "context_id": request.context_id,
                "context_mode": request.context_mode,
                "assistant_profile": request.assistant_profile,
                "collections_touched": chunk_state.get("collections_touched"),
                "retrieval_scope": chunk_state.get("retrieval_scope"),
                "retrieval_plan": chunk_state.get("retrieval_plan"),
                "scope_confidence": chunk_state.get("scope_confidence"),
                "scope_reason": chunk_state.get("scope_reason"),
                "dense_policy": chunk_state.get("dense_policy"),
                "dense_only": chunk_state.get("dense_only"),
                "sparse_status": chunk_state.get("sparse_status"),
                "sparse_backend": chunk_state.get("sparse_backend"),
                "sparse_fallback_reason": chunk_state.get("sparse_fallback_reason"),
                "retrieval_profile": chunk_state.get("retrieval_profile"),
                "latency_budget": chunk_state.get("latency_budget"),
                "score_threshold_applied": chunk_state.get("score_threshold_applied"),
                "deep_retrieval_recommended": chunk_state.get("deep_retrieval_recommended"),
                "deep_job_id": chunk_state.get("deep_job_id"),
                "deep_poll_url": chunk_state.get("deep_poll_url"),
                "deep_status": chunk_state.get("deep_status"),
                "grounding_mode": grounding_policy["mode"],
                "grounding_policy": grounding_policy,
            },
        )

        return {
            "id": chunks[0].get("id") if chunks else None,
            "run_id": run_id,
            "content": content,
            "reasoning_trace": chunk_state["reasoning_trace"],
            "sources": chunk_state["sources"],
            "retrieval_scope": chunk_state.get("retrieval_scope"),
            "retrieval_plan": chunk_state.get("retrieval_plan"),
            "scope_confidence": chunk_state.get("scope_confidence"),
            "scope_reason": chunk_state.get("scope_reason"),
            "dense_policy": chunk_state.get("dense_policy"),
            "dense_only": chunk_state.get("dense_only"),
            "sparse_status": chunk_state.get("sparse_status"),
            "sparse_backend": chunk_state.get("sparse_backend"),
            "sparse_fallback_reason": chunk_state.get("sparse_fallback_reason"),
            "retrieval_profile": chunk_state.get("retrieval_profile"),
            "retrieval_fallback": chunk_state.get("retrieval_fallback"),
            "fallback_reason": fallback_reason,
            "latency_budget": chunk_state.get("latency_budget"),
            "score_threshold_applied": chunk_state.get("score_threshold_applied"),
            "deep_retrieval_recommended": chunk_state.get("deep_retrieval_recommended"),
            "deep_job_id": chunk_state.get("deep_job_id"),
            "deep_poll_url": chunk_state.get("deep_poll_url"),
            "deep_status": chunk_state.get("deep_status"),
            "deep_job": deep_job_payload,
            "status": "completed",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat completion error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deep-retrieval-jobs")
async def create_deep_retrieval_job(
    request: ChatRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue a deep retrieval job without blocking the chat stream."""
    from app.models.knowledge_collection import KnowledgeCollection
    from app.services.rag.context import get_retrieval_profile
    from app.services.workspace_jobs import create_workspace_job, dispatch_workspace_job, serialize_job

    try:
        validated_query = query_validator.validate(request.query)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not request.session_id:
        session = _ensure_chat_session(
            db,
            workspace=workspace,
            user=user,
            request_payload=request.model_dump(),
        )
        request.session_id = session.id
    else:
        session_query = db.query(ChatSession).filter(
            ChatSession.id == request.session_id,
            ChatSession.workspace_id == workspace.id,
            ChatSession.status == "active",
        )
        user_id = _user_id(user)
        session_query = session_query.filter(ChatSession.user_id == user_id) if user_id else session_query.filter(ChatSession.user_id.is_(None))
        session = session_query.first()
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

    chat_context = _resolve_chat_context(
        db,
        workspace_id=workspace.id,
        candidate=request.context_id,
    )
    if request.context_id and chat_context is None:
        raise HTTPException(status_code=404, detail="Chat context not found")

    request_dict = request.model_dump()
    request_dict["query"] = validated_query
    request_dict["workspace_slug"] = workspace.slug
    request_dict["workspace_id"] = workspace.id
    request_dict["latency_profile"] = "deep"
    request_dict["deep_retrieval"] = True
    if request.rag_mode_override:
        request_dict["rag_pipeline_mode"] = request.rag_mode_override
    _apply_context_to_chat_request(request_dict, chat_context)
    _apply_retrieval_budget_policy(request_dict)

    profile = get_retrieval_profile(request_dict)
    collection_ref = profile.get("collection")
    collection = (
        db.query(KnowledgeCollection)
        .filter(
            ((KnowledgeCollection.slug == collection_ref) | (KnowledgeCollection.id == collection_ref)),
            KnowledgeCollection.workspace_id == workspace.id,
        )
        .first()
    )
    parent_message_id = None
    previous_answer = _compact_job_text(request.previous_answer, max_chars=4000)
    if request.parent_message_id:
        parent = (
            db.query(Message)
            .filter(
                Message.id == request.parent_message_id,
                Message.session_id == session.id,
                Message.role == "assistant",
            )
            .first()
        )
        if parent:
            parent_message_id = parent.id
            if not previous_answer:
                previous_answer = _compact_job_text(parent.content, max_chars=4000)
    previous_assistant = (
        db.query(Message)
        .filter(Message.session_id == session.id, Message.role == "assistant")
        .order_by(Message.timestamp.desc())
        .first()
    )
    if not parent_message_id and previous_assistant:
        parent_message_id = previous_assistant.id
        if not previous_answer:
            previous_answer = _compact_job_text(previous_assistant.content, max_chars=4000)
    if previous_answer:
        request_dict["previous_answer"] = previous_answer
    placeholder = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Recherche approfondie lancée pour affiner cette réponse.",
        meta_data={
            "deep_status": "queued",
            "deep_stage": "manual_deep_search",
            "deep_poll_url": None,
            "parent_message_id": parent_message_id,
            "sources": [],
        },
    )
    db.add(placeholder)
    db.flush()
    job = create_workspace_job(
        db,
        workspace,
        user,
        title=f"Deep Search · {validated_query[:96]}",
        input_ref={
            "request": request_dict,
            "latency_profile": "deep",
            "trigger": "manual_deep_search",
            "partial_result": {"answer_preview": previous_answer} if previous_answer else None,
        },
        collection_id=collection.id if collection else None,
        kind="rag_deep_retrieval",
        session_id=session.id,
        parent_message_id=parent_message_id,
        message_id=placeholder.id,
        status="queued",
    )
    placeholder.meta_data = {
        **(placeholder.meta_data or {}),
        "workspace_job_id": job.id,
        "deep_job_id": job.id,
        "deep_poll_url": f"/workspace-jobs/{job.id}",
    }
    _touch_chat_session(db, session, query=validated_query)
    db.commit()
    task_id = dispatch_workspace_job(db, workspace, job, allow_inline_fallback=False)
    db.commit()
    refreshed = db.query(WorkspaceJob).filter(WorkspaceJob.id == job.id).first() or job
    payload = serialize_job(refreshed)
    payload["poll_url"] = f"/workspace-jobs/{job.id}"
    payload["task_id"] = task_id
    payload["message_id"] = placeholder.id
    return payload


@router.post("/retrieval-plan-preview")
async def preview_retrieval_plan(
    request: ChatRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the planner decision without running Qdrant, sparse, rerank, or LLM."""
    from app.services.rag.context import get_retrieval_profile
    from app.services.rag.corpus_planner import plan_corpus

    try:
        validated_query = query_validator.validate(request.query)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    chat_context = _resolve_chat_context(
        db,
        workspace_id=workspace.id,
        candidate=request.context_id,
    )
    if request.context_id and chat_context is None:
        raise HTTPException(status_code=404, detail="Chat context not found")

    request_dict = request.model_dump()
    request_dict["query"] = validated_query
    request_dict["workspace_slug"] = workspace.slug
    request_dict["workspace_id"] = workspace.id
    if request.rag_mode_override:
        request_dict["rag_pipeline_mode"] = request.rag_mode_override
    _apply_context_to_chat_request(request_dict, chat_context)
    _apply_retrieval_budget_policy(request_dict)
    profile = get_retrieval_profile(request_dict)
    planner_request = dict(request_dict)
    planner_request["retrieval_filters"] = dict(profile.get("retrieval_filters") or {})
    plan = plan_corpus(
        db=db,
        profile=profile,
        query=str(profile.get("query") or validated_query),
        request=planner_request,
    )
    return {
        "query": validated_query,
        "planner_only": True,
        "collection": profile.get("collection"),
        "collections": profile.get("collections") or [],
        "knowledge_scope": profile.get("knowledge_scope"),
        "rag_mode": profile.get("rag_mode"),
        "latency_profile": plan.latency_profile,
        "top_k": plan.top_k,
        "candidate_pool_k": plan.candidate_pool_k,
        "synthesis_k": plan.synthesis_k,
        "source_display_k": plan.source_display_k,
        "latency_budget": {
            "profile": plan.latency_profile,
            "deadline_seconds": plan.deadline_seconds,
            "top_k": plan.top_k,
            "candidate_pool_k": plan.candidate_pool_k,
        },
        "intent": plan.intent,
        "dense": plan.dense,
        "retrieval_scope": plan.retrieval_scope,
        "retrieval_plan": plan.retrieval_plan,
        "scope_confidence": plan.scope_confidence,
        "scope_reason": plan.scope_reason,
        "dense_policy": plan.dense_policy,
        "fallback_reason": plan.fallback_reason,
        "deep_retrieval_recommended": plan.deep_retrieval_recommended,
        "filters": plan.filters,
        "use_hybrid": plan.use_hybrid,
        "allow_hah_chah": plan.allow_hah_chah,
        "allow_legacy_hybrid": plan.allow_legacy_hybrid,
        "max_variants": plan.max_variants,
        "max_candidates": plan.max_candidates,
    }


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Streaming chat completion (scoped to current workspace)."""
    from fastapi.responses import StreamingResponse

    async def generate():
        stream_status = "completed"
        stream_id = metrics_collector.start_stream(
            "/api/v1/chat/stream",
            stream_type="sse",
            metadata={
                "workspace_slug": workspace.slug,
                "assistant_profile": request.assistant_profile,
                "knowledge_scope": request.knowledge_scope,
            },
        )
        try:
            provided_session_id = request.session_id
            try:
                chat_session = _ensure_chat_session(
                    db,
                    workspace=workspace,
                    user=user,
                    request_payload=request.model_dump(),
                )
                request.session_id = chat_session.id
            except HTTPException:
                yield _sse_data(
                    _error_chunk(
                        "CHAT_SESSION_NOT_FOUND",
                        "Chat session not found",
                        recoverable=True,
                    )
                )
                yield _sse_done()
                return
            if not provided_session_id:
                yield _sse_data(
                    {
                        "chunk_type": "session",
                        "session_id": chat_session.id,
                        "title": chat_session.title,
                        "is_final": False,
                    }
                )

            chat_context = _resolve_chat_context(
                db,
                workspace_id=workspace.id,
                candidate=request.context_id,
            )
            if request.context_id and chat_context is None:
                yield _sse_data(
                    _error_chunk(
                        "CHAT_CONTEXT_NOT_FOUND",
                        "Chat context not found",
                        recoverable=True,
                    )
                )
                yield _sse_done()
                return

            app_settings = get_resolved_settings(workspace_id=workspace.id)

            request_dict = request.model_dump()
            request_dict["workspace_slug"] = workspace.slug
            request_dict["workspace_id"] = workspace.id
            _apply_context_to_chat_request(request_dict, chat_context)
            if request.rag_mode_override:
                request_dict["rag_pipeline_mode"] = request.rag_mode_override

            empty_bypass = maybe_trivial_bypass(request.query)
            if (
                empty_bypass
                and not str(request.query or "").strip()
                and _can_apply_trivial_bypass(db, workspace=workspace, request=request)
            ):
                run_id = _persist_trivial_bypass_turn(
                    db,
                    workspace=workspace,
                    request=request,
                    query="",
                    bypass=empty_bypass,
                )
                yield _sse_data(
                    {
                        "chunk_type": "retrieval",
                        "phase": "bypassed",
                        "content": "",
                        "message": "Trivial chat bypassed retrieval",
                        "details": empty_bypass.metadata(),
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": empty_bypass.content,
                        "sources": [],
                        "run_id": run_id,
                        "trivial_bypass": True,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            try:
                validated_query = query_validator.validate(request.query)
            except ValidationError as e:
                yield _sse_data(
                    _error_chunk(
                        "QUERY_VALIDATION_FAILED",
                        str(e),
                        recoverable=True,
                    )
                )
                yield _sse_done()
                return
            request_dict["query"] = validated_query

            trivial_bypass = maybe_trivial_bypass(validated_query)
            if trivial_bypass and _can_apply_trivial_bypass(db, workspace=workspace, request=request):
                run_id = _persist_trivial_bypass_turn(
                    db,
                    workspace=workspace,
                    request=request,
                    query=validated_query,
                    bypass=trivial_bypass,
                )
                yield _sse_data(
                    {
                        "chunk_type": "retrieval",
                        "phase": "bypassed",
                        "content": "",
                        "message": "Trivial chat bypassed retrieval",
                        "details": trivial_bypass.metadata(),
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": trivial_bypass.content,
                        "sources": [],
                        "run_id": run_id,
                        "trivial_bypass": True,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            orchestrator = get_orchestrator()
            if not orchestrator:
                yield _sse_data(
                    _error_chunk(
                        "ORCHESTRATOR_UNAVAILABLE",
                        "Orchestrator not initialized",
                        recoverable=True,
                    )
                )
                yield _sse_done()
                return

            canonical = None if (request.context_id or request.knowledge_scope) else _canonical_answer_hit(
                db,
                workspace_id=workspace.id,
                query=validated_query,
            )
            if canonical:
                canonical_answer, match_score = canonical
                content = canonical_answer.answer
                if request.session_id:
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="user",
                            content=request.query,
                            meta_data={},
                        )
                    )
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="assistant",
                            content=content,
                            meta_data={
                                "canonical_answer_id": canonical_answer.id,
                                "canonical_answer_score": match_score,
                            },
                        )
                    )
                    db.commit()
                now = datetime.utcnow()
                run_id = _persist_chat_run(
                    db,
                    workspace_id=workspace.id,
                    system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                    query=validated_query,
                    response_text=content,
                    sources=[],
                    reasoning_trace=None,
                    started_at=now,
                    completed_at=now,
                    duration_ms=0.0,
                    trigger="canonical_answer",
                    schedule=False,
                    extra_output={
                        "canonical_answer_id": canonical_answer.id,
                        "canonical_answer_score": match_score,
                    },
                )
                db.commit()
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": content,
                        "canonical_answer_hit": True,
                        "canonical_answer_id": canonical_answer.id,
                        "canonical_answer_score": match_score,
                        "run_id": run_id,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            registry_action = await _try_registry_chat_action(
                db,
                workspace,
                user,
                query=validated_query,
                assistant_profile=request.assistant_profile,
                session_id=request.session_id,
                knowledge_scope=request.knowledge_scope,
            )
            if registry_action:
                content = registry_action["content"]
                if request.session_id:
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="user",
                            content=request.query,
                            meta_data={},
                        )
                    )
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="assistant",
                            content=content,
                            meta_data={"registry_action": registry_action},
                        )
                    )
                now = datetime.utcnow()
                run_id = _persist_chat_run(
                    db,
                    workspace_id=workspace.id,
                    system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                    query=validated_query,
                    response_text=content,
                    sources=registry_action.get("sources") or [],
                    reasoning_trace=None,
                    started_at=now,
                    completed_at=now,
                    duration_ms=0.0,
                    trigger="action_registry",
                    schedule=False,
                    extra_output={
                        "registry_action": registry_action,
                        "action_effects": registry_action.get("action_effects") or [],
                        "assistant_profile": request.assistant_profile,
                        "knowledge_scope": request.knowledge_scope,
                        "session_id": request.session_id,
                    },
                )
                db.commit()
                for effect in registry_action.get("action_effects") or []:
                    yield _sse_data({**effect, "run_id": run_id, "is_final": False})
                yield _sse_data(
                    {
                        "chunk_type": "action_result",
                        "action": registry_action.get("action"),
                        "applied": registry_action.get("applied"),
                        "registry_action": registry_action,
                        "run_id": run_id,
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": content,
                        "sources": registry_action.get("sources") or [],
                        "run_id": run_id,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            calendar_action = handle_calendar_chat_action(
                db,
                workspace,
                user,
                query=validated_query,
                assistant_profile=request.assistant_profile,
            )
            if calendar_action:
                content = calendar_action["content"]
                if request.session_id:
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="user",
                            content=request.query,
                            meta_data={},
                        )
                    )
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="assistant",
                            content=content,
                            meta_data={"calendar_action": calendar_action},
                        )
                    )
                now = datetime.utcnow()
                run_id = _persist_chat_run(
                    db,
                    workspace_id=workspace.id,
                    system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                    query=validated_query,
                    response_text=content,
                    sources=[{"title": "Agenda institutionnel", "source_label": "Agenda institutionnel", "kind": "calendar"}],
                    reasoning_trace=None,
                    started_at=now,
                    completed_at=now,
                    duration_ms=0.0,
                    trigger="calendar_action",
                    schedule=False,
                    extra_output={
                        "calendar_action": calendar_action,
                        "assistant_profile": request.assistant_profile,
                        "knowledge_scope": request.knowledge_scope,
                    },
                )
                db.commit()
                yield _sse_data(
                    {
                        "chunk_type": "action_result",
                        "action": calendar_action.get("action"),
                        "applied": calendar_action.get("applied"),
                        "calendar_action": calendar_action,
                        "run_id": run_id,
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": content,
                        "sources": [{"title": "Agenda institutionnel", "kind": "calendar"}],
                        "run_id": run_id,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            action_plan_action = handle_transverse_chat_action(
                db,
                workspace,
                user,
                query=validated_query,
                assistant_profile=request.assistant_profile,
            )
            if action_plan_action:
                content = action_plan_action["content"]
                if request.session_id:
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="user",
                            content=request.query,
                            meta_data={},
                        )
                    )
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="assistant",
                            content=content,
                            meta_data={"action_plan_action": action_plan_action},
                        )
                    )
                now = datetime.utcnow()
                run_id = _persist_chat_run(
                    db,
                    workspace_id=workspace.id,
                    system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                    query=validated_query,
                    response_text=content,
                    sources=[{"title": "Actions cabinet", "source_label": "Actions cabinet", "kind": "action_plan"}],
                    reasoning_trace=None,
                    started_at=now,
                    completed_at=now,
                    duration_ms=0.0,
                    trigger="action_plan",
                    schedule=False,
                    extra_output={
                        "action_plan_action": action_plan_action,
                        "assistant_profile": request.assistant_profile,
                        "knowledge_scope": request.knowledge_scope,
                    },
                )
                db.commit()
                yield _sse_data(
                    {
                        "chunk_type": "action_result",
                        "action": action_plan_action.get("action"),
                        "applied": action_plan_action.get("applied"),
                        "action_plan_action": action_plan_action,
                        "run_id": run_id,
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": content,
                        "sources": [{"title": "Actions cabinet", "kind": "action_plan"}],
                        "run_id": run_id,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            visual_action = handle_visual_chat_query(
                db,
                workspace,
                user,
                query=validated_query,
                assistant_profile=request.assistant_profile,
            )
            if visual_action:
                content = visual_action["content"]
                if request.session_id:
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="user",
                            content=request.query,
                            meta_data={},
                        )
                    )
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="assistant",
                            content=content,
                            meta_data={"visual_action": visual_action},
                        )
                    )
                now = datetime.utcnow()
                run_id = _persist_chat_run(
                    db,
                    workspace_id=workspace.id,
                    system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                    query=validated_query,
                    response_text=content,
                    sources=[{"title": "Flux visuels institutionnels", "source_label": "Flux visuels institutionnels", "kind": "visual_stream"}],
                    reasoning_trace=None,
                    started_at=now,
                    completed_at=now,
                    duration_ms=0.0,
                    trigger="visual_observation",
                    schedule=False,
                    extra_output={
                        "visual_action": visual_action,
                        "assistant_profile": request.assistant_profile,
                        "knowledge_scope": request.knowledge_scope,
                    },
                )
                db.commit()
                yield _sse_data(
                    {
                        "chunk_type": "action_result",
                        "action": visual_action.get("action"),
                        "applied": visual_action.get("applied"),
                        "visual_action": visual_action,
                        "run_id": run_id,
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": content,
                        "sources": [{"title": "Flux visuels institutionnels", "kind": "visual_stream"}],
                        "run_id": run_id,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            map_action = handle_map_chat_query(
                db,
                workspace,
                user,
                query=validated_query,
                assistant_profile=request.assistant_profile,
            )
            if map_action:
                content = map_action["content"]
                sources = map_action.get("sources") or [{"title": "Carte strategique", "kind": "workspace_map"}]
                if request.session_id:
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="user",
                            content=request.query,
                            meta_data={},
                        )
                    )
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="assistant",
                            content=content,
                            meta_data={"map_action": map_action},
                        )
                    )
                now = datetime.utcnow()
                run_id = _persist_chat_run(
                    db,
                    workspace_id=workspace.id,
                    system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                    query=validated_query,
                    response_text=content,
                    sources=sources,
                    reasoning_trace=None,
                    started_at=now,
                    completed_at=now,
                    duration_ms=0.0,
                    trigger="map_command",
                    schedule=False,
                    extra_output={
                        "map_action": map_action,
                        "map_command": map_action.get("command"),
                        "assistant_profile": request.assistant_profile,
                        "knowledge_scope": request.knowledge_scope,
                    },
                )
                db.commit()
                yield _sse_data(
                    {
                        "chunk_type": "map_command",
                        "map_command": map_action.get("command"),
                        "run_id": run_id,
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "map_source",
                        "sources": sources,
                        "run_id": run_id,
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": content,
                        "sources": sources,
                        "run_id": run_id,
                        "is_final": False,
                    }
                )
                yield _sse_data(
                    {
                        "chunk_type": "map_state_updated",
                        "map_state": (map_action.get("command") or {}).get("map_state"),
                        "run_id": run_id,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            vigie_reply = _vigie_executive_quick_reply(
                db,
                workspace,
                validated_query,
                assistant_profile=request.assistant_profile,
            )
            if vigie_reply:
                content = vigie_reply["content"]
                sources = vigie_reply.get("sources") or []
                if request.session_id:
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="user",
                            content=request.query,
                            meta_data={},
                        )
                    )
                    db.add(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=request.session_id,
                            role="assistant",
                            content=content,
                            meta_data={"vigie_quick_reply": vigie_reply.get("details") or {}},
                        )
                    )
                now = datetime.utcnow()
                run_id = _persist_chat_run(
                    db,
                    workspace_id=workspace.id,
                    system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                    query=validated_query,
                    response_text=content,
                    sources=sources,
                    reasoning_trace=None,
                    started_at=now,
                    completed_at=now,
                    duration_ms=0.0,
                    trigger="vigie_quick_brief",
                    schedule=False,
                    extra_output={
                        "assistant_profile": request.assistant_profile,
                        "knowledge_scope": request.knowledge_scope,
                        "vigie_quick_reply": vigie_reply.get("details") or {},
                    },
                )
                db.commit()
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": content,
                        "sources": sources,
                        "run_id": run_id,
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return
            
            grounding_policy = resolve_grounding_policy(
                query=validated_query,
                workspace=workspace,
                assistant_profile=request.assistant_profile,
                requested_mode=request.grounding_mode,
                context_id=request.context_id,
            )
            request_dict["grounding_policy"] = grounding_policy
            request_dict["grounding_mode"] = grounding_policy["mode"]

            # Apply settings defaults if not provided
            if not request_dict.get("agent_preferences"):
                request_dict["agent_preferences"] = {}
            if not request_dict["agent_preferences"].get("preferred_agents"):
                request_dict["agent_preferences"]["preferred_agents"] = app_settings.get("preferredAgents", [])
            if not request_dict["agent_preferences"].get("model_preferences"):
                request_dict["agent_preferences"]["model_preferences"] = {}
            if not request_dict["agent_preferences"]["model_preferences"].get("model"):
                request_dict["agent_preferences"]["model_preferences"]["model"] = app_settings.get("defaultModel") or settings.default_model
            if not request_dict["agent_preferences"]["model_preferences"].get("provider"):
                request_dict["agent_preferences"]["model_preferences"]["provider"] = app_settings.get("defaultProvider") or settings.default_provider
            
            full_content = []
            all_chunks = []
            decision_steps = []  # Collect all decision pipeline steps
            pipeline_start_time = None
            chunk_state: Dict[str, Any] = {
                "reasoning_trace": None,
                "sources": None,
                "rag_context": None,
                "retrieval_metrics": None,
                "retrieval_worker_task_id": None,
                "retrieval_fallback": None,
                "knowledge_scope": None,
                "collections_touched": None,
                "retrieval_scope": None,
                "retrieval_plan": None,
                "scope_confidence": None,
                "scope_reason": None,
                "dense_policy": None,
                "dense_only": None,
                "sparse_status": None,
                "sparse_backend": None,
                "sparse_fallback_reason": None,
                "retrieval_profile": None,
                "latency_budget": None,
                "score_threshold_applied": None,
                "deep_retrieval_recommended": None,
                "deep_job_id": None,
                "deep_poll_url": None,
                "deep_status": None,
                "grounding_policy": grounding_policy,
            }
            import time as _time
            run_started_at = datetime.utcnow()
            run_started_ts = _time.time()
            
            # Load conversation history for context (long-term memory)
            conversation_history = []
            if request.session_id:
                # Get previous messages from this session for context
                previous_messages = db.query(Message).filter(
                    Message.session_id == request.session_id
                ).order_by(Message.timestamp.asc()).all()
                
                # Build conversation history (last 20 messages for context)
                for msg in previous_messages[-20:]:
                    conversation_history.append({
                        "role": msg.role,
                        "content": msg.content
                    })
                
                # Save user message
                user_message = Message(
                    id=str(uuid.uuid4()),
                    session_id=request.session_id,
                    role="user",
                    content=request.query,
                    meta_data={}
                )
                db.add(user_message)
                
                # Update session last_activity
                from app.models.user import Session as SessionModel
                session = db.query(SessionModel).filter(SessionModel.id == request.session_id).first()
                if session:
                    session.last_activity = datetime.utcnow()
                
                db.commit()
            
            # Add conversation history to request for context
            if conversation_history:
                if not request_dict.get("context"):
                    request_dict["context"] = {}
                request_dict["context"]["conversation_history"] = conversation_history
                request_dict["context"]["memory_type"] = "long_term"  # Default to long-term memory
            if request.assistant_profile == "vigie_executive":
                if not request_dict.get("context"):
                    request_dict["context"] = {}
                request_dict["context"]["workspace_calendar"] = calendar_context_for_chat(db, workspace)
                request_dict["context"]["workspace_actions"] = action_context_for_chat(db, workspace)
                request_dict["context"]["workspace_visual_observations"] = visual_context_for_chat(db, workspace)
            
            # Add RAG settings if provided
            if request.top_k is not None:
                request_dict["top_k"] = request.top_k
            if request.candidate_pool_k is not None:
                request_dict["candidate_pool_k"] = request.candidate_pool_k
            if request.synthesis_k is not None:
                request_dict["synthesis_k"] = request.synthesis_k
            if request.source_display_k is not None:
                request_dict["source_display_k"] = request.source_display_k
            if request.similarity_threshold is not None:
                request_dict["similarity_threshold"] = request.similarity_threshold
            _apply_retrieval_budget_policy(request_dict)
            
            stream_error = None
            try:
                async with asyncio.timeout(settings.chat_stream_timeout_seconds):
                    async for chunk in orchestrator.process_request(request_dict):
                        all_chunks.append(chunk)
                        _collect_chat_chunk(
                            chunk,
                            full_content=full_content,
                            decision_steps=decision_steps,
                            state=chunk_state,
                        )
                        if (
                            chunk.get("chunk_type") == "decision_step"
                            and pipeline_start_time is None
                        ):
                            pipeline_start_time = _time.time()
                        yield _sse_data(chunk)
                        if chunk.get("chunk_type") == "retrieval" and not full_content:
                            degraded_reply = _dense_fast_degraded_reply(chunk_state)
                            if degraded_reply:
                                full_content.append(degraded_reply)
                                yield _sse_data(
                                    {
                                        "chunk_type": "text",
                                        "content": degraded_reply,
                                        "is_final": False,
                                    }
                                )
                                break
            except TimeoutError as exc:
                metrics_collector.record_timeout("/api/v1/chat/stream", "chat_stream")
                stream_status = "timeout"
                partial_chars = len("".join(full_content))
                deep_recommended = bool(
                    chunk_state.get("deep_retrieval_recommended")
                    or (_retrieval_metrics(chunk_state).get("deep_retrieval_recommended"))
                )
                stream_error = _error_chunk(
                    "CHAT_STREAM_TIMEOUT",
                    (
                        f"Chat turn exceeded its {settings.chat_stream_timeout_seconds:.0f}s budget. "
                        "Any partial answer and retrieved context were preserved; deeper retrieval can continue "
                        "asynchronously when the retrieval policy recommends it."
                    ),
                    recoverable=True,
                    details={
                        "timeout_seconds": settings.chat_stream_timeout_seconds,
                        "partial_answer_chars": partial_chars,
                        "retrieval_context_available": bool(chunk_state.get("rag_context")),
                        "deep_retrieval_recommended": deep_recommended,
                        "fallback_reason": "chat_stream_timeout",
                    },
                )
                logger.warning("Chat stream timed out", error=str(exc))
            except Exception as exc:  # noqa: BLE001
                stream_status = "error"
                stream_error = _error_chunk(
                    "CHAT_STREAM_ERROR",
                    str(exc),
                    recoverable=True,
                )
                logger.error("Streaming error", error=str(exc))

            if stream_error:
                yield _sse_data(stream_error)

            # Calculate total pipeline time
            if pipeline_start_time:
                pipeline_total_time = int((_time.time() - pipeline_start_time) * 1000)
            else:
                pipeline_total_time = None
            fallback_reason = _retrieval_fallback_reason(chunk_state)
            deep_job_payload = None
            assistant_message_id = None
            
            # Save assistant message after streaming completes
            if request.session_id and full_content:
                # Build meta_data with decision steps
                meta_data = {
                    "reasoning_trace": chunk_state["reasoning_trace"],
                    "sources": chunk_state["sources"],
                    "context_id": request.context_id,
                    "context_mode": request.context_mode,
                    "knowledge_scope": request_dict.get("knowledge_scope") or chunk_state.get("knowledge_scope"),
                    "grounding_mode": grounding_policy["mode"],
                    "grounding_policy": grounding_policy,
                    "retrieval_scope": chunk_state.get("retrieval_scope"),
                    "retrieval_plan": chunk_state.get("retrieval_plan"),
                    "scope_confidence": chunk_state.get("scope_confidence"),
                    "scope_reason": chunk_state.get("scope_reason"),
                    "dense_policy": chunk_state.get("dense_policy"),
                    "dense_only": chunk_state.get("dense_only"),
                    "sparse_status": chunk_state.get("sparse_status"),
                    "sparse_backend": chunk_state.get("sparse_backend"),
                    "sparse_fallback_reason": chunk_state.get("sparse_fallback_reason"),
                    "retrieval_profile": chunk_state.get("retrieval_profile"),
                    "retrieval_fallback": chunk_state.get("retrieval_fallback"),
                    "fallback_reason": fallback_reason,
                    "latency_budget": chunk_state.get("latency_budget"),
                    "score_threshold_applied": chunk_state.get("score_threshold_applied"),
                    "deep_retrieval_recommended": chunk_state.get("deep_retrieval_recommended"),
                    "deep_job_id": chunk_state.get("deep_job_id"),
                    "deep_poll_url": chunk_state.get("deep_poll_url"),
                    "deep_status": chunk_state.get("deep_status"),
                }
                
                # Add decision steps if any were collected
                if decision_steps:
                    meta_data["decision_steps"] = decision_steps
                    if pipeline_total_time is not None:
                        meta_data["decision_pipeline_total_time"] = pipeline_total_time
                
                assistant_message = Message(
                    id=str(uuid.uuid4()),
                    session_id=request.session_id,
                    role="assistant",
                    content="".join(full_content),
                    meta_data=meta_data
                )
                db.add(assistant_message)
                db.flush()
                assistant_message_id = assistant_message.id
                session = db.query(ChatSession).filter(ChatSession.id == request.session_id).first()
                if session:
                    _touch_chat_session(db, session, query=validated_query)
                try:
                    deep_job_payload = _queue_auto_deep_retrieval_job(
                        db=db,
                        workspace=workspace,
                        user=user,
                        request_dict=request_dict,
                        state=chunk_state,
                        partial_answer="".join(full_content),
                        partial_sources=chunk_state.get("sources"),
                        parent_message_id=assistant_message.id,
                    )
                    if deep_job_payload:
                        assistant_message.meta_data = {
                            **(assistant_message.meta_data or {}),
                            "deep_retrieval_recommended": True,
                        }
                except Exception as exc:  # noqa: BLE001 - refinement is best-effort.
                    logger.warning("Auto deep retrieval queue failed", error=str(exc))
                db.commit()
            elif request.session_id:
                session = db.query(ChatSession).filter(ChatSession.id == request.session_id).first()
                if session:
                    _touch_chat_session(db, session, query=validated_query)
                    db.commit()

            if deep_job_payload:
                yield _sse_data(
                    {
                        "chunk_type": "retrieval",
                        "phase": "deep_queued",
                        "content": "",
                        "message": "Deep retrieval queued",
                        "details": {
                            **deep_job_payload,
                            "deep_retrieval_recommended": True,
                            "deep_job_id": deep_job_payload.get("deep_job_id"),
                            "deep_poll_url": deep_job_payload.get("deep_poll_url"),
                            "deep_status": deep_job_payload.get("deep_status"),
                            "latency_profile": "deep",
                            "dense_policy": chunk_state.get("dense_policy"),
                            "dense_only": chunk_state.get("dense_only"),
                            "sparse_status": chunk_state.get("sparse_status"),
                            "sparse_backend": chunk_state.get("sparse_backend"),
                            "sparse_fallback_reason": chunk_state.get("sparse_fallback_reason"),
                            "retrieval_profile": chunk_state.get("retrieval_profile"),
                            "retrieval_plan": chunk_state.get("retrieval_plan"),
                            "scope_confidence": chunk_state.get("scope_confidence"),
                            "scope_reason": chunk_state.get("scope_reason"),
                            "latency_budget": chunk_state.get("latency_budget"),
                        },
                        "is_final": False,
                    }
                )

            # Persist canonical Run + kick auto-eval. The front polls
            # /evaluation/by-run/{run_id} when it receives the
            # ``eval_pending`` chunk below so a breach can surface as
            # a toast while the judge runs in the background.
            run_id = None
            if full_content:
                run_completed_at = datetime.utcnow()
                run_id = _persist_chat_run(
                    db,
                    workspace_id=workspace.id,
                    system_id=_resolve_system_id(db, workspace.id, request.agent_id),
                    query=validated_query,
                    response_text="".join(full_content),
                    sources=chunk_state["sources"],
                    reasoning_trace=chunk_state["reasoning_trace"],
                    started_at=run_started_at,
                    completed_at=run_completed_at,
                    duration_ms=(_time.time() - run_started_ts) * 1000.0,
                    extra_output={
                        "rag_context": chunk_state["rag_context"],
                        "retrieval_metrics": chunk_state["retrieval_metrics"],
                        "retrieval_worker_task_id": chunk_state["retrieval_worker_task_id"],
                        "retrieval_fallback": chunk_state["retrieval_fallback"],
                        "fallback_reason": fallback_reason,
                        "knowledge_scope": request_dict.get("knowledge_scope") or chunk_state.get("knowledge_scope"),
                        "context_id": request.context_id,
                        "context_mode": request.context_mode,
                        "assistant_profile": request.assistant_profile,
                        "collections_touched": chunk_state.get("collections_touched"),
                        "retrieval_scope": chunk_state.get("retrieval_scope"),
                        "retrieval_plan": chunk_state.get("retrieval_plan"),
                        "scope_confidence": chunk_state.get("scope_confidence"),
                        "scope_reason": chunk_state.get("scope_reason"),
                        "dense_policy": chunk_state.get("dense_policy"),
                        "dense_only": chunk_state.get("dense_only"),
                        "sparse_status": chunk_state.get("sparse_status"),
                        "sparse_backend": chunk_state.get("sparse_backend"),
                        "sparse_fallback_reason": chunk_state.get("sparse_fallback_reason"),
                        "retrieval_profile": chunk_state.get("retrieval_profile"),
                        "latency_budget": chunk_state.get("latency_budget"),
                        "score_threshold_applied": chunk_state.get("score_threshold_applied"),
                        "deep_retrieval_recommended": chunk_state.get("deep_retrieval_recommended"),
                        "deep_job_id": chunk_state.get("deep_job_id"),
                        "deep_poll_url": chunk_state.get("deep_poll_url"),
                        "deep_status": chunk_state.get("deep_status"),
                        "grounding_mode": grounding_policy["mode"],
                        "grounding_policy": grounding_policy,
                    },
                )
                if run_id and assistant_message_id:
                    persisted_message = db.query(Message).filter(Message.id == assistant_message_id).first()
                    if persisted_message:
                        persisted_message.meta_data = {
                            **(persisted_message.meta_data or {}),
                            "run_id": run_id,
                        }
                        db.commit()
            if run_id:
                yield _sse_data(
                    {
                        "chunk_type": "eval_pending",
                        "run_id": run_id,
                        "is_final": False,
                    }
                )

            yield _sse_done()
        except asyncio.CancelledError:
            stream_status = "cancelled"
            raise
        except Exception as e:
            stream_status = "error"
            logger.error("Streaming error", error=str(e))
            yield _sse_data(_error_chunk("CHAT_STREAM_ERROR", str(e), recoverable=True))
            yield _sse_done()
        finally:
            metrics_collector.finish_stream(stream_id, status=stream_status)
    
    return StreamingResponse(generate(), media_type="text/event-stream")
