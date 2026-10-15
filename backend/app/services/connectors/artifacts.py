"""Common bounded connector stream -> Parquet contract, before publication."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.services.connectors.adapters.sql import AdapterError, _remaining


def decode_value(value):
    if isinstance(value, dict) and set(value) == {"type", "value"}:
        kind, text = value["type"], value["value"]
        if kind == "object" and isinstance(text, dict):
            return {key: decode_value(item) for key, item in text.items()}
        if not isinstance(text, str):
            raise AdapterError("CONNECTOR_ARTIFACT_INVALID")
        if kind == "decimal":
            return Decimal(text)
        if kind == "date":
            return date.fromisoformat(text)
        if kind == "datetime":
            return datetime.fromisoformat(text)
        if kind == "binary":
            return base64.b64decode(text, validate=True)
        if kind == "float":
            return float(text)
    if isinstance(value, list):
        return [decode_value(item) for item in value]
    if isinstance(value, dict):
        raise AdapterError("CONNECTOR_ARTIFACT_INVALID")
    return value


def _batches(source, columns, deadline_at):
    import pyarrow as pa

    batch, size = [], 0
    with source.open("rb") as handle:
        while line := handle.readline(8 * 1024 * 1024 + 1):
            _remaining(deadline_at)
            if len(line) > 8 * 1024 * 1024:
                raise AdapterError("CONNECTOR_VALUE_TOO_LARGE")
            values = json.loads(line)
            if not isinstance(values, list) or len(values) != len(columns):
                raise AdapterError("CONNECTOR_ARTIFACT_INVALID")
            batch.append(
                {column: decode_value(value) for column, value in zip(columns, values, strict=True)}
            )
            size += len(line)
            if len(batch) >= 1000 or size >= 16 * 1024 * 1024:
                yield pa.Table.from_pylist(batch)
                batch, size = [], 0
        if batch:
            yield pa.Table.from_pylist(batch)


def parquet_artifact(output: dict, directory: Path, deadline_at: str) -> dict:
    """Two bounded passes infer a common schema, including leading null batches.

    Incompatible heterogeneous types fail closed. Decimal precision and null
    promotion are delegated to Arrow's permissive schema unification; value
    casts remain safe. No full table is collected in memory.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if output.get("format") != "typed-jsonl-v2":
        raise AdapterError("CONNECTOR_ARTIFACT_INVALID")
    columns = output.get("columns")
    if not isinstance(columns, list) or not columns or len(set(columns)) != len(columns):
        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
    source, target = directory / "rows.jsonl", directory / "data.parquet"
    schema = pa.schema([(name, pa.null()) for name in columns])
    rows = 0
    try:
        for batch in _batches(source, columns, deadline_at):
            schema = pa.unify_schemas([schema, batch.schema], promote_options="permissive")
            rows += batch.num_rows
        if rows != output.get("row_count"):
            raise AdapterError("CONNECTOR_ARTIFACT_INVALID")
        with pq.ParquetWriter(target, schema, compression="zstd") as writer:
            for batch in _batches(source, columns, deadline_at):
                writer.write_table(batch.cast(schema, safe=True))
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                _remaining(deadline_at)
                digest.update(block)
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("CONNECTOR_TYPE_UNSUPPORTED") from None
    return {
        **output,
        "artifact": "data.parquet",
        "format": "parquet",
        "bytes": target.stat().st_size,
        "sha256": digest.hexdigest(),
    }
