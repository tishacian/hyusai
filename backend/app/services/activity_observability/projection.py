"""Explicit metadata allowlist shared by live hooks and historical snapshots.

No inputs, outputs, errors, SQL, log tails, metrics JSON, model parameters or
credentials are projected. Checkpoints/trace are read only through an explicit
metadata allowlist and retained only as a revision digest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select, update

from app.db.base import Base
from app.models.activity import (
    Activity,
    ActivityEvent,
    ActivityWorkspaceCursor,
    measured_columns,
    non_negative_number,
)

SOURCES = {
    "runs": "run",
    "skill_invocations": "skill_invocation",
    "recipe_executions": "recipe_execution",
    "compute_runs": "compute_run",
    "ml_models": "ml_training",
    "workspace_jobs": "workspace_job",
    "service_windows": "service_window",
    "delivery_receipts": "delivery_receipt",
}
KINDS = tuple(SOURCES.values())
STATUS_MAP = {
    "pending": "pending",
    "queued": "pending",
    "created": "pending",
    "env_building": "running",
    "admitted": "running",
    "launching": "running",
    "running": "running",
    "training": "running",
    "committing": "running",
    "waiting": "waiting",
    "waiting_subflows": "waiting",
    "hitl_pending": "waiting",
    "debug_pending": "waiting",
    "awaiting_review": "waiting",
    "completed": "succeeded",
    "succeeded": "succeeded",
    "ready": "succeeded",
    "delivered": "succeeded",
    "published": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "timed_out": "timed_out",
    "missed": "timed_out",
    "lost": "lost",
    "deleted": "unknown",
}
STATUSES = tuple(dict.fromkeys(STATUS_MAP.values()))
TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "lost", "unknown"}
# Scalar columns only. Changes to lease heartbeats, token/row counters and
# serving statistics deliberately do not produce lifecycle events.
SOURCE_FIELDS = frozenset(
    {
        "id",
        "workspace_id",
        "system_id",
        "run_id",
        "parent_run_id",
        "invocation_id",
        "recipe_execution_id",
        "window_id",
        "contract_id",
        "initiated_by_user_id",
        "user_id",
        "created_by",
        "created_by_user_id",
        "status",
        "cancel_requested",
        "created_at",
        "started_at",
        "completed_at",
        "finished_at",
        "trained_at",
        "published_at",
        "duration_ms",
        "latency_ms",
        "train_duration_ms",
        "provider_cost_usd",
        "cost_measured",
        "cost",
        "metrics",
        "cost_usd",
        "cpu_cores",
        "memory_mb",
        "core_hours",
        "reserved_core_hours",
        "deadline_at",
        "checkpoints",
        "trace",
        "node_id",
        "attempt",
        "stage",
        "outcome_unknown",
    }
)


def activity_id(kind: str, native_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agentium:activity:{kind}:{native_id}"))


def iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def number(value):
    return non_negative_number(value)


def source_row(connection, table_name: str, identifier: str, *, lock=False):
    table = Base.metadata.tables[table_name]
    columns = [c for c in table.c if c.name in SOURCE_FIELDS]
    statement = select(*columns).where(table.c.id == identifier)
    return connection.execute(statement.with_for_update() if lock else statement).mappings().first()


def metadata(connection, table_name: str, row):
    row = dict(row)
    kind = SOURCES[table_name]
    run_id = row["id"] if kind == "run" else row.get("run_id")
    run = source_row(connection, "runs", run_id) if run_id and kind != "run" else None
    workspace_id = row.get("workspace_id") or (run or {}).get("workspace_id")
    system_id = row.get("system_id") or (run or {}).get("system_id")
    owner_id = (
        row.get("initiated_by_user_id")
        or row.get("user_id")
        or row.get("created_by")
        or row.get("created_by_user_id")
        or (run or {}).get("initiated_by_user_id")
    )
    parent_id = activity_id("run", run_id) if run_id and kind != "run" else None
    if row.get("parent_run_id"):
        parent_id = activity_id("run", row["parent_run_id"])
    if row.get("invocation_id"):
        parent_id = activity_id("skill_invocation", row["invocation_id"])
    if kind == "delivery_receipt":
        window = source_row(connection, "service_windows", row["window_id"])
        if window and window["workspace_id"] == workspace_id:
            system_id = window["system_id"]
        parent_id = activity_id("service_window", row["window_id"])
    native_status = "published" if kind == "delivery_receipt" else row.get("status")
    native_status = native_status if native_status in STATUS_MAP else "unknown"
    # Provider costs have explicit coverage. Historical SkillInvocation.cost=0
    # is intentionally not evidence. Parent and child costs are never summed.
    cost = number(row.get("provider_cost_usd"))
    if kind == "skill_invocation" and row.get("cost_measured") is not True:
        cost = None
    if kind == "compute_run":
        cost = number(row.get("cost_usd"))
    duration = number(row.get("duration_ms", row.get("latency_ms", row.get("train_duration_ms"))))
    created = row.get("created_at") or row.get("started_at") or row.get("published_at")
    if created is None or not workspace_id:
        return None  # No invented tenant or timestamp for historical incomplete rows.
    finished = (
        row.get("finished_at")
        or row.get("completed_at")
        or row.get("trained_at")
        or row.get("published_at")
    )
    measurements = {
        "duration_ms": duration,
        "provider_cost_usd": cost,
        "cost_known": cost is not None,
    }
    measurements["cost_basis"] = (
        "infrastructure_allocation" if kind == "compute_run" else "provider_tariff"
    )
    if kind == "skill_invocation":
        from .execution_metadata import invocation_cost

        measurements.update(invocation_cost(cost=row.get("cost"), provider_cost_usd=row.get("provider_cost_usd"),
                                            cost_measured=row.get("cost_measured"), metrics=row.get("metrics")))
    if kind == "compute_run":
        measurements.update(
            {
                key: number(row.get(key))
                for key in ("cpu_cores", "memory_mb", "core_hours", "reserved_core_hours")
            }
        )
        measurements["resource_basis"] = "requested_resources_x_wall_time"
    execution_revision = None
    if kind == "run":
        from .execution_metadata import transitions

        # Identity/transition metadata only: no errors, labels, decisions, state,
        # outputs or timestamps. Token-only writes cannot invalidate this view.
        public = [{key: value for key, value in item.items() if key != "t"}
                  for item in transitions(row.get("checkpoints"), row["id"])]
        if public:
            execution_revision = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
    elif kind == "skill_invocation":
        from .execution_metadata import correlation

        execution_revision = hashlib.sha256(json.dumps(correlation(row.get("trace")), sort_keys=True).encode()).hexdigest()
    return {
        **({"execution_revision": execution_revision} if execution_revision else {}),
        "kind": kind,
        "native_id": row["id"],
        "workspace_id": workspace_id,
        "system_id": system_id,
        "run_id": run_id,
        "owner_id": owner_id,
        "parent_activity_id": parent_id,
        "status": "unknown" if kind == "compute_run" and row.get("outcome_unknown") is True else STATUS_MAP.get(native_status, "unknown"),
        "native_status": native_status,
        "created_at": iso(created),
        "started_at": iso(row.get("started_at")),
        "finished_at": iso(finished),
        "deadline_at": iso(row.get("deadline_at")),
        "cancel_requested": bool(row.get("cancel_requested", False)),
        "progress": None,
        "measurements": measurements,
        "resource_coverage": "allocated" if kind == "compute_run" else "unavailable",
        "related_recipe_execution_id": row.get("recipe_execution_id"),
    }


def next_sequence(connection, workspace_id: str) -> int:
    """The row lock lasts until the source transaction commits or rolls back.

    Unlike a SQL sequence/serial, a later committed event cannot overtake an
    uncommitted lower cursor in the same workspace.
    """
    table = ActivityWorkspaceCursor.__table__
    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("ACTIVITY_DATABASE_UNSUPPORTED")
    connection.execute(
        insert(table)
        .values(workspace_id=workspace_id, sequence=0)
        .on_conflict_do_nothing(index_elements=["workspace_id"])
    )
    return connection.execute(
        update(table)
        .where(table.c.workspace_id == workspace_id)
        .values(sequence=table.c.sequence + 1)
        .returning(table.c.sequence)
    ).scalar_one()


def project(connection, table_name: str, identifier: str, *, origin="observed"):
    # Backfill must obey the same source→cursor lock order as live mutations;
    # otherwise a stale historical read could overwrite a just-committed state.
    row = source_row(connection, table_name, identifier, lock=True)
    if row is None:
        # Purged native objects are removed rather than exposing stale identity
        # or retaining payload-free tombstones outside native retention policy.
        connection.execute(
            Activity.__table__.delete().where(
                Activity.id == activity_id(SOURCES[table_name], identifier)
            )
        )
        return None
    snapshot = metadata(connection, table_name, row)
    if snapshot is None:
        return None
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    identifier = activity_id(snapshot["kind"], snapshot["native_id"])
    table = Activity.__table__
    old = connection.execute(select(table).where(table.c.id == identifier)).mappings().first()
    if old and old["snapshot_digest"] == digest:
        return identifier
    sequence = next_sequence(connection, snapshot["workspace_id"])
    # Re-read after the tenant counter lock for concurrent historical backfills.
    old = connection.execute(select(table).where(table.c.id == identifier)).mappings().first()
    if old and old["snapshot_digest"] == digest:
        return identifier
    version = (old["version"] if old else 0) + 1
    now = datetime.utcnow()
    values = {
        key: snapshot[key]
        for key in (
            "workspace_id",
            "kind",
            "native_id",
            "system_id",
            "run_id",
            "owner_id",
            "parent_activity_id",
            "status",
            "native_status",
        )
    }
    values.update(
        version=version,
        snapshot=snapshot,
        snapshot_digest=digest,
        origin=old["origin"] if old else origin,
        created_at=datetime.fromisoformat(snapshot["created_at"].replace("Z", "+00:00")).replace(
            tzinfo=None
        ),
        updated_at=now,
        **measured_columns(snapshot),
    )
    if old:
        connection.execute(update(table).where(table.c.id == identifier).values(**values))
    else:
        connection.execute(table.insert().values(id=identifier, **values))
    connection.execute(
        ActivityEvent.__table__.insert().values(
            id=str(uuid4()),
            workspace_id=snapshot["workspace_id"],
            sequence=sequence,
            activity_id=identifier,
            version=version,
            event_type="activity.snapshot"
            if not old and origin == "snapshot_only"
            else "activity.updated",
            payload={key: snapshot[key] for key in ("kind", "status", "native_status")},
            occurred_at=now,
        )
    )
    return identifier


def backfill(db, *, kind: str, after_id: str | None = None, limit: int = 200):
    """One bounded snapshot page; caller commits and persists its continuation."""
    if kind not in KINDS or not 1 <= limit <= 500:
        raise ValueError("ACTIVITY_BACKFILL_INVALID")
    table_name = next(name for name, value in SOURCES.items() if value == kind)
    table = Base.metadata.tables[table_name]
    statement = select(table.c.id).order_by(table.c.id).limit(limit)
    if after_id:
        statement = statement.where(table.c.id > after_id)
    connection = db.connection()
    ids = list(connection.execute(statement).scalars())
    for identifier in ids:
        project(connection, table_name, identifier, origin="snapshot_only")
    return {"processed": len(ids), "next_id": ids[-1] if len(ids) == limit else None}
