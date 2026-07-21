from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.models.decision import Decision
from app.models.run import Run
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import hitl_watchdog


def _delegated_hitl(db, *, decision_status: str = "proposed", approved_at=None):
    workspace = Workspace(id=str(uuid4()), name="Watchdog", slug=f"watchdog-{uuid4()}")
    parent_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Parent",
        objective="Watchdog parent",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
        settings={"features": {"subflow_celery": True}},
    )
    child_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Child",
        objective="Watchdog child",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
        settings={},
    )
    db.add(workspace)
    db.flush()
    db.add_all([parent_system, child_system])
    db.flush()

    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=parent_system.id,
        status="waiting_subflows",
        input_ref={"query": "parent"},
        checkpoints=[{"kind": "subflow_wait", "state": {}}],
    )
    db.add(parent)
    db.flush()
    deadline = datetime.utcnow() - timedelta(seconds=5)
    decision_id = str(uuid4())
    delegation_key = "d" * 64
    child = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=child_system.id,
        parent_run_id=parent.id,
        status="hitl_pending",
        input_ref={
            "_delegation": {
                "parent_run_id": parent.id,
                "execution_plane": "celery",
                "deadline_at": deadline.isoformat(),
            }
        },
        output_ref={"must": "not publish"},
        delegation_key=delegation_key,
        delegation_node_id="delegate",
        delegation_branch="legal",
        delegation_deadline_at=deadline,
        checkpoints=[
            {
                "kind": "hitl_pause",
                "decision_id": decision_id,
                "node_id": "approval",
                "state": {},
            }
        ],
    )
    parent.waiting_subflows = {
        "_meta": {
            "strategy": "all",
            "state": "waiting",
            "execution_plane": "celery",
            "wave_id": 7,
        },
        delegation_key: {
            "child_run_id": child.id,
            "node_id": "delegate",
            "branch": "legal",
            "status": "hitl_pending",
            "deadline_at": deadline.isoformat(),
            "wave_id": 7,
        },
    }
    decision = Decision(
        id=decision_id,
        workspace_id=workspace.id,
        scope="run",
        target_id=child.id,
        kind="hitl",
        status=decision_status,
        title="Approve child",
        rationale={"prompt": "Approve?"},
        approved_at=approved_at,
    )
    db.add_all([child, decision])
    db.commit()
    return parent, child, decision, deadline


def test_expired_proposed_hitl_fails_child_and_wakes_parent(db_session, monkeypatch):
    parent, child, decision, deadline = _delegated_hitl(db_session)
    enqueued = []
    monkeypatch.setattr(
        hitl_watchdog,
        "enqueue_dispatch",
        lambda _db, **kwargs: enqueued.append(kwargs),
    )
    now = deadline + timedelta(seconds=10)

    assert (
        hitl_watchdog._reconcile_candidate(db_session, run_id=child.id, now=now)
        == "expired"
    )
    db_session.expire_all()
    persisted_child = db_session.query(Run).filter(Run.id == child.id).one()
    persisted_decision = db_session.query(Decision).filter(Decision.id == decision.id).one()

    assert persisted_child.status == "failed"
    assert persisted_child.error == hitl_watchdog.WATCHDOG_ERROR
    assert persisted_child.output_ref == {}
    assert [cp["kind"] for cp in persisted_child.checkpoints[-2:]] == [
        "hitl_timeout",
        "run_end",
    ]
    assert persisted_decision.status == "rejected"
    assert persisted_decision.approved_by == hitl_watchdog.WATCHDOG_ACTOR
    assert persisted_decision.rationale["hitl_timeout"]["deadline_at"] == deadline.isoformat()
    assert enqueued == [
        {
            "event_type": hitl_watchdog.SUBFLOW_PARENT_RESUME,
            "workspace_id": persisted_child.workspace_id,
            "run_id": parent.id,
            "source_id": child.id,
            "wave_id": 7,
        }
    ]

    assert (
        hitl_watchdog._reconcile_candidate(db_session, run_id=child.id, now=now)
        == "terminal"
    )
    assert len(enqueued) == 1


def test_resolution_recorded_before_deadline_is_resumed_not_expired(db_session, monkeypatch):
    approved_at = datetime.utcnow() - timedelta(seconds=10)
    parent, child, decision, deadline = _delegated_hitl(
        db_session,
        decision_status="accepted",
        approved_at=approved_at,
    )
    # Make the approval provably earlier than the immutable deadline.
    decision.approved_at = deadline - timedelta(seconds=1)
    db_session.commit()
    enqueued = []
    monkeypatch.setattr(
        hitl_watchdog,
        "enqueue_dispatch",
        lambda _db, **kwargs: enqueued.append(kwargs),
    )

    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=20),
        )
        == "resume_enqueued"
    )
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == child.id).one()
    assert persisted.status == "hitl_pending"
    assert persisted.error is None
    assert enqueued == [
        {
            "event_type": hitl_watchdog.SUBFLOW_HITL_RESUME,
            "workspace_id": child.workspace_id,
            "run_id": child.id,
            "decision_id": decision.id,
        }
    ]
    assert db_session.query(Run).filter(Run.id == parent.id).one().status == "waiting_subflows"


def test_mismatched_parent_envelope_is_quarantined_fail_closed(db_session, monkeypatch):
    parent, child, decision, deadline = _delegated_hitl(db_session)
    waiting = dict(parent.waiting_subflows or {})
    waiting[child.delegation_key] = {
        **waiting[child.delegation_key],
        "child_run_id": str(uuid4()),
    }
    parent.waiting_subflows = waiting
    db_session.commit()
    enqueued = []
    monkeypatch.setattr(
        hitl_watchdog,
        "enqueue_dispatch",
        lambda _db, **kwargs: enqueued.append(kwargs),
    )

    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=10),
        )
        == "quarantined"
    )
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == child.id).one()
    assert persisted.status == "failed"
    assert persisted.error == hitl_watchdog.WATCHDOG_INVALID_ERROR
    assert persisted.checkpoints[-2]["kind"] == "hitl_watchdog_invalid"
    assert db_session.query(Decision).filter(Decision.id == decision.id).one().status == "rejected"
    assert enqueued == []
    assert db_session.query(Run).filter(Run.id == parent.id).one().status == "failed"


def test_missing_deadline_is_quarantined_instead_of_ignored(db_session, monkeypatch):
    _parent, child, decision, deadline = _delegated_hitl(db_session)
    child.delegation_deadline_at = None
    db_session.commit()
    enqueued = []
    monkeypatch.setattr(
        hitl_watchdog,
        "enqueue_dispatch",
        lambda _db, **kwargs: enqueued.append(kwargs),
    )

    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=10),
        )
        == "quarantined"
    )
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == child.id).one()
    persisted_decision = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "failed"
    assert persisted.error == hitl_watchdog.WATCHDOG_INVALID_ERROR
    assert persisted.checkpoints[-2]["kind"] == "hitl_watchdog_invalid"
    assert persisted.checkpoints[-2]["reason"] == "missing_delegation_deadline"
    assert persisted_decision.status == "rejected"
    assert enqueued == [
        {
            "event_type": hitl_watchdog.SUBFLOW_PARENT_RESUME,
            "workspace_id": persisted.workspace_id,
            "run_id": _parent.id,
            "source_id": child.id,
            "wave_id": 7,
        }
    ]


def test_parent_only_celery_claim_is_quarantined_and_wakes_parent(db_session):
    parent, child, decision, deadline = _delegated_hitl(db_session)
    delegation = dict((child.input_ref or {}).get("_delegation") or {})
    delegation.pop("execution_plane")
    child.input_ref = {"_delegation": delegation}
    child.delegation_deadline_at = None
    db_session.commit()
    # The parent still claims this exact child/key in the same workspace.
    assert (
        (parent.waiting_subflows or {}).get("_meta", {}).get("execution_plane")
        == "celery"
    )
    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=10),
        )
        == "quarantined"
    )
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == child.id).one()
    persisted_decision = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "failed"
    assert persisted.error == hitl_watchdog.WATCHDOG_INVALID_ERROR
    assert persisted.checkpoints[-2]["reason"] == "missing_delegation_deadline"
    assert persisted_decision.status == "rejected"
    event = db_session.query(RunDispatchOutbox).one()
    assert (event.event_type, event.run_id, event.source_id, event.wave_id) == (
        "subflow_parent_resume",
        parent.id,
        child.id,
        7,
    )


def test_child_only_claim_terminalizes_malformed_parent_chain(db_session):
    parent, child, decision, deadline = _delegated_hitl(db_session)
    child.delegation_deadline_at = None
    parent.waiting_subflows = {}
    db_session.commit()

    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=10),
        )
        == "quarantined"
    )

    db_session.expire_all()
    child = db_session.query(Run).filter(Run.id == child.id).one()
    parent = db_session.query(Run).filter(Run.id == parent.id).one()
    decision = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert child.status == "failed"
    assert child.error == hitl_watchdog.WATCHDOG_INVALID_ERROR
    assert parent.status == "failed"
    assert parent.error == hitl_watchdog.WATCHDOG_INVALID_ERROR
    assert decision.status == "rejected"
    assert db_session.query(RunDispatchOutbox).count() == 0


def test_legacy_workspace_null_decision_is_rejected_by_quarantine(db_session):
    _parent, child, decision, deadline = _delegated_hitl(db_session)
    child.delegation_deadline_at = None
    decision.workspace_id = None
    db_session.commit()

    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=10),
        )
        == "quarantined"
    )
    db_session.expire_all()
    persisted = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "rejected"


def test_unclaimed_hitl_without_deadline_remains_outside_watchdog(db_session):
    parent, child, decision, deadline = _delegated_hitl(db_session)
    child.input_ref = {}
    child.delegation_deadline_at = None
    parent.waiting_subflows = {}
    db_session.commit()

    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=10),
        )
        == "not_owned"
    )
    db_session.expire_all()
    assert db_session.query(Run).filter(Run.id == child.id).one().status == "hitl_pending"
    assert db_session.query(Decision).filter(Decision.id == decision.id).one().status == "proposed"


def test_parent_only_claim_cannot_cross_workspace(db_session):
    parent, child, decision, deadline = _delegated_hitl(db_session)
    other_workspace = Workspace(
        id=str(uuid4()),
        name="Other watchdog workspace",
        slug=f"other-watchdog-{uuid4()}",
    )
    db_session.add(other_workspace)
    delegation = dict((child.input_ref or {}).get("_delegation") or {})
    delegation.pop("execution_plane")
    child.input_ref = {"_delegation": delegation}
    child.delegation_deadline_at = None
    child.workspace_id = other_workspace.id
    decision.workspace_id = other_workspace.id
    db_session.commit()

    assert parent.workspace_id != child.workspace_id
    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=10),
        )
        == "not_owned"
    )
    db_session.expire_all()
    assert db_session.query(Run).filter(Run.id == child.id).one().status == "hitl_pending"


def test_expiry_cancels_active_delegated_descendants_in_same_transaction(
    db_session,
    monkeypatch,
):
    _parent, child, _decision, deadline = _delegated_hitl(db_session)
    descendant = Run(
        id=str(uuid4()),
        workspace_id=child.workspace_id,
        system_id=child.system_id,
        parent_run_id=child.id,
        status="running",
        delegation_key="e" * 64,
        delegation_node_id="nested",
        delegation_branch="review",
        input_ref={
            "_delegation": {
                "parent_run_id": child.id,
                "execution_plane": "celery",
            }
        },
        celery_task_id="nested-task",
    )
    child.waiting_subflows = {
        "_meta": {
            "strategy": "all",
            "state": "waiting",
            "execution_plane": "celery",
            "wave_id": 2,
        },
        descendant.delegation_key: {
            "child_run_id": descendant.id,
            "node_id": descendant.delegation_node_id,
            "branch": descendant.delegation_branch,
            "status": "running",
            "wave_id": 2,
        },
    }
    db_session.add(descendant)
    db_session.commit()
    monkeypatch.setattr(hitl_watchdog, "enqueue_dispatch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hitl_watchdog, "_revoke_tasks", lambda _task_ids: None)

    assert (
        hitl_watchdog._reconcile_candidate(
            db_session,
            run_id=child.id,
            now=deadline + timedelta(seconds=10),
        )
        == "expired"
    )
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == descendant.id).one()
    assert persisted.status == "cancelled"
    assert persisted.error == hitl_watchdog.WATCHDOG_ERROR


def test_batch_watchdog_is_inert_without_postgresql(monkeypatch):
    # Force the non-PostgreSQL branch explicitly: this unit suite is also run
    # against PostgreSQL by the real RabbitMQ gate.
    selection_db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(
            dialect=SimpleNamespace(name="sqlite"),
        )
    )
    monkeypatch.setattr(
        hitl_watchdog,
        "SessionLocal",
        lambda: nullcontext(selection_db),
    )

    # The production scanner must never silently emulate PostgreSQL row and
    # advisory locks on another dialect.
    result = hitl_watchdog.expire_overdue_hitl_waits(batch_size=10)
    assert result["unsupported"] == 1
    assert result["scanned"] == 0
