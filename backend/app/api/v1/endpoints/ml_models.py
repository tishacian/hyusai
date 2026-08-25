"""Model plane API: the algorithm catalog, training runs and the registry.

Workspace-scoped. The endpoint never fits anything: a training request is
validated synchronously — so a bad target is a form error and not the terminal
status of a job — then handed to ``agentium.ml_train``, which folds the metrics,
the curves and the input contract back into the row. Every read here is one
indexed SELECT, which is what lets the Models page poll a run without cost.

``/plan`` exists for the same reason the SQL workshop resolves its catalog before
any run: the form has to be able to say what a choice implies (the task a target
suggests, the features it leaves, the columns that will not generalize) before
the author commits to a fit.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.tabular import MLModel, TabularDataset
from app.models.user import User
from app.models.workspace import Workspace
from app.services.tabular_datasets import (
    TabularError,
    resolve_dataset_ref,
    serialize_dataset,
)
from app.services.tabular_ml import (
    catalog_payload,
    delete_model,
    get_model,
    infer_task,
    request_cancel,
    serialize_model,
    set_champion,
    submit_training,
    validate_training,
)

router = APIRouter()


def _raise_tabular(exc: TabularError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class TrainBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: Optional[str] = Field(default=None, max_length=36)
    dataset_slug: Optional[str] = Field(default=None, max_length=200)
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2_000)
    task: Optional[str] = Field(default=None, max_length=20)
    target: str = Field(default="", max_length=200)
    features: list[str] = Field(default_factory=list, max_length=512)
    algo: Optional[str] = Field(default=None, max_length=80)
    knobs: dict[str, float] = Field(default_factory=dict)
    test_size: Optional[float] = Field(default=None, ge=0.05, le=0.5)
    cross_validation: Optional[int] = Field(default=None, ge=0, le=10)

    def dataset_ref(self) -> dict[str, Any]:
        if self.dataset_id:
            return {"dataset_id": self.dataset_id}
        return {"slug": self.dataset_slug or ""}


@router.get("")
async def list_models(
    task: Optional[str] = Query(default=None, max_length=20),
    status: Optional[str] = Query(default=None, max_length=16),
    dataset_id: Optional[str] = Query(default=None, max_length=36),
    limit: int = Query(default=100, ge=1, le=500),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    query = db.query(MLModel).filter(MLModel.workspace_id == workspace.id)
    if task:
        query = query.filter(MLModel.task == task)
    if status:
        query = query.filter(MLModel.status == status)
    if dataset_id:
        query = query.filter(MLModel.dataset_id == dataset_id)
    models = query.order_by(MLModel.created_at.desc()).limit(limit).all()
    return {
        "models": [serialize_model(row) for row in models],
        "catalog": catalog_payload(),
    }


@router.get("/catalog")
async def get_catalog(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    """Algorithms, their knobs and the platform's training limits."""

    return {"catalog": catalog_payload()}


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: Optional[str] = Field(default=None, max_length=36)
    dataset_slug: Optional[str] = Field(default=None, max_length=200)
    target: Optional[str] = Field(default=None, max_length=200)
    task: Optional[str] = Field(default=None, max_length=20)
    features: list[str] = Field(default_factory=list, max_length=512)
    algo: Optional[str] = Field(default=None, max_length=80)

    def dataset_ref(self) -> dict[str, Any]:
        if self.dataset_id:
            return {"dataset_id": self.dataset_id}
        return {"slug": self.dataset_slug or ""}


@router.post("/plan")
async def plan_training(
    body: PlanBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """What a training request would be, without running it.

    With a target: the resolved plan (task, features, knob defaults, warnings) or
    the coded refusal the form should render inline. Without one: the dataset's
    candidate targets, each carrying the task it suggests, so the first choice
    the author makes is already informed.
    """

    try:
        dataset = resolve_dataset_ref(
            db, workspace_id=workspace.id, ref=body.dataset_ref()
        )
    except TabularError as exc:
        _raise_tabular(exc)

    columns = [
        {
            "name": str(column.get("name")),
            "kind": str(column.get("kind") or "other"),
            "distinct": int(
                ((dataset.stats_json or {}).get(str(column.get("name"))) or {}).get(
                    "distinct"
                )
                or 0
            ),
            "nulls": int(
                ((dataset.stats_json or {}).get(str(column.get("name"))) or {}).get(
                    "nulls"
                )
                or 0
            ),
            "suggested_task": infer_task(dataset, str(column.get("name"))),
        }
        for column in (dataset.schema_json or [])
        if column.get("name")
    ]
    payload: dict[str, Any] = {
        "dataset": serialize_dataset(dataset),
        "columns": columns,
        "catalog": catalog_payload(),
        "plan": None,
        "refusal": None,
    }
    if not (body.target or "").strip():
        return payload

    try:
        spec = validate_training(
            dataset,
            task=body.task,
            target=body.target,
            features=body.features,
            algo=body.algo,
        )
    except TabularError as exc:
        # A refusal is an answer here, not an error: the form renders it against
        # the field that caused it while the author keeps editing.
        payload["refusal"] = exc.payload()
        return payload

    payload["plan"] = {
        "task": spec.task,
        "target": spec.target,
        "features": spec.features,
        "algo": spec.algo.key,
        "estimator": spec.algo.estimator_for(spec.task),
        "knobs": spec.knobs,
        "test_size": spec.test_size,
        "cross_validation": spec.cross_validation,
        "name": spec.name,
        "warnings": spec.warnings,
        "rows": int(dataset.row_count or 0),
    }
    return payload


@router.post("")
async def train_model(
    body: TrainBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Validate a training request and dispatch it; the row is the tracker."""

    if not settings.ml_train_enabled:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ml_train_disabled",
                "code": "ML_TRAIN_DISABLED",
                "message": "Model training is not enabled on this deployment.",
            },
        )
    try:
        model = submit_training(
            db,
            workspace_id=workspace.id,
            dataset_ref=body.dataset_ref(),
            task=body.task,
            target=body.target,
            features=body.features,
            algo=body.algo,
            knobs=body.knobs,
            test_size=body.test_size,
            cross_validation=body.cross_validation,
            name=body.name,
            description=body.description,
            created_by=getattr(user, "id", None),
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {"model": serialize_model(model, include_detail=True)}


@router.get("/{model_id}")
async def get_model_detail(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """The model card: metrics, curves, the input contract and the lineage."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    dataset = (
        db.query(TabularDataset)
        .filter(TabularDataset.id == model.dataset_id)
        .first()
        if model.dataset_id
        else None
    )
    versions = (
        db.query(MLModel)
        .filter(
            MLModel.workspace_id == workspace.id,
            MLModel.slug == model.slug,
        )
        .order_by(MLModel.version.desc())
        .limit(50)
        .all()
    )
    return {
        "model": serialize_model(model, include_detail=True),
        "dataset": serialize_dataset(dataset) if dataset is not None else None,
        "versions": [serialize_model(row) for row in versions],
        "catalog": catalog_payload(),
    }


@router.post("/{model_id}/cancel")
async def cancel_model_training(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Flip the cooperative stop flag; the worker kills the fit's process group."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    model = request_cancel(db, model)
    return {"model": serialize_model(model)}


@router.post("/{model_id}/champion")
async def promote_model(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Point the lineage's serving alias at this version."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        model = set_champion(db, model)
    except TabularError as exc:
        _raise_tabular(exc)
    versions = (
        db.query(MLModel)
        .filter(MLModel.workspace_id == workspace.id, MLModel.slug == model.slug)
        .order_by(MLModel.version.desc())
        .limit(50)
        .all()
    )
    return {
        "model": serialize_model(model, include_detail=True),
        "versions": [serialize_model(row) for row in versions],
    }


@router.delete("/{model_id}")
async def remove_model(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    return {"deleted": delete_model(db, model)}
