"""Usage evidence, versioned tariffs and explicit blocking budget controls."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.model_usage import ModelTariff, UsageBudgetPolicy
from app.models.user import User
from app.models.workspace import Workspace
from app.services import model_usage as usage
from app.services import model_usage_views as views
from app.services.activity_observability.queries import require_membership
from app.services.huggingface.access import is_workspace_admin

router = APIRouter(prefix="/observability/usage", tags=["model-usage"])


class BudgetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["workspace", "system"]
    system_id: str | None = Field(None, max_length=36)
    enabled: bool = False
    timezone: str = Field("UTC", max_length=80)
    max_tokens: int | None = Field(None, ge=0, le=9_000_000_000_000_000, strict=True)
    currency_limits: dict[str, str] = Field(default_factory=dict)
    expected_revision: int = Field(ge=0)


class TariffBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    currency: str = Field(pattern="^[A-Z]{3}$")
    input_per_million: str
    output_per_million: str
    cached_input_per_million: str | None = None
    cache_write_per_million: str | None = None


class RolloutBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern="^[a-f0-9]{40}$")
    components: dict[str, str]
    all_workers_recreated: bool
    livekit_sessions_drained: bool


def _manage(db, workspace, user):
    require_membership(db, workspace, user)
    if not is_workspace_admin(db, user, workspace):
        raise HTTPException(403, "USAGE_BUDGET_MANAGEMENT_DENIED")


def _invoke(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except usage.UsageError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, **exc.details}) from None


def _filters(
    window: Literal["24h", "7d", "30d", "90d"] = "7d",
    as_of: datetime | None = None,
    system_id: str | None = Query(None, max_length=36),
    run_id: str | None = Query(None, max_length=36),
    provider: str | None = Query(None, max_length=80),
    model: str | None = Query(None, max_length=200),
    purpose: str | None = Query(None, max_length=40),
    run_scope: Literal["direct", "tree"] = "direct",
    traffic: Literal["all", "business", "evaluation", "preview", "ingestion"] = "all",
    status: Literal[
        "prepared", "dispatched", "completed", "failed", "cancelled", "unknown", "blocked"
    ]
    | None = None,
):
    return dict(
        window=window,
        as_of=as_of,
        system_id=system_id,
        run_id=run_id,
        provider=provider,
        model=model,
        purpose=purpose,
        traffic=traffic,
        status=status,
        run_scope=run_scope,
    )


@router.get("/summary")
def summary(
    filters=Depends(_filters),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_membership(db, workspace, user)
    rows, coverage = views.visible_calls(db, workspace, user, **filters)
    return {**views.summarize(rows), "coverage": coverage}


@router.get("/series")
def series(
    filters=Depends(_filters),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_membership(db, workspace, user)
    rows, coverage = views.visible_calls(db, workspace, user, **filters)
    return {"buckets": views.series(rows), "timezone": "UTC", "coverage": coverage}


@router.get("/calls")
def calls(
    filters=Depends(_filters),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=20_000),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_membership(db, workspace, user)
    rows, coverage = views.visible_calls(db, workspace, user, **filters)
    return {
        "items": views.visible_call_payloads(db, workspace, user, rows[offset : offset + limit]),
        "total": len(rows) if coverage["complete"] else None,
        "limit": limit,
        "offset": offset,
        "coverage": coverage,
    }


@router.get("/readiness")
def readiness(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_membership(db, workspace, user)
    return usage.budget_readiness(workspace)


@router.post("/readiness/attest")
def attest(
    body: RolloutBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _manage(db, workspace, user)
    return _invoke(usage.attest_rollout, db, workspace, user, **body.model_dump())


@router.get("/budgets")
def budgets(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_membership(db, workspace, user)
    can_manage = is_workspace_admin(db, user, workspace)
    # A shared budget's consumption is workspace-wide and can include private
    # Runs. Do not expose it to a reader who only sees a subset of those Runs.
    rows = (
        db.query(UsageBudgetPolicy)
        .filter_by(workspace_id=workspace.id)
        .order_by(UsageBudgetPolicy.scope_key)
        .all()
        if can_manage
        else []
    )
    return {
        "items": [usage.public_budget(db, row) for row in rows],
        "can_manage": can_manage,
        "readiness": usage.budget_readiness(workspace),
    }


@router.post("/budgets")
def save_budget(
    body: BudgetBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _manage(db, workspace, user)
    return _invoke(usage.save_budget, db, workspace, user, **body.model_dump())


@router.get("/tariffs")
def tariffs(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_membership(db, workspace, user)
    rows = (
        db.query(ModelTariff)
        .filter_by(workspace_id=workspace.id)
        .order_by(ModelTariff.provider, ModelTariff.model, ModelTariff.revision.desc())
        .all()
    )
    return {
        "items": [usage._tariff_snapshot(row) for row in rows],
        "can_manage": is_workspace_admin(db, user, workspace),
    }


@router.post("/tariffs")
def create_tariff(
    body: TariffBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _manage(db, workspace, user)
    return _invoke(usage.create_tariff, db, workspace, user, **body.model_dump())
