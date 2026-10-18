"""Audited admin export of one workspace-bound model version."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace
from app.services.ml.artifacts import artifact_fingerprint
from app.services.ml_exports import build_export
from app.services.ml_requalification import attested_runtimes
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import get_model

router = APIRouter()


class _ExportResponse(FileResponse):
    def __init__(self, *args, temporary, **kwargs):
        self.temporary = temporary
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.temporary.cleanup()


@router.get("/{model_id}/export")
def export_model(
    model_id: str,
    request: Request,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # M1 is a hard dependency, not a permissive optional integration.
    from app.services.ml_permissions import audit, require

    temporary = None
    try:
        require(db, "export", workspace, user)
        model = get_model(db, workspace_id=workspace.id, model_id=model_id, ready_only=True)
        temporary = tempfile.TemporaryDirectory(prefix="agentium-ml-export-")
        archive, metadata = build_export(
            model, Path(temporary.name), attested=attested_runtimes(db, model)
        )
        # Revalidate authority and exact source after the potentially slow copy.
        db.refresh(workspace)
        db.refresh(user)
        require(db, "export", workspace, user)
        current = (
            db.query(MLModel)
            .filter_by(id=model_id, workspace_id=workspace.id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if (
            current is None
            or current.status != "ready"
            or current.version != metadata["model_version"]
            or artifact_fingerprint((current.metrics_json or {}).get("artifact") or {})
            != metadata["artifact_fingerprint"]
            # A revocation during the copy must not leave with the archive.
            or sorted(item["id"] for item in attested_runtimes(db, current))
            != metadata.get("attestations", [])
        ):
            raise TabularError(
                code="ML_EXPORT_SOURCE_CHANGED",
                message="The model changed during export. Try again.",
                status_code=409,
            )
        audit(
            db,
            action="export",
            workspace_id=workspace.id,
            actor=user.id,
            model=current,
            after=metadata,
            ip=request.client.host if request.client else None,
        )
        db.commit()  # No archive bytes leave before the audit is durable.
        return _ExportResponse(
            archive,
            temporary=temporary,
            media_type="application/zip",
            filename=f"model-{current.id}-v{current.version}.zip",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Archive-SHA256": metadata["archive_sha256"],
            },
        )
    except TabularError as exc:
        db.rollback()
        if temporary:
            temporary.cleanup()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    except BaseException:
        db.rollback()
        if temporary:
            temporary.cleanup()
        raise
