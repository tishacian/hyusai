"""Gate TTL helpers + expired-gate sweep for HITL / membrane HOLD pauses.

``scheduler_tick`` calls :func:`sweep_expired_gates` every ~60s. Actions:

* ``reject`` / ``approve`` — transition the Decision, resume the paused Run.
* ``escalate`` — append a checkpoint reminder, clear ``expires_at`` so the
  gate stays open for a human (no hot-loop on every tick).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System

logger = get_logger(__name__)

EXPIRY_REJECT = "reject"
EXPIRY_APPROVE = "approve"
EXPIRY_ESCALATE = "escalate"
_VALID_ACTIONS = frozenset({EXPIRY_REJECT, EXPIRY_APPROVE, EXPIRY_ESCALATE})
_DEFERRED_TO_P4 = "deferred_to_p4"
_INVALID_PERSISTED_PLANE = "invalid_persisted_plane"
_QUARANTINE_LOCAL = "quarantine_local"


def normalize_expiry_action(raw: Any) -> str:
    action = str(raw or settings.hitl_gate_default_expiry_action or EXPIRY_REJECT).strip().lower()
    return action if action in _VALID_ACTIONS else EXPIRY_REJECT


def resolve_gate_ttl(
    config: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
) -> tuple[datetime, str]:
    """Return ``(expires_at, expiry_action)`` from node config or defaults."""
    cfg = config if isinstance(config, dict) else {}
    days = cfg.get("expires_in_days")
    if days is None:
        days = cfg.get("gate_ttl_days")
    if days is None:
        days = settings.hitl_gate_ttl_days
    try:
        days_f = float(days)
    except (TypeError, ValueError):
        days_f = float(settings.hitl_gate_ttl_days)
    if days_f <= 0:
        days_f = float(settings.hitl_gate_ttl_days)
    base = now or datetime.utcnow()
    action = normalize_expiry_action(cfg.get("expiry_action"))
    return base + timedelta(days=days_f), action


def stamp_decision_ttl(
    decision: Optional[Decision],
    config: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Mutate a Decision with TTL fields (caller commits)."""
    if decision is None:
        return
    expires_at, action = resolve_gate_ttl(config, now=now)
    decision.expires_at = expires_at
    decision.expiry_action = action
    rationale = dict(decision.rationale or {})
    rationale["gate_ttl"] = {
        "expires_at": expires_at.isoformat(),
        "expiry_action": action,
    }
    decision.rationale = rationale


def _append_run_checkpoint(db: DBSession, run: Run, checkpoint: Dict[str, Any]) -> None:
    run.checkpoints = [*(run.checkpoints or []), checkpoint]
    db.add(run)


def _resume_paused_run(run_id: str, decision_id: str) -> None:
    """Mirror the HITL API resume shim (sync entry for Celery tick)."""
    import asyncio

    from app.services.run_engine.dag import resume_run_dag  # noqa: WPS433

    try:
        asyncio.run(resume_run_dag(run_id, decision_id=decision_id))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(resume_run_dag(run_id, decision_id=decision_id))


def _utc_naive(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _latest_pause_decision(run: Run) -> Optional[str]:
    pause = next(
        (
            checkpoint
            for checkpoint in reversed(list(run.checkpoints or []))
            if isinstance(checkpoint, dict) and checkpoint.get("kind") == "hitl_pause"
        ),
        None,
    )
    return str((pause or {}).get("decision_id") or "") or None


def _persisted_dispatch_plane(run: Run, decision_id: str) -> Optional[str]:
    """Read the immutable HITL execution plane, rejecting corrupt values."""

    for checkpoint in reversed(list(run.checkpoints or [])):
        if (
            not isinstance(checkpoint, dict)
            or checkpoint.get("kind") != "hitl_resume_dispatch"
            or str(checkpoint.get("decision_id") or "") != decision_id
        ):
            continue
        plane = str(checkpoint.get("plane") or "")
        if plane in {"inline", "run_celery", "subflow_celery"}:
            return plane
        return _INVALID_PERSISTED_PLANE
    return None


def _outermost_paused_run(
    db: DBSession,
    *,
    target: Run,
    decision_id: str,
) -> Run:
    """Resolve copied in-process pauses to their single durable owner."""

    current = target
    owner = target
    visited = {target.id}
    while current.parent_run_id:
        parent = (
            db.query(Run)
            .filter(
                Run.id == current.parent_run_id,
                Run.workspace_id == target.workspace_id,
            )
            .first()
        )
        if parent is None or parent.id in visited:
            break
        visited.add(parent.id)
        current = parent
        if (
            parent.status == "hitl_pending"
            and _latest_pause_decision(parent) == decision_id
        ):
            owner = parent
    return owner


def _durable_dispatch_plane(db: DBSession, run: Run) -> str:
    """Return inline/run_celery/subflow_celery or fail closed to P4."""

    from app.services.run_engine.subflow_orchestration import (  # noqa: WPS433
        delegated_celery_claimed,
        delegated_celery_context,
    )

    decision_id = _latest_pause_decision(run)
    persisted = (
        _persisted_dispatch_plane(run, decision_id)
        if decision_id is not None
        else None
    )
    celery_claimed = delegated_celery_claimed(
        db,
        child=run,
        workspace_id=run.workspace_id,
    )
    if persisted == _INVALID_PERSISTED_PLANE:
        return _DEFERRED_TO_P4 if celery_claimed else _QUARANTINE_LOCAL
    if celery_claimed:
        context = delegated_celery_context(
            db,
            child=run,
            workspace_id=run.workspace_id,
        )
        if context is None or persisted not in {None, "subflow_celery"}:
            return _DEFERRED_TO_P4
        return "subflow_celery"
    if persisted == "subflow_celery":
        return _QUARANTINE_LOCAL
    if persisted == "inline":
        return "inline"
    if persisted == "run_celery":
        return (
            "run_celery"
            if settings.database_url.startswith("postgresql")
            else _QUARANTINE_LOCAL
        )
    system = (
        db.query(System)
        .filter(System.id == run.system_id, System.workspace_id == run.workspace_id)
        .first()
        if run.system_id
        else None
    )
    features = (
        system.settings.get("features")
        if system and isinstance(system.settings, dict)
        else None
    )
    if (
        settings.database_url.startswith("postgresql")
        and settings.enable_run_hitl_celery
        and isinstance(features, dict)
        and features.get("run_hitl_celery") is True
    ):
        return "run_celery"
    return "inline"


def _mark_p4_handoff(
    db: DBSession,
    decision: Decision,
    run: Run,
    *,
    now: datetime,
    reason: str,
) -> None:
    """Disarm the generic TTL after durably handing ownership to P4."""

    decision.expires_at = None
    already_recorded = any(
        isinstance(checkpoint, dict)
        and checkpoint.get("kind") == "gate_ttl_deferred_to_p4"
        and str(checkpoint.get("decision_id") or "") == decision.id
        for checkpoint in run.checkpoints or []
    )
    if not already_recorded:
        _append_run_checkpoint(
            db,
            run,
            {
                "kind": "gate_ttl_deferred_to_p4",
                "t": now.isoformat(),
                "decision_id": decision.id,
                "reason": reason,
            },
        )
    db.commit()


def _relock_and_mark_p4_handoff(
    db: DBSession,
    *,
    decision_id: str,
    run_id: str,
    workspace_id: str,
    now: datetime,
    reason: str,
) -> None:
    """Persist a handoff after a rolled-back transition crossed its deadline."""

    decision = (
        db.query(Decision)
        .filter(Decision.id == decision_id, Decision.status == "proposed")
        .populate_existing()
        .with_for_update()
        .first()
    )
    run = (
        db.query(Run)
        .filter(
            Run.id == run_id,
            Run.workspace_id == workspace_id,
            Run.status == "hitl_pending",
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if (
        decision is None
        or run is None
        or _latest_pause_decision(run) != decision_id
        or decision.workspace_id not in (None, workspace_id)
    ):
        db.rollback()
        return
    _mark_p4_handoff(
        db,
        decision,
        run,
        now=now,
        reason=reason,
    )


def _record_dispatch_plane(
    db: DBSession,
    run: Run,
    *,
    decision_id: str,
    plane: str,
    now: datetime,
) -> None:
    existing = next(
        (
            checkpoint
            for checkpoint in reversed(list(run.checkpoints or []))
            if isinstance(checkpoint, dict)
            and checkpoint.get("kind") == "hitl_resume_dispatch"
            and str(checkpoint.get("decision_id") or "") == decision_id
        ),
        None,
    )
    if existing is not None:
        if existing.get("plane") != plane:
            raise RuntimeError("persisted HITL dispatch plane conflicts with gate TTL")
        return
    _append_run_checkpoint(
        db,
        run,
        {
            "kind": "hitl_resume_dispatch",
            "t": now.isoformat(),
            "decision_id": decision_id,
            "plane": plane,
        },
    )


def _apply_expiry(
    db: DBSession,
    decision: Decision,
    run: Run,
    *,
    now: datetime,
) -> str:
    from app.services.decisions.state_machine import (  # noqa: WPS433
        accept,
        reject,
        InvalidTransition,
    )

    action = normalize_expiry_action(decision.expiry_action)
    actor = "system:gate_ttl"
    plane = _durable_dispatch_plane(db, run)
    delegation_deadline = _utc_naive(run.delegation_deadline_at)
    if plane == "subflow_celery" and delegation_deadline is None:
        delegation = (
            ((run.input_ref or {}).get("_delegation") or {})
            if isinstance(run.input_ref, dict)
            else {}
        )
        raw_deadline = delegation.get("deadline_at") if isinstance(delegation, dict) else None
        delegation_deadline = _utc_naive(raw_deadline)
    if plane == _QUARANTINE_LOCAL:
        from app.services.run_engine.hitl_watchdog import (  # noqa: WPS433
            quarantine_locked_hitl_owner,
        )

        return quarantine_locked_hitl_owner(
            db,
            run=run,
            decision=decision,
            now=now,
            reason="invalid_persisted_hitl_dispatch_plane",
        )
    handoff_reason = None
    if plane == _DEFERRED_TO_P4:
        handoff_reason = "invalid_delegation_contract"
    elif plane == "subflow_celery" and delegation_deadline is None:
        handoff_reason = "missing_delegation_deadline"
    elif (
        plane == "subflow_celery"
        and delegation_deadline is not None
        and now >= delegation_deadline
    ):
        handoff_reason = "delegation_deadline_reached"
    if handoff_reason is not None:
        # The immutable delegation deadline and malformed delegated envelopes
        # belong to the P4 watchdog. The generic TTL sweep must never race it
        # with an in-process continuation.
        _mark_p4_handoff(
            db,
            decision,
            run,
            now=now,
            reason=handoff_reason,
        )
        return _DEFERRED_TO_P4

    if action == EXPIRY_ESCALATE:
        _append_run_checkpoint(
            db,
            run,
            {
                "kind": "gate_ttl_escalated",
                "t": now.isoformat(),
                "decision_id": decision.id,
                "node_id": (decision.rationale or {}).get("node_id"),
                "expires_at": decision.expires_at.isoformat() if decision.expires_at else None,
            },
        )
        decision.expires_at = None
        note = f"\n[gate_ttl] escalated at {now.isoformat()}"
        decision.notes = (decision.notes or "") + note
        db.commit()
        logger.info(
            "gate_ttl: escalated",
            decision_id=decision.id,
            run_id=run.id,
        )
        return EXPIRY_ESCALATE

    try:
        if action == EXPIRY_APPROVE:
            accept(
                db,
                decision,
                actor=actor,
                note="Auto-approved by gate TTL expiry",
                commit=False,
            )
        else:
            reject(
                db,
                decision,
                actor=actor,
                note="Auto-rejected by gate TTL expiry",
                commit=False,
            )
            action = EXPIRY_REJECT
    except InvalidTransition as exc:
        logger.warning(
            "gate_ttl: transition failed",
            decision_id=decision.id,
            error_type=type(exc).__name__,
        )
        decision.expires_at = None
        db.commit()
        return "skipped"

    if (
        plane == "subflow_celery"
        and delegation_deadline is not None
        and (_utc_naive(decision.approved_at) or now) > delegation_deadline
    ):
        decision_id = decision.id
        run_id = run.id
        workspace_id = str(run.workspace_id)
        db.rollback()
        _relock_and_mark_p4_handoff(
            db,
            decision_id=decision_id,
            run_id=run_id,
            workspace_id=workspace_id,
            now=datetime.utcnow(),
            reason="delegation_deadline_crossed_during_transition",
        )
        return _DEFERRED_TO_P4

    dispatch_event = None
    _record_dispatch_plane(
        db,
        run,
        decision_id=decision.id,
        plane=plane,
        now=now,
    )
    if plane in {"subflow_celery", "run_celery"}:
        from app.services.run_engine.dispatch_outbox import (  # noqa: WPS433
            RUN_HITL_RESUME,
            SUBFLOW_HITL_RESUME,
            enqueue_dispatch,
        )

        dispatch_event = enqueue_dispatch(
            db,
            event_type=(
                SUBFLOW_HITL_RESUME if plane == "subflow_celery" else RUN_HITL_RESUME
            ),
            workspace_id=str(run.workspace_id),
            run_id=run.id,
            decision_id=decision.id,
        )

    _append_run_checkpoint(
        db,
        run,
        {
            "kind": "gate_ttl_expired",
            "t": now.isoformat(),
            "decision_id": decision.id,
            "expiry_action": action,
        },
    )
    db.commit()

    if dispatch_event is not None:
        try:
            from app.services.run_engine.dispatch_outbox import (  # noqa: WPS433
                reconcile_dispatch_outbox,
            )

            reconcile_dispatch_outbox(
                batch_size=50,
                lease_seconds=settings.p4_maintenance_lease_seconds,
            )
        except Exception as exc:  # persisted event remains authoritative
            logger.warning(
                "gate_ttl: durable resume reconciliation deferred",
                run_id=run.id,
                decision_id=decision.id,
                error_type=type(exc).__name__,
            )
    else:
        try:
            _resume_paused_run(run.id, decision.id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "gate_ttl: resume failed",
                run_id=run.id,
                decision_id=decision.id,
                error_type=type(exc).__name__,
            )
    return action


def sweep_expired_gates(*, limit: int = 50) -> Dict[str, Any]:
    """Apply expiry_action on proposed HITL decisions past ``expires_at``."""
    applied: List[Dict[str, str]] = []
    deferred = 0
    skipped = 0
    errors = 0
    limit = max(1, min(int(limit), 1000))

    try:
        selection_now = datetime.utcnow()
        with SessionLocal() as selection_db:
            candidate_ids = [
                row[0]
                for row in (
                    selection_db.query(Decision.id)
                    .filter(
                        Decision.status == "proposed",
                        Decision.kind == "hitl_approval",
                        Decision.expires_at.isnot(None),
                        Decision.expires_at <= selection_now,
                    )
                    .order_by(Decision.expires_at.asc(), Decision.id.asc())
                    .limit(limit)
                    .all()
                )
            ]
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "gate_ttl: candidate selection failed",
            error_type=type(exc).__name__,
        )
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "swept": 0,
            "deferred_to_p4": 0,
            "skipped": 0,
            "errors": 1,
            "gates": [],
        }

    for decision_id in candidate_ids:
        with SessionLocal() as db:
            try:
                now = datetime.utcnow()
                decision_query = db.query(Decision).filter(
                    Decision.id == decision_id,
                    Decision.status == "proposed",
                    Decision.kind == "hitl_approval",
                    Decision.expires_at.isnot(None),
                    Decision.expires_at <= now,
                )
                dialect = db.get_bind().dialect.name
                if dialect == "postgresql":
                    decision = (
                        decision_query.populate_existing()
                        .with_for_update(skip_locked=True)
                        .first()
                    )
                elif dialect == "sqlite":
                    # SQLite is used only by deterministic unit tests and has
                    # no row-level lock syntax. Never turn a PostgreSQL lock or
                    # transport failure into this unlocked compatibility path.
                    decision = decision_query.populate_existing().first()
                else:
                    raise RuntimeError(
                        f"gate TTL does not support database dialect {dialect!r}"
                    )
                if decision is None:
                    db.rollback()
                    skipped += 1
                    continue
                if decision.scope != "run" or not decision.target_id:
                    decision.expires_at = None
                    db.commit()
                    skipped += 1
                    continue

                target_query = db.query(Run).filter(Run.id == decision.target_id)
                if decision.workspace_id is not None:
                    target_query = target_query.filter(
                        Run.workspace_id == decision.workspace_id,
                    )
                target = target_query.first()
                if target is None or target.status != "hitl_pending":
                    # Stale or cross-workspace TTL: disarm it without touching
                    # any Run or transitioning the Decision.
                    decision.expires_at = None
                    db.commit()
                    skipped += 1
                    continue
                owner_candidate = _outermost_paused_run(
                    db,
                    target=target,
                    decision_id=decision.id,
                )
                owner = (
                    db.query(Run)
                    .filter(
                        Run.id == owner_candidate.id,
                        Run.workspace_id == target.workspace_id,
                    )
                    .populate_existing()
                    .with_for_update()
                    .first()
                )
                if (
                    owner is None
                    or owner.status != "hitl_pending"
                    or _latest_pause_decision(owner) != decision.id
                    or decision.workspace_id not in (None, owner.workspace_id)
                ):
                    decision.expires_at = None
                    db.commit()
                    skipped += 1
                    continue

                action = _apply_expiry(
                    db,
                    decision,
                    owner,
                    # Re-read the clock only after Decision and Run ownership
                    # have been serialised. This closes the lock-wait deadline
                    # race with human resolution and the P4 watchdog.
                    now=datetime.utcnow(),
                )
                if action == _DEFERRED_TO_P4:
                    deferred += 1
                    continue
                applied.append(
                    {
                        "decision_id": decision.id,
                        "run_id": owner.id,
                        "action": action,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                errors += 1
                logger.error(
                    "gate_ttl: candidate sweep failed",
                    decision_id=decision_id,
                    error_type=type(exc).__name__,
                )

    return {
        "status": "ok",
        "swept": len(applied),
        "deferred_to_p4": deferred,
        "skipped": skipped,
        "errors": errors,
        "gates": applied,
    }
