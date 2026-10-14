"""Durable purge intentions; only a separately credentialed process deletes bytes."""

from datetime import datetime

from app.models.service_contract import AssetVersion
from app.models.tabular import TabularDataset
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.mlops_jobs import can_configure_mlops
from app.services.tabular_datasets import TabularError, dataset_prefix
from app.services.workspace_jobs import create_workspace_job, transition_job

KIND = "tabular_dataset_purge"


def refuse(code, message, status=409):
    raise TabularError(code=code, message=message, status_code=status)


def retain_guard(db, dataset):
    """Caller holds the workspace lock also used by A1 asset registration."""
    for asset in db.query(AssetVersion).filter_by(workspace_id=dataset.workspace_id):
        manifest = asset.manifest_json or {}
        prefix = dataset_prefix(dataset.workspace_id, dataset.id) + "/"
        if any(
            ref.get("kind") == "dataset" and ref.get("id") == dataset.id
            for ref in manifest.get("native_refs", [])
        ) or any(obj.get("key", "").startswith(prefix) for obj in manifest.get("objects", [])):
            refuse(
                "DATASET_GOVERNED_VERSION_IN_USE",
                "This immutable version is retained by a governed asset.",
            )


def request_purge(db, *, workspace, user, dataset_id):
    if not isinstance(user, User) or not can_configure_mlops(
        db, workspace=workspace, user=user, admin_only=True
    ):
        refuse(
            "DATASET_PURGE_ADMIN_REQUIRED",
            "A workspace administrator must request physical deletion.",
            403,
        )
    db.query(Workspace).filter_by(id=workspace.id).with_for_update().one()
    dataset = (
        db.query(TabularDataset)
        .filter_by(id=dataset_id, workspace_id=workspace.id)
        .with_for_update()
        .first()
    )
    if dataset is None:
        refuse("DATASET_NOT_FOUND", "Dataset not found.", 404)
    if dataset.status not in {"deleted", "failed"}:
        refuse(
            "DATASET_PURGE_REQUIRES_RETIRED",
            "Retire the dataset before requesting physical deletion.",
        )
    retain_guard(db, dataset)
    # A failed upload is retired before a durable purge can race its retry.
    dataset.status = "deleted"
    for job in db.query(WorkspaceJob).filter_by(workspace_id=workspace.id, kind=KIND):
        if job.input_ref.get("dataset_id") == dataset.id and job.status in {
            "queued",
            "running",
            "completed",
        }:
            return job
    return create_workspace_job(
        db,
        workspace,
        user,
        kind=KIND,
        title="Purge retired dataset",
        input_ref={"dataset_id": dataset.id, "version": dataset.version},
        status="queued",
    )


def purge_job(db, job_id, *, delete_prefix):
    """Dedicated worker supplies its deletion adapter, never application storage credentials.

    The DB lock spans storage deletion. Retries remove remaining versions under
    exactly the same immutable dataset prefix and then settle the same ledger.
    """
    job = db.get(WorkspaceJob, job_id)
    if job is None or job.kind != KIND:
        refuse("DATASET_PURGE_JOB_NOT_FOUND", "Purge job not found.", 404)
    workspace = db.query(Workspace).filter_by(id=job.workspace_id).with_for_update().one()
    job = db.query(WorkspaceJob).filter_by(id=job_id).with_for_update().populate_existing().one()
    if job.status == "completed":
        return job
    if job.status not in {"queued", "failed", "running"}:
        refuse("DATASET_PURGE_JOB_STATE", "This purge job cannot run.")
    user = db.get(User, job.created_by_user_id)
    if not user or not can_configure_mlops(db, workspace=workspace, user=user, admin_only=True):
        refuse(
            "DATASET_PURGE_ADMIN_REQUIRED", "The purge author is no longer an administrator.", 403
        )
    dataset = (
        db.query(TabularDataset)
        .filter_by(id=job.input_ref.get("dataset_id"), workspace_id=workspace.id)
        .with_for_update()
        .first()
    )
    if (
        dataset is None
        or dataset.status not in {"deleted", "failed"}
        or dataset.version != job.input_ref.get("version")
    ):
        refuse("DATASET_PURGE_VERSION_CHANGED", "The retired dataset version is unavailable.")
    retain_guard(db, dataset)
    transition_job(db, workspace, job, "running", stage="deleting", user=user)
    prefix = dataset_prefix(workspace.id, dataset.id) + "/"
    count = delete_prefix(prefix)
    dataset.status = "deleted"
    dataset.status_detail = "Physical objects purged"
    dataset.updated_at = datetime.utcnow()
    transition_job(
        db,
        workspace,
        job,
        "completed",
        stage="purged",
        result={"dataset_id": dataset.id, "deleted_objects": count},
        user=user,
    )
    return job
