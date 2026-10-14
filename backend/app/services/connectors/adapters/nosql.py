"""Structured document/search reads and token-range Cassandra scans."""

from __future__ import annotations

import hashlib
import json
import re
import ssl
from urllib.parse import quote

from app.services.connectors.adapters import http
from app.services.connectors.adapters.driver_egress import pinned_python_driver
from app.services.connectors.adapters.object_clients import endpoint
from app.services.connectors.adapters.sql import AdapterError, _identifier, _json_value, _remaining

MONGO_OPS = {
    "$eq",
    "$ne",
    "$gt",
    "$gte",
    "$lt",
    "$lte",
    "$in",
    "$nin",
    "$exists",
    "$and",
    "$or",
    "$not",
}


def validate_search_query(value, depth=0):
    """Only local index predicates; no terms lookup, scripts or joins."""
    if depth > 20 or not isinstance(value, dict) or len(value) != 1:
        raise AdapterError("CONNECTOR_FILTER_INVALID")
    name, body = next(iter(value.items()))
    if name not in {
        "bool",
        "match_all",
        "term",
        "terms",
        "range",
        "exists",
        "match",
        "prefix",
    } or not isinstance(body, dict):
        raise AdapterError("CONNECTOR_FILTER_FORBIDDEN")
    if name == "bool":
        if set(body) - {"must", "filter", "should", "must_not", "minimum_should_match"}:
            raise AdapterError("CONNECTOR_FILTER_FORBIDDEN")
        for key, item in body.items():
            if key == "minimum_should_match":
                if type(item) is not int or not 0 <= item <= 1000:
                    raise AdapterError("CONNECTOR_FILTER_INVALID")
                continue
            clauses = item if isinstance(item, list) else [item]
            if len(clauses) > 1000:
                raise AdapterError("CONNECTOR_FILTER_INVALID")
            for clause in clauses:
                validate_search_query(clause, depth + 1)
    elif name == "match_all":
        if body:
            raise AdapterError("CONNECTOR_FILTER_INVALID")
    elif name == "exists":
        if set(body) != {"field"} or not isinstance(body["field"], str):
            raise AdapterError("CONNECTOR_FILTER_INVALID")
    else:
        if len(body) != 1:
            raise AdapterError("CONNECTOR_FILTER_INVALID")
        field, term = next(iter(body.items()))
        if not isinstance(field, str) or not field or len(field) > 255:
            raise AdapterError("CONNECTOR_FILTER_INVALID")
        if name == "terms":
            if (
                not isinstance(term, list)
                or len(term) > 1000
                or any(isinstance(v, (dict, list)) for v in term)
            ):
                raise AdapterError("CONNECTOR_FILTER_FORBIDDEN")
        elif name == "range":
            if (
                not isinstance(term, dict)
                or set(term) - {"gt", "gte", "lt", "lte", "format", "time_zone"}
                or any(isinstance(v, (dict, list)) for v in term.values())
            ):
                raise AdapterError("CONNECTOR_FILTER_FORBIDDEN")
        elif isinstance(term, (dict, list)):
            raise AdapterError("CONNECTOR_FILTER_FORBIDDEN")
    return value


def validate_filter(value, *, kind, depth=0):
    if depth > 20:
        raise AdapterError("CONNECTOR_FILTER_INVALID")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 255 or "\x00" in key:
                raise AdapterError("CONNECTOR_FILTER_INVALID")
            if kind == "mongo" and key.startswith("$") and key not in MONGO_OPS:
                raise AdapterError("CONNECTOR_FILTER_FORBIDDEN")
            if kind == "search" and key.lower() in {
                "script",
                "script_fields",
                "runtime_mappings",
                "query_string",
                "simple_query_string",
                "painless",
                "knn",
                "percolate",
                "wrapper",
                "template",
            }:
                raise AdapterError("CONNECTOR_FILTER_FORBIDDEN")
            validate_filter(item, kind=kind, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 1000:
            raise AdapterError("CONNECTOR_FILTER_INVALID")
        for item in value:
            validate_filter(item, kind=kind, depth=depth + 1)
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise AdapterError("CONNECTOR_FILTER_INVALID")
    return value


def _name(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,126}", value)
        or value in (".", "..")
    ):
        raise AdapterError("CONNECTOR_IDENTIFIER_INVALID")
    return value


def _scope(config, parameters, access):
    namespace = parameters.get("schema", config.get("database") or config.get("keyspace", ""))
    table = parameters.get("table")
    if namespace:
        _name(namespace)
    if table:
        _name(table)
    allowed = access or {}
    if allowed.get("allowed_schemas") and namespace not in allowed["allowed_schemas"]:
        raise AdapterError("CONNECTOR_SOURCE_FORBIDDEN")
    if (
        table
        and allowed.get("allowed_tables")
        and table not in allowed["allowed_tables"]
        and namespace + "." + table not in allowed["allowed_tables"]
    ):
        raise AdapterError("CONNECTOR_SOURCE_FORBIDDEN")
    return namespace, table


def _document(value):
    # BSON types that lack a native tabular counterpart use stable Extended JSON.
    try:
        return _json_value(value)
    except AdapterError:
        from bson import json_util

        return json.loads(json_util.dumps(value))


def _stage(rows, operation, parameters, directory, deadline, *, flatten_paths=None):
    limit = parameters.get("limit", 100)
    max_rows = parameters.get("max_rows", 3000000)
    max_bytes = parameters.get("max_bytes", 1024**3)
    if (
        type(limit) is not int
        or not 1 <= limit <= 1000
        or type(max_rows) is not int
        or not 1 <= max_rows <= 10000000
        or type(max_bytes) is not int
        or not 1 <= max_bytes <= 1024**3
    ):
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    flatten_paths = flatten_paths or []
    if (
        not isinstance(flatten_paths, list)
        or len(flatten_paths) > 64
        or len(set(flatten_paths)) != len(flatten_paths)
        or not all(
            isinstance(p, str)
            and re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", p)
            and p != "document"
            for p in flatten_paths
        )
    ):
        raise AdapterError("CONNECTOR_FLATTEN_INVALID")
    columns = ["document", *flatten_paths]
    # Document shape can vary; retain the entire document in a single typed
    # JSON column unless flattening was explicitly selected on the connection.
    output = directory / "rows.jsonl"
    count = size = 0
    digest = hashlib.sha256()
    preview = []
    with output.open("xb") as handle:
        for row in rows:
            _remaining(deadline)
            value = _document(row._asdict() if hasattr(row, "_asdict") else row)
            document = json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True)
            values = [document]
            for field in flatten_paths:
                nested = value
                for part in field.split("."):
                    nested = nested.get(part) if isinstance(nested, dict) else None
                values.append(
                    json.dumps(nested, ensure_ascii=False, sort_keys=True)
                    if isinstance(nested, (dict, list))
                    else nested
                )
            count += 1
            payload = (json.dumps(values, allow_nan=False, ensure_ascii=False) + "\n").encode()
            size += len(payload)
            if count > max_rows or size > max_bytes:
                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
            if operation in ("preview", "table"):
                preview.append(values)
                if size > 4 * 1024 * 1024:
                    raise AdapterError("CONNECTOR_PREVIEW_TOO_LARGE")
                if count >= limit:
                    break
            else:
                handle.write(payload)
                digest.update(payload)
    common = {"columns": columns, "row_count": count, "consistency": "none", "source": "real"}
    if operation in ("preview", "table"):
        return {**common, "rows": preview}
    return {
        **common,
        "artifact": "rows.jsonl",
        "format": "typed-jsonl-v2",
        "bytes": size,
        "sha256": digest.hexdigest(),
    }


def _test_result(version, *, forbidden=False):
    # Bind only the software version returned by the source. A successful ping
    # without an observable version stays connected but cannot earn a badge.
    observed = (
        version
        if isinstance(version, str) and re.fullmatch(r"[0-9][A-Za-z0-9.+_-]{0,159}", version)
        else None
    )
    result = {"connected": True, "source": "real", "server_version": observed}
    if observed is None:
        result["identity_error_code"] = (
            "CONNECTOR_SERVER_VERSION_FORBIDDEN"
            if forbidden
            else "CONNECTOR_SERVER_VERSION_UNAVAILABLE"
        )
    return result


def _mongo(operation, config, credentials, parameters, deadline, directory, access):
    from pymongo import MongoClient

    database, table = _scope(config, parameters, access)
    query = validate_filter(parameters.get("filter", {}), kind="mongo")
    if not isinstance(query, dict):
        raise AdapterError("CONNECTOR_FILTER_INVALID")
    host, port = config["host"], config.get("port", 27017)
    with pinned_python_driver([(host, port)]):
        with MongoClient(
            host=host,
            port=port,
            username=config.get("username"),
            password=credentials.get("password"),
            authSource=config.get("auth_source", database),
            tls=True,
            tlsAllowInvalidCertificates=False,
            tlsAllowInvalidHostnames=False,
            directConnection=True,
            connectTimeoutMS=min(10000, int(_remaining(deadline) * 1000)),
            serverSelectionTimeoutMS=min(10000, int(_remaining(deadline) * 1000)),
            socketTimeoutMS=int(_remaining(deadline) * 1000),
            retryReads=False,
            retryWrites=False,
        ) as client:
            db = client[database]
            if operation == "test":
                client.admin.command("ping")
                _remaining(deadline)
                try:
                    build = client.admin.command("buildInfo")
                except Exception as exc:
                    if getattr(exc, "code", None) == 13:  # MongoDB Unauthorized
                        return _test_result(None, forbidden=True)
                    raise
                return _test_result(build.get("version") if isinstance(build, dict) else None)
            if operation == "catalog":
                names = db.list_collection_names()
                return {
                    "tables": [
                        {"schema": database, "table": name}
                        for name in names
                        if not (access or {}).get("allowed_tables")
                        or name in access["allowed_tables"]
                        or database + "." + name in access["allowed_tables"]
                    ]
                }
            if not table:
                raise AdapterError("CONNECTOR_TABLE_REQUIRED")
            cursor = (
                db[table]
                .find(query, projection=None, batch_size=500)
                .max_time_ms(max(1, int(_remaining(deadline) * 1000)))
                .sort("_id", 1)
            )
            try:
                return _stage(
                    cursor,
                    operation,
                    parameters,
                    directory,
                    deadline,
                    flatten_paths=config.get("flatten_paths"),
                )
            finally:
                cursor.close()


def _search(operation, config, credentials, parameters, deadline, directory, access):
    _, table = _scope(config, parameters, access)
    base = endpoint(config["endpoint"])
    headers = {"Content-Type": "application/json"}
    if credentials.get("api_key"):
        headers["Authorization"] = "ApiKey " + credentials["api_key"]
    elif credentials.get("password"):
        import base64

        headers["Authorization"] = (
            "Basic "
            + base64.b64encode(
                (config["username"] + ":" + credentials["password"]).encode()
            ).decode()
        )
    query = validate_filter(parameters.get("filter", {"match_all": {}}), kind="search")
    validate_search_query(query)
    if not isinstance(query, dict):
        raise AdapterError("CONNECTOR_FILTER_INVALID")

    def req(method, path, body=None):
        return http.json_request(
            method,
            base + path,
            deadline_at=deadline,
            headers=headers,
            content=json.dumps(body).encode() if body is not None else None,
        )[1]

    if operation == "test":
        info = req("GET", "/")
        if not isinstance(info, dict) or not info:
            raise AdapterError("CONNECTOR_RESPONSE_INVALID")
        version = info.get("version")
        return _test_result(version.get("number") if isinstance(version, dict) else None)
    if operation == "catalog":
        indices = req("GET", "/_cat/indices?format=json&h=index")
        allowed = (access or {}).get("allowed_tables")
        return {
            "tables": [
                {"schema": "", "table": r["index"]}
                for r in indices
                if not allowed or r["index"] in allowed
            ]
        }
    if not table:
        raise AdapterError("CONNECTOR_TABLE_REQUIRED")
    table = quote(table, safe="")
    if operation == "table":
        return {"mapping": req("GET", "/" + table + "/_mapping")}
    opensearch = config.get("_engine") == "opensearch"
    pit = req(
        "POST",
        "/"
        + table
        + ("/_search/point_in_time?keep_alive=1m" if opensearch else "/_pit?keep_alive=1m"),
    ).get("pit_id" if opensearch else "id")
    if not pit:
        raise AdapterError("CONNECTOR_RESPONSE_INVALID")

    def rows():
        nonlocal pit
        after = None
        while True:
            body = {
                "size": 500,
                "query": query,
                "sort": ["_shard_doc"],
                "pit": {"id": pit, "keep_alive": "1m"},
                "track_total_hits": False,
                "timeout": str(max(1, min(30, int(_remaining(deadline))))) + "s",
            }
            if after is not None:
                body["search_after"] = after
            result = req("POST", "/_search", body)
            if result.get("timed_out") or result.get("_shards", {}).get("failed"):
                raise AdapterError("CONNECTOR_SOURCE_INCOMPLETE")
            pit = result.get("pit_id", pit)
            hits = result.get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                yield {"_id": hit["_id"], **hit.get("_source", {})}
            next_after = hits[-1].get("sort")
            if not next_after or next_after == after:
                raise AdapterError("CONNECTOR_PAGINATION_INVALID")
            after = next_after

    try:
        result = _stage(
            rows(),
            operation,
            parameters,
            directory,
            deadline,
            flatten_paths=config.get("flatten_paths"),
        )
        result["consistency"] = "snapshot"
        return result
    finally:
        try:
            req(
                "DELETE",
                "/_search/point_in_time" if opensearch else "/_pit",
                {"pit_id": [pit]} if opensearch else {"id": pit},
            )
        except Exception:
            pass


def _cassandra(operation, config, credentials, parameters, deadline, directory, access):
    from cassandra.auth import PlainTextAuthProvider
    from cassandra.cluster import Cluster
    from cassandra.io.asyncioreactor import AsyncioConnection
    from cassandra.policies import WhiteListRoundRobinPolicy
    from cassandra.query import SimpleStatement, dict_factory

    namespace, table = _scope(config, parameters, access)
    host, port = config["host"], config.get("port", 9042)
    context = ssl.create_default_context()
    with pinned_python_driver([(host, port)]) as destinations:
        cluster = Cluster(
            contact_points=[host],
            port=port,
            ssl_context=context,
            ssl_options={"server_hostname": host},
            auth_provider=PlainTextAuthProvider(
                username=config["username"], password=credentials["password"]
            ),
            load_balancing_policy=WhiteListRoundRobinPolicy([destinations[0].address]),
            connection_class=AsyncioConnection,
            connect_timeout=min(10, _remaining(deadline)),
            control_connection_timeout=min(10, _remaining(deadline)),
            protocol_version=4,
        )
        try:
            session = cluster.connect()
            session.row_factory = dict_factory
            if operation == "test":
                try:
                    info = session.execute(
                        "SELECT release_version FROM system.local",
                        timeout=min(30, _remaining(deadline)),
                    ).one()
                except Exception as exc:
                    from cassandra import Unauthorized

                    if isinstance(exc, Unauthorized):
                        return _test_result(None, forbidden=True)
                    raise
                return _test_result(info.get("release_version") if isinstance(info, dict) else None)
            metadata = cluster.metadata.keyspaces.get(namespace)
            if metadata is None:
                raise AdapterError("CONNECTOR_SOURCE_NOT_FOUND")
            if operation == "catalog":
                allowed = (access or {}).get("allowed_tables")
                return {
                    "tables": [
                        {"schema": namespace, "table": name}
                        for name in metadata.tables
                        if not allowed or name in allowed or namespace + "." + name in allowed
                    ]
                }
            spec = metadata.tables.get(table)
            if spec is None:
                raise AdapterError("CONNECTOR_SOURCE_NOT_FOUND")
            if operation == "table":
                return {
                    "columns": [
                        {"name": c.name, "type": c.cql_type} for c in spec.columns.values()
                    ],
                    "partition_keys": [c.name for c in spec.partition_key],
                }
            statement = f"SELECT * FROM {_identifier(namespace)}.{_identifier(table)}"
            values = []
            if "token_start" in parameters or "token_end" in parameters:
                start, end = parameters.get("token_start"), parameters.get("token_end")
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not -(2**63) <= start < end < 2**63
                ):
                    raise AdapterError("CONNECTOR_PARTITION_BOUNDS_INVALID")
                token = "token(" + ",".join(_identifier(c.name) for c in spec.partition_key) + ")"
                statement += f" WHERE {token} > %s AND {token} <= %s"
                values = [start, end]
            if operation == "preview":
                statement += " LIMIT " + str(min(1000, parameters.get("limit", 100)))
            rows = session.execute(
                SimpleStatement(statement, fetch_size=500),
                values or None,
                timeout=min(30, _remaining(deadline)),
            )
            return _stage(rows, operation, parameters, directory, deadline)
        finally:
            cluster.shutdown()


def execute(
    operation,
    config,
    credentials,
    parameters,
    deadline_at,
    output_dir,
    *,
    dialect,
    access=None,
    limits=None,
    execution=None,
):
    if operation in ("write_append", "write_upsert", "reconcile_write"):
        from app.services.connectors.adapters.nosql_write import execute as write

        return write(
            operation,
            config,
            credentials,
            parameters,
            deadline_at,
            dialect=dialect,
            access=access,
            execution=execution,
        )
    if operation not in ("test", "catalog", "table", "preview", "import"):
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {
        "schema",
        "table",
        "filter",
        "limit",
        "max_rows",
        "max_bytes",
        "token_start",
        "token_end",
    }:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    fn = {
        "mongodb": _mongo,
        "elasticsearch": _search,
        "opensearch": _search,
        "cassandra": _cassandra,
    }.get(dialect)
    if fn is None:
        raise AdapterError("CONNECTOR_DIALECT_UNSUPPORTED")
    try:
        return fn(
            operation,
            {**config, "_engine": dialect},
            credentials,
            parameters,
            deadline_at,
            output_dir,
            access,
        )
    except AdapterError:
        raise
    except ImportError:
        raise AdapterError("CONNECTOR_DRIVER_UNAVAILABLE") from None
    except Exception as exc:
        from app.services.connectors.network_policy import ConnectorNetworkError

        if isinstance(exc, ConnectorNetworkError):
            raise
        raise AdapterError("CONNECTOR_NOSQL_FAILED") from None
