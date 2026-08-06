"""Transactional and delivery contracts for the P4 Run dispatch outbox."""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app.models.decision import Decision
from app.models.run import Run
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.workspace import Workspace
from app.services.run_engine.dispatch_outbox import (
    RUN_HITL_RESUME,
    SUBFLOW_HITL_RESUME,
    SUBFLOW_PARENT_RESUME,
    SUBFLOW_RUN,
    TRIGGER_RUN,
    DispatchLeaseLost,
    ObsoleteDispatch,
    PermanentDispatchError,
    claim_dispatch_batch,
    enqueue_dispatch,
    mark_dispatch_published,
    mark_dispatch_retry,
    publish_claimed_dispatch,
    repair_dispatch_gaps,
)


def _workspace_and_run(db_session, *, status: str = "pending") -> tuple[Workspace, Run]:
    workspace = Workspace(
        id=str(uuid4()),
        name="Outbox test",
        slug=f"outbox-{uuid4()}",
    )
    run = Run(id=str(uuid4()), workspace_id=workspace.id, status=status)
    db_session.add_all([workspace, run])
    db_session.flush()
    return workspace, run


def _make_publishable_subflow(db_session, workspace: Workspace, child: Run) -> Run:
    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        status="waiting_subflows",
    )
    child.parent_run_id = parent.id
    child.delegation_key = uuid4().hex * 2
    child.delegation_node_id = "delegate"
    child.delegation_branch = "main"
    child.input_ref = {
        "_delegation": {
            "parent_run_id": parent.id,
            "execution_plane": "celery",
        }
    }
    parent.waiting_subflows = {
        "_meta": {"execution_plane": "celery", "strategy": "all", "wave_id": 1},
        child.delegation_key: {
            "child_run_id": child.id,
            "node_id": child.delegation_node_id,
            "branch": child.delegation_branch,
            "wave_id": 1,
            "status": child.status,
        },
    }
    db_session.add(parent)
    db_session.flush()
    return parent


def test_enqueue_is_uncommitted_idempotent_and_task_id_is_stable(db_session):
    workspace, run = _workspace_and_run(db_session)

    first = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=run.id,
        source_id="delegation-key",
        wave_id=3,
    )
    second = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=run.id,
        source_id="delegation-key",
        wave_id=3,
    )

    assert first.id == second.id
    assert first.task_id == second.task_id
    assert first.state == "pending"
    assert db_session.query(RunDispatchOutbox).count() == 1
    db_session.rollback()
    assert db_session.query(RunDispatchOutbox).count() == 0


@pytest.mark.parametrize("invalid_wave", [True, 1.0, "1", -1])
def test_enqueue_rejects_noncanonical_wave_ids(db_session, invalid_wave):
    workspace, run = _workspace_and_run(db_session)

    with pytest.raises(ValueError, match="non-negative integer"):
        enqueue_dispatch(
            db_session,
            event_type=SUBFLOW_RUN,
            workspace_id=workspace.id,
            run_id=run.id,
            wave_id=invalid_wave,
        )


def test_custom_dedupe_key_cannot_alias_a_different_envelope(db_session):
    workspace, run = _workspace_and_run(db_session)
    other = Run(id=str(uuid4()), workspace_id=workspace.id, status="pending")
    db_session.add(other)
    db_session.flush()
    enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=run.id,
        dedupe_key="stable-event",
    )
    with pytest.raises(ValueError, match="different dispatch envelope"):
        enqueue_dispatch(
            db_session,
            event_type=SUBFLOW_RUN,
            workspace_id=workspace.id,
            run_id=other.id,
            dedupe_key="stable-event",
        )


def test_claim_recovers_expired_lease_and_stale_owner_cannot_ack(db_session):
    workspace, run = _workspace_and_run(db_session)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=run.id,
        wave_id=1,
    )
    db_session.commit()
    first = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=2)[0]
    first_token = first.lease_token
    first.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    second = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    assert second.id == row.id
    assert second.attempts == 2
    assert second.lease_token != first_token
    with pytest.raises(DispatchLeaseLost):
        mark_dispatch_published(
            db_session,
            outbox_id=row.id,
            lease_token=str(first_token),
        )


def test_retry_is_capped_and_releases_the_lease(db_session):
    workspace, run = _workspace_and_run(db_session)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=run.id,
        wave_id=1,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    now = datetime.utcnow()
    retried = mark_dispatch_retry(
        db_session,
        outbox_id=row.id,
        lease_token=str(claimed.lease_token),
        error="broker unavailable",
        now=now,
        base_delay_seconds=2,
        max_delay_seconds=3,
    )
    assert retried.state == "pending"
    assert retried.lease_token is None
    assert retried.last_error == "broker unavailable"
    assert now < retried.available_at <= now + timedelta(seconds=3)


def test_publish_uses_only_ids_and_the_outbox_task_id(db_session, monkeypatch):
    workspace, run = _workspace_and_run(db_session, status="hitl_pending")
    run.input_ref = {"secret": "must-never-enter-rabbitmq"}
    decision_id = str(uuid4())
    run.checkpoints = [
        {"kind": "hitl_pause", "decision_id": decision_id},
        {
            "kind": "hitl_resume_dispatch",
            "decision_id": decision_id,
            "plane": "run_celery",
        },
    ]
    db_session.add(
        Decision(
            id=decision_id,
            workspace_id=workspace.id,
            scope="run",
            target_id=run.id,
            status="accepted",
            title="Approve",
            approved_at=datetime.utcnow(),
        )
    )
    row = enqueue_dispatch(
        db_session,
        event_type=RUN_HITL_RESUME,
        workspace_id=workspace.id,
        run_id=run.id,
        decision_id=decision_id,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    published = {}

    class Result:
        id = row.task_id

    def fake_send_task(name, *, args, kwargs, **options):
        published.update(name=name, args=args, kwargs=kwargs, options=options)
        return Result()

    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", fake_send_task)
    assert publish_claimed_dispatch(
        db_session,
        outbox_id=row.id,
        lease_token=str(claimed.lease_token),
    ) == row.task_id
    assert published == {
        "name": "agentium.run_hitl_resume",
        "args": [run.id, decision_id],
        "kwargs": {},
        "options": {"task_id": row.task_id},
    }
    db_session.refresh(row)
    assert row.state == "published"


def test_trigger_run_publish_uses_claim_and_identifier_only(db_session, monkeypatch):
    workspace, run = _workspace_and_run(db_session)
    run.trigger = "webhook"
    run.trigger_dedup_key = "trigger-key"
    row = enqueue_dispatch(
        db_session,
        event_type=TRIGGER_RUN,
        workspace_id=workspace.id,
        run_id=run.id,
        source_id=run.trigger_dedup_key,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    published = {}

    class Result:
        id = row.task_id

    def fake_send_task(name, *, args, kwargs, **options):
        published.update(name=name, args=args, kwargs=kwargs, options=options)
        return Result()

    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", fake_send_task)
    publish_claimed_dispatch(
        db_session,
        outbox_id=row.id,
        lease_token=str(claimed.lease_token),
    )

    assert published == {
        "name": "agentium.trigger_run",
        "args": [run.id],
        "kwargs": {},
        "options": {"task_id": row.task_id},
    }
    db_session.refresh(run)
    assert run.celery_task_id == row.task_id


def test_repair_recovers_pending_trigger_run_without_outbox(db_session):
    workspace, run = _workspace_and_run(db_session)
    run.trigger = "webhook"
    run.trigger_dedup_key = "repair-trigger-key"
    db_session.commit()

    repaired = repair_dispatch_gaps(db_session, limit=5)
    db_session.commit()

    assert repaired[TRIGGER_RUN] == 1
    row = db_session.query(RunDispatchOutbox).filter_by(event_type=TRIGGER_RUN).one()
    assert (row.run_id, row.source_id, row.state) == (
        run.id,
        run.trigger_dedup_key,
        "pending",
    )


def test_publish_failure_returns_row_to_pending(db_session, monkeypatch):
    workspace, run = _workspace_and_run(db_session)
    _make_publishable_subflow(db_session, workspace, run)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=run.id,
        wave_id=1,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]

    def fail_publish(*_args, **_kwargs):
        raise OSError("RabbitMQ down")

    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", fail_publish)
    with pytest.raises(OSError, match="RabbitMQ down"):
        publish_claimed_dispatch(
            db_session,
            outbox_id=row.id,
            lease_token=str(claimed.lease_token),
        )
    db_session.refresh(row)
    assert row.state == "pending"
    assert row.lease_token is None
    assert row.last_error == "OSError"


def test_subflow_publication_preserves_absolute_deadline(db_session, monkeypatch):
    workspace, run = _workspace_and_run(db_session)
    _make_publishable_subflow(db_session, workspace, run)
    run.delegation_deadline_at = datetime.utcnow() + timedelta(seconds=2.5)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=run.id,
        wave_id=1,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    published = {}

    class Result:
        id = row.task_id

    def fake_send_task(name, *, args, kwargs, **options):
        published.update(name=name, args=args, kwargs=kwargs, options=options)
        return Result()

    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", fake_send_task)
    publish_claimed_dispatch(
        db_session,
        outbox_id=row.id,
        lease_token=str(claimed.lease_token),
    )
    assert published["name"] == "agentium.subflow_run"
    assert published["args"] == [run.id]
    assert published["kwargs"] == {}
    assert 1 <= published["options"]["soft_time_limit"] <= 3
    assert published["options"]["time_limit"] == published["options"]["soft_time_limit"] + 5


def test_repair_derives_initial_and_parent_resume_events(db_session):
    workspace, parent = _workspace_and_run(db_session, status="waiting_subflows")
    child = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        parent_run_id=parent.id,
        status="pending",
        delegation_key="d" * 64,
        delegation_node_id="delegate",
        delegation_branch="main",
        input_ref={
            "_delegation": {
                "parent_run_id": parent.id,
                "execution_plane": "celery",
                "deadline_at": (datetime.utcnow() + timedelta(minutes=1)).isoformat(),
            }
        },
    )
    parent.waiting_subflows = {
        "_meta": {"execution_plane": "celery", "strategy": "all", "wave_id": 4},
        child.delegation_key: {
            "child_run_id": child.id,
            "node_id": "delegate",
            "branch": "main",
            "wave_id": 4,
            "status": "pending",
        },
    }
    db_session.add(child)
    db_session.commit()

    first = repair_dispatch_gaps(db_session)
    db_session.commit()
    assert first[SUBFLOW_RUN] == 1
    initial = db_session.query(RunDispatchOutbox).filter_by(event_type=SUBFLOW_RUN).one()
    assert initial.run_id == child.id
    assert child.delegation_deadline_at is not None

    child.status = "completed"
    child.completed_at = datetime.utcnow()
    db_session.commit()
    second = repair_dispatch_gaps(db_session)
    db_session.commit()
    assert second[SUBFLOW_PARENT_RESUME] == 1
    resume = (
        db_session.query(RunDispatchOutbox)
        .filter_by(event_type=SUBFLOW_PARENT_RESUME)
        .one()
    )
    assert (resume.run_id, resume.source_id, resume.wave_id) == (parent.id, child.id, 4)


def test_quarantined_parent_only_child_repairs_and_publishes_parent_resume(
    db_session,
    monkeypatch,
):
    workspace, child = _workspace_and_run(db_session, status="failed")
    parent = _make_publishable_subflow(db_session, workspace, child)
    child.input_ref = {
        "_delegation": {
            "parent_run_id": parent.id,
        }
    }
    child.error = "subflow_hitl_watchdog_invalid_state"
    child.delegation_quarantined_at = datetime.utcnow()
    child.checkpoints = [
        {
            "kind": "hitl_watchdog_invalid",
            "reason": "missing_delegation_deadline",
        },
        {"kind": "run_end", "status": "failed"},
    ]
    db_session.commit()

    repaired = repair_dispatch_gaps(db_session)
    db_session.commit()

    assert repaired[SUBFLOW_PARENT_RESUME] == 1
    event = db_session.query(RunDispatchOutbox).one()
    assert (event.run_id, event.source_id, event.wave_id) == (
        parent.id,
        child.id,
        1,
    )
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    published = {}

    class Result:
        id = event.task_id

    def fake_send_task(name, *, args, kwargs, **options):
        published.update(name=name, args=args, kwargs=kwargs, options=options)
        return Result()

    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", fake_send_task)
    publish_claimed_dispatch(
        db_session,
        outbox_id=event.id,
        lease_token=str(claimed.lease_token),
    )

    assert published == {
        "name": "agentium.subflow_parent_resume",
        "args": [parent.id],
        "kwargs": {},
        "options": {"task_id": event.task_id},
    }


def test_repair_limit_selects_real_gap_not_already_covered_child(db_session):
    workspace, covered = _workspace_and_run(db_session)
    _make_publishable_subflow(db_session, workspace, covered)
    enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=covered.id,
    )

    missing = Run(id=str(uuid4()), workspace_id=workspace.id, status="pending")
    db_session.add(missing)
    _make_publishable_subflow(db_session, workspace, missing)
    db_session.commit()

    repaired = repair_dispatch_gaps(db_session, limit=1)
    db_session.commit()

    assert repaired[SUBFLOW_RUN] == 1
    row = (
        db_session.query(RunDispatchOutbox)
        .filter(
            RunDispatchOutbox.event_type == SUBFLOW_RUN,
            RunDispatchOutbox.run_id == missing.id,
        )
        .one()
    )
    assert row.workspace_id == workspace.id


def test_repair_limit_skips_old_irreparable_child_only_quarantine(db_session):
    workspace, poisoned = _workspace_and_run(db_session, status="failed")
    poisoned.started_at = datetime.utcnow() - timedelta(days=1)
    poisoned_parent = _make_publishable_subflow(db_session, workspace, poisoned)
    poisoned_parent.waiting_subflows = {}
    poisoned.error = "subflow_hitl_watchdog_invalid_state"
    poisoned.delegation_quarantined_at = datetime.utcnow()
    poisoned.checkpoints = [
        {
            "kind": "hitl_watchdog_invalid",
            "reason": "invalid_child_delegation_context",
        },
        {"kind": "run_end", "status": "failed"},
    ]

    real_gap = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        status="pending",
        started_at=datetime.utcnow(),
    )
    db_session.add(real_gap)
    _make_publishable_subflow(db_session, workspace, real_gap)
    db_session.commit()

    repaired = repair_dispatch_gaps(db_session, limit=1)
    db_session.commit()

    assert repaired[SUBFLOW_RUN] == 1
    assert repaired[SUBFLOW_PARENT_RESUME] == 0
    event = db_session.query(RunDispatchOutbox).one()
    assert (event.event_type, event.run_id) == (SUBFLOW_RUN, real_gap.id)


def test_repair_query_excludes_more_than_work_cap_of_typed_wave_mismatches(
    db_session,
):
    workspace, _seed = _workspace_and_run(db_session)
    db_session.delete(_seed)
    oldest = datetime.utcnow() - timedelta(days=2)
    for index in range(257):
        malformed = Run(
            id=str(uuid4()),
            workspace_id=workspace.id,
            status="pending",
            started_at=oldest + timedelta(seconds=index),
        )
        db_session.add(malformed)
        malformed_parent = _make_publishable_subflow(db_session, workspace, malformed)
        waiting = dict(malformed_parent.waiting_subflows)
        entry = dict(waiting[malformed.delegation_key])
        # JSON number 1 and JSON string "1" have the same ->> text in
        # PostgreSQL, but are different immutable wave identifiers.
        entry["wave_id"] = "1"
        waiting[malformed.delegation_key] = entry
        malformed_parent.waiting_subflows = waiting

    real_gap = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        status="pending",
        started_at=datetime.utcnow(),
    )
    db_session.add(real_gap)
    _make_publishable_subflow(db_session, workspace, real_gap)
    db_session.commit()

    repaired = repair_dispatch_gaps(db_session, limit=1)
    db_session.commit()

    assert repaired[SUBFLOW_RUN] == 1
    event = db_session.query(RunDispatchOutbox).one()
    assert (event.event_type, event.run_id) == (SUBFLOW_RUN, real_gap.id)


def test_repair_limit_ignores_in_process_delegations(db_session):
    workspace, in_process = _workspace_and_run(db_session)
    _make_publishable_subflow(db_session, workspace, in_process)
    in_process.input_ref = {
        "_delegation": {
            "parent_run_id": in_process.parent_run_id,
        }
    }

    celery_child = Run(id=str(uuid4()), workspace_id=workspace.id, status="pending")
    db_session.add(celery_child)
    _make_publishable_subflow(db_session, workspace, celery_child)
    db_session.commit()

    repaired = repair_dispatch_gaps(db_session, limit=1)
    db_session.commit()

    assert repaired[SUBFLOW_RUN] == 1
    assert (
        db_session.query(RunDispatchOutbox)
        .filter_by(event_type=SUBFLOW_RUN, run_id=celery_child.id)
        .count()
        == 1
    )
    assert (
        db_session.query(RunDispatchOutbox)
        .filter_by(event_type=SUBFLOW_RUN, run_id=in_process.id)
        .count()
        == 0
    )


def test_repair_targets_outermost_paused_ancestor_for_nested_hitl(db_session):
    workspace, outer = _workspace_and_run(db_session, status="hitl_pending")
    decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id="placeholder",
        status="accepted",
        title="Nested approval",
        approved_at=datetime.utcnow(),
    )
    inner = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        parent_run_id=outer.id,
        status="hitl_pending",
    )
    decision.target_id = inner.id
    pause = {"kind": "hitl_pause", "decision_id": decision.id}
    inner.checkpoints = [pause]
    outer.checkpoints = [
        pause,
        {
            "kind": "hitl_resume_dispatch",
            "decision_id": decision.id,
            "plane": "run_celery",
        },
    ]
    db_session.add_all([inner, decision])
    db_session.commit()

    repaired = repair_dispatch_gaps(db_session, limit=1)
    db_session.commit()

    assert repaired[RUN_HITL_RESUME] == 1
    event = db_session.query(RunDispatchOutbox).one()
    assert (event.run_id, event.decision_id) == (outer.id, decision.id)


def _late_delegated_hitl(db_session) -> tuple[Workspace, Run, Decision]:
    workspace, child = _workspace_and_run(db_session, status="hitl_pending")
    parent = _make_publishable_subflow(db_session, workspace, child)
    deadline = datetime.utcnow() - timedelta(seconds=5)
    child.delegation_deadline_at = deadline
    child.input_ref = {
        "_delegation": {
            "parent_run_id": parent.id,
            "execution_plane": "celery",
            "deadline_at": deadline.isoformat(),
        }
    }
    waiting = dict(parent.waiting_subflows)
    entry = dict(waiting[child.delegation_key])
    entry["deadline_at"] = deadline.isoformat()
    waiting[child.delegation_key] = entry
    parent.waiting_subflows = waiting
    decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=child.id,
        status="accepted",
        title="Too late",
        approved_at=deadline + timedelta(seconds=2),
    )
    child.checkpoints = [
        {"kind": "hitl_pause", "decision_id": decision.id},
        {
            "kind": "hitl_resume_dispatch",
            "decision_id": decision.id,
            "plane": "subflow_celery",
        },
    ]
    db_session.add(decision)
    db_session.commit()
    return workspace, child, decision


def test_repair_leaves_late_delegated_hitl_to_watchdog(db_session):
    _late_delegated_hitl(db_session)

    repaired = repair_dispatch_gaps(db_session)
    db_session.commit()

    assert repaired[SUBFLOW_HITL_RESUME] == 0
    assert db_session.query(RunDispatchOutbox).count() == 0


def test_publisher_fails_late_delegated_hitl_closed(db_session, monkeypatch):
    workspace, child, decision = _late_delegated_hitl(db_session)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_HITL_RESUME,
        workspace_id=workspace.id,
        run_id=child.id,
        decision_id=decision.id,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    monkeypatch.setattr(
        "app.workers.celery_app.celery_app.send_task",
        lambda *_args, **_kwargs: pytest.fail("late HITL must not reach RabbitMQ"),
    )

    with pytest.raises(ObsoleteDispatch, match="missed its deadline"):
        publish_claimed_dispatch(
            db_session,
            outbox_id=row.id,
            lease_token=str(claimed.lease_token),
        )
    db_session.refresh(row)
    assert row.state == "cancelled"


def test_obsolete_initial_dispatch_is_cancelled_without_broker(db_session, monkeypatch):
    workspace, child = _workspace_and_run(db_session)
    parent = _make_publishable_subflow(db_session, workspace, child)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=child.id,
        source_id=child.delegation_key,
        wave_id=1,
    )
    parent.status = "cancelled"
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    monkeypatch.setattr(
        "app.workers.celery_app.celery_app.send_task",
        lambda *_args, **_kwargs: pytest.fail("obsolete dispatch must not reach RabbitMQ"),
    )

    with pytest.raises(ObsoleteDispatch, match="parent is already terminal"):
        publish_claimed_dispatch(
            db_session,
            outbox_id=row.id,
            lease_token=str(claimed.lease_token),
        )
    db_session.refresh(row)
    assert row.state == "cancelled"


def test_late_ack_does_not_mutate_a_new_fanout_wave(db_session):
    workspace, child = _workspace_and_run(db_session)
    parent = _make_publishable_subflow(db_session, workspace, child)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=child.id,
        source_id=child.delegation_key,
        wave_id=1,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    waiting = dict(parent.waiting_subflows)
    waiting["_meta"] = {**waiting["_meta"], "wave_id": 2}
    waiting[child.delegation_key] = {
        **waiting[child.delegation_key],
        "wave_id": 2,
        "dispatch_state": "outbox_pending",
    }
    parent.waiting_subflows = waiting
    flag_modified(parent, "waiting_subflows")
    db_session.commit()

    mark_dispatch_published(
        db_session,
        outbox_id=row.id,
        lease_token=str(claimed.lease_token),
    )
    db_session.refresh(parent)
    db_session.refresh(row)
    assert row.state == "published"
    assert parent.waiting_subflows[child.delegation_key]["dispatch_state"] == "outbox_pending"


@pytest.mark.parametrize("coerced_wave", [True, 1.0])
def test_publisher_rejects_python_coerced_parent_wave(
    db_session,
    monkeypatch,
    coerced_wave,
):
    workspace, child = _workspace_and_run(db_session)
    parent = _make_publishable_subflow(db_session, workspace, child)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=child.id,
        source_id=child.delegation_key,
        wave_id=1,
    )
    waiting = dict(parent.waiting_subflows)
    waiting["_meta"] = {**waiting["_meta"], "wave_id": coerced_wave}
    waiting[child.delegation_key] = {
        **waiting[child.delegation_key],
        "wave_id": coerced_wave,
    }
    parent.waiting_subflows = waiting
    flag_modified(parent, "waiting_subflows")
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    monkeypatch.setattr(
        "app.workers.celery_app.celery_app.send_task",
        lambda *_args, **_kwargs: pytest.fail(
            "noncanonical wave must not reach RabbitMQ"
        ),
    )

    with pytest.raises(ObsoleteDispatch, match="active parent wave"):
        publish_claimed_dispatch(
            db_session,
            outbox_id=row.id,
            lease_token=str(claimed.lease_token),
        )
    db_session.refresh(row)
    assert row.state == "cancelled"


@pytest.mark.parametrize("coerced_wave", [True, 1.0])
def test_late_ack_does_not_coerce_parent_wave_type(db_session, coerced_wave):
    workspace, child = _workspace_and_run(db_session)
    parent = _make_publishable_subflow(db_session, workspace, child)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_RUN,
        workspace_id=workspace.id,
        run_id=child.id,
        source_id=child.delegation_key,
        wave_id=1,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    waiting = dict(parent.waiting_subflows)
    waiting["_meta"] = {**waiting["_meta"], "wave_id": coerced_wave}
    waiting[child.delegation_key] = {
        **waiting[child.delegation_key],
        "wave_id": coerced_wave,
        "dispatch_state": "outbox_pending",
    }
    parent.waiting_subflows = waiting
    flag_modified(parent, "waiting_subflows")
    db_session.commit()

    mark_dispatch_published(
        db_session,
        outbox_id=row.id,
        lease_token=str(claimed.lease_token),
    )

    db_session.refresh(parent)
    assert parent.waiting_subflows[child.delegation_key]["dispatch_state"] == "outbox_pending"


def test_parent_resume_from_stale_wave_is_cancelled(db_session, monkeypatch):
    workspace, child = _workspace_and_run(db_session, status="completed")
    parent = _make_publishable_subflow(db_session, workspace, child)
    row = enqueue_dispatch(
        db_session,
        event_type=SUBFLOW_PARENT_RESUME,
        workspace_id=workspace.id,
        run_id=parent.id,
        source_id=child.id,
        wave_id=1,
    )
    waiting = dict(parent.waiting_subflows)
    waiting["_meta"] = {**waiting["_meta"], "wave_id": 2}
    waiting[child.delegation_key] = {**waiting[child.delegation_key], "wave_id": 2}
    parent.waiting_subflows = waiting
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    monkeypatch.setattr(
        "app.workers.celery_app.celery_app.send_task",
        lambda *_args, **_kwargs: pytest.fail("stale wave must not reach RabbitMQ"),
    )

    with pytest.raises(ObsoleteDispatch, match="stale fan-out wave"):
        publish_claimed_dispatch(
            db_session,
            outbox_id=row.id,
            lease_token=str(claimed.lease_token),
        )
    db_session.refresh(row)
    assert row.state == "cancelled"


def test_cross_workspace_hitl_decision_is_dead_without_broker(db_session, monkeypatch):
    workspace, run = _workspace_and_run(db_session, status="hitl_pending")
    foreign = Workspace(id=str(uuid4()), slug=f"foreign-{uuid4()}", name="Foreign")
    decision = Decision(
        id=str(uuid4()),
        workspace_id=foreign.id,
        scope="run",
        target_id=run.id,
        status="accepted",
        title="Foreign approval",
        approved_at=datetime.utcnow(),
    )
    run.checkpoints = [
        {"kind": "hitl_pause", "decision_id": decision.id},
        {
            "kind": "hitl_resume_dispatch",
            "decision_id": decision.id,
            "plane": "run_celery",
        },
    ]
    db_session.add_all([foreign, decision])
    row = enqueue_dispatch(
        db_session,
        event_type=RUN_HITL_RESUME,
        workspace_id=workspace.id,
        run_id=run.id,
        decision_id=decision.id,
    )
    db_session.commit()
    claimed = claim_dispatch_batch(db_session, batch_size=1, lease_seconds=30)[0]
    monkeypatch.setattr(
        "app.workers.celery_app.celery_app.send_task",
        lambda *_args, **_kwargs: pytest.fail("cross-workspace event must not publish"),
    )

    with pytest.raises(PermanentDispatchError, match="Decision no longer exists"):
        publish_claimed_dispatch(
            db_session,
            outbox_id=row.id,
            lease_token=str(claimed.lease_token),
        )
    db_session.refresh(row)
    assert row.state == "dead"
