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
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.logging import get_logger
from app.core.validation import QueryValidator, ResponseValidator
from app.core.errors import ValidationError
from app.core.settings_manager import get_resolved_settings
from app.db.base import get_db
from app.models.run import Run
from app.models.system import System
from app.models.user import Message, User
from app.models.workspace import Workspace
from app.api.v1.endpoints.agents import get_orchestrator
from app.services.evaluation.auto_eval import schedule_eval
from app.services.evaluation.canonical_answer_service import (
    find_canonical_answer,
    record_hit,
)
from app.services.action_plans import action_context_for_chat, handle_action_plan_chat_action
from app.services.workspace_calendar import calendar_context_for_chat, handle_calendar_chat_action
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
    # Product-facing assistant profile. It does not bypass backend policy; it
    # carries UI/prompt intent into the Run ledger for audit and replay.
    assistant_profile: Optional[str] = None


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


@router.post("/completion")
async def chat_completion(
    request: ChatRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Non-streaming chat completion (scoped to current workspace)."""
    try:
        # Validate query
        try:
            validated_query = query_validator.validate(request.query)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        canonical = _canonical_answer_hit(
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

        action_plan_action = handle_action_plan_chat_action(
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

        orchestrator = get_orchestrator()
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        
        # Load resolved preset config for defaults (workspace-scoped).
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        
        request_dict = request.model_dump()
        request_dict["query"] = validated_query
        request_dict["workspace_slug"] = workspace.slug
        request_dict["workspace_id"] = workspace.id
        if request.assistant_profile == "vigie_executive":
            request_dict.setdefault("context", {})["workspace_calendar"] = calendar_context_for_chat(db, workspace)
            request_dict.setdefault("context", {})["workspace_actions"] = action_context_for_chat(db, workspace)

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
            request_dict["agent_preferences"]["model_preferences"]["model"] = app_settings.get("defaultModel", "deepseek-r1:14b")
        if not request_dict["agent_preferences"]["model_preferences"].get("provider"):
            request_dict["agent_preferences"]["model_preferences"]["provider"] = app_settings.get("defaultProvider", "ollama")
        
        # Apply default temperature and max_tokens from settings
        if request.max_tokens is None:
            request_dict["max_tokens"] = app_settings.get("maxTokens", 2000)
        if request.temperature is None:
            request_dict["temperature"] = app_settings.get("temperature", 0.7)
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
                "knowledge_scope": request.knowledge_scope or chunk_state.get("knowledge_scope"),
                "assistant_profile": request.assistant_profile,
                "collections_touched": chunk_state.get("collections_touched"),
            },
        )

        return {
            "id": chunks[0].get("id") if chunks else None,
            "run_id": run_id,
            "content": content,
            "reasoning_trace": chunk_state["reasoning_trace"],
            "sources": chunk_state["sources"],
            "status": "completed",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat completion error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


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
        try:
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

            app_settings = get_resolved_settings(workspace_id=workspace.id)

            request_dict = request.model_dump()
            request_dict["workspace_slug"] = workspace.slug
            request_dict["workspace_id"] = workspace.id
            if request.rag_mode_override:
                request_dict["rag_pipeline_mode"] = request.rag_mode_override

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

            canonical = _canonical_answer_hit(
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

            action_plan_action = handle_action_plan_chat_action(
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
            
            # Apply settings defaults if not provided
            if not request_dict.get("agent_preferences"):
                request_dict["agent_preferences"] = {}
            if not request_dict["agent_preferences"].get("preferred_agents"):
                request_dict["agent_preferences"]["preferred_agents"] = app_settings.get("preferredAgents", [])
            if not request_dict["agent_preferences"].get("model_preferences"):
                request_dict["agent_preferences"]["model_preferences"] = {}
            if not request_dict["agent_preferences"]["model_preferences"].get("model"):
                request_dict["agent_preferences"]["model_preferences"]["model"] = app_settings.get("defaultModel", "deepseek-r1:14b")
            if not request_dict["agent_preferences"]["model_preferences"].get("provider"):
                request_dict["agent_preferences"]["model_preferences"]["provider"] = app_settings.get("defaultProvider", "ollama")
            
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
            
            # Add RAG settings if provided
            if request.top_k is not None:
                request_dict["top_k"] = request.top_k
            if request.similarity_threshold is not None:
                request_dict["similarity_threshold"] = request.similarity_threshold
            
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
            except TimeoutError as exc:
                stream_error = _error_chunk(
                    "CHAT_STREAM_TIMEOUT",
                    f"Chat stream exceeded {settings.chat_stream_timeout_seconds:.0f}s",
                    recoverable=True,
                    details={"timeout_seconds": settings.chat_stream_timeout_seconds},
                )
                logger.warning("Chat stream timed out", error=str(exc))
            except Exception as exc:  # noqa: BLE001
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
            
            # Save assistant message after streaming completes
            if request.session_id and full_content:
                # Build meta_data with decision steps
                meta_data = {
                    "reasoning_trace": chunk_state["reasoning_trace"],
                    "sources": chunk_state["sources"],
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
                
                # Update session last_activity
                from app.models.user import Session as SessionModel
                session = db.query(SessionModel).filter(SessionModel.id == request.session_id).first()
                if session:
                    session.last_activity = datetime.utcnow()
                
                db.commit()

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
                        "knowledge_scope": request.knowledge_scope or chunk_state.get("knowledge_scope"),
                        "assistant_profile": request.assistant_profile,
                        "collections_touched": chunk_state.get("collections_touched"),
                    },
                )
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
            raise
        except Exception as e:
            logger.error("Streaming error", error=str(e))
            yield _sse_data(_error_chunk("CHAT_STREAM_ERROR", str(e), recoverable=True))
            yield _sse_done()
    
    return StreamingResponse(generate(), media_type="text/event-stream")
