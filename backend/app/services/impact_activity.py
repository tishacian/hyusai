"""Workspace-scoped execution activity for configurable Impact blocks.

Counts attempts, including failures, without inferring business outcomes or
human time from technical execution. Authoring previews are excluded.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from math import isfinite
from statistics import median

from fastapi import HTTPException
from sqlalchemy import func

from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.services.projection_integrity import invocation_cost_is_measured
from app.services.run_access import (
    readable_run_page,
    readable_skill_invocations_for_runs,
)
from app.services.run_engine.execution_contract import NON_PUBLISHED_EXECUTION_SURFACES
from app.services.system_access import readable_systems

ACTIVITY_LIMIT = 2000
WINDOWS = {"7d": 7, "30d": 30, "90d": 90}
TERMINAL = {"completed", "failed", "cancelled"}


def activity_systems(db, workspace, user):
    systems = readable_systems(
        db,
        systems=db.query(System)
        .filter(System.workspace_id == workspace.id)
        .order_by(System.name, System.id)
        .all(),
        workspace=workspace,
        user=user,
    )
    return [{"id": system.id, "name": system.name} for system in systems]


def _seconds(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value / 1000 if isfinite(value) and value >= 0 else None


def summarize_activity(runs, invocations, *, complete_ledger_runs):
    calls_by_run = defaultdict(list)
    for call in invocations:
        calls_by_run[call.run_id].append(call)
    statuses = Counter(run.status for run in runs)
    buckets = defaultdict(Counter)
    prices = defaultdict(Decimal)
    priced = 0
    durations = []
    entries = []
    for run in runs:
        calls = calls_by_run[run.id]
        seconds = [_seconds(call.latency_ms) for call in calls]
        # A hidden, pending or missing invocation cannot create a short median.
        duration = (
            sum(seconds)
            if run.id in complete_ledger_runs
            and run.status in TERMINAL
            and seconds
            and all(value is not None for value in seconds)
            and all(call.status in TERMINAL for call in calls)
            else None
        )
        if duration is not None:
            durations.append(duration)
        for call in calls:
            metrics = call.metrics if isinstance(call.metrics, Mapping) else {}
            raw = metrics.get("cost_evidence")
            evidence = raw if isinstance(raw, Mapping) else {}
            currency = evidence.get("currency")
            if (
                invocation_cost_is_measured(call)
                and call.status in TERMINAL
                and evidence.get("state") in {"measured", "calculated"}
                and isinstance(currency, str)
                and len(currency) == 3
                and currency.isascii()
                and currency.isalpha()
                and currency.isupper()
            ):
                prices[currency] += Decimal(str(call.cost))
                priced += 1
        buckets[run.started_at.date().isoformat()][run.status] += 1
        entries.append(
            {
                "id": run.id,
                "system_id": run.system_id,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "technical_seconds": duration,
            }
        )
    return {
        "counts": {
            "attempts": len(runs),
            "completed": statuses["completed"],
            "failed": statuses["failed"],
            "cancelled": statuses["cancelled"],
            "pending": sum(v for k, v in statuses.items() if k not in TERMINAL),
            "invocations": len(invocations),
        },
        "buckets": [
            {
                "date": day,
                "attempts": sum(counts.values()),
                "completed": counts["completed"],
                "failed": counts["failed"],
                "cancelled": counts["cancelled"],
                "pending": sum(v for k, v in counts.items() if k not in TERMINAL),
            }
            for day, counts in sorted(buckets.items())
        ],
        "costs": {
            "state": "available"
            if priced and priced == len(invocations)
            else "partial"
            if priced
            else "not_measured",
            "by_currency": {code: str(value) for code, value in sorted(prices.items())},
            "priced_invocations": priced,
            "unpriced_invocations": len(invocations) - priced,
        },
        "median_technical_seconds": median(durations) if durations else None,
        "technical_sample_count": len(durations),
        "runs": entries[:50],
    }


def execution_activity(db, workspace, user, *, window, system_id=None):
    systems = activity_systems(db, workspace, user)
    system_ids = [system["id"] for system in systems]
    if system_id:
        if system_id not in system_ids:
            raise HTTPException(status_code=404, detail={"code": "SYSTEM_NOT_FOUND"})
        system_ids = [system_id]
    now = datetime.utcnow()
    start = (now - timedelta(days=WINDOWS[window] - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    query = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            Run.system_id.in_(system_ids),
            Run.started_at >= start,
            Run.started_at <= now,
            func.coalesce(Run.execution_surface, "").notin_(NON_PUBLISHED_EXECUTION_SURFACES),
            func.coalesce(Run.trigger, "").notin_(NON_PUBLISHED_EXECUTION_SURFACES),
        )
        .order_by(Run.started_at.desc(), Run.id.asc())
    )
    page = readable_run_page(
        db, query=query, limit=ACTIVITY_LIMIT + 1, user=user, workspace=workspace
    )
    limited = len(page) > ACTIVITY_LIMIT
    runs = page[:ACTIVITY_LIMIT]
    calls = (
        db.query(SkillInvocation).filter(SkillInvocation.run_id.in_([run.id for run in runs])).all()
        if runs
        else []
    )
    visible_calls = readable_skill_invocations_for_runs(
        db, invocations=calls, runs=runs, user=user, workspace=workspace
    )
    raw_counts = Counter(call.run_id for call in calls)
    visible_counts = Counter(call.run_id for call in visible_calls)
    complete = {run.id for run in runs if raw_counts[run.id] == visible_counts[run.id]}
    return {
        "window": window,
        "from": start.isoformat(),
        "to": now.isoformat(),
        "system_id": system_id,
        "limited": limited,
        "limit": ACTIVITY_LIMIT,
        "authorization_scope": {
            "counts_include_only_readable_runs": True,
            "invocations_include_only_readable_invocations": True,
        },
        **summarize_activity(runs, visible_calls, complete_ledger_runs=complete),
    }
