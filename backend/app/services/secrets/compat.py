"""Dual read / registry write for connector secrets kept in settings JSON.

A secret field (``token_encrypted``, ``secrets.token``...) holds either a
registry reference ``{"ref": "secret://..."}`` or, until the migration ran, a
legacy per-service envelope string. ``read_secret_field`` resolves the
reference first and only then hands the envelope to the service's own
decrypt function. ``write_secret_field`` creates (or rotates) the named secret
and returns the reference to store in place of the envelope; with no registry
key configured it falls back to the legacy envelope so a deployment without
``SECRET_REGISTRY_FERNET_KEY`` keeps working.

Callers report ``*_set`` with ``bool(stored)``: a reference is as truthy as an
envelope, so public payloads do not change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.models.secret import Secret
from app.services.secrets import registry
from app.services.secrets.registry import REF_PREFIX, SecretConsumer
from app.services.secrets.values import SecretRegistryError

ACTOR_SYSTEM = "system:secret-compat"


def ref_of(stored: Any) -> str | None:
    if isinstance(stored, Mapping):
        ref = stored.get("ref")
        if isinstance(ref, str) and ref.startswith(REF_PREFIX):
            return ref
    return None


def is_ref(stored: Any) -> bool:
    return ref_of(stored) is not None


def secret_name(*parts: str) -> str:
    """Derived secret name: ``("mcp", "My_Server", "token")`` -> ``mcp-my-server-token``."""
    text = "-".join(str(part) for part in parts if part)
    slug = "".join(c if c.isalnum() or c in ".-" else "-" for c in text.lower())
    slug = "-".join(filter(None, slug.split("-")))
    return slug[:120].strip("-.") or "secret"


def kind_for(field: str) -> str:
    field = field.lower()
    if "password" in field:
        return "password"
    if "api_key" in field:
        return "api_key"
    if "client_secret" in field:
        return "oauth_client"
    if "token" in field:
        return "token"
    return "generic"


def _session_for(owner: Any):
    if owner is None:
        return None
    from sqlalchemy.orm import object_session
    from sqlalchemy.orm.exc import UnmappedInstanceError

    try:
        return object_session(owner)
    except UnmappedInstanceError:
        return None


def read_secret_field(
    stored: Any,
    *,
    legacy: Callable[[str], str | None],
    consumer: SecretConsumer,
    db: Any = None,
    owner: Any = None,
) -> str | None:
    """Clear value of a stored field, or ``None`` when empty.

    ``owner`` (the workspace row) lends its session when ``db`` is not given;
    otherwise a short-lived session is opened for the resolution.
    """
    if not stored:
        return None
    ref = ref_of(stored)
    if ref is None:
        return legacy(stored if isinstance(stored, str) else str(stored))
    session = db or _session_for(owner)
    if session is not None:
        return registry.resolve(session, ref, consumer=consumer).reveal()
    from app.db.base import SessionLocal

    with SessionLocal() as own:
        return registry.resolve(own, ref, consumer=consumer).reveal()


def write_secret_field(
    db: Any,
    value: str,
    *,
    scope: str,
    name: str,
    legacy: Callable[[str], Any] | None,
    actor: str = ACTOR_SYSTEM,
    kind: str = "token",
    workspace_id: str | None = None,
    description: str | None = None,
) -> Any:
    """Store ``value`` in the registry and return ``{"ref": ...}``.

    An existing secret of that name is rotated. With no registry key (or no
    session) ``legacy(value)`` is returned instead, when given.
    """
    from sqlalchemy.orm import Session

    if not isinstance(db, Session) or (scope == "workspace" and not workspace_id):
        if legacy is None:
            raise SecretRegistryError("SECRET_INVALID", "no session to store the secret")
        return legacy(value)
    owner_key = "platform" if scope == "platform" else workspace_id
    existing = (
        db.query(Secret)
        .filter(Secret.scope == scope, Secret.owner_key == owner_key, Secret.name == name)
        .one_or_none()
    )
    try:
        if existing is not None:
            meta = registry.rotate(db, existing.id, value=value, actor=actor)
        else:
            meta = registry.create(
                db,
                scope=scope,
                name=name,
                value=value,
                actor=actor,
                kind=kind,
                workspace_id=workspace_id if scope == "workspace" else None,
                description=description,
            )
    except SecretRegistryError as exc:
        if exc.code == "SECRET_KEY_NOT_CONFIGURED" and legacy is not None:
            return legacy(value)
        raise
    return {"ref": meta["ref"]}
