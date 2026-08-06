"""Tests for the Phase 3 event-trigger service (``run_engine.triggers``).

Sub-lot A (dry-run plumbing): registry build, governance allowlist (the ADR
invariant), flag gating, dry-run journaling and idempotence. Sub-lot B (live
execution) tests live in ``test_run_engine_triggers_live.py``.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.config import settings
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import triggers


# ---------------------------------------------------------------------------
# Flow fixtures
# ---------------------------------------------------------------------------
def _sftp_analysis_flow() -> dict:
    """SFTP trigger feeding an analysis-only run (governance-eligible)."""
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.sftp", "kind": "source", "type": "source.sftp_arrival"},
            {"id": "t.analyze", "kind": "task", "config": {"skill_slug": "semantic_search_v1"}},
            {"id": "snk", "kind": "sink"},
        ],
        "edges": [
            {"from": "src.sftp", "to": "t.analyze", "kind": "control"},
            {"from": "t.analyze", "to": "snk", "kind": "data"},
        ],
    }


def _sftp_ingestion_flow() -> dict:
    """SFTP trigger feeding an INGESTION node — must be rejected by governance."""
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.sftp", "kind": "source", "type": "source.sftp_arrival"},
            {
                "id": "t.ingest",
                "kind": "task",
                "config": {"skill_slug": "document_ingest_index", "effect": "ingestion"},
            },
        ],
        "edges": [{"from": "src.sftp", "to": "t.ingest", "kind": "control"}],
    }


def _deposit_analysis_flow() -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.dep", "kind": "source", "type": "source.deposit_promoted"},
            {"id": "t.analyze", "kind": "task", "config": {"skill_slug": "response_eval_v1"}},
            {"id": "snk", "kind": "sink"},
        ],
        "edges": [
            {"from": "src.dep", "to": "t.analyze", "kind": "control"},
            {"from": "t.analyze", "to": "snk", "kind": "data"},
        ],
    }


def _no_trigger_flow() -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.chat", "kind": "source", "type": "input"},
            {"id": "t.answer", "kind": "task", "config": {"skill_slug": "llm_rag_answer_v1"}},
        ],
        "edges": [{"from": "src.chat", "to": "t.answer", "kind": "control"}],
    }


def _make_system(db, *, workspace_id: str, flow: dict, status: str = "active") -> System:
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Trigger Test System",
        objective="test",
        flow_definition=flow,
        status=status,
    )
    db.add(system)
    db.commit()
    return system


def _make_workspace(db) -> Workspace:
    ws = Workspace(id=str(uuid.uuid4()), name="WS", slug=f"ws-{uuid.uuid4().hex[:6]}", settings={})
    db.add(ws)
    db.commit()
    return ws


@pytest.fixture()
def triggers_on(monkeypatch):
    monkeypatch.setattr(settings, "enable_event_triggers", True)
    yield


@pytest.fixture()
def triggers_off(monkeypatch):
    monkeypatch.setattr(settings, "enable_event_triggers", False)
    yield


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def test_registry_maps_trigger_systems(db_session):
    ws = _make_workspace(db_session)
    sftp_sys = _make_system(db_session, workspace_id=ws.id, flow=_sftp_analysis_flow())
    dep_sys = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    _make_system(db_session, workspace_id=ws.id, flow=_no_trigger_flow())

    registry = triggers.build_registry(db_session, workspace_id=ws.id)

    assert registry[(triggers.EVENT_SFTP_FILE_ARRIVED, ws.id)] == [sftp_sys.id]
    assert registry[(triggers.EVENT_DEPOSIT_PROMOTED, ws.id)] == [dep_sys.id]


def test_registry_excludes_flows_without_triggers_and_inactive(db_session):
    ws = _make_workspace(db_session)
    _make_system(db_session, workspace_id=ws.id, flow=_no_trigger_flow())
    _make_system(db_session, workspace_id=ws.id, flow=_sftp_analysis_flow(), status="draft")

    registry = triggers.build_registry(db_session, workspace_id=ws.id)

    assert registry == {}


# ---------------------------------------------------------------------------
# Governance allowlist (ADR invariant)
# ---------------------------------------------------------------------------
def test_governance_allows_sftp_analysis():
    verdict = triggers.evaluate_governance(triggers.EVENT_SFTP_FILE_ARRIVED, _sftp_analysis_flow())
    assert verdict.eligible is True


def test_governance_rejects_sftp_ingestion():
    verdict = triggers.evaluate_governance(triggers.EVENT_SFTP_FILE_ARRIVED, _sftp_ingestion_flow())
    assert verdict.eligible is False
    assert verdict.reason.startswith("effect_not_permitted:ingestion")


def test_governance_rejects_when_no_trigger_node():
    verdict = triggers.evaluate_governance(triggers.EVENT_SFTP_FILE_ARRIVED, _no_trigger_flow())
    assert verdict.eligible is False
    assert verdict.reason == "no_active_trigger_node"


# ---------------------------------------------------------------------------
# Dry-run emission (flag ON) / no-op (flag OFF)
# ---------------------------------------------------------------------------
def test_emit_deposit_promoted_simulates_when_flag_on(db_session, triggers_on):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        ws.id,
        {"collection_slug": "c1", "file_id": "f1"},
        db=db_session,
    )

    assert len(results) == 1
    assert results[0]["status"] == "simulated"
    run = db_session.query(Run).filter(Run.system_id == system.id).one()
    assert run.status == "simulated"
    assert run.trigger == "webhook"
    meta = (run.input_ref or {})["_event_trigger"]
    assert meta["simulated"] is True
    assert meta["event_kind"] == triggers.EVENT_DEPOSIT_PROMOTED
    # The dry-run is visibly marked in the Runs surface.
    assert any(cp.get("kind") == "trigger_simulated" for cp in (run.checkpoints or []))


def test_emit_is_noop_when_flag_off(db_session, triggers_off):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        ws.id,
        {"collection_slug": "c1", "file_id": "f1"},
        db=db_session,
    )

    assert results == []
    assert db_session.query(Run).filter(Run.system_id == system.id).count() == 0


def test_emit_sftp_ingestion_downstream_is_rejected(db_session, triggers_on):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_sftp_ingestion_flow())

    results = triggers.emit_event(
        triggers.EVENT_SFTP_FILE_ARRIVED,
        ws.id,
        {"job_id": "j1"},
        db=db_session,
    )

    assert len(results) == 1
    assert results[0]["status"] == "rejected"
    assert results[0]["reason"].startswith("effect_not_permitted:ingestion")
    assert db_session.query(Run).filter(Run.system_id == system.id).count() == 0


def test_dedup_suppresses_duplicate(db_session, triggers_on):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    payload = {"collection_slug": "c1", "file_id": "f1"}

    first = triggers.emit_event(triggers.EVENT_DEPOSIT_PROMOTED, ws.id, payload, db=db_session)
    second = triggers.emit_event(triggers.EVENT_DEPOSIT_PROMOTED, ws.id, payload, db=db_session)

    assert first[0]["status"] == "simulated"
    assert second[0]["status"] == "duplicate"
    assert second[0]["run_id"] == first[0]["run_id"]
    assert db_session.query(Run).filter(Run.system_id == system.id).count() == 1


def test_atomic_dedup_claim_recovers_the_existing_simulated_run(db_session, triggers_on):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    payload = {"collection_slug": "c1", "file_id": "same-delivery"}
    dedup_key = triggers._dedup_key(
        system.id,
        triggers.EVENT_DEPOSIT_PROMOTED,
        payload,
    )

    first, first_created = triggers._journal_simulated_run(
        db_session,
        system,
        triggers.EVENT_DEPOSIT_PROMOTED,
        ws.id,
        payload,
        dedup_key,
        owns_session=False,
    )
    recovered, second_created = triggers._journal_simulated_run(
        db_session,
        system,
        triggers.EVENT_DEPOSIT_PROMOTED,
        ws.id,
        payload,
        dedup_key,
        owns_session=False,
    )

    assert first_created is True
    assert second_created is False
    assert recovered.id == first.id
    assert first.trigger_dedup_key == dedup_key
    assert db_session.query(Run).filter(Run.trigger_dedup_key == dedup_key).count() == 1


def test_emit_no_target_returns_marker(db_session, triggers_on):
    ws = _make_workspace(db_session)
    # No system with a matching trigger node.
    _make_system(db_session, workspace_id=ws.id, flow=_no_trigger_flow())

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED, ws.id, {"file_id": "f1"}, db=db_session
    )

    assert results == [
        {
            "status": "no_target",
            "event_kind": triggers.EVENT_DEPOSIT_PROMOTED,
            "workspace_id": ws.id,
        }
    ]


def test_deposit_promoted_hook_wraps_emit(db_session, triggers_on):
    """The secure_deposit hook wrapper forwards to ``emit_event``."""
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())

    results = triggers.emit_deposit_promoted(
        db_session, workspace_id=ws.id, collection_slug="c1", file_ids=["f1"]
    )

    assert results[0]["status"] == "simulated"
    assert db_session.query(Run).filter(Run.system_id == system.id).count() == 1
