"""Focused contracts for the chat-to-Agentic runtime adapter."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import Message
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace
from app.services.chat_agentic_runtime import (
    AgenticChatOutcome,
    _normalise_sources,
    agentic_event_chunks,
    create_agentic_chat_run,
    finalize_resumed_agentic_chat,
    iter_agentic_run_events,
    load_agentic_chat_outcome,
)
from app.services.chat_execution_policy import ChatExecutionDecision
from app.services.run_engine.events import RunEventBus
from app.services.systems import flow_ingress, flow_publication


def _seed_agentic_system(db_session, *, retrieval_contract: dict[str, Any]) -> System:
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Andritz runtime test",
        slug=f"andritz-runtime-{uuid.uuid4().hex[:8]}",
    )
    # PostgreSQL enforces the FK immediately; flush the tenant before the
    # System rather than relying on SQLite's permissive insert ordering.
    db_session.add(workspace)
    db_session.flush()
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Andritz Chat Agentic",
        objective="Answer from the bound Andritz corpus",
        status="active",
        settings={
            "system_type": "chat_agentic",
            "retrieval_contract": retrieval_contract,
        },
        flow_definition={"variant": "chat_agentic_thinking_v1", "nodes": [], "edges": []},
    )
    db_session.add(system)
    db_session.commit()
    return system


@pytest.mark.asyncio
async def test_iter_events_drains_close_before_executor_returns_and_releases_channel(
    monkeypatch,
) -> None:
    """A close sentinel must not cancel an executor finishing one tick later."""

    from app.services import chat_agentic_runtime as runtime

    local_bus = RunEventBus()
    run_id = f"run-{uuid.uuid4()}"
    state = {"completed": False, "cancelled": False}

    async def _execute(fake_run_id: str) -> dict[str, Any]:
        assert fake_run_id == run_id
        try:
            local_bus.publish(fake_run_id, {"kind": "run_end", "status": "completed"})
            # Deliberately enqueue the sentinel while this task is still live.
            local_bus.close(fake_run_id)
            await asyncio.sleep(0.02)
            state["completed"] = True
            return {"status": "completed"}
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(runtime, "event_bus", local_bus)
    monkeypatch.setattr(runtime, "execute_run_dag", _execute)

    async def _collect() -> list[dict[str, Any]]:
        return [event async for event in iter_agentic_run_events(run_id, timeout_seconds=1.0)]

    events = await asyncio.wait_for(_collect(), timeout=1.0)

    assert events == [{"kind": "run_end", "status": "completed"}]
    assert state == {"completed": True, "cancelled": False}
    assert run_id not in local_bus._channels


@pytest.mark.asyncio
async def test_slow_stream_consumer_cannot_turn_completed_run_into_timeout(monkeypatch) -> None:
    from app.services import chat_agentic_runtime as runtime

    local_bus = RunEventBus()
    run_id = f"run-{uuid.uuid4()}"

    async def _execute(fake_run_id: str) -> dict[str, Any]:
        local_bus.publish(fake_run_id, {"kind": "run_start", "status": "running"})
        await asyncio.sleep(0.005)
        local_bus.publish(fake_run_id, {"kind": "run_end", "status": "completed"})
        local_bus.close(fake_run_id)
        return {"status": "completed"}

    monkeypatch.setattr(runtime, "event_bus", local_bus)
    monkeypatch.setattr(runtime, "execute_run_dag", _execute)

    stream = iter_agentic_run_events(run_id, timeout_seconds=0.05)
    first = await anext(stream)
    await asyncio.sleep(0.1)
    rest = [event async for event in stream]

    assert first["kind"] == "run_start"
    assert [event["kind"] for event in rest] == ["run_end"]
    assert not any(event["kind"] == "execution_timeout" for event in [first, *rest])


def test_run_start_and_end_share_one_visible_step_identity() -> None:
    started = agentic_event_chunks(
        {"kind": "run_start", "status": "running"},
        run_id="run-lifecycle",
    )
    completed = agentic_event_chunks(
        {"kind": "run_end", "status": "completed"},
        run_id="run-lifecycle",
    )

    assert started[0]["decision_step"]["id"] == "agentic:run-lifecycle:run"
    assert completed[0]["decision_step"]["id"] == "agentic:run-lifecycle:run"
    assert started[0]["decision_step"]["status"] == "active"
    assert completed[0]["decision_step"]["status"] == "completed"


def test_source_projection_drops_internal_vector_metadata() -> None:
    sources = _normalise_sources(
        [
            {
                "snippet": "public excerpt",
                "metadata": {
                    "document_id": "doc-1",
                    "document_filename": "BCX200.pdf",
                    "collection": "andritz-notices-techniques-spl-pilot",
                    "source_path": "/srv/private/BCX200.pdf",
                    "object_key": "internal/bucket/key",
                },
            }
        ]
    )

    assert sources[0]["document_id"] == "doc-1"
    assert sources[0]["filename"] == "BCX200.pdf"
    assert sources[0]["snippet"] == "public excerpt"
    assert "metadata" not in sources[0]
    assert "source_path" not in sources[0]
    assert "object_key" not in sources[0]


def test_skipped_node_end_closes_the_visible_decision_step() -> None:
    chunks = agentic_event_chunks(
        {
            "kind": "node_end",
            "node_id": "task.retrieve_deep",
            "status": "skipped",
            "chosen_branch": "balanced",
        },
        run_id="run-skipped",
    )

    assert len(chunks) == 1
    step = chunks[0]["decision_step"]
    assert step["id"] == "agentic:run-skipped:task.retrieve_deep"
    assert step["status"] == "completed"
    assert step["description"] == "Branche non retenue par le routeur"
    assert step["metrics"]["status"] == "skipped"


def test_create_run_snapshots_retrieval_contract_independently(db_session) -> None:
    original_contract = {
        "collection": "andritz-notices-techniques-spl-pilot",
        "fallback": {"empty_bound_collection": "abstain"},
    }
    system = _seed_agentic_system(db_session, retrieval_contract=original_contract)
    decision = ChatExecutionDecision(
        route="agentic",
        reason="test",
        mode="agentic_default",
        policy_version=1,
        executor_system=system,
        retrieval_contract=original_contract,
    )

    run = create_agentic_chat_run(
        db_session,
        decision=decision,
        workspace_id=system.workspace_id,
        workspace_slug=db_session.get(Workspace, system.workspace_id).slug,
        user_id=None,
        session_id="session-1",
        query="Resume BCX200",
        conversation_history=[],
        salient_entities={"project": "BCX200"},
        request_context={},
    )

    assert run.input_ref["retrieval_contract"] == original_contract

    # Changing the deployable System after Run creation must not rewrite what
    # this already-created Run is contractually allowed to retrieve.
    system.settings = {
        **system.settings,
        "retrieval_contract": {
            "collection": "a-different-collection",
            "fallback": {"empty_bound_collection": "classic"},
        },
    }
    db_session.commit()
    db_session.refresh(run)

    assert run.input_ref["retrieval_contract"] == original_contract
    assert run.input_ref["retrieval_contract"] is not system.settings["retrieval_contract"]
    assert run.published_flow_version_id is None
    assert run.execution_contract is None
    assert run.execution_surface is None


def test_feature_on_chat_run_freezes_published_ingress_evidence(db_session) -> None:
    original_contract = {
        "collection": "andritz-notices-techniques-spl-pilot",
        "fallback": {"empty_bound_collection": "abstain"},
    }
    system = _seed_agentic_system(db_session, retrieval_contract=original_contract)
    workspace = db_session.get(Workspace, system.workspace_id)
    workspace.settings = {
        **(workspace.settings or {}),
        "features": {
            "flow_publication_v1": True,
            "flow_v3_dag_authoritative": True,
        },
    }
    system.flow_definition = {
        "schema_version": 3,
        "io_mode": "strict",
        "variant": "chat_agentic_thinking_v1",
        "nodes": [
            {
                "id": "source.request",
                "type": "input",
                "kind": "source",
                "outputs": [
                    {"name": "query", "schema": "string", "required": True},
                    {"name": "conversation_history", "schema": "array"},
                ],
            },
            {"id": "sink.answer", "kind": "sink"},
        ],
        "edges": [
            {"from": "source.request", "to": "sink.answer", "kind": "data"}
        ],
    }
    db_session.commit()
    _draft, version = flow_publication.initialize_publication_state(
        db_session,
        system=system,
        workspace=workspace,
        actor="chat-boundary-test",
    )
    db_session.commit()
    decision = ChatExecutionDecision(
        route="agentic",
        reason="test",
        mode="agentic_default",
        policy_version=7,
        executor_system=system,
        retrieval_contract=original_contract,
    )

    run = create_agentic_chat_run(
        db_session,
        decision=decision,
        workspace_id=workspace.id,
        workspace_slug=workspace.slug,
        user_id=None,
        session_id=None,
        query="Resume BCX200",
        conversation_history=[],
        salient_entities={"project": "BCX200"},
        request_context={},
    )

    assert run.published_flow_version_id == version.id
    assert run.flow_version_id == version.id
    assert run.flow_sha256 == version.flow_sha256
    assert run.flow_snapshot == version.flow_definition
    assert run.execution_contract == version.execution_contract
    assert run.execution_surface == "published_chat"
    assert run.input_ref["execution"]["execution_surface"] == "published_chat"
    assert run.input_ref["execution"]["published_flow_version_id"] == version.id
    assert run.input_ref["_ingress"] == {
        "ingress_id": "source.request",
        "source_node_id": "source.request",
        "kind": "chat",
        "adapter": {
            "surface": "chat",
            "adapter_version": 1,
            "session_bound": False,
            "policy_version": 7,
            "policy_mode": "agentic_default",
        },
    }


def test_feature_on_chat_never_falls_back_to_mutable_legacy_snapshot(db_session) -> None:
    system = _seed_agentic_system(
        db_session,
        retrieval_contract={"collection": "andritz-notices-techniques-spl-pilot"},
    )
    workspace = db_session.get(Workspace, system.workspace_id)
    workspace.settings = {
        **(workspace.settings or {}),
        "features": {"flow_publication_v1": True},
    }
    db_session.commit()
    decision = ChatExecutionDecision(
        route="agentic",
        reason="test",
        mode="agentic_default",
        policy_version=1,
        executor_system=system,
    )
    before = db_session.query(Run).count()

    with pytest.raises(flow_ingress.FlowIngressError) as exc_info:
        create_agentic_chat_run(
            db_session,
            decision=decision,
            workspace_id=workspace.id,
            workspace_slug=workspace.slug,
            user_id=None,
            session_id=None,
            query="Resume BCX200",
            conversation_history=[],
            salient_entities=None,
            request_context={},
        )

    assert exc_info.value.code == "PUBLISHED_FLOW_VERSION_INVALID"
    assert db_session.query(Run).count() == before


def test_policy_terminal_outcome_neither_succeeds_nor_falls_back() -> None:
    outcome = AgenticChatOutcome(
        run_id="run-policy",
        status="completed",
        answer="A speculative draft",
        policy_terminal=True,
    )

    assert outcome.succeeded is False
    assert outcome.should_fallback is False


def test_load_policy_terminal_outcome_replaces_speculative_draft(db_session) -> None:
    system = _seed_agentic_system(
        db_session,
        retrieval_contract={"collection": "andritz-notices-techniques-spl-pilot"},
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=system.workspace_id,
        system_id=system.id,
        trigger="chat_agentic",
        status="completed",
        error="policy_blocked_skill:unapproved_skill",
        input_ref={
            "query": "Resume BCX200",
            "retrieval_contract": {"collection": "andritz-notices-techniques-spl-pilot"},
        },
        output_ref={
            "answer": "SPECULATIVE DRAFT THAT MUST NOT EGRESS",
            "citations": [{"title": "BCX200.pdf"}],
        },
    )
    db_session.add(run)
    db_session.commit()

    outcome = load_agentic_chat_outcome(db_session, run_id=run.id, system=system)

    assert outcome.status == "completed"
    assert outcome.policy_terminal is True
    assert outcome.succeeded is False
    assert outcome.should_fallback is False
    assert outcome.answer == "Cette réponse a été retenue par les règles de gouvernance Agentium."
    assert "SPECULATIVE" not in outcome.answer
    assert outcome.sources == []

    db_session.refresh(run)
    assert run.output_ref["answer"] == outcome.answer
    assert run.output_ref["sources"] == []


def test_retrieval_outage_is_technical_fallback_not_empty_collection(db_session) -> None:
    collection = "andritz-notices-techniques-spl-pilot"
    system = _seed_agentic_system(
        db_session,
        retrieval_contract={"collection": collection},
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=system.workspace_id,
        system_id=system.id,
        trigger="chat_agentic",
        status="completed",
        input_ref={"query": "Resume BCX200", "retrieval_contract": {"collection": collection}},
        output_ref={},
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        SkillInvocation(
            run_id=run.id,
            skill_slug="semantic_search_v1",
            status="completed",
            output_ref={
                "results": [],
                "raw_chunks_retrieved": 0,
                "collections_touched": [],
                "fallback_reason": "document_service_unavailable",
            },
        )
    )
    db_session.commit()

    outcome = load_agentic_chat_outcome(db_session, run_id=run.id, system=system)

    assert outcome.status == "failed"
    assert outcome.policy_terminal is False
    assert outcome.should_fallback is True
    assert outcome.fallback_reason == "agentic_retrieval_unavailable"


def test_resumed_hitl_replaces_placeholder_and_schedules_eval(
    db_session,
    monkeypatch,
) -> None:
    collection = "andritz-notices-techniques-spl-pilot"
    system = _seed_agentic_system(
        db_session,
        retrieval_contract={"collection": collection},
    )
    session = ChatSession(
        id=str(uuid.uuid4()),
        workspace_id=system.workspace_id,
        status="active",
    )
    run_id = str(uuid.uuid4())
    adapter_token = str(uuid.uuid4())
    placeholder = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Cette réponse nécessite une validation experte avant d’être diffusée.",
        meta_data={
            "route": "agentic_review",
            "run_id": run_id,
            "chat_adapter_token": adapter_token,
        },
    )
    run = Run(
        id=run_id,
        workspace_id=system.workspace_id,
        system_id=system.id,
        trigger="chat_agentic",
        status="completed",
        input_ref={
            "query": "Resume BCX200",
            "retrieval_contract": {"collection": collection},
            "chat_adapter": {
                "assistant_message_id": placeholder.id,
                "session_id": session.id,
                "policy_terminal": True,
                "origin": "chat_endpoint_v1",
                "token": adapter_token,
            },
        },
        output_ref={
            "answer": "BCX200 comporte la pompe P-101 [1].",
            "citations": [
                {
                    "title": "BCX200 manual",
                    "collection": collection,
                }
            ],
        },
    )
    db_session.add_all([session, placeholder, run])
    db_session.flush()
    db_session.add(
        SkillInvocation(
            run_id=run.id,
            skill_slug="semantic_search_v1",
            status="completed",
            output_ref={
                "raw_chunks_retrieved": 1,
                "collections_touched": [collection],
                "results": [
                    {
                        "content": "BCX200 P-101",
                        "metadata": {"collection": collection},
                    }
                ],
            },
        )
    )
    db_session.commit()
    scheduled: list[str] = []
    monkeypatch.setattr("app.services.evaluation.auto_eval.schedule_eval", scheduled.append)

    outcome = finalize_resumed_agentic_chat(run.id)

    assert outcome is not None and outcome.succeeded is True
    db_session.expire_all()
    refreshed_message = db_session.get(Message, placeholder.id)
    refreshed_run = db_session.get(Run, run.id)
    assert refreshed_message.content == "BCX200 comporte la pompe P-101 [1]."
    assert refreshed_message.meta_data["resumed_after_hitl"] is True
    assert refreshed_run.output_ref["resumed_after_hitl"] is True
    assert scheduled == [run.id]

    assert finalize_resumed_agentic_chat(run.id) is None
    assert scheduled == [run.id]


def test_resumed_hitl_rejection_never_publishes_the_draft(
    db_session,
    monkeypatch,
) -> None:
    system = _seed_agentic_system(
        db_session,
        retrieval_contract={"collection": "andritz-notices-techniques-spl-pilot"},
    )
    run_id = str(uuid.uuid4())
    adapter_token = str(uuid.uuid4())
    session = ChatSession(
        id=str(uuid.uuid4()),
        workspace_id=system.workspace_id,
        status="active",
    )
    placeholder = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Cette réponse nécessite une validation experte avant d’être diffusée.",
        meta_data={
            "route": "agentic_review",
            "run_id": run_id,
            "chat_adapter_token": adapter_token,
        },
    )
    run = Run(
        id=run_id,
        workspace_id=system.workspace_id,
        system_id=system.id,
        trigger="chat_agentic",
        status="completed",
        checkpoints=[{"kind": "hitl_resume", "decision_status": "rejected"}],
        input_ref={
            "chat_adapter": {
                "assistant_message_id": placeholder.id,
                "session_id": session.id,
                "origin": "chat_endpoint_v1",
                "token": adapter_token,
            }
        },
        output_ref={
            "answer": "BROUILLON NON VALIDÉ : pompe confidentielle P-999 [1].",
            "sources": [{"title": "draft"}],
        },
    )
    db_session.add_all([session, placeholder, run])
    db_session.commit()
    scheduled: list[str] = []
    monkeypatch.setattr("app.services.evaluation.auto_eval.schedule_eval", scheduled.append)

    outcome = finalize_resumed_agentic_chat(run.id)

    assert outcome is not None
    assert outcome.policy_terminal is True
    assert outcome.fallback_reason == "hitl_rejected"
    assert "BROUILLON" not in outcome.answer
    db_session.expire_all()
    refreshed_message = db_session.get(Message, placeholder.id)
    refreshed_run = db_session.get(Run, run.id)
    assert refreshed_message.content == "La réponse a été rejetée lors de la validation experte."
    assert "BROUILLON" not in refreshed_run.output_ref["answer"]
    assert refreshed_run.output_ref["sources"] == []
    assert refreshed_run.output_ref["fallback_reason"] == "hitl_rejected"
    assert refreshed_run.output_ref["hitl_decision"] == "rejected"
    assert "citations" not in refreshed_run.output_ref
    assert refreshed_run.decision == "hitl_rejected"
    assert scheduled == []


def test_resumed_hitl_refuses_unproven_message_binding(db_session) -> None:
    system = _seed_agentic_system(db_session, retrieval_contract={})
    session = ChatSession(
        id=str(uuid.uuid4()),
        workspace_id=system.workspace_id,
        status="active",
    )
    victim = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Réponse légitime de la victime.",
        meta_data={"run_id": "another-run", "chat_adapter_token": "another-token"},
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=system.workspace_id,
        system_id=system.id,
        trigger="chat_agentic",
        status="completed",
        input_ref={
            "chat_adapter": {
                "assistant_message_id": victim.id,
                "session_id": session.id,
                "origin": "chat_endpoint_v1",
                "token": "forged-token",
            }
        },
        output_ref={"answer": "Contenu attaquant"},
    )
    db_session.add_all([session, victim, run])
    db_session.commit()

    outcome = finalize_resumed_agentic_chat(run.id)

    assert outcome is not None
    assert outcome.fallback_reason == "chat_adapter_provenance_invalid"
    db_session.expire_all()
    assert db_session.get(Message, victim.id).content == "Réponse légitime de la victime."
