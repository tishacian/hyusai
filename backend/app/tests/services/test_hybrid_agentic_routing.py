"""Unit tests for the Phase 3 hybrid agentic routing gate.

Covers the production ``/chat`` routing decision added in
``app.api.v1.endpoints.chat``:

* ``_should_route_agentic`` — the flag+profile gate predicate.
* ``_maybe_agentic_chat_completion`` — the fail-open dispatch that walks the
  seeded agentic DAG System and degrades to the classic orchestrator on any
  failure (missing System, DAG error, non-completed run, empty answer).

Everything external is mocked: the System lookup, ``execute_run_dag`` and the
SQLAlchemy session. No live services, no orchestrator, no DB rows.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.v1.endpoints import chat


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
def _workspace():
    return SimpleNamespace(id="ws-1", slug="andritz")


def _request(profile: str, *, session_id=None):
    return chat.ChatRequest(
        query="Compare le rendement de l'ACJ200 et de l'AKK200",
        answer_profile=profile,
        answer_profile_decision={"profile": profile, "reason": f"{profile}_query"},
        session_id=session_id,
    )


def _fake_db_returning(fresh):
    """MagicMock session whose ``query(...).filter(...).first()`` yields ``fresh``."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = fresh
    return db


def _install_system(monkeypatch, system):
    monkeypatch.setattr(chat, "_lookup_agentic_chat_system", lambda db, ws: system)


def _install_execute_run_dag(monkeypatch, *, side_effect=None, result=None):
    async def _fake(run_id):
        if side_effect is not None:
            raise side_effect
        return result or {"status": "completed"}

    monkeypatch.setattr("app.services.run_engine.dag.execute_run_dag", _fake)


# ---------------------------------------------------------------------------
# _should_route_agentic — the gate predicate
# ---------------------------------------------------------------------------
def test_gate_off_by_default_keeps_classic(monkeypatch):
    monkeypatch.setattr(chat.settings, "enable_agentic_chat", False)
    for profile in ("transversal_inventory", "comparison", "equipment_detail",
                    "table_extract", "multi_hop", "precise_fact", None):
        assert chat._should_route_agentic(profile) is False, profile


def test_gate_on_selects_only_niche_profiles(monkeypatch):
    monkeypatch.setattr(chat.settings, "enable_agentic_chat", True)
    # Niche intents dispatch to the agentic lane.
    for profile in ("transversal_inventory", "comparison", "equipment_detail",
                    "table_extract", "multi_hop"):
        assert chat._should_route_agentic(profile) is True, profile
    # Everything else stays classic even with the flag on.
    for profile in ("precise_fact", "project_summary", "insufficient_context", None):
        assert chat._should_route_agentic(profile) is False, profile


# ---------------------------------------------------------------------------
# _maybe_agentic_chat_completion — dispatch + fail-open fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_returns_agentic_payload_on_completed_run(monkeypatch):
    system = SimpleNamespace(id="sys-agentic", status="active",
                             flow_definition={"variant": chat.AGENTIC_CHAT_VARIANT})
    _install_system(monkeypatch, system)
    _install_execute_run_dag(monkeypatch)
    fresh = SimpleNamespace(
        status="completed",
        output_ref={"answer": "L'ACJ200 rend plus que l'AKK200 [1].",
                    "citations": [{"id": 1, "title": "Manuel ACJ200"}]},
    )
    db = _fake_db_returning(fresh)

    payload = await chat._maybe_agentic_chat_completion(
        db, workspace=_workspace(), request=_request("comparison"),
        query="Compare le rendement de l'ACJ200 et de l'AKK200",
    )

    assert payload is not None
    assert payload["route"] == "agentic"
    assert payload["status"] == "completed"
    assert payload["content"].startswith("L'ACJ200 rend plus")
    assert payload["sources"] == [{"id": 1, "title": "Manuel ACJ200"}]
    assert payload["answer_profile"] == "comparison"
    # Shape parity: the classic completion keys are all present (as None here).
    for key in ("run_id", "reasoning_trace", "retrieval_profile", "deep_job"):
        assert key in payload


@pytest.mark.asyncio
async def test_dispatch_falls_back_when_system_absent(monkeypatch):
    _install_system(monkeypatch, None)
    # execute_run_dag must never be reached — make it explode if it is.
    _install_execute_run_dag(monkeypatch, side_effect=AssertionError("must not run"))
    db = MagicMock()

    payload = await chat._maybe_agentic_chat_completion(
        db, workspace=_workspace(), request=_request("comparison"),
        query="Compare A et B",
    )

    assert payload is None  # -> caller uses the classic orchestrator


@pytest.mark.asyncio
async def test_dispatch_falls_back_when_execute_run_dag_raises(monkeypatch):
    system = SimpleNamespace(id="sys-agentic", status="active",
                             flow_definition={"variant": chat.AGENTIC_CHAT_VARIANT})
    _install_system(monkeypatch, system)
    _install_execute_run_dag(monkeypatch, side_effect=RuntimeError("dag boom"))
    db = MagicMock()

    payload = await chat._maybe_agentic_chat_completion(
        db, workspace=_workspace(), request=_request("multi_hop"),
        query="Pour les moteurs qui dépassent 500 kW, combien...",
    )

    assert payload is None


@pytest.mark.asyncio
async def test_dispatch_falls_back_when_run_not_completed(monkeypatch):
    system = SimpleNamespace(id="sys-agentic", status="active",
                             flow_definition={"variant": chat.AGENTIC_CHAT_VARIANT})
    _install_system(monkeypatch, system)
    _install_execute_run_dag(monkeypatch)
    fresh = SimpleNamespace(status="failed", output_ref={"answer": "unused"})
    db = _fake_db_returning(fresh)

    payload = await chat._maybe_agentic_chat_completion(
        db, workspace=_workspace(), request=_request("comparison"),
        query="Compare A et B",
    )

    assert payload is None


@pytest.mark.asyncio
async def test_dispatch_falls_back_when_answer_empty(monkeypatch):
    system = SimpleNamespace(id="sys-agentic", status="active",
                             flow_definition={"variant": chat.AGENTIC_CHAT_VARIANT})
    _install_system(monkeypatch, system)
    _install_execute_run_dag(monkeypatch)
    fresh = SimpleNamespace(status="completed", output_ref={"answer": "   "})
    db = _fake_db_returning(fresh)

    payload = await chat._maybe_agentic_chat_completion(
        db, workspace=_workspace(), request=_request("comparison"),
        query="Compare A et B",
    )

    assert payload is None


@pytest.mark.asyncio
async def test_dispatch_reads_clarify_and_oos_sinks(monkeypatch):
    system = SimpleNamespace(id="sys-agentic", status="active",
                             flow_definition={"variant": chat.AGENTIC_CHAT_VARIANT})
    _install_system(monkeypatch, system)
    _install_execute_run_dag(monkeypatch)

    for output_ref, expected in (
        ({"clarifying_question": "Quel projet précisément ?"}, "Quel projet précisément ?"),
        ({"reason": "Hors périmètre Andritz."}, "Hors périmètre Andritz."),
    ):
        fresh = SimpleNamespace(status="completed", output_ref=output_ref)
        db = _fake_db_returning(fresh)
        payload = await chat._maybe_agentic_chat_completion(
            db, workspace=_workspace(), request=_request("equipment_detail"),
            query="…",
        )
        assert payload is not None
        assert payload["content"] == expected
