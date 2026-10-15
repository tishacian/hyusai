"""Append-only object versions with a compare-and-swap current pointer."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from uuid import UUID

from app.services.connectors.adapters.object_clients import client_for, object_key
from app.services.connectors.adapters.sql import AdapterError, _remaining


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def execute(config, credentials, parameters, deadline_at, *, dialect, execution):
    import pyarrow.parquet as pq

    if "mode" in parameters or parameters.get("format", "parquet") != "parquet":
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    if not isinstance(execution, dict) or not execution.get("input_files"):
        raise AdapterError("CONNECTOR_APPROVAL_REQUIRED")
    input_rows = 0
    for filename in execution["input_files"]:
        source = Path(filename)
        if source.is_symlink() or not source.is_file():
            raise AdapterError("CONNECTOR_ARTIFACT_INVALID")
        with pq.ParquetFile(source) as parquet:
            input_rows += parquet.metadata.num_rows
    if input_rows == 0:
        # The current typed reader cannot publish an empty schema-only stream.
        # Refuse before credentials are used or immutable objects are created.
        raise AdapterError("CONNECTOR_EMPTY_EXPORT_UNSUPPORTED")
    try:
        operation_id = str(UUID(execution["operation_id"]))
    except (ValueError, KeyError):
        raise AdapterError("CONNECTOR_OPERATION_ID_INVALID") from None
    prefix = object_key(
        parameters.get("prefix", config.get("prefix", "")), config.get("prefix", "")
    ).rstrip("/")
    if not prefix:
        raise AdapterError("CONNECTOR_EXPORT_PREFIX_REQUIRED")
    version = f"{prefix}/v={operation_id}"
    client = client_for(dialect, {**config, "_write": True}, credentials, deadline_at)
    parts, count, number = [], 0, 0
    for filename in execution["input_files"]:
        source = Path(filename)
        if source.is_symlink() or not source.is_file():
            raise AdapterError("CONNECTOR_ARTIFACT_INVALID")
        with pq.ParquetFile(source) as parquet:
            for batch in parquet.iter_batches(batch_size=1000):
                _remaining(deadline_at)
                buffer = io.BytesIO()
                with pq.ParquetWriter(buffer, batch.schema, compression="snappy") as writer:
                    writer.write_batch(batch)
                data = buffer.getvalue()
                if len(data) > 64 * 1024 * 1024:
                    raise AdapterError("CONNECTOR_EXPORT_PART_TOO_LARGE")
                key = f"{version}/part-{number:06d}.parquet"
                client.put(key, data)
                parts.append(
                    {
                        "key": key,
                        "rows": batch.num_rows,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
                count += batch.num_rows
                number += 1
                if len(parts) > 10000:
                    raise AdapterError("CONNECTOR_EXPORT_TOO_LARGE")
    manifest = {
        "version": 1,
        "operation_id": operation_id,
        "contract_digest": execution["contract_digest"],
        "row_count": count,
        "input_sha256": execution["input_sha256"],
        "parts": parts,
    }
    payload = _json(manifest)
    manifest_key = f"{version}/manifest.json"
    client.put(manifest_key, payload)
    manifest_digest = hashlib.sha256(payload).hexdigest()
    pointer = {"operation_id": operation_id, "manifest": manifest_key, "sha256": manifest_digest}
    # The successful pointer CAS is the publication boundary. No file is ever
    # overwritten in place, and a lost answer must be reconciled by this ID.
    etag = client.put(
        f"{prefix}/_LATEST.json",
        _json(pointer),
        expected_etag=parameters.get("expected_pointer_etag"),
    )
    return {
        "operation_id": operation_id,
        "applied": True,
        "contract_digest": execution["contract_digest"],
        "row_count": count,
        "manifest": manifest_key,
        "manifest_sha256": manifest_digest,
        "pointer_etag": etag,
        "source": "real",
    }


def reconcile(config, credentials, parameters, deadline_at, *, dialect, operation_id):
    client = client_for(dialect, config, credentials, deadline_at)
    prefix = object_key(
        parameters.get("prefix", config.get("prefix", "")), config.get("prefix", "")
    ).rstrip("/")
    data, _ = client.read_small(f"{prefix}/_LATEST.json")
    try:
        pointer = json.loads(data)
    except ValueError:
        raise AdapterError("CONNECTOR_RESPONSE_INVALID") from None
    if pointer.get("operation_id") != operation_id:
        return {"operation_id": operation_id, "applied": None, "outcome": "unknown"}
    expected = f"{prefix}/v={operation_id}/manifest.json"
    if pointer.get("manifest") != expected:
        raise AdapterError("CONNECTOR_RESPONSE_INVALID")
    manifest, _ = client.read_small(expected)
    if hashlib.sha256(manifest).hexdigest() != pointer.get("sha256"):
        raise AdapterError("CONNECTOR_RESPONSE_INVALID")
    body = json.loads(manifest)
    if body.get("operation_id") != operation_id:
        raise AdapterError("CONNECTOR_RESPONSE_INVALID")
    return {
        "operation_id": operation_id,
        "applied": True,
        "contract_digest": body["contract_digest"],
        "row_count": body["row_count"],
        "manifest": expected,
        "manifest_sha256": pointer["sha256"],
    }
