"""Cron schedule tick + gate TTL sweep.

Driven by Celery beat every 60s (``agentium.scheduler_tick``). Uses croniter
to advance ``next_fire_at``, then sweeps expired HITL / membrane HOLD gates
(Phase 4). Intentionally separate from event ``emit_event``: schedules are
table-driven, not flow-registry-driven.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.run import Run
from app.models.run_schedule import RunSchedule
from app.models.system import System

logger = get_logger(__name__)


def validate_cron_expr(cron_expr: str, timezone_name: str = "UTC") -> datetime:
    """Validate cron + timezone; return the next fire instant (UTC-naive)."""
    next_at = compute_next_fire_at(cron_expr, timezone_name, from_dt=datetime.now(timezone.utc))
    if next_at is None:
        raise ValueError(f"invalid cron expression or timezone: {cron_expr!r} / {timezone_name!r}")
    return next_at


def compute_next_fire_at(
    cron_expr: str,
    timezone_name: str = "UTC",
    *,
    from_dt: Optional[datetime] = None,
) -> Optional[datetime]:
    """Return the next fire time as a UTC-naive datetime for DB storage."""
    try:
        from croniter import croniter  # noqa: WPS433
    except ImportError:  # pragma: no cover — dependency declared in requirements
        logger.error("scheduler: croniter not installed")
        return None

    tz_name = (timezone_name or "UTC").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return None

    base = from_dt or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    local_base = base.astimezone(tz)

    try:
        itr = croniter(cron_expr, local_base)
        nxt_local = itr.get_next(datetime)
    except (ValueError, KeyError, TypeError):
        return None

    if nxt_local.tzinfo is None:
        nxt_local = nxt_local.replace(tzinfo=tz)
    return nxt_local.astimezone(timezone.utc).replace(tzinfo=None)


def serialize_schedule(row: RunSchedule) -> Dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "system_id": row.system_id,
        "name": row.name,
        "cron_expr": row.cron_expr,
        "timezone": row.timezone,
        "input_payload": row.input_payload or {},
        "enabled": bool(row.enabled),
        "next_fire_at": row.next_fire_at.isoformat() if row.next_fire_at else None,
        "last_run_id": row.last_run_id,
        "last_fired_at": row.last_fired_at.isoformat() if row.last_fired_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _dispatch_run(run_id: str) -> None:
    from app.services.run_engine.engine import schedule_run  # noqa: WPS433

    schedule_run(run_id)


def _fire_schedule(db: DBSession, sched: RunSchedule, *, now: datetime) -> Optional[str]:
    system = db.query(System).filter(System.id == sched.system_id).first()
    if system is None or system.status != "active":
        logger.info(
            "scheduler: skip inactive/missing system",
            schedule_id=sched.id,
            system_id=sched.system_id,
        )
        # Still advance next_fire_at so a retired system does not hot-loop.
        nxt = compute_next_fire_at(sched.cron_expr, sched.timezone, from_dt=now)
        sched.next_fire_at = nxt
        return None

    run = Run(
        id=str(uuid4()),
        workspace_id=sched.workspace_id,
        system_id=sched.system_id,
        input_ref={
            **(sched.input_payload if isinstance(sched.input_payload, dict) else {}),
            "_schedule": {
                "schedule_id": sched.id,
                "cron_expr": sched.cron_expr,
                "timezone": sched.timezone,
                "fired_at": now.isoformat(),
            },
        },
        status="pending",
        trigger="scheduler",
        checkpoints=[
            {
                "kind": "schedule_fired",
                "t": now.isoformat(),
                "schedule_id": sched.id,
                "cron_expr": sched.cron_expr,
            }
        ],
    )
    db.add(run)
    db.flush()

    sched.last_run_id = run.id
    sched.last_fired_at = now
    nxt = compute_next_fire_at(sched.cron_expr, sched.timezone, from_dt=now)
    sched.next_fire_at = nxt
    db.commit()

    try:
        _dispatch_run(run.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "scheduler: dispatch failed",
            schedule_id=sched.id,
            run_id=run.id,
            error=str(exc),
        )
    return run.id


def scheduler_tick(*, limit: int = 50) -> Dict[str, Any]:
    """Fire due schedules and sweep expired HITL / membrane gates.

    Returns a compact summary for the Celery result. Gate TTL reuse of this
    beat task avoids a second periodic job (Phase 4).
    """
    now = datetime.utcnow()
    fired: List[Dict[str, str]] = []
    skipped = 0

    db = SessionLocal()
    try:
        # FOR UPDATE SKIP LOCKED avoids double-fire when multiple beat/workers race.
        query = (
            db.query(RunSchedule)
            .filter(RunSchedule.enabled.is_(True), RunSchedule.next_fire_at.isnot(None), RunSchedule.next_fire_at <= now)
            .order_by(RunSchedule.next_fire_at.asc())
            .limit(limit)
        )
        try:
            due = query.with_for_update(skip_locked=True).all()
        except Exception:  # noqa: BLE001 — SQLite tests lack SKIP LOCKED
            due = query.all()

        for sched in due:
            run_id = _fire_schedule(db, sched, now=now)
            if run_id:
                fired.append({"schedule_id": sched.id, "run_id": run_id})
            else:
                skipped += 1
                db.commit()
        schedule_summary = {
            "status": "ok",
            "fired": len(fired),
            "skipped": skipped,
            "runs": fired,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("scheduler: tick failed", error=str(exc))
        schedule_summary = {"status": "error", "error": str(exc), "fired": len(fired)}
    finally:
        db.close()

    # Gate TTL sweep runs even when the cron half errors — independent concern.
    try:
        from app.services.run_engine.gate_ttl import sweep_expired_gates  # noqa: WPS433

        gate_summary = sweep_expired_gates(limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("scheduler: gate ttl sweep failed", error=str(exc))
        gate_summary = {"status": "error", "error": str(exc), "swept": 0}

    return {**schedule_summary, "gates": gate_summary}
