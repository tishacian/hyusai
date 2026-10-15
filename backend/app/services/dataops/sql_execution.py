"""SQL transforms on the worker plane: staged, dispatched, run by the DuckDB runner.

A Flow's SQL node used to execute inside whichever process walked the Flow —
often the web process — with duckdb loading every input into memory first. It
now follows the posture of the Polars and dbt nodes: the walker stages a
``RecipeExecution``, a worker on the ``dataops`` queue runs the statement in a
supervised subprocess, and the walker follows the row. No Python environment is
involved (the runner needs only duckdb and pyarrow, which the worker image
ships), so unlike those nodes this one does not depend on the managed venv
plane being enabled.

The statement is validated and the inputs resolved before anything is queued:
an unwired node or a forbidden keyword must refuse with a coded error the
author reads at once, not as the terminal status of a job.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.recipe import RECIPE_EXECUTION_TERMINAL_STATUSES, RecipeExecution
from app.services.recipe_executions import (
    cancel_requested,
    finalize_execution,
    harness_error_line,
    supervise_harness,
)
from app.services.tabular_datasets import (
    TabularError,
    dataset_reference,
    materialize_dataset,
    register_parquet_file,
)
from app.services.tabular_transforms import (
    SQL_TRANSFORM_SKILL_SLUG,
    TransformSource,
    resolve_sources,
    validate_sql,
)

logger = get_logger(__name__)

SQL_EXECUTE_TASK = "agentium.dataops_sql_execute"
SQL_TRANSFORM_KIND = "sql_transform"

_RUNNER_PATH = Path(__file__).resolve().parents[2] / "resources" / "dataops_runner.py"

# The runner's exit codes, mapped to the codes the UI already translates.
_EXIT_CODES = {
    1: "SQL_EXECUTION_FAILED",
    2: "SQL_RESULT_TOO_LARGE",
    3: "SQL_OUTPUT_TOO_LARGE",
    4: "SQL_NO_COLUMNS",
    5: "SQL_RUNNER_ERROR",
}


def runner_path() -> Path:
    return _RUNNER_PATH


def clamp_timeout(value: Any) -> float:
    try:
        seconds = float(value) if value is not None else float(settings.dataops_sql_timeout_s)
    except (TypeError, ValueError):
        seconds = float(settings.dataops_sql_timeout_s)
    return max(1.0, min(seconds, float(settings.recipe_execution_max_timeout_s)))


def submit_sql_run(
    db: DBSession,
    *,
    workspace_id: str,
    sql: Any,
    output_name: str,
    declared: Iterable[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    timeout_s: Any = None,
    run_id: str | None = None,
    node_id: str | None = None,
    produced_by: str = SQL_TRANSFORM_SKILL_SLUG,
) -> RecipeExecution:
    """Validate, resolve, stage and dispatch one SQL transform. One call, one run."""

    statement = validate_sql(sql)
    sources = resolve_sources(db, workspace_id=workspace_id, payload=payload, declared=declared)
    execution = RecipeExecution(
        id=str(uuid4()),
        workspace_id=workspace_id,
        run_id=run_id,
        node_id=node_id,
        status="queued",
        code_sha256=hashlib.sha256(statement.encode("utf-8")).hexdigest(),
        timeout_s=clamp_timeout(timeout_s),
        input_json={
            "kind": SQL_TRANSFORM_KIND,
            "persist": True,
            "placement": "local",
            "sql": statement,
            "output_name": str(output_name or ""),
            "produced_by": produced_by,
            # Pinned by id: the rows validated here are the rows the run reads.
            "sources": [
                {"view": source.view, "dataset_id": source.dataset.id} for source in sources
            ],
        },
    )
    db.add(execution)
    from app.services.dataops.compute_registry import register as register_compute
    register_compute(db, execution)
    db.commit()
    dispatch_sql_execution(db, execution)
    return execution


def dispatch_sql_execution(db: DBSession, execution: RecipeExecution) -> str:
    """Enqueue the worker task; eager mode runs it inline (dev/tests)."""

    from app.services.execution.rollout import durable_for
    if durable_for(db, execution.workspace_id):
        from app.services.execution.dispatch import stage
        intent = stage(db, "recipe_execution", execution, deadline_at=execution.deadline_at)
        db.commit()
        return intent.task_id
    if settings.worker_eager_mode:
        execution.celery_task_id = f"eager:{execution.id}"
        db.commit()
        run_sql_execution(execution.id)
        return execution.celery_task_id
    from app.workers.celery_app import celery_app

    async_result = celery_app.send_task(
        SQL_EXECUTE_TASK,
        args=(execution.id,),
        queue=settings.celery_dataops_queue,
    )
    execution.celery_task_id = async_result.id
    db.commit()
    return async_result.id


def write_manifest(scratch: Path, sources: list[TransformSource], *, sql: str) -> dict[str, Any]:
    """Materialize the inputs and describe them, with the budgets, for the runner."""

    views: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, source in enumerate(sources):
        local = materialize_dataset(source.dataset, scratch / f"in_{index}")
        views.append({"name": source.view, "paths": [str(path) for path in local]})
        names.add(source.view)
    # Same addressing as the workshop preview: every input is also ``input_N``
    # and the first one is also ``input``, unless a view already owns the name.
    aliases: dict[str, str] = {}
    for index, source in enumerate(sources):
        alias = f"input_{index + 1}"
        if alias not in names:
            aliases[alias] = source.view
    if sources and "input" not in names:
        aliases["input"] = sources[0].view
    manifest = {
        "views": views,
        "aliases": aliases,
        "sql": sql,
        "output_path": str(scratch / "out.parquet"),
        "row_limit": int(settings.tabular_transform_max_rows),
        "max_output_bytes": int(settings.dataops_max_output_mb) * 1024 * 1024,
        "duckdb": {
            "memory_mb": int(settings.dataops_duckdb_memory_mb),
            "threads": int(settings.dataops_duckdb_threads),
            "temp_directory": str(scratch / "spill"),
            "max_temp_mb": int(settings.dataops_spill_max_mb),
        },
    }
    (scratch / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def _runner_failure(run: Any, timeout_s: float) -> str:
    if run.status == "timed_out":
        return f"SQL_TIMEOUT: the transform exceeded {int(timeout_s)}s"
    code = _EXIT_CODES.get(int(run.exit_code or 0), "SQL_RUNNER_ERROR")
    detail = harness_error_line(run.stderr_tail, "the statement failed")
    # The runner prefixes its own message with the code; say it once.
    if detail.startswith(f"{code}: "):
        detail = detail[len(code) + 2 :]
    return f"{code}: {detail[:300]}"


def _load(db: DBSession, execution_id: str) -> RecipeExecution | None:
    return db.query(RecipeExecution).filter(RecipeExecution.id == execution_id).first()


def run_sql_execution(execution_id: str) -> dict[str, Any]:  # noqa: C901 - one lifecycle
    """Worker entrypoint: settle one SQL transform end to end.

    Same lifecycle guards as the Polars plane, because it settles the same row
    type and the walker polls it the same way: a terminal row is left alone, a
    row found ``running`` was claimed by a worker that died (``acks_late``
    redelivered it) and fails closed, and the cancel flag is honoured before and
    during the run.
    """

    from app.db.base import SessionLocal

    with SessionLocal() as db:
        execution = _load(db, execution_id)
        if execution is None:
            return {"id": execution_id, "status": "missing"}
        if execution.status in RECIPE_EXECUTION_TERMINAL_STATUSES:
            return {"id": execution_id, "status": execution.status}
        if execution.status == "running":
            from app.models.execution_control import ExecutionDispatch
            if execution.lifecycle_controller == "recipe_v1" or db.query(ExecutionDispatch.id).filter_by(entity_kind="recipe_execution", entity_id=execution.id).first():
                # Redelivery is not evidence of worker loss; the lease reaper
                # alone may fence the owner. Never execute the SQL twice.
                return {"id": execution_id, "status": execution.status}
            finalize_execution(execution, status="failed", error="sql_worker_lost_after_claim")
            db.commit()
            return {"id": execution_id, "status": "failed"}
        if execution.cancel_requested:
            finalize_execution(execution, status="cancelled", error="cancel_requested")
            db.commit()
            return {"id": execution_id, "status": "cancelled"}

        from app.services.dataops.compute_registry import start as start_compute
        if not start_compute(db, execution):
            return {"id": execution_id, "status": execution.status}
        spec = dict(execution.input_json or {})
        workspace_id = execution.workspace_id
        timeout_s = clamp_timeout(execution.timeout_s)
        try:
            statement = validate_sql(spec.get("sql"))
            sources = resolve_sources(
                db,
                workspace_id=workspace_id,
                declared=[
                    entry for entry in (spec.get("sources") or []) if isinstance(entry, dict)
                ],
            )
        except TabularError as exc:
            finalize_execution(execution, status="failed", error=f"{exc.code}: {exc.message}")
            db.commit()
            return {"id": execution_id, "status": "failed"}

        execution.status = "running"
        execution.started_at = datetime.utcnow()
        db.commit()

        scratch = Path(tempfile.mkdtemp(prefix="dataops-sql-"))
        started = time.monotonic()
        status, error, output, run = "failed", None, None, None
        try:
            from app.services.execution.io_lease import maintain
            with maintain(RecipeExecution, execution.id, getattr(execution, "_native_lease_token", None), status="running"):
                manifest = write_manifest(scratch, sources, sql=statement)
            threads = int(settings.dataops_duckdb_threads)
            run = supervise_harness(
                [
                    sys.executable,
                    str(runner_path()),
                    str(scratch / "manifest.json"),
                    str(scratch / "result.json"),
                ],
                venv_python=Path(sys.executable),
                scratch=scratch,
                timeout_s=timeout_s,
                should_cancel=lambda: cancel_requested(db, execution_id),
                timeout_error=f"SQL_TIMEOUT: exceeded {int(timeout_s)}s",
                memory_limit_mb=int(settings.dataops_runner_memory_limit_mb),
                # Every engine thread burns CPU seconds against the same wall
                # clock, so the CPU ceiling scales with them or a busy join on
                # two threads is killed at half its time budget.
                cpu_limit_s=int(timeout_s * threads) + 30,
                fsize_limit_mb=max(
                    int(settings.dataops_max_output_mb), int(settings.dataops_spill_max_mb)
                ),
            )
            if run.status == "cancelled":
                status, error = "cancelled", "cancel_requested"
            elif run.status is not None or run.exit_code != 0:
                status, error = "failed", _runner_failure(run, timeout_s)
            else:
                summary = json.loads((scratch / "result.json").read_text(encoding="utf-8"))
                elapsed_ms = round((time.monotonic() - started) * 1000, 1)
                from app.services.dataops.compute_registry import begin_settlement

                begin_settlement(db, execution)
                dataset = register_parquet_file(
                    db,
                    workspace_id=workspace_id,
                    name=str(spec.get("output_name") or "").strip() or "sql result",
                    path=Path(manifest["output_path"]),
                    produced_by=str(spec.get("produced_by") or SQL_TRANSFORM_SKILL_SLUG),
                    parent_ids=[source.dataset.id for source in sources],
                    run_id=execution.run_id,
                    node_id=execution.node_id,
                    lineage={
                        "engine": "duckdb",
                        "placement": "local",
                        "sql": statement[:4000],
                        "sources": [
                            {"view": source.view, "dataset_id": source.dataset.id}
                            for source in sources
                        ],
                        "runner": {
                            "rows": summary.get("rows"),
                            "bytes": summary.get("bytes"),
                            "duration_ms": summary.get("duration_ms"),
                        },
                        "duration_ms": elapsed_ms,
                    },
                )
                db.flush()
                status = "succeeded"
                output = {
                    "kind": SQL_TRANSFORM_KIND,
                    **dataset_reference(dataset),
                    "duration_ms": elapsed_ms,
                    "sources": [source.view for source in sources],
                }
        except TabularError as exc:
            db.rollback()
            status, error = "failed", f"{exc.code}: {exc.message}"
        except Exception as exc:  # noqa: BLE001 - the row is the error channel
            db.rollback()
            logger.exception("dataops: sql run crashed", execution_id=execution_id)
            status, error = "failed", f"SQL_RUNNER_ERROR: {exc}"[:480]
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        db.expire_all()
        execution = _load(db, execution_id)
        if run is not None:
            execution.stdout_tail = run.stdout_tail
            execution.stderr_tail = run.stderr_tail
        execution.output_json = output
        finalize_execution(
            execution,
            status=status,
            error=error,
            exit_code=run.exit_code if run is not None else None,
        )
        db.commit()
        logger.info(
            "dataops: sql settled",
            execution_id=execution_id,
            status=status,
            duration_ms=execution.duration_ms,
        )
        return {"id": execution_id, "status": status}


__all__ = [
    "SQL_EXECUTE_TASK",
    "SQL_TRANSFORM_KIND",
    "clamp_timeout",
    "dispatch_sql_execution",
    "run_sql_execution",
    "runner_path",
    "submit_sql_run",
    "write_manifest",
]
