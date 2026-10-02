"""Authenticated server clock and independent review for the demo benchmark."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.api.v1.endpoints.ecommerce_claims import _access
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services import claims_benchmark as service

router = APIRouter()


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pair_id: str = Field(min_length=1, max_length=40)
    condition: Literal["manual", "assisted"]


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["refund", "carrier_investigation", "close_duplicate", "request_information", "failed"]
    amount: str = Field(max_length=30)
    references: list[str] = Field(max_length=20)
    note: str = Field(min_length=1, max_length=2000)


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "resume", "finish"]
    expected_sequence: int = Field(ge=1, le=1000)
    result: Outcome | None = None


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    note: str = Field(min_length=10, max_length=2000)


def _call(db, workspace, user, fn):
    _access(db, workspace, user)
    try:
        result = fn(); db.commit(); return result
    except (ValueError, ArithmeticError) as exc:
        db.rollback()
        code = str(exc) if str(exc).startswith("BENCHMARK_") else "BENCHMARK_VALUE_INVALID"
        raise HTTPException(409, detail={"code": code}) from None


@router.get("")
def summary(db: Session = Depends(get_db), workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user)):
    return _call(db, workspace, user, lambda: service.summary(db, workspace))


@router.post("/sessions", status_code=201)
def start(body: Start, db: Session = Depends(get_db), workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user)):
    return _call(db, workspace, user, lambda: service.serialize(service.start(db, workspace, user, body.pair_id, body.condition)))


@router.post("/sessions/{trial_id}/events")
def event(trial_id: str, body: Event, db: Session = Depends(get_db), workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user)):
    return _call(db, workspace, user, lambda: service.serialize(service.event(db, workspace, user, trial_id, body.action, body.expected_sequence, body.result.model_dump() if body.result else None)))


@router.post("/sessions/{trial_id}/review")
def review(trial_id: str, body: Review, db: Session = Depends(get_db), workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user)):
    return _call(db, workspace, user, lambda: service.serialize(service.review(db, workspace, user, trial_id, body.passed, body.note)))


class Costs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ledger_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    provider_eur: str = Field(max_length=30)
    infrastructure_eur: str = Field(max_length=30)
    licence_eur: str = Field(max_length=30)
    integration_eur: str = Field(max_length=30)
    provider_evidence_ref: str = Field(min_length=10, max_length=500)
    infrastructure_evidence_ref: str = Field(min_length=10, max_length=500)
    licence_evidence_ref: str = Field(min_length=10, max_length=500)
    integration_evidence_ref: str = Field(min_length=10, max_length=500)
    conversion_convention: str = Field(min_length=10, max_length=1000)
    note: str = Field(min_length=10, max_length=2000)


@router.post("/cost-review")
def costs(body: Costs, db: Session = Depends(get_db), workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user)):
    return _call(db, workspace, user, lambda: service.approve_costs(db, workspace, user, body.model_dump()))
