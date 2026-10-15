"""Workspace policy, atomic inference admission and bounded journal retention."""

import hashlib
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.models.ml_governance import MLAdmissionCounter, MLWorkspaceLock
from app.models.tabular import MLModel, MLModelApiKey, MLPrediction
from app.models.workspace import Workspace
from app.services.tabular_datasets import TabularError


class MLPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    promotion_requires_approval: bool = False
    store_inputs: bool = True
    prediction_retention_days: int = Field(default=30, ge=1, le=3650)
    predict_requests_per_minute: int = Field(default=120, ge=1)
    predict_rows_per_minute: int = Field(default=12000, ge=1)
    max_exposed_models: int = Field(default=100, ge=1)


def policy(db, workspace_id):
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or not workspace.is_active or workspace.deleted_at:
        raise TabularError(
            code="ML_WORKSPACE_UNAVAILABLE",
            message="The model workspace is unavailable.",
            status_code=403,
        )
    defaults = {
        "prediction_retention_days": settings.ml_prediction_retention_days,
        "predict_requests_per_minute": settings.ml_predict_rate_per_minute,
        "predict_rows_per_minute": settings.ml_predict_rows_per_minute,
        "max_exposed_models": settings.ml_max_exposed_models,
    }
    try:
        value = MLPolicy.model_validate(
            {**defaults, **((workspace.settings or {}).get("ml") or {})}
        )
    except (ValueError, TypeError) as exc:
        raise TabularError(
            code="ML_POLICY_INVALID", message="The workspace ML policy is invalid.", status_code=409
        ) from exc
    # Workspace administrators may tighten operator budgets, not raise them.
    for key, ceiling in defaults.items():
        setattr(value, key, min(getattr(value, key), ceiling))
    return value


def lock_workspace(db, workspace_id):
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    db.execute(
        insert(MLWorkspaceLock)
        .values(workspace_id=workspace_id, generation=0)
        .on_conflict_do_nothing(index_elements=["workspace_id"])
    )
    db.execute(
        update(MLWorkspaceLock)
        .where(MLWorkspaceLock.workspace_id == workspace_id)
        .values(generation=MLWorkspaceLock.generation + 1)
    )


def require_exposure_capacity(db, model):
    limits = locked_policy(db, model.workspace_id)
    now = datetime.utcnow()
    keys = db.query(MLModelApiKey.model_id).filter(
        MLModelApiKey.workspace_id == model.workspace_id,
        MLModelApiKey.revoked_at.is_(None),
        or_(MLModelApiKey.expires_at.is_(None), MLModelApiKey.expires_at > now),
        or_(MLModelApiKey.revoke_after.is_(None), MLModelApiKey.revoke_after > now),
    )
    exposed = {
        row[0]
        for row in db.query(MLModel.slug)
        .filter(
            MLModel.workspace_id == model.workspace_id,
            or_(MLModel.published_skill_id.isnot(None), MLModel.id.in_(keys)),
        )
        .distinct()
    }
    if model.slug not in exposed and len(exposed) >= limits.max_exposed_models:
        from app.services.ml_operations import record_exposure_refusal

        record_exposure_refusal(db, model)
        raise TabularError(
            code="ML_EXPOSURE_QUOTA_EXCEEDED",
            message="The workspace model exposure quota is exhausted.",
            status_code=409,
        )


def locked_policy(db, workspace_id):
    """Read the committed policy after acquiring its mutation lock.

    Authentication may have loaded this Workspace before a competing policy
    update committed. Reload after waiting, without changing policy(), whose
    configuration caller deliberately validates an unflushed candidate.
    """
    lock_workspace(db, workspace_id)
    db.get(Workspace, workspace_id, populate_existing=True)
    return policy(db, workspace_id)


def admit(db, model, *, rows, key_id=None, now=None):
    """One transaction reserves both model and key counters across all workers."""
    limits = policy(db, model.workspace_id)
    now = now or datetime.utcnow()
    window = now.replace(second=0, microsecond=0)
    count = max(1, int(rows))
    scopes = [f"{model.workspace_id}:lineage:{model.slug}"]
    if key_id:
        scopes.append(f"{model.workspace_id}:key:{key_id}")
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    try:
        with db.begin_nested():
            for raw in sorted(scopes):
                scope = hashlib.sha256(raw.encode()).hexdigest()
                statement = insert(MLAdmissionCounter).values(
                    scope=scope, window_at=window, requests=0, rows=0
                )
                db.execute(statement.on_conflict_do_nothing(index_elements=["scope", "window_at"]))
                changed = db.execute(
                    update(MLAdmissionCounter)
                    .where(
                        MLAdmissionCounter.scope == scope,
                        MLAdmissionCounter.window_at == window,
                        MLAdmissionCounter.requests < limits.predict_requests_per_minute,
                        MLAdmissionCounter.rows + count <= limits.predict_rows_per_minute,
                    )
                    .values(
                        requests=MLAdmissionCounter.requests + 1,
                        rows=MLAdmissionCounter.rows + count,
                    )
                )
                if changed.rowcount != 1:
                    raise TabularError(
                        code="ML_RATE_LIMITED",
                        message="The model inference budget is exhausted for this minute.",
                        status_code=429,
                        details={"retry_after": max(1, 60 - now.second)},
                    )
        db.commit()
    except TabularError:
        # A failed multi-scope reservation leaves neither scope charged.
        raise


def inputs_allowed(db, workspace_id, store=True):
    return bool(store and policy(db, workspace_id).store_inputs)


def purge_predictions(db, *, now=None):
    from app.models.workspace_job import WorkspaceJob

    now = now or datetime.utcnow()
    removed = 0
    # Pending shadow work owns a journal reference until settled. Limit each
    # pass rather than holding the entire journal or workspace table in memory.
    cursor = ""
    while True:
        workspaces = (
            db.query(Workspace)
            .filter(
                Workspace.id > cursor, Workspace.is_active.is_(True), Workspace.deleted_at.is_(None)
            )
            .order_by(Workspace.id)
            .limit(100)
            .all()
        )
        if not workspaces:
            break
        cursor = workspaces[-1].id
        for workspace in workspaces:
            cutoff = now - timedelta(days=policy(db, workspace.id).prediction_retention_days)
            pending = (
                db.query(WorkspaceJob)
                .filter(
                    WorkspaceJob.workspace_id == workspace.id,
                    WorkspaceJob.kind == "ml_shadow",
                    WorkspaceJob.status.in_(["created", "queued", "running"]),
                )
                .all()
            )
            retained = {str((job.input_ref or {}).get("prediction_id")) for job in pending}
            records = (
                db.query(MLPrediction)
                .filter(
                    MLPrediction.workspace_id == workspace.id,
                    MLPrediction.created_at < cutoff,
                    MLPrediction.id.notin_(retained),
                )
                .order_by(MLPrediction.created_at, MLPrediction.id)
                .limit(settings.ml_retention_batch_size)
                .all()
            )
            for row in records:
                db.delete(row)
            removed += len(records)
            db.commit()
    db.query(MLAdmissionCounter).filter(
        MLAdmissionCounter.window_at < now - timedelta(days=1)
    ).delete(synchronize_session=False)
    db.commit()
    return removed
