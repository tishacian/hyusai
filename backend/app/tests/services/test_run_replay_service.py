"""Tests for ``services.runs.replay_service`` — E1.5.2.

Exercises the deterministic helpers (``_build_request_dict``,
``_is_replayable_chat_run``) and ``replay_run_async`` with a stubbed
orchestrator. The orchestrator round-trip (real LLM call) lives in the
VM smoke test ``/tmp/e152_smoke.py``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator, Dict, List
from uuid import uuid4

import pytest

from app.models.audit import AuditLog
from app.models.run import Run
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
