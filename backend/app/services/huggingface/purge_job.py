"""Privileged physical purge on the preparation worker, with deletion receipts."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

from app.models.huggingface import HubArtifact, HubArtifactGrant, HubArtifactUsage
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import nodes, registry
from app.services.huggingface.access import require_platform_admin
from app.services.huggingface.cache import configured_cache
from app.services.huggingface.errors import HFError
from app.services.huggingface.lifecycle import purge_registry_artifact
from app.services.huggingface.storage import HubStore


def _delete_dataset_result(artifact_id, result):
    owner = result.get("owner_workspace_id")
    expected = f"workspaces/{owner}/tabular/hub-artifacts/{artifact_id}/result.parquet"
    if not owner or result.get("object_key") != expected:
        raise HFError("HF_PURGE_BLOCKED", "Invalid retained dataset ownership", 409)
    store = HubStore(use_hub_credentials=False)
    if store.store.backend == "s3":
        import boto3

        from app.core.config import settings

        access, secret = (
            os.getenv("HF_TABULAR_DELETE_ACCESS_KEY"),
            os.getenv("HF_TABULAR_DELETE_SECRET_KEY"),
        )
        if not access or not secret:
            raise HFError(
                "HF_PURGE_BLOCKED",
                "Configure the dedicated retained-dataset deletion identity",
                409,
            )
        # Separate deletion capability, scoped only to retained result keys;
        # never silently substitute the runtime tabular or Hub writer identity.
        store = HubStore(
            use_hub_credentials=False,
            s3_client=boto3.client(
                "s3",
                endpoint_url=settings.object_store_s3_endpoint_url,
                aws_access_key_id=access,
                aws_secret_access_key=secret,
            ),
        )
    store.delete(expected)


def run_purge_job(db, job_id: str) -> dict:
    job = db.get(WorkspaceJob, job_id)
    if not job or job.kind != "hf_purge":
        raise HFError("HF_NOT_FOUND", "Purge job not found", 404)
    if job.status == "completed":
        return job.result
    if job.status == "cancelled":
        raise HFError("HF_JOB_INACTIVE", "The purge was cancelled", 409)
    artifact_id = job.input_ref["artifact_id"]
    try:
        require_platform_admin(db.get(User, job.created_by_user_id))
        artifact = db.get(HubArtifact, artifact_id)
        if not artifact or artifact.status != "revoked":
            raise HFError("HF_PURGE_BLOCKED", "The artifact must remain globally revoked", 409)
        job.status, job.stage, job.started_at = "running", "draining", datetime.utcnow()
        db.commit()
        # Stop remote readers before checking local/registry leases. A failed
        # or unreachable node stays retained; the user can retry the same job.
        usages = db.query(HubArtifactUsage).filter_by(artifact_id=artifact_id, kind="llm").all()
        for usage in usages:
            details = usage.details_json or {}
            if details.get("copies_deleted") is True:
                continue
            workspace = db.get(Workspace, usage.workspace_id)
            result = asyncio.run(
                nodes.stop_deployment(
                    details["node_name"],
                    details["deployment_id"],
                    workspace=workspace,
                    artifact_id=artifact_id,
                    authorize_control=lambda *_: require_platform_admin(
                        db.get(User, job.created_by_user_id)
                    ),
                )
            )
            usage.status = result["state"]
            if result["state"] == "stopped":
                usage.lease_expires_at = None
            db.commit()

        def release_remote(identity):
            for usage in usages:
                details = usage.details_json or {}
                if details.get("copies_deleted") is True:
                    continue
                workspace = db.get(Workspace, usage.workspace_id)
                response = asyncio.run(
                    nodes.delete_deployment_copy(
                        details["node_name"],
                        details["deployment_id"],
                        workspace=workspace,
                        artifact_id=identity,
                        authorize_control=lambda *_: require_platform_admin(
                            db.get(User, job.created_by_user_id)
                        ),
                    )
                )
                usage.details_json = {**details, "copies_deleted": response["copies_deleted"]}
            return True

        receipt = purge_registry_artifact(
            db,
            artifact_id,
            store=HubStore(),
            remove_local_cache=configured_cache().remove,
            release_remote_copies=release_remote,
            delete_dataset_result=_delete_dataset_result,
        )
        job.status, job.stage, job.progress = "completed", "purged", 100
        job.result, job.completed_at = (
            {"artifact_id": artifact_id, "receipt": receipt},
            datetime.utcnow(),
        )
        registry._audit(db, job.workspace_id, "artifact.purged", job.created_by_user_id, job.result)
        db.commit()
        return job.result
    except Exception as exc:
        db.rollback()
        job = db.get(WorkspaceJob, job_id)
        job.status = "failed"
        job.stage = (
            "blocked" if isinstance(exc, HFError) and exc.code == "HF_PURGE_BLOCKED" else "failed"
        )
        job.error = getattr(exc, "code", "HF_PURGE_FAILED")
        registry._audit(
            db,
            job.workspace_id,
            "purge.failed",
            job.created_by_user_id,
            {"job_id": job.id, "error_code": job.error},
        )
        db.commit()
        raise


def drain_revoked_deployments(db, artifact_id: str, workspace_id: str | None = None) -> dict:
    """System control is authorized by persisted revocation, not an active grant."""
    artifact = db.get(HubArtifact, artifact_id)
    if artifact is None:
        return {"stopped": 0, "pending": 0}
    query = db.query(HubArtifactUsage).filter_by(artifact_id=artifact_id, kind="llm")
    if workspace_id:
        query = query.filter_by(workspace_id=workspace_id)
    stopped, pending = 0, 0
    for usage in query.all():
        grant = db.get(HubArtifactGrant, (usage.workspace_id, artifact_id), populate_existing=True)
        if artifact.status != "revoked" and grant is not None and grant.revoked_at is None:
            continue
        if usage.status == "stopped":
            continue
        details = usage.details_json or {}

        def authorized(*_):
            db.refresh(artifact)
            current = db.get(
                HubArtifactGrant, (usage.workspace_id, artifact_id), populate_existing=True
            )
            if artifact.status != "revoked" and current is not None and current.revoked_at is None:
                raise HFError(
                    "HF_JOB_INACTIVE", "The revocation was superseded by a new authorization", 409
                )

        try:
            response = asyncio.run(
                nodes.stop_deployment(
                    details["node_name"],
                    details["deployment_id"],
                    workspace=db.get(Workspace, usage.workspace_id),
                    artifact_id=artifact_id,
                    authorize_control=authorized,
                )
            )
            usage.status = response["state"]
            if usage.status == "stopped":
                usage.lease_expires_at = None
                stopped += 1
            else:
                pending += 1
        except Exception:
            # The canonical inference client already refuses future calls.
            # Retain an observable draining state until a node confirms stop.
            usage.status = "draining"
            usage.details_json = {**details, "drain_error": "HF_NODE_UNAVAILABLE"}
            pending += 1
        db.commit()
    return {"stopped": stopped, "pending": pending}
