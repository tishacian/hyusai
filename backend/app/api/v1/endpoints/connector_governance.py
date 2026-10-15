"""Platform-only control of private egress exceptions; no runtime credentials."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.db.base import get_db
from app.models.connector_governance import ConnectorEvidence, ConnectorNetworkException
from app.models.user import User
from app.services.connectors import evidence_store
from app.services.connectors import network_exceptions as service
from app.services.connectors.certification import EvidenceBundle
from app.services.huggingface.access import is_platform_admin


def enabled():
    if not settings.connector_framework_enabled:
        raise HTTPException(404, detail={"code": "CONNECTOR_FRAMEWORK_DISABLED"})


def platform_user(user: User = Depends(get_current_user)):
    if not is_platform_admin(user):
        raise HTTPException(403, detail={"code": "PLATFORM_PERMISSION_DENIED"})
    return user


router = APIRouter(dependencies=[Depends(enabled)])


class ExceptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str | None = None
    cidr: str = Field(max_length=64)
    ports: list[StrictInt] = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=10, max_length=1000)
    expires_at: datetime


def exception_view(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "workspace_id",
            "cidr",
            "ports",
            "reason",
            "expires_at",
            "created_by",
            "created_at",
            "revoked_at",
            "revoked_by",
        )
    }


@router.get("/network-exceptions")
def list_exceptions(user=Depends(platform_user), db: Session = Depends(get_db)):
    return {
        "exceptions": [
            exception_view(row)
            for row in db.query(ConnectorNetworkException)
            .order_by(ConnectorNetworkException.created_at.desc())
            .limit(1000)
            .all()
        ]
    }


@router.post("/network-exceptions", status_code=201)
def create_exception(
    body: ExceptionInput, user=Depends(platform_user), db: Session = Depends(get_db)
):
    try:
        return exception_view(service.create_exception(db, user=user, **body.model_dump()))
    except service.NetworkExceptionError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


@router.delete("/network-exceptions/{exception_id}")
def revoke_exception(exception_id: str, user=Depends(platform_user), db: Session = Depends(get_db)):
    try:
        return exception_view(service.revoke_exception(db, user=user, exception_id=exception_id))
    except service.NetworkExceptionError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producer: str = Field(min_length=1, max_length=160)
    bundle: EvidenceBundle
    reports: list[evidence_store.ProofReport] = Field(min_length=1, max_length=100)


@router.post("/evidence", status_code=201)
def accept_evidence(
    body: EvidenceInput, user=Depends(platform_user), db: Session = Depends(get_db)
):
    try:
        row = evidence_store.accept_evidence(
            db, user=user, producer=body.producer, bundle=body.bundle, reports=body.reports
        )
        return {
            "digest": row.digest,
            "profile_key": row.profile_key,
            "accepted_at": row.accepted_at,
        }
    except evidence_store.EvidenceError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


@router.delete("/evidence/{digest}")
def revoke_evidence(digest: str, user=Depends(platform_user), db: Session = Depends(get_db)):
    try:
        row = evidence_store.revoke_evidence(db, user=user, digest=digest)
        return {"digest": row.digest, "revoked_at": row.revoked_at}
    except evidence_store.EvidenceError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


@router.get("/evidence/{digest}")
def get_evidence(digest: str, user=Depends(platform_user), db: Session = Depends(get_db)):
    row = db.get(ConnectorEvidence, digest)
    if row is None:
        raise HTTPException(404, detail={"code": "CONNECTOR_EVIDENCE_NOT_FOUND"})
    return {
        "bundle": row.payload,
        "reports": row.reports,
        "producer": row.producer,
        "accepted_by": row.accepted_by,
        "accepted_at": row.accepted_at,
        "revoked_at": row.revoked_at,
    }
