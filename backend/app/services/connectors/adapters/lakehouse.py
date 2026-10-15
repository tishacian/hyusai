"""Guarded Delta Sharing, Unity Catalog and Iceberg REST snapshot readers.

Ephemeral cloud credentials and signed URLs stay in this child process. Every
metadata and object request traverses the common TLS/DNS/deadline guard. Native
Delta, Arrow and Avro readers open local files only. Unsupported delete semantics
fail closed instead of returning deleted rows as if they were current.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from app.services.connectors.adapters import http
from app.services.connectors.adapters.lakehouse_files import stage_files
from app.services.connectors.adapters.object_clients import (
    AzureClient,
    GCSClient,
    ObjectClient,
    S3Client,
    object_key,
)
from app.services.connectors.adapters.object_store import _bounded_int, _snapshot
from app.services.connectors.adapters.sql import AdapterError, _remaining
from app.services.connectors.connections import ConnectionError
from app.services.connectors.lakehouse_contracts import validate_config
from app.services.connectors.tool_contracts import allowed_url

MAX_BYTES = 1024**3
MAX_OBJECTS = 10000


def _url(config, url, *, download=False):
    try:
        return allowed_url(
            {"allowed_origins": config["download_origins"]} if download else config, url
        )
    except ConnectionError:
        raise AdapterError(
            "CONNECTOR_DOWNLOAD_ORIGIN_DENIED" if download else "CONNECTOR_ORIGIN_DENIED"
        ) from None


def _name(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 255
        or any(ord(c) < 32 for c in value)
        or any(c in value for c in "/\\")
        or value in (".", "..")
    ):
        raise AdapterError("CONNECTOR_IDENTIFIER_INVALID")
    return value


def _access(schema, table, access):
    access = access or {}
    schemas, tables = access.get("allowed_schemas") or [], access.get("allowed_tables") or []
    if (
        schemas
        and schema not in schemas
        or tables
        and table not in tables
        and f"{schema}.{table}" not in tables
    ):
        raise AdapterError("CONNECTOR_SOURCE_FORBIDDEN")


class Catalog:
    def __init__(self, config, credentials, deadline):
        validate_config(config)
        self.config, self.deadline = config, deadline
        self.base = config["base_url"].rstrip("/")
        token = credentials.get("token")
        if not isinstance(token, str) or not token or any(ord(c) < 32 for c in token):
            raise AdapterError("CONNECTOR_CREDENTIAL_REQUIRED")
        self.headers = {"Authorization": "Bearer " + token}

    def get(self, path, *, params=None):
        url = self.base + path + ("?" + urlencode(params) if params else "")
        _, value = http.json_request(
            "GET", _url(self.config, url), headers=self.headers, deadline_at=self.deadline
        )
        if not isinstance(value, dict):
            raise AdapterError("CONNECTOR_RESPONSE_INVALID")
        return value

    def post(self, path, body):
        _, value = http.json_request(
            "POST",
            _url(self.config, self.base + path),
            headers={**self.headers, "Content-Type": "application/json"},
            content=json.dumps(body).encode(),
            deadline_at=self.deadline,
        )
        if not isinstance(value, dict):
            raise AdapterError("CONNECTOR_RESPONSE_INVALID")
        return value

    def pages(self, path, field, *, params=None, token="pageToken", next_token="nextPageToken"):
        params, seen, values = dict(params or {}), set(), []
        while True:
            response = self.get(path, params=params)
            batch = response.get(field, [])
            if not isinstance(batch, list) or any(not isinstance(v, dict) for v in batch):
                raise AdapterError("CONNECTOR_RESPONSE_INVALID")
            values.extend(batch)
            if len(values) > MAX_OBJECTS:
                raise AdapterError("CONNECTOR_CATALOG_TOO_LARGE")
            cursor = response.get(next_token)
            if not cursor:
                return values
            if not isinstance(cursor, str) or len(cursor) > 8192 or cursor in seen:
                raise AdapterError("CONNECTOR_PAGINATION_INVALID")
            seen.add(cursor)
            params[token] = cursor


def _sharing(catalog, operation, parameters, directory, access, options):
    share = quote(_name(catalog.config["share"]), safe="")
    root = "/shares/" + share
    if operation in ("test", "catalog", "list"):
        schemas = catalog.pages(root + "/schemas", "items")
        tables = []
        for item in schemas:
            schema = _name(item.get("name"))
            if (access or {}).get("allowed_schemas") and schema not in access["allowed_schemas"]:
                continue
            for table in catalog.pages(
                root + "/schemas/" + quote(schema, safe="") + "/tables", "items"
            ):
                name = _name(table.get("name"))
                try:
                    _access(schema, name, access)
                except AdapterError:
                    continue
                tables.append({"schema": schema, "name": name})
                if len(tables) > MAX_OBJECTS:
                    raise AdapterError("CONNECTOR_CATALOG_TOO_LARGE")
        return {"source": "real", "tables": tables}
    schema, table = _name(parameters.get("schema")), _name(parameters.get("table"))
    _access(schema, table, access)
    path = (
        root + "/schemas/" + quote(schema, safe="") + "/tables/" + quote(table, safe="") + "/query"
    )
    headers, payload = http.request(
        "POST",
        _url(catalog.config, catalog.base + path),
        headers={
            **catalog.headers,
            "Content-Type": "application/json",
            "delta-sharing-capabilities": "responseformat=parquet",
        },
        content=b"{}",
        deadline_at=catalog.deadline,
        max_bytes=16 * 1024**2,
    )
    try:
        lines = [json.loads(line) for line in payload.splitlines() if line.strip()]
        if len(lines) > MAX_OBJECTS + 2 or len(lines) < 2:
            raise ValueError()
        protocol, metadata = lines[0]["protocol"], lines[1]["metaData"]
        if protocol.get("minReaderVersion", 1) != 1 or protocol.get("readerFeatures"):
            raise AdapterError("CONNECTOR_DELTA_FEATURE_UNSUPPORTED")
        if metadata.get("configuration", {}).get("delta.columnMapping.mode", "none") != "none":
            raise AdapterError("CONNECTOR_DELTA_FEATURE_UNSUPPORTED")
        schema_spec = json.loads(metadata["schemaString"])
        columns = [
            {"name": _name(f["name"]), "type": f["type"], "required": not f.get("nullable", True)}
            for f in schema_spec["fields"]
        ]
        if len(columns) > 2000 or len({c["name"] for c in columns}) != len(columns):
            raise ValueError()
        version = headers.get("delta-table-version")
        if version is None or not str(version).isdigit():
            raise AdapterError("CONNECTOR_SNAPSHOT_REQUIRED")
        files = []
        for line in lines[2:]:
            item = line["file"]
            if item.get("deletionVector") or item.get("deletionVectors"):
                raise AdapterError("CONNECTOR_DELTA_FEATURE_UNSUPPORTED")
            identity = item["id"]
            if not isinstance(identity, str) or not identity or len(identity) > 1024:
                raise ValueError()
            files.append(
                {
                    "id": identity,
                    "url": _url(catalog.config, item["url"], download=True),
                    "size": item["size"],
                    "partitions": item.get("partitionValues", {}),
                }
            )
    except (KeyError, TypeError, ValueError):
        raise AdapterError("CONNECTOR_RESPONSE_INVALID") from None

    def download(item, path, maximum):
        # Never forward catalog bearer credentials to presigned object URLs.
        return http.download(item["url"], path, deadline_at=catalog.deadline, max_bytes=maximum)

    return stage_files(
        files,
        columns,
        directory,
        download=download,
        operation=operation,
        deadline=catalog.deadline,
        snapshot={
            "protocol": "delta_sharing",
            "table_id": metadata.get("id"),
            "version": int(version),
        },
        **options,
    )


class TemporaryGCS(GCSClient):
    def __init__(self, config, credentials, deadline):
        ObjectClient.__init__(self, config, credentials, deadline)
        self.base = "https://storage.googleapis.com"
        self.token = credentials["oauth_token"]


def _temporary_client(location, vended, config, deadline):
    parsed = urlsplit(location)
    if parsed.query or parsed.fragment or not parsed.netloc:
        raise AdapterError("CONNECTOR_STORAGE_LOCATION_INVALID")
    prefix = object_key(parsed.path.lstrip("/")).rstrip("/")
    if parsed.scheme == "s3":
        creds = vended.get("aws_temp_credentials") or {}
        client = S3Client(
            {
                "bucket": parsed.netloc,
                "prefix": prefix,
                "region": config.get("region", "us-east-1"),
            },
            {
                "access_key": creds.get("access_key_id"),
                "secret_key": creds.get("secret_access_key"),
                "session_token": creds.get("session_token"),
            },
            deadline,
        )
        if not client.session_token:
            raise AdapterError("CONNECTOR_TEMPORARY_CREDENTIAL_REQUIRED")
    elif parsed.scheme in ("abfs", "abfss"):
        match = re.fullmatch(r"([a-z0-9-]+)@([a-z0-9]+)\.dfs\.core\.windows\.net", parsed.netloc)
        creds = vended.get("azure_user_delegation_sas") or {}
        if not match or not creds.get("sas_token"):
            raise AdapterError("CONNECTOR_STORAGE_LOCATION_INVALID")
        client = AzureClient(
            {"bucket": match[1], "account": match[2], "prefix": prefix, "auth_mode": "sas"},
            {"sas_token": creds["sas_token"]},
            deadline,
        )
    elif parsed.scheme == "gs":
        creds = vended.get("gcp_oauth_token") or {}
        if not creds.get("oauth_token"):
            raise AdapterError("CONNECTOR_TEMPORARY_CREDENTIAL_REQUIRED")
        client = TemporaryGCS({"bucket": parsed.netloc, "prefix": prefix}, creds, deadline)
    else:
        raise AdapterError("CONNECTOR_STORAGE_SCHEME_UNSUPPORTED")
    # GCS constructs some URLs without signed(); its base is fixed and checked.
    _url(config, client.base, download=True)
    original_signed = client.signed

    def signed(*args, **kwargs):
        url, headers = original_signed(*args, **kwargs)
        _url(config, url, download=True)
        return url, headers

    client.signed = signed
    return client


def _unity(catalog, operation, parameters, directory, access, options):
    name = _name(catalog.config["catalog"])
    root = "/api/2.1/unity-catalog"
    if operation in ("test", "catalog", "list"):
        schemas = catalog.pages(
            root + "/schemas",
            "schemas",
            params={"catalog_name": name},
            token="page_token",
            next_token="next_page_token",
        )
        tables = []
        for item in schemas:
            schema = _name(item.get("name"))
            if (access or {}).get("allowed_schemas") and schema not in access["allowed_schemas"]:
                continue
            for item in catalog.pages(
                root + "/tables",
                "tables",
                params={"catalog_name": name, "schema_name": schema},
                token="page_token",
                next_token="next_page_token",
            ):
                table = _name(item.get("name"))
                try:
                    _access(schema, table, access)
                except AdapterError:
                    continue
                tables.append(
                    {"schema": schema, "name": table, "format": item.get("data_source_format")}
                )
                if len(tables) > MAX_OBJECTS:
                    raise AdapterError("CONNECTOR_CATALOG_TOO_LARGE")
        return {"source": "real", "tables": tables}
    schema, table = _name(parameters.get("schema")), _name(parameters.get("table"))
    _access(schema, table, access)
    value = catalog.get(root + "/tables/" + quote(f"{name}.{schema}.{table}", safe=""))
    if value.get("data_source_format") != "DELTA" or not value.get("table_id"):
        raise AdapterError("CONNECTOR_LAKEHOUSE_FORMAT_UNSUPPORTED")
    temporary = catalog.post(
        root + "/temporary-table-credentials", {"table_id": value["table_id"], "operation": "READ"}
    )
    expiry = temporary.get("expiration_time")
    if type(expiry) is not int or expiry <= datetime.now(UTC).timestamp() * 1000:
        raise AdapterError("CONNECTOR_TEMPORARY_CREDENTIAL_EXPIRED")
    credential_deadline = min(
        datetime.fromisoformat(catalog.deadline.replace("Z", "+00:00")),
        datetime.fromtimestamp(expiry / 1000, UTC),
    ).isoformat()
    client = _temporary_client(
        value.get("storage_location", ""), temporary, catalog.config, credential_deadline
    )
    objects = _snapshot(client, client.root, MAX_OBJECTS, options["max_bytes"], catalog.deadline)
    from app.services.connectors.adapters.delta_reader import stage_delta

    result = stage_delta(
        client, objects, directory, operation=operation, deadline=catalog.deadline, **options
    )
    result["snapshot"] = {
        "protocol": "unity_catalog",
        "table_id": value["table_id"],
        "version": result["delta_version"],
    }
    return result


def _iceberg_location(location, catalog, storage_config, path, maximum):
    parsed = urlsplit(location)
    if parsed.scheme == "https":
        return http.download(
            _url(catalog.config, location, download=True),
            path,
            deadline_at=catalog.deadline,
            max_bytes=maximum,
        )
    client = _iceberg_client(location, catalog, storage_config)
    url, headers = client.signed("GET", client.root)
    return http.download(
        url, path, deadline_at=catalog.deadline, headers=headers, max_bytes=maximum
    )


def _iceberg_client(location, catalog, storage_config):
    parsed = urlsplit(location)
    if parsed.scheme == "s3":
        vended = {
            "aws_temp_credentials": {
                "access_key_id": storage_config.get("s3.access-key-id"),
                "secret_access_key": storage_config.get("s3.secret-access-key"),
                "session_token": storage_config.get("s3.session-token"),
            }
        }
    elif parsed.scheme in ("abfs", "abfss"):
        account = parsed.netloc.split("@")[-1].split(".")[0]
        vended = {
            "azure_user_delegation_sas": {
                "sas_token": storage_config.get(f"adls.sas-token.{account}")
            }
        }
    elif parsed.scheme == "gs":
        vended = {"gcp_oauth_token": {"oauth_token": storage_config.get("gcs.oauth2.token")}}
    else:
        raise AdapterError("CONNECTOR_STORAGE_SCHEME_UNSUPPORTED")
    return _temporary_client(location, vended, catalog.config, catalog.deadline)


def _iceberg(catalog, operation, parameters, directory, access, options, *, return_snapshot=False):
    catalog.headers["X-Iceberg-Access-Delegation"] = "vended-credentials"
    root = "/v1" + (
        "/" + quote(_name(catalog.config["prefix"]), safe="")
        if catalog.config.get("prefix")
        else ""
    )
    if operation in ("test", "catalog", "list"):
        # Namespace components use the protocol unit-separator, never slash joins.
        body = catalog.get(root + "/namespaces")
        namespaces = body.get("namespaces", [])
        if (
            not isinstance(namespaces, list)
            or len(namespaces) > MAX_OBJECTS
            or body.get("next-page-token")
        ):
            raise AdapterError("CONNECTOR_CATALOG_PAGINATION_UNSUPPORTED")
        tables = []
        for namespace in namespaces:
            if not isinstance(namespace, list) or not namespace:
                raise AdapterError("CONNECTOR_RESPONSE_INVALID")
            schema = ".".join(_name(part) for part in namespace)
            if (access or {}).get("allowed_schemas") and schema not in access["allowed_schemas"]:
                continue
            body = catalog.get(
                root + "/namespaces/" + quote("\x1f".join(namespace), safe="") + "/tables"
            )
            if body.get("next-page-token"):
                raise AdapterError("CONNECTOR_CATALOG_PAGINATION_UNSUPPORTED")
            for item in body.get("identifiers", []):
                table = _name(item.get("name"))
                try:
                    _access(schema, table, access)
                except AdapterError:
                    continue
                tables.append({"schema": schema, "name": table})
                if len(tables) > MAX_OBJECTS:
                    raise AdapterError("CONNECTOR_CATALOG_TOO_LARGE")
        return {"source": "real", "tables": tables}
    schema, table = _name(parameters.get("schema")), _name(parameters.get("table"))
    _access(schema, table, access)
    namespace = "\x1f".join(_name(p) for p in schema.split("."))
    table_path = (
        root + "/namespaces/" + quote(namespace, safe="") + "/tables/" + quote(table, safe="")
    )
    body = catalog.get(table_path)
    metadata, storage_config = body.get("metadata"), body.get("config", {})
    if (
        not isinstance(metadata, dict)
        or not isinstance(storage_config, dict)
        or metadata.get("format-version") not in (1, 2)
    ):
        raise AdapterError("CONNECTOR_ICEBERG_FEATURE_UNSUPPORTED")
    if return_snapshot == "metadata":
        return {"metadata": metadata, "storage_config": storage_config, "table_path": table_path}
    current_schema = next(
        (
            s
            for s in metadata.get("schemas", [])
            if s.get("schema-id") == metadata.get("current-schema-id")
        ),
        metadata.get("schema"),
    )
    if not isinstance(current_schema, dict):
        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
    columns = current_schema.get("fields", [])
    if (
        not columns
        or len(columns) > 2000
        or any(
            not isinstance(f, dict)
            or type(f.get("id")) is not int
            or not isinstance(f.get("type"), str)
            for f in columns
        )
    ):
        raise AdapterError("CONNECTOR_ICEBERG_SCHEMA_UNSUPPORTED")
    if len({f["id"] for f in columns}) != len(columns) or len(
        {_name(f.get("name")) for f in columns}
    ) != len(columns):
        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
    snapshot_id = metadata.get("current-snapshot-id")
    snapshot = next(
        (s for s in metadata.get("snapshots", []) if s.get("snapshot-id") == snapshot_id), None
    )
    files, downloaded, manifests = [], 0, []

    def avro(location, name):
        nonlocal downloaded
        from fastavro import reader

        path = directory / name
        try:
            _, size, _ = _iceberg_location(
                location, catalog, storage_config, path, options["max_bytes"] - downloaded
            )
            downloaded += size
            with path.open("rb") as handle:
                rows = []
                for row in reader(handle):
                    _remaining(catalog.deadline)
                    rows.append(row)
                    if len(rows) > MAX_OBJECTS:
                        raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                return rows
        finally:
            path.unlink(missing_ok=True)

    if snapshot is not None:
        if not snapshot.get("manifest-list"):
            raise AdapterError("CONNECTOR_ICEBERG_FEATURE_UNSUPPORTED")
        manifests = avro(snapshot["manifest-list"], "manifest-list.avro")
        for index, manifest in enumerate(manifests):
            if manifest.get("content", 0) != 0 or manifest.get("key_metadata"):
                raise AdapterError("CONNECTOR_ICEBERG_DELETES_UNSUPPORTED")
            for entry in avro(manifest["manifest_path"], f"manifest-{index}.avro"):
                if entry.get("status") == 2:
                    continue
                if entry.get("status") not in (0, 1):
                    raise AdapterError("CONNECTOR_RESPONSE_INVALID")
                data = entry["data_file"]
                if data.get("content", 0) != 0 or data.get("key_metadata"):
                    raise AdapterError("CONNECTOR_ICEBERG_DELETES_UNSUPPORTED")
                if data.get("file_format", "").upper() != "PARQUET":
                    raise AdapterError("CONNECTOR_LAKEHOUSE_FORMAT_UNSUPPORTED")
                location = data["file_path"]
                files.append(
                    {
                        "id": hashlib.sha256(location.encode()).hexdigest(),
                        "url": location,
                        "size": data["file_size_in_bytes"],
                        **({"data_file": data} if return_snapshot else {}),
                    }
                )
                if len(files) > MAX_OBJECTS:
                    raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
    elif snapshot_id not in (None, -1):
        raise AdapterError("CONNECTOR_SNAPSHOT_REQUIRED")

    if return_snapshot:
        return {
            "metadata": metadata,
            "storage_config": storage_config,
            "columns": columns,
            "files": files,
            "manifests": manifests,
            "downloaded": downloaded,
            "table_path": table_path,
        }

    def download(item, path, maximum):
        return _iceberg_location(item["url"], catalog, storage_config, path, maximum)

    return stage_files(
        files,
        columns,
        directory,
        download=download,
        operation=operation,
        deadline=catalog.deadline,
        snapshot={
            "protocol": "iceberg_rest",
            "table_uuid": metadata.get("table-uuid"),
            # Iceberg snapshot IDs are int64, beyond JavaScript's exact range.
            "snapshot_id": str(snapshot_id) if snapshot_id not in (None, -1) else None,
            "schema_id": metadata.get("current-schema-id"),
        },
        iceberg=True,
        **{**options, "max_bytes": options["max_bytes"] - downloaded},
    )


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
    if dialect == "iceberg_rest" and operation in {
        "write_append",
        "write_overwrite",
        "write_upsert",
        "write_preview",
        "reconcile_write",
    }:
        from app.services.connectors.adapters.iceberg_write import execute_write

        return execute_write(
            operation,
            config,
            credentials,
            parameters,
            deadline_at,
            output_dir,
            access=access,
            execution=execution,
        )
    if operation not in ("test", "catalog", "list", "table", "preview", "import"):
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {"schema", "table", "limit", "max_rows", "max_bytes"}:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    options = {
        "max_bytes": _bounded_int(parameters, "max_bytes", MAX_BYTES, MAX_BYTES),
        "max_rows": _bounded_int(parameters, "max_rows", 10_000_000, 10_000_000),
        "preview_limit": _bounded_int(
            parameters, "limit", (limits or {}).get("preview_rows", 100), 1000
        ),
    }
    adapter = {"delta_sharing": _sharing, "unity_catalog": _unity, "iceberg_rest": _iceberg}.get(
        dialect
    )
    if adapter is None:
        raise AdapterError("CONNECTOR_DIALECT_UNSUPPORTED")
    try:
        result = adapter(
            Catalog(config, credentials, deadline_at),
            operation,
            parameters,
            Path(output_dir),
            access,
            options,
        )
        if operation == "test":
            if result.get("source") != "real":
                raise AdapterError("CONNECTOR_RESPONSE_INVALID")
            # Successful catalog requests prove connectivity, not a software
            # version. Runtime identity remains absent without that observation.
            result = {**result, "connected": True}
        return result
    except ConnectionError as exc:
        raise AdapterError(exc.code) from None
    except (KeyError, TypeError, ValueError, AttributeError):
        # Protocol responses are untrusted. Do not serialize remote values or URLs.
        raise AdapterError("CONNECTOR_RESPONSE_INVALID") from None
