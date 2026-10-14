"""Fresh-process preview execution; authored SQL never runs in the web process.

This file is also the child entry point. Only the standard library is imported
before strict OS limits are installed. No application configuration or secrets
are inherited by the child, and only fixed error codes cross back to the API.
"""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REQUEST_BYTES = 8 * 1024**2
RESULT_BYTES = 32 * 1024**2
# Arrow/DuckDB native mappings use ~490 MiB of virtual space before useful
# computation (RSS was ~160 MiB in qualification). Keep that reservation separate
# from DuckDB's configured execution budget: default AS is 512 + 512 = 1024 MiB.
# This is a hard virtual-address ceiling, not a promise about resident memory.
NATIVE_RESERVE_MB = 512
ERROR_CODES = frozenset(
    {
        "DATAPREP_PREVIEW_MEMORY_LIMIT",
        "DATAPREP_PREVIEW_TIMEOUT",
        "DATAPREP_PREVIEW_OUTPUT_LIMIT",
        "DATAPREP_PREVIEW_REQUEST_LIMIT",
        "DATAPREP_PREVIEW_ISOLATION_UNAVAILABLE",
        "DATAPREP_PREVIEW_FAILED",
        "DATAPREP_TYPE_MISMATCH",
        "DATAPREP_SAMPLE_MEMORY_LIMIT",
    }
)


def _write_json(path, value, maximum):
    size = 0
    with path.open("wb") as handle:
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(value):
            data = chunk.encode()
            size += len(data)
            if size > maximum:
                raise ValueError("DATAPREP_PREVIEW_OUTPUT_LIMIT")
            handle.write(data)


def _active_members(group):
    if Path("/proc").is_dir():
        active = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if os.getpgid(int(entry.name)) != group:
                    continue
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[2]) == group and fields[0] not in {"Z", "X"}:
                    active.append(int(entry.name))
            except (FileNotFoundError, ProcessLookupError):
                continue
        return active
    # macOS has no procfs; ps exposes process state without treating a zombie
    # awaiting its OS reaper as a still-running descendant.
    rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,pgid=,stat="], text=True, timeout=1)
    return [
        int(pid)
        for pid, pgid, state in (row.split() for row in rows.splitlines())
        if int(pgid) == group and state[0] not in {"Z", "X"}
    ]


def _kill_and_reap(process):
    # The child executes closed SQL and cannot spawn commands; killing its fresh
    # session also handles any library descendants on cancellation/interruption.
    deadline = time.monotonic() + 2
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        raise ValueError("DATAPREP_PREVIEW_CLEANUP_FAILED") from None
    finally:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
            while _active_members(process.pid):
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired("preview cleanup", 2)
                time.sleep(0.01)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            raise ValueError("DATAPREP_PREVIEW_CLEANUP_FAILED") from None


def run_isolated(job, scratch, *, memory_mb, timeout_s):
    request = scratch / "request.json"
    result = scratch / "result.json"
    error = scratch / "error.json"
    try:
        _write_json(request, job, REQUEST_BYTES)
    except ValueError:
        raise ValueError("DATAPREP_PREVIEW_REQUEST_LIMIT") from None
    # Like recipe supervision, pin allocator arenas and all native thread pools.
    # Do not reuse its preexec_fn: previews start from the multithreaded API, and
    # RLIMIT_AS must fail closed rather than being best-effort in a fork hook.
    env = {
        "PATH": f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
        "LANG": "C.UTF-8",
        "MALLOC_ARENA_MAX": "2",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "POLARS_MAX_THREADS": "1",
        "ARROW_NUM_THREADS": "1",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            str(scratch),
            str(memory_mb),
            str(timeout_s),
        ],
        cwd=scratch,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise ValueError("DATAPREP_PREVIEW_TIMEOUT") from None
    finally:
        # This runs on timeout, KeyboardInterrupt and any other caller failure.
        _kill_and_reap(process)
    if error.exists():
        raw = error.read_bytes() if error.stat().st_size <= 256 else b""
        try:
            code = json.loads(raw).get("code")
        except (ValueError, AttributeError):
            code = None
        raise ValueError(code if code in ERROR_CODES else "DATAPREP_PREVIEW_FAILED")
    if process.returncode == -signal.SIGXCPU:
        raise ValueError("DATAPREP_PREVIEW_TIMEOUT")
    if process.returncode == -signal.SIGXFSZ:
        raise ValueError("DATAPREP_PREVIEW_OUTPUT_LIMIT")
    if process.returncode or not result.is_file():
        raise ValueError("DATAPREP_PREVIEW_FAILED")
    if result.stat().st_size > RESULT_BYTES:
        raise ValueError("DATAPREP_PREVIEW_OUTPUT_LIMIT")
    with result.open("rb") as handle:
        raw = handle.read(RESULT_BYTES + 1)
    if len(raw) > RESULT_BYTES:
        raise ValueError("DATAPREP_PREVIEW_OUTPUT_LIMIT")
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
            raise ValueError
        return value
    except ValueError:
        raise ValueError("DATAPREP_PREVIEW_FAILED") from None


def _limits(memory_mb, timeout_s):
    import resource

    def strict(kind, value):
        _, hard = resource.getrlimit(kind)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(kind, (value, value))
        if resource.getrlimit(kind) != (value, value):
            raise OSError("resource limit was not installed")

    strict(resource.RLIMIT_AS, (int(memory_mb) + NATIVE_RESERVE_MB) * 1024**2)
    strict(resource.RLIMIT_CPU, max(1, math.ceil(float(timeout_s))))
    strict(resource.RLIMIT_FSIZE, RESULT_BYTES)
    strict(resource.RLIMIT_CORE, 0)


def _json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    # Match the public preview's existing date/decimal JSON representation.
    if not isinstance(value, (str, int, float, bool, type(None))):
        from app.resources.dataops_storage import _json_scalar

        return _json_scalar(value)
    return value


def _execute(job):
    from types import SimpleNamespace

    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq
    import sqlglot
    from sqlglot import exp

    from app.services.dataops.compiler import literal, quote
    from app.services.dataops.preview_stats import conversion_counters, profile

    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    compiled = SimpleNamespace(**job["compiled"])
    spec = SimpleNamespace(
        operation=job["operation"],
        steps=[SimpleNamespace(**step) for step in job["steps"]],
    )
    conn = duckdb.connect(config={"threads": 1, "memory_limit": f"{job['memory_mb']}MB"})
    try:
        conn.execute("SET TimeZone='UTC'")
        conn.execute("SET temp_directory=''")
        total, counts = 0, {}
        for port, info in job["inputs"].items():
            parquet = pq.ParquetFile(info["path"])
            expanded = sum(
                parquet.metadata.row_group(i).total_byte_size
                for i in range(parquet.metadata.num_row_groups)
            )
            if expanded > job["input_mb"] * 1024**2:
                raise ValueError("DATAPREP_SAMPLE_MEMORY_LIMIT")
            batches, rows = [], 0
            for batch in parquet.iter_batches(batch_size=1000, use_threads=False):
                take = min(batch.num_rows, job["sample_rows"] - rows)
                if take <= 0:
                    break
                batches.append(batch.slice(0, take))
                rows += take
            table = pa.Table.from_batches(batches, schema=parquet.schema_arrow)
            total += table.nbytes
            if total > job["input_mb"] * 1024**2:
                raise ValueError("DATAPREP_SAMPLE_MEMORY_LIMIT")
            counts[port] = {
                "rows": table.num_rows,
                "of_rows": info["of_rows"],
                "method": info["method"],
            }
            conn.register("__sample", table)
            conn.execute(f"CREATE TEMP TABLE {quote(port)} AS SELECT * FROM __sample")
            conn.unregister("__sample")
        conn.execute("SET enable_external_access=false")
        conn.execute("SET lock_configuration=true")

        def execute(sql):
            used = {n.name for n in sqlglot.parse_one(sql, read="duckdb").find_all(exp.Placeholder)}
            parameters = {k: v for k, v in compiled.preview_parameters.items() if k in used}
            return conn.execute(sql, parameters)

        execute(f"CREATE TEMP TABLE __preview_output AS {compiled.sql}")
        predicate = (
            f" WHERE __dp_output={literal(job['output_port'])}"
            if job["output_port"] and spec.operation == "split"
            else ""
        )
        result = conn.execute(
            f"SELECT {','.join(quote(n) for n in compiled.columns)} FROM __preview_output{predicate} LIMIT {job['limit']}"
        ).to_arrow_table()
        output_counts = (
            dict(
                conn.execute(
                    "SELECT __dp_output,count(*) FROM __preview_output GROUP BY __dp_output"
                ).fetchall()
            )
            if spec.operation == "split"
            else {"out": conn.execute("SELECT count(*) FROM __preview_output").fetchone()[0]}
        )
        return {
            "rows": result.to_pylist(),
            "schema": [
                {"name": f.name, "dtype": str(f.type), "nullable": f.nullable}
                for f in result.schema
            ],
            "sample": True,
            "stats": profile(conn, result.schema, predicate),
            "stats_scope": "sample",
            "sample_metadata": {
                "method": "persisted",
                "inputs": counts,
                "max_rows_per_input": job["sample_rows"],
            },
            "fingerprint": compiled.fingerprint,
            "output_schema": compiled.output_schema,
            "step_schemas": compiled.step_schemas,
            "warnings": compiled.warnings,
            "counters": {
                "inputs": {port: info["rows"] for port, info in counts.items()},
                "outputs": output_counts,
                "steps": conversion_counters(conn, compiled, spec, execute),
            },
            "sample_info": {
                "rows": sum(info["rows"] for info in counts.values()),
                "of_rows": sum(info["of_rows"] or 0 for info in counts.values()),
                "version": {port: info["version"] for port, info in job["inputs"].items()},
            },
        }
    finally:
        conn.close()


def main():
    scratch = Path(sys.argv[1])
    code = None
    try:
        _limits(sys.argv[2], sys.argv[3])
    except (ImportError, AttributeError, OSError, ValueError):
        code = "DATAPREP_PREVIEW_ISOLATION_UNAVAILABLE"
    if code is None:
        try:
            # -I excludes inherited Python paths; this is the trusted package root.
            sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
            with (scratch / "request.json").open("rb") as handle:
                raw = handle.read(REQUEST_BYTES + 1)
            if len(raw) > REQUEST_BYTES:
                raise ValueError("DATAPREP_PREVIEW_REQUEST_LIMIT")
            job = json.loads(raw)
            value = _json_value(_execute(job))
            _write_json(scratch / "result.json", value, RESULT_BYTES)
        except MemoryError:
            code = "DATAPREP_PREVIEW_MEMORY_LIMIT"
        except Exception as exc:
            # Never send engine details: they may contain SQL or cell contents.
            if type(exc).__name__ in {"OutOfMemoryException", "ArrowMemoryError"}:
                code = "DATAPREP_PREVIEW_MEMORY_LIMIT"
            elif type(exc).__name__ == "InterruptException":
                code = "DATAPREP_PREVIEW_TIMEOUT"
            elif str(exc) in ERROR_CODES:
                code = str(exc)
            else:
                code = "DATAPREP_TYPE_MISMATCH"
    if code:
        (scratch / "error.json").write_text(json.dumps({"code": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
