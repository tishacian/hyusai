"""Build missing immutable samples on the DataOps worker, never in the API."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import or_, update

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.tabular_datasets import TabularError

KIND = "dataops_build_sample"


def _stale_before():
    return datetime.utcnow() - timedelta(seconds=settings.dataops_t0_max_timeout_s + 90)


def ensure_samples(db, workspace_id, datasets):
    missing = [d for d in datasets.values() if not (d.lineage_json or {}).get("sample")]
    if not missing:
        return
    # Serialize requests for the same workspace; versions remain ready for all
    # non-preview consumers. sample_pending describes the sample, not its data.
    db.query(Workspace).filter_by(id=workspace_id).with_for_update().one()
    dispatch = []
    now = datetime.utcnow()
    unique = {d.id: d for d in missing}
    for original in (unique[key] for key in sorted(unique)):
        dataset = (
            db.query(TabularDataset)
            .filter_by(id=original.id, workspace_id=workspace_id, status="ready")
            .with_for_update()
            .populate_existing()
            .first()
        )
        if dataset is None:
            raise ValueError("DATAPREP_INPUT_UNAVAILABLE")
        if (dataset.lineage_json or {}).get("sample"):
            continue
        identity = str(uuid5(NAMESPACE_URL, f"agentium:sample:{workspace_id}:{dataset.id}"))
        job = db.get(WorkspaceJob, identity)
        if job is None:
            job = WorkspaceJob(
                id=identity,
                workspace_id=workspace_id,
                kind=KIND,
                title="Build dataset sample",
                status="queued",
                stage="sample_pending",
                input_ref={
                    "dataset_id": dataset.id,
                    "version": dataset.version,
                    "storage_key": dataset.storage_key,
                },
                queued_at=now,
                updated_at=now,
            )
            db.add(job)
            dispatch.append(identity)
        elif (
            job.status in {"queued", "failed"}
            and (job.updated_at or now) < now - timedelta(seconds=60)
        ) or (job.status == "running" and job.started_at and job.started_at < _stale_before()):
            job.status, job.stage, job.queued_at, job.updated_at = (
                "queued",
                "sample_pending",
                now,
                now,
            )
            dispatch.append(identity)
        dataset.lineage_json = {
            **(dataset.lineage_json or {}),
            "sample_status": "sample_pending",
            "sample_job_id": identity,
        }
    db.commit()
    for identity in dispatch:
        if settings.worker_eager_mode:
            run_sample(identity)
        else:
            from app.workers.celery_app import celery_app

            try:
                celery_app.send_task(
                    "agentium.dataops_build_sample",
                    args=[identity],
                    queue=settings.celery_dataops_queue,
                    task_id=identity,
                )
            except Exception:
                # A broker may have accepted the publish before a connection
                # failed. Leave the durable intention queued; retry after 60s.
                raise TabularError(
                    code="DATAPREP_SAMPLE_QUEUE_UNAVAILABLE",
                    message="The sample is queued; the worker connection is unavailable.",
                    status_code=503,
                ) from None
    for dataset in missing:
        db.refresh(dataset)
    if any(not (d.lineage_json or {}).get("sample") for d in missing):
        raise TabularError(
            code="DATAPREP_SAMPLE_PENDING",
            message="The sample is being prepared. Retry the preview shortly.",
            status_code=409,
        )


def run_sample(job_id):
    from app.db.base import SessionLocal
    from app.services.dataops.storage import (
        file_digest,
        is_delta,
        materialize_files,
        persist_sample,
    )

    with SessionLocal() as db:
        job = db.get(WorkspaceJob, job_id)
        if job is None or job.kind != KIND:
            return {"status": "missing"}
        if job.status == "completed":
            return {"status": "completed", **(job.result or {})}
        token = uuid4().hex
        workspace_id = job.workspace_id
        ref = {**job.input_ref, "lease": token}
        claim = db.execute(
            update(WorkspaceJob)
            .where(
                WorkspaceJob.id == job_id,
                WorkspaceJob.kind == KIND,
                or_(
                    WorkspaceJob.status.in_(["queued", "failed"]),
                    (WorkspaceJob.status == "running")
                    & (WorkspaceJob.started_at < _stale_before()),
                ),
            )
            .values(
                status="running",
                stage="building_sample",
                input_ref=ref,
                started_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        db.commit()
        if claim.rowcount != 1:
            return {"status": "running"}
        try:
            dataset = (
                db.query(TabularDataset)
                .filter_by(id=ref["dataset_id"], workspace_id=job.workspace_id, status="ready")
                .first()
            )
            if (
                dataset is None
                or dataset.version != ref["version"]
                or dataset.storage_key != ref["storage_key"]
            ):
                raise ValueError("DATAPREP_INPUT_UNAVAILABLE")
            with tempfile.TemporaryDirectory(prefix="dataops-sample-") as tmp:
                paths = None
                if not (dataset.lineage_json or {}).get("sample"):
                    paths = materialize_files(dataset, Path(tmp))
                    expected = (dataset.lineage_json or {}).get("storage", {}).get("sha256")
                    if expected and not is_delta(dataset) and file_digest(paths[0]) != expected:
                        raise ValueError("DATAPREP_INPUT_CHANGED")
                # Purge uses workspace -> dataset locks. Take the same order
                # before ANY PUT, so a late worker cannot recreate an object
                # after a completed physical purge.
                db.expire_all()
                db.query(Workspace).filter_by(id=workspace_id).with_for_update().one()
                dataset = (
                    db.query(TabularDataset)
                    .filter_by(id=ref["dataset_id"], workspace_id=workspace_id)
                    .with_for_update()
                    .one()
                )
                job = db.query(WorkspaceJob).filter_by(id=job_id).with_for_update().one()
                if job.input_ref.get("lease") != token:
                    return {"status": "superseded"}
                if (
                    dataset.status != "ready"
                    or dataset.version != ref["version"]
                    or dataset.storage_key != ref["storage_key"]
                ):
                    raise ValueError("DATAPREP_INPUT_UNAVAILABLE")
                if not (dataset.lineage_json or {}).get("sample"):
                    if paths is None:
                        raise ValueError("DATAPREP_SAMPLE_CHANGED")
                    persist_sample(dataset, paths, reuse_identical=True)
                sample = dict(dataset.lineage_json["sample"])
                dataset.lineage_json = {
                    **(dataset.lineage_json or {}),
                    "sample": sample,
                    "sample_status": "ready",
                    "sample_job_id": job_id,
                }
                job.status, job.stage, job.progress = "completed", "sample_ready", 100
                job.result = {"dataset_id": dataset.id, "sample": sample}
                job.error = None
                job.completed_at = job.updated_at = datetime.utcnow()
                db.commit()
                return {"status": "completed", **job.result}
        except Exception as exc:
            db.rollback()
            job = db.query(WorkspaceJob).filter_by(id=job_id).with_for_update().one()
            if job.input_ref.get("lease") == token:
                code = str(exc).split(":", 1)[0] if isinstance(exc, ValueError) else ""
                if not code.startswith(("DATAPREP_", "DATASET_")) or not all(
                    c.isupper() or c == "_" for c in code
                ):
                    code = "DATAPREP_SAMPLE_BUILD_FAILED"
                job.status, job.stage, job.error = "failed", "sample_failed", code[:100]
                job.completed_at = job.updated_at = datetime.utcnow()
                db.commit()
            return {"status": "failed", "code": job.error}


def recover_samples(*, limit=100):
    """Republish bounded durable intentions; never retry a failed build automatically.

    A broker publish and a SQL commit cannot be atomic here. A queued intention
    older than 60 seconds therefore has uncertain delivery, and may be delivered
    again under the same task ID. The worker's claim remains the execution fence.
    """
    from app.db.base import SessionLocal
    from app.workers.celery_app import celery_app

    now = datetime.utcnow()
    retry_before = now - timedelta(seconds=60)
    stale_before = _stale_before()
    eligible = (
        WorkspaceJob.kind == KIND,
        WorkspaceJob.updated_at <= retry_before,
        or_(
            WorkspaceJob.status == "queued",
            (WorkspaceJob.status == "running") & (WorkspaceJob.started_at < stale_before),
        ),
    )
    result = {"scanned": 0, "claimed": 0, "published": 0, "publish_failed": 0}
    with SessionLocal() as db:
        candidates = (
            db.query(WorkspaceJob.id, WorkspaceJob.updated_at, WorkspaceJob.input_ref)
            .filter(*eligible)
            .order_by(WorkspaceJob.updated_at, WorkspaceJob.id)
            .limit(max(1, min(int(limit), 100)))
            .all()
        )
        result["scanned"] = len(candidates)
        for identity, observed_updated_at, ref in candidates:
            claimed_at = datetime.utcnow()
            claim = db.execute(
                update(WorkspaceJob)
                .where(
                    WorkspaceJob.id == identity,
                    WorkspaceJob.updated_at == observed_updated_at,
                    *eligible,
                )
                .values(
                    status="queued",
                    stage="sample_pending",
                    input_ref={**ref, "lease": uuid4().hex},
                    queued_at=claimed_at,
                    updated_at=claimed_at,
                )
            )
            db.commit()
            if claim.rowcount != 1:
                continue
            result["claimed"] += 1
            try:
                celery_app.send_task(
                    "agentium.dataops_build_sample",
                    args=[identity],
                    queue=settings.celery_dataops_queue,
                    task_id=identity,
                    retry=False,
                )
            except Exception:
                # The publish may still have reached the broker. Keep the
                # intention queued and the CAS timestamp; a later tick recovers
                # it, with no immediate duplicate or failed-build retry loop.
                result["publish_failed"] += 1
                break
            result["published"] += 1
    return result
