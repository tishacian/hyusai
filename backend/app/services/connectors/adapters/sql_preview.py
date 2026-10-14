"""Server-side read-only write preview bound to the same approved input bytes."""

from __future__ import annotations

import sqlite3

from app.services.connectors.adapters.sql import (
    AdapterError,
    _columns_sql,
    _connection,
    _identifier,
    _remaining,
    _scope,
    _target,
)
from app.services.connectors.adapters.sql_write import _batches, _execution, _placeholders


def preview_write(
    config, credentials, parameters, deadline_at, output_dir, *, dialect, access, execution
):
    paths = _execution(execution)
    operation = execution.get("write_operation")
    if (
        operation not in {"write_append", "write_overwrite", "write_upsert"}
        or config.get("demo_mode")
        or parameters.get("create_table")
    ):
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {"schema", "table", "columns", "keys", "create_table"}:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    if dialect in {"snowflake", "bigquery", "databricks_sql"}:
        from app.services.connectors.adapters.sql_cloud_write import _source

        # The cloud writer has a bounded inline staging contract. An oversized
        # source must fail here, before an operator can approve an impossible run.
        _source(paths, parameters, dialect)
    schema, table = parameters.get("schema"), parameters.get("table")
    _scope(schema, table, access)
    target = _target(dialect, config, schema, table)
    names, batches = _batches(paths, parameters.get("columns"))
    keys = parameters.get("keys") or []
    if operation == "write_upsert" and (
        not isinstance(keys, list)
        or not keys
        or any(not isinstance(key, str) for key in keys)
        or len(set(keys)) != len(keys)
        or set(keys) - set(names)
    ):
        raise AdapterError("CONNECTOR_UPSERT_KEY_REQUIRED")
    with _connection(dialect, config, credentials, deadline_at, read_only=True) as connection:
        cursor = connection.cursor()
        uniqueness = sqlite3.connect(output_dir / "preview-keys.sqlite")
        try:
            statement, bindings = _columns_sql(dialect, config, schema, table)
            cursor.execute(statement, bindings)
            columns = cursor.fetchmany(2001)
            if not columns or len(columns) > 2000:
                raise AdapterError("CONNECTOR_SCHEMA_INVALID")
            metadata = {
                name: {
                    "name": name,
                    "type": str(dtype),
                    "nullable": nullable in (True, "YES", "Y", "TRUE"),
                }
                for name, dtype, nullable in columns
            }
            if set(names) - set(metadata):
                raise AdapterError("CONNECTOR_SCHEMA_MISMATCH")
            cursor.execute(f"SELECT COUNT(*) FROM {target}")
            target_rows = int(cursor.fetchone()[0])
            inserted = updated = count = 0
            uniqueness.execute("CREATE TABLE keys (value TEXT PRIMARY KEY)")
            for batch in batches:
                _remaining(deadline_at)
                for row in batch.to_pylist():
                    count += 1
                    if count > 10_000_000:
                        raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                    if any(row[name] is None and not metadata[name]["nullable"] for name in names):
                        raise AdapterError("CONNECTOR_NON_NULL_REQUIRED")
                    existing = 0
                    if operation == "write_upsert":
                        values = tuple(row[key] for key in keys)
                        if any(value is None for value in values):
                            raise AdapterError("CONNECTOR_UPSERT_NULL_KEY")
                        try:
                            uniqueness.execute("INSERT INTO keys VALUES (?)", (repr(values),))
                        except sqlite3.IntegrityError:
                            raise AdapterError("CONNECTOR_UPSERT_DUPLICATE_KEY") from None
                        placeholders = (
                            ["?"] * len(keys)
                            if dialect == "hana"
                            else _placeholders(dialect, len(keys))
                        )
                        where = " AND ".join(
                            f"{_identifier(key, dialect)}={placeholder}"
                            for key, placeholder in zip(keys, placeholders, strict=True)
                        )
                        cursor.execute(f"SELECT COUNT(*) FROM {target} WHERE {where}", values)
                        existing = int(cursor.fetchone()[0])
                        if existing > 1:
                            raise AdapterError("CONNECTOR_UPSERT_NON_UNIQUE_TARGET")
                    inserted += existing == 0
                    updated += existing == 1
            return {
                "dry_run": True,
                "applied": False,
                "operation_id": execution["operation_id"],
                "contract_digest": execution["contract_digest"],
                "input_sha256": execution["input_sha256"],
                "write_operation": operation,
                "input_rows": count,
                "target_rows": target_rows,
                "inserted": inserted,
                "updated": updated,
                "deleted": target_rows if operation == "write_overwrite" else 0,
                "source_columns": names,
                "target_columns": list(metadata.values()),
                "missing_target_columns": sorted(set(metadata) - set(names)),
                "consistency": "none",
                "counts_are_estimates": True,
            }
        finally:
            cursor.close()
            uniqueness.close()
