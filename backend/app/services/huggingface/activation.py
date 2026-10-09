"""Durable adapter activation: prepare on hub-fetch, execute on the chosen runtime."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta
from uuid import uuid4

from app.core.config import settings
from app.models.huggingface import HubArtifactUsage
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface.errors import HFError


def request_activation(
    db, *, workspace_id: str, artifact_id: str, usage: str, runtime: str, actor: str
):
    from app.services.huggingface import registry

    if (
        usage not in {"forecasting", "embedding", "reranker"}
        or runtime not in {"ml", "rag"}
        or (usage == "forecasting" and runtime != "ml")
    ):
        raise HFError("HF_ADAPTER_INCOMPATIBLE", "Unsupported adapter/runtime combination.")
    registry.admission_lock(db)
    registry.require_artifact(db, workspace_id, artifact_id, usage=usage)
    request = {"artifact_id": artifact_id, "usage": usage, "runtime": runtime}
    pending = (
        db.query(WorkspaceJob)
        .filter_by(workspace_id=workspace_id, kind="hf_adapter_activate")
        .filter(WorkspaceJob.status.in_(["queued", "running"]))
        .all()
    )
    for job in pending:
        if job.input_ref == request:
            db.commit()
            return job
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=workspace_id,
        kind="hf_adapter_activate",
        title=f"Activate {usage} adapter",
        input_ref=request,
        result={},
        status="queued",
        stage="dispatch_pending",
        queued_at=datetime.utcnow(),
        created_by_user_id=actor,
    )
    db.add(job)
    registry._audit(db, workspace_id, "adapter.activation.requested", actor, request)
    db.commit()
    dispatch_activation(db, job)
    return job


def dispatch_activation(db, job):
    from celery import chain

    from app.workers.celery_app import celery_app

    if job.status != "queued":
        return
    target = job.input_ref
    queue = (
        settings.celery_ml_deep_queue
        if target["runtime"] == "ml"
        else settings.celery_task_default_queue
    )
    # This workflow remains on the proper images even when the web process is
    # configured eager: the preparation process owns the writable cache.
    try:
        prepare = celery_app.signature(
            "agentium.hf_materialize_cache",
            args=[job.workspace_id, target["artifact_id"]],
            immutable=True,
            queue="hub_fetch",
        )
        prepare.link_error(
            celery_app.signature(
                "agentium.hf_adapter_prepare_failed", args=[job.id], immutable=True, queue=queue
            )
        )
        probe = celery_app.signature(
            "agentium.hf_validate_adapter", args=[job.id], immutable=True, queue=queue
        )
        result = chain(prepare, probe).apply_async()
        job.result = {"task_id": result.id}
        job.stage = "materializing"
    except Exception:
        job.stage = "dispatch_pending"
    db.commit()


def fail_preparation(job_id: str) -> dict:
    from app.db.base import SessionLocal

    with SessionLocal() as db:
        job = (
            db.query(WorkspaceJob)
            .filter_by(id=job_id, kind="hf_adapter_activate")
            .with_for_update()
            .first()
        )
        if job and job.status == "queued":
            job.status, job.stage, job.error = "failed", "failed", "HF_CACHE_PREPARATION_FAILED"
            job.completed_at = datetime.utcnow()
            db.commit()
        return {"job_id": job_id, "status": job.status if job else "missing"}


def run_activation(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface import registry
    from app.services.huggingface.access import require_job_actor
    from app.services.huggingface.adapters import authorized_manifest, validate_local_artifact
    from app.services.huggingface.cache import configured_cache
    from app.services.ml.runtime import runtime_fingerprint

    with SessionLocal() as db, ExitStack() as leases:
        job = (
            db.query(WorkspaceJob)
            .filter_by(id=job_id, kind="hf_adapter_activate")
            .with_for_update()
            .first()
        )
        if job is None:
            raise HFError("HF_JOB_NOT_FOUND", "Adapter activation job not found.", 404)
        if job.status != "queued":
            return {"job_id": job.id, "status": job.status}
        job.status, job.stage, job.progress, job.started_at = (
            "running",
            "validating",
            50,
            datetime.utcnow(),
        )
        request = dict(job.input_ref)
        workspace_id, actor = job.workspace_id, job.created_by_user_id
        db.commit()
        try:
            require_job_actor(db, job, kind="model")
            db.commit()
            # The dedicated ML worker is explicit. A misrouted delivery cannot
            # advertise another image's capabilities even if imports succeed.
            if request["runtime"] == "ml" and settings.ml_runtime != "ml-deep":
                raise HFError(
                    "HF_RUNTIME_MISSING", "ML artifact activation requires the ml-deep worker.", 409
                )
            manifest = authorized_manifest(
                workspace_id, request["artifact_id"], usage=request["usage"]
            )
            leases.enter_context(configured_cache().lease(request["artifact_id"], manifest))
            probe = validate_local_artifact(workspace_id, request["artifact_id"], request["usage"])
            probe["runtime_identity"] = runtime_fingerprint()
            probe["target_runtime"] = request["runtime"]
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
            registry.require_artifact(
                db, workspace_id, request["artifact_id"], usage=request["usage"]
            )
            row = (
                db.query(HubArtifactUsage)
                .filter_by(
                    workspace_id=workspace_id, kind="adapter", target_id=request["artifact_id"]
                )
                .first()
            )
            validations = dict((row.details_json or {}).get("validations", {})) if row else {}
            validations[f"{request['usage']}:{request['runtime']}"] = probe
            registry.register_usage(
                db,
                workspace_id,
                request["artifact_id"],
                "adapter",
                request["artifact_id"],
                details={"validations": validations, "latest": probe},
            )
            job.status, job.stage, job.progress, job.completed_at = (
                "completed",
                "ready",
                100,
                datetime.utcnow(),
            )
            job.result = {**job.result, "probe": probe}
            registry._audit(
                db,
                workspace_id,
                "adapter.activation.completed",
                actor,
                {"artifact_id": request["artifact_id"], "usage": request["usage"]},
            )
            db.commit()
            return {"job_id": job.id, "status": job.status, "probe": probe}
        except Exception as exc:
            db.rollback()
            job = db.query(WorkspaceJob).filter_by(id=job_id).with_for_update().one()
            if job.status not in {"cancelled", "completed"}:
                job.status, job.stage, job.completed_at = "failed", "failed", datetime.utcnow()
                job.error = getattr(exc, "code", "HF_ADAPTER_LOAD_FAILED")
                registry._audit(
                    db,
                    workspace_id,
                    "adapter.activation.failed",
                    actor,
                    {"artifact_id": request["artifact_id"], "code": job.error},
                )
                db.commit()
            return {"job_id": job.id, "status": job.status, "error_code": job.error}


def cancel_activation(
    db, workspace_id: str, job_id: str, *, actor: str, kind: str = "hf_adapter_activate"
):
    from app.services.huggingface import registry

    registry.admission_lock(db)
    job = (
        db.query(WorkspaceJob)
        .filter_by(id=job_id, workspace_id=workspace_id, kind=kind)
        .with_for_update()
        .first()
    )
    if job is None:
        raise HFError("HF_JOB_NOT_FOUND", "Adapter activation job not found.", 404)
    if job.status in {"queued", "running"}:
        job.status, job.stage, job.completed_at = "cancelled", "cancelled", datetime.utcnow()
        registry._audit(
            db,
            workspace_id,
            "legacy.migration.cancelled"
            if kind == "hf_legacy_migrate"
            else "adapter.activation.cancelled",
            actor,
            {"job_id": job.id},
        )
        db.commit()
    return job


def recover_activations(db) -> int:
    """Scheduled hub worker repair; an interrupted probe never creates a usage."""
    jobs = (
        db.query(WorkspaceJob)
        .filter(WorkspaceJob.kind.in_(["hf_adapter_activate", "hf_legacy_migrate"]))
        .filter(WorkspaceJob.status.in_(["queued", "running"]))
        .all()
    )
    cutoff = datetime.utcnow() - timedelta(seconds=settings.hf_import_timeout_seconds)
    recovered = 0
    for job in jobs:
        if job.updated_at < cutoff:
            job.status, job.stage, job.completed_at = "failed", "failed", datetime.utcnow()
            job.error = (
                "HF_MIGRATION_INTERRUPTED"
                if job.kind == "hf_legacy_migrate"
                else "HF_ADAPTER_INTERRUPTED"
            )
            db.commit()
            recovered += 1
        elif job.status == "queued" and job.stage == "dispatch_pending":
            if job.kind == "hf_legacy_migrate":
                from app.services.huggingface.legacy_migration import dispatch_migration

                dispatch_migration(db, job)
            else:
                dispatch_activation(db, job)
            recovered += 1
    return recovered
