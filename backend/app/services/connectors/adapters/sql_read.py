"""Fixed integer partitions and bounded incremental windows on generated SQL.

Bounds are read once by the runner. A server checkpoint is never accepted from
public parameters; its advancement belongs to the dataset publication transaction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

from app.services.connectors.adapters.sql import (
    AdapterError,
    _identifier,
    _limited,
    _remaining,
    _typed_value,
)


def _value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value != int(value):
            raise AdapterError("CONNECTOR_INCREMENTAL_TYPE_INVALID")
        return int(value)
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        return value
    raise AdapterError("CONNECTOR_INCREMENTAL_TYPE_INVALID")


def _watermark(value, kind):
    if kind == "integer":
        if isinstance(value, Decimal) and value == int(value):
            value = int(value)
        if type(value) is not int:
            raise AdapterError("CONNECTOR_INCREMENTAL_TYPE_INVALID")
        return value
    if kind != "timestamp":
        raise AdapterError("CONNECTOR_INCREMENTAL_TYPE_INVALID")
    try:
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise AdapterError("CONNECTOR_INCREMENTAL_TYPE_INVALID") from None


class Bindings:
    def __init__(self, dialect):
        self.dialect, self.values = dialect, []

    def bind(self, value):
        self.values.append(value)
        return (
            "?"
            if self.dialect == "hana"
            else f":{len(self.values)}"
            if self.dialect == "oracle"
            else "%s"
        )


def _window(connection, target, dialect, parameters, execution):
    incremental = parameters.get("incremental")
    if incremental is None:
        return None
    if not isinstance(incremental, dict) or set(incremental) - {
        "watermark_column",
        "key_column",
        "overlap",
        "type",
    }:
        raise AdapterError("CONNECTOR_INCREMENTAL_INVALID")
    watermark, key = incremental.get("watermark_column"), incremental.get("key_column")
    wm, unique = _identifier(watermark, dialect), _identifier(key, dialect)
    kind, overlap = incremental.get("type"), incremental.get("overlap", 0)
    if (
        kind not in {"integer", "timestamp"}
        or type(overlap) is not int
        or not 0 <= overlap <= 31_536_000
    ):
        raise AdapterError("CONNECTOR_INCREMENTAL_INVALID")
    columns = parameters.get("columns")
    if columns is not None and not {watermark, key}.issubset(columns):
        raise AdapterError("CONNECTOR_INCREMENTAL_COLUMNS_REQUIRED")
    checkpoint = (execution or {}).get("read_checkpoint")
    if not isinstance(checkpoint, dict) or type(checkpoint.get("revision")) is not int:
        raise AdapterError("CONNECTOR_CHECKPOINT_REQUIRED")
    after = checkpoint.get("after")
    if after is not None:
        if not isinstance(after, list) or len(after) != 2:
            raise AdapterError("CONNECTOR_CHECKPOINT_INVALID")
        after = (_watermark(after[0], kind), _value(after[1]))
    cursor = connection.cursor()
    try:
        cursor.execute(
            _limited(
                f"SELECT {wm}, {unique} FROM {target} WHERE {wm} IS NULL OR {unique} IS NULL",
                dialect,
                1,
            )
        )
        if cursor.fetchone() is not None:
            raise AdapterError("CONNECTOR_INCREMENTAL_NULL_KEY")
        cursor.execute(
            _limited(
                f"SELECT {unique} FROM {target} GROUP BY {unique} HAVING COUNT(*)>1", dialect, 1
            )
        )
        if cursor.fetchone() is not None:
            raise AdapterError("CONNECTOR_INCREMENTAL_NON_UNIQUE_KEY")
        cursor.execute(
            _limited(
                f"SELECT {wm}, {unique} FROM {target} ORDER BY {wm} DESC, {unique} DESC", dialect, 1
            )
        )
        result = cursor.fetchone()
        upper = (_watermark(result[0], kind), _value(result[1])) if result else None
    finally:
        cursor.close()
    return {
        "watermark": watermark,
        "key": key,
        "after": after,
        "upper": upper,
        "overlap": overlap,
        "type": kind,
        "revision": checkpoint["revision"],
    }


def _partition_bounds(connection, target, dialect, parameters):
    partition = parameters.get("partitions")
    if partition is None:
        return [None]
    if (
        not isinstance(partition, dict)
        or set(partition) != {"column", "count"}
        or type(partition.get("count")) is not int
        or not 1 <= partition["count"] <= 32
    ):
        raise AdapterError("CONNECTOR_PARTITION_INVALID")
    column = _identifier(partition["column"], dialect)
    cursor = connection.cursor()
    try:
        cursor.execute(f"SELECT MIN({column}), MAX({column}) FROM {target}")
        limits = cursor.fetchone()
    finally:
        cursor.close()
    if not limits or limits[0] is None:
        return [{"column": partition["column"], "null": True}]
    lower, upper = limits
    if isinstance(lower, Decimal) and lower == int(lower):
        lower = int(lower)
    if isinstance(upper, Decimal) and upper == int(upper):
        upper = int(upper)
    if type(lower) is not int or type(upper) is not int or upper < lower:
        raise AdapterError("CONNECTOR_PARTITION_INTEGER_REQUIRED")
    count = min(partition["count"], upper - lower + 1)
    width = (upper - lower + 1 + count - 1) // count
    bounds = []
    while lower <= upper:
        end = min(upper, lower + width - 1)
        bounds.append({"column": partition["column"], "lower": lower, "upper": end})
        lower = end + 1
    # A separate NULL partition is always included; NULL never falls between
    # numeric bounds and must not be silently omitted.
    return [*bounds, {"column": partition["column"], "null": True}]


def _statement(selection, target, dialect, window, partition):
    bindings, clauses = Bindings(dialect), []
    if window:
        wm, key = _identifier(window["watermark"], dialect), _identifier(window["key"], dialect)
        upper, after = window["upper"], window["after"]
        if upper is None:
            clauses.append("1=0")
        else:
            clauses.append(
                f"({wm}<{bindings.bind(upper[0])} OR ({wm}={bindings.bind(upper[0])} AND {key}<={bindings.bind(upper[1])}))"
            )
        if after:
            if window["overlap"]:
                lower = after[0] - (
                    timedelta(seconds=window["overlap"])
                    if window["type"] == "timestamp"
                    else window["overlap"]
                )
                clauses.append(f"{wm}>={bindings.bind(lower)}")
            else:
                clauses.append(
                    f"({wm}>{bindings.bind(after[0])} OR ({wm}={bindings.bind(after[0])} AND {key}>{bindings.bind(after[1])}))"
                )
    if partition:
        column = _identifier(partition["column"], dialect)
        clauses.append(
            f"{column} IS NULL"
            if partition.get("null")
            else f"{column}>={bindings.bind(partition['lower'])} AND {column}<={bindings.bind(partition['upper'])}"
        )
    query = f"SELECT {selection} FROM {target}" + (
        " WHERE " + " AND ".join(clauses) if clauses else ""
    )
    if window:
        query += f" ORDER BY {_identifier(window['watermark'], dialect)}, {_identifier(window['key'], dialect)}"
    return query, tuple(bindings.values)


def stream(
    connection,
    target,
    selection,
    parameters,
    deadline_at,
    output_dir,
    *,
    dialect,
    limits,
    execution,
):
    max_rows, max_bytes = (
        parameters.get("max_rows", 3_000_000),
        parameters.get("max_bytes", 1024**3),
    )
    if (
        type(max_rows) is not int
        or not 1 <= max_rows <= 10_000_000
        or type(max_bytes) is not int
        or not 1 <= max_bytes <= 1024**3
    ):
        raise AdapterError("CONNECTOR_IMPORT_LIMIT_INVALID")
    window = _window(connection, target, dialect, parameters, execution)
    partitions = _partition_bounds(connection, target, dialect, parameters)
    digest, count, size, names = hashlib.sha256(), 0, 0, None
    with (output_dir / "rows.jsonl").open("xb") as handle:
        for index, partition in enumerate(partitions):
            _remaining(deadline_at)
            query, values = _statement(selection, target, dialect, window, partition)
            cursor = (
                connection.cursor(name=f"agentium_partition_{index}")
                if dialect in {"postgresql", "redshift"}
                else connection.cursor()
            )
            try:
                cursor.execute(query, values)
                columns = [str(item[0]) for item in cursor.description or ()]
                if len(columns) > 2000 or (names is not None and columns != names):
                    raise AdapterError("CONNECTOR_SCHEMA_CHANGED")
                names = columns
                while True:
                    _remaining(deadline_at)
                    rows = cursor.fetchmany(min(int(limits.get("fetch_rows", 1000)), 1000))
                    if not rows:
                        break
                    for row in rows:
                        payload = (
                            json.dumps(
                                [_typed_value(item) for item in row],
                                ensure_ascii=False,
                                allow_nan=False,
                            )
                            + "\n"
                        ).encode()
                        count, size = count + 1, size + len(payload)
                        if count > max_rows or size > max_bytes:
                            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                        handle.write(payload)
                        digest.update(payload)
            finally:
                cursor.close()
    output = {
        "artifact": "rows.jsonl",
        "format": "typed-jsonl-v2",
        "columns": names or [],
        "row_count": count,
        "bytes": size,
        "sha256": digest.hexdigest(),
        "consistency": "snapshot" if dialect == "postgresql" else "none",
        "read_consistency": "snapshot" if dialect == "postgresql" else "none",
        "partition_bounds": partitions if parameters.get("partitions") else None,
    }
    if window:
        upper, after = window["upper"], window["after"]
        # Deletion/truncation or an overlap reread must never rewind a cursor.
        next_value = max([value for value in (upper, after) if value is not None], default=None)
        output.update(
            next_checkpoint=[_value(value) for value in next_value] if next_value else None,
            checkpoint_revision=window["revision"],
            read_upper=[_value(value) for value in upper] if upper else None,
        )
    return output
