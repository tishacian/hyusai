"""Native document writes and search bulk receipts; no replay after uncertainty."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import quote

from app.services.connectors.adapters import http
from app.services.connectors.adapters.driver_egress import pinned_python_driver
from app.services.connectors.adapters.nosql import _name, _scope
from app.services.connectors.adapters.object_clients import endpoint
from app.services.connectors.adapters.sql import AdapterError, _json_value, _remaining


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def documents(execution, parameters):
    import pyarrow.parquet as pq

    ordinal = 0
    for filename in execution.get("input_files", []):
        with pq.ParquetFile(filename) as reader:
            for batch in reader.iter_batches(batch_size=500):
                for row in batch.to_pylist():
                    doc = (
                        row["document"]
                        if list(row) == ["document"] and isinstance(row["document"], dict)
                        else row
                    )
                    if list(row) == ["document"] and isinstance(row["document"], str):
                        doc = json.loads(row["document"])
                        if not isinstance(doc, dict):
                            raise AdapterError("CONNECTOR_SCHEMA_INVALID")
                    keys = parameters.get("keys") or []
                    if keys:
                        if any(key not in doc or doc[key] is None for key in keys):
                            raise AdapterError("CONNECTOR_UPSERT_KEY_INVALID")
                        identity = _digest([_json_value(doc[key]) for key in keys])
                    else:
                        identity = _digest([execution["operation_id"], ordinal])
                    yield identity, doc
                    ordinal += 1


def _receipt(execution, rows):
    return {
        "operation_id": execution["operation_id"],
        "contract_digest": execution["contract_digest"],
        "input_sha256": execution["input_sha256"],
        "row_count": rows,
        "applied": True,
    }


def _match(receipt, execution):
    if not receipt:
        return {"operation_id": execution["operation_id"], "applied": None, "outcome": "unknown"}
    if any(
        receipt.get(key) != execution[key]
        for key in ("operation_id", "contract_digest", "input_sha256")
    ):
        raise AdapterError("CONNECTOR_RECEIPT_MISMATCH")
    return {
        key: receipt[key]
        for key in ("operation_id", "contract_digest", "input_sha256", "row_count", "applied")
    }


def _mongo(operation, config, credentials, parameters, deadline, execution, access):
    from pymongo import InsertOne, MongoClient, ReplaceOne

    namespace, table = _scope(config, parameters, access)
    marker = _name(config.get("marker_collection", "agentium_operations"))
    if marker == table:
        raise AdapterError("CONNECTOR_MARKER_TARGET_CONFLICT")
    host, port = config["host"], config.get("port", 27017)
    with pinned_python_driver([(host, port)]):
        with MongoClient(
            host=host,
            port=port,
            username=config["username"],
            password=credentials["password"],
            authSource=config.get("auth_source") or namespace,
            tls=True,
            tlsAllowInvalidCertificates=False,
            tlsAllowInvalidHostnames=False,
            directConnection=True,
            retryReads=False,
            retryWrites=False,
            connectTimeoutMS=min(10000, int(_remaining(deadline) * 1000)),
            serverSelectionTimeoutMS=min(10000, int(_remaining(deadline) * 1000)),
            socketTimeoutMS=int(_remaining(deadline) * 1000),
        ) as client:
            db = client[namespace]
            if marker not in db.list_collection_names():
                raise AdapterError("CONNECTOR_MARKER_REQUIRED")
            if operation == "reconcile_write":
                return _match(db[marker].find_one({"_id": execution["operation_id"]}), execution)
            if table not in db.list_collection_names():
                raise AdapterError("CONNECTOR_SOURCE_NOT_FOUND")
            if operation == "write_upsert":
                keys = parameters.get("keys", [])
                if any(key.startswith("$") or "\x00" in key for key in keys):
                    raise AdapterError("CONNECTOR_UPSERT_KEY_INVALID")
                indexes = list(db[table].list_indexes())
                if not any(
                    list(index.get("key", {})) == keys and (index.get("unique") or keys == ["_id"])
                    for index in indexes
                ):
                    raise AdapterError("CONNECTOR_UNIQUE_KEY_REQUIRED")
            # Preflight duplicate keys before the first mutation. The durable
            # runner has already bound these files to the approved hash.
            seen = set()
            for identity, _ in documents(execution, parameters):
                if identity in seen:
                    raise AdapterError("CONNECTOR_DUPLICATE_KEY")
                seen.add(identity)
            with client.start_session() as session:
                session.start_transaction()
                try:
                    batch = []
                    count = 0
                    for identity, doc in documents(execution, parameters):
                        _remaining(deadline)
                        batch.append(
                            ReplaceOne(
                                {key: {"$eq": doc[key]} for key in parameters["keys"]},
                                doc,
                                upsert=True,
                            )
                            if operation == "write_upsert"
                            else InsertOne({**doc, "_id": doc.get("_id", identity)})
                        )
                        count += 1
                        if len(batch) == 500:
                            db[table].bulk_write(batch, ordered=True, session=session)
                            batch = []
                    if batch:
                        db[table].bulk_write(batch, ordered=True, session=session)
                    receipt = _receipt(execution, count)
                    db[marker].insert_one(
                        {"_id": execution["operation_id"], **receipt}, session=session
                    )
                    session.commit_transaction()
                    return receipt
                except BaseException:
                    try:
                        session.abort_transaction()
                    except Exception:
                        pass
                    raise


def _search(operation, config, credentials, parameters, deadline, execution, access):
    _, table = _scope(config, parameters, access)
    marker = _name(config.get("marker_index", "agentium_operations"))
    if marker == table:
        raise AdapterError("CONNECTOR_MARKER_TARGET_CONFLICT")
    base = endpoint(config["endpoint"])
    headers = {}
    if credentials.get("api_key"):
        headers["Authorization"] = "ApiKey " + credentials["api_key"]
    else:
        import base64

        headers["Authorization"] = (
            "Basic "
            + base64.b64encode(
                (config["username"] + ":" + credentials["password"]).encode()
            ).decode()
        )

    def req(method, path, body=None, ndjson=False):
        return http.json_request(
            method,
            base + path,
            deadline_at=deadline,
            headers={
                **headers,
                "Content-Type": "application/x-ndjson" if ndjson else "application/json",
            },
            content=body if ndjson else json.dumps(body).encode() if body is not None else None,
        )[1]

    operation_id = quote(execution["operation_id"], safe="")
    marker_path = "/" + quote(marker, safe="")
    if operation == "reconcile_write":
        try:
            result = req("GET", marker_path + "/_doc/" + operation_id)
        except AdapterError as exc:
            if exc.code == "CONNECTOR_SOURCE_NOT_FOUND":
                return _match(None, execution)
            raise
        return _match(result.get("_source"), execution)
    # A marker index and target index must pre-exist. No auto-creation is
    # hidden inside an append operation or a provider's permissive defaults.
    req("GET", marker_path + "/_mapping")
    req("GET", "/" + quote(table, safe="") + "/_mapping")
    seen = set()
    for identity, _ in documents(execution, parameters):
        if identity in seen:
            raise AdapterError("CONNECTOR_DUPLICATE_KEY")
        seen.add(identity)

    def flush(lines):
        result = req("POST", "/_bulk?refresh=wait_for", b"".join(lines), ndjson=True)
        if result.get("errors") or any(
            next(iter(item.values())).get("status", 500) >= 300 for item in result.get("items", [])
        ):
            raise AdapterError("CONNECTOR_WRITE_OUTCOME_UNKNOWN")
        if len(result.get("items", [])) * 2 != len(lines):
            raise AdapterError("CONNECTOR_WRITE_OUTCOME_UNKNOWN")

    lines = []
    size = count = 0
    for identity, doc in documents(execution, parameters):
        _remaining(deadline)
        action = "index" if operation == "write_upsert" else "create"
        pair = [
            (json.dumps({action: {"_index": table, "_id": identity}}) + "\n").encode(),
            (json.dumps(_json_value(doc), allow_nan=False) + "\n").encode(),
        ]
        n = sum(map(len, pair))
        if n > 8 * 1024 * 1024:
            raise AdapterError("CONNECTOR_ROW_TOO_LARGE")
        if lines and size + n > 8 * 1024 * 1024:
            flush(lines)
            lines = []
            size = 0
        lines.extend(pair)
        size += n
        count += 1
        if len(lines) >= 1000:
            flush(lines)
            lines = []
            size = 0
    if lines:
        flush(lines)
    receipt = _receipt(execution, count)
    req("PUT", marker_path + "/_create/" + operation_id, receipt)
    return receipt


def execute(operation, config, credentials, parameters, deadline_at, *, dialect, access, execution):
    if operation not in ("write_append", "write_upsert", "reconcile_write") or not execution:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if operation != "reconcile_write" and (access or {}).get("mode") != "read_write":
        raise AdapterError("CONNECTOR_READ_ONLY")
    if operation == "write_upsert" and not parameters.get("keys"):
        raise AdapterError("CONNECTOR_UPSERT_KEY_REQUIRED")
    fn = (
        _mongo
        if dialect == "mongodb"
        else _search
        if dialect in ("elasticsearch", "opensearch")
        else None
    )
    if fn is None:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    try:
        return fn(operation, config, credentials, parameters, deadline_at, execution, access)
    except AdapterError:
        raise
    except ImportError:
        raise AdapterError("CONNECTOR_DRIVER_UNAVAILABLE") from None
    except Exception:
        raise AdapterError("CONNECTOR_WRITE_OUTCOME_UNKNOWN") from None
