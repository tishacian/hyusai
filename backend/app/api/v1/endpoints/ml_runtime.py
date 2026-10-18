"""Runtime requalification of one workspace-bound model version (M4.2).

Reading the state is a model-card read (workspace membership). Capturing references, requalifying and
revoking are the M1 ``requalify`` action: administrators only, never granted
by report mode, audited in the transaction of each mutation.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services import ml_requalification
from app.services.ml_permissions import require
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import get_model

router = APIRouter()


def _raise(db, exc: TabularError):
    db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.get("/{model_id}/runtime")
def runtime_state(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Same read authority as the model card itself: workspace membership.
    try:
        model = get_model(db, workspace_id=workspace.id, model_id=model_id)
        return ml_requalification.runtime_status(db, model)
    except TabularError as exc:
        _raise(db, exc)


def _request(kind, model_id, workspace, user, db):
    try:
        require(db, "requalify", workspace, user)
        model = get_model(db, workspace_id=workspace.id, model_id=model_id, ready_only=True)
        outcome = ml_requalification.request(db, kind=kind, model=model, user=user)
        db.expire_all()
        model = get_model(db, workspace_id=workspace.id, model_id=model_id)
        return {**outcome, "runtime": ml_requalification.runtime_status(db, model)}
    except TabularError as exc:
        _raise(db, exc)


@router.post("/{model_id}/runtime/reference", status_code=202)
def capture_reference(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue a capture of reference predictions under the producer runtime."""
    return _request(ml_requalification.CAPTURE, model_id, workspace, user, db)


@router.post("/{model_id}/runtime/requalify", status_code=202)
def requalify(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue one requalification per (model, artifact, reader runtime)."""
    return _request(ml_requalification.REQUALIFY, model_id, workspace, user, db)


@router.delete("/{model_id}/runtime/attestations/{attestation_id}")
def revoke_attestation(
    model_id: str,
    attestation_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        require(db, "requalify", workspace, user)
        model = get_model(db, workspace_id=workspace.id, model_id=model_id)
        revoked = ml_requalification.revoke(
            db, model=model, attestation_id=attestation_id, actor=user.id, user=user
        )
        db.expire_all()
        model = get_model(db, workspace_id=workspace.id, model_id=model_id)
        return {"attestation": revoked, "runtime": ml_requalification.runtime_status(db, model)}
    except TabularError as exc:
        _raise(db, exc)
