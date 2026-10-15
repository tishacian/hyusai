"""Admission and fencing on the existing training authority, MLModel."""

from datetime import datetime, timedelta

from sqlalchemy import update

from app.core.config import settings
from app.models.tabular import MLModel

from . import admission
from .dispatch import defer_native, stage
from .rollout import durable_for, enabled_for


def register(db, model):
    if model.execution_policy is None and enabled_for(
        db, model.workspace_id, "execution_control_enabled"
    ):
        model.execution_policy = {
            "version": 1,
            "cpu_cores": settings.ml_train_threads,
            "memory_mb": settings.ml_train_memory_limit_mb,
        }
        model.deadline_at = datetime.utcnow() + timedelta(seconds=settings.ml_train_timeout_s)
    if durable_for(db, model.workspace_id):
        return stage(
            db,
            "ml_training",
            model,
            deadline_at=model.deadline_at
            or (datetime.utcnow() + timedelta(seconds=settings.ml_train_timeout_s)),
        )
    return None


def start(db, model):
    now = datetime.utcnow()
    try:
        if model.execution_policy is not None:
            admission.lock_scopes(db, model.workspace_id)
        from .control import parent_cancelled

        cancelled_parent = parent_cancelled(db, model.run_id, model.workspace_id)
        model = db.query(MLModel).filter_by(id=model.id).with_for_update().populate_existing().one()
        if model.status != "pending":
            db.rollback()
            return False
        if cancelled_parent:
            model.cancel_requested = True
        if model.cancel_requested or (model.deadline_at and model.deadline_at <= now):
            model.status = "cancelled" if model.cancel_requested else "failed"
            model.error = (
                "EXECUTION_CANCELLED" if model.cancel_requested else "EXECUTION_DEADLINE_EXCEEDED"
            )
            db.commit()
            return False
        if model.execution_policy is None:
            # Durable publication is at least once even when resource control
            # is disabled. Keep this claim lock until training is committed.
            return True
        allocation = admission.reserve(
            db,
            workspace_id=model.workspace_id,
            entity_kind="ml_training",
            entity_id=model.id,
            cpu_cores=model.execution_policy["cpu_cores"],
            memory_mb=model.execution_policy["memory_mb"],
            deadline_at=model.deadline_at,
            now=now,
        )
        model.lease_token = allocation.lease_token
        model.lease_expires_at = min(
            model.deadline_at, now + timedelta(seconds=settings.execution_lease_s)
        )
        model._native_lease_token = model.lease_token
        db.flush()
        return True
    except admission.AdmissionError as exc:
        db.rollback()
        defer_native(db, "ml_training", model.id, code=exc.code)
        db.commit()
        return False


def poll(db, model):
    if model.execution_policy is None:
        return False
    from app.db.base import SessionLocal

    now = datetime.utcnow()
    with SessionLocal() as heartbeat_db:
        changed = heartbeat_db.execute(
            update(MLModel)
            .where(
                MLModel.id == model.id,
                MLModel.status == "training",
                MLModel.cancel_requested.is_(False),
                MLModel.lease_token == getattr(model, "_native_lease_token", None),
                MLModel.lease_expires_at > now,
                MLModel.deadline_at > now,
            )
            .values(
                lease_expires_at=min(
                    model.deadline_at, now + timedelta(seconds=settings.execution_lease_s)
                )
            )
        )
        heartbeat_db.commit()
        return changed.rowcount != 1


def settle(db, model, status, error):
    if model.execution_policy is None:
        return status, error
    token = getattr(model, "_native_lease_token", None)
    model = db.query(MLModel).filter_by(id=model.id).with_for_update().populate_existing().one()
    now = datetime.utcnow()
    if not token or model.lease_token != token:
        raise admission.AdmissionError("EXECUTION_LEASE_LOST")
    if model.status in {"failed", "cancelled"}:
        status, error = model.status, model.error
    elif model.cancel_requested:
        status, error = "cancelled", "EXECUTION_CANCELLED"
    elif model.deadline_at <= now or model.lease_expires_at <= now:
        status, error = "failed", "EXECUTION_DEADLINE_EXCEEDED"
    admission.settle(
        db, entity_kind="ml_training", entity_id=model.id, token=token, outcome=status, now=now
    )
    return status, error


def begin_settlement(db, model, status, error):
    """Fence registry publication; settle allocation only after it returns."""
    if model.execution_policy is None:
        return status, error
    token = getattr(model, "_native_lease_token", None)
    model = db.query(MLModel).filter_by(id=model.id).with_for_update().populate_existing().one()
    now = datetime.utcnow()
    if not token or model.lease_token != token:
        raise admission.AdmissionError("EXECUTION_LEASE_LOST")
    if model.status in {"failed", "cancelled"}:
        return model.status, model.error
    if model.cancel_requested:
        return "cancelled", "EXECUTION_CANCELLED"
    if model.deadline_at <= now or model.lease_expires_at <= now:
        return "failed", "EXECUTION_DEADLINE_EXCEEDED"
    model.lease_expires_at = model.deadline_at
    db.flush()
    return status, error


def reap(db, *, limit=100):
    now = datetime.utcnow()
    rows = (
        db.query(MLModel)
        .filter(
            MLModel.execution_policy.isnot(None),
            MLModel.status == "training",
            ((MLModel.lease_expires_at <= now) | (MLModel.deadline_at <= now)),
        )
        .order_by(MLModel.id)
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    for model in rows:
        model.status, model.error = "failed", "EXECUTION_WORKER_LOST"
        admission.settle(
            db,
            entity_kind="ml_training",
            entity_id=model.id,
            token=model.lease_token,
            outcome="reconciliation_required",
            now=now,
            process_stopped=False,
        )
    return len(rows)
