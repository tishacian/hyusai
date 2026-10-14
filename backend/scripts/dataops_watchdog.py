"""One external watchdog pass; never dispatches Runs or adds a Beat schedule."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def now():
    return datetime.now(UTC)


def check_state(path: Path, max_age_seconds=900, *, at=None):
    at = at or now()
    try:
        state = json.loads(path.read_text())
        written = datetime.fromisoformat(state["observed_at"])
        age = (at - written).total_seconds()
        if age < -30 or age > max_age_seconds:
            return {"status": "stale", "code": "DATAOPS_WATCHDOG_STALE", "age_seconds": age}
        return {**state, "age_seconds": age}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "stale", "code": "DATAOPS_WATCHDOG_STATE_UNAVAILABLE"}


def write_state(path: Path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def watchdog_pass(db, *, workspace_id=None, probe_queue=False, at=None):
    from app.models.service_contract import ServiceIncident
    from app.models.workspace import Workspace
    from app.services.service_engine import enabled
    from app.services.service_promises import watchdog

    at = at or now()
    query = db.query(Workspace).filter_by(is_active=True)
    if workspace_id:
        query = query.filter_by(id=workspace_id)
    workspaces = query.order_by(Workspace.id).all()
    incidents = []
    inspected = []
    for workspace in workspaces:
        if not enabled(workspace):
            continue
        inspected.append(workspace.id)
        from app.services.dataops.watchdog import sweep

        sweep(db, workspace_id=workspace.id, now=at, limit=100)
        for incident in watchdog(db, at, workspace_id=workspace.id):
            incidents.append(
                {
                    "id": incident.id,
                    "workspace_id": workspace.id,
                    "window_id": incident.window_id,
                    "code": incident.code,
                }
            )
    db.commit()
    unresolved = (
        db.query(ServiceIncident)
        .filter(ServiceIncident.workspace_id.in_(inspected), ServiceIncident.resolved.is_(False))
        .count()
        if inspected
        else 0
    )
    queue = "not_probed"
    if probe_queue:
        try:
            from app.core.config import settings
            from app.workers.celery_app import celery_app

            queues = celery_app.control.inspect(timeout=3).active_queues() or {}
            queue = (
                "available"
                if any(
                    value.get("name") == settings.celery_dataops_queue
                    for values in queues.values()
                    for value in values
                )
                else "unavailable"
            )
        except Exception:
            queue = "unavailable"
    return {
        "schema_version": 1,
        "observed_at": at.isoformat(),
        "status": "attention" if unresolved or queue == "unavailable" else "healthy",
        "workspaces_checked": inspected,
        "new_incidents": incidents,
        "unresolved_incidents": unresolved,
        "dataops_queue": queue,
        "run_dispatch_performed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id")
    parser.add_argument("--probe-queue", action="store_true")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--check-state", action="store_true")
    parser.add_argument("--max-age-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    if args.check_state:
        if not args.state_file or args.max_age_seconds < 1:
            parser.error("--check-state requires --state-file and a positive --max-age-seconds")
        result = check_state(args.state_file, args.max_age_seconds)
    else:
        try:
            import app.models  # noqa: F401
            from app.db.base import SessionLocal

            with SessionLocal() as db:
                result = watchdog_pass(
                    db, workspace_id=args.workspace_id, probe_queue=args.probe_queue
                )
        except Exception:
            result = {
                "schema_version": 1,
                "observed_at": now().isoformat(),
                "status": "failed",
                "code": "DATAOPS_WATCHDOG_FAILED",
            }
        if args.state_file:
            write_state(args.state_file, result)
    print(json.dumps(result, sort_keys=True))
    return (
        0 if result["status"] == "healthy" else 2 if result["status"] in {"stale", "failed"} else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
