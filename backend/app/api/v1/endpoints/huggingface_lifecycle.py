"""Authorized deployment control and durable offline/lifecycle jobs."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.huggingface import HubArtifact, HubArtifactUsage
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import nodes, offline, policy, registry
from app.services.huggingface.access import require_platform_admin, require_workspace_admin
from app.services.huggingface.errors import HFError
from app.services.huggingface.storage import HubStore, blob_key
from app.services.model_plane.serving_nodes import PortalClientError


class _HFRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except HFError as exc:
                raise HTTPException(exc.status_code, detail=exc.public()) from exc
            except PortalClientError as exc:
                raise HTTPException(
                    exc.status_code,
                    detail={
                        "code": "HF_NODE_UNAVAILABLE",
                        "message": "The node could not complete the artifact operation",
                    },
                ) from exc

        return handler


router = APIRouter(route_class=_HFRoute)


class DeploymentBody(BaseModel):
    node_name: str = Field(min_length=1, max_length=128)
    architecture: str = Field(min_length=1, max_length=128)
    context_length: int = Field(gt=0, le=2_000_000)
    required_memory_bytes: int = Field(gt=0, le=10 * 1024**4)
    deployment_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")


class BundleExportBody(BaseModel):
    expiry_seconds: int = Field(default=86400, ge=60, le=86400)


def _usage(db, workspace, deployment_id):
    usage = (
        db.query(HubArtifactUsage)
        .filter_by(workspace_id=workspace.id, kind="llm", target_id=deployment_id)
        .first()
    )
    if usage is None:
        raise HFError("HF_NOT_FOUND", "Deployment not found in this workspace", 404)
    return usage


def _control(db, user, workspace, usage):
    def check(artifact_id, deployment_id):
        require_workspace_admin(db, user, workspace)
        current = _usage(db, workspace, deployment_id)
        if current.artifact_id != artifact_id or current.id != usage.id:
            raise HFError("HF_ACCESS_REVOKED", "Deployment ownership changed", 403)

    return check


def _authorize(db, user, workspace):
    def check(artifact_id):
        db.expire_all()
        require_workspace_admin(db, user, workspace)
        return registry.require_artifact(db, workspace.id, artifact_id, usage="llm")

    return check


def _presign(artifact):
    store = HubStore(use_hub_credentials=False)

    def sign(path, ttl):
        key = blob_key(artifact, path)
        if artifact.manifest_json["files"][path].get("object_key") != key:
            raise HFError("HF_PATH_INVALID", "Invalid artifact object reference")
        return store.presign(key, ttl)

    return sign


def _update_usage(db, usage, result):
    usage.status = result["state"]
    usage.details_json = {
        **usage.details_json,
        "state": result["state"],
        "error_code": result.get("error_code"),
        "copies_deleted": result.get("copies_deleted") is True,
    }
    usage.lease_expires_at = (
        None
        if result["state"] in {"stopped", "failed"}
        else datetime.utcnow() + timedelta(minutes=10)
    )
    db.commit()
    return {**result, "node_name": usage.details_json["node_name"]}


@router.get("/nodes/{node_name}/capabilities")
async def node_capabilities(
    node_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    return await nodes.get_capabilities(node_name, workspace=workspace)


@router.post("/artifacts/{artifact_id}/deployments")
async def deploy(
    artifact_id: str,
    body: DeploymentBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    artifact = registry.require_artifact(db, workspace.id, artifact_id, usage="llm")
    request = {
        **body.model_dump(exclude={"deployment_id"}),
        "artifact_id": artifact_id,
        "workspace_id": workspace.id,
    }
    deployment_id = body.deployment_id or registry.digest(request)
    registry.admission_lock(db)
    usage = (
        db.query(HubArtifactUsage)
        .filter_by(workspace_id=workspace.id, kind="llm", target_id=deployment_id)
        .first()
    )
    if usage and usage.details_json.get("request") != request:
        raise HFError("HF_IDEMPOTENCY_CONFLICT", "This deployment ID names another request", 409)
    if usage is None:
        usage = registry.register_usage(
            db,
            workspace.id,
            artifact.id,
            "llm",
            deployment_id,
            details={
                "node_name": body.node_name,
                "deployment_id": deployment_id,
                "request": request,
            },
        )
        usage.status = "preparing"
        usage.lease_expires_at = datetime.utcnow() + timedelta(minutes=10)
    db.commit()
    try:
        result = await nodes.deploy_artifact(
            body.node_name,
            artifact.manifest_json,
            workspace=workspace,
            architecture=body.architecture,
            context_length=body.context_length,
            required_memory_bytes=body.required_memory_bytes,
            deployment_id=deployment_id,
            authorize=_authorize(db, user, workspace),
            presign=_presign(artifact),
        )
        result = _update_usage(db, usage, result)
        registry._audit(
            db,
            workspace.id,
            "deployment.requested",
            user.id,
            {"artifact_id": artifact.id, "deployment_id": deployment_id},
        )
        db.commit()
        if result["state"] == "ready":
            from app.services.model_plane.serving_nodes import list_nodes

            await list_nodes(workspace=workspace)
        return result
    except HFError:
        # A remote timeout is intentionally NOT marked failed: the node may
        # still be preparing. Preflight/authorization refusal has no readers.
        usage.status = "failed"
        usage.lease_expires_at = None
        db.commit()
        raise


@router.get("/deployments/{deployment_id}")
async def deployment_status(
    deployment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    usage = _usage(db, workspace, deployment_id)
    result = await nodes.deployment_status(
        usage.details_json["node_name"],
        deployment_id,
        workspace=workspace,
        artifact_id=usage.artifact_id,
        authorize_control=_control(db, user, workspace, usage),
    )
    result = _update_usage(db, usage, result)
    if result["state"] == "ready":
        from app.services.model_plane.serving_nodes import list_nodes

        await list_nodes(workspace=workspace)
    return result


@router.post("/deployments/{deployment_id}/stop")
async def stop_deployment(
    deployment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    usage = _usage(db, workspace, deployment_id)
    usage.status = "draining"
    db.commit()
    result = await nodes.stop_deployment(
        usage.details_json["node_name"],
        deployment_id,
        workspace=workspace,
        artifact_id=usage.artifact_id,
        authorize_control=_control(db, user, workspace, usage),
    )
    return _update_usage(db, usage, result)


@router.post("/deployments/{deployment_id}/refresh")
async def refresh_deployment(
    deployment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    usage = _usage(db, workspace, deployment_id)
    artifact = registry.require_artifact(db, workspace.id, usage.artifact_id, usage="llm")
    result = await nodes.refresh_deployment_urls(
        usage.details_json["node_name"],
        deployment_id,
        artifact.manifest_json,
        workspace=workspace,
        authorize=_authorize(db, user, workspace),
        authorize_control=_control(db, user, workspace, usage),
        presign=_presign(artifact),
    )
    return _update_usage(db, usage, result)


def _new_job(db, user, workspace, kind, input_ref):
    from app.services.workspace_jobs import create_workspace_job

    job = create_workspace_job(
        db, workspace, user, kind=kind, title=kind, input_ref=input_ref, status="queued"
    )
    job.stage, job.queued_at = "queued", datetime.utcnow()
    db.commit()
    return job


def _dispatch(db, job, task_name, *, dataset=False):
    from app.workers.celery_app import celery_app

    job.input_ref = {**job.input_ref, "task_name": task_name, "dataset_worker": dataset}
    try:
        result = celery_app.send_task(
            task_name,
            args=[job.id],
            queue=settings.celery_task_default_queue if dataset else "hub_fetch",
        )
        job.input_ref = {**job.input_ref, "celery_task_id": result.id, "task_name": task_name}
    except Exception:
        job.stage = "dispatch_pending"
    db.commit()
    return {"job_id": job.id, "status": job.status, "stage": job.stage}


def _admit_spool(db, workspace, expected, *, existing_job_id=None):
    registry.admission_lock(db)
    reservations, active = registry.inflight_admissions(db)
    if existing_job_id:
        reservations = [row for row in reservations if row.job_id != existing_job_id]
        active = [row for row in active if row.id != existing_job_id]
    limits = registry.effective_limits(db)
    if (
        sum(j.workspace_id == workspace.id for j in active)
        + sum(r.workspace_id == workspace.id for r in reservations)
        >= limits["workspace_imports"]
        or len(active) + len(reservations) >= limits["platform_imports"]
    ):
        raise HFError("HF_QUOTA_EXCEEDED", "The concurrent import limit has been reached", 409)
    if (
        shutil.disk_usage(offline.spool_root()).free
        - expected * 2
        - registry.reservation_bytes(reservations, active, db=db)
        < settings.hf_disk_min_free_bytes
    ):
        raise HFError("HF_QUOTA_EXCEEDED", "Insufficient shared disk headroom for this bundle", 409)


@router.post("/artifacts/{artifact_id}/bundles", status_code=202)
def export_bundle(
    artifact_id: str,
    body: BundleExportBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    artifact = registry.require_artifact(db, workspace.id, artifact_id)
    expected = artifact.total_bytes + 16 * 1024**2
    _admit_spool(db, workspace, expected)
    job = _new_job(
        db,
        user,
        workspace,
        "hf_bundle_export",
        {"artifact_id": artifact_id, "upload_bytes": expected, **body.model_dump()},
    )
    task = (
        "agentium.hf_bundle_dataset_export"
        if artifact.kind == "dataset"
        else "agentium.hf_bundle_export"
    )
    return _dispatch(db, job, task, dataset=artifact.kind == "dataset")


@router.post("/bundles", status_code=202)
async def import_bundle(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    offline.trust_keys()  # Refuse before receiving bytes without configured trust.
    maximum = registry.effective_limits(db)["model_max_bytes"] + 16 * 1024**2
    length = request.headers.get("content-length")
    if length is None or not length.isdigit() or not 0 < int(length) <= maximum:
        raise HFError(
            "HF_TOO_LARGE",
            "Provide a bounded bundle Content-Length within the platform model limit",
            413,
        )
    expected = int(length)
    _admit_spool(db, workspace, expected)
    job = _new_job(db, user, workspace, "hf_bundle_import", {"upload_bytes": expected})
    job.stage = "uploading"
    db.commit()
    directory = offline.job_directory(job.id)
    directory.mkdir(mode=0o700)
    target = directory / "upload.tar"
    transferred = 0
    try:
        with target.open("xb") as output:
            os.chmod(target, 0o600)
            async for chunk in request.stream():
                transferred += len(chunk)
                if (
                    transferred > expected
                    or shutil.disk_usage(directory).free - len(chunk)
                    < settings.hf_disk_min_free_bytes
                ):
                    raise HFError(
                        "HF_TOO_LARGE", "Bundle exceeds its admitted transfer or disk limit", 413
                    )
                output.write(chunk)
        if transferred != expected:
            raise HFError("HF_BUNDLE_INVALID", "Bundle upload was truncated")
        with target.open("rb") as source:
            manifest = offline.inspect_bundle(source, workspace.id)
        if manifest.get("kind") not in {"model", "dataset"}:
            raise HFError("HF_BUNDLE_INVALID", "Unsupported artifact kind")
        job.input_ref = {**job.input_ref, "kind": manifest["kind"]}
        decision = policy.assess(db, workspace, manifest, manifest.get("license_text", ""))
        if decision["license_class"] == "blocked":
            raise HFError(
                "HF_LICENSE_BLOCKED", "The offline bundle license is blocked in this workspace", 403
            )
        if decision["license_class"] == "acceptance_required" and not decision.get("accepted"):
            job.status, job.stage = "created", "license_required"
            db.commit()
            return {
                "job_id": job.id,
                "status": job.status,
                "stage": job.stage,
                "license": {
                    "tag": manifest.get("license"),
                    "text": manifest.get("license_text", ""),
                    "digest": decision["license_digest"],
                },
            }
        job.stage = "queued"
        task = (
            "agentium.hf_bundle_dataset_import"
            if manifest["kind"] == "dataset"
            else "agentium.hf_bundle_import"
        )
        return _dispatch(db, job, task, dataset=manifest["kind"] == "dataset")
    except BaseException:
        job.status, job.stage, job.error = "failed", "failed", "HF_BUNDLE_UPLOAD_FAILED"
        db.commit()
        shutil.rmtree(directory, ignore_errors=True)
        raise


@router.get("/bundle-jobs/{job_id}")
def bundle_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    job = db.query(WorkspaceJob).filter_by(id=job_id, workspace_id=workspace.id).first()
    if job is None or job.kind not in {"hf_bundle_import", "hf_bundle_export", "hf_purge"}:
        raise HFError("HF_NOT_FOUND", "Lifecycle job not found", 404)
    result = {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "error_code": job.error,
        "artifact_id": (job.result or {}).get("artifact_id"),
        "download_available": bool((job.result or {}).get("download_available")),
    }
    if job.stage == "license_required" and job.status == "created":
        with (offline.job_directory(job.id) / "upload.tar").open("rb") as source:
            manifest = offline.inspect_bundle(source, workspace.id)
        result["license"] = {
            "tag": manifest.get("license"),
            "text": manifest.get("license_text", ""),
            "digest": policy.license_digest(manifest, manifest.get("license_text", "")),
        }
    return result


@router.post("/bundle-jobs/{job_id}/cancel")
def cancel_bundle(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    registry.admission_lock(db)
    job = (
        db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.id == job_id,
            WorkspaceJob.workspace_id == workspace.id,
            WorkspaceJob.kind.in_(["hf_bundle_import", "hf_bundle_export"]),
        )
        .first()
    )
    if job is None:
        raise HFError("HF_NOT_FOUND", "Bundle job not found", 404)
    if job.status not in {"completed", "failed", "cancelled"}:
        job.status, job.stage = "cancelled", "cancelled"
        registry._audit(db, workspace.id, "bundle.cancelled", user.id, {"job_id": job.id})
    db.commit()
    return {"job_id": job.id, "status": job.status}


@router.post("/bundle-jobs/{job_id}/accept-license", status_code=202)
def accept_bundle_license(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    job = (
        db.query(WorkspaceJob)
        .filter_by(id=job_id, workspace_id=workspace.id, kind="hf_bundle_import")
        .first()
    )
    if not job or job.stage != "license_required" or job.status != "created":
        raise HFError("HF_NOT_FOUND", "No offline license acceptance is pending", 404)
    with (offline.job_directory(job.id) / "upload.tar").open("rb") as source:
        manifest = offline.inspect_bundle(source, workspace.id)
    _admit_spool(db, workspace, int(job.input_ref["upload_bytes"]), existing_job_id=job.id)
    policy.accept_license(db, workspace, manifest, manifest.get("license_text", ""), actor=user.id)
    job.status, job.stage = "queued", "queued"
    task = (
        "agentium.hf_bundle_dataset_import"
        if manifest["kind"] == "dataset"
        else "agentium.hf_bundle_import"
    )
    return _dispatch(db, job, task, dataset=manifest["kind"] == "dataset")


@router.get("/bundle-jobs/{job_id}/download")
def download_bundle(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    job = (
        db.query(WorkspaceJob)
        .filter_by(id=job_id, workspace_id=workspace.id, kind="hf_bundle_export")
        .first()
    )
    if not job or job.status != "completed":
        raise HFError("HF_NOT_FOUND", "Bundle is not ready", 404)
    registry.require_artifact(db, workspace.id, job.input_ref["artifact_id"])
    if datetime.fromisoformat(job.result["expires_at"]) <= datetime.now(UTC):
        raise HFError(
            "HF_BUNDLE_PROOF_EXPIRED", "The bundle attestation expired; export a fresh bundle", 410
        )
    path = offline.job_directory(job.id) / "export.tar"
    if not path.is_file():
        raise HFError("HF_NOT_FOUND", "The bundle file is unavailable", 404)
    return FileResponse(
        path,
        filename=f"artifact-{job.input_ref['artifact_id']}.tar",
        media_type="application/x-tar",
    )


@router.post("/artifacts/{artifact_id}/purge", status_code=202)
def purge(
    artifact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_platform_admin(user)
    artifact = db.get(HubArtifact, artifact_id)
    if artifact is None:
        raise HFError("HF_NOT_FOUND", "Artifact not found", 404)
    if artifact.status != "revoked":
        raise HFError("HF_PURGE_BLOCKED", "Revoke the artifact before physical purge", 409)
    job = _new_job(
        db, user, workspace, "hf_purge", {"artifact_id": artifact_id, "actor_id": user.id}
    )
    return _dispatch(db, job, "agentium.hf_purge_artifact")
