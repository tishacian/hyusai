"""Measure real preparation/scoring workers with bounded batches and a native model.

Generated inputs are explicitly synthetic, either repeated serving examples or
deterministic variations within their ranges; they never assert customer quality.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import resource
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.core.config import settings
from app.models.tabular import MLModel, TabularDataset
from app.services.dataops.ingestion import register_batches
from app.services.dataops.preparation import submit_preparation
from app.services.dataops.scoring import submit_score
from app.services.dataops.storage import dataset_digest, delta_manifest, is_delta
from app.services.service_promises import require_member
from app.services.tabular_datasets import reserve_frame, resolve_dataset_ref
from app.services.tabular_predict import contract_fields, serving_version


def _rss_tree(pid):
    # Some container proc mounts omit task/*/children. PPid in process status
    # still allows descendants to be measured without counting unrelated tests.
    processes = {}
    for path in Path("/proc").glob("[0-9]*/status"):
        try:
            status = dict(line.split(":", 1) for line in path.read_text().splitlines())
            processes[int(path.parent.name)] = (
                int(status["PPid"]),
                int(status.get("VmRSS", "0 kB").split()[0]) * 1024,
            )
        except (OSError, ValueError, KeyError):
            continue
    descendants = {pid}
    while (
        additions := {p for p, (parent, _) in processes.items() if parent in descendants}
        - descendants
    ):
        descendants.update(additions)
    return sum(processes[p][1] for p in descendants if p in processes)


@contextmanager
def _memory():
    stopped = threading.Event()
    result = {
        "baseline_rss_bytes": _rss_tree(os.getpid()),
        "peak_tree_sampled_rss_bytes": 0,
        "sampling_interval_ms": 50,
        "sampled_scope": "visible_process_tree_via_proc_ppid",
    }

    def sample():
        while not stopped.is_set():
            result["peak_tree_sampled_rss_bytes"] = max(
                result["peak_tree_sampled_rss_bytes"], _rss_tree(os.getpid())
            )
            stopped.wait(0.05)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        yield result
    finally:
        stopped.set()
        thread.join(timeout=1)
        result["peak_process_rss_bytes"] = int(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        )
        result["max_child_rss_bytes"] = int(
            resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024
        )


def _mix64(values):
    """Deterministic counters, independent of batch boundaries."""
    import numpy as np

    values = values.astype(np.uint64, copy=True)
    values = (values ^ (values >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    values = (values ^ (values >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return values ^ (values >> np.uint64(31))


def synthetic_batches(model, rows, batch_rows, *, extra_columns=0, varied_inputs=False):
    import numpy as np
    import pyarrow as pa

    fields = [field["name"] for field in contract_fields(model)]
    examples = model.input_example_json
    if (
        not isinstance(examples, list)
        or not examples
        or any(
            not isinstance(row, dict) or any(field not in row for field in fields)
            for row in examples
        )
    ):
        raise ValueError("BENCHMARK_NATIVE_INPUT_EXAMPLE_REQUIRED")
    # Infer once from the persisted serving example; every yielded table is
    # bounded by batch_rows and preserves the model's exact feature order.
    schema = pa.Table.from_pylist(
        [{field: row[field] for field in fields} for row in examples]
    ).schema
    extras = [f"benchmark_extra_{index:02d}" for index in range(extra_columns)]
    if set(extras) & set(fields):
        raise ValueError("BENCHMARK_EXTRA_COLUMN_COLLISION")
    schema = pa.schema(
        [
            *schema,
            *[
                pa.field(name, pa.int64() if index == 0 else pa.float64())
                for index, name in enumerate(extras)
            ],
        ]
    )

    def batches():
        cycle = itertools.cycle(examples)
        remaining = rows
        while remaining:
            count = min(remaining, batch_rows)
            row_ids = np.arange(rows - remaining, rows - remaining + count, dtype=np.uint64)
            records = [
                {field: row[field] for field in fields} for row in itertools.islice(cycle, count)
            ]
            columns = []
            for index, field in enumerate(schema):
                mixed = _mix64(row_ids + np.uint64((index + 1) * 7919))
                uniform = (mixed >> np.uint64(11)).astype(np.float64) / 9007199254740992.0
                if field.name in extras:
                    values = row_ids.astype(np.int64) if field.name == extras[0] else uniform
                elif varied_inputs:
                    example_values = [row[field.name] for row in examples]
                    if pa.types.is_floating(field.type) or pa.types.is_integer(field.type):
                        finite = [float(value) for value in example_values if value is not None]
                        if not finite:
                            raise ValueError("BENCHMARK_NUMERIC_EXAMPLE_REQUIRED")
                        low, high = min(finite), max(finite)
                        values = low + (high - low) * uniform
                        if pa.types.is_integer(field.type):
                            values = np.floor(values).astype(np.int64)
                    else:
                        values = [example_values[int(value % len(examples))] for value in mixed]
                else:
                    values = [row[field.name] for row in records]
                columns.append(pa.array(values, type=field.type))
            yield pa.RecordBatch.from_arrays(columns, schema=schema)
            remaining -= count

    return schema, batches()


def _artifact(dataset):
    return {
        "dataset_id": dataset.id,
        "version": dataset.version,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "size_bytes": dataset.size_bytes,
        "digest": dataset_digest(dataset),
        "format": "delta" if is_delta(dataset) else "parquet",
        "part_count": len(delta_manifest(dataset)["files"]) if is_delta(dataset) else 1,
    }


def benchmark(
    db,
    *,
    workspace_id,
    owner_user_id,
    model_id,
    model_version=None,
    dataset_id=None,
    synthetic_input=False,
    rows=3_000_000,
    extra_columns=0,
    varied_inputs=False,
    progress_path=None,
):
    if type(rows) is not int or not 1 <= rows <= min(
        3_000_000, settings.ml_score_streaming_max_rows
    ):
        raise ValueError("BENCHMARK_ROW_BUDGET_INVALID")
    if bool(dataset_id) == bool(synthetic_input):
        raise ValueError("BENCHMARK_CHOOSE_DATASET_OR_SYNTHETIC_INPUT")
    if (
        type(extra_columns) is not int
        or not 0 <= extra_columns <= 128
        or (not synthetic_input and (extra_columns or varied_inputs))
    ):
        raise ValueError("BENCHMARK_SYNTHETIC_OPTIONS_INVALID")
    require_member(db, workspace_id, owner_user_id, admin=True)
    requested = db.query(MLModel).filter_by(id=model_id, workspace_id=workspace_id).one()
    model = serving_version(db, requested, version=model_version or requested.version)
    if model.family not in {"tabular", "clustering"}:
        raise ValueError("BENCHMARK_MODEL_FAMILY_UNSUPPORTED")
    # Local worker calls are deliberate for measurement; this changes this CLI
    # process only and never enables workspace or deployment feature flags.
    overrides = {
        "worker_eager_mode": True,
        "dataops_enabled": True,
        "dataops_write_delta_enabled": True,
        "ml_score_streaming_enabled": True,
    }
    previous = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        setattr(settings, key, value)
    identifier = uuid4().hex
    method = (
        "counter_hash_native_example_ranges"
        if varied_inputs
        else "cyclic_native_model_input_example"
    )
    phases = {}
    started = time.perf_counter()

    def checkpoint(phase, **values):
        if progress_path is not None:
            path = Path(progress_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "phase": phase,
                        "benchmark_id": identifier,
                        "elapsed_seconds": time.perf_counter() - started,
                        "observed_at": datetime.now(UTC).isoformat(),
                        "phases": phases,
                        "memory": memory,
                        **values,
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            )
            temporary.replace(path)

    try:
        with _memory() as memory:
            checkpoint("ingestion")
            if synthetic_input:
                input_row = reserve_frame(
                    db,
                    workspace_id=workspace_id,
                    name=f"Synthetic volume benchmark {identifier}",
                    source="generated",
                    produced_by="dataops_showcase_benchmark",
                    created_by=owner_user_id,
                    lineage={
                        "synthetic": True,
                        "method": method,
                        "extra_columns": extra_columns,
                        "benchmark_id": identifier,
                        "model_id": model.id,
                    },
                )
                schema, batches = synthetic_batches(
                    model,
                    rows,
                    settings.dataops_batch_rows,
                    extra_columns=extra_columns,
                    varied_inputs=varied_inputs,
                )
                before = time.perf_counter()
                with TemporaryDirectory(prefix="showcase-benchmark-ingest-") as directory:
                    register_batches(
                        db, input_row, batches, schema=schema, directory=Path(directory), delta=True
                    )
                db.commit()
                phases["ingestion_seconds"] = time.perf_counter() - before
            else:
                input_row = resolve_dataset_ref(
                    db, workspace_id=workspace_id, ref={"dataset_id": dataset_id}
                )
                if input_row.status != "ready" or input_row.row_count != rows:
                    raise ValueError("BENCHMARK_EXACT_READY_ROWS_REQUIRED")
                phases["ingestion_seconds"] = None
            checkpoint("preparation", input=_artifact(input_row))
            before = time.perf_counter()
            prepared = submit_preparation(
                db,
                workspace_id=workspace_id,
                spec={
                    "operation": "prepare",
                    "steps": [
                        {
                            "action": "select",
                            "params": {
                                "columns": [field["name"] for field in contract_fields(model)]
                                + [f"benchmark_extra_{index:02d}" for index in range(extra_columns)]
                            },
                        }
                    ],
                    "outputs": [{"port": "out", "name": f"Benchmark prepared {identifier}"}],
                },
                inputs={"in": {"dataset_id": input_row.id}},
                request_key=identifier,
            )
            if prepared.status != "succeeded":
                raise ValueError("BENCHMARK_PREPARATION_FAILED")
            phases["preparation_seconds"] = time.perf_counter() - before
            prepared_row = db.get(TabularDataset, prepared.output_json["dataset_id"])
            checkpoint("scoring", input=_artifact(input_row), prepared=_artifact(prepared_row))
            before = time.perf_counter()
            scored = submit_score(
                db,
                workspace_id=workspace_id,
                model_id=model.id,
                version=model.version,
                dataset_ref={"dataset_id": prepared_row.id},
                output_name=f"Benchmark scored {identifier}",
            )
            if scored.status != "succeeded":
                raise ValueError("BENCHMARK_SCORING_FAILED")
            phases["scoring_seconds"] = time.perf_counter() - before
            output = db.get(TabularDataset, scored.output_json["dataset_id"])
            if (
                input_row.row_count,
                prepared_row.row_count,
                output.row_count,
                scored.output_json["scored_rows"],
                scored.output_json["excluded_rows"],
            ) != (rows, rows, rows, rows, 0):
                raise ValueError("BENCHMARK_CARDINALITY_FAILED")
            result = {
                "schema_version": 1,
                "benchmark_id": identifier,
                "observed_at": datetime.now(UTC).isoformat(),
                "execution_surface": "direct_worker_benchmark",
                "synthetic_input": synthetic_input,
                "synthetic_method": method if synthetic_input else None,
                "extra_columns": extra_columns,
                "varied_inputs": varied_inputs,
                "business_quality_claim": False,
                "model": {"id": model.id, "version": model.version, "family": model.family},
                "input": _artifact(input_row),
                "prepared": _artifact(prepared_row),
                "output": _artifact(output),
                "cardinality": {"expected": rows, "processed": rows, "excluded": 0},
                "phases": phases,
                "total_seconds": time.perf_counter() - started,
                "memory": memory,
                "batch_rows": settings.dataops_batch_rows,
                "receipts_created": 0,
            }
            checkpoint("completed", status="completed")
        return result
    finally:
        for key, value in previous.items():
            setattr(settings, key, value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--owner-user-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-version", type=int)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset-id")
    source.add_argument("--synthetic-input", action="store_true")
    parser.add_argument("--extra-columns", type=int, default=0)
    parser.add_argument("--varied-inputs", action="store_true")
    parser.add_argument("--rows", type=int, choices=[2_000_000, 3_000_000], default=3_000_000)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    import app.models  # noqa: F401
    from app.db.base import SessionLocal

    values = vars(args).copy()
    report = values.pop("report")
    values["progress_path"] = report.with_suffix(report.suffix + ".progress.json")
    with SessionLocal() as db:
        result = benchmark(db, **values)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
