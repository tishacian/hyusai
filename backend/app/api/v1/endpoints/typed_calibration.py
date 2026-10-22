"""Authenticated human calibration workflow; never accepts claimed model scores."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.typed_evaluation import (
    CalibrationCaseFromEvaluation,
    CalibrationCorpus,
    CalibrationPrediction,
    HumanAnnotation,
    VisionRouteDefinition,
    VisionRouteQualification,
)
from app.services.evaluation import typed_calibration as service
from app.services.governed_assets import GovernanceError, asset_ref

router = APIRouter()


@router.post("/vision-routes")
def create_vision_route(
    body: VisionRouteDefinition,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(db, workspace, user, service.create_vision_route, body.model_dump(), commit=True)


@router.post("/vision-routes/{route_id}/qualify")
def qualify_vision_route(
    route_id: str,
    body: VisionRouteQualification,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(
        db, workspace, user, service.qualify_vision_route, route_id, body.model_dump(), commit=True
    )


def _call(db, workspace, user, operation, *args, commit=False):
    if (
        not settings.service_contracts_enabled
        and (workspace.settings or {}).get("features", {}).get("service_contracts") is not True
    ):
        raise HTTPException(404, detail={"code": "SERVICE_CONTRACTS_DISABLED"})
    try:
        result = operation(db, workspace.id, user.id, *args)
        if commit:
            db.commit()
        return result
    except GovernanceError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


@router.post("/corpora")
def create(
    body: CalibrationCorpus,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(db, workspace, user, service.create_corpus, body.model_dump(), commit=True)


@router.get("/corpora")
def list_corpora(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(db, workspace, user, service.list_corpora, offset, limit)


@router.post("/cases/from-evaluation", status_code=201)
def create_case_from_evaluation(
    body: CalibrationCaseFromEvaluation,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(
        db, workspace, user, service.create_case_from_evaluation, body.model_dump(), commit=True
    )


@router.get("/corpora/{corpus_id}/review-units")
def review_units(
    corpus_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(db, workspace, user, service.review_units, corpus_id)


@router.get("/corpora/{corpus_id}/review-units/{unit_key}")
def review_unit(
    corpus_id: str,
    unit_key: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(db, workspace, user, service.review_unit, corpus_id, unit_key)


@router.get("/corpora/{corpus_id}")
def read(
    corpus_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    def get(db, wid, uid, identifier):
        row = service.corpus(db, wid, identifier, uid)
        return {"asset_ref": asset_ref(row), "spec": row.manifest_json["spec"]}

    return _call(db, workspace, user, get, corpus_id)


@router.post("/corpora/{corpus_id}/annotations")
def annotate(
    corpus_id: str,
    body: HumanAnnotation,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(db, workspace, user, service.annotate, corpus_id, body.model_dump(), commit=True)


@router.post("/corpora/{corpus_id}/predictions")
def prediction(
    corpus_id: str,
    body: CalibrationPrediction,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(
        db, workspace, user, service.attach_prediction, corpus_id, body.model_dump(), commit=True
    )


@router.get("/corpora/{corpus_id}/report")
def report(
    corpus_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(db, workspace, user, service.report, corpus_id)


@router.post("/corpora/{corpus_id}/qualify")
def qualify(
    corpus_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    return _call(db, workspace, user, service.qualify, corpus_id, commit=True)
