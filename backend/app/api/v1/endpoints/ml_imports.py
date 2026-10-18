"""Admin import of an external MLflow sklearn/skops model (M4.3).

Strict M1 ``import`` action (never granted by report mode) behind
``ML_IMPORT_ENABLED``. The upload is bounded while it is copied, checked
without loading anything, staged, and validated by a background job in the
isolated reader. Every attempt is audited as ``ml.model.import``.
"""

import hashlib
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services import ml_import
from app.services.ml_permissions import require
from app.services.tabular_datasets import TabularError

router = APIRouter()
logger = get_logger(__name__)


def _copy_bounded(upload: UploadFile, target: Path, limit: int) -> tuple[int, str]:
    """Copy the spooled upload with a byte counter; refuse past the limit."""
    digest, size = hashlib.sha256(), 0
    with target.open("xb") as sink:
        while block := upload.file.read(1024 * 1024):
            size += len(block)
            if size > limit:
                raise TabularError(
                    code="ML_IMPORT_REJECTED",
                    message="The archive exceeds the upload limit.",
                    status_code=413,
                    details={"reason": "archive_too_large"},
                )
            digest.update(block)
            sink.write(block)
    return size, digest.hexdigest()


@router.post("/import", status_code=202)
def import_model(
    request: Request,
    archive: UploadFile = File(...),
    validation: UploadFile = File(...),
    task: str = Form(..., max_length=20),
    name: str = Form(..., max_length=200),
    target: str = Form("", max_length=200),
    lineage_model_id: str | None = Form(None, max_length=36),
    description: str | None = Form(None, max_length=2000),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else None
    facts: dict = {"ip": ip}
    temporary = tempfile.TemporaryDirectory(prefix="agentium-ml-import-")
    try:
        require(db, "import", workspace, user)
        if not settings.ml_import_enabled:
            raise TabularError(
                code="ML_IMPORT_DISABLED",
                message="Model import is not enabled on this deployment.",
                status_code=409,
            )
        archive_limit = int(settings.ml_import_max_mb) * 1024 * 1024
        validation_limit = int(settings.ml_import_validation_max_bytes)
        declared = request.headers.get("content-length")
        # The proxy bounds the body first; this refuses an announced excess
        # before copying anything, and the copy below bounds an unannounced one.
        if (
            declared
            and declared.isdigit()
            and int(declared) > archive_limit + validation_limit + 1024 * 1024
        ):
            raise TabularError(
                code="ML_IMPORT_REJECTED",
                message="The upload exceeds its size limit.",
                status_code=413,
                details={"reason": "archive_too_large"},
            )
        path = Path(temporary.name) / "upload.zip"
        size, digest = _copy_bounded(archive, path, archive_limit)
        facts.update(archive_bytes=size, archive_sha256=digest)
        raw = validation.file.read(validation_limit + 1)
        facts["validation_bytes"] = len(raw)
        job = ml_import.request_import(
            db,
            workspace=workspace,
            user=user,
            archive=path,
            validation=raw,
            task=task,
            target=target,
            name=name.strip(),
            lineage_model_id=lineage_model_id or None,
            description=description,
            facts=facts,
        )
    except TabularError as exc:
        ml_import.audit_refusal(
            db,
            workspace_id=workspace.id,
            actor=user.id,
            error=exc,
            facts={key: value for key, value in facts.items() if key != "ip"},
            ip=ip,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    finally:
        temporary.cleanup()
    try:
        ml_import.dispatch(job.id)
    except Exception:  # noqa: BLE001 - an undelivered job expires and is reported
        logger.warning("ml_import: dispatch deferred", job_id=job.id)
    db.expire_all()
    return {"job": ml_import.public_job(db.get(WorkspaceJob, job.id))}


@router.get("/import/{job_id}")
def import_status(
    job_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        require(db, "import", workspace, user)
        job = (
            db.query(WorkspaceJob)
            .filter_by(id=job_id, workspace_id=workspace.id, kind=ml_import.KIND)
            .populate_existing()
            .first()
        )
        if job is None:
            raise TabularError(
                code="ML_IMPORT_NOT_FOUND", message="Import not found.", status_code=404
            )
        return {"job": ml_import.public_job(ml_import.expire_abandoned(db, job))}
    except TabularError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
