"""SQL APIs with the same pinned HTTPS boundary as other connector transports.

Cloud APIs are intentionally called here rather than through SDKs that may
follow new origins or fetch result chunks outside the configured destination.
"""

from __future__ import annotations

import base64
import json
import re
import time
from decimal import Decimal
from itertools import islice
from urllib.parse import quote, urlencode

from app.services.connectors.adapters.http import json_request
from app.services.connectors.adapters.sql import AdapterError, _remaining


def _token(credentials, dialect, deadline_at, *, read_only=True):
    access = credentials.get("access_token")
    if access:
        return access
    if dialect != "bigquery" or not credentials.get("credentials_json"):
        raise AdapterError("CONNECTOR_CREDENTIAL_REQUIRED")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        account = json.loads(credentials["credentials_json"])
        if account.get("type") != "service_account":
            raise ValueError()
        now = int(time.time())

        def encoded(value):
            return base64.urlsafe_b64encode(
                json.dumps(value, separators=(",", ":")).encode()
            ).rstrip(b"=")

        header = encoded({"alg": "RS256", "typ": "JWT"})
        claims = encoded(
            {
                "iss": account["client_email"],
                "scope": "https://www.googleapis.com/auth/bigquery.readonly"
                if read_only
                else "https://www.googleapis.com/auth/bigquery",
                "aud": "https://oauth2.googleapis.com/token",
                "iat": now,
                "exp": now + 3600,
            }
        )
        message = header + b"." + claims
        key = serialization.load_pem_private_key(account["private_key"].encode(), password=None)
        signature = base64.urlsafe_b64encode(
            key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        ).rstrip(b"=")
        assertion = (message + b"." + signature).decode()
    except Exception:
        raise AdapterError("CONNECTOR_CREDENTIAL_INVALID") from None
    _, body = json_request(
        "POST",
        "https://oauth2.googleapis.com/token",
        deadline_at=deadline_at,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        content=urlencode(
            {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
        ).encode(),
    )
    if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
        raise AdapterError("CONNECTOR_AUTH_DENIED")
    return body["access_token"]


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value):
        raise AdapterError("CONNECTOR_RESPONSE_INVALID")
    return value


def _bind(statement, params, dialect=None):
    literals = []
    for value in params or ():
        if dialect:
            import pyarrow as pa

            from app.services.connectors.adapters.sql_cloud_write import _literal

            dtype = pa.array([value]).type
            literal = _literal(value, dtype, dialect)
        elif isinstance(value, str):
            literal = "'" + value.replace("'", "''") + "'"
        else:
            raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
        literals.append(literal)
    # Scan only the generated template. Never search an already substituted
    # value: a literal containing "%s" must not consume the next binding.
    output, index, bound, quoted = [], 0, 0, None
    while index < len(statement):
        char = statement[index]
        if quoted:
            output.append(char)
            if char == "\\" and index + 1 < len(statement):
                index += 1
                output.append(statement[index])
            elif char == quoted:
                if index + 1 < len(statement) and statement[index + 1] == quoted:
                    index += 1
                    output.append(statement[index])
                else:
                    quoted = None
        elif char in "'\"`":
            quoted = char
            output.append(char)
        elif statement.startswith("%s", index):
            if bound >= len(literals):
                raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
            output.append(literals[bound])
            bound += 1
            index += 1
        else:
            output.append(char)
        index += 1
    if quoted or bound != len(literals):
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    return "".join(output)


def _value(value, field, dialect):
    if value is None:
        return None
    kind = str(field.get("type") or field.get("type_name") or field.get("type_text") or "").upper()
    if dialect == "bigquery" and field.get("mode") == "REPEATED":
        return [_value(item.get("v"), {**field, "mode": "NULLABLE"}, dialect) for item in value]
    if kind in {"INTEGER", "INT64", "INT", "BIGINT", "SMALLINT", "TINYINT"}:
        return int(value)
    if kind in {"NUMBER", "FIXED", "NUMERIC", "BIGNUMERIC", "DECIMAL"} or kind.startswith(
        "DECIMAL("
    ):
        return Decimal(value)
    if kind in {"FLOAT", "FLOAT64", "DOUBLE", "REAL"}:
        return float(value)
    if kind in {"BOOLEAN", "BOOL"}:
        return str(value).lower() == "true"
    if kind in {"BYTES", "BINARY"}:
        return bytes.fromhex(value) if dialect == "snowflake" else base64.b64decode(value)
    if kind in {"RECORD", "STRUCT"} and isinstance(value, dict):
        return {
            child["name"]: _value(item.get("v"), child, dialect)
            for child, item in zip(field.get("fields", []), value.get("f", []), strict=True)
        }
    # Temporal values keep the exact provider text if its encoding depends on
    # session settings; no timezone/precision is silently guessed here.
    return value


class CloudConnection:
    def __init__(self, dialect, config, credentials, deadline_at, *, read_only=True):
        self.dialect, self.config, self.deadline_at = dialect, config, deadline_at
        self.token = _token(credentials, dialect, deadline_at, read_only=read_only)
        host = config.get("host", "")
        if dialect == "snowflake":
            valid = re.fullmatch(r"[a-zA-Z0-9.-]+\.snowflakecomputing\.com", host)
        elif dialect == "databricks_sql":
            valid = re.fullmatch(r"[a-zA-Z0-9.-]+\.(?:databricks\.com|azuredatabricks\.net)", host)
        else:
            valid, host = True, "bigquery.googleapis.com"
            _id(config.get("project"))
        if not valid:
            raise AdapterError("CONNECTOR_HOST_INVALID")
        self.base = f"https://{host}"

    def request(self, method, path, body=None):
        if not path.startswith("/") or path.startswith("//"):
            raise AdapterError("CONNECTOR_REDIRECT_DENIED")
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        if self.dialect == "snowflake":
            headers["X-Snowflake-Authorization-Token-Type"] = "OAUTH"
        _, payload = json_request(
            method,
            self.base + path,
            deadline_at=self.deadline_at,
            headers=headers,
            content=json.dumps(body).encode() if body is not None else None,
            max_bytes=16 * 1024 * 1024,
        )
        if not isinstance(payload, dict):
            raise AdapterError("CONNECTOR_RESPONSE_INVALID")
        return payload

    def cursor(self, **kwargs):
        return CloudCursor(self)

    def rollback(self):
        pass  # Only generated SELECT statements are accepted by this adapter.

    def close(self):
        self.token = ""


class CloudCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []
        self.rows = iter(())

    def execute(self, statement, params=None):
        query = _bind(statement, params, self.connection.dialect)
        if not query.startswith("SELECT "):
            raise AdapterError("CONNECTOR_READ_ONLY")
        first, pages, fields = self._query(query)
        self.description = [(field["name"],) for field in fields]

        def rows():
            for index, batch in enumerate(pages):
                if index >= 100000:
                    raise AdapterError("CONNECTOR_PAGINATION_INVALID")
                _remaining(self.connection.deadline_at)
                for row in batch:
                    if self.connection.dialect == "bigquery":
                        row = [item.get("v") for item in row.get("f", [])]
                    if len(row) != len(fields):
                        raise AdapterError("CONNECTOR_RESPONSE_INVALID")
                    yield tuple(
                        _value(value, field, self.connection.dialect)
                        for value, field in zip(row, fields, strict=True)
                    )

        self.rows = rows()
        return self

    def _query(self, query):
        c, conf = self.connection, self.connection.config
        if c.dialect == "snowflake":
            body = {
                "statement": query,
                "timeout": max(1, int(_remaining(c.deadline_at))),
                "database": conf.get("database"),
                "schema": conf.get("schema"),
                "warehouse": conf["warehouse"],
                "parameters": {"MULTI_STATEMENT_COUNT": "1"},
            }
            if conf.get("role"):
                body["role"] = conf["role"]
            payload = c.request("POST", "/api/v2/statements", body)
            handle = _id(payload.get("statementHandle"))
            path = f"/api/v2/statements/{handle}"
            while "resultSetMetaData" not in payload:
                if payload.get("code") not in {"333334", "090001", None}:
                    raise AdapterError("CONNECTOR_SQL_FAILED")
                _remaining(c.deadline_at)
                time.sleep(min(0.25, _remaining(c.deadline_at)))
                payload = c.request("GET", path)
            metadata = payload["resultSetMetaData"]
            fields = metadata.get("rowType", [])

            def pages():
                yield payload.get("data", [])
                for partition in range(1, len(metadata.get("partitionInfo", []))):
                    yield c.request("GET", path + f"?partition={partition}").get("data", [])

            return payload, pages(), fields
        if c.dialect == "bigquery":
            project = _id(conf["project"])
            path = f"/bigquery/v2/projects/{project}/queries"
            budget = conf.get("maximum_bytes_billed", 1024**3)
            if type(budget) is not int or not 1 <= budget <= 1024**4:
                raise AdapterError("CONNECTOR_BUDGET_INVALID")
            payload = c.request(
                "POST",
                path,
                {
                    "query": query,
                    "useLegacySql": False,
                    "timeoutMs": min(10000, max(1, int(_remaining(c.deadline_at) * 1000))),
                    "maxResults": 1000,
                    "maximumBytesBilled": str(budget),
                    "jobTimeoutMs": str(max(1, int(_remaining(c.deadline_at) * 1000))),
                    "location": conf.get("location", "US"),
                },
            )
            job = payload.get("jobReference") or {}
            path += "/" + _id(job.get("jobId"))
            location = quote(str(job.get("location") or conf.get("location", "US")), safe="")
            while not payload.get("jobComplete"):
                if payload.get("errors"):
                    raise AdapterError("CONNECTOR_SQL_FAILED")
                time.sleep(min(0.25, _remaining(c.deadline_at)))
                payload = c.request("GET", path + f"?maxResults=1000&location={location}")
            fields = (payload.get("schema") or {}).get("fields", [])

            def pages():
                current = payload
                seen = set()
                while True:
                    if current.get("errors"):
                        raise AdapterError("CONNECTOR_SQL_FAILED")
                    yield current.get("rows", [])
                    token = current.get("pageToken")
                    if not token:
                        break
                    if token in seen:
                        raise AdapterError("CONNECTOR_PAGINATION_INVALID")
                    seen.add(token)
                    current = c.request(
                        "GET",
                        path
                        + "?"
                        + urlencode(
                            {
                                "maxResults": 1000,
                                "location": job.get("location", conf.get("location", "US")),
                                "pageToken": token,
                            }
                        ),
                    )

            return payload, pages(), fields
        # SQL Statements API; INLINE results prohibit external result URLs.
        payload = c.request(
            "POST",
            "/api/2.0/sql/statements",
            {
                "warehouse_id": conf["warehouse_id"],
                "statement": query,
                "catalog": conf.get("catalog"),
                "schema": conf.get("schema"),
                "format": "JSON_ARRAY",
                "disposition": "INLINE",
                "wait_timeout": "0s",
                "row_limit": 3_000_001,
                "byte_limit": 1024**3,
            },
        )
        identifier = _id(payload.get("statement_id"))
        path = f"/api/2.0/sql/statements/{identifier}"
        while (payload.get("status") or {}).get("state") != "SUCCEEDED":
            if (payload.get("status") or {}).get("state") in {"FAILED", "CANCELED", "CLOSED"}:
                raise AdapterError("CONNECTOR_SQL_FAILED")
            try:
                time.sleep(min(0.25, _remaining(c.deadline_at)))
                payload = c.request("GET", path)
            except Exception:
                # Best effort remote cancellation; a hard process loss remains
                # bounded by the warehouse's configured query timeout.
                try:
                    c.request("POST", path + "/cancel")
                except Exception:
                    pass
                raise
        manifest = payload.get("manifest") or {}
        if manifest.get("truncated"):
            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        fields = (manifest.get("schema") or {}).get("columns", [])

        def pages():
            current, seen = payload.get("result") or {}, set()
            while True:
                if current.get("external_links"):
                    raise AdapterError("CONNECTOR_REDIRECT_DENIED")
                yield current.get("data_array", [])
                link = current.get("next_chunk_internal_link")
                if not link:
                    break
                if (
                    not isinstance(link, str)
                    or not re.fullmatch(re.escape(path) + r"/result/chunks/[0-9]+", link)
                    or link in seen
                ):
                    raise AdapterError("CONNECTOR_REDIRECT_DENIED")
                seen.add(link)
                current = c.request("GET", link)

        return payload, pages(), fields

    def fetchmany(self, count):
        return list(islice(self.rows, count))

    def fetchone(self):
        return next(self.rows, None)

    def close(self):
        self.rows = iter(())
