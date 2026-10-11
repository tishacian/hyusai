"""Standalone DuckDB runner: one validated statement over Parquet, streamed to Parquet.

The same program serves every placement of a data transform. On the worker it
runs as a supervised subprocess (rlimits, hard timeout, cooperative cancel);
later in an ephemeral pod. So it imports nothing from the application and reads
everything it needs from a manifest:

  {"views": [{"name": "orders", "path": "/scratch/in_0.parquet"}, ...],
   "aliases": {"input": "orders", "input_1": "orders"},
   "sql": "<statement already validated by the platform>",
   "output_path": "/scratch/out.parquet",
   "row_limit": 5000000, "max_output_bytes": 4294967296,
   "duckdb": {"memory_mb": 1024, "threads": 2,
              "temp_directory": "/scratch/spill", "max_temp_mb": 4096}}

Three things differ from the in-process engine it replaces, and they are the
point of moving it:

* inputs are scanned lazily through ``pyarrow.dataset``: projection and filter
  push down, so a statement reading two columns of a wide table never loads the
  rest, and nothing is copied into a duckdb table first;
* the result streams to Parquet batch by batch, so the runner's memory is the
  engine's working set, not the size of the answer;
* past its memory budget duckdb spills to ``temp_directory`` instead of
  failing. That is also why the seal is ``enable_external_access = false`` plus
  ``lock_configuration`` rather than disabling the local filesystem: the latter
  forbids the spill files too, while the former still refuses every path the
  statement could name (``read_*``, ``COPY``, ``ATTACH``, ``INSTALL``, globs)
  and the lock refuses switching it back.

Exit codes are the machine contract with the supervising worker:
  0 success · 1 statement failed · 2 too many rows · 3 output too large ·
  4 no column · 5 manifest or I/O error
"""

from __future__ import annotations

import json
import os
import sys
import time

_BATCH_ROWS = 122_880  # a multiple of duckdb's vector size


def _fail(code: int, message: str) -> int:
    print(message, file=sys.stderr, flush=True)
    return code


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _literal(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _first_line(exc: BaseException) -> str:
    for line in str(exc).strip().splitlines():
        if line.strip():
            return line.strip()[:400]
    return type(exc).__name__


def main(argv: list[str]) -> int:  # noqa: C901 - one linear pipeline, read top down
    if len(argv) != 3:
        return _fail(5, "usage: dataops_runner.py MANIFEST_JSON RESULT_JSON")
    manifest_path, result_path = argv[1:3]
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return _fail(5, f"dataops_manifest_unreadable: {exc}")
    views = manifest.get("views") if isinstance(manifest, dict) else None
    sql = manifest.get("sql") if isinstance(manifest, dict) else None
    output_path = manifest.get("output_path") if isinstance(manifest, dict) else None
    if not isinstance(views, list) or not isinstance(sql, str) or not isinstance(output_path, str):
        return _fail(5, "dataops_manifest_incomplete")
    aliases = manifest.get("aliases") or {}
    row_limit = int(manifest.get("row_limit") or 0)
    max_output_bytes = int(manifest.get("max_output_bytes") or 0)
    engine = manifest.get("duckdb") or {}

    started = time.monotonic()
    try:
        import duckdb
        import pyarrow.dataset as ds
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - the runtime ships both
        return _fail(5, f"dataops_engine_missing: {exc}")

    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(f"SET threads TO {max(1, int(engine.get('threads') or 1))}")
        connection.execute(f"SET memory_limit = '{max(16, int(engine.get('memory_mb') or 256))}MB'")
        temp_directory = engine.get("temp_directory")
        max_temp_mb = int(engine.get("max_temp_mb") or 0)
        if temp_directory and max_temp_mb > 0:
            os.makedirs(temp_directory, exist_ok=True)
            connection.execute(f"SET temp_directory = {_literal(temp_directory)}")
            connection.execute(f"SET max_temp_directory_size = '{max_temp_mb}MB'")
        else:
            # No disk granted: running out of memory is an error, not a spill.
            connection.execute("SET temp_directory = ''")
        for view in views:
            name, path = view.get("name"), view.get("path")
            if not isinstance(name, str) or not isinstance(path, str):
                return _fail(5, "dataops_manifest_bad_view")
            connection.register(name, ds.dataset(path, format="parquet"))
        for alias, target in aliases.items():
            connection.execute(f"CREATE VIEW {_quote(alias)} AS SELECT * FROM {_quote(target)}")
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
    except Exception as exc:  # noqa: BLE001 - an unreadable input is an I/O error
        return _fail(5, f"dataops_input_unreadable: {_first_line(exc)}")

    rows = 0
    writer = None
    try:
        reader = connection.execute(sql).to_arrow_reader(_BATCH_ROWS)
        if not len(reader.schema):
            return _fail(4, "SQL_NO_COLUMNS: the statement returned no columns")
        writer = pq.ParquetWriter(output_path, reader.schema, compression="zstd")
        for batch in reader:
            rows += batch.num_rows
            if row_limit and rows > row_limit:
                # Stopping here is the gain over the in-process engine: an
                # oversized answer is refused before it is computed in full.
                return _fail(2, f"SQL_RESULT_TOO_LARGE: the result exceeds {row_limit:,} rows")
            writer.write_batch(batch)
            if max_output_bytes and os.path.getsize(output_path) > max_output_bytes:
                return _fail(
                    3,
                    f"SQL_OUTPUT_TOO_LARGE: the result exceeds {max_output_bytes // 1024**2:,} MB",
                )
        writer.close()
        writer = None
    except Exception as exc:  # noqa: BLE001 - the engine's message is the answer
        return _fail(1, f"SQL_EXECUTION_FAILED: {_first_line(exc)}")
    finally:
        if writer is not None:
            writer.close()
        connection.close()

    summary = {
        "rows": rows,
        "bytes": os.path.getsize(output_path),
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }
    try:
        with open(result_path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle)
    except OSError as exc:
        return _fail(5, f"dataops_summary_unwritable: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
