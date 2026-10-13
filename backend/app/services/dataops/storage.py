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


def delta_manifest(dataset) -> dict[str, Any]:
    """Only the committed log determines the files that belong to a version."""
    store = get_object_store()
    key = dataset.storage_key
    if not key or not is_delta(dataset):
        raise ValueError("DATASET_NOT_DELTA")
    log = store.read_bytes(f"{key}/_delta_log/00000000000000000000.json")
    expected = (dataset.lineage_json or {}).get("storage", {}).get("log_sha256")
    if expected and hashlib.sha256(log).hexdigest() != expected:
        raise ValueError("DATASET_INTEGRITY_FAILED")
    files, metadata = [], None
    for line in log.decode("utf-8").splitlines():
        action = json.loads(line)
        if "metaData" in action:
            metadata = action["metaData"]
        if "remove" in action:
            raise ValueError("DATASET_MUTABLE_DELTA_REFUSED")
        if "protocol" in action:
            protocol = action["protocol"]
            if protocol.get("minReaderVersion", 1) > 1:
                raise ValueError("DATASET_DELTA_PROTOCOL_UNSUPPORTED")
        if "add" in action:
            item = action["add"]
            relative = PurePosixPath(item["path"])
            if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
                raise ValueError("DATASET_PART_PATH_INVALID")
            files.append({"path": str(relative), "size": int(item["size"])})
    if metadata is None:
        raise ValueError("DATASET_DELTA_METADATA_REQUIRED")
    return {"files": files, "log": log, "metadata": metadata}


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
    import pyarrow.dataset as ds

    with tempfile.TemporaryDirectory(prefix="dataset-batches-") as tmp:
        files = materialize_files(dataset, Path(tmp))
        scanner = ds.dataset([str(p) for p in files], format="parquet").scanner(
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
        parts = (dataset.lineage_json or {}).get("storage", {}).get("parts", {})
        return hashlib.sha256(
            json.dumps(
                {"log": hashlib.sha256(manifest["log"]).hexdigest(), "parts": parts}, sort_keys=True
            ).encode()
        ).hexdigest()
    with tempfile.TemporaryDirectory(prefix="dataset-digest-") as tmp:
        return file_digest(materialize_files(dataset, Path(tmp))[0])


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


def persist_sample(dataset, paths):
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    store = get_object_store()
    with tempfile.TemporaryDirectory(prefix="dataset-sample-") as tmp:
        path = Path(tmp) / "sample.parquet"
        table = (
            ds.dataset([str(p) for p in paths], format="parquet")
            .scanner(
                use_threads=False,
                batch_size=settings.dataops_sample_rows,
                batch_readahead=0,
                fragment_readahead=0,
            )
            .head(settings.dataops_sample_rows)
        )
        if table.nbytes > settings.dataops_preview_input_mb * 1024**2:
            raise ValueError("DATAPREP_SAMPLE_MEMORY_LIMIT")
        pq.write_table(table, path, compression="zstd")
        if path.stat().st_size > 16 * 1024**2:
            raise ValueError("DATAPREP_SAMPLE_BUDGET_EXCEEDED")
        key = f"workspaces/{dataset.workspace_id}/tabular/datasets/{dataset.id}/sample.parquet"
        store.write_once(key, path.read_bytes())
        dataset.lineage_json = {
            **(dataset.lineage_json or {}),
            "sample": {
                "key": key,
                "sha256": file_digest(path),
                "size_bytes": path.stat().st_size,
                "rows": table.num_rows,
                "method": "head",
                "version": 1,
            },
        }


def profile_files(paths: list[Path]) -> dict[str, Any]:
    """SQL aggregates spill; the only values collected are bounded display data."""
    import duckdb
    import polars as pl
    import pyarrow.dataset as ds

    from app.services.tabular_datasets import _column_kind, _json_scalar

    with tempfile.TemporaryDirectory(prefix="dataset-profile-") as tmp:
        conn = duckdb.connect()
        try:
            conn.execute(f"SET memory_limit='{settings.dataops_duckdb_memory_mb}MB'")
            conn.execute(f"SET threads={settings.dataops_duckdb_threads}")
            conn.execute("SET TimeZone='UTC'")
            conn.execute("SET temp_directory=?", [tmp])
            conn.execute(f"SET max_temp_directory_size='{settings.dataops_spill_max_mb}MB'")
            arrow = ds.dataset([str(p) for p in paths], format="parquet")
            # The managed DuckDB table can spill under memory_limit. An Arrow
            # dataset registration would prefetch outside that memory budget.
            from app.services.dataops.compiler import literal

            inputs = ",".join(literal(str(p)) for p in paths)
            conn.execute(f"CREATE TEMP TABLE data AS SELECT * FROM read_parquet([{inputs}])")
            conn.execute("SET enable_external_access=false")
            conn.execute("SET lock_configuration=true")
            count = conn.execute("SELECT count(*) FROM data").fetchone()[0]
            dtypes = pl.from_arrow(arrow.schema.empty_table()).schema
            schema, stats = [], {}
            for name, dtype in dtypes.items():
                quoted = '"' + name.replace('"', '""') + '"'
                kind = _column_kind(dtype)
                nulls, distinct = conn.execute(
                    f"SELECT count(*)-count({quoted}),count(DISTINCT {quoted}) FROM data"
                ).fetchone()
                info = {
                    "kind": kind,
                    "nulls": nulls,
                    "null_ratio": round(nulls / count, 4) if count else 0.0,
                    "distinct": distinct + int(nulls > 0),
                }
                schema.append(
                    {"name": name, "kind": kind, "dtype": str(dtype), "nullable": nulls > 0}
                )
                if kind in {"integer", "float", "datetime"}:
                    low, high = conn.execute(
                        f"SELECT min({quoted}),max({quoted}) FROM data"
                    ).fetchone()
                    info.update(min=_json_scalar(low), max=_json_scalar(high))
                if kind in {"integer", "float"}:
                    mean, std, q25, q50, q75 = conn.execute(
                        f"SELECT avg({quoted}),stddev_samp({quoted}),quantile_cont({quoted},0.25),quantile_cont({quoted},0.5),quantile_cont({quoted},0.75) FROM data"
                    ).fetchone()
                    info.update(
                        mean=_json_scalar(mean),
                        std=_json_scalar(std),
                        q25=_json_scalar(q25),
                        q50=_json_scalar(q50),
                        q75=_json_scalar(q75),
                    )
                    if low is not None and high is not None and high != low:
                        bins = conn.execute(
                            f"SELECT least(11,greatest(0,floor(({quoted}-?)/?)))::INT AS bin,count(*) FROM data WHERE {quoted} IS NOT NULL GROUP BY bin ORDER BY bin",
                            [float(low), (float(high) - float(low)) / 12],
                        ).fetchall()
                        info["histogram"] = [
                            {
                                "lower": float(low) + i * (float(high) - float(low)) / 12,
                                "upper": float(low) + (i + 1) * (float(high) - float(low)) / 12,
                                "count": dict(bins).get(i, 0),
                            }
                            for i in range(12)
                        ]
                    else:
                        info["histogram"] = []
                if kind in {"string", "boolean"}:
                    values = conn.execute(
                        f"SELECT {quoted},count(*) AS n FROM data WHERE {quoted} IS NOT NULL GROUP BY {quoted} ORDER BY n DESC,{quoted} LIMIT 6"
                    ).fetchall()
                    info["top_values"] = [{"value": _json_scalar(v), "count": n} for v, n in values]
                if kind == "string":
                    info["mean_length"] = _json_scalar(
                        conn.execute(f"SELECT avg(length({quoted})) FROM data").fetchone()[0]
                    )
                stats[name] = info
            preview = (
                conn.execute(f"SELECT * FROM data LIMIT {int(settings.tabular_preview_rows)}")
                .fetch_arrow_table()
                .to_pylist()
            )
            return {
                "row_count": count,
                "column_count": len(schema),
                "schema": schema,
                "stats": stats,
                "preview": [{k: _json_scalar(v) for k, v in row.items()} for row in preview],
            }
        finally:
            conn.close()


def write_batches(directory: Path, batches: Iterable, *, schema, delta: bool = False) -> list[Path]:
    """Write bounded batches; Delta generates one immutable commit, never append."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    directory.mkdir(parents=True, exist_ok=True)
    if delta:
        from deltalake import write_deltalake

        reader = pa.RecordBatchReader.from_batches(schema, batches)
        write_deltalake(
            str(directory),
            reader,
            mode="error",
            target_file_size=settings.dataops_part_max_mb * 1024**2,
        )
        from deltalake import DeltaTable

        files = [Path(uri) for uri in DeltaTable(str(directory)).file_uris()]
        if not files:
            # Profile zero-row output without adding a file outside the log.
            output = directory / "empty-profile.parquet"
            pq.write_table(schema.empty_table(), output)
            return [output]
        return files
    output = directory / "data.parquet"
    with pq.ParquetWriter(output, schema, compression="zstd") as writer:
        for batch in batches:
            writer.write_batch(batch)
    return [output]


def settle_files(
    db, dataset, paths: list[Path], *, delta_root: Path | None = None, on_profile=None
):
    from app.services.tabular_datasets import _apply_profile

    if dataset.status != "ingesting":
        raise ValueError("DATASET_OUTPUT_NOT_RESERVED")
    store = get_object_store()
    profile = profile_files(paths)
    if on_profile is not None:
        on_profile(profile)
    prefix = f"workspaces/{dataset.workspace_id}/tabular/datasets/{dataset.id}"
    size = sum(p.stat().st_size for p in paths)
    if size > settings.dataops_max_output_mb * 1024**2:
        raise ValueError("DATASET_OUTPUT_BUDGET_EXCEEDED")
    if delta_root is not None:
        # Delta returns canonical file URIs (e.g. /private/var on macOS),
        # while TemporaryDirectory may preserve a symlink such as /var.
        delta_root = delta_root.resolve(strict=True)
        key = f"{prefix}/delta"
        log = delta_root / "_delta_log/00000000000000000000.json"
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
