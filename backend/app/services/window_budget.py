"""One durable reservation ledger for every paid stage of a service window.

No authority comes from Run input JSON. Admission resolves the live fenced
attempt in the database. Late settlement may record an old attempt's real
spend, but can never authorize another dispatch. Unknown usage retains the
reservation. All mutating helpers own and commit their short transaction.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from app.models.run import Run
from app.models.service_contract import ServiceAttempt, ServiceWindow
from app.models.workspace_job import WorkspaceJob
from app.services.governed_assets import GovernanceError

KIND = "service_window_budget_v1"
UNITS = ("cost", "tokens", "seconds")
MAX_ENTRIES = 10000


def _now():
    return datetime.utcnow()


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _job_id(workspace_id, window_id):
    return str(uuid5(NAMESPACE_URL, f"agentium:service-budget:{workspace_id}:{window_id}"))


def _scope(db, ctx, *, active=True, lock=False, allow_stopped_run=False):
    run = (
        db.query(Run)
        .filter_by(id=ctx.get("run_id"), workspace_id=ctx.get("workspace_id"))
        .populate_existing()
        .first()
    )
    if run is None:
        if ctx.get("run_id"):
            raise GovernanceError("SERVICE_BUDGET_RUN_INVALID", 403)
        return None
    attempt = (
        db.query(ServiceAttempt)
        .filter_by(workspace_id=run.workspace_id, run_id=run.id)
        .order_by(ServiceAttempt.fence.desc())
        .populate_existing()
        .first()
    )
    if attempt is None:
        if (run.input_ref or {}).get("service_window_id"):
            raise GovernanceError("SERVICE_BUDGET_ATTEMPT_REQUIRED", 403)
        return None
    query = db.query(ServiceWindow).filter_by(id=attempt.window_id, workspace_id=run.workspace_id)
    window = (query.with_for_update() if lock else query).populate_existing().one()
    if run.system_id != window.system_id:
        raise GovernanceError("SERVICE_BUDGET_RUN_INVALID", 403)
    if active and (
        (not allow_stopped_run and run.status in {"failed", "cancelled", "completed"})
        or attempt.status != "running"
        or attempt.completed_at is not None
        or window.status != "running"
        or window.fence != attempt.fence
        or not window.lease_token
        or not secrets.compare_digest(window.lease_token, attempt.lease_token)
        or window.lease_expires_at is None
        or window.lease_expires_at <= _now()
        or window.deadline_at <= _now()
    ):
        raise GovernanceError("SERVICE_STALE_LEASE")
    return window, attempt, run


def _definition(db, window):
    from app.services.service_promises import get_contract

    return get_contract(db, window.workspace_id, window.contract_id).definition_json["budget"]


def assert_active(ctx):
    from app.db.base import SessionLocal

    with SessionLocal() as db:
        scope = _scope(db, ctx)
        return scope[0].id if scope else None


def guard_checkpoint(db, ctx):
    """Caller holds the window row lock until its checkpoint commit/rollback."""
    return _scope(db, ctx, lock=True, allow_stopped_run=True)


def limits(ctx, stage):
    """Frozen stage envelope, not remaining balance; the reservation checks that."""
    from app.db.base import SessionLocal

    with SessionLocal() as db:
        scope = _scope(db, ctx)
        if scope is None:
            return None
        window, _, _ = scope
        budget = _definition(db, window)
        stages = budget.get("stages", {})
        if stages and stage not in stages:
            raise GovernanceError("SERVICE_STAGE_NOT_ALLOCATED")
        return {
            "window_id": window.id,
            **{
                f"max_{u}": min(budget[f"max_{u}"], stages.get(stage, budget)[f"max_{u}"])
                for u in UNITS
            },
        }


def _validate(cost, tokens, seconds, *, nullable=False):
    for unit, value in zip(UNITS, (cost, tokens, seconds), strict=True):
        if nullable and value is None:
            continue
        if (
            (type(value) is not int if unit == "tokens" else type(value) not in {float, int})
            or not math.isfinite(value)
            or value < 0
        ):
            raise GovernanceError("SERVICE_USAGE_INVALID", 422)


def _engaged(entry, unit):
    known = entry.get("measured_" + unit)
    if entry.get("complete_" + unit) and known is not None:
        return Decimal(str(known))
    return max(Decimal(str(entry["reserved_" + unit])), Decimal(str(known or 0)))


def _summary(entries, budget):
    result = {"entries": len(entries), "over_budget": False}
    for unit in UNITS:
        known = [e["measured_" + unit] for e in entries if e.get("measured_" + unit) is not None]
        complete = bool(entries) and all(e.get("complete_" + unit) for e in entries)
        engaged = sum((_engaged(e, unit) for e in entries), Decimal(0))
        cast = int if unit == "tokens" else float
        result["engaged_" + unit] = cast(engaged)
        result["reserved_" + unit] = cast(sum(Decimal(str(e["reserved_" + unit])) for e in entries))
        result["known_" + unit] = cast(sum(Decimal(str(v)) for v in known)) if known else None
        result["measured_" + unit] = result["known_" + unit] if complete else None
        result[unit + "_coverage"] = (
            "measured" if complete else "partial" if known else "unavailable"
        )
        result["over_budget"] |= engaged > Decimal(str(budget["max_" + unit]))
    for stage, allocation in budget.get("stages", {}).items():
        for unit in UNITS:
            result["over_budget"] |= sum(
                (_engaged(e, unit) for e in entries if e["stage"] == stage), Decimal(0)
            ) > Decimal(str(allocation["max_" + unit]))
    return result


def summary(db, workspace_id, window_id, *, attempt_id=None, run_id=None):
    """Canonical complete totals are nullable; known_* is only a partial subtotal."""
    window = db.query(ServiceWindow).filter_by(id=window_id, workspace_id=workspace_id).first()
    if window is None:
        raise GovernanceError("SERVICE_WINDOW_NOT_FOUND", 404)
    job = db.get(WorkspaceJob, _job_id(workspace_id, window_id), populate_existing=True)
    if job is None:
        return None
    entries = list(job.result.get("entries", {}).values())
    if attempt_id is not None:
        entries = [e for e in entries if e["attempt_id"] == attempt_id]
    if run_id is not None:
        entries = [e for e in entries if e["run_id"] == run_id]
    return {
        "ledger_id": job.id,
        "window_id": window.id,
        "measurement_conflict": job.result.get("measurement_conflict", False),
        **_summary(entries, _definition(db, window)),
    }


@dataclass(frozen=True)
class Reservation:
    workspace_id: str
    window_id: str
    entry_key: str
    token: str = field(repr=False)
    run_id: str
    fence: int


def reserve(ctx, *, stage, key, cost, tokens, seconds, replayable=False):
    """Reserve before dispatch. Only a gateway with a stable idempotency key may replay."""
    from app.db.base import SessionLocal
    from app.services.llm_dataset_labeling import LabelingError, _workspace_lock

    _validate(cost, tokens, seconds)
    if stage not in {"narration", "judge"} or not isinstance(key, str) or not 1 <= len(key) <= 300:
        raise GovernanceError("SERVICE_BUDGET_KEY_INVALID", 422)
    with SessionLocal() as db:
        scope = _scope(db, ctx)
        if scope is None:
            return None
        window_id = scope[0].id
        db.rollback()
        try:
            with _workspace_lock(db.get_bind(), "service-budget:" + window_id):
                window, attempt, run = _scope(db, ctx, lock=True)
                budget = _definition(db, window)
                job = db.get(
                    WorkspaceJob, _job_id(window.workspace_id, window.id), populate_existing=True
                )
                if job is None:
                    job = WorkspaceJob(
                        id=_job_id(window.workspace_id, window.id),
                        workspace_id=window.workspace_id,
                        system_id=window.system_id,
                        kind=KIND,
                        title="Service window budget",
                        status="running",
                        input_ref={
                            "window_id": window.id,
                            "contract_id": window.contract_id,
                            "budget": budget,
                        },
                        result={"entries": {}},
                    )
                    db.add(job)
                if job.input_ref.get("budget") != budget:
                    raise GovernanceError("SERVICE_BUDGET_CONTRACT_CHANGED")
                state = copy.deepcopy(job.result)
                if state.get("measurement_conflict"):
                    raise GovernanceError("SERVICE_BUDGET_RECONCILIATION_REQUIRED")
                entry_key = _hash([stage, key])
                fingerprint = _hash([stage, key, cost, tokens, seconds])
                entry = state["entries"].get(entry_key)
                if entry:
                    if entry["fingerprint"] != fingerprint:
                        raise GovernanceError("SERVICE_BUDGET_RESERVATION_CHANGED")
                    if not replayable:
                        raise GovernanceError("SERVICE_BUDGET_RECONCILIATION_REQUIRED")
                    return Reservation(
                        window.workspace_id,
                        window.id,
                        entry_key,
                        entry["token"],
                        entry["run_id"],
                        entry["fence"],
                    )
                if len(state["entries"]) >= MAX_ENTRIES:
                    raise GovernanceError("SERVICE_BUDGET_ENTRY_LIMIT")
                stages = budget.get("stages", {})
                if stages and stage not in stages:
                    raise GovernanceError("SERVICE_STAGE_NOT_ALLOCATED")
                entry = {
                    "stage": stage,
                    "fingerprint": fingerprint,
                    "token": secrets.token_hex(32),
                    "attempt_id": attempt.id,
                    "run_id": run.id,
                    "fence": attempt.fence,
                    "created_at": _now().isoformat(),
                    "final": False,
                    **{
                        f"reserved_{u}": v
                        for u, v in zip(UNITS, (cost, tokens, seconds), strict=True)
                    },
                    **{f"measured_{u}": None for u in UNITS},
                    **{f"complete_{u}": False for u in UNITS},
                }
                state["entries"][entry_key] = entry
                if _summary(list(state["entries"].values()), budget)["over_budget"]:
                    raise GovernanceError("SERVICE_BUDGET_EXHAUSTED")
                job.result, job.updated_at = state, _now()
                db.commit()
                return Reservation(
                    window.workspace_id,
                    window.id,
                    entry_key,
                    entry["token"],
                    entry["run_id"],
                    entry["fence"],
                )
        except LabelingError:
            raise GovernanceError("SERVICE_BUDGET_BUSY") from None


def settle(reservation, *, cost=None, tokens=None, seconds=None, final=True):
    """Record even late responses against their original reservation, never release unknowns."""
    from app.db.base import SessionLocal
    from app.services.llm_dataset_labeling import LabelingError, _workspace_lock

    if reservation is None:
        return None
    _validate(cost, tokens, seconds, nullable=True)
    with SessionLocal() as db:
        try:
            with _workspace_lock(db.get_bind(), "service-budget:" + reservation.window_id):
                window = (
                    db.query(ServiceWindow)
                    .filter_by(id=reservation.window_id, workspace_id=reservation.workspace_id)
                    .with_for_update()
                    .one()
                )
                job = db.get(
                    WorkspaceJob,
                    _job_id(reservation.workspace_id, reservation.window_id),
                    populate_existing=True,
                )
                state = copy.deepcopy(job.result) if job else {}
                entry = state.get("entries", {}).get(reservation.entry_key)
                if (
                    not entry
                    or not secrets.compare_digest(entry["token"], reservation.token)
                    or entry["run_id"] != reservation.run_id
                    or entry["fence"] != reservation.fence
                ):
                    raise GovernanceError("SERVICE_BUDGET_RESERVATION_INVALID", 403)
                for unit, value in zip(UNITS, (cost, tokens, seconds), strict=True):
                    if value is None:
                        continue
                    previous = entry["measured_" + unit]
                    if unit == "seconds" and entry["complete_seconds"]:
                        # An idempotent gateway replay does not reopen the
                        # already measured remote execution interval.
                        continue
                    if previous is not None and (value < previous):
                        raise GovernanceError("SERVICE_BUDGET_MEASUREMENT_CHANGED")
                    if previous is not None and entry["complete_" + unit] and value != previous:
                        # Keep a provider's increased final bill even when its
                        # protocol is inconsistent; never erase observed spend.
                        state["measurement_conflict"] = True
                    entry["measured_" + unit] = value
                    entry["complete_" + unit] = entry["complete_" + unit] or bool(final)
                entry["final"] = entry["final"] or bool(final)
                job.result, job.updated_at = state, _now()
                result = {
                    "ledger_id": job.id,
                    "window_id": window.id,
                    "measurement_conflict": state.get("measurement_conflict", False),
                    **_summary(list(state["entries"].values()), _definition(db, window)),
                }
                db.commit()
                return result
        except LabelingError:
            raise GovernanceError("SERVICE_BUDGET_BUSY") from None
