"""Governed ML settings and reviewable model promotion decisions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.decision import Decision
from app.models.user import User
from app.models.workspace import Workspace
from app.services import ml_permissions, ml_promotion
from app.services.ml_governance import MLPolicy, lock_workspace, policy
from app.services.tabular_datasets import TabularError

router = APIRouter()


def refuse(exc):
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.get("")
def read_governance(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ml_permissions.require(db, "read", workspace, user)
        rows = (
            db.query(Decision)
            .filter_by(workspace_id=workspace.id, kind="ml_promotion", status="proposed")
            .order_by(Decision.created_at.desc())
            .limit(100)
            .all()
        )
        return {
            "policy": policy(db, workspace.id).model_dump(),
            "retention_enabled": settings.ml_retention_enabled,
            "permissions": ml_permissions.capabilities(db, workspace, user),
            "promotions": [
                ml_promotion.public(
                    row,
                    can_decide=ml_permissions.allowed(db, "promote", workspace, user)
                    and (row.rationale or {}).get("requested_by") != user.id,
                )
                for row in rows
            ],
        }
    except TabularError as exc:
        refuse(exc)


@router.put("/policy")
def configure_policy(
    body: MLPolicy,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ml_permissions.require(db, "policy", workspace, user)
        lock_workspace(db, workspace.id)
        db.refresh(workspace)
        before = policy(db, workspace.id).model_dump()
        workspace.settings = {**(workspace.settings or {}), "ml": body.model_dump()}
        # Persist the effective operator-capped values, so the UI never promises
        # a budget the inference service will not honor.
        effective = policy(db, workspace.id).model_dump()
        workspace.settings = {**workspace.settings, "ml": effective}
        ml_permissions.audit(
            db,
            action="policy_changed",
            workspace_id=workspace.id,
            actor=user.id,
            before=before,
            after=effective,
        )
        db.commit()
        return {"policy": effective}
    except TabularError as exc:
        refuse(exc)


class PromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    approve: bool


@router.post("/promotions/{decision_id}")
def decide_promotion(
    decision_id: str,
    body: PromotionDecision,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return {
            "decision": ml_promotion.decide(
                db, workspace=workspace, user=user, decision_id=decision_id, approve=body.approve
            )
        }
    except TabularError as exc:
        refuse(exc)
