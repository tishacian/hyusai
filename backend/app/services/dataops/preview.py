"""Type inference reads no rows; previews use sealed bounded persisted samples."""

import re
import tempfile
import threading
from pathlib import Path

from app.core.config import settings
from app.services.dataops.compiler import quote
from app.services.dataops.secrets import hash_parameters
from app.services.dataops.storage import file_digest
from app.services.object_store import get_object_store

_slots = threading.BoundedSemaphore(1)


def native_schema(dataset):
    import pyarrow as pa

    fields = []
    for field in dataset.schema_json:
        name, dtype = field["name"], field.get("dtype", "")
        kind = field.get("kind")
        if dtype.startswith("Decimal"):
            digits = re.findall(r"\d+", dtype)
            value = (
                pa.decimal128(int(digits[0]), int(digits[1]))
                if len(digits) >= 2
                else pa.decimal128(38, 6)
            )
        elif dtype == "Date":
            value = pa.date32()
        elif kind == "datetime" or dtype.startswith("Datetime"):
            value = pa.timestamp("us", tz="UTC" if "UTC" in dtype else None)
        else:
            value = {
                "integer": pa.int64(),
                "float": pa.float64(),
                "boolean": pa.bool_(),
                "date": pa.date32(),
            }.get(kind, pa.string())
        fields.append(pa.field(name, value))
    return pa.schema(fields)


def infer_schema(compiled, datasets, spec):
    import duckdb

    conn = duckdb.connect()
    try:
        conn.execute("SET threads=1")
        conn.execute("SET memory_limit='64MB'")
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


def preview(compiled, datasets, spec):
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

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
                    table = pa.Table.from_pylist(dataset.preview_json or [])
                    if not table.num_columns:
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
            result = conn.execute(
                f"SELECT * FROM ({compiled.sql}) LIMIT {int(settings.tabular_preview_rows)}",
                hash_parameters(spec),
            ).to_arrow_table()
        return {
            "rows": result.to_pylist(),
            "schema": [
                {"name": f.name, "dtype": str(f.type), "nullable": f.nullable}
                for f in result.schema
            ],
            "sample": True,
            "sample_metadata": {
                "method": "persisted",
                "inputs": counts,
                "max_rows_per_input": min(10000, settings.dataops_sample_rows),
            },
            "fingerprint": compiled.fingerprint,
        }
    except duckdb.InterruptException:
        raise ValueError("DATAPREP_PREVIEW_TIMEOUT") from None
    except duckdb.Error as exc:
        raise ValueError("DATAPREP_TYPE_MISMATCH: " + str(exc).splitlines()[0][:240]) from None
    finally:
        timer.cancel()
        conn.close()
        _slots.release()
