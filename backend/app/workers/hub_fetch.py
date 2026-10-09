"""Worker-only Hub acquisition and cache preparation tasks."""

from datetime import UTC

from app.workers.celery_hub import celery_hub


@celery_hub.task(name="agentium.hf_import", acks_late=True, reject_on_worker_lost=True)
def hf_import(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface.registry import run_import

    with SessionLocal() as db:
        artifact = run_import(db, job_id)
        return {
            "job_id": job_id,
            "artifact_id": artifact.id if artifact is not None else None,
            "status": artifact.status if artifact is not None else "dataset_queued",
        }


@celery_hub.task(name="agentium.hf_materialize_cache", acks_late=True)
def materialize_cache(workspace_id: str, artifact_id: str) -> dict:
    from contextlib import ExitStack

    from app.db.base import SessionLocal
    from app.services.huggingface.cache import configured_cache
    from app.services.huggingface.errors import HFError
    from app.services.huggingface.registry import require_artifact
    from app.services.huggingface.storage import HubStore, blob_key

    with SessionLocal() as db, ExitStack() as sources:
        artifact = require_artifact(db, workspace_id, artifact_id)
        store = HubStore()

        def read_file(path, entry):
            key = entry.get("object_key")
            if key != blob_key(artifact, path):
                raise HFError(
                    "HF_PATH_INVALID", "The artifact contains an invalid model object reference."
                )
            return sources.enter_context(store.open(key))

        configured_cache().materialize(artifact.manifest_json, read_file)
        # Cache success alone never authorizes a use after grant revocation.
        require_artifact(db, workspace_id, artifact_id)
        db.commit()
        return {"artifact_id": artifact_id, "workspace_id": workspace_id, "status": "cached"}


@celery_hub.task(name="agentium.hf_cleanup_temporary", acks_late=True)
def cleanup_temporary(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.models.workspace_job import WorkspaceJob
    from app.services.huggingface.storage import HubStore

    with SessionLocal() as db:
        job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
        if job is not None and job.status not in {"failed", "cancelled", "completed"}:
            return {"job_id": job_id, "status": "retained"}
        HubStore().delete_temporary(job_id)
        return {"job_id": job_id, "status": "cleaned"}


@celery_hub.task(name="agentium.hf_recover", acks_late=True)
def recover_imports() -> dict:
    import logging
    import shutil
    from datetime import datetime, timedelta
    from pathlib import Path

    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.huggingface import HubArtifactUsage, HubImportReservation
    from app.models.workspace_job import WorkspaceJob
    from app.services.huggingface.activation import recover_activations
    from app.services.huggingface.offline import recover_bundle_jobs
    from app.services.huggingface.purge_job import drain_revoked_deployments
    from app.services.huggingface.registry import recover_imports as recover
    from app.services.huggingface.storage import HubStore

    store = HubStore()
    failures = 0
    disk_root = Path(settings.hf_cache_dir)
    while not disk_root.exists() and disk_root != disk_root.parent:
        disk_root = disk_root.parent
    disk = shutil.disk_usage(disk_root)
    occupied = disk.used / max(1, disk.total)
    if disk.free < settings.hf_disk_min_free_bytes or occupied >= 0.8:
        logging.getLogger(__name__).warning(
            "HF_DISK_PRESSURE: shared data disk requires attention",
            extra={
                "free_bytes": disk.free,
                "used_percent": round(occupied * 100, 1),
                "minimum_free_bytes": settings.hf_disk_min_free_bytes,
            },
        )
    with SessionLocal() as db:
        for repair in (recover, recover_activations, recover_bundle_jobs):
            try:
                repair(db)
            except Exception:
                # A temporarily unavailable broker must not prevent the other
                # recovery paths, disk warning, or temporary object cleanup.
                db.rollback()
                failures += 1
        try:
            unavailable = (
                db.query(HubArtifactUsage.artifact_id, HubArtifactUsage.workspace_id)
                .filter(
                    HubArtifactUsage.kind == "llm",
                    HubArtifactUsage.status.in_(["unavailable", "draining"]),
                )
                .distinct()
                .all()
            )
            for artifact_id, workspace_id in unavailable:
                drain_revoked_deployments(db, artifact_id, workspace_id=workspace_id)
        except Exception:
            db.rollback()
            failures += 1
        terminal = (
            db.query(WorkspaceJob)
            .filter(
                WorkspaceJob.kind == "hf_import",
                WorkspaceJob.status.in_(["completed", "failed", "cancelled"]),
            )
            .order_by(WorkspaceJob.updated_at.desc())
            .limit(200)
            .all()
        )
        for job in terminal:
            try:
                store.delete_temporary(job.id)
            except Exception:
                failures += 1
        active = {row.job_id for row in db.query(HubImportReservation).all()}
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.hf_import_timeout_seconds)
    return {
        "checked_jobs": len(terminal),
        "failures": failures,
        "disk_free_bytes": disk.free,
        "abandoned_uploads": store.cleanup_abandoned_uploads(older_than=cutoff),
        "abandoned_sources": store.cleanup_abandoned_sources(
            active_job_ids=active, older_than=cutoff
        ),
    }


@celery_hub.task(name="agentium.hf_purge_artifact", acks_late=True)
def hf_purge_artifact(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface.purge_job import run_purge_job

    with SessionLocal() as db:
        return run_purge_job(db, job_id)


@celery_hub.task(name="agentium.hf_drain_revoked", acks_late=True)
def hf_drain_revoked(artifact_id: str, workspace_id: str | None = None) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface.purge_job import drain_revoked_deployments

    with SessionLocal() as db:
        return drain_revoked_deployments(db, artifact_id, workspace_id=workspace_id)


@celery_hub.task(name="agentium.hf_bundle_import", acks_late=True)
def hf_bundle_import(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface.offline import run_bundle_job

    with SessionLocal() as db:
        return run_bundle_job(db, job_id)


@celery_hub.task(name="agentium.hf_bundle_export", acks_late=True)
def hf_bundle_export(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface.offline import run_bundle_job

    with SessionLocal() as db:
        return run_bundle_job(db, job_id)
