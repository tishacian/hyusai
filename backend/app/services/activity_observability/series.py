"""Authorized observation series. Native expenses are never summed with parents.

The API uses a repeatable-read transaction on PostgreSQL. Bounded authorization
batches precede aggregation; pagination and missing evidence never fabricate zero.
"""

from array import array
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from math import ceil

from fastapi import HTTPException
from sqlalchemy import and_, func, or_

from app.models.activity import Activity, parse_instant
from app.models.compute_run import ComputeRun
from app.models.run import SkillInvocation
from app.services.observation_window import observation_anchor

from . import queries
from .execution_metadata import invocation_cost
from .filters import parse_status_filter
from .projection import KINDS, TERMINAL, iso, number

# The native reader's date parser; the typed activities.finished_at uses it too.
_date = parse_instant


def _summary():
    return {
        "total": 0,
        "by_status": Counter(),
        "by_kind": Counter(),
        "durations": defaultdict(lambda: {"eligible": 0, "values": array("d")}),
        "costs": defaultdict(lambda: {"known_amount": 0.0, "known_count": 0}),
        "cost_unknown_count": 0,
        "cost_known_count": 0,
        "snapshot_only_count": 0,
    }


def _public(summary):
    durations = {}
    for kind, values in summary["durations"].items():
        measured = sorted(values["values"])
        durations[kind] = {
            "eligible_count": values["eligible"],
            "measured_count": len(measured),
            "p50_ms": measured[ceil(len(measured) * 0.5) - 1] if measured else None,
            "p95_ms": measured[ceil(len(measured) * 0.95) - 1] if measured else None,
        }
    costs = [
        {"basis": basis, "currency": currency, **value}
        for (basis, currency), value in sorted(summary["costs"].items())
    ]
    return {
        "total": summary["total"],
        "by_status": dict(summary["by_status"]),
        "by_kind": dict(summary["by_kind"]),
        "durations": durations,
        "costs": costs,
        "cost_known_count": summary["cost_known_count"],
        "cost_unknown_count": summary["cost_unknown_count"],
        "cost_complete": summary["cost_unknown_count"] == 0 and summary["total"] > 0,
        "snapshot_only_count": summary["snapshot_only_count"],
    }


def _cost_sources(db, rows):
    invocation_ids = [row.native_id for row in rows if row.kind == "skill_invocation"]
    compute_ids = [row.native_id for row in rows if row.kind == "compute_run"]
    sources = {}
    if invocation_ids:
        for value in (
            db.query(
                SkillInvocation.id,
                SkillInvocation.cost,
                SkillInvocation.provider_cost_usd,
                SkillInvocation.cost_measured,
                SkillInvocation.metrics,
            )
            .filter(SkillInvocation.id.in_(invocation_ids))
            .all()
        ):
            evidence = invocation_cost(
                cost=value.cost,
                provider_cost_usd=value.provider_cost_usd,
                cost_measured=value.cost_measured,
                metrics=value.metrics,
            )
            if evidence["cost_known"]:
                sources[("skill_invocation", value.id)] = (
                    evidence["cost_basis"],
                    evidence["currency"],
                    evidence["cost_amount"],
                )
    if compute_ids:
        for value in (
            db.query(ComputeRun.id, ComputeRun.cost_usd)
            .filter(ComputeRun.id.in_(compute_ids))
            .all()
        ):
            amount = number(value.cost_usd)
            if amount is not None:
                sources[("compute_run", value.id)] = ("infrastructure_allocation", "USD", amount)
    return sources


def _add(summary, row, expense, metric):
    summary["total"] += 1
    summary["by_status"][row.status] += 1
    summary["by_kind"][row.kind] += 1
    summary["snapshot_only_count"] += row.origin == "snapshot_only"
    if row.status in TERMINAL:
        durations = summary["durations"][row.kind]
        durations["eligible"] += 1
        duration = number((row.snapshot.get("measurements") or {}).get("duration_ms"))
        if duration is not None:
            durations["values"].append(duration)
    if metric == "cost":
        if expense is None:
            summary["cost_unknown_count"] += 1
        else:
            basis, currency, amount = expense
            summary["costs"][(basis, currency)]["known_amount"] += amount
            summary["costs"][(basis, currency)]["known_count"] += 1
            summary["cost_known_count"] += 1


def activity_series(
    db,
    workspace,
    user,
    *,
    start,
    until,
    metric="activity",
    kind=None,
    status=None,
    system_id=None,
    bucket="hour",
    time_basis="created",
):
    queries.require_membership(db, workspace, user)
    start = start.astimezone(UTC).replace(tzinfo=None) if start.tzinfo else start
    until = observation_anchor(until)
    if not timedelta(0) < until - start <= timedelta(days=30):
        raise HTTPException(422, detail="ACTIVITY_SERIES_WINDOW_INVALID")
    statuses = parse_status_filter(status, detail="ACTIVITY_SERIES_FILTER_INVALID")
    if (
        metric not in {"activity", "cost"}
        or bucket not in {"hour", "day"}
        or time_basis not in {"created", "finished"}
        or kind is not None
        and kind not in KINDS
    ):
        raise HTTPException(422, detail="ACTIVITY_SERIES_FILTER_INVALID")
    if metric == "cost" and (
        kind not in {"skill_invocation", "compute_run"} or time_basis != "finished"
    ):
        raise HTTPException(422, detail="ACTIVITY_SERIES_COST_POPULATION_REQUIRED")
    width = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    first = start.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        first = first.replace(hour=0)
    cells = {}
    date = first
    while date < until:
        cells[date] = _summary()
        date += width
    totals = _summary()
    query = db.query(Activity).filter(Activity.workspace_id == workspace.id)
    if system_id:
        query = query.filter(Activity.system_id == system_id)
    if kind:
        query = query.filter(Activity.kind == kind)
    if statuses is not None:
        query = query.filter(Activity.status.in_(statuses))
    if time_basis == "created":
        query = query.filter(Activity.created_at >= start, Activity.created_at < until)
    else:
        # Select independently of creation. A valid historical offset can move
        # a finish across a UTC day boundary; Python accepts offsets <24h. The
        # widened prefix is conservative, and unusual ISO forms reach the same
        # native parser. Exact UTC bounds are applied only after authorization.
        ended = Activity.snapshot["finished_at"].as_string()
        query = query.filter(
            Activity.status.in_(TERMINAL),
            or_(
                and_(
                    func.substr(ended, 1, 19)
                    >= (start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                    func.substr(ended, 1, 19)
                    < (until + timedelta(days=1, seconds=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                ),
                and_(Activity.created_at >= start, Activity.created_at < until),
                ~ended.like("____-__-__T__:__:__%"),
            ),
        )
    read_context = queries.VisibilityReadContext(db, workspace, user)
    from .series_sql import aggregate_compat

    accelerated = aggregate_compat(
        db,
        workspace,
        user,
        read_context=read_context,
        start=start,
        until=until,
        metric=metric,
        kind=kind,
        status=status,
        system_id=system_id,
        bucket=bucket,
        time_basis=time_basis,
    )
    if accelerated is not None:
        public_totals, public_buckets, missing_finished = accelerated
    else:
        last = None
        missing_finished = 0
        while True:
            page_query = query.filter(Activity.id > last) if last else query
            batch = page_query.order_by(Activity.id).limit(2000).all()
            if not batch:
                break
            visible = queries.filter_visible(db, batch, workspace, user, read_context=read_context)
            sources = _cost_sources(db, visible) if metric == "cost" else {}
            for row in visible:
                occurred = (
                    row.created_at
                    if time_basis == "created"
                    else _date(row.snapshot.get("finished_at"))
                )
                if occurred is None:
                    missing_finished += start <= row.created_at < until
                    continue
                if not start <= occurred < until:
                    continue
                slot = occurred.replace(minute=0, second=0, microsecond=0)
                if bucket == "day":
                    slot = slot.replace(hour=0)
                expense = sources.get((row.kind, row.native_id))
                _add(cells[slot], row, expense, metric)
                _add(totals, row, expense, metric)
            last = batch[-1].id
            # ORM identity maps otherwise retain large native JSON across batches.
            for row in batch:
                db.expunge(row)
        public_totals = _public(totals)
        public_buckets = [
            {
                "from": iso(max(slot, start)),
                "until": iso(min(slot + width, until)),
                **_public(summary),
            }
            for slot, summary in cells.items()
        ]
    return {
        "schema_version": 1,
        "from": iso(start),
        "until": iso(until),
        "as_of": iso(datetime.now(UTC).replace(tzinfo=None)),
        "population": {
            "metric": metric,
            "kind": kind,
            "status": status,
            "system_id": system_id,
            "time_basis": time_basis,
            "unit": "native_expenses" if metric == "cost" else "activities",
        },
        "bucket": bucket,
        "timezone": "UTC",
        "quantile_method": "nearest_rank_exact",
        "totals": public_totals,
        "buckets": public_buckets,
        "coverage": {
            "missing_finished_at": missing_finished,
            "missing_finished_population": "terminal_activities_created_in_window",
            "historical_state_reconstruction": False,
        },
    }
