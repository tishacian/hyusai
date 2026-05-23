"""On-demand report generation API (Phase G).

Used by AYA's ``aya.draft_strategic_report`` action and by the cockpit
"generate full report" affordance. Real markdown -> HTML -> PDF generation
is delegated to :mod:`app.services.sentinel_ci_reports`; the endpoint is
idempotent (hash-based) so repeated calls reuse the same artifact.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.sentinel_ci_reports import generate_strategic_report


router = APIRouter()


class ReportGenerateRequest(BaseModel):
    topic: str = Field(default="cacao_diversification", max_length=160)
    context_refs: list[str] = Field(default_factory=list)
    target_id: Optional[str] = Field(default=None, max_length=160)
    length: str = Field(default="long", max_length=32)


@router.post("/generate")
def generate_report(
    body: ReportGenerateRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        result = generate_strategic_report(
            db,
            workspace,
            user,
            topic=body.topic,
            context_refs=body.context_refs,
            target_id=body.target_id,
            length=body.length,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="report.generated",
        actor=(user.email or user.username or user.id) if user else "system",
        details={
            "topic": body.topic,
            "report_id": result.get("report_id"),
            "total_pages": result.get("total_pages"),
            "object_key": result.get("object_key"),
        },
    )
    return result
