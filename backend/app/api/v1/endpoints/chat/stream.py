"""POST /stream: the SSE chat endpoint."""

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.endpoints.agents import get_orchestrator
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.errors import ValidationError
from app.core.monitoring import metrics_collector
from app.core.settings_manager import get_resolved_settings
from app.db.base import get_db
from app.models.user import Message, User
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace
from app.services.action_plans import action_context_for_chat
from app.services.actions import handle_transverse_chat_action
from app.services.chat_agentic_runtime import (
    agentic_event_chunks,
    agentic_timeout_seconds,
    create_agentic_chat_run,
    iter_agentic_run_events,
    load_agentic_chat_outcome,
    mark_agentic_fallback,
)
from app.services.chat_execution_policy import (
    resolve_chat_execution,
)
from app.services.chat_grounding import resolve_grounding_policy
from app.services.chat_trivial_bypass import maybe_trivial_bypass
from app.services.evaluation.auto_eval import schedule_eval
from app.services.industrial_answer_profile import (
    apply_answer_policy_to_text,
)
from app.services.system_engine_authorization import enforce_system_engine_run
from app.services.visual_intelligence import handle_visual_chat_query, visual_context_for_chat
from app.services.workspace_calendar import calendar_context_for_chat, handle_calendar_chat_action
from app.services.workspace_maps import handle_map_chat_query
from app.api.v1.endpoints.chat.common import (
    ChatRequest,
    _apply_response_language_contract,
    _apply_workspace_chat_flow_defaults,
    _collect_chat_chunk,
    _error_chunk,
    _resolve_response_language,
    _resolve_system_id,
    _sse_data,
    _sse_done,
    _trivial_bypass_for_language,
    _trivial_bypass_metadata,
    logger,
    query_validator,
    router,
)
from app.api.v1.endpoints.chat.sessions import (
    _apply_context_to_chat_request,
    _apply_retrieval_budget_policy,
    _can_apply_trivial_bypass,
    _can_force_agentic_canary,
    _canonical_answer_hit,
    _canonical_answer_shortcut_allowed,
    _ensure_chat_session,
    _persist_chat_run,
    _persist_trivial_bypass_turn,
    _resolve_chat_context,
    _touch_chat_session,
)
from app.api.v1.endpoints.chat.retrieval import (
    _apply_collection_access,
    _deep_refinement_preview_text,
    _dense_fast_degraded_reply,
    _grounding_degraded_reply,
    _queue_auto_deep_retrieval_job,
    _retrieval_fallback_reason,
    _retrieval_has_grounded_context,
    _retrieval_metrics,
    _retrieval_observability,
    _vigie_executive_quick_reply,
)
from app.api.v1.endpoints.chat.agentic import (
    _agentic_request_context,
    _apply_agentic_classic_fallback_scope,
    _consume_expert_teaching_turn,
    _latest_salient_entities,
    _load_chat_conversation_state,
    _persist_agentic_chat_turn,
    _source_anchor_texts,
    _try_registry_chat_action,
    _turn_salient_entities,
)


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
            requested_system_id = request.agent_id
            _apply_workspace_chat_flow_defaults(db, workspace=workspace, request=request)
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
            try:
                _apply_collection_access(db, workspace=workspace, user=user, request_dict=request_dict)
            except HTTPException:
                yield _sse_data(
                    _error_chunk(
                        "COLLECTION_NOT_FOUND",
                        "Collection not found",
                        recoverable=False,
                    )
                )
                yield _sse_done()
                return
            if request.rag_mode_override:
                request_dict["rag_pipeline_mode"] = request.rag_mode_override

            empty_bypass = maybe_trivial_bypass(request.query)
            if (
                empty_bypass
                and not str(request.query or "").strip()
                and _can_apply_trivial_bypass(db, workspace=workspace, request=request)
            ):
                response_language = _resolve_response_language(request, request.query)
                request.response_language = response_language
                empty_bypass = _trivial_bypass_for_language(empty_bypass, response_language)
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
                        "details": _trivial_bypass_metadata(empty_bypass, ""),
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
            response_language = _resolve_response_language(request, validated_query)
            request.response_language = response_language
            request_dict["ui_locale"] = request.ui_locale
            _apply_response_language_contract(request_dict, response_language)

            trivial_bypass = maybe_trivial_bypass(validated_query)
            if trivial_bypass and _can_apply_trivial_bypass(
                db, workspace=workspace, request=request
            ):
                trivial_bypass = _trivial_bypass_for_language(trivial_bypass, response_language)
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
                        "details": _trivial_bypass_metadata(trivial_bypass, validated_query),
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

            teaching = await _consume_expert_teaching_turn(
                db,
                workspace=workspace,
                user=user,
                request=request,
                query=validated_query,
            )
            if teaching:
                # Consumed as a correction: no retrieval, so no density banner
                # and no async Deep Retrieval for this turn.
                yield _sse_data(
                    {
                        "chunk_type": "text",
                        "content": teaching["acknowledgement"],
                        "sources": [],
                        "run_id": teaching["run_id"],
                        "expert_correction": teaching["expert_correction"],
                        "is_final": True,
                    }
                )
                yield _sse_done()
                return

            canonical = (
                None
                if (
                    request.context_id
                    or request.knowledge_scope
                    or response_language != "fr"
                    or not _canonical_answer_shortcut_allowed(workspace)
                )
                else _canonical_answer_hit(
                    db,
                    workspace_id=workspace.id,
                    query=validated_query,
                )
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

            registry_system_id = _resolve_system_id(db, workspace.id, request.agent_id)
            registry_action = await _try_registry_chat_action(
                db,
                workspace,
                user,
                query=validated_query,
                assistant_profile=request.assistant_profile,
                session_id=request.session_id,
                knowledge_scope=request.knowledge_scope,
                system_id=registry_system_id,
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
                    system_id=registry_system_id,
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
                    sources=[
                        {
                            "title": "Agenda institutionnel",
                            "source_label": "Agenda institutionnel",
                            "kind": "calendar",
                        }
                    ],
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
                    sources=[
                        {
                            "title": "Actions cabinet",
                            "source_label": "Actions cabinet",
                            "kind": "action_plan",
                        }
                    ],
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
                    sources=[
                        {
                            "title": "Flux visuels institutionnels",
                            "source_label": "Flux visuels institutionnels",
                            "kind": "visual_stream",
                        }
                    ],
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
                        "sources": [
                            {"title": "Flux visuels institutionnels", "kind": "visual_stream"}
                        ],
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
                sources = map_action.get("sources") or [
                    {"title": "Carte strategique", "kind": "workspace_map"}
                ]
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

            execution_decision = resolve_chat_execution(
                db,
                workspace=workspace,
                requested_system_id=requested_system_id,
                session_id=request.session_id,
                answer_profile=request.answer_profile,
                context_id=request.context_id,
                rag_mode_override=request.rag_mode_override,
                allow_forced_agentic=_can_force_agentic_canary(
                    db,
                    user=user,
                    workspace=workspace,
                ),
            )
            if not execution_decision.is_agentic:
                _apply_agentic_classic_fallback_scope(request_dict, execution_decision)
            agentic_fallback_metadata: Optional[dict[str, Any]] = None
            if execution_decision.is_agentic:
                try:
                    enforce_system_engine_run(
                        db,
                        user=user,
                        workspace=workspace,
                        system=execution_decision.executor_system,
                        source="chat.stream",
                    )
                except HTTPException:
                    db.rollback()
                    yield _sse_data(
                        _error_chunk(
                            "SYSTEM_ENGINE_RUN_DENIED",
                            "System execution is not authorized",
                            recoverable=False,
                        )
                    )
                    yield _sse_done()
                    return
                conversation_history, previous_salient_entities = _load_chat_conversation_state(
                    db, session_id=request.session_id
                )
                agentic_run_id: Optional[str] = None
                try:
                    agentic_run = create_agentic_chat_run(
                        db,
                        decision=execution_decision,
                        workspace_id=workspace.id,
                        workspace_slug=workspace.slug,
                        user_id=getattr(user, "id", None),
                        session_id=request.session_id,
                        query=validated_query,
                        conversation_history=conversation_history,
                        salient_entities=previous_salient_entities,
                        request_context=_agentic_request_context(
                            db,
                            workspace=workspace,
                            request=request,
                            grounding_policy=grounding_policy,
                        ),
                    )
                    agentic_run_id = agentic_run.id
                    async for event in iter_agentic_run_events(
                        agentic_run.id,
                        timeout_seconds=agentic_timeout_seconds(execution_decision.executor_system),
                    ):
                        for chunk in agentic_event_chunks(event, run_id=agentic_run.id):
                            yield _sse_data(chunk)
                    outcome = load_agentic_chat_outcome(
                        db,
                        run_id=agentic_run.id,
                        system=execution_decision.executor_system,
                    )
                    if outcome.succeeded or outcome.policy_terminal:
                        content, answer_policy_violations = apply_answer_policy_to_text(
                            outcome.answer,
                            answer_policy=request.answer_policy
                            if isinstance(request.answer_policy, dict)
                            else None,
                            profile_decision=request.answer_profile_decision
                            if isinstance(request.answer_profile_decision, dict)
                            else None,
                        )
                        try:
                            _persist_agentic_chat_turn(
                                db,
                                request=request,
                                query=validated_query,
                                run_id=outcome.run_id,
                                content=content,
                                sources=outcome.sources,
                                metadata=outcome.metadata,
                                previous_salient_entities=previous_salient_entities,
                                answer_policy_violations=answer_policy_violations,
                                schedule_evaluation=outcome.succeeded,
                            )
                        except Exception as persist_exc:  # noqa: BLE001
                            # The Run already owns one safe terminal answer.
                            # History persistence must never generate a second
                            # classic Run/answer for the same user turn.
                            logger.exception(
                                "agentic chat stream persistence failed",
                                run_id=outcome.run_id,
                                error=str(persist_exc),
                            )
                            if outcome.succeeded:
                                try:
                                    schedule_eval(outcome.run_id)
                                except Exception:  # noqa: BLE001
                                    pass
                        yield _sse_data(
                            {
                                "chunk_type": "retrieval",
                                "phase": "completed",
                                "content": "",
                                "message": "Recherche agentique terminée",
                                "details": {
                                    **(outcome.metadata.get("retrieval_metrics") or {}),
                                    "retrieval_scope": outcome.metadata.get("retrieval_scope"),
                                    "retrieval_plan": outcome.metadata.get("retrieval_plan"),
                                    "retrieval_decision_trace": outcome.metadata.get(
                                        "retrieval_decision_trace"
                                    ),
                                    "route": outcome.metadata.get("route"),
                                },
                                "run_id": outcome.run_id,
                                "is_final": False,
                            }
                        )
                        yield _sse_data(
                            {
                                "chunk_type": "text",
                                "content": content,
                                "sources": outcome.sources,
                                "run_id": outcome.run_id,
                                "route": outcome.metadata.get("route") or "agentic",
                                "policy_terminal": outcome.policy_terminal,
                                "is_final": True,
                            }
                        )
                        if outcome.succeeded:
                            yield _sse_data(
                                {
                                    "chunk_type": "eval_pending",
                                    "run_id": outcome.run_id,
                                    "is_final": False,
                                }
                            )
                        elif (
                            outcome.policy_terminal
                            and outcome.metadata.get("route") == "agentic_review"
                        ):
                            yield _sse_data(
                                {
                                    "chunk_type": "hitl_pending",
                                    "run_id": outcome.run_id,
                                    "is_final": False,
                                }
                            )
                        yield _sse_done()
                        return
                    agentic_fallback_metadata = mark_agentic_fallback(
                        db,
                        run_id=agentic_run.id,
                        reason=outcome.fallback_reason or "agentic_technical_failure",
                    )
                except Exception as exc:  # noqa: BLE001 - classic technical safety net.
                    db.rollback()
                    logger.exception("agentic chat stream attempt failed", error=str(exc))
                    if agentic_run_id:
                        agentic_fallback_metadata = mark_agentic_fallback(
                            db,
                            run_id=agentic_run_id,
                            reason="agentic_adapter_error",
                        )
                    else:
                        agentic_fallback_metadata = {"fallback_reason": "agentic_adapter_error"}
                if agentic_fallback_metadata:
                    fallback_collection = _apply_agentic_classic_fallback_scope(
                        request_dict,
                        execution_decision,
                    )
                    yield _sse_data(
                        {
                            "chunk_type": "decision_step",
                            "decision_step": {
                                "id": f"agentic:{agentic_run_id or 'uncreated'}:fallback",
                                "type": "routing",
                                "status": "warning",
                                "title": "Repli technique contrôlé",
                                "description": "Le moteur classique reprend le tour sans élargir le corpus.",
                                "metrics": {
                                    **agentic_fallback_metadata,
                                    "collection": fallback_collection,
                                },
                            },
                            "route": "classic_fallback",
                            "is_final": False,
                        }
                    )

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

            # Apply settings defaults if not provided
            if not request_dict.get("agent_preferences"):
                request_dict["agent_preferences"] = {}
            if not request_dict["agent_preferences"].get("preferred_agents"):
                request_dict["agent_preferences"]["preferred_agents"] = app_settings.get(
                    "preferredAgents", []
                )
            if not request_dict["agent_preferences"].get("model_preferences"):
                request_dict["agent_preferences"]["model_preferences"] = {}
            if not request_dict["agent_preferences"]["model_preferences"].get("model"):
                request_dict["agent_preferences"]["model_preferences"]["model"] = (
                    app_settings.get("defaultModel") or settings.default_model
                )
            if not request_dict["agent_preferences"]["model_preferences"].get("provider"):
                request_dict["agent_preferences"]["model_preferences"]["provider"] = (
                    app_settings.get("defaultProvider") or settings.default_provider
                )

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
            previous_salient_entities = None
            if request.session_id:
                # Get previous messages from this session for context
                previous_messages = (
                    db.query(Message)
                    .filter(Message.session_id == request.session_id)
                    .order_by(Message.timestamp.asc())
                    .all()
                )

                # Token-budgeted history: keep as many recent turns as fit the
                # budget and condense the older ones into a summary prefix —
                # a fixed message count silently lost long-session context.
                from app.core.memory_manager import memory_manager

                conversation_history = memory_manager.build_chat_context(
                    [{"role": msg.role, "content": msg.content} for msg in previous_messages],
                    max_tokens=settings.chat_history_token_budget,
                )

                # Salient entities precomputed when the previous turn was
                # persisted — lets follow-up retrieval anchor on the project/
                # machine references and line positions without re-scanning
                # the history. A teaching turn stores them on the ack.
                previous_salient_entities = _latest_salient_entities(previous_messages)

                # Save user message
                user_message = Message(
                    id=str(uuid.uuid4()),
                    session_id=request.session_id,
                    role="user",
                    content=request.query,
                    meta_data={},
                )
                db.add(user_message)

                # Update session last_activity
                from app.models.user import Session as SessionModel

                session = (
                    db.query(SessionModel).filter(SessionModel.id == request.session_id).first()
                )
                if session:
                    session.last_activity = datetime.utcnow()

                db.commit()

            # Add conversation history to request for context
            if conversation_history:
                if not request_dict.get("context"):
                    request_dict["context"] = {}
                request_dict["context"]["conversation_history"] = conversation_history
                request_dict["context"]["memory_type"] = "long_term"  # Default to long-term memory
                if previous_salient_entities:
                    request_dict["context"]["salient_entities"] = previous_salient_entities
            # Meta follow-ups ("résume", "détaille") legitimately answer from
            # the previous turn without fresh retrieval — exempt them from the
            # post-retrieval grounding guard.
            try:
                from app.agents.procurement_agent import _is_meta_followup

                is_conversation_meta_followup = _is_meta_followup(
                    validated_query, conversation_history
                )
            except Exception:  # noqa: BLE001 - guard exemption must never break chat.
                is_conversation_meta_followup = False
            if request.assistant_profile in {"vigie_executive", "octave_executive"}:
                if not request_dict.get("context"):
                    request_dict["context"] = {}
                request_dict["context"]["workspace_calendar"] = calendar_context_for_chat(
                    db, workspace
                )
                request_dict["context"]["workspace_actions"] = action_context_for_chat(
                    db, workspace
                )
                request_dict["context"]["workspace_visual_observations"] = visual_context_for_chat(
                    db, workspace
                )

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
                        if (
                            chunk.get("chunk_type") == "retrieval"
                            and chunk.get("phase") != "started"
                            and not full_content
                        ):
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
                            grounding_reply = _grounding_degraded_reply(
                                chunk_state,
                                grounding_policy,
                                response_language=response_language,
                                is_meta_followup=is_conversation_meta_followup,
                            )
                            if grounding_reply:
                                chunk_state["grounding_state"] = "no_grounded_context"
                                full_content.append(grounding_reply)
                                yield _sse_data(
                                    {
                                        "chunk_type": "text",
                                        "content": grounding_reply,
                                        "is_final": False,
                                    }
                                )
                                break
                            if (
                                _retrieval_has_grounded_context(chunk_state) is False
                                and not is_conversation_meta_followup
                            ):
                                # Balanced mode keeps generating but the turn is
                                # flagged so audit/UI can show it ran ungrounded.
                                chunk_state["grounding_state"] = "foundational_fallback"
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
            deep_partial_answer = "".join(full_content)
            if full_content:
                raw_stream_content = "".join(full_content)
                deep_partial_answer = _deep_refinement_preview_text(
                    content=raw_stream_content,
                    state=chunk_state,
                    grounding_policy=grounding_policy,
                )
                sanitized_content, answer_policy_violations = apply_answer_policy_to_text(
                    raw_stream_content,
                    answer_policy=request_dict.get("answer_policy")
                    if isinstance(request_dict.get("answer_policy"), dict)
                    else None,
                    profile_decision=request_dict.get("answer_profile_decision")
                    if isinstance(request_dict.get("answer_profile_decision"), dict)
                    else None,
                )
                full_content[:] = [sanitized_content]
                chunk_state["answer_profile"] = request_dict.get("answer_profile")
                chunk_state["answer_profile_decision"] = request_dict.get("answer_profile_decision")
                chunk_state["answer_policy_applied"] = bool(request_dict.get("answer_policy"))
                chunk_state["answer_policy_violations"] = answer_policy_violations

            # Save assistant message after streaming completes
            if request.session_id and full_content:
                # Build meta_data with decision steps
                meta_data = {
                    "reasoning_trace": chunk_state["reasoning_trace"],
                    "sources": chunk_state["sources"],
                    "context_id": request.context_id,
                    "context_mode": request.context_mode,
                    "knowledge_scope": request_dict.get("knowledge_scope")
                    or chunk_state.get("knowledge_scope"),
                    "grounding_mode": grounding_policy["mode"],
                    "grounding_policy": grounding_policy,
                    "grounding_state": chunk_state.get("grounding_state"),
                    "response_language": response_language,
                    "answer_profile": chunk_state.get("answer_profile"),
                    "answer_profile_decision": chunk_state.get("answer_profile_decision"),
                    "answer_policy_applied": chunk_state.get("answer_policy_applied"),
                    "answer_policy_violations": chunk_state.get("answer_policy_violations"),
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
                    **(agentic_fallback_metadata or {}),
                    **_retrieval_observability(chunk_state),
                }

                # Add decision steps if any were collected
                if decision_steps:
                    meta_data["decision_steps"] = decision_steps
                    if pipeline_total_time is not None:
                        meta_data["decision_pipeline_total_time"] = pipeline_total_time

                # Precompute salient entities for the next turn's retrieval
                # anchoring — paid here, post-stream, never on the hot path.
                try:
                    source_texts = [
                        text
                        for item in (chunk_state.get("sources") or [])
                        if isinstance(item, dict)
                        for text in _source_anchor_texts(item)
                    ]
                    turn_entities = _turn_salient_entities(
                        validated_query,
                        "".join(full_content),
                        *source_texts,
                        previous=previous_salient_entities,
                    )
                    if turn_entities:
                        meta_data["salient_entities"] = turn_entities
                except Exception:  # noqa: BLE001 - anchoring must never break persistence.
                    pass

                assistant_message = Message(
                    id=str(uuid.uuid4()),
                    session_id=request.session_id,
                    role="assistant",
                    content="".join(full_content),
                    meta_data=meta_data,
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
                        partial_answer=deep_partial_answer,
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
                            "parent_retrieval_observability": _retrieval_observability(chunk_state),
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
                        "knowledge_scope": request_dict.get("knowledge_scope")
                        or chunk_state.get("knowledge_scope"),
                        "context_id": request.context_id,
                        "context_mode": request.context_mode,
                        "assistant_profile": request.assistant_profile,
                        "response_language": response_language,
                        "answer_profile": chunk_state.get("answer_profile"),
                        "answer_profile_decision": chunk_state.get("answer_profile_decision"),
                        "answer_policy_applied": chunk_state.get("answer_policy_applied"),
                        "answer_policy_violations": chunk_state.get("answer_policy_violations"),
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
                        **(agentic_fallback_metadata or {}),
                        **_retrieval_observability(chunk_state),
                    },
                )
                if run_id and assistant_message_id:
                    persisted_message = (
                        db.query(Message).filter(Message.id == assistant_message_id).first()
                    )
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
