"""Bounded reconciliation of expired durable subflow HITL waits.

The watchdog is deliberately narrower than a generic Run timeout.  It only
owns Celery-delegated child Runs whose immutable delegation deadline elapsed
while the child was waiting for a human Decision.  Ordinary HITL remains
unbounded unless a future contract gives it an explicit deadline.

Every broker publication is represented by the dispatch outbox in the same
transaction as the state transition.  The periodic Celery task is only a
trigger; PostgreSQL and the persisted Run/Decision records are authoritative.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session as DBSession, aliased

from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.decision import Decision
from app.models.run import Run
from app.services.decisions.state_machine import reject as reject_decision

from .dispatch_outbox import (
    SUBFLOW_HITL_RESUME,
    SUBFLOW_PARENT_RESUME,
    enqueue_dispatch,
)
from .subflow_orchestration import (
    _cancel_waiting_descendants,
    _revoke_tasks,
    delegated_celery_claimed,
    delegated_celery_context,
    delegated_parent_claim_context,
    postgres_coordination_lease,
)

logger = get_logger(__name__)

WATCHDOG_ACTOR = "system:hitl-watchdog"
WATCHDOG_ERROR = "subflow_hitl_deadline_expired"
WATCHDOG_INVALID_ERROR = "subflow_hitl_watchdog_invalid_state"
_RESOLVED_DECISION_STATUSES = {"accepted", "applied", "rejected"}


def _utc_naive(value: datetime) -> datetime:
    """Normalise SQLAlchemy timestamps to the repository's naïve UTC clock."""

    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_deadline(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc_naive(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _utc_naive(parsed)


def _latest_hitl_pause(run: Run) -> dict[str, Any] | None:
    return next(
        (
            checkpoint
            for checkpoint in reversed(list(run.checkpoints or []))
            if isinstance(checkpoint, dict) and checkpoint.get("kind") == "hitl_pause"
        ),
        None,
    )


def _watchdog_celery_claimed(db: DBSession, run: Run) -> bool:
    """Recognise every durable claim that Celery owns this paused Run.

    The child envelope is sufficient evidence even when the rest of the
    delegation tuple is malformed.  Conversely, the existing broad parent
    claim check covers a child whose local envelope lost the execution plane.
    Both cases must fail closed instead of falling back to an ordinary,
    unbounded HITL wait.
    """

    delegation = (
        ((run.input_ref or {}).get("_delegation") or {})
        if isinstance(run.input_ref, dict)
        else {}
    )
    if isinstance(delegation, dict) and delegation.get("execution_plane") == "celery":
        return True
    return delegated_celery_claimed(
        db,
        child=run,
        workspace_id=run.workspace_id,
    )


def _delegation_deadlines_match(
    run: Run,
    entry: dict[str, Any],
    deadline: datetime,
) -> bool:
    """Require the typed index value to match both immutable envelopes."""

    delegation = (
        ((run.input_ref or {}).get("_delegation") or {})
        if isinstance(run.input_ref, dict)
        else {}
    )
    if not isinstance(delegation, dict) or delegation.get("execution_plane") != "celery":
        return False
    persisted_deadline = _parse_deadline(delegation.get("deadline_at"))
    parent_deadline = _parse_deadline(entry.get("deadline_at"))
    return persisted_deadline == deadline and parent_deadline == deadline


def _terminalize_invalid_run(run: Run, *, now: datetime, reason: str) -> None:
    """Persist the stable terminal shape used for corrupt HITL ownership."""

    run.status = "failed"
    run.error = WATCHDOG_INVALID_ERROR
    run.completed_at = now
    run.delegation_quarantined_at = now
    run.output_ref = {}
    if run.started_at is not None:
        run.duration_ms = max(
            0.0,
            (now - _utc_naive(run.started_at)).total_seconds() * 1000.0,
        )
    run.checkpoints = [
        *(run.checkpoints or []),
        {
            "kind": "hitl_watchdog_invalid",
            "t": now.isoformat(),
            "actor": WATCHDOG_ACTOR,
            "reason": str(reason)[:160],
        },
        {
            "kind": "run_end",
            "t": now.isoformat(),
            "status": "failed",
            "error": WATCHDOG_INVALID_ERROR,
            "interrupted": True,
        },
    ]


def _settle_parent_chain_after_quarantine(
    db: DBSession,
    *,
    child: Run,
    now: datetime,
    visited: set[str],
) -> list[str]:
    """Wake a valid parent, or terminalise malformed ancestors fail-closed."""

    if child.id in visited:
        return []
    visited.add(child.id)
    if not child.parent_run_id or not child.workspace_id:
        return []

    context = delegated_parent_claim_context(
        db,
        child=child,
        workspace_id=child.workspace_id,
    )
    parent_id = context[0].id if context is not None else child.parent_run_id
    parent = (
        db.query(Run)
        .filter(
            Run.id == parent_id,
            Run.workspace_id == child.workspace_id,
        )
        .populate_existing()
        # We already own the child.  A concurrent cancellation owns the
        # lineage top-down (parent then child), so waiting here would invert
        # lock order and permit a deadlock.  NOWAIT rolls this transaction
        # back; the bounded watchdog retries the same durable candidate after
        # the top-down mutation commits.
        .with_for_update(nowait=True)
        .first()
    )
    if parent is None or parent.status in {"completed", "failed", "cancelled"}:
        return []

    # Revalidate the weak claim after locking the parent. A valid active wave
    # can consume the child's stable failure through the normal parent worker.
    context = delegated_parent_claim_context(
        db,
        child=child,
        workspace_id=child.workspace_id,
    )
    if context is not None and context[0].id == parent.id and parent.status in {
        "waiting_subflows",
        "running",
    }:
        waiting = parent.waiting_subflows if isinstance(parent.waiting_subflows, dict) else {}
        meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
        enqueue_dispatch(
            db,
            event_type=SUBFLOW_PARENT_RESUME,
            workspace_id=str(parent.workspace_id),
            run_id=parent.id,
            source_id=child.id,
            wave_id=meta.get("wave_id"),
        )
        return []

    # A child-only claim with a malformed parent envelope cannot use the
    # normal resume validator. Fail that parent and its active descendants,
    # then continue upward until a valid ancestor can be woken.
    _terminalize_invalid_run(
        parent,
        now=now,
        reason="invalid_child_delegation_context",
    )
    _cancelled, task_ids = _cancel_waiting_descendants(
        db,
        parent,
        reason=WATCHDOG_INVALID_ERROR,
        visited=set(),
    )
    task_ids.extend(
        _settle_parent_chain_after_quarantine(
            db,
            child=parent,
            now=now,
            visited=visited,
        )
    )
    return task_ids


def quarantine_locked_hitl_owner(
    db: DBSession,
    *,
    run: Run,
    decision: Decision | None,
    now: datetime,
    reason: str,
) -> str:
    """Terminalise a locked invalid HITL owner and settle its parent chain."""

    if decision is not None and decision.status == "proposed":
        reject_decision(
            db,
            decision,
            actor=WATCHDOG_ACTOR,
            note="HITL ownership is invalid and cannot be resumed safely.",
            commit=False,
        )
    _terminalize_invalid_run(run, now=now, reason=reason)
    _cancelled, task_ids = _cancel_waiting_descendants(
        db,
        run,
        reason=WATCHDOG_INVALID_ERROR,
        visited=set(),
    )
    task_ids.extend(
        _settle_parent_chain_after_quarantine(
            db,
            child=run,
            now=now,
            visited=set(),
        )
    )
    db.commit()
    _revoke_tasks(task_ids)
    return "quarantined"


def _append_timeout_checkpoints(
    run: Run,
    *,
    decision_id: str,
    deadline: datetime,
    now: datetime,
) -> None:
    timestamp = now.isoformat()
    run.checkpoints = [
        *(run.checkpoints or []),
        {
            "kind": "hitl_timeout",
            "t": timestamp,
            "decision_id": decision_id,
            "deadline_at": deadline.isoformat(),
            "actor": WATCHDOG_ACTOR,
        },
        {
            "kind": "run_end",
            "t": timestamp,
            "status": "failed",
            "error": WATCHDOG_ERROR,
            "interrupted": True,
        },
    ]


def _quarantine_invalid_candidate(
    db: DBSession,
    *,
    run_id: str,
    now: datetime,
    reason: str,
    decision: Decision | None = None,
) -> str:
    """Fail one malformed overdue wait once so it cannot starve the scanner."""

    run = (
        db.query(Run)
        .filter(Run.id == run_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if run is None:
        return "missing"
    deadline = _parse_deadline(run.delegation_deadline_at)
    if (
        run.status != "hitl_pending"
        or not _watchdog_celery_claimed(db, run)
        or (deadline is not None and deadline > now)
    ):
        return "stale"
    quarantine_locked_hitl_owner(
        db,
        run=run,
        decision=decision,
        now=now,
        reason=reason,
    )
    logger.error(
        "hitl_watchdog: invalid overdue wait quarantined",
        run_id=run_id,
        reason=str(reason)[:160],
    )
    return "quarantined"


def _reconcile_candidate(
    db: DBSession,
    *,
    run_id: str,
    now: datetime,
) -> str:
    """Reconcile one candidate while its ``subflow-child`` lease is held.

    The Decision is locked before the Run, matching the public HITL endpoint's
    lock order.  Every mutable fact is then re-read and validated before a
    transition or an outbox insert is allowed.
    """

    now = _utc_naive(now)
    observed = db.query(Run).filter(Run.id == run_id).first()
    if observed is None:
        return "missing"
    if observed.status != "hitl_pending":
        return (
            "terminal"
            if observed.status in {"completed", "failed", "cancelled"}
            else "stale"
        )
    if not _watchdog_celery_claimed(db, observed):
        return "not_owned"
    pause = _latest_hitl_pause(observed)
    decision_id = str((pause or {}).get("decision_id") or "")
    if not decision_id:
        return _quarantine_invalid_candidate(
            db,
            run_id=run_id,
            now=now,
            reason="missing_decision_checkpoint",
        )

    decision = (
        db.query(Decision)
        .filter(
            Decision.id == decision_id,
            Decision.scope == "run",
            Decision.target_id == run_id,
            or_(
                Decision.workspace_id == observed.workspace_id,
                Decision.workspace_id.is_(None),
            ),
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if decision is None:
        return _quarantine_invalid_candidate(
            db,
            run_id=run_id,
            now=now,
            reason="decision_missing_or_out_of_scope",
        )

    run = (
        db.query(Run)
        .filter(Run.id == run_id, Run.workspace_id == observed.workspace_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if run is None:
        return "missing"
    if run.status != "hitl_pending":
        return "terminal" if run.status in {"completed", "failed", "cancelled"} else "stale"
    if not _watchdog_celery_claimed(db, run):
        return "not_owned"

    deadline = _parse_deadline(run.delegation_deadline_at)
    if deadline is None:
        return _quarantine_invalid_candidate(
            db,
            run_id=run_id,
            now=now,
            reason="missing_delegation_deadline",
            decision=decision,
        )
    if deadline > now:
        return "not_due"
    pause = _latest_hitl_pause(run)
    if str((pause or {}).get("decision_id") or "") != decision.id:
        return _quarantine_invalid_candidate(
            db,
            run_id=run_id,
            now=now,
            reason="decision_checkpoint_changed",
            decision=decision,
        )

    context = delegated_celery_context(
        db,
        child=run,
        workspace_id=run.workspace_id,
    )
    if context is None:
        return _quarantine_invalid_candidate(
            db,
            run_id=run_id,
            now=now,
            reason="delegation_envelope_invalid",
            decision=decision,
        )
    parent, entry = context
    if not _delegation_deadlines_match(run, entry, deadline):
        return _quarantine_invalid_candidate(
            db,
            run_id=run_id,
            now=now,
            reason="delegation_deadline_mismatch",
            decision=decision,
        )

    waiting = parent.waiting_subflows if isinstance(parent.waiting_subflows, dict) else {}
    meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
    wave_id = meta.get("wave_id")

    # A human response durably recorded before the deadline owns the outcome,
    # even when the broker publication or worker execution was delayed.  The
    # outbox republishes the same logical continuation without extending the
    # immutable deadline.
    approved_at = _parse_deadline(decision.approved_at)
    if (
        decision.status in _RESOLVED_DECISION_STATUSES
        and approved_at is not None
        and approved_at <= deadline
    ):
        enqueue_dispatch(
            db,
            event_type=SUBFLOW_HITL_RESUME,
            workspace_id=run.workspace_id,
            run_id=run.id,
            decision_id=decision.id,
        )
        db.commit()
        return "resume_enqueued"

    if decision.status == "proposed":
        timeout_note = (
            f"HITL deadline expired at {deadline.isoformat()} UTC; "
            f"resolved automatically by {WATCHDOG_ACTOR}."
        )
        # Keep the canonical Decision state machine authoritative while
        # deferring its commit so the Run failure and outbox insert remain one
        # transaction.
        reject_decision(
            db,
            decision,
            actor=WATCHDOG_ACTOR,
            note=timeout_note,
            commit=False,
        )
        rationale = dict(decision.rationale or {}) if isinstance(decision.rationale, dict) else {}
        rationale["hitl_timeout"] = {
            "deadline_at": deadline.isoformat(),
            "expired_at": now.isoformat(),
            "actor": WATCHDOG_ACTOR,
        }
        decision.rationale = rationale

    # A late accepted/rejected Decision remains an immutable audit fact, but it
    # cannot resurrect execution after the delegation budget elapsed.
    run.status = "failed"
    run.error = WATCHDOG_ERROR
    run.completed_at = now
    run.output_ref = {}
    if run.started_at is not None:
        run.duration_ms = max(0.0, (now - _utc_naive(run.started_at)).total_seconds() * 1000.0)
    _append_timeout_checkpoints(
        run,
        decision_id=decision.id,
        deadline=deadline,
        now=now,
    )
    _, descendant_task_ids = _cancel_waiting_descendants(
        db,
        run,
        reason=WATCHDOG_ERROR,
        visited=set(),
    )
    enqueue_dispatch(
        db,
        event_type=SUBFLOW_PARENT_RESUME,
        workspace_id=run.workspace_id,
        run_id=parent.id,
        source_id=run.id,
        wave_id=wave_id,
    )
    db.commit()
    _revoke_tasks(descendant_task_ids)
    return "expired"


def expire_overdue_hitl_waits(*, batch_size: int = 100) -> dict[str, int]:
    """Process one bounded PostgreSQL batch and return operational counters."""

    batch_size = max(1, min(int(batch_size), 1000))
    counters = {
        "scanned": 0,
        "expired": 0,
        "resume_enqueued": 0,
        "quarantined": 0,
        "busy": 0,
        "invalid": 0,
        "stale": 0,
        "errors": 0,
        "unsupported": 0,
    }
    now = datetime.utcnow()
    with SessionLocal() as selection_db:
        if selection_db.get_bind().dialect.name != "postgresql":
            counters["unsupported"] = 1
            return counters
        parent = aliased(Run, name="hitl_watchdog_parent")
        parent_entry = parent.waiting_subflows.op("->")(Run.delegation_key)
        child_celery_claim = (
            Run.input_ref["_delegation"]["execution_plane"].as_string()
            == "celery"
        )
        parent_celery_claim = and_(
            Run.parent_run_id.isnot(None),
            Run.delegation_key.isnot(None),
            parent.id.isnot(None),
            parent.waiting_subflows["_meta"]["execution_plane"].as_string()
            == "celery",
            parent_entry.op("->>")("child_run_id") == Run.id,
        )
        candidate_ids = [
            row[0]
            for row in (
                selection_db.query(Run.id)
                .outerjoin(
                    parent,
                    and_(
                        parent.id == Run.parent_run_id,
                        parent.workspace_id == Run.workspace_id,
                    ),
                )
                .filter(
                    Run.status == "hitl_pending",
                    or_(child_celery_claim, parent_celery_claim),
                    or_(
                        Run.delegation_deadline_at.is_(None),
                        Run.delegation_deadline_at <= now,
                    ),
                )
                .order_by(
                    Run.delegation_deadline_at.asc().nullsfirst(),
                    Run.id.asc(),
                )
                # PostgreSQL cannot lock the nullable side of an outer join.
                # The advisory lease later protects reconciliation; this
                # selector only needs disjoint ownership of child Run rows.
                .with_for_update(skip_locked=True, of=Run)
                .limit(batch_size)
                .all()
            )
        ]
        counters["scanned"] = len(candidate_ids)
        # The row locks only make concurrent scanners choose disjoint initial
        # batches.  Execution ownership is the existing child advisory lease.
        selection_db.commit()

    for run_id in candidate_ids:
        try:
            with postgres_coordination_lease("subflow-child", run_id) as acquired:
                if not acquired:
                    counters["busy"] += 1
                    continue
                with SessionLocal() as db:
                    outcome = _reconcile_candidate(db, run_id=run_id, now=now)
                    if outcome in counters:
                        counters[outcome] += 1
                    elif outcome in {"missing", "terminal", "not_due", "not_owned"}:
                        counters["stale"] += 1
                    else:
                        counters["invalid"] += 1
        except Exception as exc:  # one malformed row must not starve the batch
            counters["errors"] += 1
            logger.error(
                "hitl_watchdog: candidate reconciliation failed",
                run_id=run_id,
                error_type=type(exc).__name__,
            )
    return counters
