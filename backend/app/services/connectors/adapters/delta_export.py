"""Delta-rs writes locally; guarded object transport publishes one conditional log.

Existing data parts are never fetched, overwritten or vacuumed. New immutable
parts may become orphans after a conflict; only the next log version makes them
visible to readers. A lost response is reconciled by commit metadata, not retry.
"""

from __future__ import annotations

import hashlib
import json
import re

from app.services.connectors.adapters.delta_reader import _action, _check_log, _relative
from app.services.connectors.adapters.object_clients import client_for, object_key
from app.services.connectors.adapters.sql import AdapterError, _remaining
from app.services.connectors.adapters.sql_write import _execution

LOG_NAME = re.compile(
    r"(?:[0-9]{20}\.json|[0-9]{20}\.checkpoint(?:\.[0-9]{10}\.[0-9]{10})?\.parquet|_last_checkpoint)"
)
MAX_LOG_BYTES = 256 * 1024**2
MAX_PART_BYTES = 128 * 1024**2
METADATA = {
    "operation_id": "agentium_operation_id",
    "contract_digest": "agentium_contract_digest",
    "input_sha256": "agentium_input_sha256",
}


def _prefix(config, parameters):
    if (
        set(parameters) - {"prefix", "format", "mode"}
        or parameters.get("format") != "delta"
        or parameters.get("mode", "append") not in {"append", "overwrite"}
    ):
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    value = object_key(
        parameters.get("prefix", config.get("prefix", "")), config.get("prefix", "")
    ).rstrip("/")
    if not value:
        raise AdapterError("CONNECTOR_EXPORT_PREFIX_REQUIRED")
    return value


def _logs(client, prefix, deadline):
    result, seen, cursor, bytes_count = [], set(), None, 0
    root = prefix + "/_delta_log/"
    while True:
        _remaining(deadline)
        batch, next_cursor = client.list_page(root, cursor)
        for item in batch:
            key = object_key(item["key"], root.rstrip("/"))
            name = key.removeprefix(root)
            if not LOG_NAME.fullmatch(name):
                continue
            if (
                key in seen
                or not item.get("etag")
                or type(item.get("size")) is not int
                or item["size"] < 0
            ):
                raise AdapterError("CONNECTOR_OBJECT_IDENTITY_INVALID")
            seen.add(key)
            bytes_count += item["size"]
            if len(result) >= 10000 or bytes_count > MAX_LOG_BYTES:
                raise AdapterError("CONNECTOR_DELTA_LOG_TOO_LARGE")
            result.append(item)
        if next_cursor is None:
            break
        marker = "cursor:" + str(next_cursor)
        if next_cursor == cursor or marker in seen:
            raise AdapterError("CONNECTOR_PAGINATION_INVALID")
        seen.add(marker)
        cursor = next_cursor
    return sorted(result, key=lambda item: item["key"])


def _stage_logs(client, logs, prefix, directory, deadline):
    local = directory / "delta-export"
    (local / "_delta_log").mkdir(parents=True, mode=0o700)
    for item in logs:
        _remaining(deadline)
        path = local / item["key"].removeprefix(prefix + "/")
        if not path.resolve().is_relative_to(local.resolve()):
            raise AdapterError("CONNECTOR_DELTA_PATH_INVALID")
        client.download(item, path, MAX_LOG_BYTES)
        if path.name != "_last_checkpoint":
            _check_log(path)
        else:
            checkpoint = json.loads(path.read_text())
            if set(checkpoint) & {"v2Checkpoint", "sidecarFiles", "checkpointSchema"}:
                raise AdapterError("CONNECTOR_DELTA_FEATURE_UNSUPPORTED")
            if type(checkpoint.get("version")) is not int or checkpoint["version"] < 0:
                raise AdapterError("CONNECTOR_DELTA_LOG_INVALID")
    return local


def _receipt(info, version, log, digest, execution):
    if any(info.get(remote) != execution[local] for local, remote in METADATA.items()):
        raise AdapterError("CONNECTOR_IDEMPOTENCY_CONFLICT")
    count = info.get("agentium_input_rows")
    if isinstance(count, str) and count.isdecimal():
        count = int(count)
    if type(count) is not int or count < 0:
        raise AdapterError("CONNECTOR_RECEIPT_INVALID")
    return {
        "operation_id": execution["operation_id"],
        "contract_digest": execution["contract_digest"],
        "input_sha256": execution["input_sha256"],
        "applied": True,
        "format": "delta",
        "delta_version": version,
        "delta_log": log,
        "delta_log_sha256": digest,
        "row_count": count,
        "outcome_check": "conditional_put",
        "source": "real",
    }


def _find_commit(local, prefix, execution):
    found = None
    for path in sorted((local / "_delta_log").glob("*.json")):
        if not re.fullmatch(r"[0-9]{20}\.json", path.name):
            continue
        with path.open() as handle:
            for line in handle:
                action = json.loads(line)
                info = action.get("commitInfo") or {}
                if info.get(METADATA["operation_id"]) == execution["operation_id"]:
                    if found:
                        raise AdapterError("CONNECTOR_IDEMPOTENCY_CONFLICT")
                    found = _receipt(
                        info,
                        int(path.stem),
                        prefix + "/_delta_log/" + path.name,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                        execution,
                    )
    return found


def execute(config, credentials, parameters, deadline_at, output_dir, *, dialect, execution):
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
    from deltalake import CommitProperties, DeltaTable, write_deltalake

    prefix = _prefix(config, parameters)
    paths = _execution(execution)
    row_count = 0
    for path in paths:
        with pq.ParquetFile(path) as parquet:
            row_count += parquet.metadata.num_rows
    if row_count > 10_000_000:
        raise AdapterError("CONNECTOR_EXPORT_TOO_LARGE")
    client = client_for(dialect, {**config, "_write": True}, credentials, deadline_at)
    logs = _logs(client, prefix, deadline_at)
    local = _stage_logs(client, logs, prefix, output_dir, deadline_at)
    existing = _find_commit(local, prefix, execution)
    if existing:
        return {**existing, "reconciled": True}
    if logs:
        table = DeltaTable(str(local))
        previous_version = table.version()
    else:
        table, previous_version = str(local), -1
    scanner = ds.dataset([str(path) for path in paths], format="parquet").scanner(
        batch_size=1000, use_threads=False, batch_readahead=0, fragment_readahead=0
    )
    metadata = {remote: execution[field] for field, remote in METADATA.items()}
    metadata["agentium_input_rows"] = str(row_count)
    _remaining(deadline_at)
    write_deltalake(
        table,
        scanner.to_reader(),
        mode=parameters.get("mode", "append"),
        target_file_size=64 * 1024**2,
        commit_properties=CommitProperties(custom_metadata=metadata, max_commit_retries=0),
    )
    version = previous_version + 1
    log_path = local / "_delta_log" / f"{version:020d}.json"
    if not log_path.is_file():
        raise AdapterError("CONNECTOR_DELTA_COMMIT_INVALID")
    _check_log(log_path)
    new_parts, info = [], None
    with log_path.open() as handle:
        for line in handle:
            action = json.loads(line)
            _action(action)
            if "add" in action:
                relative = _relative(action["add"]["path"])
                path = (local / relative).resolve()
                if (
                    not path.is_relative_to(local.resolve())
                    or path.is_symlink()
                    or not path.is_file()
                ):
                    raise AdapterError("CONNECTOR_DELTA_PATH_INVALID")
                if path.stat().st_size > MAX_PART_BYTES:
                    raise AdapterError("CONNECTOR_EXPORT_PART_TOO_LARGE")
                new_parts.append((relative, path))
            if "commitInfo" in action:
                info = action["commitInfo"]
    if len(new_parts) > 10000 or info is None:
        raise AdapterError("CONNECTOR_DELTA_COMMIT_INVALID")
    payload = log_path.read_bytes()
    if len(payload) > MAX_LOG_BYTES:
        raise AdapterError("CONNECTOR_DELTA_LOG_TOO_LARGE")
    log_key = f"{prefix}/_delta_log/{version:020d}.json"
    receipt = _receipt(info, version, log_key, hashlib.sha256(payload).hexdigest(), execution)
    for relative, path in new_parts:
        _remaining(deadline_at)
        client.put(prefix + "/" + relative, path.read_bytes())
    _remaining(deadline_at)
    # No expected_etag means If-None-Match / generation=0 in all guarded
    # clients. Competing writers cannot replace this version's transaction log.
    client.put(log_key, payload)
    return receipt


def reconcile(config, credentials, parameters, deadline_at, output_dir, *, dialect, execution):
    _execution(execution, require_files=False)
    prefix = _prefix(config, parameters)
    client = client_for(dialect, config, credentials, deadline_at)
    local = _stage_logs(client, _logs(client, prefix, deadline_at), prefix, output_dir, deadline_at)
    receipt = _find_commit(local, prefix, execution)
    if receipt is None:
        # Log retention or an in-flight remote commit can make absence
        # inconclusive. It is never permission to issue the mutation again.
        return {"operation_id": execution["operation_id"], "applied": False, "outcome": "unknown"}
    return {**receipt, "reconciled": True}
