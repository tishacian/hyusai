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

* native DuckDB scans copy the authorized input Parquet files into temporary
  tables before sealing external access. This copy can spill to disk and is part
  of the execution budget; it does not materialize the input in Python;
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


def _parameters():
    path = os.environ.get("AGENTIUM_DATAPREP_SECRET_FILE")
    if not path:
        return {}
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def main(argv: list[str]) -> int:  # noqa: C901 - one linear pipeline, read top down
    if len(argv) != 3:
        return _fail(5, "usage: dataops_runner.py MANIFEST_JSON RESULT_JSON")
    if sys.platform == "linux":
        import ctypes
        import signal

        parent = os.getppid()
        if ctypes.CDLL(None).prctl(1, signal.SIGKILL) != 0 or os.getppid() != parent:
            return _fail(5, "dataops_parent_lost")
    manifest_path, result_path = argv[1:3]
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return _fail(5, f"dataops_manifest_unreadable: {exc}")
    views = manifest.get("views") if isinstance(manifest, dict) else None
    sql = manifest.get("sql") if isinstance(manifest, dict) else None
    output_path = manifest.get("output_path") if isinstance(manifest, dict) else None
    if (
        not isinstance(views, list)
        or not isinstance(sql, str)
        or (not isinstance(output_path, str) and not manifest.get("outputs"))
    ):
        return _fail(5, "dataops_manifest_incomplete")
    aliases = manifest.get("aliases") or {}
    row_limit = int(manifest.get("row_limit") or 0)
    max_output_bytes = int(manifest.get("max_output_bytes") or 0)
    engine = manifest.get("duckdb") or {}

    started = time.monotonic()
    try:
        import duckdb
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
            name, path = view.get("name"), view.get("paths") or view.get("path")
            if not isinstance(name, str) or not isinstance(path, (str, list)):
                return _fail(5, "dataops_manifest_bad_view")
            paths = path if isinstance(path, list) else [path]
            inputs = ",".join(_literal(p) for p in paths)
            connection.execute(
                f"CREATE TEMP TABLE {_quote(name)} AS SELECT * FROM read_parquet([{inputs}])"
            )
        for alias, target in aliases.items():
            connection.execute(f"CREATE VIEW {_quote(alias)} AS SELECT * FROM {_quote(target)}")
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
    except duckdb.OutOfMemoryException:
        return _fail(1, "SQL_EXECUTION_FAILED: DATAPREP_INPUT_MEMORY_LIMIT")
    except Exception as exc:  # noqa: BLE001 - an unreadable input is an I/O error
        return _fail(5, f"dataops_input_unreadable: {_first_line(exc)}")

    if manifest.get("outputs"):
        return _run_outputs(connection, manifest, result_path, started)
    rows = 0
    writer = None
    try:
        reader = connection.execute(sql, _parameters()).to_arrow_reader(_BATCH_ROWS)
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


def _run_outputs(connection, manifest, result_path, started):
    from pathlib import Path

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    outputs = manifest["outputs"]
    if not isinstance(outputs, list) or not outputs or len(outputs) > 8:
        return _fail(5, "dataops_outputs_invalid")
    writers, counts, paths = {}, {}, {}
    total, total_bytes = 0, 0
    try:
        reader = connection.execute(manifest["sql"], _parameters()).to_arrow_reader(_BATCH_ROWS)
        route = manifest.get("route_column")
        schema = pa.schema([field for field in reader.schema if field.name != route])
        for output in outputs:
            port = output["port"]
            if port in writers or not isinstance(output.get("path"), str):
                return _fail(5, "dataops_outputs_invalid")
            path = Path(output["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            writers[port] = pq.ParquetWriter(path, schema, compression="zstd")
            counts[port], paths[port] = 0, str(path)
        for batch in reader:
            total += batch.num_rows
            if manifest.get("row_limit") and total > manifest["row_limit"]:
                return _fail(2, "SQL_RESULT_TOO_LARGE")
            if route:
                index = batch.schema.get_field_index(route)
                if index < 0:
                    return _fail(6, "DATAPREP_ROUTE_MISSING")
                routes = batch.column(index)
                if pc.any(pc.invert(pc.is_in(routes, value_set=pa.array(list(writers))))).as_py():
                    return _fail(6, "DATAPREP_ROUTE_UNKNOWN")
                source = batch.remove_column(index)
                for port, writer in writers.items():
                    selected = pc.filter(source, pc.equal(routes, port))
                    writer.write_batch(selected)
                    counts[port] += selected.num_rows
            else:
                if len(writers) != 1:
                    return _fail(6, "DATAPREP_ROUTE_REQUIRED")
                port = next(iter(writers))
                writers[port].write_batch(batch)
                counts[port] += batch.num_rows
            total_bytes = sum(Path(p).stat().st_size for p in paths.values())
            if manifest.get("max_output_bytes") and total_bytes > manifest["max_output_bytes"]:
                return _fail(3, "SQL_OUTPUT_TOO_LARGE")
        for writer in writers.values():
            writer.close()
        writers.clear()
        Path(result_path).write_text(
            json.dumps(
                {
                    "rows": total,
                    "outputs": {
                        port: {"rows": counts[port], "path": path} for port, path in paths.items()
                    },
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                }
            )
        )
        return 0
    except Exception as exc:
        return _fail(1, f"SQL_EXECUTION_FAILED: {_first_line(exc)}")
    finally:
        for writer in writers.values():
            writer.close()
        connection.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
