"""Personal OAuth authorization with one-use state, S256 PKCE and scoped secrets.

Only authorization metadata is returned. OAuth HTTP uses the common pinned TLS
transport; connector data/tool traffic is executed by the isolated runner.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import update

from app.core.config import settings
from app.models.connector_connection import ConnectorGrant
from app.models.connector_oauth_state import ConnectorOAuthState
from app.models.secret import Secret
from app.services import secrets as registry
from app.services.connectors import connections
from app.services.connectors.adapters.http import json_request
from app.services.connectors.adapters.sql import AdapterError
from app.services.connectors.http_transport import destination_for_url
from app.services.connectors.network_policy import ConnectorNetworkError
from app.services.connectors.tool_contracts import allowed_url
from app.services.secrets.registry import user_owner_key


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _deadline():
    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


def _call(config, endpoint, *, payload, json_body=False):
    url = allowed_url(config, config.get(endpoint, ""))
    try:
        _, body = json_request(
            "POST",
            url,
            deadline_at=_deadline(),
            max_bytes=65536,
            headers={
                "Content-Type": "application/json"
                if json_body
                else "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            content=json.dumps(payload).encode() if json_body else urlencode(payload).encode(),
        )
    except (AdapterError, ConnectorNetworkError) as exc:
        raise connections.ConnectionError(exc.code, 502) from None
    if not isinstance(body, dict) or body.get("error"):
        raise connections.ConnectionError("CONNECTOR_OAUTH_PROVIDER_REJECTED", 400)
    return body


def callback_uri() -> str:
    value = str(settings.app_public_url or "").rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise connections.ConnectionError("CONNECTOR_OAUTH_REDIRECT_NOT_CONFIGURED", 503)
    return value + "/connectors/connections"


def start(db, connection, *, user_id: str):
    user_owner_key(db, connection.workspace_id, user_id)
    config = connection.values
    if config.get("auth_mode") != "oauth_user" or not config.get("client_id"):
        raise connections.ConnectionError("CONNECTOR_OAUTH_CONFIG_INVALID", 409)
    authorization = allowed_url(config, config.get("authorization_endpoint", ""))
    try:
        destination_for_url(authorization, require_https=True)
    except ConnectorNetworkError as exc:
        raise connections.ConnectionError(exc.code, exc.status_code) from None
    # Bound outstanding requests per identity; expired rows are inert and auditable.
    count = (
        db.query(ConnectorOAuthState)
        .filter_by(connection_id=connection.id, owner_user_id=user_id, consumed_at=None)
        .filter(ConnectorOAuthState.expires_at > _now())
        .count()
    )
    if count >= 5:
        raise connections.ConnectionError("CONNECTOR_OAUTH_TOO_MANY_REQUESTS", 429)
    verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    row_id = str(uuid4())
    expires = _now() + timedelta(minutes=10)
    meta = registry.create(
        db,
        scope="user",
        workspace_id=connection.workspace_id,
        user_id=user_id,
        actor=user_id,
        name=f"oauth-state-{row_id}",
        value=verifier,
        kind="token",
        expires_at=expires,
        commit=False,
    )
    redirect_uri = callback_uri()
    db.add(
        ConnectorOAuthState(
            id=row_id,
            state_sha256=hashlib.sha256(state.encode()).hexdigest(),
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            connection_revision=connection.revision,
            owner_user_id=user_id,
            verifier_ref=meta["ref"],
            redirect_uri=redirect_uri,
            scopes=config.get("scopes", []),
            expires_at=expires,
        )
    )
    parsed = urlsplit(authorization)
    query = dict(parse_qsl(parsed.query))
    query.update(
        response_type="code",
        client_id=config["client_id"],
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
        scope=" ".join(config.get("scopes", [])),
    )
    connections.audit(db, connection, "connection.oauth.started", user_id, request_id=row_id)
    db.flush()
    return {
        "authorization_url": urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")
        ),
        "expires_at": expires,
    }


def _client_auth(db, connection, payload, *, user_id):
    payload["client_id"] = connection.values.get("client_id", "")
    if not payload["client_id"]:
        raise connections.ConnectionError("CONNECTOR_OAUTH_CONFIG_INVALID", 409)
    ref = (connection.secret_refs or {}).get("client_secret")
    if ref:
        payload["client_secret"] = registry.resolve(
            db,
            ref,
            consumer=registry.SecretConsumer(
                "oauth_client", connection.id, workspace_id=connection.workspace_id, user_id=user_id
            ),
        ).reveal()


def _validated_tokens(body, requested_scopes):
    access = body.get("access_token")
    if (
        not isinstance(access, str)
        or not access
        or len(access) > 16384
        or str(body.get("token_type", "")).lower() != "bearer"
    ):
        raise connections.ConnectionError("CONNECTOR_OAUTH_TOKEN_INVALID", 502)
    scopes = body.get("scope")
    if scopes is None:
        scopes = list(requested_scopes)
    elif isinstance(scopes, str):
        scopes = scopes.split()
    else:
        raise connections.ConnectionError("CONNECTOR_OAUTH_TOKEN_INVALID", 502)
    if set(scopes) - set(requested_scopes):
        raise connections.ConnectionError("CONNECTOR_OAUTH_SCOPE_ESCALATION", 502)
    seconds = body.get("expires_in")
    if seconds is not None and (type(seconds) is not int or not 0 < seconds <= 31536000):
        raise connections.ConnectionError("CONNECTOR_OAUTH_TOKEN_INVALID", 502)
    refresh = body.get("refresh_token")
    if refresh is not None and (
        not isinstance(refresh, str) or not refresh or len(refresh) > 16384
    ):
        raise connections.ConnectionError("CONNECTOR_OAUTH_TOKEN_INVALID", 502)
    return access, refresh, scopes, _now() + timedelta(seconds=seconds) if seconds else None


def _secret_by_ref(db, workspace_id, user_id, ref):
    parsed = registry.parse_ref(ref)
    return (
        db.query(Secret)
        .filter_by(
            scope="user", owner_key=user_owner_key(db, workspace_id, user_id), name=parsed.name
        )
        .one()
    )


def callback(db, connection, *, user_id: str, state: str, code: str):
    if (
        not isinstance(state, str)
        or not 20 <= len(state) <= 200
        or not isinstance(code, str)
        or not code
        or len(code) > 4096
    ):
        raise connections.ConnectionError("CONNECTOR_OAUTH_CALLBACK_INVALID")
    user_owner_key(db, connection.workspace_id, user_id)
    row = (
        db.query(ConnectorOAuthState)
        .filter_by(
            state_sha256=hashlib.sha256(state.encode()).hexdigest(),
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            owner_user_id=user_id,
        )
        .one_or_none()
    )
    if (
        row is None
        or row.connection_revision != connection.revision
        or row.expires_at <= _now()
        or row.consumed_at
    ):
        raise connections.ConnectionError("CONNECTOR_OAUTH_STATE_INVALID", 409)
    # Consume before exchange. A timeout cannot make a code or state replayable.
    changed = db.execute(
        update(ConnectorOAuthState)
        .where(
            ConnectorOAuthState.id == row.id,
            ConnectorOAuthState.consumed_at.is_(None),
            ConnectorOAuthState.expires_at > _now(),
        )
        .values(consumed_at=_now())
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise connections.ConnectionError("CONNECTOR_OAUTH_STATE_INVALID", 409)
    db.commit()
    verifier = registry.resolve(
        db,
        row.verifier_ref,
        consumer=registry.SecretConsumer(
            "oauth_callback", connection.id, workspace_id=connection.workspace_id, user_id=user_id
        ),
    ).reveal()
    verifier_row = _secret_by_ref(db, connection.workspace_id, user_id, row.verifier_ref)
    registry.destroy(db, verifier_row.id, actor=user_id)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": row.redirect_uri,
    }
    _client_auth(db, connection, payload, user_id=user_id)
    body = _call(connection.values, "token_endpoint", payload=payload)
    access, refresh, scopes, expires = _validated_tokens(body, row.scopes)
    # Recheck identity/revision after the external exchange, before saving tokens.
    db.refresh(connection)
    if connection.disabled_at or connection.revision != row.connection_revision:
        raise connections.ConnectionError("CONNECTOR_OAUTH_STATE_INVALID", 409)
    user_owner_key(db, connection.workspace_id, user_id)
    old = (
        db.query(ConnectorGrant)
        .filter_by(connection_id=connection.id, owner_user_id=user_id)
        .one_or_none()
    )
    if old and old.revoked_at is None:
        connections.revoke_grant(db, old, actor=user_id)
    token_refs = {}
    nonce = uuid4().hex
    for key, value in (("access_token", access), ("refresh_token", refresh)):
        if value:
            token_refs[key] = registry.create(
                db,
                scope="user",
                workspace_id=connection.workspace_id,
                user_id=user_id,
                actor=user_id,
                name=f"conn-{connection.id}-{nonce}-{key.replace('_', '-')}",
                value=value,
                kind="token",
                expires_at=expires if key == "access_token" else None,
                commit=False,
            )["ref"]
    grant = connections.create_grant(
        db,
        connection,
        owner_user_id=user_id,
        token_refs=token_refs,
        scopes=scopes,
        expires_at=expires,
    )
    return {"grant_id": grant.id, "scopes": grant.scopes, "expires_at": grant.expires_at}


def register_client(db, connection, *, actor: str):
    if connection.values.get("client_id"):
        raise connections.ConnectionError("CONNECTOR_OAUTH_CLIENT_EXISTS", 409)
    body = _call(
        connection.values,
        "registration_endpoint",
        payload={
            "client_name": "Agentium",
            "redirect_uris": [callback_uri()],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        json_body=True,
    )
    client_id = body.get("client_id")
    if (
        not isinstance(client_id, str)
        or not client_id
        or len(client_id) > 2048
        or body.get("token_endpoint_auth_method", "none") not in {"none", "client_secret_post"}
    ):
        raise connections.ConnectionError("CONNECTOR_OAUTH_CLIENT_INVALID", 502)
    if body.get("redirect_uris", [callback_uri()]) != [callback_uri()]:
        raise connections.ConnectionError("CONNECTOR_OAUTH_CLIENT_INVALID", 502)
    refs = dict(connection.secret_refs)
    if body.get("client_secret"):
        refs["client_secret"] = registry.create(
            db,
            scope="workspace",
            workspace_id=connection.workspace_id,
            actor=actor,
            name=f"conn-{connection.id}-oauth-client",
            value=body["client_secret"],
            kind="oauth_client",
            commit=False,
        )["ref"]
    from app.schemas.connection import ConnectionUpdate

    connections.update_connection(
        db,
        connection,
        actor=actor,
        data=ConnectionUpdate(
            revision=connection.revision,
            values={**connection.values, "client_id": client_id},
            secret_refs=refs,
        ),
    )
    connections.audit(db, connection, "connection.oauth.client_registered", actor)
    return {"client_id": client_id}


def refresh(db, connection, *, user_id: str):
    user_owner_key(db, connection.workspace_id, user_id)
    grant = (
        db.query(ConnectorGrant)
        .filter_by(
            workspace_id=connection.workspace_id, connection_id=connection.id, owner_user_id=user_id
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if grant is None or grant.revoked_at or not grant.token_refs.get("refresh_token"):
        raise connections.ConnectionError("CONNECTOR_OAUTH_CONSENT_REQUIRED", 403)
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": registry.resolve(
            db,
            grant.token_refs["refresh_token"],
            consumer=registry.SecretConsumer(
                "oauth_refresh",
                connection.id,
                workspace_id=connection.workspace_id,
                user_id=user_id,
            ),
        ).reveal(),
    }
    _client_auth(db, connection, payload, user_id=user_id)
    body = _call(connection.values, "token_endpoint", payload=payload)
    access, replacement, scopes, expires = _validated_tokens(body, grant.scopes)
    for key, value in (("access_token", access), ("refresh_token", replacement)):
        if value:
            secret = _secret_by_ref(db, connection.workspace_id, user_id, grant.token_refs[key])
            registry.rotate(
                db,
                secret.id,
                value=value,
                actor=user_id,
                expires_at=expires if key == "access_token" else None,
                commit=False,
            )
    grant.scopes, grant.expires_at = scopes, expires
    connections.audit(db, connection, "connection.oauth.refreshed", user_id, grant_id=grant.id)
    db.flush()
    return {"grant_id": grant.id, "scopes": grant.scopes, "expires_at": grant.expires_at}


def revoke_provider_tokens(db, connection, grant, *, actor):
    """Best-effort provider revocation; local destruction always proceeds.

    This trusted path is used only after the caller has permission to revoke,
    never to give the caller access to the owner's token.
    """
    if not connection.values.get("revocation_endpoint"):
        return
    from app.services.connectors.adapters.http import request

    for key in ("refresh_token", "access_token"):
        ref = (grant.token_refs or {}).get(key)
        if not ref:
            continue
        outcome = "attempted"
        try:
            token = registry.resolve(
                db,
                ref,
                consumer=registry.SecretConsumer(
                    "oauth_revoke",
                    connection.id,
                    workspace_id=connection.workspace_id,
                    user_id=grant.owner_user_id,
                ),
            ).reveal()
            payload = {"token": token, "token_type_hint": key}
            _client_auth(db, connection, payload, user_id=grant.owner_user_id)
            request(
                "POST",
                allowed_url(connection.values, connection.values["revocation_endpoint"]),
                deadline_at=_deadline(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=urlencode(payload).encode(),
                max_bytes=65536,
            )
            outcome = "accepted"
        except (
            registry.SecretRegistryError,
            connections.ConnectionError,
            AdapterError,
            ConnectorNetworkError,
        ):
            outcome = "unconfirmed"
        connections.audit(
            db,
            connection,
            "connection.oauth.provider_revocation",
            actor,
            grant_id=grant.id,
            token_kind=key,
            outcome=outcome,
        )
