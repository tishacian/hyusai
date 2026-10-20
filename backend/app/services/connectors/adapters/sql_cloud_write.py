"""Bounded, approved cloud DML; uncertain requests are never automatically replayed.

Inline SQL is limited before sending any mutation. Larger datasets need a
supplier staging path and are refused rather than truncated or split into
independently committed writes.
"""

from __future__ import annotations

import base64
import json
import math
import time
from datetime import UTC, date, datetime
from urllib.parse import quote

import pyarrow as pa

from app.services.connectors.adapters.sql import (
    AdapterError,
    _identifier,
    _remaining,
    _scope,
    _target,
)
from app.services.connectors.adapters.sql_cloud import CloudConnection, _id
from app.services.connectors.adapters.sql_write import _batches, _execution

MAX_ROWS = 4000
MAX_SQL_BYTES = 1024 * 1024


def _string(value):
    # All three parsers recognize backslash escapes. Escape the backslash first
    # so a value cannot use it to consume the quote inserted by our encoder.
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _literal(value, dtype, dialect):
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        kind = "VARCHAR" if dialect == "snowflake" else "STRING"
        literal = _string(value)
    elif pa.types.is_boolean(dtype):
        kind, literal = "BOOLEAN", "TRUE" if value else "FALSE"
    elif pa.types.is_integer(dtype):
        kind, literal = ("INT64" if dialect == "bigquery" else "BIGINT"), str(value)
    elif pa.types.is_floating(dtype):
        if value is not None and not math.isfinite(value):
            raise AdapterError("CONNECTOR_TYPE_UNSUPPORTED")
        kind, literal = ("FLOAT64" if dialect == "bigquery" else "DOUBLE"), repr(value)
    elif pa.types.is_decimal(dtype):
        if dtype.precision > (76 if dialect == "bigquery" else 38):
            raise AdapterError("CONNECTOR_TYPE_UNSUPPORTED")
        kind = (
            ("NUMERIC" if dtype.precision <= 38 and dtype.scale <= 9 else "BIGNUMERIC")
            if dialect == "bigquery"
            else f"DECIMAL({dtype.precision},{dtype.scale})"
        )
        literal = _string(value)
    elif pa.types.is_binary(dtype) or pa.types.is_large_binary(dtype):
        kind = "BYTES" if dialect == "bigquery" else "BINARY"
        encoded = base64.b64encode(value or b"").decode()
        function = {
            "bigquery": "FROM_BASE64",
            "snowflake": "BASE64_DECODE_BINARY",
            "databricks_sql": "UNBASE64",
        }[dialect]
        literal = f"{function}({_string(encoded)})"
    elif pa.types.is_date(dtype):
        kind, literal = "DATE", _string(value.isoformat() if isinstance(value, date) else value)
    elif pa.types.is_timestamp(dtype):
        kind = (
            "TIMESTAMP_TZ"
            if dialect == "snowflake" and dtype.tz
            else "TIMESTAMP_NTZ"
            if dialect == "snowflake"
            else "TIMESTAMP"
            if dtype.tz
            else "DATETIME"
            if dialect == "bigquery"
            else "TIMESTAMP_NTZ"
        )
        if isinstance(value, datetime) and value.tzinfo:
            value = value.astimezone(UTC)
        literal = _string(value.isoformat() if isinstance(value, datetime) else value)
    elif pa.types.is_null(dtype):
        # There is no trustworthy destination type without catalog metadata.
        raise AdapterError("CONNECTOR_TYPE_UNSUPPORTED")
    else:
        raise AdapterError("CONNECTOR_TYPE_UNSUPPORTED")
    return f"CAST({'NULL' if value is None else literal} AS {kind})"


def _source(paths, parameters, dialect):
    names, batches = _batches(paths, parameters.get("columns"))
    columns = [_identifier(name, dialect) for name in names]
    selects, seen, count, size = [], set(), 0, 0
    keys = parameters.get("keys") or []
    if (
        not isinstance(keys, list)
        or any(not isinstance(key, str) for key in keys)
        or len(set(keys)) != len(keys)
        or set(keys) - set(names)
    ):
        raise AdapterError("CONNECTOR_UPSERT_KEY_REQUIRED")
    for batch in batches:
        for row in batch.to_pylist():
            count += 1
            if count > MAX_ROWS:
                raise AdapterError("CONNECTOR_CLOUD_STAGING_REQUIRED")
            if keys:
                values = tuple(row[key] for key in keys)
                if any(value is None for value in values):
                    raise AdapterError("CONNECTOR_UPSERT_NULL_KEY")
                identity = repr(values)
                if identity in seen:
                    raise AdapterError("CONNECTOR_UPSERT_DUPLICATE_KEY")
                seen.add(identity)
            select = "SELECT " + ", ".join(
                f"{_literal(row[name], batch.schema.field(name).type, dialect)} AS {column}"
                for name, column in zip(names, columns, strict=True)
            )
            size += len(select.encode()) + 11
            if size > MAX_SQL_BYTES:
                raise AdapterError("CONNECTOR_CLOUD_STAGING_REQUIRED")
            selects.append(select)
    if not count:
        raise AdapterError("CONNECTOR_EMPTY_WRITE")
    return names, columns, " UNION ALL ".join(selects), count


def _merge(target, source, names, keys, dialect):
    if not keys:
        raise AdapterError("CONNECTOR_UPSERT_KEY_REQUIRED")
    columns = [_identifier(name, dialect) for name in names]
    equal = " AND ".join(
        f"t.{_identifier(key, dialect)}=s.{_identifier(key, dialect)}" for key in keys
    )
    assignments = ", ".join(f"{column}=s.{column}" for column in columns)
    query = f"MERGE INTO {target} t USING ({source}) s ON {equal} WHEN MATCHED THEN UPDATE SET {assignments} WHEN NOT MATCHED THEN INSERT ({', '.join(columns)}) VALUES ({', '.join('s.' + column for column in columns)})"
    return query, equal


def _receipt(execution, count, outcome, **extra):
    return {
        "operation_id": execution["operation_id"],
        "contract_digest": execution["contract_digest"],
        "input_sha256": execution["input_sha256"],
        "row_count": count,
        "applied": True,
        "outcome_check": outcome,
        **extra,
    }


def _labels(execution):
    return {
        f"{key}_{part}": execution[field][offset : offset + 32]
        for key, field in (("contract", "contract_digest"), ("input", "input_sha256"))
        for part, offset in (("hi", 0), ("lo", 32))
    }


def _bigquery(connection, operation, target, source, names, columns, count, parameters, execution):
    config = connection.config
    project, location = _id(config["project"]), config.get("location", "US")
    job_id = "agentium_" + execution["operation_id"].replace("-", "")
    path = f"/bigquery/v2/projects/{project}/jobs/{job_id}"
    suffix = "?location=" + quote(location, safe="")
    if operation == "reconcile_write":
        payload = connection.request("GET", path + suffix)
    else:
        inserted = str(count)
        statements = [
            "DECLARE inserted INT64 DEFAULT 0",
            "DECLARE updated INT64 DEFAULT 0",
            "BEGIN TRANSACTION",
        ]
        if operation == "write_upsert":
            merge, equality = _merge(target, source, names, parameters.get("keys"), "bigquery")
            keys = ", ".join("t." + _identifier(key, "bigquery") for key in parameters["keys"])
            statements += [
                f"ASSERT (SELECT COUNT(*) FROM (SELECT {keys} FROM {target} t JOIN ({source}) s ON {equality} GROUP BY {keys} HAVING COUNT(*)>1))=0 AS 'non_unique_target'"
            ]
            inserted = f"(SELECT COUNT(*) FROM ({source}) s WHERE NOT EXISTS (SELECT 1 FROM {target} t WHERE {equality}))"
            statements += [f"SET inserted={inserted}", f"SET updated={count}-inserted", merge]
        else:
            if operation == "write_overwrite":
                statements.append(f"DELETE FROM {target} WHERE TRUE")
            statements += [
                f"INSERT INTO {target} ({', '.join(columns)}) {source}",
                f"SET inserted={count}",
            ]
        statements += [
            "COMMIT TRANSACTION",
            f"SELECT {_string(execution['operation_id'])} AS operation_id, {_string(execution['contract_digest'])} AS contract_digest, {_string(execution['input_sha256'])} AS input_sha256, inserted, updated",
        ]
        query = ";\n".join(statements)
        if len(query.encode()) > MAX_SQL_BYTES:
            raise AdapterError("CONNECTOR_CLOUD_STAGING_REQUIRED")
        budget = config.get("maximum_bytes_billed", 1024**3)
        if type(budget) is not int or not 1 <= budget <= 1024**4:
            raise AdapterError("CONNECTOR_BUDGET_INVALID")
        payload = connection.request(
            "POST",
            f"/bigquery/v2/projects/{project}/jobs",
            {
                "jobReference": {"projectId": project, "jobId": job_id, "location": location},
                "configuration": {
                    "labels": _labels(execution),
                    "jobTimeoutMs": str(max(1, int(_remaining(connection.deadline_at) * 1000))),
                    "query": {
                        "query": query,
                        "useLegacySql": False,
                        "maximumBytesBilled": str(budget),
                    },
                },
            },
        )
    while (payload.get("status") or {}).get("state") != "DONE":
        if operation == "reconcile_write":
            return {
                "operation_id": execution["operation_id"],
                "applied": False,
                "outcome": "unknown",
                "job_id": job_id,
            }
        time.sleep(min(0.25, _remaining(connection.deadline_at)))
        payload = connection.request("GET", path + suffix)
    if (payload.get("status") or {}).get("errorResult"):
        raise AdapterError("CONNECTOR_SQL_FAILED")
    if (payload.get("configuration") or {}).get("labels") != _labels(execution):
        raise AdapterError("CONNECTOR_IDEMPOTENCY_CONFLICT")
    result = connection.request("GET", f"/bigquery/v2/projects/{project}/queries/{job_id}" + suffix)
    fields = [item["name"] for item in (result.get("schema") or {}).get("fields", [])]
    rows = result.get("rows") or []
    if not result.get("jobComplete") or len(rows) != 1:
        raise AdapterError("CONNECTOR_RECEIPT_INVALID")
    receipt = dict(zip(fields, [item.get("v") for item in rows[0].get("f", [])], strict=True))
    if any(
        receipt.get(key) != execution[key]
        for key in ("operation_id", "contract_digest", "input_sha256")
    ):
        raise AdapterError("CONNECTOR_IDEMPOTENCY_CONFLICT")
    inserted, updated = int(receipt["inserted"]), int(receipt["updated"])
    if min(inserted, updated) < 0 or (
        operation != "reconcile_write" and inserted + updated != count
    ):
        raise AdapterError("CONNECTOR_WRITE_COUNT_MISMATCH")
    return _receipt(
        execution,
        inserted + updated,
        "job_id",
        inserted=inserted,
        updated=updated,
        job_id=job_id,
        reconciled=operation == "reconcile_write",
    )


def _snowflake_marker(connection, marker, execution):
    cursor = connection.cursor()
    try:
        cursor.execute(
            f'SELECT "contract_digest", "input_sha256", "receipt_json" FROM {marker} WHERE "operation_id"=%s',
            (execution["operation_id"],),
        )
        found = cursor.fetchone()
        if not found:
            return {
                "operation_id": execution["operation_id"],
                "applied": False,
                "outcome": "unknown",
            }
        if (
            found[:2] != (execution["contract_digest"], execution["input_sha256"])
            or cursor.fetchone() is not None
        ):
            raise AdapterError("CONNECTOR_IDEMPOTENCY_CONFLICT")
        receipt = json.loads(found[2])
        if (
            receipt.get("operation_id") != execution["operation_id"]
            or receipt.get("contract_digest") != execution["contract_digest"]
            or receipt.get("applied") is not True
        ):
            raise AdapterError("CONNECTOR_RECEIPT_INVALID")
        return {**receipt, "reconciled": True}
    finally:
        cursor.close()


def _snowflake(
    connection, operation, target, marker, source, names, columns, count, parameters, execution
):
    previous = _snowflake_marker(connection, marker, execution)
    if operation == "reconcile_write" or previous.get("applied"):
        return previous
    statements = [
        "DECLARE inserted INTEGER DEFAULT 0; updated INTEGER DEFAULT 0; duplicates INTEGER DEFAULT 0; duplicate_target EXCEPTION (-20001, 'CONNECTOR_UPSERT_NON_UNIQUE_TARGET'); BEGIN",
        "BEGIN TRANSACTION;",
    ]
    if operation == "write_upsert":
        merge, equality = _merge(target, source, names, parameters.get("keys"), "snowflake")
        key_sql = ", ".join("t." + _identifier(key, "snowflake") for key in parameters["keys"])
        statements += [
            f"SELECT COUNT(*) INTO :duplicates FROM (SELECT {key_sql} FROM {target} t JOIN ({source}) s ON {equality} GROUP BY {key_sql} HAVING COUNT(*)>1);",
            "IF (duplicates>0) THEN RAISE duplicate_target; END IF;",
        ]
        # Multiple target rows make counts ambiguous; the MERGE session option
        # ERROR_ON_NONDETERMINISTIC_MERGE additionally fails conflicting sources.
        statements += [
            f"SELECT COUNT(*) INTO :inserted FROM ({source}) s WHERE NOT EXISTS (SELECT 1 FROM {target} t WHERE {equality});",
            f"updated := {count} - inserted;",
            merge + ";",
        ]
    else:
        if operation == "write_overwrite":
            statements.append(f"DELETE FROM {target};")
        statements += [
            f"INSERT INTO {target} ({', '.join(columns)}) {source};",
            f"inserted := {count};",
        ]
    # Counts are computed inside the same transaction as the destination and
    # marker. The marker is the only successful durable reconciliation result.
    base = _receipt(execution, count, "marker_table")
    fields = ", ".join(
        _string(key)
        + ", "
        + ("TRUE" if value is True else str(value) if isinstance(value, int) else _string(value))
        for key, value in base.items()
    )
    receipt = f"TO_JSON(OBJECT_CONSTRUCT({fields}, 'inserted', :inserted, 'updated', :updated))"
    statements += [
        f'INSERT INTO {marker} ("operation_id", "contract_digest", "input_sha256", "receipt_json") SELECT {_string(execution["operation_id"])}, {_string(execution["contract_digest"])}, {_string(execution["input_sha256"])}, {receipt};',
        "COMMIT;",
        "RETURN TRUE;",
        "EXCEPTION WHEN OTHER THEN ROLLBACK; RAISE; END;",
    ]
    query = "EXECUTE IMMEDIATE " + _string("\n".join(statements))
    if len(query.encode()) > MAX_SQL_BYTES:
        raise AdapterError("CONNECTOR_CLOUD_STAGING_REQUIRED")
    body = {
        "statement": query,
        "timeout": max(1, int(_remaining(connection.deadline_at))),
        "database": connection.config.get("database"),
        "schema": connection.config.get("schema"),
        "warehouse": connection.config["warehouse"],
        "parameters": {"MULTI_STATEMENT_COUNT": "1", "ERROR_ON_NONDETERMINISTIC_MERGE": "TRUE"},
    }
    if connection.config.get("role"):
        body["role"] = connection.config["role"]
    payload = connection.request(
        "POST", "/api/v2/statements?requestId=" + execution["operation_id"], body
    )
    handle = _id(payload.get("statementHandle"))
    while "resultSetMetaData" not in payload:
        if payload.get("code") not in {None, "333334", "090001"}:
            raise AdapterError("CONNECTOR_SQL_FAILED")
        time.sleep(min(0.25, _remaining(connection.deadline_at)))
        payload = connection.request("GET", "/api/v2/statements/" + handle)
    return _snowflake_marker(connection, marker, execution)


def _databricks(
    connection, operation, target, source, names, columns, count, parameters, execution
):
    if operation == "reconcile_write":
        return {"operation_id": execution["operation_id"], "applied": False, "outcome": "unknown"}
    identifiers = (
        connection.config.get("catalog", "main"),
        parameters.get("schema"),
        parameters.get("table"),
    )
    if any(not isinstance(value, str) or "." in value for value in identifiers):
        raise AdapterError("CONNECTOR_IDENTIFIER_INVALID")
    table = connection.request(
        "GET", "/api/2.1/unity-catalog/tables/" + quote(".".join(identifiers), safe="")
    )
    if str(table.get("data_source_format", "")).upper() != "DELTA":
        raise AdapterError("CONNECTOR_TRANSACTIONAL_TABLE_REQUIRED")
    if operation == "write_upsert":
        query, _ = _merge(target, source, names, parameters.get("keys"), "databricks_sql")
    else:
        verb = "INSERT OVERWRITE" if operation == "write_overwrite" else "INSERT INTO"
        query = f"{verb} {target} ({', '.join(columns)}) {source}"
    if len(query.encode()) > MAX_SQL_BYTES:
        raise AdapterError("CONNECTOR_CLOUD_STAGING_REQUIRED")
    payload = connection.request(
        "POST",
        "/api/2.0/sql/statements",
        {
            "warehouse_id": connection.config["warehouse_id"],
            "catalog": connection.config.get("catalog"),
            "schema": connection.config.get("schema"),
            "statement": query,
            "format": "JSON_ARRAY",
            "disposition": "INLINE",
            "wait_timeout": "0s",
        },
    )
    identifier = _id(payload.get("statement_id"))
    while (payload.get("status") or {}).get("state") != "SUCCEEDED":
        if (payload.get("status") or {}).get("state") in {"FAILED", "CANCELED", "CLOSED"}:
            raise AdapterError("CONNECTOR_SQL_FAILED")
        time.sleep(min(0.25, _remaining(connection.deadline_at)))
        payload = connection.request("GET", "/api/2.0/sql/statements/" + identifier)
    fields = [
        field["name"]
        for field in ((payload.get("manifest") or {}).get("schema") or {}).get("columns", [])
    ]
    values = (payload.get("result") or {}).get("data_array", [])
    counts = dict(zip(fields, values[0], strict=True)) if len(values) == 1 else {}
    affected = counts.get("num_affected_rows")
    if affected is not None and int(affected) != count:
        raise AdapterError("CONNECTOR_WRITE_COUNT_MISMATCH")
    return _receipt(
        execution,
        count,
        "none",
        statement_id=identifier,
        inserted=int(counts["num_inserted_rows"])
        if counts.get("num_inserted_rows") is not None
        else count
        if operation != "write_upsert"
        else None,
        updated=int(counts["num_updated_rows"])
        if counts.get("num_updated_rows") is not None
        else 0
        if operation != "write_upsert"
        else None,
    )


def execute_write(
    operation,
    config,
    credentials,
    parameters,
    deadline_at,
    output_dir,
    *,
    dialect,
    access,
    execution,
):
    if set(parameters) - {"schema", "table", "columns", "keys", "create_table"} or parameters.get(
        "create_table"
    ):
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    paths = _execution(execution, require_files=operation != "reconcile_write")
    schema, table = parameters.get("schema"), parameters.get("table")
    _scope(schema, table, access)
    target = _target(dialect, config, schema, table)
    names, columns, source, count = (
        _source(paths, parameters, dialect) if operation != "reconcile_write" else ([], [], "", 0)
    )
    connection = CloudConnection(dialect, config, credentials, deadline_at, read_only=False)
    try:
        if dialect == "bigquery":
            return _bigquery(
                connection, operation, target, source, names, columns, count, parameters, execution
            )
        if dialect == "snowflake":
            marker = _target(dialect, config, schema, "_agentium_operations")
            return _snowflake(
                connection,
                operation,
                target,
                marker,
                source,
                names,
                columns,
                count,
                parameters,
                execution,
            )
        return _databricks(
            connection, operation, target, source, names, columns, count, parameters, execution
        )
    finally:
        connection.close()
