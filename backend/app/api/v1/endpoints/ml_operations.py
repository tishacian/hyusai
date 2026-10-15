"""Authorized, metadata-only endpoint overview and ML alert inbox."""

import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.audit import AuditLog
from app.models.ml_operations import MLAlert, MLAlertChannel, MLAlertDelivery, MLAlertState
from app.models.system import System
from app.models.tabular import MLModel, MLModelApiKey
from app.models.user import User
from app.models.workspace import Workspace
from app.services import ml_alerts, ml_operations
from app.services.activity_observability.queries import require_membership
from app.services.huggingface.access import is_platform_admin, is_workspace_admin
from app.services.system_access import readable_systems

router = APIRouter(prefix="/ml-operations", tags=["ml-operations"])


def require_enabled():
    if not ml_operations.enabled():
        raise HTTPException(404, "ML_OPERATIONS_DISABLED")


def visible_models(db, *, workspace, user, scope="workspace", system_id=None):
    require_membership(db, workspace, user)
    if scope == "platform" and not is_platform_admin(user):
        raise HTTPException(403, "ML_OPERATIONS_ACCESS_DENIED")
    if scope == "system" and not system_id:
        raise HTTPException(422, "ML_OPERATIONS_SYSTEM_REQUIRED")
    query = db.query(MLModel)
    if scope != "platform":
        query = query.filter_by(workspace_id=workspace.id)
    else:
        query = query.join(Workspace, Workspace.id == MLModel.workspace_id).filter(
            Workspace.is_active.is_(True), Workspace.deleted_at.is_(None)
        )
    if system_id:
        query = query.filter(MLModel.system_id == system_id)
    if scope == "platform" or is_workspace_admin(db, user, workspace):
        return query
    systems = readable_systems(
        db,
        systems=db.query(System).filter_by(workspace_id=workspace.id).all(),
        user=user,
        workspace=workspace,
    )
    return query.filter(
        or_(
            MLModel.system_id.in_([system.id for system in systems]),
            (MLModel.system_id.is_(None)) & (MLModel.created_by == user.id),
        )
    )


@router.get("/features")
def features(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_membership(db, workspace, user)
    return {
        "enabled": ml_operations.enabled(),
        "alerts_enabled": ml_alerts.enabled(),
        "can_manage_channels": is_workspace_admin(db, user, workspace),
        "scopes": ["workspace", "system"] + (["platform"] if is_platform_admin(user) else []),
    }


@router.get("/endpoints")
def endpoints(
    scope: Literal["workspace", "system", "platform"] = "workspace",
    system_id: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_enabled()
    now = datetime.utcnow()
    keys = db.query(MLModelApiKey.model_id).filter(MLModelApiKey.revoked_at.is_(None))
    if hasattr(MLModelApiKey, "expires_at"):
        keys = keys.filter(or_(MLModelApiKey.expires_at.is_(None), MLModelApiKey.expires_at > now))
    if hasattr(MLModelApiKey, "revoke_after"):
        keys = keys.filter(or_(MLModelApiKey.revoke_after.is_(None), MLModelApiKey.revoke_after > now))
    query = visible_models(
        db, workspace=workspace, user=user, scope=scope, system_id=system_id
    ).filter(or_(MLModel.published_skill_id.isnot(None), MLModel.id.in_(keys)))
    count, items = query.count(), []
    for model in query.order_by(MLModel.name, MLModel.id).offset(offset).limit(limit).all():
        state = db.get(MLAlertState, model.id)
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.workspace_id == model.workspace_id,
                AuditLog.details["model_id"].as_string() == model.id,
            )
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        api_keys = (
            db.query(MLModelApiKey)
            .filter_by(workspace_id=model.workspace_id, model_id=model.id, revoked_at=None)
            .all()
        )
        champion = (
            db.query(MLModel)
            .filter_by(workspace_id=model.workspace_id, slug=model.slug, is_champion=True)
            .first()
        )
        served = champion or model
        items.append(
            {
                "id": model.id,
                "name": model.name,
                "workspace_id": model.workspace_id,
                "system_id": model.system_id,
                "version": model.version,
                "served_id": served.id,
                "served_version": served.version,
                "skill_slug": model.published_skill_slug,
                "monitor_badge": state.badge if state else None,
                "keys": [
                    {
                        "id": key.id,
                        "name": key.name,
                        "created_at": key.created_at.isoformat(),
                        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                        "expires_at": getattr(key, "expires_at", None).isoformat()
                        if getattr(key, "expires_at", None)
                        else None,
                    }
                    for key in api_keys
                    if (not getattr(key, "expires_at", None) or key.expires_at > now)
                    and (not getattr(key, "revoke_after", None) or key.revoke_after > now)
                ],
                "metrics": ml_operations.model_metrics(db, model, now=now),
                "last_audit": {"event": audit.event_type, "at": audit.timestamp.isoformat()}
                if audit
                else None,
            }
        )
    return {
        "items": items,
        "total": count,
        "limit": limit,
        "offset": offset,
        "scope": scope,
        "window_resolution_seconds": 300,
    }


@router.get("/alerts")
def alerts(
    scope: Literal["workspace", "system", "platform"] = "workspace",
    system_id: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_enabled()
    query = db.query(MLAlert).filter(
        MLAlert.model_id.in_(
            visible_models(
                db, workspace=workspace, user=user, scope=scope, system_id=system_id
            ).with_entities(MLModel.id)
        )
    )
    return {
        "items": [
            serialize_alert(row)
            for row in query.order_by(MLAlert.created_at.desc(), MLAlert.id)
            .offset(offset)
            .limit(limit)
        ],
        "total": query.count(),
    }


def serialize_alert(row):
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "model_id": row.model_id,
        "event": row.event_type,
        "state": row.state,
        "created_at": row.created_at.isoformat(),
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
    }


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(
    alert_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_enabled()
    query = visible_models(db, workspace=workspace, user=user)
    row = (
        db.query(MLAlert)
        .filter(MLAlert.id == alert_id, MLAlert.model_id.in_(query.with_entities(MLModel.id)))
        .first()
    )
    if row is None:
        raise HTTPException(404, "ML_ALERT_NOT_FOUND")
    if not is_workspace_admin(db, user, workspace):
        raise HTTPException(403, "ML_OPERATIONS_ACCESS_DENIED")
    if row.acknowledged_at is None:
        row.acknowledged_at, row.acknowledged_by = datetime.utcnow(), user.id
        ml_alerts.audit(
            db,
            workspace.id,
            "ml.alert.acknowledged",
            {"alert_id": row.id, "model_id": row.model_id},
            actor=user.id,
        )
        db.commit()
    return serialize_alert(row)


class ChannelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["email", "webhook"]
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    destination_email: str | None = Field(None, max_length=254)
    webhook_url_ref: str | None = Field(None, max_length=255)
    signing_key_ref: str | None = Field(None, max_length=255)

    @model_validator(mode="after")
    def validate_channel(self):
        from app.services.secrets.registry import parse_ref

        if self.kind == "email":
            if (
                not self.destination_email
                or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", self.destination_email)
                or self.webhook_url_ref
                or self.signing_key_ref
            ):
                raise ValueError("ML_ALERT_CHANNEL_INVALID")
        else:
            if self.destination_email:
                raise ValueError("ML_ALERT_CHANNEL_INVALID")
            for ref in (self.webhook_url_ref, self.signing_key_ref):
                try:
                    if not ref or parse_ref(ref).scope != "workspace":
                        raise ValueError
                except Exception:
                    raise ValueError("ML_ALERT_SECRET_SCOPE_INVALID") from None
        return self


def channels_access(db, workspace, user):
    require_enabled()
    require_membership(db, workspace, user)
    if not is_workspace_admin(db, user, workspace):
        raise HTTPException(403, "ML_OPERATIONS_ACCESS_DENIED")


def serialize_channel(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "name",
            "kind",
            "enabled",
            "destination_email",
            "webhook_url_ref",
            "signing_key_ref",
        )
    }


@router.get("/channels")
def channels(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    channels_access(db, workspace, user)
    return {
        "items": [
            serialize_channel(row)
            for row in db.query(MLAlertChannel)
            .filter_by(workspace_id=workspace.id)
            .order_by(MLAlertChannel.created_at)
        ]
    }


@router.post("/channels")
def create_channel(
    body: ChannelRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    channels_access(db, workspace, user)
    from app.core.config import settings

    db.query(Workspace).filter_by(id=workspace.id).with_for_update().one()
    if db.query(MLAlertChannel).filter_by(workspace_id=workspace.id).count() >= int(
        getattr(settings, "ml_alert_channels_max", 20)
    ):
        raise HTTPException(409, "ML_ALERT_CHANNEL_LIMIT")
    row = MLAlertChannel(workspace_id=workspace.id, created_by=user.id, **body.model_dump())
    db.add(row)
    db.flush()
    ml_alerts.audit(
        db,
        workspace.id,
        "ml.alert.channel.created",
        {"channel_id": row.id, "kind": row.kind},
        actor=user.id,
    )
    db.commit()
    return serialize_channel(row)


@router.put("/channels/{channel_id}")
def update_channel(
    channel_id: str,
    body: ChannelRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    channels_access(db, workspace, user)
    row = (
        db.query(MLAlertChannel)
        .filter_by(id=channel_id, workspace_id=workspace.id)
        .with_for_update()
        .first()
    )
    if row is None:
        raise HTTPException(404, "ML_ALERT_CHANNEL_NOT_FOUND")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.created_by = user.id
    ml_alerts.audit(
        db,
        workspace.id,
        "ml.alert.channel.updated",
        {"channel_id": row.id, "kind": row.kind, "enabled": row.enabled},
        actor=user.id,
    )
    db.commit()
    return serialize_channel(row)


@router.get("/deliveries")
def deliveries(
    limit: int = Query(50, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    channels_access(db, workspace, user)
    rows = (
        db.query(MLAlertDelivery)
        .join(MLAlert)
        .filter(MLAlert.workspace_id == workspace.id)
        .order_by(MLAlert.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "alert_id": row.alert_id,
                "channel_id": row.channel_id,
                "status": row.status,
                "attempts": row.attempts,
                "error_code": row.error_code,
                "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            }
            for row in rows
        ]
    }
