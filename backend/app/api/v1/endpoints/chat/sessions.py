"""Chat sessions, context, retrieval budgets and run persistence."""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.iam.roles import is_admin_template
from app.models.context import Context
from app.models.run import Run
from app.models.system import System
from app.models.user import Message, User
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chat_execution_policy import (
    ANDRITZ_MIGRATION_MARKER,
)
from app.services.chat_run_ledger import enrich_chat_run_ledger
from app.services.chat_trivial_bypass import TrivialBypass
from app.services.evaluation.auto_eval import schedule_eval
from app.services.evaluation.canonical_answer_service import (
    find_canonical_answer,
    record_hit,
)
from app.services.run_outcome_provenance import record_runtime_auto_outcome
from app.api.v1.endpoints.chat.common import (
    ChatRequest,
    _resolve_system_id,
    _trivial_bypass_metadata,
    logger,
)


def _user_id(user: Optional[User]) -> Optional[str]:
    return str(getattr(user, "id", "") or "") or None


def _can_force_agentic_canary(
    db: Session,
    *,
    user: User,
    workspace: Workspace,
) -> bool:
    """Restrict the zero-percent canary escape hatch to workspace admins."""

    if getattr(user, "role", None) == "admin":
        return True
    user_id = getattr(user, "id", None)
    if not user_id:
        return False
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    return bool(membership and is_admin_template(membership.role_template, membership.role))


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
    row = db.query(ChatSession.id).filter(
        ChatSession.id == candidate,
        ChatSession.workspace_id == workspace_id,
        ChatSession.status == "active",
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


# Bounds on the context-signature fallback below. That fallback exists so a
# client which sends no ``session_id`` still gets some continuity — it is a
# convenience, not a durable conversation, and until now it had no end: in
# production one thread had glued 72 messages together over two weeks with no
# way to open a fresh one. Past either bound a NEW thread is opened; the old one
# stays active and readable in the history UI, it just stops being extended.
#
# * Idle age: a thread nobody has touched for half a day is a new conversation,
#   not a continuation. 12 h keeps a whole working day on one thread while
#   guaranteeing that the next morning starts clean.
# * Length: 40 messages is 20 exchanges, far past the history actually replayed
#   to the model (``chat_history_token_budget``), so the surplus is carried as
#   weight and cost without ever being read.
CHAT_SESSION_REUSE_MAX_IDLE = timedelta(hours=12)
CHAT_SESSION_REUSE_MAX_MESSAGES = 40


def _is_chat_session_reusable(db: Session, session: ChatSession, *, now: datetime) -> bool:
    """Whether an existing thread is still a plausible continuation."""
    last_activity = session.last_activity or session.created_at
    if last_activity is None or now - last_activity > CHAT_SESSION_REUSE_MAX_IDLE:
        return False
    message_count = (
        db.query(func.count(Message.id)).filter(Message.session_id == session.id).scalar() or 0
    )
    return message_count < CHAT_SESSION_REUSE_MAX_MESSAGES


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
        query = (
            query.filter(ChatSession.user_id == user_id)
            if user_id
            else query.filter(ChatSession.user_id.is_(None))
        )
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
    latest_query = (
        latest_query.filter(ChatSession.user_id == user_id)
        if user_id
        else latest_query.filter(ChatSession.user_id.is_(None))
    )
    latest = latest_query.order_by(ChatSession.last_activity.desc()).first()
    if (
        latest
        and (request_payload.get("reuse_latest_session") is not False)
        and _is_chat_session_reusable(db, latest, now=now)
    ):
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
    agent_preferences = (
        request_dict.get("agent_preferences")
        if isinstance(request_dict.get("agent_preferences"), dict)
        else {}
    )
    raw_profile = (
        str(request_dict.get("latency_profile") or agent_preferences.get("latency_profile") or "")
        .strip()
        .lower()
    )
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
    source_display_default = (
        top_k if explicit_top_k else min(max(top_k, source_default), 24 if profile != "fast" else 8)
    )
    source_display_k = _int_budget(request_dict.get("source_display_k"), source_display_default)
    synthesis_base = (
        top_k
        if explicit_top_k and not explicit_budget
        else max(top_k, source_display_k, synthesis_default)
    )
    synthesis_k = _int_budget(request_dict.get("synthesis_k"), synthesis_base)
    candidate_base = (
        top_k if explicit_top_k and not explicit_budget else max(synthesis_k, candidate_default)
    )
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
    bypass_metrics = _trivial_bypass_metadata(bypass, query)
    metadata = {
        "trivial_bypass": True,
        "retrieval_metrics": bypass_metrics,
        "retrieval_decision_trace": bypass_metrics.get("retrieval_decision_trace"),
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


def _trivial_bypass_completion_payload(
    run_id: Optional[str], bypass: TrivialBypass
) -> Dict[str, Any]:
    bypass_metrics = _trivial_bypass_metadata(bypass)
    return {
        "run_id": run_id,
        "content": bypass.content,
        "reasoning_trace": None,
        "sources": [],
        "retrieval_metrics": bypass_metrics,
        "retrieval_decision_trace": bypass_metrics.get("retrieval_decision_trace"),
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
        db.flush()
        control = None
        if system_id:
            system = (
                db.query(System)
                .filter(
                    System.id == system_id,
                    System.workspace_id == workspace_id,
                )
                .one_or_none()
            )
            if system is not None:
                # Reuse the canonical execution snapshot instead of allowing
                # the chat surface to invent a parallel provenance format.
                from app.services.run_engine.engine import (
                    _load_control_policy,
                    _snapshot_run_flow,
                )

                # Canonical agentic Runs already pin their contract. A legacy
                # direct chat Run has no frozen Flow contract; never attach a
                # newly published mandate retroactively to that completed turn.
                control = _load_control_policy(db, system, run=run)
                if control is not None:
                    _snapshot_run_flow(
                        db,
                        run,
                        system,
                        first_start=True,
                        control=control,
                    )
        enrich_chat_run_ledger(
            db,
            run,
            sources=sources,
            reasoning_trace=reasoning_trace,
            extra_output=extra_output or {},
            create_invocations_if_missing=True,
        )
        if run.value_source == "auto" and control is not None:
            record_runtime_auto_outcome(run, db=db)
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


def _canonical_answer_shortcut_allowed(workspace: Workspace) -> bool:
    """Do not bypass provenance-bound retrieval for the Andritz experience."""

    workspace_settings = workspace.settings if isinstance(workspace.settings, dict) else {}
    return not (
        workspace_settings.get("family") == "andritz"
        or ANDRITZ_MIGRATION_MARKER in workspace_settings
    )
