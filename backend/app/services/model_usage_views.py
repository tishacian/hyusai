"""Authorised projections of provider calls. No parent totals are added."""

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models.model_usage import ModelUsageCall
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface.access import is_workspace_admin
from app.services.model_usage import public_call
from app.services.observation_window import observation_anchor
from app.services.run_access import readable_runs, readable_skill_invocations_for_runs
from app.services.system_access import readable_systems

SCAN_LIMIT = 20_000


def visible_calls(
    db,
    workspace,
    user,
    *,
    window="7d",
    as_of=None,
    system_id=None,
    run_id=None,
    provider=None,
    model=None,
    purpose=None,
    traffic="all",
    status=None,
    run_scope="direct",
):
    anchor = observation_anchor(as_of)
    query = db.query(ModelUsageCall).filter_by(workspace_id=workspace.id)
    if run_id:
        requested = db.query(Run).filter_by(id=run_id, workspace_id=workspace.id).first()
        if not requested or not readable_runs(db, runs=[requested], workspace=workspace, user=user):
            raise HTTPException(404, "RUN_NOT_FOUND")
        # Retained Runs are available independently of the current time window.
        if run_scope == "tree":
            # root_run_id identifies the outermost application. An intermediate
            # delegation still needs its own descendants, each counted once.
            subtree = (
                select(Run.id)
                .where(Run.workspace_id == workspace.id, Run.id == run_id)
                .cte("usage_run_subtree", recursive=True)
            )
            subtree = subtree.union(
                select(Run.id)
                .join(subtree, Run.parent_run_id == subtree.c.id)
                .where(Run.workspace_id == workspace.id)
            )
            query = query.filter(
                or_(
                    ModelUsageCall.root_run_id == run_id,
                    ModelUsageCall.run_id.in_(select(subtree.c.id)),
                )
            )
        else:
            query = query.filter(ModelUsageCall.run_id == run_id)
    else:
        query = query.filter(
            ModelUsageCall.started_at
            >= anchor - timedelta(days={"24h": 1, "7d": 7, "30d": 30, "90d": 90}[window]),
            ModelUsageCall.started_at < anchor,
        )
    if system_id:
        requested = db.query(System).filter_by(id=system_id, workspace_id=workspace.id).first()
        if not requested or not readable_systems(
            db, systems=[requested], workspace=workspace, user=user
        ):
            raise HTTPException(404, "SYSTEM_NOT_FOUND")
        query = query.filter(
            or_(ModelUsageCall.system_id == system_id, ModelUsageCall.root_system_id == system_id)
        )
    for field, value in (
        ("provider", provider),
        ("model", model),
        ("purpose", purpose),
        ("status", status),
    ):
        if value:
            query = query.filter(getattr(ModelUsageCall, field) == value)
    if traffic != "all":
        query = query.filter(ModelUsageCall.traffic == traffic)
    # Limit the authorised result, not the raw rows: private calls must not
    # change pagination/coverage or hide an older readable call.
    permitted, batch = [], []
    query = query.order_by(ModelUsageCall.started_at.desc(), ModelUsageCall.id.desc())
    for row in query.execution_options(stream_results=True).yield_per(500):
        batch.append(row)
        if len(batch) < 500:
            continue
        permitted.extend(_permitted_calls(db, workspace, user, batch, system_id=system_id))
        batch = []
        if len(permitted) > SCAN_LIMIT:
            break
    if batch:
        permitted.extend(_permitted_calls(db, workspace, user, batch, system_id=system_id))
    limited = len(permitted) > SCAN_LIMIT
    permitted = permitted[:SCAN_LIMIT]
    return permitted, {
        "mode": "bounded_sample" if limited else "complete_retained_calls",
        "complete": not limited,
        "limit": SCAN_LIMIT,
        "scanned": len(permitted),
        "as_of": anchor.isoformat() + "Z",
        "historical_calls_reconstructed": False,
        "billed_cost_available": False,
    }


def _permitted_calls(db, workspace, user, rows, *, system_id=None):
    run_ids = {
        identifier for row in rows for identifier in (row.run_id, row.root_run_id) if identifier
    }
    runs = readable_runs(
        db,
        runs=db.query(Run).filter(Run.workspace_id == workspace.id, Run.id.in_(run_ids)).all(),
        workspace=workspace,
        user=user,
    )
    visible_run_ids = {run.id for run in runs}
    invocation_ids = {
        row.invocation_id for row in rows if row.invocation_id and row.run_id in visible_run_ids
    }
    invocations = readable_skill_invocations_for_runs(
        db,
        invocations=db.query(SkillInvocation).filter(SkillInvocation.id.in_(invocation_ids)).all(),
        runs=runs,
        workspace=workspace,
        user=user,
    )
    visible_invocations = {item.id for item in invocations}
    system_ids = {row.system_id for row in rows if row.system_id}
    systems = readable_systems(
        db,
        systems=db.query(System)
        .filter(System.workspace_id == workspace.id, System.id.in_(system_ids))
        .all(),
        workspace=workspace,
        user=user,
    )
    visible_system_ids = {system.id for system in systems}
    from app.api.v1.endpoints.workspace_jobs import _can_access_job

    jobs = (
        db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.workspace_id == workspace.id,
            WorkspaceJob.id.in_({r.job_id for r in rows if r.job_id}),
        )
        .all()
    )
    visible_job_ids = {job.id for job in jobs if _can_access_job(db, job, user, workspace)}
    admin = is_workspace_admin(db, user, workspace)
    return [
        row
        for row in rows
        if (not row.run_id or row.run_id in visible_run_ids)
        and (not row.invocation_id or row.invocation_id in visible_invocations)
        and (not row.system_id or row.system_id in visible_system_ids)
        and (not row.job_id or row.job_id in visible_job_ids)
        and (not row.worker_job_id or admin)
        # Filtering on a delegated root is itself a disclosure of lineage.
        and (not system_id or row.system_id == system_id or row.root_run_id in visible_run_ids)
        and (row.run_id or row.system_id or row.job_id or admin or row.actor_user_id == user.id)
    ]


def visible_call_payloads(db, workspace, user, rows):
    """Child cost is readable independently of a private delegated parent."""
    roots = {row.root_run_id for row in rows if row.root_run_id}
    systems = {row.root_system_id for row in rows if row.root_system_id}
    readable_roots = {
        run.id
        for run in readable_runs(
            db,
            runs=db.query(Run).filter(Run.workspace_id == workspace.id, Run.id.in_(roots)).all(),
            workspace=workspace,
            user=user,
        )
    }
    readable_apps = {
        system.id
        for system in readable_systems(
            db,
            systems=db.query(System)
            .filter(System.workspace_id == workspace.id, System.id.in_(systems))
            .all(),
            workspace=workspace,
            user=user,
        )
    }
    result = []
    for row in rows:
        item = public_call(row)
        private_root = bool(row.root_run_id and row.root_run_id not in readable_roots)
        if private_root:
            item["root_run_id"] = None
        if private_root or row.root_system_id not in readable_apps:
            item["root_system_id"] = None
            if str((item.get("details") or {}).get("scope", "")).startswith("system:"):
                item["details"] = {
                    key: value
                    for key, value in item["details"].items()
                    if key not in {"scope", "policy_id"}
                }
        result.append(item)
    return result


def summarize(rows):
    counts = Counter(row.status for row in rows)
    dispatched = [row for row in rows if row.dispatched_at is not None]

    def sum_known(key, selection=dispatched):
        known = [getattr(row, key) for row in selection if getattr(row, key) is not None]
        return sum(known) if known else None

    known_tokens = sum(row.total_tokens is not None for row in dispatched)
    known_cost = sum(row.amount is not None for row in dispatched)
    by_currency = defaultdict(list)
    by_group = defaultdict(list)
    for row in dispatched:
        if row.currency:
            by_currency[row.currency].append(row)
        by_group[
            (row.provider, row.model, row.purpose, row.system_id, row.traffic, row.currency)
        ].append(row)
    costs = [
        {
            "currency": currency,
            "known_amount": str(
                sum((row.amount for row in items if row.amount is not None), Decimal(0))
            )
            if any(row.amount is not None for row in items)
            else None,
            "known_calls": sum(row.amount is not None for row in items),
            "unknown_calls": sum(row.amount is None for row in items),
            "basis": "provider_tokens_at_versioned_tariff",
            "billed_amount": None,
        }
        for currency, items in sorted(by_currency.items())
    ]
    groups = [
        {
            "provider": key[0],
            "model": key[1],
            "purpose": key[2],
            "system_id": key[3],
            "traffic": key[4],
            "currency": key[5],
            "calls": len(items),
            "total_tokens": sum_known("total_tokens", items),
            "known_amount": str(
                sum((row.amount for row in items if row.amount is not None), Decimal(0))
            )
            if any(row.amount is not None for row in items)
            else None,
        }
        for key, items in sorted(
            by_group.items(), key=lambda pair: tuple(str(v or "") for v in pair[0])
        )
    ]
    return {
        "counts": {
            "calls": len(rows),
            "dispatched": len(dispatched),
            "completed": counts["completed"],
            "failed": counts["failed"],
            "unknown": counts["unknown"],
            "blocked": counts["blocked"],
            "pending": counts["prepared"] + counts["dispatched"],
            "cancelled": counts["cancelled"],
        },
        "tokens": {
            "input": sum_known("input_tokens"),
            "output": sum_known("output_tokens"),
            "total": sum_known("total_tokens"),
            "cached_input": sum_known("cached_input_tokens"),
            "cache_write": sum_known("cache_write_tokens"),
            "reasoning": sum_known("reasoning_tokens"),
            "known_calls": known_tokens,
            "unknown_calls": len(dispatched) - known_tokens,
        },
        "costs": costs,
        "groups": groups,
        "cost_coverage": {
            "known_calls": known_cost,
            "unknown_calls": len(dispatched) - known_cost,
            "complete": bool(dispatched) and known_cost == len(dispatched),
        },
        "basis": "provider_calls",
        "billed_amount": None,
    }


def series(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.started_at.date().isoformat()].append(row)
    return [{"date": key, **summarize(items)} for key, items in sorted(grouped.items())]
