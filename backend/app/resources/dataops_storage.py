"""Standalone bounded storage primitives shared by the API worker and runner."""

from __future__ import annotations

import json
import math
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _column_kind(dtype: Any) -> str:
    import polars as pl

    if dtype == pl.Boolean:
        return "boolean"
    if dtype.is_integer():
        return "integer"
    if dtype.is_float() or dtype.is_decimal():
        return "float"
    if dtype.is_temporal():
        return "datetime"
    if dtype in (pl.String, pl.Categorical, pl.Enum):
        return "string"
    return "other"


def _json_scalar(value: Any) -> Any:
    """Make one cell JSON-safe without lying about it.

    Postgres JSON columns reject NaN/Infinity, and dates must reach the UI as
    ISO strings rather than repr(). Anything exotic degrades to ``str``.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, str):
        return value[:2000]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001 - fall through to str()
            pass
    return str(value)[:2000]


def profile_files(
    paths: list[Path], *, memory_mb=1024, threads=2, spill_mb=4096, preview_rows=50
) -> dict[str, Any]:
    """SQL aggregates spill; the only values collected are bounded display data."""
    import duckdb
    import polars as pl
    import pyarrow.dataset as ds

    with tempfile.TemporaryDirectory(prefix="dataset-profile-") as tmp:
        conn = duckdb.connect()
        try:
            conn.execute(f"SET memory_limit='{memory_mb}MB'")
            # Parallel wide DISTINCT/GROUP BY states can exhaust the memory
            # budget before spilling. Profiling uses one lane within the
            # caller's CPU ceiling; output SQL still uses its requested lanes.
            conn.execute("SET threads=1")
            conn.execute("SET preserve_insertion_order=false")
            conn.execute("SET TimeZone='UTC'")
            conn.execute("SET temp_directory=?", [tmp])
            conn.execute(f"SET max_temp_directory_size='{spill_mb}MB'")
            arrow = ds.dataset([str(p) for p in paths], format="parquet")

            # Only the fixed aggregate statements below run in this helper.
            # Read local Parquet directly so profiling does not first copy the
            # entire table into DuckDB's spill budget. Unlike the authored-SQL
            # runner, this helper accepts no SQL or expressions from a caller;
            # paths are quoted literals and columns are quoted identifiers.
            # Native scans stay under DuckDB's budget; registering an Arrow
            # dataset would prefetch outside it.
            def literal(value):
                return "'" + value.replace("'", "''") + "'"

            inputs = ",".join(literal(str(p)) for p in paths)
            conn.execute(f"CREATE TEMP VIEW data AS SELECT * FROM read_parquet([{inputs}])")
            conn.execute("SET lock_configuration=true")
            count = conn.execute("SELECT count(*) FROM data").fetchone()[0]
            dtypes = pl.from_arrow(arrow.schema.empty_table()).schema
            schema, stats = [], {}
            for name, dtype in dtypes.items():
                quoted = '"' + name.replace('"', '""') + '"'
                kind = _column_kind(dtype)
                nulls, distinct = conn.execute(
                    f"SELECT (SELECT count(*)-count({quoted}) FROM data), "
                    f"(SELECT count(*) FROM (SELECT {quoted} FROM data "
                    f"WHERE {quoted} IS NOT NULL GROUP BY {quoted}))"
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
                            f"SELECT least(11,greatest(0,ceil(({quoted}-?)/?)-1))::INT AS bin,count(*) FROM data WHERE {quoted} IS NOT NULL GROUP BY bin ORDER BY bin",
                            [float(low), (float(high) - float(low)) / 12],
                        ).fetchall()
                        info["histogram"] = [
                            {
                                "upper": float(low) + (i + 1) * ((float(high) - float(low)) / 12),
                                "count": dict(bins).get(i, 0),
                            }
                            for i in range(12)
                        ]
                if kind in {"string", "boolean"}:
                    values = conn.execute(
                        f"SELECT {quoted},count(*) AS n FROM data GROUP BY {quoted} ORDER BY n DESC,{quoted} NULLS LAST LIMIT 6"
                    ).fetchall()
                    info["top_values"] = [{"value": _json_scalar(v), "count": n} for v, n in values]
                if kind == "string":
                    info["mean_length"] = _json_scalar(
                        conn.execute(f"SELECT avg(length({quoted})) FROM data").fetchone()[0]
                    )
                stats[name] = info
            # Aggregates do not preserve order, but the preview is still the
            # same bounded head of the committed part sequence as the sample.
            preview = arrow.scanner(
                batch_size=max(1, min(1024, int(preview_rows))),
                use_threads=False,
                batch_readahead=0,
                fragment_readahead=0,
            ).head(int(preview_rows)).to_pylist()
            return {
                "row_count": count,
                "column_count": len(schema),
                "schema": schema,
                "stats": stats,
                "preview": [{k: _json_scalar(v) for k, v in row.items()} for row in preview],
            }
        finally:
            conn.close()


def delta_schema(schema):
    """Protocol 1 timestamps carry UTC instants; timestamp_ntz needs protocol 3."""
    import pyarrow as pa

    def canonical(dtype):
        if pa.types.is_timestamp(dtype) and dtype.tz is None:
            return pa.timestamp(dtype.unit, tz="UTC")
        if pa.types.is_struct(dtype):
            return pa.struct([field.with_type(canonical(field.type)) for field in dtype])
        if pa.types.is_list(dtype) or pa.types.is_large_list(dtype):
            return pa.list_(dtype.value_field.with_type(canonical(dtype.value_type)))
        return dtype

    return pa.schema(
        [field.with_type(canonical(field.type)) for field in schema], metadata=schema.metadata
    )


class PartWriter:
    """Rotate Parquet parts and publish exactly one Delta commit after closing."""

    def __init__(self, directory, schema, *, target_bytes):
        import pyarrow.parquet as pq

        self.directory, self.schema = Path(directory), delta_schema(schema)
        self.directory.mkdir(parents=True, exist_ok=True)
        # Native conversion discovers files in this private staging directory.
        # Never adopt an earlier attempt's parts or an existing Delta version.
        if self.directory.is_symlink() or any(self.directory.iterdir()):
            raise ValueError("DATASET_DELTA_STAGING_NOT_EMPTY")
        self.directory = self.directory.resolve(strict=True)
        self.target_bytes = target_bytes
        self.paths, self.rows = [], []
        self.writer, self.path = None, None
        self.count = 0
        self.pq = pq
        self.closed = False

    def write_batch(self, batch):
        if self.closed:
            raise ValueError("DATASET_DELTA_WRITER_CLOSED")
        if not batch.num_rows:
            return
        if batch.schema != self.schema:
            batch = batch.cast(self.schema)
        if self.writer is None:
            self.path = self.directory / f"part-{len(self.paths):06d}-{uuid4().hex}.parquet"
            self.writer = self.pq.ParquetWriter(self.path, self.schema, compression="zstd")
            self.paths.append(self.path)
            self.rows.append(0)
        self.writer.write_batch(batch)
        self.rows[-1] += batch.num_rows
        self.count += batch.num_rows
        if self.path.stat().st_size >= self.target_bytes:
            self.writer.close()
            self.writer = None

    def abort(self):
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        self.closed = True

    @property
    def size_bytes(self):
        return sum(p.stat().st_size for p in self.paths)

    def close(self):
        if self.closed:
            return
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        from deltalake import DeltaTable, convert_to_deltalake
        from deltalake.transaction import CommitProperties, PostCommitHookProperties

        expected = {path.resolve(strict=True) for path in self.paths}
        entries = list(self.directory.iterdir())
        if any(path.is_symlink() or not path.is_file() for path in entries) or {
            path.resolve(strict=True) for path in entries
        } != expected:
            raise ValueError("DATASET_DELTA_STAGING_CHANGED")
        options = {
            "commit_properties": CommitProperties(max_commit_retries=0),
            "post_commithook_properties": PostCommitHookProperties(
                create_checkpoint=False, cleanup_expired_logs=False
            ),
        }
        if self.paths:
            # Rust reads the already closed Parquet footers and commits their
            # native AddActions/statistics without re-encoding any row. Staging
            # is private and local; S3 publication later uploads these exact
            # commit bytes with the platform's conditional write_once policy.
            convert_to_deltalake(self.directory, mode="error", collect_stats=True, **options)
            table = DeltaTable(self.directory, version=0)
        else:
            table = DeltaTable.create(self.directory, schema=self.schema, mode="error", **options)
        protocol = table.protocol()
        if (
            table.version() != 0
            or protocol.min_reader_version != 1
            or protocol.min_writer_version != 2
            or protocol.reader_features
            or protocol.writer_features
        ):
            raise ValueError("DATASET_DELTA_PROTOCOL_UNSUPPORTED")
        if {Path(path).resolve(strict=True) for path in table.file_uris()} != expected:
            raise ValueError("DATASET_DELTA_PARTS_MISMATCH")
        log_directory = self.directory / "_delta_log"
        if sorted(path.name for path in log_directory.glob("*.json")) != [
            "00000000000000000000.json"
        ]:
            raise ValueError("DATASET_MUTABLE_DELTA_REFUSED")
        log = log_directory / "00000000000000000000.json"
        if log.stat().st_size > 16 * 1024**2:
            raise ValueError("DATASET_DELTA_LOG_TOO_LARGE")
        # Native discovery may reorder parts. Keep profiling and the persisted
        # seeded sample in the same committed order used by future materializers.
        committed = [
            self.directory / action["add"]["path"]
            for line in log.read_text().splitlines()
            if "add" in (action := json.loads(line))
        ]
        if len(committed) != len(expected) or {
            path.resolve(strict=True) for path in committed
        } != expected:
            raise ValueError("DATASET_DELTA_PARTS_MISMATCH")
        rows = dict(zip(self.paths, self.rows))
        self.paths, self.rows = committed, [rows[path] for path in committed]
        self.closed = True
        if not self.paths:
            empty = self.directory / "empty-profile.parquet"
            self.pq.write_table(self.schema.empty_table(), empty)
            self.paths.append(empty)


if __name__ == "__main__":
    import sys

    try:
        request = json.loads(Path(sys.argv[1]).read_text())
        result = profile_files([Path(p) for p in request.pop("paths")], **request)
        Path(sys.argv[2]).write_text(json.dumps(result))
    except Exception as exc:
        print(f"DATASET_PROFILE_FAILED: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
