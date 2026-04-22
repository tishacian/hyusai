"""Audit log endpoints for governance demo.

Tenant-scoped (Vague D / D1). Every audit event is tied to the caller's
active workspace and reads are filtered accordingly so one tenant can
never see another's audit trail. `actor` is stamped server-side from the
authenticated user instead of trusting whatever the client sends.
"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class AuditEvent(BaseModel):
    event_type: str
    # `actor` is advisory only — we override it server-side with the
    # authenticated username so clients cannot spoof identity in the
    # audit trail.
    actor: Optional[str] = None
    details: Dict[str, Any] = {}
    trace_id: Optional[str] = None
    agent_id: Optional[str] = None
    severity: str = "info"


@router.post("")
async def create_audit_event(
    event: AuditEvent,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    log_entry = AuditLog(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        timestamp=datetime.utcnow(),
        event_type=event.event_type,
        # Override client-provided actor with the authenticated username —
        # audit logs must reflect real identity, not client claims.
        actor=user.username or user.email or "unknown",
        details=event.details,
        trace_id=event.trace_id,
        agent_id=event.agent_id,
        severity=event.severity,
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    logger.info(
        "Audit event created",
        event_type=event.event_type,
        workspace_id=workspace.id,
        actor=log_entry.actor,
    )
    return {
        "id": log_entry.id,
        "timestamp": log_entry.timestamp.isoformat(),
        "event_type": log_entry.event_type,
        "actor": log_entry.actor,
        "details": log_entry.details,
        "severity": log_entry.severity,
    }


@router.get("")
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    event_type: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    query = (
        db.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .order_by(AuditLog.timestamp.desc())
    )
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    logs = query.limit(limit).all()
    return {
        "logs": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "event_type": log.event_type,
                "actor": log.actor,
                "details": log.details,
                "trace_id": log.trace_id,
                "agent_id": log.agent_id,
                "severity": log.severity,
            }
            for log in logs
        ],
        "total": len(logs),
    }


@router.get("/summary")
async def audit_summary(
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    total = (
        db.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .count()
    )
    event_types = (
        db.query(AuditLog.event_type)
        .filter(AuditLog.workspace_id == workspace.id)
        .distinct()
        .all()
    )
    return {
        "total_events": total,
        "event_types": [e[0] for e in event_types],
        "governance_status": "active",
        "access_control": {
            "roles": ["Admin", "Auditor", "User"],
            "sso_provider": "Keycloak (OIDC)",
            "mfa_enabled": True,
        },
    }
