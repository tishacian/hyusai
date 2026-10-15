"""Preparation on the bounded worker plane, with atomic multi-output commit."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text, update

from app.core.config import settings
from app.models.recipe import RECIPE_EXECUTION_TERMINAL_STATUSES, RecipeExecution
from app.models.tabular import TabularDataset
from app.schemas.data_prep import DataPrepSpec
from app.services.dataops.compiler import compile_prep
from app.services.dataops.storage import (
    dataset_digest,
    dataset_digest_matches,
    identity_digest,
    materialize_files,
    settle_files,
)
from app.services.recipe_executions import cancel_requested, finalize_execution, supervise_harness
from app.services.tabular_datasets import (
    dataset_reference,
    reserve_frame,
    resolve_dataset_ref,
    slugify,
)


def compile_inputs(db, workspace_id: str, spec: DataPrepSpec, inputs: dict):
    if not isinstance(inputs, dict) or not inputs or len(inputs) > 16:
        raise ValueError("DATAPREP_INPUT_PORTS_INVALID")
    datasets = {
        port: resolve_dataset_ref(db, workspace_id=workspace_id, ref=ref)
        for port, ref in inputs.items()
    }
    if any(dataset.status != "ready" for dataset in datasets.values()):
        raise ValueError("DATASET_NOT_READY")
    from app.services.dataops.preview import native_schema
    from app.services.dataops.types import describe

    arrow_schemas = {port: native_schema(dataset) for port, dataset in datasets.items()}
    schemas = {port: describe(schema) for port, schema in arrow_schemas.items()}
    identities = {
        port: {"id": dataset.id, "version": dataset.version, "digest": identity_digest(dataset)}
        for port, dataset in datasets.items()
    }
    return compile_prep(spec, schemas, identities=identities, arrow_schemas=arrow_schemas), datasets


def submit_preparation(
    db,
    *,
    workspace_id: str,
    spec: DataPrepSpec | dict,
    inputs: dict,
    run_id: str | None = None,
    node_id: str | None = None,
    request_key: str | None = None,
    placement: str = "auto",
    timeout_s: int | None = None,
):
    from app.services.dataops.rollout import enabled

    if not enabled(db, workspace_id, "dataops_enabled"):
        raise ValueError("DATAPREP_DISABLED")
    if placement not in {"auto", "local"}:
        raise ValueError("DATAPREP_PLACEMENT_UNAVAILABLE")
    if timeout_s is not None and (
        type(timeout_s) is not int or not 1 <= timeout_s <= settings.dataops_t0_max_timeout_s
    ):
        raise ValueError("DATAPREP_TIMEOUT_INVALID")
    spec = spec if isinstance(spec, DataPrepSpec) else DataPrepSpec.model_validate(spec)
    if len({slugify(output.name) for output in spec.outputs}) != len(spec.outputs):
        raise ValueError("DATAPREP_OUTPUT_NAME_DUPLICATE")
    compiled, datasets = compile_inputs(db, workspace_id, spec, inputs)
    identity = (
        hashlib.sha256(
            json.dumps(
                [workspace_id, run_id, node_id, request_key, compiled.fingerprint],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:36]
        if run_id or request_key
        else str(uuid4())
    )
    existing = db.get(RecipeExecution, identity)
    if existing:
        return existing
    outputs = {}
    for output in spec.outputs:
        slug = slugify(output.name)
        if db.bind.dialect.name == "postgresql":
            lock = int.from_bytes(
                hashlib.sha256(f"{workspace_id}/{slug}".encode()).digest()[:8], "big", signed=True
            )
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        previous = (
            db.query(TabularDataset)
            .filter_by(workspace_id=workspace_id, slug=slug)
            .order_by(TabularDataset.version.desc())
            .first()
        )
        if previous:
            from app.models.run import Run

            producer_run = db.get(Run, run_id) if run_id else None
            same_producer = bool(
                run_id
                and node_id
                and previous.produced_by == "data_prep_v1"
                and previous.node_id == node_id
                and producer_run is not None
                and producer_run.workspace_id == workspace_id
                and previous.system_id == producer_run.system_id
            )
            if output.append_version_of:
                pinned = resolve_dataset_ref(
                    db, workspace_id=workspace_id, ref={"dataset_id": output.append_version_of}
                )
                if pinned.slug != slug:
                    raise ValueError("DATAPREP_APPEND_SLUG_MISMATCH")
            elif not same_producer:
                raise ValueError("DATAPREP_OUTPUT_SLUG_TAKEN")
        row = reserve_frame(
            db,
            workspace_id=workspace_id,
            name=output.name,
            source="transform",
            produced_by="data_prep_v1",
            parent_ids=[d.id for d in datasets.values()],
            run_id=run_id,
            node_id=node_id,
            lineage={
                "fingerprint": compiled.fingerprint,
                "placement": "local",
                "operation": spec.operation,
                "prep": {
                    "operation": spec.operation,
                    "spec_version": spec.version,
                    "spec": spec.canonical(),
                    "fingerprint": compiled.fingerprint,
                    "placement": "local",
                    "output_port": output.port,
                    "inputs": {
                        port: {
                            "dataset_id": dataset.id,
                            "version": dataset.version,
                            "rows": dataset.row_count,
                        }
                        for port, dataset in datasets.items()
                    },
                },
            },
            commit=False,
        )
        outputs[output.port] = row.id
    execution = RecipeExecution(
        id=identity,
        workspace_id=workspace_id,
        run_id=run_id,
        node_id=node_id,
        status="queued",
        timeout_s=timeout_s or settings.dataops_t0_max_timeout_s,
        code_sha256=compiled.fingerprint,
        input_json={
            "kind": "data_prep",
            "spec": spec.model_dump(mode="json"),
            "inputs": {p: d.id for p, d in datasets.items()},
            "input_digests": {p: dataset_digest(d) for p, d in datasets.items()},
            "asset_inputs": {
                p: ref for p, ref in inputs.items() if isinstance(ref, dict) and ref.get("asset_id")
            },
            "outputs": outputs,
            "sql": compiled.sql,
        },
    )
    db.add(execution)
    from app.services.dataops.compute_registry import register as register_compute
    register_compute(db, execution)
    db.commit()
    if settings.worker_eager_mode:
        run_preparation(execution.id)
    else:
        from app.workers.celery_app import celery_app

        result = celery_app.send_task(
            "agentium.dataops_prepare",
            args=[execution.id],
            queue=settings.celery_dataops_queue,
            task_id=execution.id,
        )
        execution.celery_task_id = result.id
        db.commit()
    db.refresh(execution)
    return execution


def run_preparation(execution_id: str):

    from app.db.base import SessionLocal

    with SessionLocal() as db:
        row = db.get(RecipeExecution, execution_id)
        if row is None or row.status in RECIPE_EXECUTION_TERMINAL_STATUSES:
            return {"id": execution_id, "status": row.status if row else "missing"}
        from app.services.dataops.compute_registry import start as start_compute
        if not start_compute(db, row):
            return {"id": execution_id, "status": row.status}
        claimed = db.execute(
            update(RecipeExecution)
            .where(RecipeExecution.id == execution_id, RecipeExecution.status == "queued")
            .values(status="running", started_at=datetime.utcnow())
        )
        db.commit()
        if claimed.rowcount != 1:
            return {"id": execution_id, "status": "running"}
        db.refresh(row)
        config = dict(row.input_json)
        try:
            with tempfile.TemporaryDirectory(prefix="data-prep-") as tmp:
                root = Path(tmp)
                views = []
                for port, identifier in config["inputs"].items():
                    dataset = resolve_dataset_ref(
                        db, workspace_id=row.workspace_id, ref={"dataset_id": identifier}
                    )
                    if not dataset_digest_matches(dataset, config["input_digests"][port]):
                        raise ValueError("DATAPREP_INPUT_CHANGED")
                    views.append(
                        {
                            "name": port,
                            "paths": [str(p) for p in materialize_files(dataset, root / port)],
                        }
                    )
                for reference in config.get("asset_inputs", {}).values():
                    resolve_dataset_ref(db, workspace_id=row.workspace_id, ref=reference)
                spec = DataPrepSpec.model_validate(config["spec"])
                manifest = {
                    "views": views,
                    "sql": config["sql"],
                    "outputs": [
                        {
                            "port": p,
                            "path": str(
                                root
                                / "out"
                                / p
                                / (
                                    "delta"
                                    if settings.dataops_write_delta_enabled
                                    else "data.parquet"
                                )
                            ),
                            "format": "delta"
                            if settings.dataops_write_delta_enabled
                            else "parquet",
                        }
                        for p in config["outputs"]
                    ],
                    "route_column": "__dp_output" if spec.operation == "split" else None,
                    "row_limit": 0,
                    "max_output_bytes": settings.dataops_max_output_mb * 1024**2,
                    "part_target_bytes": settings.dataops_part_max_mb * 1024**2,
                    "duckdb": {
                        "memory_mb": settings.dataops_duckdb_memory_mb,
                        "threads": settings.dataops_duckdb_threads,
                        "temp_directory": str(root / "spill"),
                        "max_temp_mb": settings.dataops_spill_max_mb,
                    },
                }
                from app.services.dataops.secrets import hash_parameters

                secret_params = hash_parameters(
                    spec, db, workspace_id=row.workspace_id, run_id=row.run_id, node_id=row.node_id
                )
                extra_env = {}
                if secret_params:
                    secret_file = root / "private-params.json"
                    secret_file.touch(mode=0o600)
                    secret_file.write_text(json.dumps(secret_params))
                    extra_env["AGENTIUM_DATAPREP_SECRET_FILE"] = str(secret_file)
                (root / "manifest.json").write_text(json.dumps(manifest))
                result = supervise_harness(
                    [
                        sys.executable,
                        str(Path(__file__).resolve().parents[2] / "resources/dataops_runner.py"),
                        str(root / "manifest.json"),
                        str(root / "result.json"),
                    ],
                    extra_env=extra_env,
                    venv_python=Path(sys.executable),
                    scratch=root,
                    timeout_s=row.timeout_s,
                    should_cancel=lambda: cancel_requested(db, execution_id),
                    timeout_error="DATAPREP_TIMEOUT",
                    memory_limit_mb=settings.dataops_runner_memory_limit_mb,
                    cpu_limit_s=int(row.timeout_s * settings.dataops_duckdb_threads) + 30,
                    fsize_limit_mb=max(
                        settings.dataops_max_output_mb, settings.dataops_spill_max_mb
                    ),
                )
                if result.status is not None or result.exit_code != 0:
                    raise ValueError(
                        f"DATAPREP_{result.status or 'FAILED'}: {result.stderr_tail[-400:]}"
                    )
                from app.services.dataops.compute_registry import begin_settlement

                begin_settlement(db, row)
                row = (
                    db.query(RecipeExecution)
                    .filter_by(id=execution_id)
                    .with_for_update()
                    .populate_existing()
                    .one()
                )
                if row.status != "running" or row.cancel_requested:
                    raise ValueError("DATAPREP_FENCE_LOST")
                summary = json.loads((root / "result.json").read_text())
                envelope = {}
                for port, identifier in config["outputs"].items():
                    target = db.get(TabularDataset, identifier)
                    output = summary["outputs"][port]
                    paths = [Path(p).resolve(strict=True) for p in output["paths"]]
                    authorized = (root / "out" / port).resolve()
                    if any(not path.is_relative_to(authorized) for path in paths):
                        raise ValueError("DATAPREP_OUTPUT_PATH_INVALID")
                    delta_root = (
                        Path(output["delta_root"]).resolve() if output.get("delta_root") else None
                    )
                    if delta_root is not None and delta_root != authorized / "delta":
                        raise ValueError("DATAPREP_OUTPUT_PATH_INVALID")
                    settle_files(
                        db, target, paths, delta_root=delta_root, profile=output["profile"]
                    )
                    envelope[port] = dataset_reference(target)
                if cancel_requested(db, execution_id):
                    raise ValueError("DATAPREP_CANCELLED")
                db.refresh(row)
                if row.status != "running":
                    raise ValueError("DATAPREP_FENCE_LOST")
                row.output_json = {
                    **next(iter(envelope.values())),
                    "outputs": envelope,
                    "operation": spec.operation,
                    "placement": "local",
                    "fingerprint": row.code_sha256,
                    "inputs": {
                        port: {
                            "dataset_id": identifier,
                            "rows": db.get(TabularDataset, identifier).row_count,
                        }
                        for port, identifier in config["inputs"].items()
                    },
                }
                finalize_execution(row, status="succeeded", exit_code=0)
                db.commit()
        except Exception as exc:
            db.rollback()
            row = db.get(RecipeExecution, execution_id)
            if row.status not in RECIPE_EXECUTION_TERMINAL_STATUSES:
                finalize_execution(
                    row,
                    status="cancelled" if row.cancel_requested else "failed",
                    error=str(exc)[:480],
                )
            for identifier in config["outputs"].values():
                output = db.get(TabularDataset, identifier)
                if output and output.status == "ingesting":
                    output.status, output.error = "failed", str(exc)[:480]
            db.commit()
        return {"id": execution_id, "status": row.status, "output": row.output_json}


def preview_preparation(
    db,
    *,
    workspace_id: str,
    spec: DataPrepSpec,
    inputs: dict,
    step_id=None,
    limit=None,
    output_port=None,
):
    from app.services.dataops.preview import preview
    from app.services.dataops.preview_graph import compile_preview_graph

    compiled, datasets = compile_preview_graph(db, workspace_id, spec, inputs, step_id=step_id)
    from app.services.dataops.samples import ensure_samples

    ensure_samples(db, workspace_id, datasets)
    return preview(compiled, datasets, spec, limit=limit, output_port=output_port)
