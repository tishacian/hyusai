"""No OAuth cross-identity use, no secret output, and no unapproved tool/network calls."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from app.models.connector_oauth_state import ConnectorOAuthState
from app.schemas.connection import ConnectionCreate
from app.services.connectors import connections, oauth
from app.services.connectors.adapters import tools
from app.services.connectors.adapters.sql import AdapterError
from app.services.connectors.tool_contracts import compile_openapi
from app.tests.services.test_connection_registry import client
from app.tests.services.test_connection_registry import setup as connection_setup

setup = connection_setup


@pytest.fixture()
def tool_connection(db_session, setup, monkeypatch):
    monkeypatch.setattr(oauth.settings, "app_public_url", "https://agentium.example.test")
    monkeypatch.setattr(oauth, "destination_for_url", lambda *a, **k: None)
    row = connections.create_connection(
        db_session,
        workspace_id=setup[0].id,
        actor=setup[2][0].id,
        data=ConnectionCreate(
            name="Personal tools",
            profile_key="mcp",
            values={
                "base_url": "https://tools.example.test/mcp",
                "allowed_origins": ["https://tools.example.test", "https://identity.example.test"],
                "auth_mode": "oauth_user",
                "client_id": "agentium-client",
                "authorization_endpoint": "https://identity.example.test/authorize",
                "token_endpoint": "https://identity.example.test/token",
                "scopes": ["read"],
                "tool_allowlist": ["lookup"],
            },
        ),
    )
    db_session.commit()
    return row


def start(db, setup, connection):
    result = oauth.start(db, connection, user_id=setup[2][1].id)
    db.commit()
    return parse_qs(urlsplit(result["authorization_url"]).query)


def success_body():
    return {
        "access_token": "personal-access-secret",
        "refresh_token": "personal-refresh-secret",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "read",
    }


def complete(db, setup, connection, monkeypatch):
    query = start(db, setup, connection)
    monkeypatch.setattr(oauth, "_call", lambda *args, **kwargs: success_body())
    result = oauth.callback(
        db, connection, user_id=setup[2][1].id, state=query["state"][0], code="one-code"
    )
    db.commit()
    return result, query


def test_pkce_bound_to_identity_workspace_connection_and_one_use(
    db_session, setup, tool_connection, monkeypatch
):
    query = start(db_session, setup, tool_connection)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://agentium.example.test/connectors/connections"]
    sent = []

    def provider(config, endpoint, *, payload, **kwargs):
        sent.append(payload)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(payload["code_verifier"].encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert challenge == query["code_challenge"][0]
        return success_body()

    monkeypatch.setattr(oauth, "_call", provider)
    for user in (setup[2][0], setup[2][2]):
        with pytest.raises(connections.ConnectionError, match="STATE_INVALID"):
            oauth.callback(
                db_session, tool_connection, user_id=user.id, state=query["state"][0], code="code"
            )
    assert sent == []
    result = oauth.callback(
        db_session, tool_connection, user_id=setup[2][1].id, state=query["state"][0], code="code"
    )
    db_session.commit()
    assert "personal-" not in json.dumps(result, default=str)
    assert (
        connections.resolve_credentials(db_session, tool_connection, user_id=setup[2][1].id)[
            "access_token"
        ].reveal()
        == "personal-access-secret"
    )
    assert "refresh_token" not in connections.resolve_credentials(
        db_session, tool_connection, user_id=setup[2][1].id
    )
    with pytest.raises(connections.ConnectionError, match="STATE_INVALID"):
        oauth.callback(
            db_session,
            tool_connection,
            user_id=setup[2][1].id,
            state=query["state"][0],
            code="code",
        )
    assert len(sent) == 1
    state = db_session.query(ConnectorOAuthState).one()
    assert state.consumed_at and state.state_sha256 != query["state"][0]


@pytest.mark.parametrize("change", ["expiry", "connection_revision"])
def test_stale_oauth_state_never_contacts_provider(
    db_session, setup, tool_connection, monkeypatch, change
):
    query = start(db_session, setup, tool_connection)
    if change == "expiry":
        db_session.query(ConnectorOAuthState).one().expires_at = datetime.now(UTC).replace(
            tzinfo=None
        ) - timedelta(seconds=1)
    else:
        tool_connection.revision += 1
    db_session.commit()
    monkeypatch.setattr(oauth, "_call", lambda *args, **kwargs: pytest.fail("provider contacted"))
    with pytest.raises(connections.ConnectionError, match="STATE_INVALID"):
        oauth.callback(
            db_session,
            tool_connection,
            user_id=setup[2][1].id,
            state=query["state"][0],
            code="code",
        )


def test_oauth_failure_consumes_state_and_rejects_scope_escalation(
    db_session, setup, tool_connection, monkeypatch
):
    query = start(db_session, setup, tool_connection)
    monkeypatch.setattr(oauth, "_call", lambda *a, **k: success_body() | {"scope": "read write"})
    with pytest.raises(connections.ConnectionError, match="SCOPE_ESCALATION"):
        oauth.callback(
            db_session,
            tool_connection,
            user_id=setup[2][1].id,
            state=query["state"][0],
            code="code",
        )
    db_session.rollback()
    assert db_session.query(ConnectorOAuthState).one().consumed_at
    with pytest.raises(connections.ConnectionError):
        connections.resolve_credentials(db_session, tool_connection, user_id=setup[2][1].id)


def test_refresh_and_revocation_never_share_tokens_with_admin(
    db_session, setup, tool_connection, monkeypatch
):
    complete(db_session, setup, tool_connection, monkeypatch)
    with pytest.raises(connections.ConnectionError, match="CONSENT_REQUIRED"):
        oauth.refresh(db_session, tool_connection, user_id=setup[2][0].id)
    monkeypatch.setattr(
        oauth,
        "_call",
        lambda *a, **k: (
            success_body() | {"access_token": "rotated-access", "refresh_token": "rotated-refresh"}
        ),
    )
    result = oauth.refresh(db_session, tool_connection, user_id=setup[2][1].id)
    db_session.commit()
    assert "rotated" not in json.dumps(result, default=str)
    assert (
        connections.resolve_credentials(db_session, tool_connection, user_id=setup[2][1].id)[
            "access_token"
        ].reveal()
        == "rotated-access"
    )
    response = client(db_session, setup).delete(
        f"/connections/{tool_connection.id}/grants/{result['grant_id']}"
    )
    assert response.status_code == 200
    with pytest.raises(connections.ConnectionError):
        connections.resolve_credentials(db_session, tool_connection, user_id=setup[2][1].id)


def test_dcr_admin_only_redirect_fixed_client_secret_write_only(
    db_session, setup, tool_connection, monkeypatch
):
    tool_connection.values = {
        **tool_connection.values,
        "client_id": "",
        "registration_endpoint": "https://identity.example.test/register",
    }
    db_session.commit()
    sent = []

    def provider(config, endpoint, **kwargs):
        sent.append(kwargs["payload"])
        return {
            "client_id": "new-client",
            "client_secret": "dcr-secret",
            "token_endpoint_auth_method": "client_secret_post",
        }

    monkeypatch.setattr(oauth, "_call", provider)
    path = f"/connections/{tool_connection.id}/oauth/register-client"
    assert client(db_session, setup, 1).post(path).status_code == 403
    response = client(db_session, setup).post(path)
    assert response.status_code == 200, response.text
    assert sent[0]["redirect_uris"] == ["https://agentium.example.test/connectors/connections"]
    assert "dcr-secret" not in response.text
    assert tool_connection.secret_refs["client_secret"].startswith("secret://workspace/")


def spec():
    return {
        "openapi": "3.0.3",
        "servers": [{"url": "https://api.example.test"}],
        "paths": {
            "/items/{id}": {
                "get": {
                    "operationId": "getItem",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["name"],
                                        "properties": {"name": {"type": "string"}},
                                    }
                                }
                            }
                        }
                    },
                }
            }
        },
    }


def config():
    return {
        "base_url": "https://api.example.test",
        "allowed_origins": ["https://api.example.test"],
        "auth_mode": "none",
        "tool_allowlist": ["getItem"],
        "openapi_spec": spec(),
    }


@pytest.mark.parametrize(
    "reference", ["https://evil.test/schema", "file:///etc/passwd", "#/missing"]
)
def test_openapi_refs_never_fetch_remote_or_missing_documents(reference):
    document = spec()
    document["components"] = {"schemas": {"x": {"$ref": reference}}}
    with pytest.raises(connections.ConnectionError):
        compile_openapi(document, config())


def test_openapi_ref_bomb_and_cross_origin_server_refused():
    document = spec()
    document["servers"] = [{"url": "https://evil.example.test"}]
    with pytest.raises(connections.ConnectionError, match="ORIGIN_DENIED"):
        compile_openapi(document, config())
    document = spec()
    document["components"] = {"schemas": {"x": {"$ref": "#/components/schemas/x"}}}
    with pytest.raises(connections.ConnectionError, match="RECURSIVE_REF"):
        compile_openapi(document, config())


def execute(operation, cfg, params=None):
    return tools.execute(
        operation,
        cfg,
        {},
        params or {},
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        None,
        dialect="openapi",
        access="read",
        limits={},
    )


def test_openapi_validates_input_output_and_seals_mutations(monkeypatch):
    sent = []

    def request(method, url, **kwargs):
        sent.append((method, url))
        return {}, {"name": "Item"}

    monkeypatch.setattr(tools, "json_request", request)
    cfg = config()
    assert execute("preview", cfg, {"operation_id": "getItem", "arguments": {"id": 2}})[
        "result"
    ] == {"name": "Item"}
    assert sent == [("GET", "https://api.example.test/items/2")]
    with pytest.raises(AdapterError):
        execute("preview", cfg, {"operation_id": "getItem", "arguments": {"id": "not-an-integer"}})
    with pytest.raises(AdapterError):
        execute("preview", cfg, {"operation_id": "unapproved", "arguments": {}})
    cfg["openapi_spec"]["paths"]["/items/{id}"]["post"] = cfg["openapi_spec"]["paths"][
        "/items/{id}"
    ].pop("get")
    with pytest.raises(AdapterError, match="WRITE_SEALED"):
        execute("preview", cfg, {"operation_id": "getItem", "arguments": {"id": 2}})
    assert len(sent) == 1


def test_mcp_list_filters_and_checks_read_hint_schema_then_calls(monkeypatch):
    cfg = config() | {
        "base_url": "https://api.example.test/mcp",
        "tool_allowlist": ["lookup", "change"],
    }
    calls = []

    def request(method, url, **kwargs):
        payload = json.loads(kwargs["content"])
        calls.append(payload["method"])
        if payload["method"] == "notifications/initialized":
            return {}, b""
        result = {"protocolVersion": "2024-11-05"}
        if payload["method"] == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "lookup",
                        "inputSchema": {
                            "type": "object",
                            "required": ["id"],
                            "properties": {"id": {"type": "integer"}},
                        },
                        "annotations": {"readOnlyHint": True},
                    },
                    {"name": "change", "inputSchema": {}, "annotations": {}},
                    {"name": "not-allowed", "inputSchema": {}},
                ]
            }
        if payload["method"] == "tools/call":
            result = {"content": [{"type": "text", "text": "record"}]}
        return {"mcp-session-id": "session"}, json.dumps(
            {"jsonrpc": "2.0", "id": payload["id"], "result": result}
        ).encode()

    monkeypatch.setattr(tools, "request", request)
    kwargs = dict(
        deadline_at=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        output_dir=None,
        dialect="mcp",
        access="read",
        limits={},
    )
    result = tools.execute("catalog", cfg, {}, {}, **kwargs)
    assert [t["id"] for t in result["tools"]] == ["lookup", "change"]
    with pytest.raises(AdapterError, match="WRITE_SEALED"):
        tools.execute("preview", cfg, {}, {"operation_id": "change", "arguments": {}}, **kwargs)
    assert "tools/call" not in calls
    result = tools.execute(
        "preview", cfg, {}, {"operation_id": "lookup", "arguments": {"id": 1}}, **kwargs
    )
    assert result["tool"] == "lookup" and calls[-1] == "tools/call"


@pytest.mark.parametrize(
    "paths",
    [
        [],
        None,
        {"/x": {"get": {"responses": []}}},
        {"/x": {"get": {"parameters": None}}},
        {"/x": {"get": {"parameters": [{"in": "query", "name": "q", "schema": False}]}}},
        {"/x": {"get": {"responses": {"200": {"content": []}}}}},
    ],
)
def test_malformed_openapi_shapes_fail_closed_without_echo(paths):
    with pytest.raises(connections.ConnectionError, match="CONNECTOR_OPENAPI_"):
        compile_openapi(
            {"openapi": "3.0.3", "paths": paths},
            {"base_url": "https://api.example", "allowed_origins": ["https://api.example"]},
        )


def write_config():
    cfg = config()
    cfg["tool_allowlist"] = ["createItem"]
    cfg["write_tools"] = ["createItem"]
    cfg["openapi_spec"]["paths"] = {
        "/items": {
            "post": {
                "operationId": "createItem",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["name"],
                                "properties": {"name": {"type": "string"}},
                            }
                        }
                    },
                },
                "responses": {"204": {"description": "created"}},
            }
        }
    }
    return cfg


def write_execution(cfg, dialect="openapi", arguments=None):
    from types import SimpleNamespace

    from app.services.connectors.tool_contracts import prepare_tool_contract

    params = {"operation_id": "createItem", "arguments": arguments or {"body": {"name": "Item"}}}
    contract = prepare_tool_contract(SimpleNamespace(profile_key=dialect, values=cfg), **params)
    return params, {
        "operation_id": "approved-write-id",
        "contract_digest": "a" * 64,
        "tool_contract": contract,
    }


def test_openapi_write_uses_exact_approved_body_and_accepts_empty_success(monkeypatch):
    cfg = write_config()
    params, execution = write_execution(cfg)
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, json.loads(kwargs["content"])))
        return {}, b""

    monkeypatch.setattr(tools, "mutation_request", request)
    result = tools.execute(
        "tool_write",
        cfg,
        {},
        params,
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        None,
        dialect="openapi",
        access={"mode": "read_write"},
        limits={},
        execution=execution,
    )
    assert calls == [("POST", "https://api.example.test/items", {"name": "Item"})]
    assert result["applied"] is True and result["operation_id"] == "approved-write-id"
    assert result["outcome_check"] == "unsupported"


@pytest.mark.parametrize(
    "tamper", ["arguments", "definition", "scope", "missing_approval", "read_only"]
)
def test_tool_writes_reject_contract_changes_before_network(monkeypatch, tamper):
    cfg = write_config()
    params, execution = write_execution(cfg)
    access = {"mode": "read_write"}
    if tamper == "arguments":
        params["arguments"] = {"body": {"name": "Other"}}
    if tamper == "definition":
        cfg["openapi_spec"]["paths"]["/items"]["post"]["requestBody"]["required"] = False
    if tamper == "scope":
        cfg["scopes"] = ["write:more"]
    if tamper == "missing_approval":
        execution = None
    if tamper == "read_only":
        access = {"mode": "read"}
    monkeypatch.setattr(
        tools, "mutation_request", lambda *a, **kw: pytest.fail("unapproved mutation")
    )
    with pytest.raises(AdapterError):
        tools.execute(
            "tool_write",
            cfg,
            {},
            params,
            (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            None,
            dialect="openapi",
            access=access,
            limits={},
            execution=execution,
        )


def test_mcp_live_schema_must_match_frozen_contract_before_mutation(monkeypatch):
    frozen = {
        "id": "createItem",
        "write": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "output_schema": {},
    }
    cfg = {
        "base_url": "https://api.example.test/mcp",
        "allowed_origins": ["https://api.example.test"],
        "auth_mode": "none",
        "tool_allowlist": ["createItem"],
        "write_tools": ["createItem"],
        "tool_contracts": {"createItem": frozen},
    }
    params, execution = write_execution(cfg, "mcp", {"name": "Item"})
    calls = []

    def rpc(config, headers, method, params, deadline_at, **kwargs):
        calls.append(method)
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "createItem",
                        "inputSchema": {"type": "object"},
                        "annotations": {"readOnlyHint": False},
                    }
                ]
            }, None
        if method == "tools/call":
            pytest.fail("changed definition was called")
        return {}, None

    monkeypatch.setattr(tools, "_rpc", rpc)
    with pytest.raises(AdapterError, match="TOOL_CONTRACT_CHANGED"):
        tools.execute(
            "tool_write",
            cfg,
            {},
            params,
            (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            None,
            dialect="mcp",
            access={"mode": "read_write"},
            limits={},
            execution=execution,
        )
    assert "tools/list" in calls


def test_catalog_snapshot_cannot_be_fabricated_via_connection_update(
    db_session, setup, tool_connection
):
    from app.schemas.connection import ConnectionUpdate

    with pytest.raises(connections.ConnectionError, match="CATALOG_IMPORT_REQUIRED"):
        connections.update_connection(
            db_session,
            tool_connection,
            actor=setup[2][0].id,
            data=ConnectionUpdate(
                revision=tool_connection.revision,
                values={
                    **tool_connection.values,
                    "tool_contracts": {
                        "lookup": {
                            "id": "lookup",
                            "write": True,
                            "input_schema": {},
                            "output_schema": {},
                        }
                    },
                },
            ),
        )


def test_graph_personal_authorization_requires_own_grant_and_never_client_secret(
    db_session, setup, monkeypatch
):
    monkeypatch.setattr(oauth.settings, "app_public_url", "https://agentium.example.test")
    monkeypatch.setattr(oauth, "destination_for_url", lambda *a, **k: None)
    row = connections.create_connection(
        db_session,
        workspace_id=setup[0].id,
        actor=setup[2][0].id,
        data=ConnectionCreate(
            name="Personal SharePoint",
            profile_key="sharepoint_files",
            values={
                "drive_id": "personal-drive",
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "client_id": "agentium-client",
                "download_hosts": ["company.sharepoint.com"],
                "auth_mode": "oauth_user",
                "authorization_endpoint": "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
                "token_endpoint": "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            },
        ),
    )
    db_session.commit()
    monkeypatch.setattr(oauth, "_call", lambda *a, **k: success_body() | {"scope": "Files.Read"})
    query = start(db_session, setup, row)
    oauth.callback(
        db_session, row, user_id=setup[2][1].id, state=query["state"][0], code="graph-code"
    )
    db_session.commit()
    tokens = connections.resolve_credentials(db_session, row, user_id=setup[2][1].id)
    assert (
        set(tokens) == {"access_token"}
        and tokens["access_token"].reveal() == "personal-access-secret"
    )
    with pytest.raises(connections.ConnectionError, match="CONSENT_REQUIRED"):
        connections.resolve_credentials(db_session, row, user_id=setup[2][0].id)


def test_mcp_catalog_import_requires_success_exact_connection_revision(
    db_session, setup, tool_connection
):
    from app.services import compute_runs

    row = compute_runs.create_run(
        db_session,
        workspace_id=setup[0].id,
        user_id=setup[2][0].id,
        connection_id=tool_connection.id,
        operation="catalog",
    )
    row.status = "succeeded"
    row.output_json = {
        "tools": [
            {"id": "lookup", "write": True, "input_schema": {"type": "object"}, "output_schema": {}}
        ]
    }
    db_session.commit()
    api = client(db_session, setup)
    path = f"/connections/{tool_connection.id}/tools/import"
    assert client(db_session, setup, 1).post(path, json={"run_id": row.id}).status_code == 403
    result = api.post(path, json={"run_id": row.id})
    assert result.status_code == 200, result.text
    assert result.json()["values"]["tool_contracts"]["lookup"]["write"] is True
    assert api.post(path, json={"run_id": row.id}).status_code == 409


@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef"])
def test_dynamic_schema_resolvers_cannot_bypass_guarded_transport(keyword):
    document = spec()
    document["components"] = {"schemas": {"external": {keyword: "https://metadata.invalid/schema"}}}
    with pytest.raises(connections.ConnectionError, match="EXTERNAL_REF"):
        compile_openapi(document, config())
    with pytest.raises(AdapterError, match="TOOL_SCHEMA_INVALID"):
        tools._validate({keyword: "https://metadata.invalid/schema"}, {})


def test_http_async_acceptance_is_not_a_completed_write_receipt(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    @contextmanager
    def pending(*args, **kwargs):
        yield SimpleNamespace(status_code=202)

    monkeypatch.setattr(tools, "response", pending)
    with pytest.raises(AdapterError, match="TOOL_OUTCOME_UNKNOWN"):
        tools.mutation_request(
            "POST",
            "https://api.example.test",
            deadline_at=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            headers={},
            content=b"{}",
            max_bytes=1000,
        )
