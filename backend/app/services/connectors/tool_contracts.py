"""Origin-bound declarative tool contracts. No credentials, network calls or drivers."""

from __future__ import annotations

import hashlib
import json
import re

import httpx

from app.services.connectors.connections import ConnectionError
from app.services.connectors.http_transport import origin
from app.services.connectors.network_policy import ConnectorNetworkError

MAX_SPEC_BYTES = 2 * 1024 * 1024


def allowed_url(config: dict, url: str) -> str:
    try:
        parsed = httpx.URL(url)
        target = origin(parsed)
        declared = config.get("allowed_origins", [])
        if not isinstance(declared, list) or not declared or len(declared) > 30:
            raise ValueError()
        allowed = set()
        for entry in declared:
            item = httpx.URL(entry)
            if item.path not in {"", "/"} or item.query:
                raise ValueError()
            allowed.add(origin(item))
        if target[0] != "https" or target not in allowed:
            raise ValueError()
    except (ValueError, TypeError, httpx.InvalidURL, ConnectorNetworkError):
        raise ConnectionError("CONNECTOR_ORIGIN_DENIED", 403) from None
    return str(parsed)


def validate_tool_config(values: dict) -> None:
    allowed_url(values, values.get("base_url", ""))
    for field in (
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
        "revocation_endpoint",
    ):
        if values.get(field):
            allowed_url(values, values[field])
    for field in ("scopes", "tool_allowlist", "write_tools"):
        value = values.get(field, [])
        if (
            not isinstance(value, list)
            or len(value) > 200
            or any(
                not isinstance(v, str) or not v or len(v) > 200 or any(ord(c) < 32 for c in v)
                for v in value
            )
        ):
            raise ConnectionError("CONNECTOR_TOOL_CONFIG_INVALID")
    snapshots = values.get("tool_contracts", {})
    if not isinstance(snapshots, dict) or len(snapshots) > 1000:
        raise ConnectionError("CONNECTOR_TOOL_CONFIG_INVALID")
    for key, item in snapshots.items():
        if (
            not isinstance(item, dict)
            or item.get("id") != key
            or set(item) != {"id", "input_schema", "output_schema", "write"}
            or not isinstance(item.get("input_schema"), dict)
            or not isinstance(item.get("output_schema"), dict)
            or type(item.get("write")) is not bool
        ):
            raise ConnectionError("CONNECTOR_TOOL_CONFIG_INVALID")
    if set(values.get("write_tools", [])) - set(values.get("tool_allowlist", [])):
        raise ConnectionError("CONNECTOR_TOOL_CONFIG_INVALID")
    if values.get("auth_mode") in {"oauth_user", "oauth_client_credentials"} and not values.get(
        "token_endpoint"
    ):
        raise ConnectionError("CONNECTOR_OAUTH_CONFIG_INVALID")
    if values.get("auth_mode") == "oauth_user" and not values.get("authorization_endpoint"):
        raise ConnectionError("CONNECTOR_OAUTH_CONFIG_INVALID")


def _expand(spec, node, *, ancestors=(), depth=0, budget=None):
    budget = budget if budget is not None else [50000]
    budget[0] -= 1
    if budget[0] < 0:
        raise ConnectionError("CONNECTOR_OPENAPI_TOO_COMPLEX")
    if depth > 30:
        raise ConnectionError("CONNECTOR_OPENAPI_TOO_COMPLEX")
    if isinstance(node, dict):
        if "$dynamicRef" in node or "$recursiveRef" in node:
            # These resolvers can initiate network I/O outside the transport.
            raise ConnectionError("CONNECTOR_OPENAPI_EXTERNAL_REF")
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                raise ConnectionError("CONNECTOR_OPENAPI_EXTERNAL_REF")
            if ref in ancestors:
                raise ConnectionError("CONNECTOR_OPENAPI_RECURSIVE_REF")
            target = spec
            try:
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                raise ConnectionError("CONNECTOR_OPENAPI_INVALID_REF") from None
            return _expand(
                spec, target, ancestors=(*ancestors, ref), depth=depth + 1, budget=budget
            )
        return {
            k: _expand(spec, v, ancestors=ancestors, depth=depth + 1, budget=budget)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_expand(spec, v, ancestors=ancestors, depth=depth + 1, budget=budget) for v in node]
    return node


def compile_openapi(spec: dict, config: dict) -> dict:
    """Compile an autonomous OpenAPI3 spec into explicit, read-only tool contracts.

    Writes remain sealed in this phase; importing an operation cannot authorize it.
    No server, header or security definition from the spec supplies credentials.
    """
    try:
        encoded = json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise ConnectionError("CONNECTOR_OPENAPI_INVALID") from None
    if len(encoded.encode()) > MAX_SPEC_BYTES:
        raise ConnectionError("CONNECTOR_OPENAPI_TOO_LARGE")
    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3."):
        raise ConnectionError("CONNECTOR_OPENAPI_VERSION_UNSUPPORTED")
    expanded = _expand(spec, spec)
    operations = []
    seen = set()
    paths = expanded.get("paths", {})
    if not isinstance(paths, dict):
        raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
    for path, item in paths.items():
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or "?" in path
            or "#" in path
            or not isinstance(item, dict)
        ):
            raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
        for method, operation in item.items():
            if not isinstance(method, str):
                raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            if not isinstance(operation, dict):
                raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
            servers = operation.get("servers", item.get("servers", expanded.get("servers")))
            servers = servers or [{"url": config["base_url"]}]
            if not isinstance(servers, list) or not servers:
                raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
            for server in servers:
                if (
                    not isinstance(server, dict)
                    or not isinstance(server.get("url"), str)
                    or "{" in server["url"]
                ):
                    raise ConnectionError("CONNECTOR_OPENAPI_SERVER_UNSUPPORTED")
                allowed_url(config, server["url"])
            key = operation.get("operationId") or f"{method.lower()}:{path}"
            if not isinstance(key, str) or key in seen or len(key) > 200:
                raise ConnectionError("CONNECTOR_OPENAPI_OPERATION_INVALID")
            seen.add(key)
            properties, required, parameters = {}, [], []
            shared = item.get("parameters", [])
            specific = operation.get("parameters", [])
            if not isinstance(shared, list) or not isinstance(specific, list):
                raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
            for parameter in [*shared, *specific]:
                if not isinstance(parameter, dict) or parameter.get("in") not in {"path", "query"}:
                    raise ConnectionError("CONNECTOR_OPENAPI_PARAMETER_UNSUPPORTED")
                name = parameter.get("name")
                if not isinstance(name, str) or not name or name in properties or len(name) > 120:
                    raise ConnectionError("CONNECTOR_OPENAPI_PARAMETER_UNSUPPORTED")
                schema = parameter.get("schema", {"type": "string"})
                if not isinstance(schema, dict) or schema.get("type") not in {
                    "string",
                    "number",
                    "integer",
                    "boolean",
                }:
                    raise ConnectionError("CONNECTOR_OPENAPI_PARAMETER_UNSUPPORTED")
                properties[name] = schema
                if parameter.get("required") or parameter["in"] == "path":
                    required.append(name)
                parameters.append({"name": name, "in": parameter["in"]})
            request_body = operation.get("requestBody")
            if request_body is not None:
                if not isinstance(request_body, dict) or not isinstance(
                    request_body.get("content"), dict
                ):
                    raise ConnectionError("CONNECTOR_OPENAPI_BODY_UNSUPPORTED")
                body = request_body["content"].get("application/json")
                if (
                    not isinstance(body, dict)
                    or not isinstance(body.get("schema"), dict)
                    or "body" in properties
                ):
                    raise ConnectionError("CONNECTOR_OPENAPI_BODY_UNSUPPORTED")
                properties["body"] = body["schema"]
                parameters.append({"name": "body", "in": "body"})
                if request_body.get("required"):
                    required.append("body")
            placeholders = set(re.findall(r"\{([^{}]+)\}", path))
            if placeholders != {p["name"] for p in parameters if p["in"] == "path"}:
                raise ConnectionError("CONNECTOR_OPENAPI_PARAMETER_UNSUPPORTED")
            outputs = []
            responses = operation.get("responses", {})
            if not isinstance(responses, dict):
                raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
            for status, response in responses.items():
                if str(status).startswith("2") and isinstance(response, dict):
                    content = response.get("content", {})
                    if not isinstance(content, dict):
                        raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
                    body = content.get("application/json", {})
                    if not isinstance(body, dict):
                        raise ConnectionError("CONNECTOR_OPENAPI_INVALID")
                    if isinstance(body.get("schema"), dict):
                        outputs.append(body["schema"])
            operations.append(
                {
                    "id": key,
                    "method": method.upper(),
                    "path": path,
                    "base_url": servers[0]["url"].rstrip("/"),
                    "parameters": parameters,
                    "input_schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                    "output_schema": {"anyOf": outputs} if outputs else {},
                    "write": method.lower() != "get",
                }
            )
            if len(operations) > 1000:
                raise ConnectionError("CONNECTOR_OPENAPI_TOO_COMPLEX")
    # The expanded contract is bounded too: refs must not amplify a small input.
    if len(json.dumps(operations).encode()) > MAX_SPEC_BYTES:
        raise ConnectionError("CONNECTOR_OPENAPI_TOO_LARGE")
    return {"digest": hashlib.sha256(encoded.encode()).hexdigest(), "operations": operations}


def tool_digest(value):
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ConnectionError("CONNECTOR_TOOL_SCHEMA_INVALID") from None
    if len(payload) > MAX_SPEC_BYTES:
        raise ConnectionError("CONNECTOR_TOOL_SCHEMA_INVALID")
    return hashlib.sha256(payload).hexdigest()


def prepare_tool_contract(connection, operation_id, arguments):
    """Public, deterministic approval contract. No network or credential access.

    MCP snapshots must be imported from a completed catalogue run; the child
    revalidates them against the live tool before sending a mutation.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError, ValidationError

    config = connection.values
    validate_tool_config(config)
    if operation_id not in config.get("tool_allowlist", []) or operation_id not in config.get(
        "write_tools", []
    ):
        raise ConnectionError("CONNECTOR_TOOL_NOT_ALLOWED", 403)
    if connection.profile_key == "openapi":
        spec = compile_openapi(config.get("openapi_spec"), config)
        selected = next((t for t in spec["operations"] if t["id"] == operation_id), None)
        source_digest = spec["digest"]
    elif connection.profile_key == "mcp":
        selected = config.get("tool_contracts", {}).get(operation_id)
        source_digest = tool_digest(selected)
    else:
        raise ConnectionError("CONNECTOR_OPERATION_UNSUPPORTED")
    if (
        not isinstance(selected, dict)
        or selected.get("id") != operation_id
        or selected.get("write") is not True
    ):
        raise ConnectionError("CONNECTOR_TOOL_WRITE_CONTRACT_REQUIRED", 409)
    if not isinstance(arguments, dict):
        raise ConnectionError("CONNECTOR_TOOL_SCHEMA_INVALID")
    try:
        schema = _expand(selected["input_schema"], selected["input_schema"])
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(arguments)
        output_schema = selected.get("output_schema", {})
        Draft202012Validator.check_schema(_expand(output_schema, output_schema))
    except (KeyError, TypeError, SchemaError, ValidationError):
        raise ConnectionError("CONNECTOR_TOOL_SCHEMA_INVALID") from None
    return {
        "protocol": connection.profile_key,
        "endpoint": config["base_url"],
        "operation_id": operation_id,
        "definition": selected,
        "source_digest": source_digest,
        "arguments": arguments,
        "arguments_digest": tool_digest(arguments),
        "scopes": sorted(config.get("scopes", [])),
        "outcome_check": "unsupported",
    }
