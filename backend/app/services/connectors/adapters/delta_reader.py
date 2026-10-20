"""Read a frozen Delta object set through the guarded transport, then locally.

The native Delta reader never receives a remote URL or cloud credentials. Log
paths are checked before parsing; only active files from the captured listing
are materialized. An unsupported table protocol fails instead of flattening it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.services.connectors.adapters.object_clients import object_key
from app.services.connectors.adapters.sql import AdapterError, _json_value, _remaining, _typed_value


def _relative(value):
    if not isinstance(value, str) or not value or urlsplit(value).scheme:
        raise AdapterError("CONNECTOR_DELTA_PATH_INVALID")
    decoded = unquote(value)
    object_key(decoded)
    return decoded


def _action(action):
    if action.get("sidecar") or action.get("checkpointMetadata"):
        raise AdapterError("CONNECTOR_DELTA_FEATURE_UNSUPPORTED")
    for name in ("add", "remove"):
        item = action.get(name)
        if item:
            _relative(item.get("path"))
            if item.get("deletionVector"):
                # A vector points to an additional object and changes row
                # visibility. Until it is copied and qualified, refuse it.
                raise AdapterError("CONNECTOR_DELTA_FEATURE_UNSUPPORTED")
    metadata = action.get("metaData")
    if (
        metadata
        and metadata.get("configuration", {}).get("delta.columnMapping.mode", "none") != "none"
    ):
        raise AdapterError("CONNECTOR_DELTA_FEATURE_UNSUPPORTED")


def _check_log(path):
    if path.suffix == ".json":
        with path.open() as handle:
            while line := handle.readline(4 * 1024 * 1024 + 1):
                if len(line) > 4 * 1024 * 1024:
                    raise AdapterError("CONNECTOR_DELTA_LOG_TOO_LARGE")
                if line.strip():
                    _action(json.loads(line))
    elif path.suffix == ".parquet":
        import pyarrow.parquet as pq

        with pq.ParquetFile(path) as parquet:
            for batch in parquet.iter_batches(batch_size=128):
                for row in batch.to_pylist():
                    _action(row)


def stage_delta(
    client, objects, directory, *, operation, max_rows, max_bytes, deadline, preview_limit
):
    roots = {
        item["key"].split("/_delta_log/", 1)[0] for item in objects if "/_delta_log/" in item["key"]
    }
    if len(roots) != 1:
        raise AdapterError("CONNECTOR_TABLE_ROOT_REQUIRED")
    prefix = roots.pop()
    local_root = directory / "delta-source"
    local_root.mkdir(mode=0o700)
    by_key = {item["key"]: item for item in objects}
    sources = []
    for key, item in by_key.items():
        suffix = key.removeprefix(prefix + "/")
        if not suffix.startswith("_delta_log/"):
            continue
        name = suffix.removeprefix("_delta_log/")
        if not re.fullmatch(
            r"(?:[0-9]{20}\.json|[0-9]{20}\.checkpoint(?:\.[0-9]{10}\.[0-9]{10})?\.parquet|_last_checkpoint)",
            name,
        ):
            continue
        _remaining(deadline)
        path = local_root / suffix
        path.parent.mkdir(exist_ok=True)
        _, _, sha = client.download(item, path, max_bytes)
        if name != "_last_checkpoint":
            _check_log(path)
        else:
            metadata = json.loads(path.read_text())
            if set(metadata) & {"v2Checkpoint", "sidecarFiles", "checkpointSchema"}:
                raise AdapterError("CONNECTOR_DELTA_FEATURE_UNSUPPORTED")
            if type(metadata.get("version")) is not int or metadata["version"] < 0:
                raise AdapterError("CONNECTOR_DELTA_LOG_INVALID")
        sources.append({**item, "sha256": sha})
    from deltalake import DeltaTable

    table = DeltaTable(str(local_root))
    active = table.file_uris()
    size = 0
    for uri in active:
        parsed = urlsplit(uri)
        if parsed.scheme not in ("", "file") or parsed.netloc:
            raise AdapterError("CONNECTOR_DELTA_PATH_INVALID")
        path = Path(unquote(parsed.path)).resolve()
        if not path.is_relative_to(local_root.resolve()):
            raise AdapterError("CONNECTOR_DELTA_PATH_INVALID")
        relative = path.relative_to(local_root.resolve()).as_posix()
        item = by_key.get(prefix + "/" + relative)
        if not item:
            raise AdapterError("CONNECTOR_SOURCE_CHANGED")
        size += item["size"]
        if size > max_bytes:
            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        path.parent.mkdir(parents=True, exist_ok=True)
        _, _, sha = client.download(item, path, max_bytes)
        sources.append({**item, "sha256": sha})
    arrow = table.to_pyarrow_dataset()
    columns = arrow.schema.names
    artifact = directory / "rows.jsonl"
    digest = hashlib.sha256()
    count = written = 0
    preview = []
    with artifact.open("xb") as handle:
        scanner = arrow.scanner(
            batch_size=1000, use_threads=False, batch_readahead=0, fragment_readahead=0
        )
        done = False
        for batch in scanner.to_batches():
            for row in batch.to_pylist():
                _remaining(deadline)
                count += 1
                if count > max_rows:
                    raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                values = [
                    (_json_value if operation in ("preview", "table") else _typed_value)(row[name])
                    for name in columns
                ]
                data = (json.dumps(values, allow_nan=False, ensure_ascii=False) + "\n").encode()
                written += len(data)
                if written > max_bytes:
                    raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                if operation in ("preview", "table"):
                    preview.append(values)
                    if written > 4 * 1024 * 1024:
                        raise AdapterError("CONNECTOR_PREVIEW_TOO_LARGE")
                    if count >= preview_limit:
                        done = True
                        break
                else:
                    handle.write(data)
                    digest.update(data)
            if done:
                break
    fingerprint = hashlib.sha256(
        json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output = {
        "columns": columns,
        "row_count": count,
        "source": "real",
        "consistency": "snapshot",
        "source_objects": sources,
        "source_fingerprint": fingerprint,
        "delta_version": table.version(),
    }
    if operation in ("preview", "table"):
        return {**output, "rows": preview}
    return {
        **output,
        "artifact": "rows.jsonl",
        "format": "typed-jsonl-v2",
        "bytes": written,
        "sha256": digest.hexdigest(),
    }
