"""Verified legacy ML bindings without rewriting historical training provenance.

A migration associates a trained v1 model with an already qualified Hub artifact
only when its original foundation descriptor, the provisioned v1 inventory and
the artifact's full inventory agree. Predictions keep the trained export, while
future executions now require the artifact grant. Unmapped v1 models keep working.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.core.config import settings
from app.models.huggingface import HubArtifactUsage
from app.models.tabular import MLModel
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface.errors import HFError


def migration_for(db, model):
    return (
        db.query(HubArtifactUsage)
        .filter_by(workspace_id=model.workspace_id, kind="ml_migration", target_id=model.id)
        .first()
    )


def _model(db, workspace_id, model_id):
    model = db.query(MLModel).filter_by(id=model_id, workspace_id=workspace_id).first()
    if model is None:
        raise HFError("HF_NOT_FOUND", "Trained model not found in this workspace.", 404)
    source = (model.params_json or {}).get("foundation") or {}
    if (
        model.status != "ready"
        or model.family not in {"forecasting_deep", "tabular_deep"}
        or source.get("artifact_id")
        or not source.get("model_id")
    ):
        raise HFError(
            "HF_MIGRATION_INCOMPATIBLE",
            "Migration requires a ready ML model using a legacy v1 foundation.",
            409,
        )
    return model, source, "forecasting" if model.family == "forecasting_deep" else "embedding"


def _probe(db, workspace_id, artifact_id, kind):
    row = (
        db.query(HubArtifactUsage)
        .filter_by(
            workspace_id=workspace_id, kind="adapter", target_id=artifact_id, status="active"
        )
        .first()
    )
    probe = (row.details_json or {}).get("validations", {}).get(f"{kind}:ml") if row else None
    if not probe or probe.get("validation") != "loaded_and_inferred":
        raise HFError(
            "HF_ADAPTER_NOT_VALIDATED",
            "Activate this artifact on the ML runtime before migrating a legacy model.",
            409,
        )
    return probe


def request_migration(db, *, workspace_id, model_id, artifact_id, actor):
    from app.services.huggingface import registry

    registry.admission_lock(db)
    model, source, kind = _model(db, workspace_id, model_id)
    registry.require_artifact(db, workspace_id, artifact_id, usage=kind)
    _probe(db, workspace_id, artifact_id, kind)
    previous = migration_for(db, model)
    if previous and previous.artifact_id != artifact_id:
        raise HFError(
            "HF_MIGRATION_CONFLICT",
            "This model already has a verified binding to another artifact.",
            409,
        )
    request = {"model_id": model_id, "artifact_id": artifact_id}
    for existing in (
        db.query(WorkspaceJob)
        .filter_by(workspace_id=workspace_id, kind="hf_legacy_migrate")
        .filter(WorkspaceJob.status.in_(["queued", "running"]))
        .all()
    ):
        if existing.input_ref == request:
            db.commit()
            return existing
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=workspace_id,
        kind="hf_legacy_migrate",
        title="Verify legacy model migration",
        status="queued",
        stage="dispatch_pending",
        input_ref=request,
        result={},
        queued_at=datetime.utcnow(),
        created_by_user_id=actor,
    )
    db.add(job)
    registry._audit(db, workspace_id, "legacy.migration.requested", actor, request)
    db.commit()
    dispatch_migration(db, job)
    return job


def dispatch_migration(db, job):
    from app.workers.celery_app import celery_app

    if job.status != "queued":
        return
    try:
        result = celery_app.send_task(
            "agentium.hf_migrate_legacy", args=[job.id], queue=settings.celery_ml_deep_queue
        )
        job.result, job.stage = {"task_id": result.id}, "queued"
    except Exception:
        job.stage = "dispatch_pending"
    db.commit()


def verify_legacy_identity(source: dict, local, snapshot) -> dict:
    # The v1 fingerprint binds all original files, model_id and revision. It
    # prevents silently mapping a currently provisioned replacement onto a
    # model that was trained before that operator change.
    for key in ("model_id", "revision", "kind", "upstream_id", "fingerprint"):
        if source.get(key) != local.public().get(key):
            raise HFError(
                "HF_MIGRATION_IDENTITY_MISMATCH",
                "The provisioned v1 model differs from the original training foundation.",
                409,
            )
    manifest = snapshot.manifest
    imported_files = {name: entry["sha256"] for name, entry in manifest["files"].items()}
    if (
        manifest["repo_id"] != local.upstream_id
        or manifest["revision"] != local.revision
        or imported_files != local.files
    ):
        raise HFError(
            "HF_MIGRATION_IDENTITY_MISMATCH",
            "Migration requires exactly the same repository, commit and complete SHA-256 file inventory.",
            409,
        )
    return {
        "original_foundation": dict(source),
        "artifact_fingerprint": snapshot.fingerprint,
        "repo_id": local.upstream_id,
        "revision": local.revision,
        "files": dict(local.files),
    }


def run_migration(job_id):
    from app.db.base import SessionLocal
    from app.services.huggingface import registry
    from app.services.huggingface.access import require_job_actor
    from app.services.huggingface.adapters import (
        authorized_manifest,
        runtime_versions,
        validate_layout,
    )
    from app.services.huggingface.cache import configured_cache
    from app.services.ml.local_models import resolve_model

    with SessionLocal() as db:
        job = (
            db.query(WorkspaceJob)
            .filter_by(id=job_id, kind="hf_legacy_migrate")
            .with_for_update()
            .first()
        )
        if job is None:
            raise HFError("HF_NOT_FOUND", "Migration job not found.", 404)
        if job.status != "queued":
            return {"job_id": job.id, "status": job.status}
        job.status, job.stage, job.started_at = "running", "verifying", datetime.utcnow()
        request, workspace_id, actor = dict(job.input_ref), job.workspace_id, job.created_by_user_id
        db.commit()
        try:
            require_job_actor(db, job, kind="model")
            if settings.ml_runtime != "ml-deep":
                raise HFError(
                    "HF_RUNTIME_MISSING", "Legacy migration requires the ml-deep worker.", 409
                )
            model, source, kind = _model(db, workspace_id, request["model_id"])
            source = dict(source)
            probe = dict(_probe(db, workspace_id, request["artifact_id"], kind))
            db.commit()
            manifest = authorized_manifest(workspace_id, request["artifact_id"], usage=kind)
            with configured_cache().lease(request["artifact_id"], manifest) as snapshot:
                contract = validate_layout(snapshot, kind)
                packages = runtime_versions(contract["engine"])
                if (
                    probe.get("fingerprint") != snapshot.fingerprint
                    or probe.get("runtime") != packages
                ):
                    raise HFError(
                        "HF_ADAPTER_NOT_VALIDATED",
                        "The artifact must be revalidated for this runtime.",
                        409,
                    )
                local = resolve_model(source["model_id"], kind=kind)
                proof = verify_legacy_identity(source, local, snapshot)
                registry.admission_lock(db)
                job = (
                    db.query(WorkspaceJob)
                    .filter_by(id=job_id)
                    .populate_existing()
                    .with_for_update()
                    .one()
                )
                if job.status != "running":
                    return {"job_id": job.id, "status": job.status}
                require_job_actor(db, job, kind="model")
                db.expire(model)
                current_model, current_source, _ = _model(db, workspace_id, request["model_id"])
                if current_source != source:
                    raise HFError(
                        "HF_MIGRATION_IDENTITY_MISMATCH",
                        "The model changed while migration was being verified.",
                        409,
                    )
                previous = migration_for(db, current_model)
                if previous and previous.artifact_id != request["artifact_id"]:
                    raise HFError(
                        "HF_MIGRATION_CONFLICT",
                        "The model was bound to another artifact concurrently.",
                        409,
                    )
                registry.register_usage(
                    db,
                    workspace_id,
                    request["artifact_id"],
                    "ml_migration",
                    current_model.id,
                    details={
                        **proof,
                        "verified_by": actor,
                        "verified_at": datetime.utcnow().isoformat(),
                    },
                )
                job.status, job.stage, job.progress, job.completed_at = (
                    "completed",
                    "ready",
                    100,
                    datetime.utcnow(),
                )
                job.result = {
                    "artifact_id": request["artifact_id"],
                    "model_id": current_model.id,
                    "migration": {
                        "files_verified": len(local.files),
                        "original_provenance_preserved": True,
                        "repo_id": local.upstream_id,
                        "revision": local.revision,
                    },
                }
                registry._audit(db, workspace_id, "legacy.migration.completed", actor, request)
                db.commit()
                return {"job_id": job.id, "status": job.status, **job.result}
        except Exception as exc:
            db.rollback()
            job = db.query(WorkspaceJob).filter_by(id=job_id).with_for_update().one()
            if job.status not in {"completed", "cancelled"}:
                job.status, job.stage, job.error, job.completed_at = (
                    "failed",
                    "failed",
                    getattr(exc, "code", "HF_MIGRATION_FAILED"),
                    datetime.utcnow(),
                )
                registry._audit(
                    db,
                    workspace_id,
                    "legacy.migration.failed",
                    actor,
                    {**request, "code": job.error},
                )
                db.commit()
            return {"job_id": job.id, "status": job.status, "error_code": job.error}
