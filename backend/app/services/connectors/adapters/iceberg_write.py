"""Iceberg v2 writes through guarded object PUTs and the REST atomic commit.

The supported contract is an existing, unpartitioned table with primitive fields.
Upsert rewrites one bounded snapshot locally; historical files are never deleted.
No native library receives a URL, credentials or a catalog connection.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
import time
from pathlib import Path
from uuid import UUID, uuid4

from app.services.connectors.adapters import http
from app.services.connectors.adapters.lakehouse import (
    MAX_BYTES,
    MAX_OBJECTS,
    Catalog,
    _iceberg,
    _iceberg_client,
    _iceberg_location,
    _url,
)
from app.services.connectors.adapters.sql import AdapterError, _remaining
from app.services.connectors.adapters.sql_write import _execution


def _field(name, kind, number, *, default=...):
    result = {"name": name, "type": kind, "field-id": number}
    if default is not ...:
        result["default"] = default
    return result


PARTITION = {"type": "record", "name": "r102", "fields": []}
DATA_FILE = {
    "type": "record",
    "name": "r2",
    "fields": [
        _field("content", "int", 134),
        _field("file_path", "string", 100),
        _field("file_format", "string", 101),
        _field("partition", PARTITION, 102),
        _field("record_count", "long", 103),
        _field("file_size_in_bytes", "long", 104),
    ],
}
MANIFEST = {
    "type": "record",
    "name": "manifest_entry",
    "fields": [
        _field("status", "int", 0),
        _field("snapshot_id", ["null", "long"], 1, default=None),
        _field("sequence_number", ["null", "long"], 3, default=None),
        _field("file_sequence_number", ["null", "long"], 4, default=None),
        _field("data_file", DATA_FILE, 2),
    ],
}
MANIFEST_LIST = {
    "type": "record",
    "name": "manifest_file",
    "fields": [
        _field("manifest_path", "string", 500),
        _field("manifest_length", "long", 501),
        _field("partition_spec_id", "int", 502),
        _field("content", "int", 517),
        _field("sequence_number", "long", 515),
        _field("min_sequence_number", "long", 516),
        _field("added_snapshot_id", "long", 503),
        _field("added_files_count", "int", 504),
        _field("existing_files_count", "int", 505),
        _field("deleted_files_count", "int", 506),
        _field("added_rows_count", "long", 512),
        _field("existing_rows_count", "long", 513),
        _field("deleted_rows_count", "long", 514),
    ],
}


def _avro(schema, records, metadata):
    from fastavro import writer

    output = io.BytesIO()
    writer(output, schema, records, metadata={k: str(v) for k, v in metadata.items()})
    data = output.getvalue()
    if len(data) > 64 * 1024**2:
        raise AdapterError("CONNECTOR_EXPORT_PART_TOO_LARGE")
    return data


def _schema(columns):
    import pyarrow as pa

    primitives = {
        "boolean": pa.bool_(),
        "int": pa.int32(),
        "long": pa.int64(),
        "float": pa.float32(),
        "double": pa.float64(),
        "string": pa.string(),
        "binary": pa.binary(),
        "date": pa.date32(),
        "time": pa.time64("us"),
        "timestamp": pa.timestamp("us"),
        "timestamptz": pa.timestamp("us", tz="UTC"),
    }
    fields = []
    for column in columns:
        kind = column["type"]
        datatype = primitives.get(kind)
        decimal = re.fullmatch(r"decimal\((\d+),\s*(\d+)\)", kind)
        fixed = re.fullmatch(r"fixed\[(\d+)\]", kind)
        if decimal:
            precision, scale = map(int, decimal.groups())
            if not 0 <= scale <= precision <= 38:
                raise AdapterError("CONNECTOR_ICEBERG_SCHEMA_UNSUPPORTED")
            datatype = pa.decimal128(precision, scale)
        elif fixed and 0 < int(fixed[1]) <= 65536:
            datatype = pa.binary(int(fixed[1]))
        if datatype is None:
            raise AdapterError("CONNECTOR_ICEBERG_SCHEMA_UNSUPPORTED")
        fields.append(
            pa.field(
                column["name"],
                datatype,
                nullable=not column.get("required", False),
                metadata={b"PARQUET:field_id": str(column["id"]).encode()},
            )
        )
    return pa.schema(fields)


def _batches(paths, schema, deadline, *, field_ids=False, columns=None):
    import pyarrow as pa
    import pyarrow.parquet as pq

    for path in paths:
        with pq.ParquetFile(path) as parquet:
            names = {field.name: field.name for field in parquet.schema_arrow}
            if field_ids:
                by_id = {}
                for field in parquet.schema_arrow:
                    try:
                        number = int((field.metadata or {})[b"PARQUET:field_id"])
                    except (KeyError, ValueError):
                        raise AdapterError("CONNECTOR_ICEBERG_FIELD_IDS_REQUIRED") from None
                    if number in by_id:
                        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                    by_id[number] = field.name
                names = {
                    field.name: by_id.get(int(field.metadata[b"PARQUET:field_id"]))
                    for field in schema
                }
            elif columns is not None and (
                set(columns) != set(schema.names) or len(columns) != len(schema)
            ):
                raise AdapterError("CONNECTOR_COLUMNS_INVALID")
            if not field_ids and set(parquet.schema_arrow.names) != set(schema.names):
                raise AdapterError("CONNECTOR_SCHEMA_CHANGED")
            for batch in parquet.iter_batches(batch_size=1000, use_threads=False):
                _remaining(deadline)
                if batch.nbytes > 64 * 1024**2:
                    raise AdapterError("CONNECTOR_EXPORT_PART_TOO_LARGE")
                arrays = []
                for field in schema:
                    source = names.get(field.name)
                    if source is None:
                        values = pa.nulls(batch.num_rows, type=field.type)
                    else:
                        try:
                            values = batch.column(source).cast(field.type, safe=True)
                        except (pa.ArrowException, KeyError):
                            raise AdapterError("CONNECTOR_SCHEMA_CHANGED") from None
                    if not field.nullable and values.null_count:
                        raise AdapterError("CONNECTOR_SCHEMA_CHANGED")
                    arrays.append(values)
                yield pa.RecordBatch.from_arrays(arrays, schema=schema)


def _assert_destination(metadata, parameters, *, reconciliation=False):
    try:
        table_uuid = str(UUID(metadata["table-uuid"]))
    except (KeyError, ValueError):
        raise AdapterError("CONNECTOR_SCHEMA_INVALID") from None
    if table_uuid != parameters.get("expected_table_uuid"):
        raise AdapterError("CONNECTOR_SOURCE_CHANGED")
    if not reconciliation and (
        type(parameters.get("expected_schema_id")) is not int
        or metadata.get("current-schema-id") != parameters["expected_schema_id"]
    ):
        raise AdapterError("CONNECTOR_SOURCE_CHANGED")
    if not reconciliation:
        expected = parameters.get("expected_snapshot_id")
        if isinstance(expected, str) and re.fullmatch(r"[1-9][0-9]{0,18}", expected):
            expected = int(expected)
        if expected is not None and (type(expected) is not int or not 0 < expected < 2**63):
            raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
        actual = metadata.get("current-snapshot-id")
        actual = None if actual == -1 else actual
        if "expected_snapshot_id" not in parameters or expected != actual:
            raise AdapterError("CONNECTOR_SOURCE_CHANGED")


def _receipt(metadata, execution):
    found = []
    for snapshot in metadata.get("snapshots", []):
        summary = snapshot.get("summary", {})
        if summary.get("agentium.operation-id") == execution["operation_id"]:
            if summary.get("agentium.contract-digest") != execution["contract_digest"]:
                raise AdapterError("CONNECTOR_RECEIPT_MISMATCH")
            found.append(snapshot)
    if len(found) > 1:
        raise AdapterError("CONNECTOR_RECEIPT_MISMATCH")
    if not found:
        return None
    snapshot = found[0]
    return {
        "operation_id": execution["operation_id"],
        "contract_digest": execution["contract_digest"],
        "applied": True,
        "snapshot_id": str(snapshot["snapshot-id"]),
        "table_uuid": metadata["table-uuid"],
        "row_count": int(snapshot["summary"]["agentium.input-rows"]),
        "source": "real",
        "outcome_check": "snapshot_summary",
    }


def _put(catalog, storage_config, location, data):
    # Deriving a write URL from an HTTPS download link is never authorized.
    # Cloud clients require temporary credentials and check every signed host.
    client = _iceberg_client(location, catalog, storage_config)
    client.put(client.root, data)


def _commit(catalog, path, body):
    payload = json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
    with http.response(
        "POST",
        _url(catalog.config, catalog.base + path),
        headers={**catalog.headers, "Content-Type": "application/json"},
        content=payload,
        deadline_at=catalog.deadline,
    ) as reply:
        if reply.status_code != 200:
            raise AdapterError("CONNECTOR_WRITE_OUTCOME_UNKNOWN")
        chunks, size = [], 0
        for chunk in reply.iter_bytes():
            _remaining(catalog.deadline)
            size += len(chunk)
            if size > 16 * 1024**2:
                raise AdapterError("CONNECTOR_RESPONSE_TOO_LARGE")
            chunks.append(chunk)
        try:
            result = json.loads(b"".join(chunks))
        except ValueError:
            raise AdapterError("CONNECTOR_RESPONSE_INVALID") from None
    return result


def execute_write(
    operation, config, credentials, parameters, deadline_at, output_dir, *, access, execution
):
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not access or access.get("mode") != "read_write":
        raise AdapterError("CONNECTOR_READ_ONLY")
    if set(parameters) - {
        "schema",
        "table",
        "columns",
        "keys",
        "create_table",
        "expected_snapshot_id",
        "expected_table_uuid",
        "expected_schema_id",
    }:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    if parameters.get("create_table"):
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    paths = _execution(execution, require_files=operation != "reconcile_write")
    catalog = Catalog(config, credentials, deadline_at)
    directory = Path(output_dir)
    snapshot = _iceberg(
        catalog,
        "table",
        parameters,
        directory,
        access,
        {"max_bytes": MAX_BYTES},
        return_snapshot="metadata" if operation == "reconcile_write" else True,
    )
    metadata = snapshot["metadata"]
    _assert_destination(metadata, parameters, reconciliation=operation == "reconcile_write")
    if operation == "reconcile_write":
        return _receipt(metadata, execution) or {
            "operation_id": execution["operation_id"],
            "applied": None,
            "outcome": "unknown",
        }
    columns = snapshot["columns"]
    spec_id = metadata.get("default-spec-id")
    spec = next(
        (s for s in metadata.get("partition-specs", []) if s.get("spec-id") == spec_id), None
    )
    sort = next(
        (
            s
            for s in metadata.get("sort-orders", [])
            if s.get("order-id") == metadata.get("default-sort-order-id")
        ),
        None,
    )
    if (
        metadata.get("format-version") != 2
        or not spec
        or spec.get("fields") != []
        or (sort and sort.get("fields"))
        or metadata.get("default-sort-order-id", 0) != 0
        or any(m.get("partition_spec_id") != spec_id for m in snapshot["manifests"])
    ):
        raise AdapterError("CONNECTOR_ICEBERG_FEATURE_UNSUPPORTED")
    if _receipt(metadata, execution):
        raise AdapterError("CONNECTOR_WRITE_ALREADY_APPLIED")
    schema = _schema(columns)
    actual_operation = (
        execution.get("write_operation") if operation == "write_preview" else operation
    )
    if actual_operation not in {"write_append", "write_overwrite", "write_upsert"}:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    keys = parameters.get("keys", [])
    if actual_operation == "write_upsert" and (
        not isinstance(keys, list)
        or not keys
        or len(set(keys)) != len(keys)
        or set(keys) - set(schema.names)
    ):
        raise AdapterError("CONNECTOR_UPSERT_KEY_REQUIRED")
    input_bytes = sum(path.stat().st_size for path in paths)
    if input_bytes > MAX_BYTES:
        raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
    keydb = sqlite3.connect(directory / "iceberg-keys.sqlite")
    local_parts, input_count, total_bytes, key_bytes = [], 0, 0, 0

    def key_for(row):
        nonlocal key_bytes
        values = [row[k] for k in keys]
        if any(
            v is None or (isinstance(v, float) and not __import__("math").isfinite(v))
            for v in values
        ):
            raise AdapterError("CONNECTOR_UPSERT_NULL_KEY")
        encoded = repr(values)
        key_bytes += len(encoded.encode())
        if key_bytes > MAX_BYTES:
            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        return encoded

    def save(batch):
        nonlocal total_bytes
        if not batch.num_rows:
            return
        _remaining(deadline_at)
        path = directory / f"iceberg-new-{len(local_parts)}.parquet"
        pq.write_table(pa.Table.from_batches([batch]), path, compression="snappy")
        size = path.stat().st_size
        total_bytes += size
        if size > 64 * 1024**2 or total_bytes > MAX_BYTES or len(local_parts) >= MAX_OBJECTS:
            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        local_parts.append((path, batch.num_rows, size))

    try:
        keydb.execute("CREATE TABLE incoming (key TEXT PRIMARY KEY)")
        keydb.execute("CREATE TABLE existing (key TEXT PRIMARY KEY)")
        for batch in _batches(paths, schema, deadline_at, columns=parameters.get("columns")):
            input_count += batch.num_rows
            if input_count > 10_000_000:
                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
            if actual_operation == "write_upsert":
                for row in batch.to_pylist():
                    try:
                        keydb.execute("INSERT INTO incoming VALUES (?)", (key_for(row),))
                    except sqlite3.IntegrityError:
                        raise AdapterError("CONNECTOR_UPSERT_DUPLICATE_KEY") from None
            save(batch)
        if actual_operation == "write_upsert":
            downloaded = snapshot["downloaded"] + input_bytes
            old_count = 0
            for index, item in enumerate(snapshot["files"]):
                downloaded += item["size"]
                if downloaded > MAX_BYTES:
                    raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                path = directory / f"iceberg-old-{index}.parquet"
                _, size, _ = _iceberg_location(
                    item["url"], catalog, snapshot["storage_config"], path, item["size"]
                )
                if size != item["size"]:
                    raise AdapterError("CONNECTOR_SOURCE_CHANGED")
                try:
                    for batch in _batches([path], schema, deadline_at, field_ids=True):
                        retained = []
                        old_count += batch.num_rows
                        if old_count > 10_000_000:
                            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                        for row in batch.to_pylist():
                            key = key_for(row)
                            try:
                                keydb.execute("INSERT INTO existing VALUES (?)", (key,))
                            except sqlite3.IntegrityError:
                                raise AdapterError("CONNECTOR_UPSERT_DUPLICATE_KEY") from None
                            if not keydb.execute(
                                "SELECT 1 FROM incoming WHERE key=?", (key,)
                            ).fetchone():
                                retained.append(row)
                        if retained:
                            save(pa.RecordBatch.from_pylist(retained, schema=schema))
                finally:
                    path.unlink(missing_ok=True)
    finally:
        keydb.close()
    if operation == "write_preview":
        return {
            "source": "real",
            "operation_id": execution["operation_id"],
            "contract_digest": execution["contract_digest"],
            "dry_run": True,
            "applied": False,
            "write_operation": actual_operation,
            "input_rows": input_count,
            "output_rows": sum(p[1] for p in local_parts),
            "expected_snapshot_id": parameters["expected_snapshot_id"],
            "expected_table_uuid": metadata["table-uuid"],
            "expected_schema_id": metadata["current-schema-id"],
        }
    location = metadata.get("location", "").rstrip("/")
    # Validate the future upload root before publishing the first object.
    _iceberg_client(location + "/metadata/agentium", catalog, snapshot["storage_config"])
    operation_id = str(UUID(execution["operation_id"]))
    snapshot_id = uuid4().int & ((1 << 63) - 1)
    sequence = metadata["last-sequence-number"] + 1
    entries = []
    for index, (path, rows, size) in enumerate(local_parts):
        file_path = f"{location}/data/agentium-{operation_id}-{index:06d}.parquet"
        _put(catalog, snapshot["storage_config"], file_path, path.read_bytes())
        entries.append(
            {
                "status": 1,
                "snapshot_id": snapshot_id,
                "sequence_number": sequence,
                "file_sequence_number": sequence,
                "data_file": {
                    "content": 0,
                    "file_path": file_path,
                    "file_format": "PARQUET",
                    "partition": {},
                    "record_count": rows,
                    "file_size_in_bytes": size,
                },
            }
        )
    current_schema = next(
        s for s in metadata["schemas"] if s["schema-id"] == metadata["current-schema-id"]
    )
    manifest_metadata = {
        "schema": json.dumps(current_schema),
        "partition-spec": "[]",
        "partition-spec-id": spec_id,
        "format-version": 2,
        "content": "data",
    }
    manifest = _avro(MANIFEST, entries, manifest_metadata)
    manifest_path = f"{location}/metadata/agentium-{operation_id}-manifest.avro"
    _put(catalog, snapshot["storage_config"], manifest_path, manifest)
    retained = snapshot["manifests"] if actual_operation == "write_append" else []
    manifest_record = {
        "manifest_path": manifest_path,
        "manifest_length": len(manifest),
        "partition_spec_id": spec_id,
        "content": 0,
        "sequence_number": sequence,
        "min_sequence_number": sequence,
        "added_snapshot_id": snapshot_id,
        "added_files_count": len(entries),
        "existing_files_count": 0,
        "deleted_files_count": 0,
        "added_rows_count": sum(p[1] for p in local_parts),
        "existing_rows_count": 0,
        "deleted_rows_count": 0,
    }
    parent = metadata.get("current-snapshot-id")
    manifest_list = _avro(
        MANIFEST_LIST,
        [*retained, manifest_record],
        {
            "snapshot-id": snapshot_id,
            "parent-snapshot-id": parent if parent not in (None, -1) else "null",
            "sequence-number": sequence,
            "format-version": 2,
        },
    )
    list_path = f"{location}/metadata/agentium-{operation_id}-list.avro"
    _put(catalog, snapshot["storage_config"], list_path, manifest_list)
    next_snapshot = {
        "snapshot-id": snapshot_id,
        "sequence-number": sequence,
        "timestamp-ms": int(time.time() * 1000),
        "manifest-list": list_path,
        "schema-id": metadata["current-schema-id"],
        "summary": {
            "operation": "append" if actual_operation == "write_append" else "overwrite",
            "agentium.operation-id": operation_id,
            "agentium.contract-digest": execution["contract_digest"],
            "agentium.input-rows": str(input_count),
        },
    }
    if parent not in (None, -1):
        next_snapshot["parent-snapshot-id"] = parent
    body = {
        "requirements": [
            {"type": "assert-table-uuid", "uuid": metadata["table-uuid"]},
            {
                "type": "assert-ref-snapshot-id",
                "ref": "main",
                "snapshot-id": parent if parent != -1 else None,
            },
            {
                "type": "assert-current-schema-id",
                "current-schema-id": metadata["current-schema-id"],
            },
            {"type": "assert-default-spec-id", "default-spec-id": spec_id},
            {
                "type": "assert-default-sort-order-id",
                "default-sort-order-id": metadata.get("default-sort-order-id", 0),
            },
        ],
        "updates": [
            {"action": "add-snapshot", "snapshot": next_snapshot},
            {
                "action": "set-snapshot-ref",
                "ref-name": "main",
                "type": "branch",
                "snapshot-id": snapshot_id,
            },
        ],
    }
    result = _commit(catalog, snapshot["table_path"], body)
    receipt = _receipt(result.get("metadata", {}), execution)
    if not receipt or result["metadata"].get("table-uuid") != metadata["table-uuid"]:
        raise AdapterError("CONNECTOR_WRITE_OUTCOME_UNKNOWN")
    return receipt
