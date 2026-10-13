"""Type inference reads no rows; previews use sealed bounded persisted samples."""

import hashlib
import io
import json
import math
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

from app.core.config import settings
from app.services.dataops.compiler import quote
from app.services.dataops.secrets import hash_parameters
from app.services.dataops.storage import file_digest
from app.services.object_store import get_object_store

_slots = threading.BoundedSemaphore(1)
_cache = OrderedDict()
_cache_lock = threading.Lock()
_cache_bytes = 0
_CACHE_BYTES = 32 * 1024**2


def _json_value(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def preview(compiled, datasets, spec, *, limit=None, output_port=None):
    """Authorization precedes this call; cache immutable samples for 60 seconds."""
    global _cache_bytes
    identities = []
    for port, dataset in sorted(datasets.items()):
        sample = (dataset.lineage_json or {}).get("sample")
        if not sample:
            raise ValueError("DATAPREP_SAMPLE_REQUIRED")
        identities.append(
            (
                port,
                getattr(dataset, "workspace_id", None),
                getattr(dataset, "id", None),
                dataset.version,
                sample["key"],
                sample["sha256"],
                sample.get("version"),
            )
        )
    prefix = hashlib.sha256(getattr(compiled, "sql", "").encode()).hexdigest()
    key = (
        compiled.fingerprint,
        prefix,
        tuple(identities),
        limit,
        output_port,
        settings.dataops_sample_rows,
        settings.dataops_preview_input_mb,
        settings.dataops_preview_memory_mb,
        settings.dataops_preview_timeout_s,
    )
    start = time.monotonic()
    with _cache_lock:
        for old_key, (expires, _, size) in list(_cache.items()):
            if expires <= start:
                _cache.pop(old_key)
                _cache_bytes -= size
        if key in _cache:
            _cache.move_to_end(key)
            result = json.loads(_cache[key][1])
            result["cache_hit"] = True
            return result
    result = _preview(compiled, datasets, spec, limit=limit, output_port=output_port)
    result.update(duration_ms=round((time.monotonic() - start) * 1000, 2), cache_hit=False)
    from app.resources.dataops_storage import _json_scalar

    payload = json.dumps(
        _json_value(result), default=_json_scalar, ensure_ascii=False, allow_nan=False
    ).encode()
    size = len(payload)
    if size <= _CACHE_BYTES:
        with _cache_lock:
            old = _cache.pop(key, None)
            if old:
                _cache_bytes -= old[2]
            _cache[key] = (time.monotonic() + 60, payload, size)
            _cache_bytes += size
            while len(_cache) > 64 or _cache_bytes > _CACHE_BYTES:
                _, (_, _, removed) = _cache.popitem(last=False)
                _cache_bytes -= removed
    # Both cached and fresh callers receive the same JSON types (not e.g.
    # Decimal on the first call and a string on the next one).
    return json.loads(payload)


def native_schema(dataset):
    """Read authoritative types from the Delta log or bounded Parquet footer.

    Profiling JSON is presentation metadata: it can lose decimal precision,
    timestamp units and nullability and must not determine compiled SQL types.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.services.dataops.storage import delta_manifest, is_delta

    if is_delta(dataset):
        from deltalake import Schema

        manifest = delta_manifest(dataset)
        return pa.schema(Schema.from_json(manifest["metadata"]["schemaString"]).to_arrow())
    store = get_object_store()
    if store.backend == "local":
        source = store._local_path(dataset.storage_key).open("rb")
    else:
        source = store._fsspec().open(
            store._remote_key(dataset.storage_key), "rb", block_size=65536, cache_type="none"
        )
    with source:
        source.seek(0, 2)
        size = source.tell()
        if size < 12:
            raise ValueError("DATAPREP_PARQUET_FOOTER_INVALID")
        source.seek(-8, 2)
        trailer = source.read(8)
        length = int.from_bytes(trailer[:4], "little")
        if trailer[4:] != b"PAR1" or not 0 < length <= min(size - 12, 8 * 1024**2):
            raise ValueError("DATAPREP_PARQUET_FOOTER_INVALID")
        source.seek(-8 - length, 2)
        footer = source.read(length)
        if len(footer) != length:
            raise ValueError("DATAPREP_PARQUET_FOOTER_INVALID")
    # A schema reader needs metadata only, never a row group from the source.
    return pq.read_schema(io.BytesIO(b"PAR1" + footer + trailer))


def infer_schema(compiled, datasets, spec):
    import duckdb

    conn = duckdb.connect()
    try:
        conn.execute("SET threads=1")
        conn.execute("SET memory_limit='64MB'")
        conn.execute("SET TimeZone='UTC'")
        conn.execute("PRAGMA disable_optimizer")
        for port, dataset in datasets.items():
            conn.register(port, native_schema(dataset).empty_table())
        conn.execute("SET enable_external_access=false")
        conn.execute("SET lock_configuration=true")
        result = conn.execute(
            f"SELECT * FROM ({compiled.sql}) LIMIT 0", hash_parameters(spec)
        ).to_arrow_table()
        return [
            {"name": f.name, "dtype": str(f.type), "nullable": f.nullable} for f in result.schema
        ]
    except duckdb.Error as exc:
        raise ValueError("DATAPREP_TYPE_MISMATCH: " + str(exc).splitlines()[0][:240]) from None
    finally:
        conn.close()


def _preview(compiled, datasets, spec, *, limit=None, output_port=None):
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    if output_port and output_port not in {output.port for output in spec.outputs}:
        raise ValueError("DATAPREP_OUTPUT_PORT_INVALID")

    if not _slots.acquire(blocking=False):
        raise ValueError("DATAPREP_PREVIEW_BUSY")
    conn = duckdb.connect()
    timer = threading.Timer(settings.dataops_preview_timeout_s, conn.interrupt)
    timer.daemon = True
    try:
        conn.execute(f"SET memory_limit='{settings.dataops_preview_memory_mb}MB'")
        conn.execute("SET threads=1")
        conn.execute("SET TimeZone='UTC'")
        conn.execute("SET temp_directory=''")
        total = 0
        counts = {}
        with tempfile.TemporaryDirectory(prefix="prep-preview-") as tmp:
            for port, dataset in datasets.items():
                info = (dataset.lineage_json or {}).get("sample")
                if info:
                    path = get_object_store().copy_to_local(
                        info["key"], Path(tmp) / port / "sample.parquet", max_bytes=16 * 1024**2
                    )
                    if file_digest(path) != info["sha256"]:
                        raise ValueError("DATAPREP_SAMPLE_CHANGED")
                    parquet = pq.ParquetFile(path)
                    expanded = sum(
                        parquet.metadata.row_group(i).total_byte_size
                        for i in range(parquet.metadata.num_row_groups)
                    )
                    if expanded > settings.dataops_preview_input_mb * 1024**2:
                        raise ValueError("DATAPREP_SAMPLE_MEMORY_LIMIT")
                    batches = []
                    rows = 0
                    for batch in parquet.iter_batches(batch_size=1000, use_threads=False):
                        take = min(batch.num_rows, min(10000, settings.dataops_sample_rows) - rows)
                        if take <= 0:
                            break
                        batches.append(batch.slice(0, take))
                        rows += take
                    table = pa.Table.from_batches(batches, schema=parquet.schema_arrow)
                else:
                    raise ValueError("DATAPREP_SAMPLE_REQUIRED")
                total += table.nbytes
                if total > settings.dataops_preview_input_mb * 1024**2:
                    raise ValueError("DATAPREP_SAMPLE_MEMORY_LIMIT")
                counts[port] = {
                    "rows": table.num_rows,
                    "of_rows": dataset.row_count,
                    "method": info["method"] if info else "legacy_profile_preview",
                }
                conn.register("__sample", table)
                conn.execute(f"CREATE TEMP TABLE {quote(port)} AS SELECT * FROM __sample")
                conn.unregister("__sample")
            conn.execute("SET enable_external_access=false")
            conn.execute("SET lock_configuration=true")
            timer.start()
            import sqlglot
            from sqlglot import exp

            def execute(sql):
                used = {
                    n.name for n in sqlglot.parse_one(sql, read="duckdb").find_all(exp.Placeholder)
                }
                parameters = {k: v for k, v in compiled.preview_parameters.items() if k in used}
                return conn.execute(sql, parameters)

            execute(f"CREATE TEMP TABLE __preview_output AS {compiled.sql}")
            from app.services.dataops.compiler import literal

            predicate = (
                f" WHERE __dp_output={literal(output_port)}"
                if output_port and spec.operation == "split"
                else ""
            )
            result = conn.execute(
                f"SELECT {','.join(quote(n) for n in compiled.columns)} FROM __preview_output{predicate} LIMIT {min(200, max(1, int(limit or settings.tabular_preview_rows)))}"
            ).to_arrow_table()
            if spec.operation == "split":
                output_counts = {
                    port: count
                    for port, count in conn.execute(
                        "SELECT __dp_output,count(*) FROM __preview_output GROUP BY __dp_output"
                    ).fetchall()
                }
            else:
                output_counts = {
                    "out": conn.execute("SELECT count(*) FROM __preview_output").fetchone()[0]
                }
            from app.services.dataops.preview_stats import conversion_counters, profile

            stats = profile(conn, result.schema, predicate)
            steps = conversion_counters(conn, compiled, spec, execute)
        return {
            "rows": result.to_pylist(),
            "schema": [
                {"name": f.name, "dtype": str(f.type), "nullable": f.nullable}
                for f in result.schema
            ],
            "sample": True,
            "stats": stats,
            "stats_scope": "sample",
            "sample_metadata": {
                "method": "persisted",
                "inputs": counts,
                "max_rows_per_input": min(10000, settings.dataops_sample_rows),
            },
            "fingerprint": compiled.fingerprint,
            "output_schema": list(compiled.output_schema),
            "step_schemas": list(compiled.step_schemas),
            "warnings": list(compiled.warnings),
            "counters": {
                "inputs": {port: value["rows"] for port, value in counts.items()},
                "outputs": output_counts,
                "steps": steps,
            },
            "sample_info": {
                "rows": sum(value["rows"] for value in counts.values()),
                "of_rows": sum(value["of_rows"] or 0 for value in counts.values()),
                "version": {port: dataset.version for port, dataset in datasets.items()},
            },
        }
    except duckdb.InterruptException:
        raise ValueError("DATAPREP_PREVIEW_TIMEOUT") from None
    except duckdb.Error as exc:
        raise ValueError("DATAPREP_TYPE_MISMATCH: " + str(exc).splitlines()[0][:240]) from None
    finally:
        timer.cancel()
        conn.close()
        _slots.release()
