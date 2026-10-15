"""Bounded object/document preflight with no remote mutation or invented counts."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from urllib.parse import quote

from app.services.connectors.adapters import http
from app.services.connectors.adapters.driver_egress import pinned_python_driver
from app.services.connectors.adapters.nosql import _name, _scope
from app.services.connectors.adapters.nosql_write import documents
from app.services.connectors.adapters.object_clients import client_for, endpoint, object_key
from app.services.connectors.adapters.sql import AdapterError, _json_value, _remaining
from app.services.connectors.adapters.sql_write import _execution


def _input(execution, deadline):
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    paths = _execution(execution)
    size = sum(path.stat().st_size for path in paths)
    if size > 1024**3:
        raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
    rows = 0
    for path in paths:
        _remaining(deadline)
        with pq.ParquetFile(path) as reader:
            rows += reader.metadata.num_rows
    if rows > 10_000_000:
        raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
    schema = ds.dataset([str(p) for p in paths], format="parquet").schema
    if not 1 <= len(schema) <= 2000:
        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
    return paths, rows, schema


def _receipt(execution, rows, schema, **details):
    return {
        "dry_run": True,
        "applied": False,
        "operation_id": execution["operation_id"],
        "contract_digest": execution["contract_digest"],
        "input_sha256": execution["input_sha256"],
        "write_operation": execution["write_operation"],
        "input_rows": rows,
        "source_columns": [
            {"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in schema
        ],
        "inserted": None,
        "updated": None,
        "deleted": None,
        "target_rows": None,
        "counts_are_estimates": True,
        "effects_observed": False,
        "consistency": "none",
        "source": "real",
        **details,
    }


def _objects(config, credentials, parameters, deadline, directory, dialect, execution):
    _, rows, schema = _input(execution, deadline)
    if rows == 0 and parameters.get("format", "parquet") == "parquet":
        raise AdapterError("CONNECTOR_EMPTY_EXPORT_UNSUPPORTED")
    if execution.get("write_operation") != "export" or dialect not in {
        "s3",
        "s3_compatible",
        "azure_blob",
        "gcs",
    }:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {"prefix", "format", "mode", "expected_pointer_etag"}:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    prefix = object_key(
        parameters.get("prefix", config.get("prefix", "")), config.get("prefix", "")
    ).rstrip("/")
    if not prefix:
        raise AdapterError("CONNECTOR_EXPORT_PREFIX_REQUIRED")
    if parameters.get("format", "parquet") == "delta":
        from app.services.connectors.adapters.delta_export import _prefix

        _prefix(config, parameters)
    elif parameters.get("format", "parquet") != "parquet" or "mode" in parameters:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    # Request the exact write principal/role, but send only listing/GET calls.
    # A successful read does not establish a PUT privilege or CAS success.
    client = client_for(dialect, {**config, "_write": True}, credentials, deadline)
    if parameters.get("format", "parquet") == "delta":
        import pyarrow as pa
        from deltalake import DeltaTable

        from app.services.connectors.adapters.delta_export import _logs, _stage_logs

        logs = _logs(client, prefix, deadline)
        local = _stage_logs(client, logs, prefix, directory, deadline)
        current = DeltaTable(str(local)) if logs else None
        if current is not None:
            remote_schema = pa.schema(current.schema().to_arrow())
            if [(f.name, f.type) for f in schema] != [(f.name, f.type) for f in remote_schema]:
                raise AdapterError("CONNECTOR_SCHEMA_MISMATCH")
        return _receipt(
            execution,
            rows,
            schema,
            format="delta",
            prefix=prefix,
            target_version=current.version() if current else None,
            validation_scope="input_schema_and_frozen_delta_log",
            write_permissions_checked=False,
            publication_cas_checked=False,
        )
    try:
        payload, etag = client.read_small(prefix + "/_LATEST.json")
    except AdapterError as exc:
        if exc.code != "CONNECTOR_SOURCE_NOT_FOUND":
            raise
        etag = None
    else:
        try:
            pointer = json.loads(payload)
            if not isinstance(pointer, dict) or not isinstance(pointer.get("manifest"), str):
                raise ValueError
            object_key(pointer["manifest"], prefix)
        except (ValueError, TypeError):
            raise AdapterError("CONNECTOR_RESPONSE_INVALID") from None
        if not etag:
            raise AdapterError("CONNECTOR_OBJECT_IDENTITY_INVALID")
    if etag != parameters.get("expected_pointer_etag"):
        raise AdapterError("CONNECTOR_SOURCE_CHANGED")
    return _receipt(
        execution,
        rows,
        schema,
        format="parquet",
        prefix=prefix,
        pointer_etag=etag,
        validation_scope="input_schema_and_current_pointer",
        write_permissions_checked=False,
        publication_cas_checked=False,
    )


def _document_input(execution, parameters, deadline, directory, dialect):
    keys = parameters.get("keys") or []
    if execution["write_operation"] == "write_upsert" and not keys:
        raise AdapterError("CONNECTOR_UPSERT_KEY_REQUIRED")
    if (
        not isinstance(keys, list)
        or len(keys) > 2000
        or any(
            not isinstance(key, str) or not key or key.startswith("$") or "\x00" in key
            for key in keys
        )
        or len(keys) != len(set(keys))
    ):
        raise AdapterError("CONNECTOR_UPSERT_KEY_INVALID")
    count = 0
    with sqlite3.connect(directory / "preview-document-keys.sqlite") as index:
        index.execute("CREATE TABLE keys (value TEXT PRIMARY KEY)")
        for identity, doc in documents(execution, parameters):
            _remaining(deadline)
            payload = json.dumps(_json_value(doc), allow_nan=False).encode()
            if len(payload) > 8 * 1024**2:
                raise AdapterError("CONNECTOR_ROW_TOO_LARGE")
            if (
                dialect == "mongodb"
                and execution["write_operation"] == "write_append"
                and "_id" in doc
            ):
                identity = hashlib.sha256(
                    json.dumps(_json_value(doc["_id"]), sort_keys=True).encode()
                ).hexdigest()
            try:
                index.execute("INSERT INTO keys VALUES (?)", (identity,))
            except sqlite3.IntegrityError:
                raise AdapterError("CONNECTOR_DUPLICATE_KEY") from None
            count += 1
            if count > 10_000_000:
                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
    return keys, count


def _mongo(config, credentials, parameters, deadline, access, keys, operation):
    from pymongo import MongoClient

    namespace, table = _scope(config, parameters, access)
    marker = _name(config.get("marker_collection", "agentium_operations"))
    if not table or marker == table:
        raise AdapterError("CONNECTOR_MARKER_TARGET_CONFLICT")
    host, port = config["host"], config.get("port", 27017)
    with (
        pinned_python_driver([(host, port)]),
        MongoClient(
            host=host,
            port=port,
            username=config["username"],
            password=credentials["password"],
            authSource=config.get("auth_source") or namespace,
            tls=True,
            tlsAllowInvalidCertificates=False,
            tlsAllowInvalidHostnames=False,
            directConnection=True,
            retryReads=False,
            retryWrites=False,
            connectTimeoutMS=min(10000, int(_remaining(deadline) * 1000)),
            serverSelectionTimeoutMS=min(10000, int(_remaining(deadline) * 1000)),
            socketTimeoutMS=int(_remaining(deadline) * 1000),
        ) as client,
    ):
        db = client[namespace]
        collections = db.list_collection_names()
        if marker not in collections or table not in collections:
            raise AdapterError("CONNECTOR_SOURCE_NOT_FOUND")
        indexes = list(db[table].list_indexes())
        if operation == "write_upsert" and not any(
            list(item.get("key", {})) == keys and (item.get("unique") or keys == ["_id"])
            for item in indexes
        ):
            raise AdapterError("CONNECTOR_UNIQUE_KEY_REQUIRED")
        return {
            "validation_scope": "input_documents_and_target_unique_indexes",
            "target_indexes": [
                {
                    "keys": list(i.get("key", {})),
                    "unique": bool(i.get("unique") or list(i.get("key", {})) == ["_id"]),
                }
                for i in indexes
            ],
            "write_permissions_checked": False,
            "transaction_support_checked": False,
        }


def _search(config, credentials, parameters, deadline, access):
    _, table = _scope(config, parameters, access)
    marker = _name(config.get("marker_index", "agentium_operations"))
    if not table or marker == table:
        raise AdapterError("CONNECTOR_MARKER_TARGET_CONFLICT")
    base = endpoint(config["endpoint"])
    if credentials.get("api_key"):
        headers = {"Authorization": "ApiKey " + credentials["api_key"]}
    else:
        token = base64.b64encode(
            (config["username"] + ":" + credentials["password"]).encode()
        ).decode()
        headers = {"Authorization": "Basic " + token}
    mappings = {}
    for name in (marker, table):
        _, mapping = http.json_request(
            "GET",
            base + "/" + quote(name, safe="") + "/_mapping",
            deadline_at=deadline,
            headers=headers,
            max_bytes=4 * 1024**2,
        )
        if not isinstance(mapping, dict) or not mapping:
            raise AdapterError("CONNECTOR_SCHEMA_INVALID")
        mappings[name] = hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest()
    return {
        "validation_scope": "input_documents_and_target_mapping",
        "target_mapping_digest": mappings[table],
        "write_permissions_checked": False,
        "mapping_compatibility_checked": False,
    }


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
    if operation != "write_preview" or not execution or (access or {}).get("mode") != "read_write":
        raise AdapterError("CONNECTOR_APPROVAL_REQUIRED")
    if dialect in {"s3", "s3_compatible", "azure_blob", "gcs"}:
        return _objects(
            config, credentials, parameters, deadline_at, output_dir, dialect, execution
        )
    if dialect not in {"mongodb", "elasticsearch", "opensearch"} or execution.get(
        "write_operation"
    ) not in {"write_append", "write_upsert"}:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {"schema", "table", "keys", "create_table"} or parameters.get(
        "create_table"
    ):
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    _, rows, schema = _input(execution, deadline_at)
    keys, count = _document_input(execution, parameters, deadline_at, output_dir, dialect)
    if rows != count:
        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
    details = (
        _mongo(
            config, credentials, parameters, deadline_at, access, keys, execution["write_operation"]
        )
        if dialect == "mongodb"
        else _search(config, credentials, parameters, deadline_at, access)
    )
    return _receipt(execution, rows, schema, **details)
