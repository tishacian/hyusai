"""Bounded, read-only PostgreSQL/HANA driver adapter for the isolated runner.

No caller-supplied SQL, driver options, DSNs or paths enter a driver. Import
streams rows into a private staging file; publication belongs to the parent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.connectors.network_policy import (
    ConnectorNetworkError,
    postgresql_connection_options,
)


class AdapterError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _identifier(value: Any, dialect: str = "") -> str:
    if not isinstance(value, str) or not value or len(value) > 127 or "\x00" in value:
        raise AdapterError("CONNECTOR_IDENTIFIER_INVALID")
    quote = "`" if dialect in {"mysql", "mariadb", "bigquery", "databricks_sql"} else '"'
    return quote + value.replace(quote, quote * 2) + quote


def _remaining(deadline_at: str) -> float:
    deadline = datetime.fromisoformat(deadline_at)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise AdapterError("CONNECTOR_TIMEOUT")
    return remaining


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"type": "float", "value": str(value)}
        return value
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, (datetime, date)):
        return {
            "type": "datetime" if isinstance(value, datetime) else "date",
            "value": value.isoformat(),
        }
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "binary", "value": base64.b64encode(bytes(value)).decode()}
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise AdapterError("CONNECTOR_TYPE_UNSUPPORTED")


def _typed_value(value: Any) -> Any:
    """Encode a cell for typed-jsonl-v2, escaping every user JSON object.

    Object envelopes make literal documents resembling scalar tags lossless,
    including documents resembling this envelope itself. Public previews and
    outgoing JSON requests deliberately retain the separate _json_value format.
    """
    if isinstance(value, dict):
        return {
            "type": "object",
            "value": {str(key): _typed_value(item) for key, item in value.items()},
        }
    if isinstance(value, (tuple, list)):
        return [_typed_value(item) for item in value]
    return _json_value(value)


@contextmanager
def _connection(
    dialect: str, config: dict, credentials: dict, deadline_at: str, *, read_only: bool = True
):
    connection = None
    try:
        remaining = _remaining(deadline_at)
        if dialect in {"postgresql", "redshift"}:
            import psycopg2

            connection = psycopg2.connect(
                **postgresql_connection_options(config["host"], config.get("port", 5432)),
                dbname=config["database"],
                user=config["username"],
                password=credentials.get("password", ""),
                connect_timeout=max(1, min(10, math.ceil(remaining))),
            )
            connection.set_session(readonly=read_only, autocommit=False)
            if read_only and dialect == "postgresql":
                connection.set_session(isolation_level="REPEATABLE READ")
            if not read_only and dialect == "postgresql":
                connection.set_session(isolation_level="SERIALIZABLE")
            with connection.cursor() as cursor:
                if dialect == "redshift":
                    # Database isolation is not a PostgreSQL session knob in
                    # Redshift; statement_timeout also bounds table-lock waits.
                    cursor.execute("SET statement_timeout TO %s", (max(1, int(remaining * 1000)),))
                else:
                    cursor.execute(
                        "SET LOCAL statement_timeout = %s", (max(1, int(remaining * 1000)),)
                    )
                    cursor.execute(
                        "SET LOCAL lock_timeout = %s", (max(1, min(5000, int(remaining * 1000))),)
                    )
        elif dialect in {"mysql", "mariadb", "sql_server", "synapse", "oracle"}:
            with _other_connection(
                dialect, config, credentials, deadline_at, read_only=read_only
            ) as native:
                yield native
            return
        elif dialect in {"snowflake", "bigquery", "databricks_sql"}:
            from app.services.connectors.adapters.sql_cloud import CloudConnection

            connection = CloudConnection(dialect, config, credentials, deadline_at)
        elif dialect == "hana":
            from hdbcli import dbapi

            from app.services.connectors.hana.network_policy import resolve_destination

            if (
                config.get("encrypt", True) is not True
                or config.get("ssl_validate_certificate", True) is not True
            ):
                raise AdapterError("CONNECTOR_TLS_REQUIRED")
            destination = resolve_destination(config["host"], config.get("port", 443))
            connection = dbapi.connect(
                address=destination.address,
                port=config.get("port", 443),
                user=config["user"],
                password=credentials.get("password", ""),
                encrypt=True,
                sslValidateCertificate=True,
                sslHostNameInCertificate=destination.host,
                distributionMode="off",
                connectTimeout=max(1, min(10000, int(remaining * 1000))),
                communicationTimeout=max(1, int(remaining * 1000)),
            )
            connection.setautocommit(False)
            cursor = connection.cursor()
            try:
                cursor.execute("SET TRANSACTION READ ONLY")
            finally:
                cursor.close()
        else:
            raise AdapterError("CONNECTOR_DIALECT_UNSUPPORTED")
        yield connection
    except (AdapterError, ConnectorNetworkError):
        raise
    except ImportError:
        raise AdapterError("CONNECTOR_DRIVER_UNAVAILABLE") from None
    except Exception:
        # Driver errors can quote credentials, SQL literals, hostnames and data.
        raise AdapterError("CONNECTOR_SQL_FAILED") from None
    finally:
        if connection is not None:
            for action in (connection.rollback, connection.close):
                try:
                    action()
                except Exception:
                    pass


def _scope(schema: str, table: str | None, access: dict) -> None:
    schemas = access.get("allowed_schemas") or []
    tables = access.get("allowed_tables") or []
    if schemas and schema not in schemas:
        raise AdapterError("CONNECTOR_SOURCE_FORBIDDEN")
    if table is not None and tables and table not in tables and f"{schema}.{table}" not in tables:
        raise AdapterError("CONNECTOR_SOURCE_FORBIDDEN")


def execute(
    operation: str,
    config: dict,
    credentials: dict,
    parameters: dict,
    deadline_at: str,
    output_dir: Path,
    *,
    dialect: str,
    access: dict | None = None,
    limits: dict | None = None,
    execution: dict | None = None,
) -> dict:
    """Return bounded JSON metadata, or a staged JSONL stream for import.

    The staging path is chosen by the runner. It is never a user input and is
    not a public dataset until publication completes outside this adapter.
    """
    if operation == "write_preview":
        from app.services.connectors.adapters.sql_preview import preview_write

        return preview_write(
            config,
            credentials,
            parameters,
            deadline_at,
            output_dir,
            dialect=dialect,
            access=access or {},
            execution=execution,
        )
    if operation in {"write_append", "write_overwrite", "write_upsert", "reconcile_write"}:
        if dialect in {"bigquery", "snowflake", "databricks_sql"}:
            from app.services.connectors.adapters.sql_cloud_write import execute_write
        else:
            from app.services.connectors.adapters.sql_write import execute_write
        return execute_write(
            operation,
            config,
            credentials,
            parameters,
            deadline_at,
            output_dir,
            dialect=dialect,
            access=access or {},
            execution=execution,
        )
    if operation not in {"test", "catalog", "table", "preview", "import"}:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {
        "schema",
        "table",
        "columns",
        "limit",
        "max_rows",
        "max_bytes",
        "incremental",
        "partitions",
    }:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    if config.get("demo_mode"):
        if dialect != "hana":
            raise AdapterError("CONNECTOR_DEMO_NOT_SUPPORTED")
        return _execute_demo(operation, config, parameters, output_dir, access or {})
    access, limits = access or {}, limits or {}
    max_preview = min(1000, int(limits.get("preview_rows", 100)))
    limit = parameters.get("limit", max_preview)
    if type(limit) is not int or not 1 <= limit <= max_preview:
        raise AdapterError("CONNECTOR_PREVIEW_LIMIT_INVALID")
    schema = parameters.get(
        "schema",
        config.get("schema")
        or config.get("dataset")
        or ("public" if dialect in {"postgresql", "redshift"} else config.get("database", "")),
    )
    table = parameters.get("table")
    if operation in {"table", "preview", "import"}:
        _identifier(schema)
        _identifier(table)
        _scope(schema, table, access)
    with _connection(dialect, config, credentials, deadline_at) as connection:
        cursor = (
            connection.cursor(name="agentium_read")
            if dialect in {"postgresql", "redshift"} and operation == "import"
            else connection.cursor()
        )
        try:
            if operation == "test":
                if dialect == "bigquery":
                    # BigQuery does not expose a database software version.
                    # Executing a literal API label cannot observe one.
                    cursor.execute("SELECT 1")
                    record = cursor.fetchone()
                    if (
                        not record
                        or len(record) != 1
                        or type(record[0]) is not int
                        or record[0] != 1
                    ):
                        raise AdapterError("CONNECTOR_RESPONSE_INVALID")
                    return {
                        "connected": True,
                        "source": "real",
                        "identity_error_code": "CONNECTOR_SERVER_VERSION_UNAVAILABLE",
                    }
                version_sql = {
                    "postgresql": "SELECT version()",
                    "redshift": "SELECT version()",
                    "mysql": "SELECT VERSION()",
                    "mariadb": "SELECT VERSION()",
                    "sql_server": "SELECT CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(128))",
                    "synapse": "SELECT CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(128))",
                    "oracle": "SELECT VERSION FROM PRODUCT_COMPONENT_VERSION WHERE PRODUCT LIKE 'Oracle Database%'",
                    "hana": "SELECT VERSION FROM SYS.M_DATABASE",
                    "snowflake": "SELECT CURRENT_VERSION()",
                    "databricks_sql": "SELECT current_version().dbsql_version",
                }
                cursor.execute(version_sql[dialect])
                record = cursor.fetchone()
                version = str(record[0])[:512] if record and record[0] is not None else None
                if not version:
                    raise AdapterError("CONNECTOR_SERVER_IDENTITY_UNAVAILABLE")
                return {
                    "connected": True,
                    "source": "real",
                    "server_version": version,
                    "version_kind": "server",
                }
            if operation == "catalog":
                statement = _catalog_sql(dialect, config)
                cursor.execute(statement)
                rows = cursor.fetchmany(10001)
                if len(rows) > 10000:
                    raise AdapterError("CONNECTOR_CATALOG_TOO_LARGE")
                visible = []
                for source_schema, source_table in rows:
                    try:
                        _scope(source_schema, source_table, access)
                    except AdapterError:
                        continue
                    visible.append({"schema": source_schema, "table": source_table})
                return {"tables": visible}
            if operation == "table":
                statement, bindings = _columns_sql(dialect, config, schema, table)
                cursor.execute(statement, bindings)
                rows = cursor.fetchmany(2001)
                if len(rows) > 2000:
                    raise AdapterError("CONNECTOR_SCHEMA_TOO_LARGE")
                return {
                    "columns": [
                        {
                            "name": name,
                            "type": kind,
                            "nullable": nullable in (True, "YES", "TRUE", "Y"),
                        }
                        for name, kind, nullable in rows
                    ]
                }
            columns = parameters.get("columns")
            if columns is not None and (
                not isinstance(columns, list)
                or not 1 <= len(columns) <= 2000
                or len(set(columns)) != len(columns)
            ):
                raise AdapterError("CONNECTOR_COLUMNS_INVALID")
            selection = (
                ", ".join(_identifier(value, dialect) for value in columns) if columns else "*"
            )
            if operation == "import" and (
                "incremental" in parameters or "partitions" in parameters
            ):
                from app.services.connectors.adapters.sql_read import stream

                return stream(
                    connection,
                    _target(dialect, config, schema, table),
                    selection,
                    parameters,
                    deadline_at,
                    output_dir,
                    dialect=dialect,
                    limits=limits,
                    execution=execution,
                )
            statement = f"SELECT {selection} FROM {_target(dialect, config, schema, table)}"
            if operation == "preview":
                statement = _limited(statement, dialect, limit)
            cursor.execute(statement)
            names = [str(item[0]) for item in cursor.description or ()]
            if len(names) > 2000:
                raise AdapterError("CONNECTOR_SCHEMA_TOO_LARGE")
            if operation == "preview":
                rows = [[_json_value(item) for item in row] for row in cursor.fetchmany(limit)]
                result = {
                    "columns": names,
                    "rows": rows,
                    "row_count": len(rows),
                    "consistency": "snapshot" if dialect == "postgresql" else "none",
                }
                if len(json.dumps(result).encode()) > 4 * 1024 * 1024:
                    raise AdapterError("CONNECTOR_PREVIEW_TOO_LARGE")
                return result
            # This is bounded streaming, not a fetchall or an in-memory dataset.
            max_rows = parameters.get("max_rows", 3_000_000)
            max_bytes = parameters.get("max_bytes", 1024 * 1024 * 1024)
            if (
                type(max_rows) is not int
                or not 1 <= max_rows <= 10_000_000
                or type(max_bytes) is not int
                or not 1 <= max_bytes <= 1024 * 1024 * 1024
            ):
                raise AdapterError("CONNECTOR_IMPORT_LIMIT_INVALID")
            artifact = output_dir / "rows.jsonl"
            digest, count, size = hashlib.sha256(), 0, 0
            with artifact.open("xb") as handle:
                while True:
                    _remaining(deadline_at)
                    batch = cursor.fetchmany(min(int(limits.get("fetch_rows", 1000)), 1000))
                    if not batch:
                        break
                    for row in batch:
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
            return {
                "columns": names,
                "row_count": count,
                "bytes": size,
                "sha256": digest.hexdigest(),
                "artifact": "rows.jsonl",
                "format": "typed-jsonl-v2",
                "consistency": "snapshot" if dialect == "postgresql" else "none",
                "source": "real",
            }
        finally:
            cursor.close()


def _execute_demo(operation, config, parameters, output_dir, access):
    """Explicit HANA showcase fixtures, never a successful live connection."""
    from app.services.connectors.hana.demo_dataset import _build_connection
    from app.services.connectors.hana.service import _demo_tables

    schema = parameters.get("schema") or config.get("schema") or "DEMO"
    tables = [row["name"] for row in _demo_tables()]
    if operation == "test":
        return {"connected": False, "source": "demo", "demo_mode": True}
    if operation == "catalog":
        visible = []
        for table in tables:
            try:
                _scope(schema, table, access)
            except AdapterError:
                continue
            visible.append({"schema": schema, "table": table})
        return {"tables": visible, "source": "demo", "demo_mode": True}
    table = parameters.get("table")
    if table not in tables:
        raise AdapterError("CONNECTOR_SOURCE_FORBIDDEN")
    _scope(schema, table, access)
    connection = _build_connection()
    try:
        connection.execute("PRAGMA query_only = ON")
        if operation == "table":
            return {
                "columns": [
                    {"name": row[1], "type": row[2], "nullable": not row[3]}
                    for row in connection.execute(
                        f"PRAGMA table_info({_identifier(table)})"
                    ).fetchall()
                ],
                "source": "demo",
                "demo_mode": True,
            }
        limit = parameters.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise AdapterError("CONNECTOR_PREVIEW_LIMIT_INVALID")
        columns = parameters.get("columns")
        if columns is not None and (not isinstance(columns, list) or not 1 <= len(columns) <= 2000):
            raise AdapterError("CONNECTOR_COLUMNS_INVALID")
        selection = ", ".join(_identifier(name) for name in columns) if columns else "*"
        cursor = connection.execute(f"SELECT {selection} FROM {_identifier(table)}")
        names = [row[0] for row in cursor.description]
        rows = cursor.fetchmany(limit if operation == "preview" else 10001)
        if len(rows) > parameters.get("max_rows", 3_000_000):
            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        output = {
            "columns": names,
            "row_count": len(rows),
            "consistency": "none",
            "source": "demo",
            "demo_mode": True,
        }
        if operation == "preview":
            return {**output, "rows": [list(row) for row in rows]}
        encoded = "".join(
            json.dumps([_typed_value(item) for item in row], allow_nan=False) + "\n" for row in rows
        ).encode()
        if len(encoded) > parameters.get("max_bytes", 1024**3):
            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        path = output_dir / "rows.jsonl"
        path.write_bytes(encoded)
        return {
            **output,
            "artifact": "rows.jsonl",
            "format": "typed-jsonl-v2",
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    finally:
        connection.close()


def _limited(statement, dialect, limit):
    if dialect in {"sql_server", "synapse"}:
        return statement.replace("SELECT ", f"SELECT TOP {int(limit)} ", 1)
    if dialect == "oracle":
        return statement + f" FETCH FIRST {int(limit)} ROWS ONLY"
    return statement + f" LIMIT {int(limit)}"


def _target(dialect, config, schema, table):
    if dialect == "bigquery":
        return _identifier(f"{config['project']}.{schema}.{table}", dialect)
    if dialect == "databricks_sql" and config.get("catalog"):
        return ".".join(_identifier(value, dialect) for value in (config["catalog"], schema, table))
    return f"{_identifier(schema, dialect)}.{_identifier(table, dialect)}"


def _catalog_sql(dialect, config):
    if dialect == "hana":
        query = "SELECT SCHEMA_NAME, TABLE_NAME FROM SYS.TABLES ORDER BY SCHEMA_NAME, TABLE_NAME"
    elif dialect == "oracle":
        query = "SELECT OWNER, TABLE_NAME FROM ALL_TABLES ORDER BY OWNER, TABLE_NAME"
    elif dialect == "bigquery":
        location = _identifier(
            f"{config['project']}.{config['dataset']}.INFORMATION_SCHEMA.TABLES", dialect
        )
        query = f"SELECT table_schema, table_name FROM {location} WHERE table_type='BASE TABLE' ORDER BY table_schema, table_name"
    else:
        query = "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type='BASE TABLE' ORDER BY table_schema, table_name"
    return _limited(query, dialect, 10001)


def _columns_sql(dialect, config, schema, table):
    if dialect == "hana":
        return (
            "SELECT COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME=? AND TABLE_NAME=? ORDER BY POSITION",
            (schema, table),
        )
    if dialect == "oracle":
        return (
            "SELECT COLUMN_NAME, DATA_TYPE, NULLABLE FROM ALL_TAB_COLUMNS WHERE OWNER=:1 AND TABLE_NAME=:2 ORDER BY COLUMN_ID",
            (schema, table),
        )
    location = "information_schema.columns"
    if dialect == "bigquery":
        location = _identifier(f"{config['project']}.{schema}.INFORMATION_SCHEMA.COLUMNS", dialect)
    return (
        f"SELECT column_name, data_type, is_nullable FROM {location} WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
        (schema, table),
    )


@contextmanager
def _other_connection(dialect, config, credentials, deadline_at, *, read_only=True):
    import ssl

    from app.services.connectors.adapters.sql_transport import pinned_sql_destination

    timeout = max(1, _remaining(deadline_at))
    default_port = (
        3306 if dialect in {"mysql", "mariadb"} else 2484 if dialect == "oracle" else 1433
    )
    connection = None
    with pinned_sql_destination(config["host"], config.get("port", default_port)):
        try:
            if dialect in {"mysql", "mariadb"}:
                import pymysql
                from pymysql.constants import CLIENT

                class TLSConnection(pymysql.connections.Connection):
                    def _request_authentication(self):
                        if not self.server_capabilities & CLIENT.SSL:
                            raise AdapterError("CONNECTOR_TLS_REQUIRED")
                        return super()._request_authentication()

                connection = TLSConnection(
                    host=config["host"],
                    port=config.get("port", 3306),
                    database=config["database"],
                    user=config["username"],
                    password=credentials.get("password", ""),
                    ssl=ssl.create_default_context(),
                    ssl_verify_cert=True,
                    ssl_verify_identity=True,
                    cursorclass=pymysql.cursors.SSCursor,
                    client_flag=CLIENT.FOUND_ROWS,
                    connect_timeout=min(10, int(timeout)),
                    read_timeout=timeout,
                    write_timeout=timeout,
                    autocommit=False,
                    local_infile=False,
                )
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SET SESSION TRANSACTION READ ONLY"
                        if read_only
                        else "SET SESSION TRANSACTION ISOLATION LEVEL SERIALIZABLE"
                    )
                    cursor.execute(
                        "START TRANSACTION READ ONLY"
                        if read_only
                        else "START TRANSACTION READ WRITE"
                    )
            elif dialect in {"sql_server", "synapse"}:
                import certifi
                import pytds

                connection = pytds.connect(
                    server=config["host"],
                    port=config.get("port", 1433),
                    database=config["database"],
                    user=config["username"],
                    password=credentials.get("password", ""),
                    cafile=certifi.where(),
                    validate_host=True,
                    enc_login_only=False,
                    timeout=timeout,
                    login_timeout=min(10, timeout),
                    readonly=read_only,
                    disable_connect_retry=True,
                    pooling=False,
                    autocommit=False,
                )
                cursor = connection.cursor()
                try:
                    cursor.execute("SET QUOTED_IDENTIFIER ON")
                    if not read_only:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    cursor.execute(f"SET LOCK_TIMEOUT {int(min(timeout, 5) * 1000)}")
                finally:
                    cursor.close()
            else:
                import oracledb

                if not oracledb.is_thin_mode():
                    raise AdapterError("CONNECTOR_ORACLE_THIN_REQUIRED")
                connection = oracledb.connect(
                    host=config["host"],
                    port=config.get("port", 2484),
                    service_name=config["service_name"],
                    user=config["username"],
                    password=credentials.get("password", ""),
                    protocol="tcps",
                    ssl_server_dn_match=True,
                    use_sni=True,
                    ssl_context=ssl.create_default_context(),
                    tcp_connect_timeout=min(10, timeout),
                    retry_count=0,
                )
                connection.call_timeout = int(timeout * 1000)
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "SET TRANSACTION READ ONLY"
                        if read_only
                        else "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
                    )
                finally:
                    cursor.close()
            yield connection
        finally:
            if connection:
                for action in (connection.rollback, connection.close):
                    try:
                        action()
                    except Exception:
                        pass
