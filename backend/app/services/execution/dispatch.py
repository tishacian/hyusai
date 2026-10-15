"""Transactional identifier-only submissions, at-least-once publication.

A publisher confirm acknowledges RabbitMQ persistence, never execution success.
Consumers must claim the native row before effects. Unknown outcomes are not
automatically retried as new attempts.
"""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, update

from app.core.config import settings
from app.models.execution_control import ExecutionDispatch


def _destination(kind, native):
    if kind == "recipe_execution":
        tasks = {
            "data_prep": "agentium.dataops_prepare",
            "ml_stream_score": "agentium.dataops_score",
            "sql_transform": "agentium.dataops_sql_execute",
        }
        task = tasks.get((native.input_json or {}).get("kind"))
        if task:
            return task, settings.celery_dataops_queue
    elif kind == "compute_run" and not native.recipe_execution_id:
        from app.services.compute_runs import INTERACTIVE, TASK_NAME

        return TASK_NAME, (
            settings.celery_connectors_interactive_queue
            if native.operation in INTERACTIVE
            else settings.celery_connectors_queue
        )
    elif kind == "ml_training":
        from app.services.tabular_ml import ML_TRAIN_TASK, get_family

        return ML_TRAIN_TASK, get_family(native.family).train_queue()
    elif kind == "run":
        if (native.execution_policy or {}).get("engine") == "temporal":
            return "agentium.execution_temporal_start", settings.celery_orchestration_queue
        return "agentium.execution_run", settings.celery_task_default_queue
    raise ValueError("EXECUTION_DISPATCH_KIND_UNSUPPORTED")


def stage(db, kind, native, *, deadline_at=None):
    """Caller must call before its first commit of the native submission."""
    task, queue = _destination(kind, native)
    db.flush()
    key = f"{kind}:{native.id}:initial:v1"
    row = db.query(ExecutionDispatch).filter_by(dedupe_key=key).one_or_none()
    if row:
        return row
    row = ExecutionDispatch(
        workspace_id=native.workspace_id,
        entity_kind=kind,
        entity_id=native.id,
        task_name=task,
        task_queue=queue,
        dedupe_key=key,
        task_id=str(uuid4()),
        deadline_at=deadline_at,
    )
    db.add(row)
    native.celery_task_id = row.task_id
    db.flush()
    return row


def defer_native(db, kind, identifier, *, code, seconds=5):
    db.execute(
        update(ExecutionDispatch)
        .where(
            ExecutionDispatch.entity_kind == kind,
            ExecutionDispatch.entity_id == identifier,
            ExecutionDispatch.state.notin_(["dead", "cancelled"]),
        )
        .values(
            state="pending",
            available_at=datetime.utcnow() + timedelta(seconds=seconds),
            lease_token=None,
            lease_expires_at=None,
            error_code=code,
        )
    )


def _native(db, row, *, lock=True):
    from app.models.compute_run import ComputeRun
    from app.models.recipe import RecipeExecution
    from app.models.run import Run
    from app.models.tabular import MLModel

    cls = {
        "recipe_execution": RecipeExecution,
        "compute_run": ComputeRun,
        "ml_training": MLModel,
        "run": Run,
    }.get(row.entity_kind)
    # The pending check and expiry mutation share the native claim lock. Never
    # wait while holding an outbox row: a native owner may need this same intent
    # when deferring admission. A busy native is retried on a later tick.
    if cls is None:
        return None
    query = db.query(cls).filter_by(id=row.entity_id, workspace_id=row.workspace_id)
    if lock:
        query = query.with_for_update(skip_locked=True)
    return query.populate_existing().first()


def _expire_pending(db, row, native, now):
    # No worker has claimed this submission. Settle through native mutators.
    if row.entity_kind == "recipe_execution":
        from app.services.recipe_executions import finalize_execution

        finalize_execution(native, status="timed_out", error="EXECUTION_DISPATCH_DEADLINE")
    elif row.entity_kind == "compute_run":
        from app.services.compute_runs import _finish

        _finish(native, "timed_out", "EXECUTION_DISPATCH_DEADLINE", now)
    elif row.entity_kind == "ml_training":
        from app.services.tabular_ml import _finalize

        _finalize(native, status="failed", error="EXECUTION_DISPATCH_DEADLINE")
    elif row.entity_kind == "run":
        native.status, native.error, native.completed_at = (
            "failed",
            "EXECUTION_DISPATCH_DEADLINE",
            now,
        )


def publish_due(session_factory, *, publisher=None, limit=100, now=None):
    """Bounded short transactions, publish outside locks, fence acknowledgements."""
    if publisher is None:
        from app.workers.celery_app import celery_app

        publisher = celery_app.send_task
    count = 0
    now = now or datetime.utcnow()
    for _ in range(min(max(limit, 1), 500)):
        with session_factory() as db:
            row = (
                db.query(ExecutionDispatch)
                .filter(
                    or_(
                        and_(
                            ExecutionDispatch.state == "pending",
                            ExecutionDispatch.available_at <= now,
                        ),
                        and_(
                            ExecutionDispatch.state == "leased",
                            ExecutionDispatch.lease_expires_at <= now,
                        ),
                    )
                )
                .order_by(ExecutionDispatch.available_at, ExecutionDispatch.id)
                .with_for_update(skip_locked=True)
                .first()
            )
            if row is None:
                break
            native = _native(db, row)
            if native is None:
                if _native(db, row, lock=False) is None:
                    row.state, row.error_code = "cancelled", "EXECUTION_NATIVE_NOT_FOUND"
                else:
                    # Revisit busy native work later, avoiding head-of-line
                    # starvation of other tenants while retaining its intent.
                    row.available_at = now + timedelta(seconds=1)
                    if row.state == "leased":
                        row.lease_expires_at = now + timedelta(seconds=1)
                db.commit()
                continue
            if native.status not in {"queued", "pending"} or getattr(
                native, "cancel_requested", False
            ):
                row.state, row.error_code = "cancelled", "EXECUTION_NATIVE_NOT_PENDING"
                db.commit()
                continue
            if row.deadline_at and row.deadline_at <= now:
                _expire_pending(db, row, native, now)
                row.state, row.error_code = "dead", "EXECUTION_DISPATCH_DEADLINE"
                db.commit()
                continue
            token = str(uuid4())
            row.state, row.lease_token = "leased", token
            row.lease_expires_at = now + timedelta(seconds=30)
            row.attempts += 1
            identifier, task, queue, task_id, native_id = (
                row.id,
                row.task_name,
                row.task_queue,
                row.task_id,
                row.entity_id,
            )
            attempt = row.attempts
            db.commit()
        try:
            publisher(
                task, args=[native_id], task_id=task_id, queue=queue, retry=False, delivery_mode=2
            )
        except Exception:
            # Broker exception text can contain credentials; store a fixed code.
            values = dict(
                state="pending",
                error_code="EXECUTION_BROKER_UNAVAILABLE",
                available_at=now + timedelta(seconds=min(60, 2 ** min(attempt, 6))),
                lease_token=None,
                lease_expires_at=None,
            )
        else:
            values = dict(
                state="published",
                published_at=now,
                error_code=None,
                lease_token=None,
                lease_expires_at=None,
            )
            count += 1
        with session_factory() as db:
            db.execute(
                update(ExecutionDispatch)
                .where(
                    ExecutionDispatch.id == identifier,
                    ExecutionDispatch.state == "leased",
                    ExecutionDispatch.lease_token == token,
                )
                .values(**values)
            )
            db.commit()
    return count
