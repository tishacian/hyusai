"""Workspace-scoped Hub resources. Only server-resolved metadata is trusted."""

from __future__ import annotations

from datetime import datetime
from functools import wraps
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.huggingface import HubArtifact, HubArtifactGrant, HubArtifactUsage
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.connectors.generic import service as connectors
from app.services.huggingface import policy, registry
from app.services.huggingface.access import (
    can_import_dataset,
    is_platform_admin,
    is_workspace_admin,
    require_import_permission,
    require_platform_admin,
    require_workspace_admin,
)
from app.services.huggingface.client import HFClient
from app.services.huggingface.connection import (
    Connection,
    public_platform_config,
    set_platform_connection,
)
from app.services.huggingface.errors import HFError

router = APIRouter()


def handled(fn):
    """Rollback partial writes, then retain a credential-free refusal event."""

    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except HFError as exc:
            db, workspace, user = kwargs.get("db"), kwargs.get("workspace"), kwargs.get("user")
            if db is not None:
                db.rollback()
                from app.services.audit_logger import emit_audit_event

                emit_audit_event(
                    workspace_id=getattr(workspace, "id", None),
                    event_type="hf.request.refused",
                    actor=getattr(user, "id", "system"),
                    details={"operation": fn.__name__, "code": exc.code},
                    db=db,
                )
                db.commit()
            raise HTTPException(status_code=exc.status_code, detail=exc.public()) from None

    return call


class Values(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class PolicyUpdate(BaseModel):
    overrides: dict[str, str] = Field(default_factory=dict)


class Repository(BaseModel):
    kind: Literal["model", "dataset"] = "model"
    repo_id: str = Field(min_length=1, max_length=200)
    revision: str = Field(default="main", min_length=1, max_length=200)


class ImportRequest(Repository):
    format: Literal["safetensors", "gguf", "onnx", "parquet"] | None = None
    variant: str | None = Field(default=None, max_length=255)
    files: list[str] | None = Field(default=None, max_length=512)
    config: str | None = Field(default=None, max_length=200)
    split: str | None = Field(default=None, max_length=200)
    columns: list[str] | None = Field(default=None, max_length=512)
    max_rows: int | None = Field(default=None, ge=1, le=5_000_000)
    name: str | None = Field(default=None, max_length=200)
    request_key: str | None = Field(default=None, min_length=1, max_length=128)


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class LicenseException(Repository):
    reason: str = Field(min_length=1, max_length=2000)
    expires_at: datetime | None = None


class Catalogue(BaseModel):
    published: bool


def _repository(db, workspace, kind, repo_id, revision):
    client = HFClient(Connection.resolve(db, workspace))
    metadata = client.repo_info(kind, repo_id, revision)
    evidence = client.license_evidence(metadata)
    metadata["license_text"] = evidence["license_text"]
    return metadata


@router.get("/config")
@handled
def get_config(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    connection = Connection.resolve(db, workspace)
    overrides, version = policy.effective_policy(db, workspace)
    admin = is_workspace_admin(db, user, workspace)
    return {
        "connection": connection.public(),
        "policy": {"overrides": overrides, "policy_version": version},
        "limits": registry.effective_limits(db),
        "can_configure": admin,
        "can_accept_license": admin,
        "can_import_models": admin,
        "can_import_datasets": can_import_dataset(db, user, workspace),
        "can_admin_platform": is_platform_admin(user),
    }


@router.put("/config")
@handled
def set_config(
    body: Values,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_workspace_admin(db, user, workspace)
    try:
        connectors.set_config(db, workspace, "huggingface", body.values, actor=user.id)
    except HFError:
        raise
    except ValueError as exc:
        raise HFError("HF_CONFIG_INVALID", str(exc), 422) from None
    return {"connection": Connection.resolve(db, workspace).public()}


@router.delete("/config")
@handled
def clear_config(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_workspace_admin(db, user, workspace)
    connectors.clear_config(db, workspace, "huggingface", actor=user.id)
    return {"connection": Connection.resolve(db, workspace).public()}


@router.post("/test")
@handled
def test_connection(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_workspace_admin(db, user, workspace)
    return HFClient(Connection.resolve(db, workspace)).test()


@router.get("/platform/config")
@handled
def get_platform_config(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    require_platform_admin(user)
    return {**public_platform_config(db), "limits": registry.effective_limits(db)}


@router.put("/platform/config")
@handled
def configure_platform(
    body: Values, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)
):
    require_platform_admin(user)
    return {"connection": set_platform_connection(db, body.values, actor=user.id)}


@router.put("/platform/policy")
@handled
def platform_policy(
    body: PolicyUpdate, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)
):
    require_platform_admin(user)
    return policy.set_platform_policy(db, body.model_dump(), actor=user.id)


@router.put("/platform/limits")
@handled
def platform_limits(
    body: dict[str, StrictInt],
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_platform_admin(user)
    return registry.set_limits(db, body, actor=user.id)


@router.put("/policy")
@handled
def workspace_policy(
    body: PolicyUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_workspace_admin(db, user, workspace)
    return policy.set_workspace_policy(db, workspace, body.overrides, actor=user.id)


@router.get("/search")
@handled
def search(
    kind: Literal["model", "dataset"] = "model",
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    rows = HFClient(Connection.resolve(db, workspace)).search(kind, query, limit)
    overrides, _ = policy.effective_policy(db, workspace)
    for row in rows:
        tag = row.get("license") or "unknown"
        row["license_class"] = max(
            (policy.classify(tag), overrides.get(tag, "allowed")), key=policy.CLASSES.__getitem__
        )
    return {"results": rows}


@router.get("/repository")
@handled
def repository(
    repo_id: str = Query(min_length=1, max_length=200),
    kind: Literal["model", "dataset"] = "model",
    revision: str = Query(default="main", min_length=1, max_length=200),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    metadata = _repository(db, workspace, kind, repo_id, revision)
    return {
        "metadata": metadata,
        "license": policy.assess(db, workspace, metadata, metadata["license_text"]),
        "license_text": metadata["license_text"],
    }


@router.post("/licenses/accept")
@handled
def accept_license(
    body: Repository,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_workspace_admin(db, user, workspace)
    metadata = _repository(db, workspace, body.kind, body.repo_id, body.revision)
    return policy.accept_license(db, workspace, metadata, metadata["license_text"], actor=user.id)


@router.post("/licenses/exception")
@handled
def license_exception(
    body: LicenseException,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_platform_admin(user)
    metadata = _repository(db, workspace, body.kind, body.repo_id, body.revision)
    return policy.grant_exception(
        db,
        workspace,
        metadata,
        metadata["license_text"],
        actor=user.id,
        reason=body.reason,
        expires_at=body.expires_at,
    )


@router.post("/imports", status_code=202)
@handled
def import_artifact(
    body: ImportRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_import_permission(db, user, workspace, body.kind)
    metadata = _repository(db, workspace, body.kind, body.repo_id, body.revision)
    plan = body.model_dump(
        exclude_none=True, exclude={"kind", "repo_id", "revision", "request_key"}
    )
    artifact, job = registry.request_import(
        db,
        workspace_id=workspace.id,
        actor_id=user.id,
        metadata=metadata,
        selection=plan,
        job_key=body.request_key,
    )
    grant = db.get(HubArtifactGrant, (workspace.id, artifact.id))
    return {
        "artifact": registry.public_artifact(artifact, grant=grant),
        "job": registry.public_job(job),
    }


@router.get("/artifacts")
@handled
def artifacts(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    rows = (
        db.query(HubArtifact, HubArtifactGrant)
        .outerjoin(
            HubArtifactGrant,
            (HubArtifactGrant.artifact_id == HubArtifact.id)
            & (HubArtifactGrant.workspace_id == workspace.id),
        )
        .filter(
            or_(HubArtifactGrant.workspace_id == workspace.id, HubArtifact.in_catalogue.is_(True))
        )
        .order_by(HubArtifact.created_at.desc())
        .limit(200)
        .all()
    )
    return {
        "artifacts": [registry.public_artifact(artifact, grant=grant) for artifact, grant in rows]
    }


def _visible(db, workspace, artifact_id):
    artifact = db.get(HubArtifact, artifact_id)
    grant = db.get(HubArtifactGrant, (workspace.id, artifact_id))
    if artifact is None or not (grant or artifact.in_catalogue):
        raise HFError("HF_NOT_FOUND", "Artifact not available in this workspace.", 404)
    return artifact, grant


@router.get("/artifacts/{artifact_id}")
@handled
def artifact_detail(
    artifact_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    artifact, grant = _visible(db, workspace, artifact_id)
    return registry.public_artifact(artifact, grant=grant)


@router.post("/artifacts/{artifact_id}/grant")
@handled
def grant_artifact(
    artifact_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    artifact, _ = _visible(db, workspace, artifact_id)
    require_import_permission(db, user, workspace, artifact.kind)
    # Re-resolve gated/private state and prove this workspace's current access.
    metadata = _repository(db, workspace, artifact.kind, artifact.repo_id, artifact.revision)
    result, job = registry.request_import(
        db,
        workspace_id=workspace.id,
        actor_id=user.id,
        metadata=metadata,
        selection=dict(artifact.selection_json),
    )
    return {
        "artifact": registry.public_artifact(
            result, grant=db.get(HubArtifactGrant, (workspace.id, result.id))
        ),
        "job": registry.public_job(job),
    }


@router.get("/artifacts/{artifact_id}/usages")
@handled
def usages(
    artifact_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _visible(db, workspace, artifact_id)
    rows = (
        db.query(HubArtifactUsage)
        .filter_by(workspace_id=workspace.id, artifact_id=artifact_id)
        .all()
    )
    return {
        "usages": [
            {
                "id": row.id,
                "kind": row.kind,
                "target_id": row.target_id,
                "status": row.status,
                "lease_expires_at": row.lease_expires_at,
            }
            for row in rows
        ]
    }


@router.post("/artifacts/{artifact_id}/revoke-grant")
@handled
def revoke_grant(
    artifact_id: str,
    body: Reason,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_workspace_admin(db, user, workspace)
    registry.revoke_grant(db, workspace.id, artifact_id, actor=user.id, reason=body.reason)
    return {"status": "revoked", "scope": "workspace"}


@router.post("/artifacts/{artifact_id}/revoke")
@handled
def revoke_artifact(
    artifact_id: str,
    body: Reason,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_platform_admin(user)
    registry.revoke_artifact(db, artifact_id, actor=user.id, reason=body.reason)
    return {"status": "revoked", "scope": "platform"}


@router.put("/artifacts/{artifact_id}/catalogue")
@handled
def catalogue(
    artifact_id: str,
    body: Catalogue,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_platform_admin(user)
    registry.admission_lock(db)
    artifact = db.get(HubArtifact, artifact_id)
    if not artifact or (body.published and artifact.status != "ready"):
        raise HFError(
            "HF_ARTIFACT_NOT_READY", "Only a ready artifact may be published to the catalogue.", 409
        )
    artifact.in_catalogue = body.published
    registry._audit(
        db,
        None,
        "catalogue.updated",
        user.id,
        {"artifact_id": artifact_id, "published": body.published},
    )
    db.commit()
    return registry.public_artifact(artifact)


HF_JOB_KINDS = (
    "hf_import",
    "hf_bundle_import",
    "hf_bundle_export",
    "hf_purge",
    "hf_adapter_activate",
    "hf_legacy_migrate",
)


@router.get("/jobs")
@handled
def list_jobs(
    limit: int = Query(default=100, ge=1, le=200),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    jobs = (
        db.query(WorkspaceJob)
        .filter(WorkspaceJob.workspace_id == workspace.id, WorkspaceJob.kind.in_(HF_JOB_KINDS))
        .order_by(WorkspaceJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"jobs": [registry.public_job(job) for job in jobs]}


@router.get("/jobs/{job_id}")
@handled
def job_detail(
    job_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    job = (
        db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.id == job_id,
            WorkspaceJob.workspace_id == workspace.id,
            WorkspaceJob.kind.in_(HF_JOB_KINDS),
        )
        .first()
    )
    if not job:
        raise HFError("HF_NOT_FOUND", "Import job not found.", 404)
    return registry.public_job(job)


@router.post("/jobs/{job_id}/cancel")
@handled
def cancel_job(
    job_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    job = (
        db.query(WorkspaceJob)
        .filter_by(id=job_id, workspace_id=workspace.id, kind="hf_import")
        .first()
    )
    if not job:
        raise HFError("HF_NOT_FOUND", "Import job not found.", 404)
    if job.created_by_user_id != user.id:
        require_workspace_admin(db, user, workspace)
    return registry.public_job(registry.cancel_import(db, workspace.id, job_id, actor=user.id))
