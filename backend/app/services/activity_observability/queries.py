"""Authorized metadata projections; pagination never changes aggregate totals."""

import base64
import json
from collections import Counter
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select

from app.core.config import settings
from app.models.activity import Activity, ActivityCommand, ActivityEvent, ActivityWorkspaceCursor
from app.models.run import Run
from app.models.system import System
from app.models.workspace import WorkspaceMember
from app.services.huggingface.access import is_platform_admin, is_workspace_admin
from app.services.run_access import readable_runs
from app.services.system_access import readable_systems

from .projection import KINDS, STATUSES, TERMINAL, iso


def enabled():
    return bool(getattr(settings, "activity_observability_enabled", False))


def require_enabled():
    if not enabled():
        raise HTTPException(404, detail="ACTIVITY_OBSERVABILITY_DISABLED")


def require_membership(db, workspace, user):
    if (
        not user
        or not user.is_active
        or not workspace
        or not workspace.is_active
        or workspace.deleted_at
    ):
        raise HTTPException(403, detail="ACTIVITY_ACCESS_DENIED")
    if (
        not is_platform_admin(user)
        and not db.query(WorkspaceMember.id)
        .filter_by(workspace_id=workspace.id, user_id=user.id)
        .first()
    ):
        raise HTTPException(403, detail="ACTIVITY_ACCESS_DENIED")


def encode_cursor(workspace_id, sequence):
    return (
        base64.urlsafe_b64encode(
            json.dumps([1, workspace_id, sequence], separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


def decode_cursor(value, workspace_id):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 256:
            raise ValueError
        payload = json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if (
            not isinstance(payload, list)
            or len(payload) != 3
            or payload[0] != 1
            or payload[1] != workspace_id
            or type(payload[2]) is not int
            or not 0 <= payload[2] <= 2**63 - 1
        ):
            raise ValueError
        return payload[2]
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(400, detail="ACTIVITY_CURSOR_INVALID") from None


def highwater(db, workspace_id):
    return (
        db.execute(
            select(ActivityWorkspaceCursor.sequence).where(
                ActivityWorkspaceCursor.workspace_id == workspace_id
            )
        ).scalar_one_or_none()
        or 0
    )


def filter_visible(db, rows, workspace, user):
    """Current native read boundaries apply to every child and historical event."""
    if not rows:
        return []
    run_ids = {row.run_id for row in rows if row.run_id}
    runs = (
        db.query(Run).filter(Run.workspace_id == workspace.id, Run.id.in_(run_ids)).all()
        if run_ids
        else []
    )
    allowed_runs = {row.id for row in readable_runs(db, runs=runs, user=user, workspace=workspace)}
    system_ids = {row.system_id for row in rows if row.system_id and not row.run_id}
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.id.in_(system_ids))
        .all()
        if system_ids
        else []
    )
    allowed_systems = {
        row.id for row in readable_systems(db, systems=systems, user=user, workspace=workspace)
    }
    admin = is_workspace_admin(db, user, workspace)
    candidates = [
        row
        for row in rows
        if row.workspace_id == workspace.id
        and (
            (row.run_id in allowed_runs)
            if row.run_id
            else (row.system_id in allowed_systems)
            if row.system_id
            else (admin or row.owner_id == user.id)
        )
    ]
    # Connector ownership and private job/session policy can be narrower than
    # the linked System/Run. The projection must not broaden those native APIs.
    from app.api.v1.endpoints.workspace_jobs import _can_access_job
    from app.models.compute_run import ComputeRun
    from app.models.workspace_job import WorkspaceJob

    computes = {
        value.id: value
        for value in db.query(ComputeRun)
        .filter(
            ComputeRun.workspace_id == workspace.id,
            ComputeRun.id.in_([r.native_id for r in candidates if r.kind == "compute_run"]),
        )
        .all()
    }
    jobs = {
        value.id: value
        for value in db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.workspace_id == workspace.id,
            WorkspaceJob.id.in_([r.native_id for r in candidates if r.kind == "workspace_job"]),
        )
        .all()
    }
    return [
        row
        for row in candidates
        if (
            row.kind != "compute_run"
            or row.native_id in computes
            and (admin or computes[row.native_id].user_id == user.id)
        )
        and (
            row.kind != "workspace_job"
            or row.native_id in jobs
            and _can_access_job(db, jobs[row.native_id], user, workspace)
        )
    ]


def authorized_activity(db, activity_id, workspace, user):
    row = (
        db.query(Activity)
        .filter_by(id=activity_id, workspace_id=workspace.id)
        .populate_existing()
        .first()
    )
    if not row or not filter_visible(db, [row], workspace, user):
        raise HTTPException(404, detail="ACTIVITY_NOT_FOUND")
    return row


def links(row):
    native = quote(row.native_id, safe="")
    paths = {
        "run": f"/runs/{native}",
        "skill_invocation": f"/runs/{quote(row.run_id or '', safe='')}/invocations/{native}",
        "ml_training": f"/models/{native}",
    }
    if row.kind in paths:
        return [{"rel": "native", "href": paths[row.kind]}]
    if row.kind in {"service_window", "delivery_receipt"}:
        return [{"rel": "services", "href": "/work/services"}]
    if row.run_id:
        return [{"rel": "run", "href": f"/runs/{quote(row.run_id, safe='')}"}]
    return []


def can_cancel(db, row, workspace, user, *, new_admission=True):
    from app.services.execution.rollout import enabled_for

    # Canary/flag closure prevents new control commands, not the draining of
    # already accepted commands. Every path still revalidates native authority.
    if new_admission and not enabled_for(db, workspace.id, "execution_control_enabled"):
        return False
    if not (
        row.kind in {"recipe_execution", "compute_run", "ml_training", "run"}
        and row.status not in TERMINAL
        and not row.snapshot.get("cancel_requested")
        and is_workspace_admin(db, user, workspace)
    ):
        return False
    run = (
        db.query(Run)
        .filter_by(id=row.run_id, workspace_id=workspace.id)
        .populate_existing()
        .first()
        if row.run_id
        else None
    )
    if row.run_id and not run:
        return False
    system_id = run.system_id if run else row.system_id
    if system_id:
        system = (
            db.query(System)
            .filter_by(id=system_id, workspace_id=workspace.id)
            .populate_existing()
            .first()
        )
        if system is None:
            return False
        # Same complete operator boundary as the existing debugger stop API,
        # including strict IAM and the frozen Run's published execution policy.
        # Run children cannot escape this guard by controlling their native row.
        from app.api.v1.endpoints.systems import _enforce_system_run_authority

        try:
            _enforce_system_run_authority(
                db,
                user=user,
                workspace=workspace,
                system=system,
                execution_source="activity_cancel",
                execution_contract=(run.execution_contract or {}) if run else {},
            )
        except HTTPException:
            return False  # Never expose policy/contract details in metadata.
    return True


def serialize_activity(db, row, workspace, user):
    value = {
        key: item
        for key, item in row.snapshot.items()
        if key not in {"owner_id", "resource_coverage", "related_recipe_execution_id"}
    }
    value.update(
        id=row.id,
        version=row.version,
        updated_at=iso(row.updated_at),
        links=links(row),
        capabilities={"cancel": can_cancel(db, row, workspace, user)},
        coverage={
            "events": row.origin,
            "resources": row.snapshot.get("resource_coverage", "unavailable"),
            "cost": "measured"
            if row.snapshot.get("measurements", {}).get("cost_known")
            else "unknown",
        },
    )
    return value


def aggregate(rows):
    statuses, kinds = Counter(), Counter()
    for row in rows:
        statuses[row.status] += 1
        kinds[row.kind] += 1
    return {"total": sum(statuses.values()), "by_status": dict(statuses), "by_kind": dict(kinds)}


def list_activities(
    db, workspace, user, *, system_id=None, kind=None, status=None, since=None, limit=50, offset=0
):
    if kind is not None and kind not in KINDS or status is not None and status not in STATUSES:
        raise HTTPException(422, detail="ACTIVITY_FILTER_INVALID")
    cursor = encode_cursor(workspace.id, highwater(db, workspace.id))
    query = db.query(Activity).filter(Activity.workspace_id == workspace.id)
    if system_id:
        query = query.filter(Activity.system_id == system_id)
    if kind:
        query = query.filter(Activity.kind == kind)
    if status:
        query = query.filter(Activity.status == status)
    if since:
        query = query.filter(Activity.created_at >= since)
    # Authorization precedes pagination. Iterate bounded native-read batches;
    # never truncate totals to the first page of the selected time window.
    total, items, by_status, by_kind = 0, [], Counter(), Counter()
    last = None
    while True:
        batch_query = (
            query
            if last is None
            else query.filter(
                or_(
                    Activity.created_at < last[0],
                    and_(Activity.created_at == last[0], Activity.id < last[1]),
                )
            )
        )
        batch = (
            batch_query.order_by(Activity.created_at.desc(), Activity.id.desc()).limit(250).all()
        )
        if not batch:
            break
        visible = filter_visible(db, batch, workspace, user)
        if visible:
            counts = (
                db.query(Activity.status, Activity.kind, func.count(Activity.id))
                .filter(
                    Activity.workspace_id == workspace.id,
                    Activity.id.in_([row.id for row in visible]),
                )
                .group_by(Activity.status, Activity.kind)
                .all()
            )
            for state, source, count in counts:
                by_status[state] += count
                by_kind[source] += count
        for row in visible:
            if offset <= total < offset + limit:
                items.append(serialize_activity(db, row, workspace, user))
            total += 1
        last = batch[-1].created_at, batch[-1].id
    return {
        "items": items,
        "total": total,
        "has_more": offset + len(items) < total,
        "offset": offset,
        "limit": limit,
        "snapshot_cursor": cursor,
        "aggregates": {"total": total, "by_status": dict(by_status), "by_kind": dict(by_kind)},
    }


def serialize_event(row):
    data = {"activity_id": row.activity_id, "version": row.version, **row.payload}
    return {
        "specversion": "1.0",
        "id": row.id,
        "source": f"/workspaces/{quote(row.workspace_id, safe='')}/activities",
        "type": row.event_type,
        "subject": row.activity_id,
        "time": iso(row.occurred_at),
        "datacontenttype": "application/json",
        "data": data,
        "cursor": encode_cursor(row.workspace_id, row.sequence),
        "sequence": row.sequence,
        "activity_id": row.activity_id,
        "version": row.version,
        "event_type": row.event_type,
        "occurred_at": iso(row.occurred_at),
        **row.payload,
    }


def event_page(db, workspace, user, *, cursor=None, activity_id=None, limit=100):
    after = decode_cursor(cursor, workspace.id) if cursor else 0
    upper = highwater(db, workspace.id)
    if after > upper:
        raise HTTPException(409, detail="ACTIVITY_CURSOR_AHEAD")
    if activity_id:
        authorized_activity(db, activity_id, workspace, user)
    query = db.query(ActivityEvent).filter(
        ActivityEvent.workspace_id == workspace.id,
        ActivityEvent.sequence > after,
        ActivityEvent.sequence <= upper,
    )
    if activity_id:
        query = query.filter(ActivityEvent.activity_id == activity_id)
    scanned = query.order_by(ActivityEvent.sequence).limit(limit).all()
    activities = (
        db.query(Activity)
        .filter(
            Activity.workspace_id == workspace.id,
            Activity.id.in_({row.activity_id for row in scanned}),
        )
        .all()
        if scanned
        else []
    )
    visible = {row.id for row in filter_visible(db, activities, workspace, user)}
    through = scanned[-1].sequence if len(scanned) == limit else upper
    return {
        "items": [serialize_event(row) for row in scanned if row.activity_id in visible],
        "next_cursor": encode_cursor(workspace.id, through),
        "has_more": through < upper,
    }


def serialize_command(row):
    return {
        "id": row.id,
        "activity_id": row.activity_id,
        "action": row.action,
        "status": row.status,
        "created_at": iso(row.created_at),
        "completed_at": iso(row.completed_at),
        "error_code": row.error_code,
    }


def detail(db, row, workspace, user):
    value = serialize_activity(db, row, workspace, user)
    from app.models.execution_control import ExecutionReservation

    allocation = (
        db.query(ExecutionReservation)
        .filter_by(workspace_id=workspace.id, entity_kind=row.kind, entity_id=row.native_id)
        .one_or_none()
    )
    if allocation:
        value["measurements"] = {
            **value["measurements"],
            "cpu_cores": allocation.cpu_cores,
            "memory_mb": allocation.memory_mb,
            "core_hours": allocation.allocated_core_hours,
            "allocated_core_hours": allocation.allocated_core_hours,
            "reserved_core_hours": allocation.reserved_core_hours,
            "cpu_seconds": allocation.cpu_seconds,
            "peak_memory_bytes": allocation.peak_rss_bytes,
            "resource_basis": "requested_resources_x_wall_time",
        }
        value["coverage"]["resources"] = (
            "allocation_only" if allocation.cpu_seconds is None else "measured"
        )
        value["coordination"] = {
            "lane": allocation.lane,
            "deadline_at": iso(allocation.deadline_at),
            "released_at": iso(allocation.released_at),
            "outcome": allocation.outcome,
        }

    def visible_children(query):
        result, offset = [], 0
        while len(result) < 101:
            batch = query.order_by(Activity.created_at, Activity.id).offset(offset).limit(200).all()
            if not batch:
                break
            result.extend(filter_visible(db, batch, workspace, user))
            offset += len(batch)
        return result[:101]

    children = visible_children(
        db.query(Activity).filter_by(workspace_id=workspace.id, parent_activity_id=row.id)
    )
    value["related_activities"] = [
        serialize_activity(db, child, workspace, user) for child in children[:100]
    ]
    value["related_has_more"] = len(children) > 100
    attempts = []
    if row.kind == "service_window":
        from app.models.service_contract import ServiceAttempt

        native_runs = (
            db.query(ServiceAttempt.run_id)
            .filter_by(workspace_id=workspace.id, window_id=row.native_id)
            .filter(ServiceAttempt.run_id.isnot(None))
            .subquery()
        )
        attempts = visible_children(
            db.query(Activity).filter(
                Activity.workspace_id == workspace.id,
                Activity.kind == "run",
                Activity.native_id.in_(select(native_runs.c.run_id)),
            )
        )
    elif row.kind == "run":
        # parent_run_id is also used for delegated child Runs. Only an explicit
        # replay of the same System is another attempt, never every child node.
        replays = (
            db.query(Run.id)
            .filter_by(
                workspace_id=workspace.id, parent_run_id=row.native_id, system_id=row.system_id
            )
            .filter(Run.trigger.in_(["replay", "rerun"]))
            .subquery()
        )
        attempts = visible_children(
            db.query(Activity).filter(
                Activity.workspace_id == workspace.id,
                Activity.kind == "run",
                Activity.native_id.in_(select(replays.c.id)),
            )
        )
    value["attempts"] = [
        serialize_activity(db, attempt, workspace, user) for attempt in attempts[:100]
    ]
    value["attempts_has_more"] = len(attempts) > 100
    value["evidence"] = links(row)
    value["events"] = [
        serialize_event(event)
        for event in reversed(
            db.query(ActivityEvent)
            .filter_by(workspace_id=workspace.id, activity_id=row.id)
            .order_by(ActivityEvent.sequence.desc())
            .limit(100)
            .all()
        )
    ]
    value["commands"] = [
        serialize_command(command)
        for command in db.query(ActivityCommand)
        .filter_by(workspace_id=workspace.id, activity_id=row.id)
        .order_by(ActivityCommand.created_at.desc())
        .limit(100)
        .all()
    ]
    return value
