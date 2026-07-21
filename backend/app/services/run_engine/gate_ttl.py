"""Gate TTL helpers + expired-gate sweep for HITL / membrane HOLD pauses.

``scheduler_tick`` calls :func:`sweep_expired_gates` every ~60s. Actions:

* ``reject`` / ``approve`` — transition the Decision, resume the paused Run.
* ``escalate`` — append a checkpoint reminder, clear ``expires_at`` so the
  gate stays open for a human (no hot-loop on every tick).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.decision import Decision
from app.models.run import Run

logger = get_logger(__name__)

EXPIRY_REJECT = "reject"
EXPIRY_APPROVE = "approve"
EXPIRY_ESCALATE = "escalate"
_VALID_ACTIONS = frozenset({EXPIRY_REJECT, EXPIRY_APPROVE, EXPIRY_ESCALATE})


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
            accept(db, decision, actor=actor, note="Auto-approved by gate TTL expiry")
        else:
            reject(db, decision, actor=actor, note="Auto-rejected by gate TTL expiry")
            action = EXPIRY_REJECT
    except InvalidTransition as exc:
        logger.warning(
            "gate_ttl: transition failed",
            decision_id=decision.id,
            error=str(exc),
        )
        decision.expires_at = None
        db.commit()
        return "skipped"

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

    try:
        _resume_paused_run(run.id, decision.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "gate_ttl: resume failed",
            run_id=run.id,
            decision_id=decision.id,
            error=str(exc),
        )
    return action


def sweep_expired_gates(*, limit: int = 50) -> Dict[str, Any]:
    """Apply expiry_action on proposed HITL decisions past ``expires_at``."""
    now = datetime.utcnow()
    applied: List[Dict[str, str]] = []

    db = SessionLocal()
    try:
        query = (
            db.query(Decision)
            .filter(
                Decision.status == "proposed",
                Decision.kind == "hitl_approval",
                Decision.expires_at.isnot(None),
                Decision.expires_at <= now,
            )
            .order_by(Decision.expires_at.asc())
            .limit(limit)
        )
        try:
            rows = query.with_for_update(skip_locked=True).all()
        except Exception:  # noqa: BLE001 — SQLite tests lack SKIP LOCKED
            rows = query.all()

        for decision in rows:
            run = None
            if decision.scope == "run" and decision.target_id:
                run = db.query(Run).filter(Run.id == decision.target_id).first()
            if run is None or run.status != "hitl_pending":
                # Stale TTL on a settled run — disarm so we don't re-scan forever.
                decision.expires_at = None
                db.commit()
                continue
            action = _apply_expiry(db, decision, run, now=now)
            applied.append(
                {
                    "decision_id": decision.id,
                    "run_id": run.id,
                    "action": action,
                }
            )
        return {"status": "ok", "swept": len(applied), "gates": applied}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("gate_ttl: sweep failed", error=str(exc))
        return {"status": "error", "error": str(exc), "swept": len(applied)}
    finally:
        db.close()
