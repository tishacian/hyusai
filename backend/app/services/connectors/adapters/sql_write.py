"""Approved SQL mutations with a marker committed in the same transaction.

The destination schema must already contain _agentium_operations. Engines with
enforced constraints require a unique operation_id; Redshift uses table locks
and explicit duplicate checks. No DDL is hidden in a write or uncertain retry.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from app.services.connectors.adapters.sql import (
    AdapterError,
    _connection,
    _identifier,
    _remaining,
    _scope,
    _target,
)

NATIVE_WRITERS = frozenset(
    {"postgresql", "mysql", "mariadb", "sql_server", "oracle", "synapse", "redshift"}
)


def _execution(value, *, require_files=True):
    if not isinstance(value, dict) or not re.fullmatch(
        r"[a-f0-9-]{36}", str(value.get("operation_id", ""))
    ):
        raise AdapterError("CONNECTOR_APPROVAL_REQUIRED")
    for name in ("input_sha256", "contract_digest"):
        if not re.fullmatch(r"[a-f0-9]{64}", str(value.get(name, ""))):
            raise AdapterError("CONNECTOR_WRITE_CONTRACT_CHANGED")
    if not require_files:
        return []
    paths = [Path(name) for name in value.get("input_files", [])]
    if not paths or any(path.is_symlink() or not path.is_file() for path in paths):
        raise AdapterError("CONNECTOR_INPUT_INVALID")
    hashes = []
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
        hashes.append(digest.hexdigest())
    digest = hashlib.sha256(json.dumps(hashes, separators=(",", ":")).encode()).hexdigest()
    if digest != value["input_sha256"]:
        raise AdapterError("CONNECTOR_WRITE_CONTRACT_CHANGED")
    return paths


def _placeholders(dialect, count, start=1):
    return [f":{index}" if dialect == "oracle" else "%s" for index in range(start, start + count)]


def _batches(paths, names):
    import pyarrow.dataset as ds

    dataset = ds.dataset([str(path) for path in paths], format="parquet")
    if names is not None and (
        not isinstance(names, list)
        or not names
        or len(set(names)) != len(names)
        or set(names) - set(dataset.schema.names)
    ):
        raise AdapterError("CONNECTOR_COLUMNS_INVALID")
    names = names or dataset.schema.names
    if not names or len(names) > 2000:
        raise AdapterError("CONNECTOR_COLUMNS_INVALID")
    scanner = dataset.scanner(
        columns=names, batch_size=1000, use_threads=False, batch_readahead=0, fragment_readahead=0
    )
    return names, scanner.to_batches()


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
    if dialect not in NATIVE_WRITERS:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if dialect == "redshift" and operation not in {
        "write_append",
        "write_upsert",
        "reconcile_write",
    }:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if config.get("demo_mode") or parameters.get("create_table"):
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {"schema", "table", "columns", "keys", "create_table"}:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    paths = _execution(execution, require_files=operation != "reconcile_write")
    schema, table = parameters.get("schema"), parameters.get("table")
    _scope(schema, table, access)
    target = _target(dialect, config, schema, table)
    marker = _target(dialect, config, schema, "_agentium_operations")
    if dialect == "redshift" and str(table).casefold() == "_agentium_operations":
        raise AdapterError("CONNECTOR_RESERVED_TARGET")
    if operation == "reconcile_write":
        return reconcile(
            config, credentials, deadline_at, dialect=dialect, marker=marker, execution=execution
        )
    names, batches = _batches(paths, parameters.get("columns"))
    columns = [_identifier(name, dialect) for name in names]
    keys = parameters.get("keys", [])
    if operation == "write_upsert" and (
        not isinstance(keys, list)
        or not keys
        or len(set(keys)) != len(keys)
        or set(keys) - set(names)
    ):
        raise AdapterError("CONNECTOR_UPSERT_KEY_REQUIRED")
    # A disk-backed uniqueness check bounds memory and refuses duplicate/null
    # upsert keys before any destination mutation. It also computes dry counts.
    keydb = sqlite3.connect(output_dir / "keys.sqlite")
    count = 0
    try:
        keydb.execute("CREATE TABLE seen (key TEXT PRIMARY KEY)")
        for batch in batches:
            _remaining(deadline_at)
            for row in batch.to_pylist():
                count += 1
                if count > 10_000_000:
                    raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                if keys:
                    values = [row[key] for key in keys]
                    if any(value is None for value in values):
                        raise AdapterError("CONNECTOR_UPSERT_NULL_KEY")
                    # repr includes the Python scalar type; bytes/dates/decimal
                    # are not reduced to a lossy JSON float.
                    try:
                        keydb.execute("INSERT INTO seen VALUES (?)", (repr(values),))
                    except sqlite3.IntegrityError:
                        raise AdapterError("CONNECTOR_UPSERT_DUPLICATE_KEY") from None
        keydb.commit()
    finally:
        keydb.close()
    operation_id = execution["operation_id"]
    inserted = updated = 0
    marker_parameters = (operation_id,)
    placeholder = _placeholders(dialect, 1)[0]
    with _connection(dialect, config, credentials, deadline_at, read_only=False) as connection:
        cursor = connection.cursor()
        try:
            if dialect == "redshift":
                # PK/UNIQUE constraints are informational. The schema's marker
                # is always locked first, then the data table, regardless of
                # case-folded identifier spelling. Neither lock establishes a
                # data snapshot before the other writer has committed.
                for locked in (marker, target):
                    _remaining(deadline_at)
                    cursor.execute(f"LOCK TABLE {locked}")
            if dialect in {"mysql", "mariadb"}:
                # MyISAM permits successful COMMIT while retaining partial
                # changes after rollback. Both the data and marker tables must
                # share transactional semantics before any mutation is sent.
                cursor.execute(
                    "SELECT TABLE_NAME, ENGINE FROM information_schema.tables WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s, %s)",
                    (schema, table, "_agentium_operations"),
                )
                engines = {name: str(engine).upper() for name, engine in cursor.fetchall()}
                if any(engines.get(name) != "INNODB" for name in (table, "_agentium_operations")):
                    raise AdapterError("CONNECTOR_TRANSACTIONAL_TABLE_REQUIRED")
            cursor.execute(
                f"SELECT {_identifier('contract_digest', dialect)}, {_identifier('input_sha256', dialect)}, {_identifier('receipt_json', dialect)} FROM {marker} WHERE {_identifier('operation_id', dialect)}={placeholder}",
                marker_parameters,
            )
            existing = cursor.fetchone()
            if dialect == "redshift" and cursor.fetchone() is not None:
                raise AdapterError("CONNECTOR_MARKER_NON_UNIQUE")
            if existing:
                if (
                    existing[0] != execution["contract_digest"]
                    or existing[1] != execution["input_sha256"]
                ):
                    raise AdapterError("CONNECTOR_IDEMPOTENCY_CONFLICT")
                receipt = json.loads(
                    existing[2].read() if hasattr(existing[2], "read") else existing[2]
                )
                if (
                    receipt.get("operation_id") != operation_id
                    or receipt.get("applied") is not True
                    or (
                        dialect == "redshift"
                        and (
                            receipt.get("contract_digest") != execution["contract_digest"]
                            or receipt.get("input_sha256") != execution["input_sha256"]
                        )
                    )
                ):
                    raise AdapterError("CONNECTOR_RECEIPT_INVALID")
                return {**receipt, "reconciled": True}
            if dialect == "redshift":
                cursor.execute(f"SELECT COUNT(*) FROM {target}")
                target_rows_before = int(cursor.fetchone()[0])
                if operation == "write_upsert":
                    grouped = ", ".join(_identifier(key, dialect) for key in keys)
                    cursor.execute(
                        f"SELECT 1 FROM {target} GROUP BY {grouped} HAVING COUNT(*) > 1 LIMIT 1"
                    )
                    if cursor.fetchone() is not None:
                        raise AdapterError("CONNECTOR_UPSERT_NON_UNIQUE_TARGET")
            if operation == "write_overwrite":
                # DELETE is transactional on every declared engine; TRUNCATE is
                # not (Oracle/MySQL implicitly commit DDL).
                cursor.execute(f"DELETE FROM {target}")
            _, batches = _batches(paths, names)
            insert = f"INSERT INTO {target} ({', '.join(columns)}) VALUES ({', '.join(_placeholders(dialect, len(names)))})"
            for batch in batches:
                _remaining(deadline_at)
                for row in batch.to_pylist():
                    values = tuple(row[name] for name in names)
                    exists = False
                    if operation == "write_upsert":
                        where = " AND ".join(
                            f"{_identifier(key, dialect)}={ph}"
                            for key, ph in zip(keys, _placeholders(dialect, len(keys)), strict=True)
                        )
                        hint = (
                            " WITH (UPDLOCK, HOLDLOCK)"
                            if dialect in {"sql_server", "synapse"}
                            else ""
                        )
                        suffix = (
                            " FOR UPDATE"
                            if dialect in {"postgresql", "mysql", "mariadb", "oracle"}
                            else ""
                        )
                        cursor.execute(
                            f"SELECT {'COUNT(*)' if dialect == 'redshift' else '1'} FROM {target}{hint} WHERE {where}{suffix}",
                            tuple(row[key] for key in keys),
                        )
                        match = cursor.fetchone()
                        if dialect == "redshift":
                            if match is None or int(match[0]) not in (0, 1):
                                raise AdapterError("CONNECTOR_UPSERT_NON_UNIQUE_TARGET")
                            exists = int(match[0]) == 1
                        else:
                            exists = match is not None
                    if exists:
                        assignments = ", ".join(
                            f"{name}={ph}"
                            for name, ph in zip(
                                columns, _placeholders(dialect, len(names)), strict=True
                            )
                        )
                        where = " AND ".join(
                            f"{_identifier(key, dialect)}={ph}"
                            for key, ph in zip(
                                keys, _placeholders(dialect, len(keys), len(names) + 1), strict=True
                            )
                        )
                        cursor.execute(
                            f"UPDATE {target} SET {assignments} WHERE {where}",
                            values + tuple(row[key] for key in keys),
                        )
                        if cursor.rowcount != 1:
                            raise AdapterError("CONNECTOR_UPSERT_NON_UNIQUE_TARGET")
                        updated += 1
                    else:
                        cursor.execute(insert, values)
                        if cursor.rowcount != 1:
                            raise AdapterError("CONNECTOR_WRITE_COUNT_MISMATCH")
                        inserted += 1
                    if dialect == "redshift" and operation == "write_upsert":
                        predicate = " AND ".join(
                            f"{_identifier(key, dialect)}={ph}"
                            for key, ph in zip(keys, _placeholders(dialect, len(keys)), strict=True)
                        )
                        cursor.execute(
                            f"SELECT COUNT(*) FROM {target} WHERE {predicate}",
                            tuple(row[key] for key in keys),
                        )
                        if cursor.fetchone()[0] != 1:
                            raise AdapterError("CONNECTOR_UPSERT_NON_UNIQUE_TARGET")
            if dialect == "redshift":
                cursor.execute(f"SELECT COUNT(*) FROM {target}")
                if int(cursor.fetchone()[0]) != target_rows_before + inserted:
                    raise AdapterError("CONNECTOR_WRITE_COUNT_MISMATCH")
            receipt = {
                "operation_id": operation_id,
                "applied": True,
                "inserted": inserted,
                "updated": updated,
                "row_count": count,
                "contract_digest": execution["contract_digest"],
                "input_sha256": execution["input_sha256"],
                "outcome_check": "marker_table",
            }
            fields = ["operation_id", "contract_digest", "input_sha256", "receipt_json"]
            cursor.execute(
                f"INSERT INTO {marker} ({', '.join(_identifier(name, dialect) for name in fields)}) VALUES ({', '.join(_placeholders(dialect, 4))})",
                (
                    operation_id,
                    execution["contract_digest"],
                    execution["input_sha256"],
                    json.dumps(receipt),
                ),
            )
            if dialect == "redshift":
                if cursor.rowcount != 1:
                    raise AdapterError("CONNECTOR_WRITE_COUNT_MISMATCH")
                cursor.execute(
                    f"SELECT {_identifier('contract_digest', dialect)}, {_identifier('input_sha256', dialect)}, {_identifier('receipt_json', dialect)} FROM {marker} WHERE {_identifier('operation_id', dialect)}=%s",
                    (operation_id,),
                )
                stored = cursor.fetchone()
                if (
                    stored is None
                    or cursor.fetchone() is not None
                    or tuple(stored[:2])
                    != (execution["contract_digest"], execution["input_sha256"])
                    or json.loads(stored[2]) != receipt
                ):
                    raise AdapterError("CONNECTOR_RECEIPT_INVALID")
            _remaining(deadline_at)
            connection.commit()
            return receipt
        finally:
            cursor.close()


def reconcile(config, credentials, deadline_at, *, dialect, marker, execution):
    with _connection(dialect, config, credentials, deadline_at) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"SELECT {_identifier('contract_digest', dialect)}, {_identifier('input_sha256', dialect)}, {_identifier('receipt_json', dialect)} FROM {marker} WHERE {_identifier('operation_id', dialect)}={_placeholders(dialect, 1)[0]}",
                (execution["operation_id"],),
            )
            existing = cursor.fetchone()
            if dialect == "redshift" and cursor.fetchone() is not None:
                raise AdapterError("CONNECTOR_MARKER_NON_UNIQUE")
            if not existing:
                # Absence is not an authorization to replay: a transaction may
                # still be finishing remotely after loss of the client.
                return {
                    "operation_id": execution["operation_id"],
                    "applied": False,
                    "outcome": "unknown",
                }
            if (
                existing[0] != execution["contract_digest"]
                or existing[1] != execution["input_sha256"]
            ):
                raise AdapterError("CONNECTOR_IDEMPOTENCY_CONFLICT")
            receipt = json.loads(
                existing[2].read() if hasattr(existing[2], "read") else existing[2]
            )
            if dialect == "redshift" and any(
                receipt.get(key) != execution[key]
                for key in ("operation_id", "contract_digest", "input_sha256")
            ):
                raise AdapterError("CONNECTOR_RECEIPT_INVALID")
            if dialect == "redshift" and receipt.get("applied") is not True:
                raise AdapterError("CONNECTOR_RECEIPT_INVALID")
            return {
                **receipt,
                "reconciled": True,
            }
        finally:
            cursor.close()


def marker_table_ddl(dialect, schema):
    """Operator-visible prerequisite; this DDL is never executed by the adapter."""
    if dialect not in NATIVE_WRITERS | {"snowflake"}:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    text_type = (
        "CLOB"
        if dialect == "oracle"
        else "NVARCHAR(MAX)"
        if dialect in {"sql_server", "synapse"}
        else "VARCHAR(65535)"
        if dialect == "redshift"
        else "TEXT"
    )

    def identifier(name):
        return _identifier(name, dialect)

    return (
        f"CREATE TABLE {identifier(schema)}.{identifier('_agentium_operations')} ("
        + ", ".join(
            [
                f"{identifier('operation_id')} VARCHAR(36) {'NOT NULL' if dialect == 'redshift' else 'PRIMARY KEY'}",
                f"{identifier('contract_digest')} VARCHAR(64) NOT NULL",
                f"{identifier('input_sha256')} VARCHAR(64) NOT NULL",
                f"{identifier('receipt_json')} {text_type} NOT NULL",
            ]
        )
        + ")"
        + (" ENGINE=InnoDB" if dialect in {"mysql", "mariadb"} else "")
    )
