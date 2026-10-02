"""Bounded, SELECT-only PostgreSQL discovery and native dataset snapshots.

Identifiers come from the accessible catalog, never from authored SQL. Each
read owns a short read-only transaction; imports re-read the source, rather
than persisting the browser's preview. Decimal and JSON values use lossless
text columns in the snapshot (reported explicitly in the column metadata).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services import tabular_datasets as datasets
from app.services.connectors.generic.service import get_config

MAX_TABLES = 500
MAX_COLUMNS = 128
MAX_IMPORT_ROWS = 10_000
MAX_PREVIEW_ROWS = 100
MAX_IMPORT_BYTES = 16 * 1024 * 1024
MAX_PREVIEW_BYTES = 512 * 1024


class PostgresBrowseError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _identifier(value: str) -> str:
    if not value or "\x00" in value or len(value.encode()) > 63:
        raise PostgresBrowseError("PG_IDENTIFIER_INVALID")
    return value


@contextmanager
def _connection(workspace):
    import psycopg2

    connection = None
    try:
        config = get_config(workspace, "postgresql", include_secrets=True)
        values, secrets = config.get("values", {}), config.get("secrets", {})
        # Never let libpq fill missing credentials from PGUSER/PGPASSWORD or
        # .pgpass belonging to the backend process.
        if not all(values.get(key) for key in ("host", "database", "username")) or not secrets.get(
            "password"
        ):
            raise PostgresBrowseError("PG_NOT_CONFIGURED", 409)
        port = int(values.get("port") or 5432)
        if not 1 <= port <= 65535:
            raise PostgresBrowseError("PG_NOT_CONFIGURED", 409)
        connection = psycopg2.connect(
            host=values["host"],
            port=port,
            dbname=values["database"],
            user=values["username"],
            password=secrets["password"],
            connect_timeout=5,
            application_name="agentium-postgresql-explorer",
        )
        # Catalog rechecks must see DDL committed while we acquired the table
        # lock. The SELECT cursor owns one row snapshot; ACCESS SHARE holds
        # the relation/schema stable through that read.
        connection.set_session(isolation_level="READ COMMITTED", readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '5s'")
        yield connection, config
    except PostgresBrowseError:
        raise
    except Exception as exc:
        # Driver strings can contain connection details; only closed codes leave
        # this boundary. It also covers decryption/configuration failures.
        code = getattr(exc, "pgcode", None)
        if code == "42501":
            raise PostgresBrowseError("PG_PERMISSION_DENIED", 403) from None
        if code in {"57014", "55P03"}:
            raise PostgresBrowseError("PG_TIMEOUT", 504) from None
        if code in {"42P01", "42703"}:
            raise PostgresBrowseError("PG_SOURCE_CHANGED", 409) from None
        raise PostgresBrowseError("PG_UNAVAILABLE", 503) from None
    finally:
        if connection is not None:
            for finish in (connection.rollback, connection.close):
                try:
                    finish()
                except Exception:
                    pass


def catalog(workspace) -> dict[str, Any]:
    from psycopg2.extras import RealDictCursor

    with _connection(workspace) as (connection, _config):
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT n.nspname AS schema, c.relname AS name,
                       CASE WHEN c.relkind = 'p' THEN 'partitioned' ELSE 'table' END AS kind
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
                  AND n.nspname NOT LIKE 'pg\\_%%' AND n.nspname <> 'information_schema'
                  AND has_schema_privilege(n.oid, 'USAGE')
                  AND has_table_privilege(c.oid, 'SELECT')
                ORDER BY n.nspname, c.relname LIMIT %s
            """,
                (MAX_TABLES + 1,),
            )
            tables = [dict(row) for row in cursor.fetchall()]
        if len(tables) > MAX_TABLES:
            raise PostgresBrowseError("PG_CATALOG_TOO_LARGE")
    return {
        "tables": tables,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "limits": {
            "preview_rows": MAX_PREVIEW_ROWS,
            "import_rows": MAX_IMPORT_ROWS,
            "import_bytes": MAX_IMPORT_BYTES,
        },
        "datasets_enabled": settings.tabular_data_enabled,
    }


_KINDS = {
    "int2": "integer",
    "int4": "integer",
    "int8": "integer",
    "oid": "integer",
    "float4": "float",
    "float8": "float",
    "bool": "boolean",
    "date": "datetime",
    "timestamp": "datetime",
    "timestamptz": "datetime",
    "text": "string",
    "varchar": "string",
    "bpchar": "string",
    "name": "string",
    "uuid": "string",
    "numeric": "string",
    "json": "string",
    "jsonb": "string",
    "time": "string",
    "timetz": "string",
    "interval": "string",
}


def _describe(connection, config, schema: str, table: str) -> dict[str, Any]:
    from psycopg2.extras import RealDictCursor

    _identifier(schema)
    _identifier(table)
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT c.oid AS relation_oid, a.attname AS name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS dtype,
                   t.typname AS pg_type, tn.nspname AS type_schema,
                   NOT a.attnotnull AS nullable,
                   EXISTS (SELECT 1 FROM pg_catalog.pg_index i
                           WHERE i.indrelid = c.oid AND i.indisprimary
                             AND a.attnum = ANY(i.indkey)) AS primary_key
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
            JOIN pg_catalog.pg_namespace tn ON tn.oid = t.typnamespace
            WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('r', 'p')
              AND NOT c.relispartition AND n.nspname NOT LIKE 'pg\\_%%'
              AND n.nspname <> 'information_schema'
              AND has_schema_privilege(n.oid, 'USAGE') AND has_table_privilege(c.oid, 'SELECT')
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum LIMIT %s
        """,
            (schema, table, MAX_COLUMNS + 1),
        )
        raw = [dict(row) for row in cursor.fetchall()]
    if not raw:
        raise PostgresBrowseError("PG_TABLE_NOT_ACCESSIBLE", 404)
    if len(raw) > MAX_COLUMNS:
        raise PostgresBrowseError("PG_TOO_MANY_COLUMNS")
    # The public fingerprint binds the source identity, never a password or a
    # password-derived digest that could enable offline credential guessing.
    fingerprint = _hash(
        {"columns": raw, "schema": schema, "table": table, "connection": config["values"]}
    )
    columns = [
        {
            **row,
            "kind": _KINDS.get(row["pg_type"], "other"),
            "supported": row["type_schema"] == "pg_catalog" and row["pg_type"] in _KINDS,
            "as_text": row["pg_type"]
            in {"numeric", "json", "jsonb", "time", "timetz", "interval", "uuid"},
        }
        for row in raw
    ]
    return {"schema": schema, "table": table, "columns": columns, "fingerprint": fingerprint}


def describe(workspace, schema: str, table: str) -> dict[str, Any]:
    with _connection(workspace) as (connection, config):
        return _describe(connection, config, schema, table)


def _value(value: Any, pg_type: str) -> Any:
    if value is None:
        return None
    if pg_type in {"json", "jsonb"}:
        return value if isinstance(value, str) else _canonical(value)
    if pg_type in {"numeric", "uuid", "time", "timetz", "interval"}:
        return str(value)
    if isinstance(value, datetime) and value.tzinfo:
        return value.astimezone(timezone.utc)
    if isinstance(value, float) and not math.isfinite(value):
        raise PostgresBrowseError("PG_UNSUPPORTED_VALUE")
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        return str(value)  # Browser JSON numbers cannot represent every int64.
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def read(
    workspace,
    *,
    schema: str,
    table: str,
    columns: list[str],
    fingerprint: str,
    limit: int,
    importing: bool = False,
) -> dict[str, Any]:
    from psycopg2 import sql

    max_rows = MAX_IMPORT_ROWS if importing else MAX_PREVIEW_ROWS
    if not 1 <= limit <= max_rows or not columns or len(set(columns)) != len(columns):
        raise PostgresBrowseError("PG_SELECTION_INVALID")
    started = time.monotonic()
    with _connection(workspace) as (connection, config):
        metadata = _describe(connection, config, schema, table)
        # Lock the discovered relation before checking its fingerprint again:
        # concurrent DDL must not swap the source between discovery and SELECT.
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("LOCK TABLE {}.{} IN ACCESS SHARE MODE").format(
                    sql.Identifier(schema), sql.Identifier(table)
                )
            )
        metadata = _describe(connection, config, schema, table)
        if metadata["fingerprint"] != fingerprint:
            raise PostgresBrowseError("PG_SOURCE_CHANGED", 409)
        by_name = {col["name"]: col for col in metadata["columns"]}
        if any(name not in by_name or not by_name[name]["supported"] for name in columns):
            raise PostgresBrowseError("PG_SELECTION_INVALID")
        selected = [by_name[name] for name in columns]
        keys = [col["name"] for col in metadata["columns"] if col["primary_key"]]
        order = (
            sql.SQL(" ORDER BY {}").format(sql.SQL(", ").join(map(sql.Identifier, keys)))
            if keys
            else sql.SQL("")
        )
        expressions = [
            sql.SQL("{}::pg_catalog.text AS {}").format(
                sql.Identifier(col["name"]), sql.Identifier(col["name"])
            )
            if col["as_text"]
            else sql.Identifier(col["name"])
            for col in selected
        ]
        rows, byte_count = [], 0
        byte_limit = MAX_IMPORT_BYTES if importing else MAX_PREVIEW_BYTES
        budget_name = "__agentium_fits_" + uuid4().hex[:16]
        while budget_name in by_name:
            budget_name = "__agentium_fits_" + uuid4().hex[:16]
        budget = sql.Identifier(budget_name)
        sizes = sql.SQL(" + ").join(
            sql.SQL("COALESCE(pg_catalog.octet_length({}::pg_catalog.text), 0)::bigint").format(
                sql.Identifier(col["name"])
            )
            for col in selected
        )
        bounded = sql.SQL(", ").join(
            sql.SQL("CASE WHEN {} THEN {} ELSE NULL END").format(
                budget, sql.Identifier(col["name"])
            )
            for col in selected
        )
        # Oversized rows return a flag and NULLs, never their large cells. A
        # materialized CTE computes the size once; fetching one row at a time
        # keeps the client buffer bounded even with many wide rows.
        query = sql.SQL("""
            WITH agentium_source AS MATERIALIZED (
                SELECT {}, ({}) <= {} AS {} FROM {}.{}{} LIMIT %s
            ) SELECT {}, {} FROM agentium_source
        """).format(
            sql.SQL(", ").join(expressions),
            sizes,
            sql.Literal(byte_limit),
            budget,
            sql.Identifier(schema),
            sql.Identifier(table),
            order,
            budget,
            bounded,
        )
        with connection.cursor(name="agentium_snapshot") as cursor:
            cursor.execute(query, (limit + 1,))
            while True:
                batch = cursor.fetchmany(1)
                if not batch:
                    break
                for values in batch:
                    if not values[0]:
                        raise PostgresBrowseError("PG_RESULT_TOO_LARGE", 413)
                    row = {
                        col["name"]: _value(value, col["pg_type"])
                        for col, value in zip(selected, values[1:])
                    }
                    byte_count += len(
                        _canonical({k: _json_value(v) for k, v in row.items()}).encode()
                    )
                    if byte_count > byte_limit:
                        raise PostgresBrowseError("PG_RESULT_TOO_LARGE", 413)
                    rows.append(row)
                if time.monotonic() - started > 20:
                    raise PostgresBrowseError("PG_TIMEOUT", 504)
        truncated = len(rows) > limit
        if importing and truncated:
            raise PostgresBrowseError("PG_IMPORT_ROW_LIMIT", 413)
        rows = rows[:limit]
        captured_at = datetime.now(timezone.utc).isoformat()
    json_rows = [{k: _json_value(v) for k, v in row.items()} for row in rows]
    return {
        "schema": selected,
        "rows": json_rows,
        "native_rows": rows,
        "row_count": len(rows),
        "has_more": truncated,
        "ordered_by": keys,
        "captured_at": captured_at,
        "fingerprint": fingerprint,
        "snapshot_sha256": _hash(json_rows),
        "database": config["values"]["database"],
    }


def import_dataset(db, workspace, user, *, name: str, request_id: str, **selection):
    if not settings.tabular_data_enabled:
        raise PostgresBrowseError("PG_DATASETS_DISABLED", 409)
    try:
        request_id = str(UUID(request_id))
    except ValueError:
        raise PostgresBrowseError("PG_REQUEST_INVALID") from None
    name = name.strip()
    if not name or len(name) > 200:
        raise PostgresBrowseError("PG_NAME_INVALID")
    request_hash = _hash({"name": name, **selection})
    # Serializes version allocation and idempotency in this workspace. The
    # lock is held through the bounded read/write and commit by the API caller.
    db.query(Workspace).filter(
        Workspace.id == workspace.id
    ).populate_existing().with_for_update().one()
    previous = (
        db.query(TabularDataset)
        .filter(
            TabularDataset.workspace_id == workspace.id,
            TabularDataset.source == "postgresql",
            TabularDataset.lineage_json["request_id"].as_string() == request_id,
        )
        .first()
    )
    if previous:
        if previous.lineage_json.get("request_hash") != request_hash or previous.status != "ready":
            raise PostgresBrowseError("PG_REQUEST_CONFLICT", 409)
        return previous, True
    result = read(workspace, **selection, importing=True, limit=MAX_IMPORT_ROWS)
    import polars as pl

    dtype = {"integer": pl.Int64, "float": pl.Float64, "boolean": pl.Boolean, "string": pl.String}
    schema = {}
    for column in result["schema"]:
        pg_type = column["pg_type"]
        schema[column["name"]] = (
            pl.Date
            if pg_type == "date"
            else pl.Datetime("us", "UTC")
            if pg_type == "timestamptz"
            else pl.Datetime("us")
            if pg_type == "timestamp"
            else dtype[column["kind"]]
        )
    frame = pl.DataFrame(result["native_rows"], schema=schema, strict=True)
    dataset = datasets.register_frame(
        db,
        workspace_id=workspace.id,
        name=name,
        frame=frame,
        source="postgresql",
        created_by=user.id,
        lineage={
            "engine": "postgresql",
            "request_id": request_id,
            "request_hash": request_hash,
            "postgresql": {
                "database": result["database"],
                "schema": selection["schema"],
                "table": selection["table"],
                "columns": selection["columns"],
                "captured_at": result["captured_at"],
                "mode": "snapshot",
                "row_count": frame.height,
                "truncated": False,
                "schema_fingerprint": result["fingerprint"],
                "snapshot_sha256": result["snapshot_sha256"],
                "text_columns": [col["name"] for col in result["schema"] if col["as_text"]],
            },
        },
    )
    return dataset, False
