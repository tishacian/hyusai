"""Persisted prefix polling; event dispatch and observed checkpoint commit together."""

import re
from datetime import datetime, timedelta
from uuid import uuid4

from app.models.compute_run import ComputeRun
from app.models.connector_connection import ConnectorConnection
from app.models.connector_sync import ConnectorWatch
from app.models.system import System
from app.services import compute_runs
from app.services.connectors import connections
from app.services.connectors.adapters.object_clients import object_key
from app.services.connectors.profiles import get_profile
from app.services.connectors.writes import WriteError, _admin
from app.services.run_engine import triggers

EVENT = "connector.objects_changed"


def create(db, *, workspace_id, user, connection_id, system_id, prefix, interval_s=300):
    _admin(db, workspace_id, user)
    connection = connections.get_connection(db, workspace_id, connection_id)
    if not get_profile(connection.profile_key).capabilities.watch:
        raise WriteError("CONNECTOR_OPERATION_UNSUPPORTED")
    if type(interval_s) is not int or not 60 <= interval_s <= 86400:
        raise WriteError("CONNECTOR_WATCH_INTERVAL_INVALID")
    system = db.query(System).filter_by(id=system_id, workspace_id=workspace_id).one_or_none()
    if system is None:
        raise WriteError("CONNECTOR_SYSTEM_NOT_FOUND", 404)
    prefix = object_key(prefix, connection.values.get("prefix", ""))
    row = ConnectorWatch(
        id=str(uuid4()),
        workspace_id=workspace_id,
        connection_id=connection.id,
        connection_revision=connection.revision,
        system_id=system.id,
        created_by=user.id,
        prefix=prefix,
        interval_s=interval_s,
    )
    db.add(row)
    connections.audit(
        db, connection, "connection.watch.created", user.id, watch_id=row.id, system_id=system.id
    )
    db.flush()
    return row


def disable(db, *, workspace_id, user, watch_id):
    _admin(db, workspace_id, user)
    row = (
        db.query(ConnectorWatch)
        .filter_by(id=watch_id, workspace_id=workspace_id)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise WriteError("CONNECTOR_WATCH_NOT_FOUND", 404)
    row.enabled = False
    if row.pending_run_id:
        run = db.get(ComputeRun, row.pending_run_id)
        if run and run.status not in compute_runs.TERMINAL_STATUSES:
            compute_runs.request_cancel(db, run)
    connections.audit(
        db,
        db.get(ConnectorConnection, row.connection_id),
        "connection.watch.disabled",
        user.id,
        watch_id=row.id,
    )
    db.flush()
    return row


def view(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "connection_id",
            "system_id",
            "prefix",
            "interval_s",
            "enabled",
            "sequence",
            "fingerprint",
            "pending_run_id",
            "next_poll_at",
            "last_error",
        )
    }


def _settle(db, watch, run):
    if run.status != "succeeded":
        watch.last_error = run.error_code or "CONNECTOR_WATCH_FAILED"
        watch.pending_run_id = None
        return
    output = run.output_json or {}
    fingerprint = output.get("source_fingerprint", "")
    objects = output.get("objects")
    if (
        not re.fullmatch("[a-f0-9]{64}", fingerprint)
        or not isinstance(objects, list)
        or len(objects) > 10000
    ):
        raise WriteError("CONNECTOR_WATCH_RESULT_INVALID")
    previous = {item["key"]: item for item in watch.objects}
    changed = [
        item
        for item in objects
        if item["key"] not in previous or item.get("etag") != previous[item["key"]].get("etag")
    ]
    # First poll creates a baseline. Deletions update the baseline, but cannot
    # masquerade as arrivals or trigger processing of a nonexistent file.
    if watch.fingerprint is not None and changed:
        from app.services.connectors.source_requalification import invalidate

        invalidate(db, watch.workspace_id, watch.connection_id, changed)
        if not triggers.is_event_triggers_enabled(watch.workspace_id, db=db):
            watch.last_error = "CONNECTOR_EVENT_TRIGGERS_DISABLED"
            return
        payload = {
            "watch_id": watch.id,
            "connection_id": watch.connection_id,
            "connection_revision": watch.connection_revision,
            "sequence": watch.sequence + 1,
            "source_fingerprint": fingerprint,
            "objects": changed,
        }
        results = triggers.emit_event(
            EVENT, watch.workspace_id, payload, db=db, system_id=watch.system_id
        )
        if not results or any(
            row.get("status") not in ("simulated", "dispatched", "buffered", "duplicate")
            for row in results
        ):
            watch.last_error = "CONNECTOR_EVENT_DELIVERY_PENDING"
            return
    watch.sequence += 1
    watch.objects, watch.fingerprint, watch.pending_run_id = objects, fingerprint, None
    watch.last_error = None
    db.flush()


def tick(db, *, now=None, limit=100):
    """Called by the existing scheduler's connector maintenance task."""
    from app.core.config import settings

    if not settings.connector_framework_enabled:
        return 0
    now = now or datetime.utcnow()
    ids = [
        r[0]
        for r in db.query(ConnectorWatch.id)
        .filter(ConnectorWatch.enabled.is_(True), ConnectorWatch.next_poll_at <= now)
        .order_by(ConnectorWatch.next_poll_at)
        .limit(limit)
        .all()
    ]
    count = 0
    for watch_id in ids:
        try:
            watch = (
                db.query(ConnectorWatch)
                .filter_by(id=watch_id, enabled=True)
                .with_for_update(skip_locked=True)
                .populate_existing()
                .one_or_none()
            )
            if watch is None or watch.next_poll_at > now:
                continue
            connection = connections.get_connection(db, watch.workspace_id, watch.connection_id)
            if connection.revision != watch.connection_revision:
                watch.enabled = False
                watch.last_error = "CONNECTOR_CONNECTION_CHANGED"
                db.commit()
                continue
            watch.next_poll_at = now + timedelta(seconds=watch.interval_s)
            if watch.pending_run_id:
                run = db.get(ComputeRun, watch.pending_run_id)
                if run and run.status in compute_runs.TERMINAL_STATUSES:
                    from app.workers.tasks_connectors import _check_actor

                    try:
                        _check_actor(db, run)
                    except compute_runs.ComputeRunError:
                        watch.enabled = False
                        watch.last_error = "CONNECTOR_ACTOR_FORBIDDEN"
                        db.commit()
                        continue
                    _settle(db, watch, run)
                elif run and run.status == "queued" and not run.celery_task_id:
                    compute_runs.dispatch_run(db, run)
                db.commit()
                count += 1
                continue
            run = compute_runs.create_run(
                db,
                workspace_id=watch.workspace_id,
                user_id=watch.created_by,
                connection_id=watch.connection_id,
                operation="watch",
                parameters={"prefix": watch.prefix, "previous_fingerprint": watch.fingerprint},
            )
            watch.pending_run_id = run.id
            db.flush()
            compute_runs.dispatch_run(db, run)
            count += 1
        except Exception as exc:
            db.rollback()
            watch = db.get(ConnectorWatch, watch_id)
            if watch:
                code = getattr(exc, "code", "CONNECTOR_WATCH_FAILED")
                watch.last_error = (
                    code
                    if isinstance(code, str) and re.fullmatch("CONNECTOR_[A-Z_]+", code)
                    else "CONNECTOR_WATCH_FAILED"
                )
                watch.next_poll_at = now + timedelta(seconds=watch.interval_s)
                db.commit()
    return count
