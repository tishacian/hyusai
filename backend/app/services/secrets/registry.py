"""Secret registry: scoped, versioned, audited secrets behind pluggable backends.

Scopes and references
---------------------
* ``platform``  — ``secret://platform/<name>``
* ``workspace`` — ``secret://workspace/<name>`` (workspace taken from the consumer)
* ``user``      — ``secret://user/<user_id>/<name>`` (workspace from the consumer)
* ``system``    — ``secret://system/<system_id>/<name>``

An optional ``#<version>`` pins a version; otherwise the current one is used.
Names are slugs (``[a-z0-9][a-z0-9._-]*``, max 120) unique per scope owner.

Public API (stable; every function takes the SQLAlchemy session first)
----------------------------------------------------------------------
    parse_ref(ref: str) -> SecretRef
    ref_for(secret: Secret) -> str
    create(db, *, scope, name, value, actor, kind="generic", workspace_id=None,
           system_id=None, backend=None, description=None, metadata=None,
           expires_at=None) -> dict
    rotate(db, secret_id, *, value, actor, expires_at=UNSET) -> dict
    get_metadata(db, secret_id) -> dict
    list_metadata(db, *, scope, workspace_id=None, system_id=None,
                  include_disabled=False) -> list[dict]
    disable(db, secret_id, *, actor) -> dict
    destroy(db, secret_id, *, actor, version=None) -> dict
    resolve(db, ref, *, consumer: SecretConsumer) -> SecretValue

``value`` accepts ``str`` or ``SecretValue``. Mutations commit the session and
emit ``secret.created|rotated|disabled|destroyed`` in the same transaction.
``resolve`` emits ``secret.resolved`` (or ``secret.resolve_denied``) in its own
session so it never commits the caller's unit of work. Metadata dicts never
contain values; ``value_set`` tells whether the current version is readable.

Errors are ``SecretRegistryError`` with a stable ``code`` (see ``values``).
A secret stored on an unavailable backend fails closed with
``SECRET_BACKEND_UNAVAILABLE``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.secret import SECRET_BACKENDS, SECRET_KINDS, SECRET_SCOPES, Secret, SecretVersion
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.secrets.backends.base import get_backend
from app.services.secrets.values import SecretRegistryError, SecretValue

logger = get_logger(__name__)

REF_PREFIX = "secret://"
MAX_VALUE_LENGTH = 16384
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
_REF_RE = re.compile(
    r"^secret://(?:(?P<scope>platform|workspace)/(?P<name>[^/#]+)"
    r"|system/(?P<system_id>[^/#]+)/(?P<sname>[^/#]+)"
    r"|user/(?P<user_id>[a-zA-Z0-9_-]{1,36})/(?P<uname>[^/#]+))(?:#(?P<version>[1-9][0-9]*))?$"
)


class _Unset:
    pass


UNSET: Any = _Unset()


@dataclass(frozen=True)
class SecretRef:
    scope: str
    name: str
    system_id: str | None = None
    version: int | None = None
    user_id: str | None = None

    def __str__(self) -> str:
        owner = f"system/{self.system_id}" if self.scope == "system" else self.scope
        if self.scope == "user":
            owner = f"user/{self.user_id}"
        suffix = f"#{self.version}" if self.version else ""
        return f"{REF_PREFIX}{owner}/{self.name}{suffix}"


@dataclass(frozen=True)
class SecretConsumer:
    """Who resolves a secret. ``kind`` e.g. ``connector``, ``flow_node``, ``hub_fetch``."""

    kind: str
    id: str
    workspace_id: str | None = None
    system_id: str | None = None
    run_id: str | None = None
    node_id: str | None = None
    user_id: str | None = None


def parse_ref(ref: str) -> SecretRef:
    match = _REF_RE.match(ref.strip()) if isinstance(ref, str) else None
    if not match:
        raise SecretRegistryError("SECRET_INVALID_REF", "expected secret://<scope>/<name>[#v]")
    version = int(match["version"]) if match["version"] else None
    if match["user_id"]:
        ref_obj = SecretRef("user", match["uname"], version=version, user_id=match["user_id"])
    elif match["system_id"]:
        ref_obj = SecretRef("system", match["sname"], match["system_id"], version)
    else:
        ref_obj = SecretRef(match["scope"], match["name"], None, version)
    if not _NAME_RE.match(ref_obj.name):
        raise SecretRegistryError("SECRET_INVALID_REF", "invalid secret name")
    return ref_obj


def ref_for(secret: Secret) -> str:
    return str(SecretRef(secret.scope, secret.name, secret.system_id, user_id=secret.user_id))


def create(
    db: Session,
    *,
    scope: str,
    name: str,
    value: str | SecretValue,
    actor: str,
    kind: str = "generic",
    workspace_id: str | None = None,
    system_id: str | None = None,
    backend: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
    user_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    if scope not in SECRET_SCOPES:
        raise SecretRegistryError("SECRET_INVALID", "unknown scope")
    if kind not in SECRET_KINDS:
        raise SecretRegistryError("SECRET_INVALID", "unknown kind")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SecretRegistryError("SECRET_INVALID", "name must be a lowercase slug")
    backend_name = backend or settings.secret_registry_default_backend or "db"
    if backend_name not in SECRET_BACKENDS:
        raise SecretRegistryError("SECRET_INVALID", "unknown backend")
    if scope == "user":
        if system_id or not user_id or actor != user_id:
            raise SecretRegistryError("SECRET_SCOPE_VIOLATION", "user secret requires its owner")
        owner_key = user_owner_key(db, workspace_id, user_id)
    else:
        if user_id:
            raise SecretRegistryError("SECRET_SCOPE_VIOLATION", "user_id requires user scope")
        workspace_id, system_id, owner_key = _owner(db, scope, workspace_id, system_id)
    secret_value = _coerce_value(value)
    meta = _clean_metadata(metadata)

    exists = (
        db.query(Secret.id)
        .filter(Secret.scope == scope, Secret.owner_key == owner_key, Secret.name == name)
        .first()
    )
    if exists:
        raise SecretRegistryError("SECRET_NAME_TAKEN", name)

    secret = Secret(
        id=str(uuid4()),
        scope=scope,
        workspace_id=workspace_id,
        system_id=system_id,
        owner_key=owner_key,
        user_id=user_id,
        name=name,
        kind=kind,
        backend=backend_name,
        current_version=1,
        description=description,
        meta=meta,
        expires_at=expires_at,
        created_by=actor,
        created_at=datetime.utcnow(),
    )
    _store_version(db, secret, 1, secret_value, actor)
    _audit(db, secret, "secret.created", actor, {"version": 1})
    if commit:
        db.commit()
    logger.info("secret_registry.created", secret_id=secret.id, scope=scope, backend=backend_name)
    return _metadata(db, secret)


def rotate(
    db: Session,
    secret_id: str,
    *,
    value: str | SecretValue,
    actor: str,
    expires_at: Any = UNSET,
    commit: bool = True,
) -> dict[str, Any]:
    secret = _get(db, secret_id)
    if secret.scope == "user" and actor != secret.user_id:
        raise SecretRegistryError(
            "SECRET_SCOPE_VIOLATION", "only the owner can rotate a personal secret"
        )
    if secret.disabled_at is not None:
        raise SecretRegistryError("SECRET_DISABLED", secret.id)
    secret_value = _coerce_value(value)
    new_version = secret.current_version + 1
    _store_version(db, secret, new_version, secret_value, actor)
    secret.current_version = new_version
    secret.rotated_at = datetime.utcnow()
    if expires_at is not UNSET:
        secret.expires_at = expires_at
    _audit(db, secret, "secret.rotated", actor, {"version": new_version})
    if commit:
        db.commit()
    logger.info("secret_registry.rotated", secret_id=secret.id, version=new_version)
    return _metadata(db, secret)


def get_metadata(db: Session, secret_id: str) -> dict[str, Any]:
    return _metadata(db, _get(db, secret_id))


def list_metadata(
    db: Session,
    *,
    scope: str,
    workspace_id: str | None = None,
    system_id: str | None = None,
    include_disabled: bool = False,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    if scope not in SECRET_SCOPES:
        raise SecretRegistryError("SECRET_INVALID", "unknown scope")
    query = db.query(Secret).filter(Secret.scope == scope)
    if scope == "user":
        owner_key = user_owner_key(db, workspace_id, user_id)
        query = query.filter(Secret.owner_key == owner_key)
    elif scope == "workspace":
        query = query.filter(Secret.workspace_id == workspace_id)
    elif scope == "system":
        if system_id:
            query = query.filter(Secret.system_id == system_id)
        if workspace_id:
            query = query.filter(Secret.workspace_id == workspace_id)
        if not system_id and not workspace_id:
            raise SecretRegistryError("SECRET_INVALID", "system scope needs an owner filter")
    if not include_disabled:
        query = query.filter(Secret.disabled_at.is_(None))
    return [_metadata(db, s) for s in query.order_by(Secret.name).all()]


def disable(db: Session, secret_id: str, *, actor: str) -> dict[str, Any]:
    secret = _get(db, secret_id)
    if secret.disabled_at is None:
        secret.disabled_at = datetime.utcnow()
        _audit(db, secret, "secret.disabled", actor, {})
        db.commit()
    return _metadata(db, secret)


def destroy(
    db: Session, secret_id: str, *, actor: str, version: int | None = None, commit: bool = True
) -> dict[str, Any]:
    """Erase stored material. ``version=None`` destroys every version and
    disables the secret; rows stay for audit and history."""
    secret = _get(db, secret_id)
    query = db.query(SecretVersion).filter(
        SecretVersion.secret_id == secret.id, SecretVersion.destroyed_at.is_(None)
    )
    if version is not None:
        query = query.filter(SecretVersion.version == version)
    rows = query.all()
    if version is not None and not rows:
        raise SecretRegistryError("SECRET_NOT_FOUND", f"version {version}")
    backend = get_backend(secret.backend)
    now = datetime.utcnow()
    for row in rows:
        backend.destroy(secret, row)
        row.ciphertext = None
        row.destroyed_at = now
    if version is None and secret.disabled_at is None:
        secret.disabled_at = now
    _audit(
        db,
        secret,
        "secret.destroyed",
        actor,
        {"versions": sorted(r.version for r in rows)},
        severity="warning",
    )
    if commit:
        db.commit()
    return _metadata(db, secret)


def resolve(db: Session, ref: str, *, consumer: SecretConsumer) -> SecretValue:
    parsed = parse_ref(ref)
    secret: Secret | None = None
    try:
        secret = _find(db, parsed, consumer)
        if secret.disabled_at is not None:
            raise SecretRegistryError("SECRET_DISABLED", str(parsed))
        if secret.expires_at is not None and secret.expires_at <= datetime.utcnow():
            raise SecretRegistryError("SECRET_EXPIRED", str(parsed))
        version_no = parsed.version or secret.current_version
        row = (
            db.query(SecretVersion)
            .filter(SecretVersion.secret_id == secret.id, SecretVersion.version == version_no)
            .one_or_none()
        )
        if row is None:
            raise SecretRegistryError("SECRET_NOT_FOUND", f"{parsed.name}#{version_no}")
        if row.destroyed_at is not None:
            raise SecretRegistryError("SECRET_VERSION_DESTROYED", f"{parsed.name}#{version_no}")
        value = get_backend(secret.backend).get(secret, row)
    except SecretRegistryError as exc:
        _audit_resolution(secret, parsed, consumer, "secret.resolve_denied", error=exc.code)
        raise
    _audit_resolution(secret, parsed, consumer, "secret.resolved", version=version_no)
    return value


# --------------------------------------------------------------------------- internals


def user_owner_key(db: Session, workspace_id: str | None, user_id: str | None) -> str:
    """Recheck membership every time: removal immediately closes all personal tokens."""
    if not workspace_id or not user_id:
        raise SecretRegistryError("SECRET_SCOPE_VIOLATION", "user scope needs a workspace and user")
    member = (
        db.query(WorkspaceMember.id).filter_by(workspace_id=workspace_id, user_id=user_id).first()
    )
    workspace = db.get(Workspace, workspace_id, populate_existing=True)
    user = db.get(User, user_id, populate_existing=True)
    if user is None or not user.is_active:
        raise SecretRegistryError("SECRET_SCOPE_VIOLATION", "inactive user")
    if (
        not member
        or workspace is None
        or workspace.deleted_at is not None
        or not workspace.is_active
    ):
        raise SecretRegistryError(
            "SECRET_SCOPE_VIOLATION", "user is not an active workspace member"
        )
    return str(uuid5(NAMESPACE_URL, f"agentium:secret-user:{workspace_id}:{user_id}"))


def _owner(db: Session, scope: str, workspace_id, system_id):
    if scope == "platform":
        if workspace_id or system_id:
            raise SecretRegistryError("SECRET_INVALID", "platform secrets have no owner")
        return None, None, "platform"
    if scope == "workspace":
        if not workspace_id or system_id:
            raise SecretRegistryError("SECRET_INVALID", "workspace scope needs workspace_id only")
        return workspace_id, None, workspace_id
    if not system_id:
        raise SecretRegistryError("SECRET_INVALID", "system scope needs system_id")
    system = db.get(System, system_id)
    if system is None:
        raise SecretRegistryError("SECRET_INVALID", "unknown system")
    if workspace_id and system.workspace_id != workspace_id:
        raise SecretRegistryError("SECRET_SCOPE_VIOLATION", "system outside workspace")
    return system.workspace_id, system_id, system_id


def _coerce_value(value) -> SecretValue:
    if isinstance(value, SecretValue):
        secret_value = value
    elif isinstance(value, str):
        secret_value = SecretValue(value)
    else:
        raise SecretRegistryError("SECRET_INVALID", "value must be a string")
    if not secret_value:
        raise SecretRegistryError("SECRET_INVALID", "value is empty")
    if len(secret_value) > MAX_VALUE_LENGTH:
        raise SecretRegistryError("SECRET_INVALID", "value too long")
    return secret_value


def _clean_metadata(metadata) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise SecretRegistryError("SECRET_INVALID", "metadata must be an object")
    try:
        json.dumps(metadata)
    except TypeError as exc:
        raise SecretRegistryError("SECRET_INVALID", "metadata must be JSON") from exc
    return dict(metadata)


def _store_version(db: Session, secret: Secret, version: int, value: SecretValue, actor: str):
    stored = get_backend(secret.backend).put(secret, version, value)
    db.add(secret)
    db.add(
        SecretVersion(
            secret_id=secret.id,
            version=version,
            ciphertext=stored.ciphertext,
            backend_ref=stored.backend_ref,
            created_by=actor,
            created_at=datetime.utcnow(),
        )
    )
    db.flush()


def _get(db: Session, secret_id: str) -> Secret:
    secret = db.get(Secret, secret_id)
    if secret is None:
        raise SecretRegistryError("SECRET_NOT_FOUND", secret_id)
    return secret


def _find(db: Session, parsed: SecretRef, consumer: SecretConsumer) -> Secret:
    if parsed.scope == "user":
        if consumer.user_id != parsed.user_id:
            raise SecretRegistryError(
                "SECRET_SCOPE_VIOLATION", "personal secret used by another identity"
            )
        owner_key = user_owner_key(db, consumer.workspace_id, consumer.user_id)
    elif parsed.scope == "platform":
        owner_key = "platform"
    elif parsed.scope == "workspace":
        if not consumer.workspace_id:
            raise SecretRegistryError(
                "SECRET_SCOPE_VIOLATION", "workspace secret needs a workspace"
            )
        owner_key = consumer.workspace_id
    else:
        if consumer.system_id and consumer.system_id != parsed.system_id:
            raise SecretRegistryError("SECRET_SCOPE_VIOLATION", "system secret used elsewhere")
        owner_key = parsed.system_id
    secret = (
        db.query(Secret)
        .filter(
            Secret.scope == parsed.scope,
            Secret.owner_key == owner_key,
            Secret.name == parsed.name,
        )
        .one_or_none()
    )
    if secret is None:
        raise SecretRegistryError("SECRET_NOT_FOUND", str(parsed))
    if (
        parsed.scope == "system"
        and consumer.workspace_id
        and secret.workspace_id != consumer.workspace_id
    ):
        raise SecretRegistryError("SECRET_SCOPE_VIOLATION", "system secret used elsewhere")
    return secret


def _metadata(db: Session, secret: Secret) -> dict[str, Any]:
    versions = (
        db.query(SecretVersion)
        .filter(SecretVersion.secret_id == secret.id)
        .order_by(SecretVersion.version)
        .all()
    )
    current = next((v for v in versions if v.version == secret.current_version), None)
    return {
        "id": secret.id,
        "ref": ref_for(secret),
        "scope": secret.scope,
        "workspace_id": secret.workspace_id,
        "system_id": secret.system_id,
        "user_id": secret.user_id,
        "name": secret.name,
        "kind": secret.kind,
        "backend": secret.backend,
        "current_version": secret.current_version,
        "description": secret.description,
        "metadata": dict(secret.meta or {}),
        "expires_at": secret.expires_at,
        "rotated_at": secret.rotated_at,
        "created_by": secret.created_by,
        "created_at": secret.created_at,
        "disabled_at": secret.disabled_at,
        "value_set": bool(current and current.destroyed_at is None),
        "versions": [
            {
                "version": v.version,
                "created_by": v.created_by,
                "created_at": v.created_at,
                "destroyed_at": v.destroyed_at,
            }
            for v in versions
        ],
    }


def _base_details(secret: Secret) -> dict[str, Any]:
    return {
        "secret_id": secret.id,
        "ref": ref_for(secret),
        "scope": secret.scope,
        "system_id": secret.system_id,
        "user_id": secret.user_id,
        "backend": secret.backend,
    }


def _audit(db, secret, event_type, actor, extra, severity: str = "info") -> None:
    emit_audit_event(
        workspace_id=secret.workspace_id,
        event_type=event_type,
        actor=actor,
        details={**_base_details(secret), **extra},
        severity=severity,
        db=db,
    )


def _audit_resolution(secret, parsed, consumer, event_type, **extra) -> None:
    emit_audit_event(
        workspace_id=(secret.workspace_id if secret else None) or consumer.workspace_id,
        event_type=event_type,
        actor=f"{consumer.kind}:{consumer.id}",
        details={
            **(_base_details(secret) if secret else {}),
            "requested_ref": str(parsed),
            "consumer": asdict(consumer),
            **extra,
        },
        trace_id=consumer.run_id,
        severity="info" if event_type == "secret.resolved" else "warning",
    )
