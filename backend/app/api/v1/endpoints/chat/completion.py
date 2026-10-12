"""POST /completion, deep-retrieval jobs and the retrieval-plan preview."""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.endpoints.agents import get_orchestrator
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.errors import ValidationError
from app.core.settings_manager import get_resolved_settings
from app.db.base import get_db
from app.models.user import Message, User
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.action_plans import action_context_for_chat
from app.services.actions import handle_transverse_chat_action
from app.services.chat_agentic_runtime import (
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
    _resolve_response_language,
    _resolve_system_id,
    _trivial_bypass_for_language,
    logger,
    query_validator,
    response_validator,
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
    _trivial_bypass_completion_payload,
    _user_id,
)
from app.api.v1.endpoints.chat.retrieval import (
    _apply_collection_access,
    _compact_job_text,
    _deep_refinement_preview_text,
    _grounding_degraded_reply,
    _queue_auto_deep_retrieval_job,
    _retrieval_fallback_reason,
    _retrieval_has_grounded_context,
    _retrieval_observability,
    _sanitize_workspace_collection_filters,
    _vigie_executive_quick_reply,
)
from app.api.v1.endpoints.chat.agentic import (
    _agentic_completion_payload,
    _agentic_request_context,
    _apply_agentic_classic_fallback_scope,
    _consume_expert_teaching_turn,
    _load_chat_conversation_state,
    _persist_agentic_chat_turn,
    _try_registry_chat_action,
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
        requested_system_id = request.agent_id
        _apply_workspace_chat_flow_defaults(db, workspace=workspace, request=request)
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
            return _trivial_bypass_completion_payload(run_id, empty_bypass)

        # Validate query
        try:
            validated_query = query_validator.validate(request.query)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

        response_language = _resolve_response_language(request, validated_query)
        request.response_language = response_language
        trivial_bypass = maybe_trivial_bypass(validated_query)
        if trivial_bypass and _can_apply_trivial_bypass(db, workspace=workspace, request=request):
            trivial_bypass = _trivial_bypass_for_language(trivial_bypass, response_language)
            run_id = _persist_trivial_bypass_turn(
                db,
                workspace=workspace,
                request=request,
                query=validated_query,
                bypass=trivial_bypass,
            )
            return _trivial_bypass_completion_payload(run_id, trivial_bypass)

        teaching = await _consume_expert_teaching_turn(
            db,
            workspace=workspace,
            user=user,
            request=request,
            query=validated_query,
        )
        if teaching:
            return {
                "run_id": teaching["run_id"],
                "content": teaching["acknowledgement"],
                "sources": [],
                "status": "completed",
                "expert_correction": teaching["expert_correction"],
            }

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
            run_completed_at = datetime.utcnow()
            run_id = _persist_chat_run(
                db,
                workspace_id=workspace.id,
                system_id=registry_system_id,
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
                sources=[
                    {
                        "title": "Agenda institutionnel",
                        "source_label": "Agenda institutionnel",
                        "kind": "calendar",
                    }
                ],
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
                sources=[
                    {
                        "title": "Actions cabinet",
                        "source_label": "Actions cabinet",
                        "kind": "action_plan",
                    }
                ],
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
                sources=[
                    {
                        "title": "Flux visuels institutionnels",
                        "source_label": "Flux visuels institutionnels",
                        "kind": "visual_stream",
                    }
                ],
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
                sources=map_action.get("sources")
                or [{"title": "Carte strategique", "kind": "workspace_map"}],
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
                "sources": map_action.get("sources")
                or [{"title": "Carte strategique", "kind": "workspace_map"}],
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

        grounding_policy = resolve_grounding_policy(
            query=validated_query,
            workspace=workspace,
            assistant_profile=request.assistant_profile,
            requested_mode=request.grounding_mode,
            context_id=request.context_id,
        )
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
        agentic_fallback_metadata: Optional[dict[str, Any]] = None
        if execution_decision.is_agentic:
            enforce_system_engine_run(
                db,
                user=user,
                workspace=workspace,
                system=execution_decision.executor_system,
                source="chat.completion",
            )
            history, previous_salient_entities = _load_chat_conversation_state(
                db,
                session_id=request.session_id,
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
                    conversation_history=history,
                    salient_entities=previous_salient_entities,
                    request_context=_agentic_request_context(
                        db,
                        workspace=workspace,
                        request=request,
                        grounding_policy=grounding_policy,
                    ),
                )
                agentic_run_id = agentic_run.id
                async for _event in iter_agentic_run_events(
                    agentic_run.id,
                    timeout_seconds=agentic_timeout_seconds(execution_decision.executor_system),
                ):
                    pass
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
                    except Exception as persist_exc:  # noqa: BLE001
                        # The canonical Run is already terminal and safe. Never
                        # generate a second answer/Run because chat-history
                        # persistence failed after successful execution.
                        logger.exception(
                            "agentic chat completion persistence failed",
                            run_id=outcome.run_id,
                            error=str(persist_exc),
                        )
                        if outcome.succeeded:
                            try:
                                schedule_eval(outcome.run_id)
                            except Exception:  # noqa: BLE001
                                pass
                    return _agentic_completion_payload(
                        run_id=outcome.run_id,
                        content=content,
                        sources=outcome.sources,
                        metadata=outcome.metadata,
                        request=request,
                        answer_policy_violations=answer_policy_violations,
                        policy_terminal=outcome.policy_terminal,
                    )
                agentic_fallback_metadata = mark_agentic_fallback(
                    db,
                    run_id=agentic_run.id,
                    reason=outcome.fallback_reason or "agentic_technical_failure",
                )
            except Exception as exc:  # noqa: BLE001 - classic is the technical safety net.
                db.rollback()
                logger.exception("agentic chat completion attempt failed", error=str(exc))
                if agentic_run_id:
                    agentic_fallback_metadata = mark_agentic_fallback(
                        db,
                        run_id=agentic_run_id,
                        reason="agentic_adapter_error",
                    )
                else:
                    agentic_fallback_metadata = {"fallback_reason": "agentic_adapter_error"}

        orchestrator = get_orchestrator()
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")

        # Load resolved preset config for defaults (workspace-scoped).
        app_settings = get_resolved_settings(workspace_id=workspace.id)

        request_dict = request.model_dump()
        request_dict["query"] = validated_query
        request_dict["workspace_slug"] = workspace.slug
        request_dict["workspace_id"] = workspace.id
        request_dict["ui_locale"] = request.ui_locale
        _apply_response_language_contract(request_dict, response_language)
        _apply_context_to_chat_request(request_dict, chat_context)
        _apply_collection_access(db, workspace=workspace, user=user, request_dict=request_dict)
        if not execution_decision.is_agentic or agentic_fallback_metadata:
            _apply_agentic_classic_fallback_scope(request_dict, execution_decision)
        if request.assistant_profile in {"vigie_executive", "octave_executive"}:
            request_dict.setdefault("context", {})[
                "workspace_calendar"
            ] = calendar_context_for_chat(db, workspace)
            request_dict.setdefault("context", {})["workspace_actions"] = action_context_for_chat(
                db, workspace
            )
            request_dict.setdefault("context", {})[
                "workspace_visual_observations"
            ] = visual_context_for_chat(db, workspace)
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
            if (
                chunk.get("chunk_type") == "retrieval"
                and chunk.get("phase") != "started"
                and not full_content
            ):
                grounding_reply = _grounding_degraded_reply(
                    chunk_state,
                    grounding_policy,
                    response_language=request.response_language,
                )
                if grounding_reply:
                    chunk_state["grounding_state"] = "no_grounded_context"
                    full_content.append(grounding_reply)
                    break
                if _retrieval_has_grounded_context(chunk_state) is False:
                    chunk_state["grounding_state"] = "foundational_fallback"

            if chunk.get("is_final"):
                break

        # Calculate pipeline total time
        if pipeline_start_time:
            pipeline_total_time = int((time.time() - pipeline_start_time) * 1000)
        else:
            pipeline_total_time = None

        # Combine chunks
        raw_content = "".join(full_content)
        content = raw_content
        content, answer_policy_violations = apply_answer_policy_to_text(
            content,
            answer_policy=request_dict.get("answer_policy")
            if isinstance(request_dict.get("answer_policy"), dict)
            else None,
            profile_decision=request_dict.get("answer_profile_decision")
            if isinstance(request_dict.get("answer_profile_decision"), dict)
            else None,
        )
        chunk_state["answer_profile"] = request_dict.get("answer_profile")
        chunk_state["answer_profile_decision"] = request_dict.get("answer_profile_decision")
        chunk_state["answer_policy_applied"] = bool(request_dict.get("answer_policy"))
        chunk_state["answer_policy_violations"] = answer_policy_violations

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
                partial_answer=_deep_refinement_preview_text(
                    content=raw_content,
                    state=chunk_state,
                    grounding_policy=grounding_policy,
                ),
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
                meta_data={},
            )
            db.add(user_message)

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

            # Save assistant message
            assistant_message = Message(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="assistant",
                content=content,
                meta_data=meta_data,
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
            "answer_profile": chunk_state.get("answer_profile"),
            "answer_policy_applied": chunk_state.get("answer_policy_applied"),
            "answer_policy_violations": chunk_state.get("answer_policy_violations"),
            **_retrieval_observability(chunk_state),
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
    from app.services.workspace_jobs import (
        create_workspace_job,
        dispatch_workspace_job,
        serialize_job,
    )

    _apply_workspace_chat_flow_defaults(db, workspace=workspace, request=request)
    try:
        validated_query = query_validator.validate(request.query)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    response_language = _resolve_response_language(request, validated_query)
    request.response_language = response_language
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
        session_query = (
            session_query.filter(ChatSession.user_id == user_id)
            if user_id
            else session_query.filter(ChatSession.user_id.is_(None))
        )
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
    request_dict["ui_locale"] = request.ui_locale
    _apply_response_language_contract(request_dict, response_language)
    if request.rag_mode_override:
        request_dict["rag_pipeline_mode"] = request.rag_mode_override
    _apply_context_to_chat_request(request_dict, chat_context)
    _apply_collection_access(db, workspace=workspace, user=user, request_dict=request_dict)
    retrieval_scope_decision = resolve_chat_execution(
        db,
        workspace=workspace,
        requested_system_id=request.agent_id,
        session_id=request.session_id,
        answer_profile=request.answer_profile,
        context_id=request.context_id,
        rag_mode_override=request.rag_mode_override,
        allow_forced_agentic=False,
    )
    _apply_agentic_classic_fallback_scope(request_dict, retrieval_scope_decision)
    _apply_retrieval_budget_policy(request_dict)

    profile = get_retrieval_profile(request_dict)
    collection_ref = profile.get("collection")
    collection = (
        db.query(KnowledgeCollection)
        .filter(
            (
                (KnowledgeCollection.slug == collection_ref)
                | (KnowledgeCollection.id == collection_ref)
            ),
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
            "response_language": response_language,
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
    request_dict["retrieval_filters"] = _sanitize_workspace_collection_filters(
        db,
        workspace_id=workspace.id,
        retrieval_filters=request_dict.get("retrieval_filters"),
    )
    if request.rag_mode_override:
        request_dict["rag_pipeline_mode"] = request.rag_mode_override
    _apply_context_to_chat_request(request_dict, chat_context)
    _apply_collection_access(db, workspace=workspace, user=user, request_dict=request_dict)
    retrieval_scope_decision = resolve_chat_execution(
        db,
        workspace=workspace,
        requested_system_id=request.agent_id,
        session_id=request.session_id,
        answer_profile=request.answer_profile,
        context_id=request.context_id,
        rag_mode_override=request.rag_mode_override,
        allow_forced_agentic=False,
    )
    _apply_agentic_classic_fallback_scope(request_dict, retrieval_scope_decision)
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
