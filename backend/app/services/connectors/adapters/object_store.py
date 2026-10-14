"""Frozen object-set imports, bounded previews and immutable object exports."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from app.services.connectors.adapters.object_clients import client_for, object_key
from app.services.connectors.adapters.sql import AdapterError, _json_value, _remaining, _typed_value

MAX_IMPORT_BYTES = 1024 * 1024 * 1024
MAX_OBJECTS = 10000


def _bounded_int(parameters, name, default, maximum):
    value = parameters.get(name, default)
    if type(value) is not int or not 1 <= value <= maximum:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    return value


def _snapshot(client, prefix, max_objects, max_bytes, deadline):
    cursor, seen, rows, size = None, set(), [], 0
    while True:
        _remaining(deadline)
        batch, next_cursor = client.list_page(prefix, cursor)
        for item in batch:
            if not item.get("etag") or item["key"] in seen:
                raise AdapterError("CONNECTOR_OBJECT_IDENTITY_INVALID")
            seen.add(item["key"])
            size += item["size"]
            rows.append(item)
            if len(rows) > max_objects or size > max_bytes:
                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        if next_cursor is None:
            break
        if next_cursor == cursor or next_cursor in seen:
            raise AdapterError("CONNECTOR_PAGINATION_INVALID")
        # Separate cursor tracking from keys so malicious cyclic listings stop.
        marker = "cursor:" + next_cursor
        if marker in seen:
            raise AdapterError("CONNECTOR_PAGINATION_INVALID")
        seen.add(marker)
        cursor = next_cursor
    return sorted(rows, key=lambda item: item["key"])


def iter_rows(path, filename):
    suffix = Path(filename).suffix.lower()
    if suffix == ".parquet":
        import pyarrow.parquet as pq

        with pq.ParquetFile(path) as reader:
            for batch in reader.iter_batches(batch_size=1000):
                yield from batch.to_pylist()
    elif suffix in (".csv", ".tsv"):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t" if suffix == ".tsv" else ",")
            if (
                not reader.fieldnames
                or len(reader.fieldnames) != len(set(reader.fieldnames))
                or len(reader.fieldnames) > 2000
            ):
                raise AdapterError("CONNECTOR_SCHEMA_INVALID")
            for row in reader:
                if None in row:
                    raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                yield row
    elif suffix in (".ndjson", ".jsonl"):
        with path.open(encoding="utf-8") as handle:
            while line := handle.readline(4 * 1024 * 1024 + 1):
                if len(line) > 4 * 1024 * 1024:
                    raise AdapterError("CONNECTOR_ROW_TOO_LARGE")
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                    yield row
    elif suffix == ".json":
        # Stream an array of objects. ijson is runner-only; never json.load a
        # remote file of unbounded size into the backend process.
        import ijson

        with path.open("rb") as handle:
            first = handle.read(1)
            while first and first.isspace():
                first = handle.read(1)
            if first != b"[":
                raise AdapterError("CONNECTOR_SCHEMA_INVALID")
            handle.seek(0)
            for row in ijson.items(handle, "item"):
                if not isinstance(row, dict):
                    raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                yield row
    elif suffix == ".xlsx":
        from zipfile import ZipFile

        import openpyxl

        with ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_IMPORT_BYTES:
                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        book = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            for sheet in book.worksheets:
                iterator = sheet.iter_rows(values_only=True)
                names = next(iterator, None)
                if names is None:
                    continue
                if (
                    len(names) > 2000
                    or not all(isinstance(name, str) and name for name in names)
                    or len(names) != len(set(names))
                ):
                    raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                for values in iterator:
                    yield dict(zip(names, values, strict=True))
        finally:
            book.close()
    else:
        raise AdapterError("CONNECTOR_FILE_FORMAT_UNSUPPORTED")


def _stage(client, objects, directory, *, operation, max_rows, max_bytes, deadline, preview_limit):
    schema, count, size = None, 0, 0
    digest, preview = hashlib.sha256(), []
    artifact = directory / "rows.jsonl"
    sources = []
    with artifact.open("xb") as out:
        for index, item in enumerate(objects):
            _remaining(deadline)
            local = directory / f"object-{index}"
            _, actual_size, source_digest = client.download(item, local, max_bytes)
            if item.get("expected_sha256") and source_digest != item["expected_sha256"]:
                raise AdapterError("CONNECTOR_SOURCE_CHANGED")
            sources.append({**item, "sha256": source_digest})
            try:
                for row in iter_rows(local, item["key"]):
                    _remaining(deadline)
                    names = sorted(row)
                    if len(names) > 2000 or not all(
                        isinstance(name, str) and name for name in names
                    ):
                        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                    if schema is None:
                        schema = names
                    if names != schema:
                        raise AdapterError("CONNECTOR_SCHEMA_CHANGED")
                    values = [
                        (_json_value if operation in ("preview", "table") else _typed_value)(
                            row[name]
                        )
                        for name in schema
                    ]
                    count += 1
                    if count > max_rows:
                        raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                    if operation in ("preview", "table"):
                        preview.append(values)
                        if len(json.dumps(preview, allow_nan=False).encode()) > 4 * 1024 * 1024:
                            raise AdapterError("CONNECTOR_PREVIEW_TOO_LARGE")
                        if count >= preview_limit:
                            break
                    else:
                        data = (
                            json.dumps(values, allow_nan=False, ensure_ascii=False) + "\n"
                        ).encode()
                        size += len(data)
                        if size > max_bytes:
                            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                        out.write(data)
                        digest.update(data)
            finally:
                local.unlink(missing_ok=True)
            if operation in ("preview", "table") and count >= preview_limit:
                break
    fingerprint = hashlib.sha256(
        json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result = {
        "columns": schema or [],
        "row_count": count,
        "source": "real",
        "consistency": "snapshot"
        if sources
        and all(item.get("etag") and not str(item["etag"]).startswith("W/") for item in sources)
        else "none",
        "source_objects": sources,
        "source_fingerprint": fingerprint,
    }
    if operation in ("preview", "table"):
        return {**result, "rows": preview}
    return {
        **result,
        "artifact": "rows.jsonl",
        "format": "typed-jsonl-v2",
        "bytes": size,
        "sha256": digest.hexdigest(),
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
    if operation == "export" and (access or {}).get("mode") != "read_write":
        raise AdapterError("CONNECTOR_READ_ONLY")
    if operation in ("export", "reconcile_write") and parameters.get("format") == "delta":
        from app.services.connectors.adapters import delta_export

        fn = delta_export.execute if operation == "export" else delta_export.reconcile
        return fn(
            config,
            credentials,
            parameters,
            deadline_at,
            output_dir,
            dialect=dialect,
            execution=execution,
        )
    if operation == "reconcile_write":
        from app.services.connectors.adapters.object_export import reconcile

        if not execution:
            raise AdapterError("CONNECTOR_APPROVAL_REQUIRED")
        return reconcile(
            config,
            credentials,
            parameters,
            deadline_at,
            dialect=dialect,
            operation_id=execution["operation_id"],
        )
    if operation == "export":
        from app.services.connectors.adapters.object_export import execute as export

        return export(
            config, credentials, parameters, deadline_at, dialect=dialect, execution=execution
        )
    if dialect in ("http_files", "sharepoint_files", "onedrive"):
        from app.services.connectors.adapters.file_http import execute as file_execute

        return file_execute(
            operation,
            config,
            credentials,
            parameters,
            deadline_at,
            output_dir,
            dialect=dialect,
            access=access,
            limits=limits,
        )
    if operation not in ("test", "catalog", "list", "table", "preview", "import", "watch"):
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {
        "prefix",
        "key",
        "cursor",
        "limit",
        "max_rows",
        "max_bytes",
        "max_objects",
        "previous_fingerprint",
    }:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    client = client_for(dialect, config, credentials, deadline_at)
    prefix = object_key(
        parameters.get("prefix", config.get("prefix", "")), config.get("prefix", "")
    )
    max_bytes = _bounded_int(parameters, "max_bytes", MAX_IMPORT_BYTES, MAX_IMPORT_BYTES)
    max_rows = _bounded_int(parameters, "max_rows", 3_000_000, 10_000_000)
    max_objects = _bounded_int(parameters, "max_objects", 1000, MAX_OBJECTS)
    limit = _bounded_int(
        parameters, "limit", 100, min(1000, (limits or {}).get("preview_rows", 100))
    )
    if operation in ("test", "catalog", "list"):
        objects, cursor = client.list_page(prefix, parameters.get("cursor"))
        return {"connected": True, "objects": objects, "next_cursor": cursor, "source": "real"}
    key = parameters.get("key")
    if key is not None:
        key = object_key(key, config.get("prefix", ""))
        prefix = key
    objects = _snapshot(client, prefix, max_objects, 2**63 - 1, deadline_at)
    if operation != "watch" and key is None:
        from app.services.connectors.adapters.object_manifest import published_objects

        published = published_objects(client, prefix, objects)
        if published is not None:
            objects = published
    if sum(item["size"] for item in objects) > max_bytes:
        raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
    if key is not None:
        objects = [item for item in objects if item["key"] == key]
        if not objects:
            raise AdapterError("CONNECTOR_SOURCE_NOT_FOUND")
    if any("/_delta_log/" in "/" + item["key"] for item in objects) and operation != "watch":
        from app.services.connectors.adapters.delta_reader import stage_delta

        return stage_delta(
            client,
            objects,
            output_dir,
            operation=operation,
            max_rows=max_rows,
            max_bytes=max_bytes,
            deadline=deadline_at,
            preview_limit=limit,
        )
    if any(item["key"].endswith(".metadata.json") for item in objects) and operation != "watch":
        raise AdapterError("CONNECTOR_TABLE_FORMAT_REQUIRES_NATIVE_READER")
    fingerprint = hashlib.sha256(
        json.dumps(objects, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if operation == "watch":
        return {
            "objects": objects,
            "source_fingerprint": fingerprint,
            "changed": parameters.get("previous_fingerprint") != fingerprint,
            "source": "real",
        }
    if not objects:
        raise AdapterError("CONNECTOR_SOURCE_NOT_FOUND")
    return _stage(
        client,
        objects,
        output_dir,
        operation=operation,
        max_rows=max_rows,
        max_bytes=max_bytes,
        deadline=deadline_at,
        preview_limit=limit,
    )
