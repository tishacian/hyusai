"""Narrow, expiring egress grants. Workspace administrators cannot create them."""

from __future__ import annotations

import ipaddress
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_

from app.models.connector_governance import ConnectorNetworkException
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.huggingface.access import is_platform_admin


class NetworkExceptionError(RuntimeError):
    def __init__(self, code, status_code=400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def utc_naive(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise NetworkExceptionError("CONNECTOR_EXCEPTION_EXPIRY_INVALID")
    return value.astimezone(UTC).replace(tzinfo=None)


def checked_network(cidr):
    try:
        network = ipaddress.ip_network(cidr, strict=True)
    except (ValueError, TypeError):
        raise NetworkExceptionError("CONNECTOR_EXCEPTION_NETWORK_INVALID") from None
    private = [
        ipaddress.ip_network(c)
        for c in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
    ]
    minimum = 24 if network.version == 4 else 64
    if network.prefixlen < minimum or not any(
        network.version == allowed.version and network.subnet_of(allowed) for allowed in private
    ):
        raise NetworkExceptionError("CONNECTOR_EXCEPTION_NETWORK_FORBIDDEN", 403)
    return network


def _admin(user):
    if not is_platform_admin(user):
        raise NetworkExceptionError("PLATFORM_PERMISSION_DENIED", 403)


def create_exception(db, *, user, workspace_id, cidr, ports, reason, expires_at, now=None):
    _admin(user)
    now = now or datetime.now(UTC)
    expiry = utc_naive(expires_at)
    if not utc_naive(now) < expiry <= utc_naive(now) + timedelta(days=90):
        raise NetworkExceptionError("CONNECTOR_EXCEPTION_EXPIRY_INVALID")
    network = checked_network(cidr)
    if (
        not isinstance(ports, list)
        or not 1 <= len(ports) <= 32
        or any(type(port) is not int or not 1 <= port <= 65535 for port in ports)
    ):
        raise NetworkExceptionError("CONNECTOR_EXCEPTION_PORTS_INVALID")
    if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 1000:
        raise NetworkExceptionError("CONNECTOR_EXCEPTION_REASON_REQUIRED")
    workspace = db.get(Workspace, workspace_id) if workspace_id else None
    if workspace_id and (not workspace or not workspace.is_active or workspace.deleted_at):
        raise NetworkExceptionError("WORKSPACE_NOT_FOUND", 404)
    row = ConnectorNetworkException(
        workspace_id=workspace_id,
        cidr=str(network),
        ports=sorted(set(ports)),
        reason=reason.strip(),
        expires_at=expiry,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    if (
        emit_audit_event(
            db=db,
            event_type="network.exception_created",
            actor=user.id,
            workspace_id=workspace_id,
            details={
                "exception_id": row.id,
                "cidr": row.cidr,
                "ports": row.ports,
                "expires_at": expiry.isoformat(),
            },
        )
        is None
    ):
        db.rollback()
        raise NetworkExceptionError("CONNECTOR_AUDIT_REQUIRED", 503)
    db.commit()
    return row


def revoke_exception(db, *, user, exception_id):
    _admin(user)
    row = db.get(ConnectorNetworkException, exception_id)
    if row is None:
        raise NetworkExceptionError("CONNECTOR_EXCEPTION_NOT_FOUND", 404)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC).replace(tzinfo=None)
        row.revoked_by = user.id
        if (
            emit_audit_event(
                db=db,
                event_type="network.exception_revoked",
                actor=user.id,
                workspace_id=row.workspace_id,
                details={"exception_id": row.id},
            )
            is None
        ):
            db.rollback()
            raise NetworkExceptionError("CONNECTOR_AUDIT_REQUIRED", 503)
        db.commit()
    return row


@dataclass(frozen=True)
class NetworkGrant:
    cidr: str
    ports: tuple[int, ...]
    expires_at: datetime


_grants: ContextVar[tuple[NetworkGrant, ...]] = ContextVar("connector_network_grants", default=())


def load_grants(db, workspace_id, *, now=None):
    now = now or datetime.now(UTC)
    rows = (
        db.query(ConnectorNetworkException)
        .filter(
            ConnectorNetworkException.revoked_at.is_(None),
            ConnectorNetworkException.expires_at > utc_naive(now),
            or_(
                ConnectorNetworkException.workspace_id.is_(None),
                ConnectorNetworkException.workspace_id == workspace_id,
            ),
        )
        .all()
    )
    return tuple(
        NetworkGrant(row.cidr, tuple(row.ports), row.expires_at.replace(tzinfo=UTC)) for row in rows
    )


@contextmanager
def network_grants(grants):
    """Only trusted runtime code may supply grants loaded from the database.

    The runner serializes these independently of user parameters. Context is
    local to one call, never a global allow-list shared by other workspaces.
    """
    token = _grants.set(tuple(grants))
    try:
        yield
    finally:
        _grants.reset(token)


def approved_cidrs(port, *, now=None):
    now = now or datetime.now(UTC)
    return tuple(
        str(checked_network(grant.cidr))
        for grant in _grants.get()
        if port in grant.ports and utc_naive(grant.expires_at) > utc_naive(now)
    )
