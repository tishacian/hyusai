"""Immutable dataset versions with bounded Arrow IO and Delta commit authority."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import settings
from app.services.object_store import get_object_store


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_delta(dataset) -> bool:
    return bool(dataset.storage_key and dataset.storage_key.endswith("/delta"))


def _parse_delta_log(log: bytes) -> dict[str, Any]:
    """Accept only the deliberately small immutable Delta protocol we write."""
    files, metadata, protocol = [], None, None
    seen = set()
    for line in log.decode("utf-8").splitlines():
        action = json.loads(line)
        if "metaData" in action:
            if metadata is not None:
                raise ValueError("DATASET_DELTA_METADATA_INVALID")
            metadata = action["metaData"]
        if "remove" in action:
            raise ValueError("DATASET_MUTABLE_DELTA_REFUSED")
        if "protocol" in action:
            protocol = action["protocol"]
            if (
                protocol.get("minReaderVersion") != 1
                or protocol.get("minWriterVersion") != 2
                or protocol.get("readerFeatures")
                or protocol.get("writerFeatures")
            ):
                raise ValueError("DATASET_DELTA_PROTOCOL_UNSUPPORTED")
        if "add" in action:
            item = action["add"]
            raw = item["path"]
            relative = PurePosixPath(raw)
            from urllib.parse import unquote

            if (
                not raw
                or relative.is_absolute()
                or ".." in relative.parts
                or "\\" in raw
                or str(relative) != raw
                or unquote(raw) != raw
                or raw in seen
                or not raw.endswith(".parquet")
            ):
                raise ValueError("DATASET_PART_PATH_INVALID")
            if item.get("deletionVector") or type(item.get("size")) is not int or item["size"] < 0:
                raise ValueError("DATASET_DELTA_PROTOCOL_UNSUPPORTED")
            seen.add(raw)
            files.append({"path": raw, "size": item["size"]})
    if metadata is None or protocol is None:
        raise ValueError("DATASET_DELTA_METADATA_REQUIRED")
    config = metadata.get("configuration") or {}
    if (
        config.get("delta.columnMapping.mode", "none") != "none"
        or str(config.get("delta.enableDeletionVectors", "false")).lower() != "false"
        or metadata.get("partitionColumns")
    ):
        raise ValueError("DATASET_DELTA_PROTOCOL_UNSUPPORTED")
    return {"files": files, "log": log, "metadata": metadata}


def delta_manifest(dataset) -> dict[str, Any]:
    """Only commit zero determines active files, never a directory listing."""
    store = get_object_store()
    key = dataset.storage_key
    if not key or not is_delta(dataset):
        raise ValueError("DATASET_NOT_DELTA")
    # The journal is bounded independently of the data and never read_bytes().
    with tempfile.TemporaryDirectory(prefix="delta-journal-") as tmp:
        path = store.copy_to_local(
            f"{key}/_delta_log/00000000000000000000.json",
            Path(tmp) / "commit.json",
            max_bytes=16 * 1024**2,
        )
        log = path.read_bytes()
    if store.exists(f"{key}/_delta_log/00000000000000000001.json"):
        raise ValueError("DATASET_MUTABLE_DELTA_REFUSED")
    expected = (dataset.lineage_json or {}).get("storage", {}).get("log_sha256")
    if expected and hashlib.sha256(log).hexdigest() != expected:
        raise ValueError("DATASET_INTEGRITY_FAILED")
    return _parse_delta_log(log)


def dataset_files(dataset) -> list[str]:
    """ObjectStore keys; Delta membership comes exclusively from commit zero."""
    if not dataset.storage_key:
        raise ValueError("DATASET_NOT_READY")
    if not is_delta(dataset):
        return [dataset.storage_key]
    return [f"{dataset.storage_key}/{item['path']}" for item in delta_manifest(dataset)["files"]]


def open_dataset_arrow(dataset):
    """Lazy Arrow dataset over active parts, with native local/S3 range reads."""
    import pyarrow.dataset as ds

    from app.services.object_store import settings as store_settings

    store = get_object_store()
    if is_delta(dataset):
        from deltalake import DeltaTable

        delta_manifest(dataset)  # integrity/protocol guard before exposing the snapshot
        options = None
        if store.backend == "s3":
            options = {"AWS_REGION": "us-east-1"}
            for name, value in {
                "AWS_ENDPOINT_URL": store_settings.object_store_s3_endpoint_url,
                "AWS_ACCESS_KEY_ID": store_settings.object_store_s3_access_key,
                "AWS_SECRET_ACCESS_KEY": store_settings.object_store_s3_secret_key,
            }.items():
                if value:
                    options[name] = value
            if (store_settings.object_store_s3_endpoint_url or "").startswith("http://"):
                options["AWS_ALLOW_HTTP"] = "true"
        location = (
            str(store._local_path(dataset.storage_key))
            if store.backend == "local"
            else store.uri(dataset.storage_key)
        )
        return DeltaTable(location, version=0, storage_options=options).to_pyarrow_dataset()
    if not dataset.storage_key:
        raise ValueError("DATASET_NOT_READY")
    if store.backend == "local":
        return ds.dataset(str(store._local_path(dataset.storage_key)), format="parquet")
    import pyarrow.fs as fs

    return ds.dataset(
        store._remote_key(dataset.storage_key),
        format="parquet",
        filesystem=fs.PyFileSystem(fs.FSSpecHandler(store._fsspec())),
    )


def materialize_files(dataset, directory: Path, *, max_bytes: int | None = None) -> list[Path]:
    store = get_object_store()
    directory.mkdir(parents=True, exist_ok=True)
    ceiling = max_bytes if max_bytes is not None else settings.dataops_max_input_mb * 1024**2
    if not is_delta(dataset):
        return [
            store.copy_to_local(dataset.storage_key, directory / "data.parquet", max_bytes=ceiling)
        ]
    manifest = delta_manifest(dataset)
    integrity = (dataset.lineage_json or {}).get("storage", {}).get("parts", {})
    if not manifest["files"]:
        import pyarrow as pa
        import pyarrow.parquet as pq
        from deltalake import Schema

        schema = pa.schema(Schema.from_json(manifest["metadata"]["schemaString"]).to_arrow())
        path = directory / "empty.parquet"
        pq.write_table(schema.empty_table(), path)
        return [path]
    total = 0
    paths = []
    for item in manifest["files"]:
        total += item["size"]
        if total > ceiling:
            raise ValueError("DATASET_INPUT_BUDGET_EXCEEDED")
        destination = directory / item["path"]
        path = store.copy_to_local(
            f"{dataset.storage_key}/{item['path']}", destination, max_bytes=item["size"]
        )
        if path.stat().st_size != item["size"] or (
            item["path"] in integrity and file_digest(path) != integrity[item["path"]]
        ):
            raise ValueError("DATASET_INTEGRITY_FAILED")
        paths.append(path)
    return paths


def iter_dataset_batches(
    dataset, *, columns: list[str] | None = None, batch_size: int | None = None
):
    # Lazy range reads must preserve the input ceiling previously enforced by
    # materialize_files, without downloading or listing uncommitted objects.
    size = (
        sum(part["size"] for part in delta_manifest(dataset)["files"])
        if is_delta(dataset)
        else get_object_store().size(dataset.storage_key)
    )
    if size is None or size > settings.dataops_max_input_mb * 1024**2:
        raise ValueError("DATASET_INPUT_BUDGET_EXCEEDED")
    scanner = open_dataset_arrow(dataset).scanner(
        columns=columns,
        batch_size=batch_size or settings.dataops_batch_rows,
        use_threads=False,
        batch_readahead=0,
        fragment_readahead=0,
    )
    yield from scanner.to_batches()


def dataset_digest(dataset) -> str:
    if is_delta(dataset):
        manifest = delta_manifest(dataset)
        return hashlib.sha256(manifest["log"]).hexdigest()
    with tempfile.TemporaryDirectory(prefix="dataset-digest-") as tmp:
        return file_digest(materialize_files(dataset, Path(tmp))[0])


def dataset_digest_matches(dataset, expected: str) -> bool:
    """Read compatibility for already queued pre-D3 Delta execution fingerprints."""
    if dataset_digest(dataset) == expected:
        return True
    if not is_delta(dataset):
        return False
    manifest = delta_manifest(dataset)
    parts = (dataset.lineage_json or {}).get("storage", {}).get("parts", {})
    previous = hashlib.sha256(
        json.dumps(
            {"log": hashlib.sha256(manifest["log"]).hexdigest(), "parts": parts}, sort_keys=True
        ).encode()
    ).hexdigest()
    return previous == expected


def identity_digest(dataset):
    storage = (dataset.lineage_json or {}).get("storage", {})
    if storage.get("sha256"):
        return storage["sha256"]
    if is_delta(dataset):
        return dataset_digest(dataset)
    # Legacy rows have no persisted byte hash. Their producer must backfill
    # it on the worker before byte-sensitive execution; preview only names
    # their stable native version, and does not download the table.
    return hashlib.sha256(
        json.dumps(
            {
                "id": dataset.id,
                "version": dataset.version,
                "storage_key": dataset.storage_key,
                "schema": dataset.schema_json,
                "rows": dataset.row_count,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def persist_sample(dataset, paths, *, reuse_identical=False):
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    store = get_object_store()
    with tempfile.TemporaryDirectory(prefix="dataset-sample-") as tmp:
        path = Path(tmp) / "sample.parquet"
        import pyarrow as pa

        arrow = ds.dataset([str(p) for p in paths], format="parquet")
        maximum = min(settings.dataops_preview_input_mb * 1024**2, 8 * 1024**2)
        import numpy as np

        total = sum(pq.read_metadata(part).num_rows for part in paths)
        rng = np.random.default_rng(42)
        indices = rng.choice(total, size=min(total, settings.dataops_sample_rows), replace=False)
        # Choosing a uniform subset of known row indices is equivalent to a
        # seeded reservoir, independent of part boundaries. If wide cells exceed
        # the byte ceiling, reduce the subset uniformly and replay the scan;
        # keeping the first rows that fit would bias the sample toward the head.
        while True:
            ordered = np.sort(indices)
            selected, used, offset, cursor = [], 0, 0, 0
            oversized = False
            for batch in arrow.scanner(
                use_threads=False, batch_size=1024,
                batch_readahead=0, fragment_readahead=0,
            ).to_batches():
                stop = int(np.searchsorted(ordered, offset + batch.num_rows, side="left"))
                if stop > cursor:
                    # take copies selected cells; slice would retain the entire
                    # input batch's buffers even for a tiny selection.
                    candidate = batch.take(pa.array(ordered[cursor:stop] - offset))
                    if used + candidate.nbytes > maximum:
                        oversized = True
                        break
                    selected.append(candidate)
                    used += candidate.nbytes
                cursor, offset = stop, offset + batch.num_rows
                if cursor == len(ordered):
                    break
            if not oversized:
                if cursor != len(ordered):
                    raise ValueError("DATASET_SAMPLE_CARDINALITY_CHANGED")
                break
            if len(indices) <= 1:
                raise ValueError("DATAPREP_SAMPLE_ROW_TOO_LARGE")
            indices = rng.choice(indices, size=max(1, len(indices) // 2), replace=False)
        table = pa.Table.from_batches(selected, schema=arrow.schema)
        pq.write_table(table, path, compression="zstd")
        if path.stat().st_size > 16 * 1024**2:
            raise ValueError("DATAPREP_SAMPLE_BUDGET_EXCEEDED")
        key = f"workspaces/{dataset.workspace_id}/tabular/datasets/{dataset.id}/sample.parquet"
        try:
            store.write_once(key, path.read_bytes())
        except Exception:
            if not reuse_identical:
                raise
            # Recovery may find bytes committed before the DB transaction.
            # Never overwrite them or trust existence without byte identity.
            existing = store.copy_to_local(key, Path(tmp) / "existing.parquet", max_bytes=16 * 1024**2)
            if file_digest(existing) != file_digest(path):
                raise ValueError("DATAPREP_SAMPLE_CHANGED") from None
        dataset.lineage_json = {
            **(dataset.lineage_json or {}),
            "sample": {
                "key": key,
                "sha256": file_digest(path),
                "size_bytes": path.stat().st_size,
                "rows": table.num_rows,
                "method": "reservoir_seeded",
                "seed": 42,
                "version": 1,
            },
        }


def profile_files(paths: list[Path]) -> dict[str, Any]:
    """All producer profiles share wall/virtual-memory/CPU subprocess limits."""
    import sys

    from app.services.recipe_executions import supervise_harness

    with tempfile.TemporaryDirectory(prefix="dataset-profile-runner-") as tmp:
        root = Path(tmp)
        request = root / "request.json"
        result = root / "result.json"
        request.write_text(
            json.dumps(
                {
                    "paths": [str(p.resolve()) for p in paths],
                    "memory_mb": settings.dataops_duckdb_memory_mb,
                    "threads": settings.dataops_duckdb_threads,
                    "spill_mb": settings.dataops_spill_max_mb,
                    "preview_rows": settings.tabular_preview_rows,
                }
            )
        )
        run = supervise_harness(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "resources/dataops_storage.py"),
                str(request),
                str(result),
            ],
            venv_python=Path(sys.executable),
            scratch=root,
            timeout_s=settings.dataops_sql_timeout_s,
            memory_limit_mb=settings.dataops_runner_memory_limit_mb,
            cpu_limit_s=int(settings.dataops_sql_timeout_s * settings.dataops_duckdb_threads) + 30,
            fsize_limit_mb=max(16, settings.dataops_spill_max_mb),
        )
        if run.status is not None or run.exit_code != 0:
            raise ValueError("DATASET_PROFILE_BUDGET_OR_EXECUTION_FAILED")
        if result.stat().st_size > 16 * 1024**2:
            raise ValueError("DATASET_PROFILE_RESULT_TOO_LARGE")
        return json.loads(result.read_text())


def write_batches(directory: Path, batches: Iterable, *, schema, delta: bool = False) -> list[Path]:
    """Write bounded batches; Delta generates one immutable commit, never append."""
    import pyarrow.parquet as pq

    directory.mkdir(parents=True, exist_ok=True)
    if delta:
        from app.resources.dataops_storage import PartWriter

        writer = PartWriter(directory, schema, target_bytes=settings.dataops_part_max_mb * 1024**2)
        try:
            for batch in batches:
                writer.write_batch(batch)
                if writer.size_bytes > settings.dataops_max_output_mb * 1024**2:
                    raise ValueError("DATASET_OUTPUT_BUDGET_EXCEEDED")
            writer.close()
        except Exception:
            # Close the current Parquet footer without publishing a Delta commit.
            writer.abort()
            raise
        if writer.size_bytes > settings.dataops_max_output_mb * 1024**2:
            raise ValueError("DATASET_OUTPUT_BUDGET_EXCEEDED")
        return writer.paths
    output = directory / "data.parquet"
    with pq.ParquetWriter(output, schema, compression="zstd") as writer:
        for batch in batches:
            writer.write_batch(batch)
            if output.stat().st_size > settings.dataops_max_output_mb * 1024**2:
                raise ValueError("DATASET_OUTPUT_BUDGET_EXCEEDED")
    return [output]


def settle_files(
    db, dataset, paths: list[Path], *, delta_root: Path | None = None, on_profile=None, profile=None
):
    from app.services.tabular_datasets import _apply_profile

    if dataset.status != "ingesting":
        raise ValueError("DATASET_OUTPUT_NOT_RESERVED")
    store = get_object_store()
    size = sum(
        p.stat().st_size for p in paths if delta_root is None or p.name != "empty-profile.parquet"
    )
    if size > settings.dataops_max_output_mb * 1024**2:
        raise ValueError("DATASET_OUTPUT_BUDGET_EXCEEDED")
    profile = profile if profile is not None else profile_files(paths)
    if on_profile is not None:
        on_profile(profile)
    prefix = f"workspaces/{dataset.workspace_id}/tabular/datasets/{dataset.id}"
    if delta_root is not None:
        # Delta returns canonical file URIs (e.g. /private/var on macOS),
        # while TemporaryDirectory may preserve a symlink such as /var.
        delta_root = delta_root.resolve(strict=True)
        key = f"{prefix}/delta"
        log = delta_root / "_delta_log/00000000000000000000.json"
        if log.stat().st_size > 16 * 1024**2:
            raise ValueError("DATASET_DELTA_LOG_TOO_LARGE")
        manifest = _parse_delta_log(log.read_bytes())
        actual = {
            p.resolve().relative_to(delta_root).as_posix(): p
            for p in paths
            if p.name != "empty-profile.parquet"
        }
        if set(actual) != {item["path"] for item in manifest["files"]}:
            raise ValueError("DATASET_DELTA_PARTS_MISMATCH")
        import pyarrow.parquet as pq

        rows = 0
        for item in manifest["files"]:
            path = actual[item["path"]]
            if path.stat().st_size != item["size"]:
                raise ValueError("DATASET_DELTA_PART_SIZE_MISMATCH")
            from deltalake import Schema

            actual_schema = json.loads(Schema.from_arrow(pq.read_schema(path)).to_json())
            declared_schema = json.loads(manifest["metadata"]["schemaString"])
            if actual_schema != declared_schema:
                raise ValueError("DATASET_SCHEMA_MISMATCH")
            rows += pq.read_metadata(path).num_rows
        if rows != profile["row_count"]:
            raise ValueError("DATASET_CARDINALITY_MISMATCH")
        from deltalake import DeltaTable

        committed = DeltaTable(str(delta_root), version=0).to_pyarrow_dataset()
        if len(committed.schema) != profile["column_count"] or committed.schema.names != [
            col["name"] for col in profile["schema"]
        ]:
            raise ValueError("DATASET_SCHEMA_MISMATCH")
        parts = {}
        for path in paths:
            if path.name == "empty-profile.parquet":
                continue
            path = path.resolve(strict=True)
            relative = path.relative_to(delta_root).as_posix()
            parts[relative] = file_digest(path)
            store.write_file(f"{key}/{relative}", path)
        store.write_once(f"{key}/_delta_log/00000000000000000000.json", log.read_bytes())
        dataset.lineage_json = {
            **(dataset.lineage_json or {}),
            "storage": {"format": "delta", "log_sha256": file_digest(log), "parts": parts},
        }
    else:
        if len(paths) != 1:
            raise ValueError("DATASET_PARQUET_SINGLE_FILE_REQUIRED")
        key = f"{prefix}/data.parquet"
        store.write_file(key, paths[0])
        dataset.lineage_json = {
            **(dataset.lineage_json or {}),
            "storage": {"format": "parquet", "sha256": file_digest(paths[0])},
        }
    persist_sample(dataset, paths)
    _apply_profile(dataset, profile)
    dataset.storage_key = key
    dataset.size_bytes = size
    dataset.status = "ready"
    dataset.status_detail = None
    from datetime import datetime

    dataset.ingested_at = datetime.utcnow()
    db.flush()
    return dataset
