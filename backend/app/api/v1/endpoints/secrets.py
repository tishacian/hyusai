"""Secret registry API: metadata only, values are write-only.

Workspace secrets need a workspace admin, system secrets a workspace admin or
a granular system admin, platform secrets a platform admin. Request bodies are
read as raw JSON objects: a pydantic validation error echoes its input, and
the input carries the value.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.audit import AuditLog
from app.models.secret import Secret
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services import secrets as registry
from app.services.huggingface.access import is_platform_admin, is_workspace_admin
from app.services.iam.decision_plane import enforce_action
from app.services.secrets import SecretRegistryError

router = APIRouter()

_STATUS = {
    "SECRET_INVALID": 400,
    "SECRET_INVALID_REF": 400,
    "SECRET_NOT_FOUND": 404,
    "SECRET_NAME_TAKEN": 409,
    "SECRET_DISABLED": 409,
    "SECRET_EXPIRED": 409,
    "SECRET_VERSION_DESTROYED": 409,
    "SECRET_SCOPE_VIOLATION": 403,
    "SECRET_BACKEND_UNAVAILABLE": 503,
    "SECRET_KEY_NOT_CONFIGURED": 503,
}
_CREATE_FIELDS = {"scope", "name", "value", "kind", "system_id", "description", "metadata", "expires_at"}


def _http(exc: SecretRegistryError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(exc.code, 400), detail={"code": exc.code, "message": exc.message}
    )


def _denied(code: str = "WORKSPACE_PERMISSION_DENIED") -> HTTPException:
    return HTTPException(status_code=403, detail={"code": code})


def _system_in_workspace(db: DBSession, workspace: Workspace, system_id: Any) -> System:
    system = db.get(System, system_id) if isinstance(system_id, str) and system_id else None
    if system is None or system.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail={"code": "SYSTEM_NOT_FOUND"})
    return system


def _require_scope_admin(
    db: DBSession, user: User, workspace: Workspace, scope: str, system: Optional[System]
) -> None:
    if scope == "platform":
        if not is_platform_admin(user):
            raise _denied("PLATFORM_PERMISSION_DENIED")
        return
    if is_workspace_admin(db, user, workspace):
        return
    if scope == "system" and system is not None:
        enforce_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="admin",
            legacy_allowed=False,
            resource_attrs={"system_id": system.id, "capability_id": system.capability_id},
        )
        return
    raise _denied()


def _load(db: DBSession, user: User, workspace: Workspace, secret_id: str) -> Secret:
    secret = db.get(Secret, secret_id)
    if secret is None or (secret.scope != "platform" and secret.workspace_id != workspace.id):
        raise HTTPException(status_code=404, detail={"code": "SECRET_NOT_FOUND"})
    system = db.get(System, secret.system_id) if secret.system_id else None
    _require_scope_admin(db, user, workspace, secret.scope, system)
    return secret


def _object(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"code": "SECRET_INVALID", "message": "JSON object expected"})
    return body


def _optional_str(body: dict[str, Any], key: str) -> Optional[str]:
    value = body.get(key)
    if value is not None and not isinstance(value, str):
        raise HTTPException(status_code=400, detail={"code": "SECRET_INVALID", "message": f"{key} must be a string"})
    return value or None


def _datetime(body: dict[str, Any], key: str) -> Optional[datetime]:
    raw = _optional_str(body, key)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "SECRET_INVALID", "message": f"{key} must be ISO 8601"}) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@router.get("")
async def list_secrets(
    scope: str = Query("workspace"),
    system_id: Optional[str] = Query(None),
    include_disabled: bool = Query(False),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_in_workspace(db, workspace, system_id) if system_id else None
    _require_scope_admin(db, user, workspace, scope, system)
    try:
        rows = registry.list_metadata(
            db,
            scope=scope,
            workspace_id=None if scope == "platform" else workspace.id,
            system_id=system_id,
            include_disabled=include_disabled,
        )
    except SecretRegistryError as exc:
        raise _http(exc) from exc
    return {"secrets": rows, "can_manage_platform": is_platform_admin(user)}


@router.post("", status_code=201)
async def create_secret(
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    body = _object(body)
    unknown = sorted(set(body) - _CREATE_FIELDS)
    if unknown:
        raise HTTPException(status_code=400, detail={"code": "SECRET_INVALID", "message": f"unknown fields: {', '.join(unknown)}"})
    scope = body.get("scope") or "workspace"
    if scope not in ("platform", "workspace", "system"):
        raise HTTPException(status_code=400, detail={"code": "SECRET_INVALID", "message": "unknown scope"})
    system = _system_in_workspace(db, workspace, body.get("system_id")) if scope == "system" else None
    _require_scope_admin(db, user, workspace, scope, system)
    try:
        return registry.create(
            db,
            scope=scope,
            name=body.get("name"),
            value=body.get("value"),
            actor=user.id,
            kind=body.get("kind") or "generic",
            workspace_id=workspace.id if scope == "workspace" else None,
            system_id=system.id if system else None,
            description=_optional_str(body, "description"),
            metadata=body.get("metadata"),
            expires_at=_datetime(body, "expires_at"),
        )
    except SecretRegistryError as exc:
        raise _http(exc) from exc


@router.get("/{secret_id}")
async def get_secret(
    secret_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    secret = _load(db, user, workspace, secret_id)
    return registry.get_metadata(db, secret.id)


@router.get("/{secret_id}/consumers")
async def list_consumers(
    secret_id: str,
    limit: int = Query(200, ge=1, le=1000),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Distinct consumers seen in ``secret.resolved`` audit events, newest first."""
    secret = _load(db, user, workspace, secret_id)
    query = db.query(AuditLog).filter(AuditLog.event_type == "secret.resolved")
    if secret.workspace_id:
        query = query.filter(AuditLog.workspace_id == secret.workspace_id)
    consumers: dict[tuple, dict[str, Any]] = {}
    for row in query.order_by(AuditLog.timestamp.desc()).limit(limit * 20).all():
        details = row.details or {}
        if details.get("secret_id") != secret.id:
            continue
        consumer = details.get("consumer") or {}
        key = (consumer.get("kind"), consumer.get("id"), consumer.get("node_id"))
        entry = consumers.get(key)
        if entry is None:
            if len(consumers) >= limit:
                continue
            consumers[key] = {
                "kind": consumer.get("kind"),
                "id": consumer.get("id"),
                "system_id": consumer.get("system_id"),
                "node_id": consumer.get("node_id"),
                "last_resolved_at": row.timestamp,
                "last_version": details.get("version"),
                "count": 1,
            }
        else:
            entry["count"] += 1
    return {"consumers": list(consumers.values())}


@router.post("/{secret_id}/rotate")
async def rotate_secret(
    secret_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    body = _object(body)
    secret = _load(db, user, workspace, secret_id)
    kwargs: dict[str, Any] = {}
    if "expires_at" in body:
        kwargs["expires_at"] = _datetime(body, "expires_at")
    try:
        return registry.rotate(db, secret.id, value=body.get("value"), actor=user.id, **kwargs)
    except SecretRegistryError as exc:
        raise _http(exc) from exc


@router.post("/{secret_id}/disable")
async def disable_secret(
    secret_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    secret = _load(db, user, workspace, secret_id)
    return registry.disable(db, secret.id, actor=user.id)


@router.delete("/{secret_id}")
async def destroy_secret(
    secret_id: str,
    version: Optional[int] = Query(None, ge=1),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    secret = _load(db, user, workspace, secret_id)
    try:
        return registry.destroy(db, secret.id, actor=user.id, version=version)
    except SecretRegistryError as exc:
        raise _http(exc) from exc
