"""Tests for ``services.runs.replay_service`` — E1.5.2.

Exercises the deterministic helpers (``_build_request_dict``,
``_is_replayable_chat_run``) and ``replay_run_async`` with a stubbed
orchestrator. The orchestrator round-trip (real LLM call) lives in the
VM smoke test ``/tmp/e152_smoke.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, List
from uuid import uuid4

import pytest

from app.models.audit import AuditLog
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.runs import replay_service


def _make_parent(
    db_session,
    *,
    workspace_id: str = "ws-1",
    trigger: str = "chat",
    system_id: str | None = None,
    flow_snapshot=None,
    input_ref=None,
    status: str = "completed",
) -> Run:
    if input_ref is None:
        input_ref = {"query": "what is the policy on X?"}
    r = Run(
        id=str(uuid4()),
        workspace_id=workspace_id,
        system_id=system_id,
        status=status,
        trigger=trigger,
        input_ref=input_ref,
        output_ref={"response": "Policy says Y", "sources": []},
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        flow_snapshot=flow_snapshot,
    )
    db_session.add(r)
    db_session.commit()
    return r


# ---------------------------------------------------------------------------
# _build_request_dict
# ---------------------------------------------------------------------------


def test_build_request_dict_uses_parent_query_when_no_override(db_session) -> None:
    parent = _make_parent(db_session)
    req = replay_service._build_request_dict(
        parent=parent,
        workspace_slug="ws-1-slug",
        workspace_id="ws-1",
        overrides={},
    )
    assert req["query"] == "what is the policy on X?"
    assert req["workspace_id"] == "ws-1"
    assert req["stream"] is False


def test_build_request_dict_overrides_query(db_session) -> None:
    parent = _make_parent(db_session)
    req = replay_service._build_request_dict(
        parent=parent,
        workspace_slug="ws-1-slug",
        workspace_id="ws-1",
        overrides={"query": "rephrased question"},
    )
    assert req["query"] == "rephrased question"


def test_build_request_dict_promotes_model_to_agent_preferences(db_session) -> None:
    parent = _make_parent(db_session)
    req = replay_service._build_request_dict(
        parent=parent,
        workspace_slug="ws-1-slug",
        workspace_id="ws-1",
        overrides={"model": "gpt-5", "provider": "azure-openai"},
    )
    prefs = req["agent_preferences"]["model_preferences"]
    assert prefs["model"] == "gpt-5"
    assert prefs["provider"] == "azure-openai"


def test_build_request_dict_forwards_unknown_keys_to_custom_overrides(db_session) -> None:
    parent = _make_parent(db_session)
    req = replay_service._build_request_dict(
        parent=parent,
        workspace_slug="ws-1-slug",
        workspace_id="ws-1",
        overrides={"future_knob": True, "pipeline_variant": "exp-3"},
    )
    extras = req["agent_preferences"]["custom_overrides"]
    assert extras == {"future_knob": True, "pipeline_variant": "exp-3"}


def test_build_request_dict_promotes_retrieval_policy_fields(db_session) -> None:
    parent = _make_parent(db_session)
    req = replay_service._build_request_dict(
        parent=parent,
        workspace_slug="ws-1-slug",
        workspace_id="ws-1",
        overrides={
            "latency_profile": "balanced",
            "candidate_pool_k": 80,
            "synthesis_k": 24,
            "source_display_k": 8,
            "retrieval_filters": {"project_code": "ACJ100"},
            "knowledge_scope": "andritz_spl",
            "context_collection": "andritz-notices-techniques-spl-pilot",
            "future_knob": True,
        },
    )

    assert req["latency_profile"] == "balanced"
    assert req["candidate_pool_k"] == 80
    assert req["synthesis_k"] == 24
    assert req["source_display_k"] == 8
    assert req["retrieval_filters"] == {"project_code": "ACJ100"}
    assert req["knowledge_scope"] == "andritz_spl"
    assert req["context_collection"] == "andritz-notices-techniques-spl-pilot"
    assert req["agent_preferences"]["custom_overrides"] == {"future_knob": True}


def test_build_request_dict_carries_system_id(db_session) -> None:
    parent = _make_parent(db_session, system_id="sys-abc")
    req = replay_service._build_request_dict(
        parent=parent,
        workspace_slug="ws-1-slug",
        workspace_id="ws-1",
        overrides={},
    )
    assert req["agent_id"] == "sys-abc"


def test_build_request_dict_rejects_empty_parent_input(db_session) -> None:
    parent = _make_parent(db_session, input_ref={})
    with pytest.raises(replay_service.ReplayError):
        replay_service._build_request_dict(
            parent=parent,
            workspace_slug="ws-1-slug",
            workspace_id="ws-1",
            overrides={},
        )


# ---------------------------------------------------------------------------
# _is_replayable_chat_run
# ---------------------------------------------------------------------------


def test_chat_trigger_is_replayable(db_session) -> None:
    p = _make_parent(db_session, trigger="chat")
    assert replay_service._is_replayable_chat_run(p) is True


def test_replay_of_replay_is_replayable(db_session) -> None:
    p = _make_parent(db_session, trigger="replay")
    assert replay_service._is_replayable_chat_run(p) is True


def test_engine_run_with_flow_snapshot_is_not_replayable(db_session) -> None:
    p = _make_parent(
        db_session,
        trigger="manual",
        system_id="sys-x",
        flow_snapshot={"nodes": [{"id": "a"}], "edges": []},
    )
    assert replay_service._is_replayable_chat_run(p) is False


def test_workspace_chat_with_no_system_is_replayable(db_session) -> None:
    p = _make_parent(db_session, trigger="manual", system_id=None)
    assert replay_service._is_replayable_chat_run(p) is True


def test_run_without_query_is_not_replayable(db_session) -> None:
    p = _make_parent(db_session, input_ref={})
    assert replay_service._is_replayable_chat_run(p) is False


# ---------------------------------------------------------------------------
# replay_run_async (with stubbed orchestrator)
# ---------------------------------------------------------------------------


class _StubOrchestrator:
    def __init__(self, chunks: List[Dict[str, Any]]) -> None:
        self._chunks = chunks
        self.last_request: Dict[str, Any] | None = None

    async def process_request(self, req: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        self.last_request = req
        for c in self._chunks:
            yield c


@pytest.fixture()
def stub_orchestrator(monkeypatch):
    """Stub ``app.api.v1.endpoints.agents.get_orchestrator`` so the service
    doesn't hit any real model client during unit tests."""
    stub = _StubOrchestrator(
        [
            {"chunk_type": "text", "content": "replay reply"},
            {"chunk_type": "sources", "sources": [{"url": "u"}]},
            {"chunk_type": "text", "content": " continues", "is_final": True},
        ]
    )
    # The service does a lazy import of get_orchestrator inside the
    # function body, so we patch the source module.
    import app.api.v1.endpoints.agents as agents_mod

    monkeypatch.setattr(agents_mod, "get_orchestrator", lambda: stub)
    return stub


@pytest.mark.asyncio
async def test_replay_persists_new_run_and_audits(
    db_session, stub_orchestrator, monkeypatch
) -> None:
    # Suppress fire-and-forget eval scheduling — we don't want to start
    # an asyncio judge thread in unit tests.
    monkeypatch.setattr(
        "app.services.runs.replay_service.schedule_eval", lambda _id: None
    )

    parent = _make_parent(db_session, trigger="chat")
    new_run, text = await replay_service.replay_run_async(
        db=db_session,
        parent=parent,
        workspace_slug="ws-1-slug",
        overrides={"query": "rephrased", "model": "gpt-5"},
        actor="alice",
        source_decision_id="dec-1",
    )

    assert new_run.parent_run_id == parent.id
    assert new_run.trigger == "replay"
    assert new_run.status == "completed"
    assert new_run.replay_overrides == {"query": "rephrased", "model": "gpt-5"}
    assert "replay reply" in text
    # Orchestrator received the override-patched request.
    assert stub_orchestrator.last_request["query"] == "rephrased"
    assert (
        stub_orchestrator.last_request["agent_preferences"]["model_preferences"]["model"]
        == "gpt-5"
    )

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "run.replayed")
        .first()
    )
    assert audit is not None
    assert audit.details["parent_run_id"] == parent.id
    assert audit.details["new_run_id"] == new_run.id
    assert audit.details["source_decision_id"] == "dec-1"


@pytest.mark.asyncio
async def test_terminal_replay_copies_only_validated_parent_execution_evidence(
    db_session, stub_orchestrator, monkeypatch
) -> None:
    monkeypatch.setattr(replay_service.settings, "agentium_image_revision", "e" * 40)
    monkeypatch.setattr(
        "app.services.runs.replay_service.schedule_eval", lambda _id: None
    )
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"replay-evidence-{uuid4().hex[:8]}",
        name="Replay evidence",
    )
    foreign_workspace = Workspace(
        id=str(uuid4()),
        slug=f"foreign-replay-{uuid4().hex[:8]}",
        name="Foreign replay evidence",
    )
    flow = {"nodes": [{"id": "chat"}], "edges": []}
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="System-scoped chat",
        objective="test",
        flow_definition=flow,
    )
    parent_started_at = datetime.utcnow() - timedelta(minutes=2)
    version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=1,
        flow_definition=flow,
        created_at=parent_started_at - timedelta(seconds=1),
        created_by="test",
    )
    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        trigger="chat",
        input_ref={
            "query": "what changed?",
            "execution": {
                "snapshot_at": parent_started_at.isoformat(timespec="microseconds")
                + "Z"
            },
        },
        output_ref={"response": "before"},
        flow_snapshot=flow,
        flow_version_id=version.id,
        started_at=parent_started_at,
        completed_at=parent_started_at + timedelta(seconds=1),
    )
    db_session.add_all([workspace, foreign_workspace, system, version, parent])
    db_session.commit()

    replay, _ = await replay_service.replay_run_async(
        db=db_session,
        parent=parent,
        workspace_slug=workspace.slug,
        overrides={},
    )

    assert replay.flow_snapshot == flow
    assert replay.flow_snapshot is not parent.flow_snapshot
    assert replay.flow_version_id == version.id
    assert replay.input_ref["execution"]["snapshot_at"].endswith("Z")
    assert replay.input_ref["execution"]["runtime_revision"] == "e" * 40

    foreign_version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=foreign_workspace.id,
        version_number=2,
        flow_definition=flow,
        created_at=parent_started_at - timedelta(seconds=1),
        created_by="test",
    )
    db_session.add(foreign_version)
    db_session.flush()
    parent.flow_version_id = foreign_version.id
    db_session.commit()

    unbound_replay, _ = await replay_service.replay_run_async(
        db=db_session,
        parent=parent,
        workspace_slug=workspace.slug,
        overrides={},
    )

    assert unbound_replay.flow_snapshot == flow
    assert unbound_replay.flow_version_id is None


@pytest.mark.asyncio
async def test_replay_clamps_untrusted_retrieval_budget(
    db_session, stub_orchestrator, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.services.runs.replay_service.schedule_eval", lambda _id: None
    )

    parent = _make_parent(db_session, trigger="chat")
    await replay_service.replay_run_async(
        db=db_session,
        parent=parent,
        workspace_slug="ws-1-slug",
        overrides={
            "query": "audit SPL",
            "rag_pipeline_mode": "chah",
            "top_k": 999,
            "candidate_pool_k": 999,
            "synthesis_k": 999,
            "source_display_k": 999,
        },
    )

    assert stub_orchestrator.last_request["latency_profile"] == "fast"
    assert stub_orchestrator.last_request["top_k"] == 8
    assert stub_orchestrator.last_request["candidate_pool_k"] == 20
    assert stub_orchestrator.last_request["synthesis_k"] == 12
    assert stub_orchestrator.last_request["source_display_k"] == 8
    assert stub_orchestrator.last_request["latency_budget"]["candidate_pool_k"] == 20


@pytest.mark.asyncio
async def test_replay_persists_retrieval_metadata(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.runs.replay_service.schedule_eval", lambda _id: None
    )
    stub = _StubOrchestrator(
        [
            {
                "chunk_type": "decision_step",
                "decision_step": {"id": "retrieve-1", "type": "retrieve", "status": "completed"},
            },
            {
                "chunk_type": "retrieval",
                "details": {
                    "dense_policy": "fast_scoped_dense",
                    "fallback_reason": "sparse_unavailable",
                    "retrieval_scope": {"filters": {"project_code": "ACJ100"}},
                    "scope_confidence": 0.82,
                    "latency_budget": {"profile": "fast", "candidate_pool_k": 20},
                },
                "rag_context": {"chunks": ["evidence"], "scores": [0.8], "metadatas": []},
            },
            {
                "chunk_type": "text",
                "content": "answer",
                "sources": [{"title": "Manual"}],
                "reasoning_trace": [{"step": "retrieve"}],
                "is_final": True,
            },
        ]
    )
    import app.api.v1.endpoints.agents as agents_mod

    monkeypatch.setattr(agents_mod, "get_orchestrator", lambda: stub)

    parent = _make_parent(db_session, trigger="chat")
    new_run, _ = await replay_service.replay_run_async(
        db=db_session,
        parent=parent,
        workspace_slug="ws-1-slug",
        overrides={"query": "replay SPL"},
    )

    assert new_run.output_ref["sources"] == [{"title": "Manual"}]
    assert new_run.output_ref["reasoning_trace"] == [{"step": "retrieve"}]
    assert new_run.output_ref["decision_steps"][0]["id"] == "retrieve-1"
    assert new_run.output_ref["retrieval_metrics"]["dense_policy"] == "fast_scoped_dense"
    assert new_run.output_ref["dense_policy"] == "fast_scoped_dense"
    assert new_run.output_ref["fallback_reason"] == "sparse_unavailable"
    assert new_run.output_ref["retrieval_scope"] == {"filters": {"project_code": "ACJ100"}}
    assert new_run.output_ref["latency_budget"] == {"profile": "fast", "candidate_pool_k": 20}
    assert new_run.output_ref["rag_context"]["chunks"] == ["evidence"]


@pytest.mark.asyncio
async def test_replay_marks_run_failed_on_orchestrator_exception(
    db_session, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.services.runs.replay_service.schedule_eval", lambda _id: None
    )

    class _Boom:
        async def process_request(self, req):  # noqa: ARG002
            if False:
                yield {}
            raise RuntimeError("model refused")

    import app.api.v1.endpoints.agents as agents_mod

    monkeypatch.setattr(agents_mod, "get_orchestrator", lambda: _Boom())

    parent = _make_parent(db_session, trigger="chat")
    new_run, text = await replay_service.replay_run_async(
        db=db_session,
        parent=parent,
        workspace_slug="ws-1-slug",
        overrides={},
    )
    assert new_run.status == "failed"
    assert new_run.error and "model refused" in new_run.error
    assert text == ""


@pytest.mark.asyncio
async def test_replay_rejects_pending_parent(db_session) -> None:
    parent = _make_parent(db_session, status="pending")
    with pytest.raises(replay_service.ReplayError):
        await replay_service.replay_run_async(
            db=db_session,
            parent=parent,
            workspace_slug="ws-1-slug",
            overrides={},
        )


@pytest.mark.asyncio
async def test_replay_rejects_engine_run_with_flow_snapshot(db_session) -> None:
    parent = _make_parent(
        db_session,
        trigger="manual",
        system_id="sys-x",
        flow_snapshot={"nodes": [{"id": "a"}], "edges": []},
    )
    with pytest.raises(replay_service.ReplayError):
        await replay_service.replay_run_async(
            db=db_session,
            parent=parent,
            workspace_slug="ws-1-slug",
            overrides={},
        )
