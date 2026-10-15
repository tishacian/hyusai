"""Connection registry. Mutations join the caller's transaction; never import drivers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.connector_connection import ConnectorConnection, ConnectorDelegation, ConnectorGrant
from app.models.secret import Secret
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.connection import ConnectionCreate, ConnectionUpdate
from app.services import secrets as registry
from app.services.connectors.profiles import get_profile
from app.services.huggingface.access import is_workspace_admin
from app.services.secrets.registry import user_owner_key


class ConnectionError(ValueError):
    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def audit(db: Session, connection: ConnectorConnection, event: str, actor: str, **details):
    # Security/governance audit is mandatory and participates in this transaction.
    db.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=connection.workspace_id,
            event_type=event,
            actor=actor,
            details={
                "connection_id": connection.id,
                "profile_key": connection.profile_key,
                **details,
            },
        )
    )


def require_registry() -> None:
    backend = registry.get_backend(settings.secret_registry_default_backend or "db")
    if not backend.health().get("ok"):
        raise ConnectionError("CONNECTOR_REGISTRY_REQUIRED", 503)


def get_connection(db: Session, workspace_id: str, connection_id: str) -> ConnectorConnection:
    row = (
        db.query(ConnectorConnection)
        .filter_by(workspace_id=workspace_id, id=connection_id)
        .one_or_none()
    )
    if row is None or row.disabled_at is not None:
        raise ConnectionError("CONNECTOR_NOT_FOUND", 404)
    return row


def list_connections(db: Session, workspace_id: str) -> list[ConnectorConnection]:
    return (
        db.query(ConnectorConnection)
        .filter_by(workspace_id=workspace_id, disabled_at=None)
        .order_by(ConnectorConnection.name, ConnectorConnection.id)
        .all()
    )


def serialize_connection(row: ConnectorConnection) -> dict[str, Any]:
    from sqlalchemy.orm import object_session

    from app.services.connectors.runtime_identity import connection_decision

    decision = connection_decision(object_session(row), row)
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "workspace_id",
            "name",
            "profile_key",
            "profile_version",
            "values",
            "secret_refs",
            "access",
            "allowed_schemas",
            "allowed_tables",
            "revision",
            "last_test",
            "created_at",
            "updated_at",
        )
    } | {
        "certification": decision.level,
        "certification_reason": decision.reason,
        "certification_evidence": list(decision.evidence_sha256),
    }


def _validate_refs(db: Session, workspace_id: str, refs: dict[str, str]) -> None:
    for ref in refs.values():
        parsed = registry.parse_ref(ref)
        if parsed.scope != "workspace":
            raise ConnectionError("CONNECTOR_SECRET_SCOPE_VIOLATION", 403)
        secret = (
            db.query(Secret)
            .filter_by(
                scope="workspace",
                workspace_id=workspace_id,
                owner_key=workspace_id,
                name=parsed.name,
            )
            .one_or_none()
        )
        if secret is None or secret.disabled_at is not None:
            raise ConnectionError("CONNECTOR_SECRET_UNAVAILABLE", 400)
        metadata = registry.get_metadata(db, secret.id)
        version = parsed.version or secret.current_version
        if not any(
            v["version"] == version and v["destroyed_at"] is None for v in metadata["versions"]
        ):
            raise ConnectionError("CONNECTOR_SECRET_UNAVAILABLE", 400)
        if secret.expires_at and secret.expires_at <= datetime.utcnow():
            raise ConnectionError("CONNECTOR_SECRET_UNAVAILABLE", 400)


def _validate_policy(profile, values, access, schemas, tables):
    if profile.family in {"uc_rest", "delta_sharing", "iceberg_rest"}:
        from app.services.connectors.lakehouse_contracts import validate_config

        validate_config(values)
    if profile.family in {"mcp", "openapi"} or (
        profile.key in {"sharepoint_files", "onedrive"} and values.get("auth_mode") == "oauth_user"
    ):
        from app.services.connectors.tool_contracts import compile_openapi, validate_tool_config

        validate_tool_config(values)
        if profile.family == "openapi" and values.get("openapi_spec"):
            compile_openapi(values["openapi_spec"], values)
    if (
        access == "read_write"
        and not (profile.family in {"mcp", "openapi"} and values.get("write_tools"))
        and not any(
            (
                profile.capabilities.write_append,
                profile.capabilities.write_overwrite,
                profile.capabilities.write_upsert,
                profile.capabilities.export_files,
            )
        )
    ):
        raise ConnectionError("CONNECTOR_OPERATION_UNSUPPORTED", 409)
    if profile.key == "sap_hana" and (
        values.get("encrypt") is not True or values.get("ssl_validate_certificate") is not True
    ):
        raise ConnectionError("CONNECTOR_TLS_REQUIRED", 400)
    if any(
        not item or len(item) > 255 or any(ord(c) < 32 for c in item)
        for item in [*schemas, *tables]
    ):
        raise ConnectionError("CONNECTOR_RESTRICTION_INVALID")


def create_connection(
    db: Session,
    *,
    workspace_id: str,
    actor: str,
    data: ConnectionCreate,
    legacy_source: str | None = None,
) -> ConnectorConnection:
    require_registry()
    profile = get_profile(data.profile_key)
    values = profile.validate_values(data.values, data.secret_refs)
    if values.get("tool_contracts"):
        raise ConnectionError("CONNECTOR_TOOL_CATALOG_IMPORT_REQUIRED")
    _validate_refs(db, workspace_id, data.secret_refs)
    _validate_policy(profile, values, data.access, data.allowed_schemas, data.allowed_tables)
    name = data.name.strip()
    if not name:
        raise ConnectionError("CONNECTOR_NAME_INVALID")
    if db.query(ConnectorConnection.id).filter_by(workspace_id=workspace_id, name=name).first():
        raise ConnectionError("CONNECTOR_NAME_TAKEN", 409)
    row = ConnectorConnection(
        id=str(uuid4()),
        workspace_id=workspace_id,
        name=name,
        profile_key=profile.key,
        profile_version=profile.version,
        values=values,
        secret_refs=dict(data.secret_refs),
        access=data.access,
        allowed_schemas=data.allowed_schemas,
        allowed_tables=data.allowed_tables,
        created_by=actor,
        revision=1,
        legacy_source=legacy_source,
    )
    db.add(row)
    audit(db, row, "connection.created", actor)
    db.flush()
    return row


def update_connection(
    db: Session,
    row: ConnectorConnection,
    *,
    actor: str,
    data: ConnectionUpdate,
    trusted_tool_catalog: bool = False,
) -> ConnectorConnection:
    profile = get_profile(row.profile_key)
    if row.profile_version != profile.version:
        raise ConnectionError("CONNECTOR_PROFILE_VERSION_CHANGED", 409)
    values = profile.validate_values(
        data.values if data.values is not None else row.values,
        data.secret_refs if data.secret_refs is not None else row.secret_refs,
    )
    if (
        values.get("tool_contracts", {}) != row.values.get("tool_contracts", {})
        and not trusted_tool_catalog
    ):
        raise ConnectionError("CONNECTOR_TOOL_CATALOG_IMPORT_REQUIRED")
    refs = data.secret_refs if data.secret_refs is not None else row.secret_refs
    _validate_refs(db, row.workspace_id, refs)
    access = data.access or row.access
    schemas = data.allowed_schemas if data.allowed_schemas is not None else row.allowed_schemas
    tables = data.allowed_tables if data.allowed_tables is not None else row.allowed_tables
    _validate_policy(profile, values, access, schemas, tables)
    name = data.name.strip() if data.name is not None else row.name
    if not name:
        raise ConnectionError("CONNECTOR_NAME_INVALID")
    if (
        db.query(ConnectorConnection.id)
        .filter(
            ConnectorConnection.workspace_id == row.workspace_id,
            ConnectorConnection.name == name,
            ConnectorConnection.id != row.id,
        )
        .first()
    ):
        raise ConnectionError("CONNECTOR_NAME_TAKEN", 409)
    result = db.execute(
        update(ConnectorConnection)
        .where(
            ConnectorConnection.id == row.id,
            ConnectorConnection.workspace_id == row.workspace_id,
            ConnectorConnection.revision == data.revision,
            ConnectorConnection.disabled_at.is_(None),
        )
        .values(
            name=name,
            values=values,
            secret_refs=refs,
            access=access,
            allowed_schemas=schemas,
            allowed_tables=tables,
            revision=data.revision + 1,
            last_test=None,
            updated_at=datetime.utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ConnectionError("CONNECTOR_REVISION_CONFLICT", 409)
    db.refresh(row)
    # A changed endpoint must never silently inherit someone's earlier consent.
    for grant in db.query(ConnectorGrant).filter_by(connection_id=row.id, revoked_at=None).all():
        revoke_grant(db, grant, actor=actor)
    audit(db, row, "connection.updated", actor, revision=row.revision)
    db.flush()
    return row


def delete_connection(db: Session, row: ConnectorConnection, *, actor: str):
    for grant in db.query(ConnectorGrant).filter_by(connection_id=row.id, revoked_at=None).all():
        revoke_grant(db, grant, actor=actor)
    row.disabled_at = datetime.utcnow()
    row.revision += 1
    audit(db, row, "connection.deleted", actor)
    db.flush()


def create_grant(
    db: Session,
    connection: ConnectorConnection,
    *,
    owner_user_id: str,
    token_refs: dict[str, str],
    scopes: list[str],
    expires_at: datetime | None = None,
) -> ConnectorGrant:
    """Trusted OAuth callback primitive; deliberately has no token-accepting HTTP route."""
    owner_key = user_owner_key(db, connection.workspace_id, owner_user_id)
    if not token_refs:
        raise ConnectionError("CONNECTOR_GRANT_INVALID")
    for ref in token_refs.values():
        parsed = registry.parse_ref(ref)
        if parsed.scope != "user" or parsed.user_id != owner_user_id:
            raise ConnectionError("CONNECTOR_SECRET_SCOPE_VIOLATION", 403)
        secret = (
            db.query(Secret)
            .filter_by(scope="user", owner_key=owner_key, name=parsed.name, disabled_at=None)
            .one_or_none()
        )
        if secret is None:
            raise ConnectionError("CONNECTOR_SECRET_UNAVAILABLE")
        # Personal tokens must not be reused across connections.
        for other in (
            db.query(ConnectorGrant)
            .filter(
                ConnectorGrant.owner_user_id == owner_user_id,
                ConnectorGrant.workspace_id == connection.workspace_id,
                ConnectorGrant.connection_id != connection.id,
            )
            .all()
        ):
            if any(
                registry.parse_ref(other_ref).name == parsed.name
                for other_ref in (other.token_refs or {}).values()
            ):
                raise ConnectionError("CONNECTOR_GRANT_TOKEN_REUSED", 409)
    grant = (
        db.query(ConnectorGrant)
        .filter_by(connection_id=connection.id, owner_user_id=owner_user_id)
        .one_or_none()
    )
    if grant is not None and grant.revoked_at is None:
        raise ConnectionError("CONNECTOR_GRANT_EXISTS", 409)
    if grant is None:
        grant = ConnectorGrant(
            id=str(uuid4()),
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            owner_user_id=owner_user_id,
        )
        db.add(grant)
    grant.token_refs = dict(token_refs)
    grant.scopes = list(scopes)
    grant.granted_at = datetime.utcnow()
    grant.expires_at = expires_at
    grant.revoked_at = None
    grant.revoked_by = None
    audit(db, connection, "connection.grant.created", owner_user_id, grant_id=grant.id)
    db.flush()
    return grant


def revoke_grant(db: Session, grant: ConnectorGrant, *, actor: str):
    connection = db.get(ConnectorConnection, grant.connection_id)
    if grant.revoked_at is None and connection.values.get("revocation_endpoint"):
        from app.services.connectors.oauth import revoke_provider_tokens

        revoke_provider_tokens(db, connection, grant, actor=actor)
    now = datetime.utcnow()
    grant.revoked_at, grant.revoked_by = now, actor
    for delegation in (
        db.query(ConnectorDelegation).filter_by(grant_id=grant.id, revoked_at=None).all()
    ):
        delegation.revoked_at, delegation.revoked_by = now, actor
    # Find by owner key without requiring current membership: removal must erase tokens too.
    from uuid import NAMESPACE_URL, uuid5

    owner_key = str(
        uuid5(NAMESPACE_URL, f"agentium:secret-user:{grant.workspace_id}:{grant.owner_user_id}")
    )
    for ref in (grant.token_refs or {}).values():
        parsed = registry.parse_ref(ref)
        secret = (
            db.query(Secret)
            .filter_by(scope="user", owner_key=owner_key, name=parsed.name)
            .one_or_none()
        )
        if secret:
            registry.destroy(db, secret.id, actor=actor, commit=False)
    connection = db.get(ConnectorConnection, grant.connection_id)
    audit(db, connection, "connection.grant.revoked", actor, grant_id=grant.id)
    db.flush()


def revoke_user_grants(db: Session, *, workspace_id: str, user_id: str, actor: str):
    for grant in (
        db.query(ConnectorGrant)
        .filter_by(workspace_id=workspace_id, owner_user_id=user_id, revoked_at=None)
        .all()
    ):
        revoke_grant(db, grant, actor=actor)
    for secret in (
        db.query(Secret)
        .filter_by(scope="user", workspace_id=workspace_id, user_id=user_id, disabled_at=None)
        .all()
    ):
        registry.destroy(db, secret.id, actor=actor, commit=False)


def create_delegation(
    db: Session, grant: ConnectorGrant, *, actor: str, system_version_id: str, expires_at: datetime
) -> ConnectorDelegation:
    if actor != grant.owner_user_id or grant.revoked_at is not None:
        raise ConnectionError("CONNECTOR_GRANT_REQUIRED", 403)
    user_owner_key(db, grant.workspace_id, actor)
    version = db.get(SystemVersion, system_version_id)
    system = db.get(System, version.system_id) if version else None
    if (
        version is None
        or version.workspace_id != grant.workspace_id
        or version.release_kind not in {"publish", "rollback"}
        or system is None
        or system.published_flow_version_id != version.id
    ):
        raise ConnectionError("CONNECTOR_SYSTEM_VERSION_REQUIRED", 409)
    if expires_at <= datetime.utcnow() or (grant.expires_at and expires_at > grant.expires_at):
        raise ConnectionError("CONNECTOR_DELEGATION_EXPIRY_INVALID")
    delegation = ConnectorDelegation(
        id=str(uuid4()),
        workspace_id=grant.workspace_id,
        grant_id=grant.id,
        system_id=version.system_id,
        system_version_id=version.id,
        created_by=actor,
        expires_at=expires_at,
    )
    db.add(delegation)
    audit(
        db,
        db.get(ConnectorConnection, grant.connection_id),
        "connection.delegation.requested",
        actor,
        delegation_id=delegation.id,
    )
    db.flush()
    return delegation


def approve_delegation(db: Session, delegation: ConnectorDelegation, *, actor: User):
    workspace = db.get(Workspace, delegation.workspace_id)
    if not workspace or not is_workspace_admin(db, actor, workspace):
        raise ConnectionError("CONNECTOR_ADMIN_REQUIRED", 403)
    grant = db.get(ConnectorGrant, delegation.grant_id, populate_existing=True)
    if (
        grant is None
        or grant.revoked_at
        or (grant.expires_at and grant.expires_at <= datetime.utcnow())
    ):
        raise ConnectionError("CONNECTOR_GRANT_REQUIRED", 403)
    user_owner_key(db, grant.workspace_id, grant.owner_user_id)
    system = db.get(System, delegation.system_id)
    if system is None or system.published_flow_version_id != delegation.system_version_id:
        raise ConnectionError("CONNECTOR_SYSTEM_VERSION_REQUIRED", 409)
    if delegation.revoked_at or delegation.expires_at <= datetime.utcnow():
        raise ConnectionError("CONNECTOR_GRANT_REQUIRED", 403)
    delegation.approved_by, delegation.approved_at = actor.id, datetime.utcnow()
    grant = db.get(ConnectorGrant, delegation.grant_id)
    audit(
        db,
        db.get(ConnectorConnection, grant.connection_id),
        "connection.delegation.approved",
        actor.id,
        delegation_id=delegation.id,
    )
    db.flush()


def _credential_references(
    db: Session,
    connection: ConnectorConnection,
    *,
    user_id: str | None = None,
    system_id: str | None = None,
    system_version_id: str | None = None,
    delegation_id: str | None = None,
    run_id: str | None = None,
):
    # Do not trust a cached ORM row: revocation is checked at each execution boundary.
    db.refresh(connection)
    if connection.disabled_at:
        raise ConnectionError("CONNECTOR_NOT_FOUND", 404)
    workspace = db.get(Workspace, connection.workspace_id, populate_existing=True)
    if workspace is None or workspace.deleted_at or not workspace.is_active:
        raise ConnectionError("CONNECTOR_NOT_FOUND", 404)
    if user_id:
        user_owner_key(db, connection.workspace_id, user_id)
    if system_id:
        system = db.get(System, system_id, populate_existing=True)
        if system is None or system.workspace_id != connection.workspace_id:
            raise ConnectionError("CONNECTOR_GRANT_REQUIRED", 403)
    refs = dict(connection.secret_refs or {})
    acting_user = user_id
    # SQL profiles currently use workspace service credentials. Future OAuth profiles
    # must explicitly declare auth_mode=oauth_user; absence never picks someone else's grant.
    personal = connection.values.get("auth_mode") == "oauth_user"
    grant = delegation = None
    if personal:
        grant = None
        if user_id:
            grant = (
                db.query(ConnectorGrant)
                .filter_by(
                    workspace_id=connection.workspace_id,
                    connection_id=connection.id,
                    owner_user_id=user_id,
                )
                .populate_existing()
                .one_or_none()
            )
        elif delegation_id and system_id and system_version_id:
            delegation = db.get(ConnectorDelegation, delegation_id, populate_existing=True)
            if (
                delegation
                and delegation.workspace_id == connection.workspace_id
                and delegation.system_id == system_id
                and delegation.system_version_id == system_version_id
                and system.published_flow_version_id == system_version_id
                and delegation.approved_at
                and delegation.revoked_at is None
                and delegation.expires_at > datetime.utcnow()
            ):
                grant = db.get(ConnectorGrant, delegation.grant_id, populate_existing=True)
                if grant and grant.connection_id != connection.id:
                    grant = None
                if grant:
                    acting_user = grant.owner_user_id
        if (
            grant is None
            or grant.revoked_at
            or (grant.expires_at and grant.expires_at <= datetime.utcnow())
        ):
            raise ConnectionError(
                "CONNECTOR_OAUTH_CONSENT_REQUIRED" if user_id else "CONNECTOR_GRANT_REQUIRED", 403
            )
        refs = {key: ref for key, ref in grant.token_refs.items() if key != "refresh_token"}
    return refs, acting_user, grant, delegation


def authorization_snapshot(
    db,
    connection,
    *,
    user_id=None,
    system_id=None,
    system_version_id=None,
    delegation_id=None,
    run_id=None,
):
    """Check revocation using metadata only; neither decrypt nor emit resolve audit."""
    from app.models.secret import SecretVersion
    from app.services.secrets.registry import _find

    refs, acting_user, grant, delegation = _credential_references(
        db,
        connection,
        user_id=user_id,
        system_id=system_id,
        system_version_id=system_version_id,
        delegation_id=delegation_id,
        run_id=run_id,
    )
    consumer = registry.SecretConsumer(
        kind="connector",
        id=connection.id,
        workspace_id=connection.workspace_id,
        user_id=acting_user,
        system_id=system_id,
        run_id=run_id,
    )
    secrets = []
    for key, ref in sorted(refs.items()):
        parsed = registry.parse_ref(ref)
        secret = _find(db, parsed, consumer)
        db.refresh(secret)
        if secret.disabled_at or (secret.expires_at and secret.expires_at <= datetime.utcnow()):
            raise ConnectionError("CONNECTOR_SECRET_UNAVAILABLE", 403)
        number = parsed.version or secret.current_version
        version = (
            db.query(SecretVersion)
            .filter_by(secret_id=secret.id, version=number)
            .populate_existing()
            .one_or_none()
        )
        if version is None or version.destroyed_at:
            raise ConnectionError("CONNECTOR_SECRET_UNAVAILABLE", 403)
        secrets.append(
            (
                key,
                ref,
                secret.id,
                number,
                secret.current_version,
                secret.rotated_at,
                secret.expires_at,
                version.id,
                version.created_at,
            )
        )
    return (
        connection.revision,
        connection.profile_version,
        connection.updated_at,
        tuple(secrets),
        (grant.id, grant.granted_at, grant.expires_at, tuple(grant.scopes or []))
        if grant
        else None,
        (delegation.id, delegation.approved_at, delegation.approved_by, delegation.expires_at)
        if delegation
        else None,
    )


def resolve_credentials(
    db: Session,
    connection: ConnectorConnection,
    *,
    user_id: str | None = None,
    system_id: str | None = None,
    system_version_id: str | None = None,
    delegation_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, registry.SecretValue]:
    refs, acting_user, _, _ = _credential_references(
        db,
        connection,
        user_id=user_id,
        system_id=system_id,
        system_version_id=system_version_id,
        delegation_id=delegation_id,
        run_id=run_id,
    )
    return {
        key: registry.resolve(
            db,
            ref,
            consumer=registry.SecretConsumer(
                kind="connector",
                id=connection.id,
                workspace_id=connection.workspace_id,
                user_id=acting_user,
                system_id=system_id,
                run_id=run_id,
            ),
        )
        for key, ref in refs.items()
    }
