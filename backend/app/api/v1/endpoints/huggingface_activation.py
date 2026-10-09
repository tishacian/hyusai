"""Local model activation is a job with a real runtime probe."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.huggingface import handled
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.huggingface.access import require_workspace_admin
from app.services.huggingface.activation import cancel_activation, request_activation
from app.services.huggingface.registry import public_job

router = APIRouter()


class ActivationBody(BaseModel):
    usage: Literal["forecasting", "embedding", "reranker"]
    runtime: Literal["ml", "rag"] | None = None


@router.post("/artifacts/{artifact_id}/activate")
@handled
def activate(
    artifact_id: str,
    body: ActivationBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    runtime = body.runtime or ("rag" if body.usage == "reranker" else "ml")
    job = request_activation(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
        usage=body.usage,
        runtime=runtime,
        actor=user.id,
    )
    return {"artifact_id": artifact_id, "job": public_job(job)}


@router.post("/activations/{job_id}/cancel")
@handled
def cancel(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    return {"job": public_job(cancel_activation(db, workspace.id, job_id, actor=user.id))}


class LegacyMigrationBody(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)


@router.post("/artifacts/{artifact_id}/migrate-legacy")
@handled
def migrate_legacy(
    artifact_id: str,
    body: LegacyMigrationBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    from app.services.huggingface.legacy_migration import request_migration

    require_workspace_admin(db, user, workspace)
    job = request_migration(
        db,
        workspace_id=workspace.id,
        model_id=body.model_id,
        artifact_id=artifact_id,
        actor=user.id,
    )
    return {"artifact_id": artifact_id, "job": public_job(job)}


@router.get("/legacy-models/{model_id}/migration")
@handled
def legacy_migration(
    model_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    from app.models.tabular import MLModel
    from app.services.huggingface.errors import HFError
    from app.services.huggingface.legacy_migration import migration_for

    model = db.query(MLModel).filter_by(id=model_id, workspace_id=workspace.id).first()
    if model is None:
        raise HFError("HF_NOT_FOUND", "Trained model not found in this workspace.", 404)
    migration = migration_for(db, model)
    return {
        "model_id": model_id,
        "migration": (
            {
                "artifact_id": migration.artifact_id,
                "status": migration.status,
                "repo_id": migration.details_json["repo_id"],
                "revision": migration.details_json["revision"],
                "original_provenance_preserved": True,
                "verified_at": migration.details_json["verified_at"],
            }
            if migration
            else None
        ),
    }


@router.post("/legacy-migrations/{job_id}/cancel")
@handled
def cancel_legacy_migration(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    require_workspace_admin(db, user, workspace)
    return {
        "job": public_job(
            cancel_activation(db, workspace.id, job_id, actor=user.id, kind="hf_legacy_migrate")
        )
    }
