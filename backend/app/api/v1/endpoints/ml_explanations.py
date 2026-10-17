"""Explaining a model in use: counterfactuals and production debugging (M5).

Registered beside ``ml_models`` under ``/ml-models`` rather than inside it, so
the serving router keeps its contract and this surface reads on its own:

* ``POST /{id}/counterfactuals`` — the fewest, nearest changes to 1–3 fields
  that flip the answer. A workspace session with ``predict`` (read level);
  model API keys are not accepted, because each call scores up to
  ``ML_COUNTERFACTUAL_MAX_CANDIDATES`` internal rows while being charged as one.
* ``GET /{id}/production-debug`` — the latest production report of this exact
  version and its fairness series (``read``).
* ``POST /{id}/production-debug`` — run an analysis now (``score``, a WRITE
  action: it runs the model's pipeline over recorded production data on the
  general worker, exactly what batch scoring is authorized for), audited as
  ``ml.model.production_debug`` in the same transaction as the staged report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services import ml_permissions, ml_production_debug
from app.services.ml import counterfactuals
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import get_model

router = APIRouter()


def _raise(exc: TabularError) -> None:
    headers = (
        {"Retry-After": str((exc.details or {}).get("retry_after", 60))}
        if exc.status_code == 429
        else None
    )
    raise HTTPException(status_code=exc.status_code, detail=exc.payload(), headers=headers) from exc


class CounterfactualTarget(BaseModel):
    """``class`` for a classifier (absent: any other answer), a range for a regressor."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    class_: str | None = Field(default=None, alias="class", max_length=200)
    min: float | None = Field(default=None, allow_inf_nan=False)
    max: float | None = Field(default=None, allow_inf_nan=False)


class CounterfactualBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: dict[str, Any]
    fields: list[str] = Field(min_length=1, max_length=counterfactuals.MAX_FIELDS)
    target: CounterfactualTarget | None = None
    version: int | None = Field(default=None, ge=1)


@router.post("/{model_id}/counterfactuals")
async def search_counterfactuals(
    model_id: str,
    body: CounterfactualBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Predictions only, in a worker thread; nothing is journalled or stored."""

    try:
        ml_permissions.require(db, "predict", workspace, user)
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        target = body.target.model_dump(by_alias=True) if body.target else None
        return await run_in_threadpool(
            counterfactuals.search,
            db,
            model,
            body.row,
            fields=body.fields,
            target=target,
            version=body.version,
        )
    except TabularError as exc:
        _raise(exc)


@router.get("/{model_id}/production-debug")
async def get_production_debug(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        ml_permissions.require(db, "read", workspace, user)
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise(exc)
    return ml_production_debug.view(db, model)


class ProductionDebugBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    since: datetime | None = None
    until: datetime | None = None


def _naive(value: datetime | None) -> datetime | None:
    # The journal stores naive UTC; an aware bound is converted, not compared raw.
    if value is None or value.tzinfo is None:
        return value
    from datetime import UTC

    return value.astimezone(UTC).replace(tzinfo=None)


@router.post("/{model_id}/production-debug", status_code=202)
async def run_production_debug(
    model_id: str,
    body: ProductionDebugBody | None = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    body = body or ProductionDebugBody()
    try:
        ml_permissions.require(db, "score", workspace, user)
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        row = await run_in_threadpool(
            ml_production_debug.request_manual,
            db,
            model=model,
            workspace=workspace,
            user=user,
            since=_naive(body.since),
            until=_naive(body.until),
        )
    except TabularError as exc:
        _raise(exc)
    return {"report": ml_production_debug.serialize(row), **ml_production_debug.view(db, model)}
