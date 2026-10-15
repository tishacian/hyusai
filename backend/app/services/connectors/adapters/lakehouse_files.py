"""Read snapshot Parquet files locally after guarded, bounded downloads.

No native reader sees a remote URL or credentials. Source receipts contain
opaque file identities and content digests, never presigned URLs or SAS tokens.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.services.connectors.adapters.sql import AdapterError, _json_value, _remaining, _typed_value


def stage_files(
    files,
    columns,
    directory,
    *,
    download,
    operation,
    max_rows,
    max_bytes,
    deadline,
    preview_limit,
    snapshot,
    iceberg=False,
):
    import pyarrow.parquet as pq

    directory = Path(directory)
    seen, sources, preview = set(), [], []
    count = written = downloaded = 0
    digest = hashlib.sha256()
    artifact = directory / "rows.jsonl"
    with artifact.open("xb") as output:
        for index, item in enumerate(files):
            _remaining(deadline)
            if item["id"] in seen or type(item["size"]) is not int or item["size"] < 0:
                raise AdapterError("CONNECTOR_SOURCE_IDENTITY_INVALID")
            seen.add(item["id"])
            downloaded += item["size"]
            if downloaded > max_bytes:
                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
            path = directory / f"part-{index}.parquet"
            _, size, sha = download(item, path, min(item["size"], max_bytes))
            if size != item["size"]:
                raise AdapterError("CONNECTOR_SOURCE_CHANGED")
            sources.append(
                {
                    "id": item["id"],
                    "size": size,
                    "sha256": sha,
                    **({"partition_values": item["partitions"]} if "partitions" in item else {}),
                }
            )
            try:
                with pq.ParquetFile(path) as parquet:
                    names = parquet.schema_arrow.names
                    if len(names) != len(set(names)):
                        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                    by_id = {}
                    if iceberg:
                        for field in parquet.schema_arrow:
                            field_id = (field.metadata or {}).get(b"PARQUET:field_id")
                            if field_id is None:
                                raise AdapterError("CONNECTOR_ICEBERG_FIELD_IDS_REQUIRED")
                            try:
                                number = int(field_id)
                            except ValueError:
                                raise AdapterError("CONNECTOR_SCHEMA_INVALID") from None
                            if number in by_id:
                                raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                            by_id[number] = field.name
                    for batch in parquet.iter_batches(batch_size=1000, use_threads=False):
                        for row in batch.to_pylist():
                            _remaining(deadline)
                            values = []
                            for column in columns:
                                name = by_id.get(column["id"]) if iceberg else column["name"]
                                if name in row:
                                    value = row[name]
                                elif not iceberg and column["name"] in item.get("partitions", {}):
                                    value = partition_value(
                                        item["partitions"][column["name"]], column["type"]
                                    )
                                elif not column.get("required"):
                                    value = None
                                else:
                                    raise AdapterError("CONNECTOR_SCHEMA_CHANGED")
                                if value is None and column.get("required"):
                                    raise AdapterError("CONNECTOR_SCHEMA_CHANGED")
                                values.append(
                                    (
                                        _json_value
                                        if operation in ("preview", "table")
                                        else _typed_value
                                    )(value)
                                )
                            count += 1
                            if count > max_rows:
                                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                            data = (
                                json.dumps(values, ensure_ascii=False, allow_nan=False) + "\n"
                            ).encode()
                            written += len(data)
                            if written > max_bytes:
                                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                            if operation in ("preview", "table"):
                                preview.append(values)
                                if written > 4 * 1024 * 1024:
                                    raise AdapterError("CONNECTOR_PREVIEW_TOO_LARGE")
                                if count >= preview_limit:
                                    break
                            else:
                                output.write(data)
                                digest.update(data)
                        if operation in ("preview", "table") and count >= preview_limit:
                            break
            finally:
                path.unlink(missing_ok=True)
            if operation in ("preview", "table") and count >= preview_limit:
                break
    identity = {"snapshot": snapshot, "schema": columns, "files": sources}
    result = {
        "columns": [c["name"] for c in columns],
        "row_count": count,
        "source": "real",
        "consistency": "snapshot",
        "snapshot": snapshot,
        "source_objects": sources,
        "source_fingerprint": hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    if operation in ("preview", "table"):
        return {**result, "rows": preview}
    return {
        **result,
        "artifact": "rows.jsonl",
        "format": "typed-jsonl-v2",
        "bytes": written,
        "sha256": digest.hexdigest(),
    }


def partition_value(value, kind):
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterError("CONNECTOR_PARTITION_INVALID")
    try:
        if kind in ("byte", "short", "integer", "long"):
            return int(value)
        if kind in ("float", "double"):
            return float(value)
        if kind == "boolean":
            if value not in ("true", "false"):
                raise ValueError()
            return value == "true"
        if kind in ("string", "date", "timestamp", "timestamp_ntz") or kind.startswith("decimal("):
            return value
    except ValueError:
        pass
    raise AdapterError("CONNECTOR_PARTITION_INVALID")
