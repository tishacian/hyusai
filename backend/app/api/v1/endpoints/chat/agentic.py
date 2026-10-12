"""Registry actions, agentic routing and expert-teaching turns."""

import uuid
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.endpoints.knowledge_capture import (
    apply_chat_correction,
    authorize_chat_correction,
)
from app.core.config import settings
from app.models.run import Run
from app.models.system import System
from app.models.user import Message, User
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace
from app.services.actions import handle_registry_chat_action
from app.services.chat_agentic_runtime import (
    create_chat_adapter_run,
)
from app.services.chat_execution_policy import (
    ChatExecutionDecision,
)
from app.services.evaluation.auto_eval import schedule_eval
from app.services.industrial_answer_profile import (
    apply_answer_policy_to_text,
)
from app.services.knowledge_capture import is_teaching_utterance
from app.services.systems.bootstrap import (
    workspace_chat_system_id,
)
from app.api.v1.endpoints.chat.common import (
    ChatRequest,
    _as_dict,
    _resolve_system_id,
    logger,
)
from app.api.v1.endpoints.chat.sessions import (
    _persist_chat_run,
    _touch_chat_session,
)


async def _try_registry_chat_action(
    db: Session,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str],
    session_id: Optional[str] = None,
    knowledge_scope: Optional[str] = None,
    system_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return await handle_registry_chat_action(
        db,
        workspace,
        user,
        query=query,
        assistant_profile=assistant_profile,
        session_id=session_id,
        knowledge_scope=knowledge_scope,
        system_id=system_id,
    )


# ---------------------------------------------------------------------------
# Hybrid agentic routing (Phase 3). Off by default via
# ``settings.enable_agentic_chat``; when enabled, only *niche* intents
# (inventory / comparison / equipment / table / multi-hop) are dispatched to
# the seeded agentic DAG System — every other intent (and every failure mode)
# stays on the classic ``AgentOrchestrator`` path. The gate is fail-open: a
# missing System, a DAG error, or an empty answer all fall back to classic so
# ``/chat`` never breaks.
# ---------------------------------------------------------------------------
AGENTIC_CHAT_SYSTEM_NAME = "Andritz Chat Agentic"
AGENTIC_CHAT_VARIANT = "chat_agentic_thinking_v1"
_AGENTIC_NICHE_PROFILES = frozenset(
    {"transversal_inventory", "comparison", "equipment_detail", "table_extract", "multi_hop"}
)


def _should_route_agentic(profile: Optional[str]) -> bool:
    """Gate predicate: agentic only when the flag is on and the profile is niche."""
    return (
        bool(getattr(settings, "enable_agentic_chat", False)) and profile in _AGENTIC_NICHE_PROFILES
    )


def _lookup_agentic_chat_system(db: Session, workspace: Workspace) -> Optional[System]:
    """Find the seeded 'Andritz Chat Agentic' System (variant match).

    Mirrors ``agentic_chat_spike.lookup_agentic_system``: prefer an active
    System on the target variant, otherwise the first candidate. Returns
    ``None`` when the System is not seeded so the caller degrades to classic.
    """
    candidates = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == AGENTIC_CHAT_SYSTEM_NAME)
        .all()
    )
    fallback: Optional[System] = None
    for candidate in candidates:
        if (candidate.flow_definition or {}).get("variant") == AGENTIC_CHAT_VARIANT:
            if candidate.status == "active":
                return candidate
            fallback = fallback or candidate
    return fallback or (candidates[0] if candidates else None)


def _agentic_run_answer(output_ref: Any) -> str:
    """User-facing text from a completed agentic Run's ``output_ref``.

    The finalized DAG routes to one of three sinks: ``sink.final_answer``
    (``answer``), ``sink.ask_user`` (``clarifying_question``) or ``sink.oos``
    (``reason``). ``_collect_terminal_output`` merges the chosen sink onto
    ``run.output_ref``.
    """
    if isinstance(output_ref, dict):
        for key in ("answer", "response", "clarifying_question", "reason"):
            value = output_ref.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


async def _maybe_agentic_chat_completion(
    db: Session,
    *,
    workspace: Workspace,
    request: "ChatRequest",
    query: str,
) -> Optional[Dict[str, Any]]:
    """Dispatch a niche chat turn through the seeded agentic DAG System.

    Returns a ``/chat`` completion payload on success, or ``None`` to signal
    the caller to fall back to the classic orchestrator. This never raises:
    a missing System, a DAG error, a non-completed run, or an empty answer all
    degrade to ``None`` so the classic path stays a byte-for-byte safety net.
    Mirrors ``agentic_chat_spike.run_arm_agentic``: create a ``Run`` against the
    System, walk it with ``execute_run_dag``, then re-read the committed row.
    """
    try:
        system = _lookup_agentic_chat_system(db, workspace)
        if system is None:
            logger.info(
                "agentic chat: system not seeded, using classic path", workspace_id=workspace.id
            )
            return None

        from app.services.run_engine.dag import execute_run_dag

        run = create_chat_adapter_run(
            db,
            workspace=workspace,
            system=system,
            payload={"query": query, "conversation_history": []},
            session_id=request.session_id,
            adapter_evidence={"adapter_path": "hybrid_agentic_v1"},
        )
        run_id = run.id

        # ``execute_run_dag`` opens its OWN session and commits there; re-read
        # the fresh row (expire the stale identity-mapped snapshot first).
        await execute_run_dag(run_id)
        db.expire_all()
        fresh = db.query(Run).filter(Run.id == run_id).first()
        if fresh is None or fresh.status != "completed":
            logger.warning(
                "agentic chat: run not completed, using classic path",
                run_id=run_id,
                status=getattr(fresh, "status", None),
            )
            return None

        output_ref = fresh.output_ref if isinstance(fresh.output_ref, dict) else {}
        answer = _agentic_run_answer(output_ref)
        if not answer.strip():
            logger.warning("agentic chat: empty answer, using classic path", run_id=run_id)
            return None

        content, answer_policy_violations = apply_answer_policy_to_text(
            answer,
            answer_policy=request.answer_policy
            if isinstance(request.answer_policy, dict)
            else None,
            profile_decision=request.answer_profile_decision
            if isinstance(request.answer_profile_decision, dict)
            else None,
        )
        citations = output_ref.get("citations")
        sources = citations if isinstance(citations, list) else []

        # Keep the chat session history coherent when a session is bound. Best
        # effort only — a persistence hiccup must never sink an otherwise good
        # answer, so the classic path's message contract is mirrored loosely.
        if request.session_id:
            try:
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
                            "route": "agentic",
                            "run_id": run_id,
                            "answer_profile": request.answer_profile,
                            "answer_profile_decision": request.answer_profile_decision,
                            "answer_policy_applied": bool(request.answer_policy),
                            "answer_policy_violations": answer_policy_violations,
                            "sources": sources,
                        },
                    )
                )
                db.commit()
            except Exception as exc:  # noqa: BLE001 - history is best-effort
                db.rollback()
                logger.warning("agentic chat: session message persist failed", error=str(exc))

        return {
            "id": run_id,
            "run_id": run_id,
            "content": content,
            "reasoning_trace": None,
            "sources": sources,
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
            "retrieval_fallback": None,
            "fallback_reason": None,
            "latency_budget": None,
            "score_threshold_applied": None,
            "deep_retrieval_recommended": None,
            "deep_job_id": None,
            "deep_poll_url": None,
            "deep_status": None,
            "deep_job": None,
            "answer_profile": request.answer_profile,
            "answer_policy_applied": bool(request.answer_policy),
            "answer_policy_violations": answer_policy_violations,
            "status": "completed",
            "route": "agentic",
        }
    except Exception as exc:  # noqa: BLE001 - the agentic lane must never break /chat
        logger.warning("agentic chat dispatch failed; falling back to classic", error=str(exc))
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


_SALIENT_ENTITY_KEYS = ("references", "positions", "documents")


def _source_anchor_texts(item: Mapping[str, Any]) -> list[str]:
    """Prefer the payload filename over the unwrapped display title.

    ``_display_title`` strips archive-flattened paths down to the leaf name
    (``Spare Parts List_BBA120.pdf``). The planner matches session document
    anchors by substring against ledger paths, so the real
    ``document_filename`` is the value that can be resolved exactly.
    """
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    texts: list[str] = []
    for raw in (
        item.get("filename"),
        item.get("document_filename"),
        metadata.get("document_filename"),
        item.get("title"),
    ):
        value = str(raw or "").strip()
        if value and value not in texts:
            texts.append(value)
    return texts


def _turn_salient_entities(
    *texts: Any,
    previous: Optional[Mapping[str, Any]] = None,
) -> Optional[dict[str, list[str]]]:
    """Build the next-turn anchors, including a station-only follow-up."""
    from app.services.rag.conversation_anchors import extract_salient_entities

    turn_entities = extract_salient_entities(*texts)
    if isinstance(previous, Mapping):
        for key in _SALIENT_ENTITY_KEYS:
            for value in previous.get(key) or []:
                if value not in turn_entities[key] and len(turn_entities[key]) < 6:
                    turn_entities[key].append(value)
    if any(turn_entities.get(key) for key in _SALIENT_ENTITY_KEYS):
        return turn_entities
    return None


def _latest_salient_entities(messages: list[Any]) -> Optional[dict[str, Any]]:
    for msg in reversed(messages):
        meta = getattr(msg, "meta_data", None)
        if not isinstance(meta, dict):
            continue
        entities = meta.get("salient_entities")
        if isinstance(entities, dict):
            return dict(entities)
    return None


def _load_chat_conversation_state(
    db: Session,
    *,
    session_id: Optional[str],
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """Load the same token-budgeted memory used by the classic stream."""

    if not session_id:
        return [], None
    previous_messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.timestamp.asc())
        .all()
    )
    from app.core.memory_manager import memory_manager

    history = memory_manager.build_chat_context(
        [{"role": msg.role, "content": msg.content} for msg in previous_messages],
        max_tokens=settings.chat_history_token_budget,
    )
    return history, _latest_salient_entities(previous_messages)


def _agentic_request_context(
    db: Session,
    *,
    workspace: Workspace,
    request: ChatRequest,
    grounding_policy: dict[str, Any],
) -> dict[str, Any]:
    context = request.model_dump()
    context["surface_system_id"] = workspace_chat_system_id(db, workspace.id)
    context["grounding_policy"] = grounding_policy
    context["grounding_mode"] = grounding_policy.get("mode")
    return context


def _persist_agentic_chat_turn(
    db: Session,
    *,
    request: ChatRequest,
    query: str,
    run_id: str,
    content: str,
    sources: list[dict[str, Any]],
    metadata: dict[str, Any],
    previous_salient_entities: Optional[dict[str, Any]],
    answer_policy_violations: list[Any],
    schedule_evaluation: bool,
) -> Optional[str]:
    """Atomically persist the user/assistant pair and finalize the Run output."""

    assistant_message_id: Optional[str] = None
    adapter_token = str(uuid.uuid4())
    run = db.query(Run).filter(Run.id == run_id).first()
    run_output = dict(run.output_ref or {}) if run is not None else {}
    message_metadata = {
        **metadata,
        "run_id": run_id,
        "sources": sources,
        "response_language": request.response_language,
        "answer_profile": request.answer_profile,
        "answer_profile_decision": request.answer_profile_decision,
        "answer_policy_applied": bool(request.answer_policy),
        "answer_policy_violations": answer_policy_violations,
        "chat_adapter_token": adapter_token,
    }
    try:
        source_texts = [
            text
            for item in sources
            if isinstance(item, dict)
            for text in _source_anchor_texts(item)
        ]
        turn_entities = _turn_salient_entities(
            query, content, *source_texts, previous=previous_salient_entities
        )
        if turn_entities:
            message_metadata["salient_entities"] = turn_entities
    except Exception:  # noqa: BLE001 - anchoring must not break turn persistence.
        pass

    try:
        if request.session_id:
            db.add(
                Message(
                    id=str(uuid.uuid4()),
                    session_id=request.session_id,
                    role="user",
                    content=request.query,
                    meta_data={
                        "chat_turn_id": metadata.get("chat_turn_id"),
                        "route": metadata.get("route"),
                    },
                )
            )
            assistant_message = Message(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="assistant",
                content=content,
                meta_data=message_metadata,
            )
            db.add(assistant_message)
            db.flush()
            assistant_message_id = assistant_message.id
            session = db.query(ChatSession).filter(ChatSession.id == request.session_id).first()
            if session:
                _touch_chat_session(db, session, query=query)
        if run is not None:
            run_input = dict(run.input_ref or {})
            run_input["chat_adapter"] = {
                "assistant_message_id": assistant_message_id,
                "session_id": request.session_id,
                "policy_terminal": bool(metadata.get("route") != "agentic"),
                "origin": "chat_endpoint_v1",
                "token": adapter_token,
            }
            run.input_ref = run_input
            run.output_ref = {
                **run_output,
                **metadata,
                "answer": content,
                "sources": sources,
                "assistant_message_id": assistant_message_id,
                "answer_policy_applied": bool(request.answer_policy),
                "answer_policy_violations": answer_policy_violations,
            }
        db.commit()
    except Exception:
        db.rollback()
        raise

    if schedule_evaluation:
        try:
            schedule_eval(run_id)
        except Exception as exc:  # noqa: BLE001 - eval is asynchronous/best effort.
            logger.warning(
                "agentic chat auto-eval scheduling failed", run_id=run_id, error=str(exc)
            )
    return assistant_message_id


def _agentic_completion_payload(
    *,
    run_id: str,
    content: str,
    sources: list[dict[str, Any]],
    metadata: dict[str, Any],
    request: ChatRequest,
    answer_policy_violations: list[Any],
    policy_terminal: bool,
) -> dict[str, Any]:
    retrieval_metrics = metadata.get("retrieval_metrics") or {}
    return {
        "id": run_id,
        "run_id": run_id,
        "content": content,
        "reasoning_trace": None,
        "sources": sources,
        "retrieval_scope": metadata.get("retrieval_scope"),
        "retrieval_plan": metadata.get("retrieval_plan"),
        "retrieval_decision_trace": metadata.get("retrieval_decision_trace"),
        "retrieval_metrics": retrieval_metrics,
        "collections_touched": metadata.get("collections_touched"),
        "fallback_reason": metadata.get("fallback_reason"),
        "answer_profile": request.answer_profile,
        "answer_policy_applied": bool(request.answer_policy),
        "answer_policy_violations": answer_policy_violations,
        "status": "completed",
        "route": metadata.get("route") or "agentic",
        "policy_terminal": policy_terminal,
    }


def _apply_agentic_classic_fallback_scope(
    request_dict: dict[str, Any],
    decision: ChatExecutionDecision,
) -> Optional[str]:
    # Use the contract frozen by the resolver, never mutable live System state.
    contract = _as_dict(decision.retrieval_contract)
    if contract.get("asset_binding") != "authoritative":
        return None
    collection = str(contract.get("collection") or "").strip()
    if not collection:
        return None
    request_dict["context_collection"] = collection
    request_dict["context_mode"] = "replace"
    request_dict["authoritative_collections"] = [collection]
    request_dict.pop("knowledge_scope", None)
    return collection


def _previous_answered_turn(db: Session, *, session_id: str) -> Optional[Dict[str, Any]]:
    """Last answered turn of the session an expert correction can attach to.

    Correction acknowledgements are skipped: they acquit a fiche, they are not
    an answer an expert can correct.
    """
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.timestamp.asc())
        .all()
    )
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role != "assistant":
            continue
        meta = message.meta_data if isinstance(message.meta_data, dict) else {}
        if meta.get("kind") == "expert_correction_ack":
            continue
        question = next(
            (item.content for item in reversed(messages[:index]) if item.role == "user"),
            "",
        )
        sources = meta.get("sources")
        return {
            "question": question,
            "answer": message.content,
            "message_id": message.id,
            "sources": sources if isinstance(sources, list) else [],
        }
    return None


async def _consume_expert_teaching_turn(
    db: Session,
    *,
    workspace: Workspace,
    user: User,
    request: ChatRequest,
    query: str,
) -> Optional[Dict[str, Any]]:
    """Capture an expert teaching turn as a fiche instead of a new query.

    An expert who answers the assistant ("Pour ta connaissance, sur un J1 on
    installe une toile 2310PW") is not asking anything: replanning retrieval on
    that message produces an unscoped dense fallback and loses the fact. The
    turn is routed to the same proposal path as the "Corriger" button, behind
    the same gates.

    Returns ``None`` — leaving the message on the normal retrieval path — when
    the turn is not a teaching assertion, when there is no previous answer to
    attach it to, or when the caller fails the chat-correction gates. A user
    without ``knowledge_proposal:chat_correct`` therefore keeps plain chat and
    never loses the message.
    """
    if not request.session_id or not is_teaching_utterance(query):
        return None
    anchor = _previous_answered_turn(db, session_id=request.session_id)
    if anchor is None:
        return None
    try:
        source_policy, collection_slug = authorize_chat_correction(
            db,
            user=user,
            workspace=workspace,
        )
    except HTTPException:
        return None

    started_at = datetime.utcnow()
    try:
        correction = await apply_chat_correction(
            db,
            user=user,
            workspace=workspace,
            source_policy=source_policy,
            collection_slug=collection_slug,
            query=anchor["question"],
            assistant_answer=anchor["answer"],
            correction_text=query,
            sources=anchor["sources"],
            session_id=request.session_id,
            message_id=anchor["message_id"],
            trigger="chat_teaching",
        )
    except Exception as exc:  # noqa: BLE001 - a capture failure must not eat the turn.
        db.rollback()
        logger.warning("chat: expert teaching capture failed", error=str(exc))
        return None

    # The teaching message is a real chat turn. It is persisted with a timestamp
    # taken before the capture so it stays ahead of the acknowledgement the
    # correction path already wrote. Positions the expert just taught (J1, …)
    # are stored on both the user turn and the ack so the next question can
    # reuse them.
    teaching_entities = _turn_salient_entities(query)
    teaching_meta: dict[str, Any] = {"expert_teaching": True}
    if teaching_entities:
        teaching_meta["salient_entities"] = teaching_entities
        ack_id = correction.get("ack_message_id")
        if ack_id:
            ack = db.query(Message).filter(Message.id == ack_id).first()
            if ack is not None:
                ack.meta_data = {**(ack.meta_data or {}), "salient_entities": teaching_entities}
    db.add(
        Message(
            id=str(uuid.uuid4()),
            session_id=request.session_id,
            role="user",
            content=request.query,
            timestamp=started_at,
            meta_data=teaching_meta,
        )
    )
    _touch_chat_session(
        db,
        db.query(ChatSession).filter(ChatSession.id == request.session_id).first(),
        query=query,
    )
    db.commit()

    expert_correction = {
        "proposal_id": correction.get("proposal_id"),
        "status": correction.get("status"),
        "collection": correction.get("collection"),
        "document_id": correction.get("document_id"),
        "message_id": correction.get("ack_message_id"),
    }
    completed_at = datetime.utcnow()
    run_id = _persist_chat_run(
        db,
        workspace_id=workspace.id,
        system_id=_resolve_system_id(db, workspace.id, request.agent_id),
        query=query,
        response_text=correction["acknowledgement"],
        sources=[],
        reasoning_trace=None,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        trigger="expert_teaching_correction",
        # The turn acquits a fiche instead of answering: nothing grounded for
        # the auto-eval judge to score.
        schedule=False,
        extra_output={
            "expert_correction": expert_correction,
            "session_id": request.session_id,
        },
    )
    return {
        "acknowledgement": correction["acknowledgement"],
        "run_id": run_id,
        "expert_correction": expert_correction,
    }
