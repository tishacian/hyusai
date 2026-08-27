"""Polars transform node: author-written Python over dataset frames.

Why not just run the code in the caller
---------------------------------------
SQL is declarative and can be validated; Python cannot. So this node reuses the
recipe plane's isolation wholesale instead of inventing a second, weaker one:
the author's ``transform()`` runs on a **managed venv interpreter** through the
standalone :mod:`app.resources.polars_harness`, in a supervised subprocess with
rlimits, a hard timeout and a scrubbed environment. The application is not
importable from there, which is the property an in-process ``exec`` could never
give.

That isolation also decides *where* the code runs. Only the Celery worker mounts
the venv store (see ``docker/compose.agentium.yml``), so every Polars run —
node execution and workshop preview alike — is a ``RecipeExecution`` row settled
by ``agentium.tabular_polars_execute``. Reusing that row rather than inventing a
second job table is what gives the workshop its statuses (``env_building`` →
``running`` → terminal), its cancel button and its evidence trail for free.

Environment identity
--------------------
The engine has to live in the venv, so ``settings.tabular_polars_requirement``
*is* the environment. A Polars node cannot add libraries — leftover
``requirements_text`` on an older node is ignored so a hand-edited flow cannot
widen the venv. The env is content-addressed: every Polars node in a workspace
shares one venv, and only a platform pin change produces a new fingerprint.

Data path
---------
Frames travel as Parquet files in the scratch directory — never as JSON. The
harness reads the inputs, writes one Parquet result, and the worker reads it
back to profile it (preview) or register it as a new dataset version (node run).
Reading it back is also the validation: whatever the author returned is a real
frame by then.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.recipe import (
    RECIPE_EXECUTION_TERMINAL_STATUSES,
    PythonEnv,
    RecipeExecution,
)
from app.services.recipe_envs import (
    RecipeError,
    build_env_spec,
    env_python,
    mark_env_used,
    resolve_env,
)
from app.services.recipe_executions import (
    cancel_requested,
    ensure_env_ready,
    finalize_execution,
    harness_error_line,
    supervise_harness,
)
from app.services.tabular_datasets import (
    TabularError,
    dataset_reference,
    materialize,
    profile_frame,
    register_frame,
)
from app.services.tabular_transforms import (
    POLARS_TRANSFORM_SKILL_SLUG,
    TransformSource,
    resolve_sources,
    source_catalog,
)

logger = get_logger(__name__)

POLARS_EXECUTE_TASK = "agentium.tabular_polars_execute"

_HARNESS_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "polars_harness.py"
)

# Machine reasons the harness exits with, mapped to the codes the UI translates.
_EXIT_CODES = {
    1: "POLARS_SCRIPT_RAISED",
    3: "POLARS_TRANSFORM_MISSING",
    4: "POLARS_RESULT_NOT_TABULAR",
    5: "POLARS_RESULT_UNWRITABLE",
    6: "POLARS_HARNESS_ERROR",
}

POLARS_DEFAULT_CODE = '''import polars as pl


def transform(inputs: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Transform entry point.

    'inputs' maps every addressable source name to an eager frame; return the
    frame the node should publish as its dataset.
    """
    return inputs["input"]
'''


def harness_path() -> Path:
    return _HARNESS_PATH


def clamp_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = float(settings.tabular_polars_default_timeout_s)
    if timeout <= 0:
        timeout = float(settings.tabular_polars_default_timeout_s)
    return min(timeout, float(settings.recipe_execution_max_timeout_s))


def validate_code(code: Any) -> str:
    """Refuse an empty or oversized script before an env is even resolved."""

    text = code if isinstance(code, str) else ""
    if not text.strip():
        raise TabularError(
            code="POLARS_CODE_REQUIRED",
            message="Write a `transform(inputs)` function before running the node.",
        )
    if len(text.encode("utf-8")) > int(settings.recipe_execution_max_code_bytes):
        raise TabularError(
            code="POLARS_CODE_TOO_LARGE",
            message="The transform script exceeds the allowed size.",
        )
    return text


def effective_requirements(requirements_text: Any) -> str:
    """The pinned engine, and nothing the author declared.

    Extras in ``requirements_text`` are ignored: the environment is imposed. The
    argument stays so every call site keeps one signature; a leftover
    declaration on an older node must not widen the venv. The fingerprint still
    changes when the pin changes, so a platform upgrade of polars rebuilds the
    env instead of running the author's code against a frame format it was
    never tested on.
    """

    _ = requirements_text
    return settings.tabular_polars_requirement.strip()


def env_spec_for(
    *,
    requirements_text: Any = None,
    index_url: Any = None,
    extra_index_urls: Any = None,
):
    """Environment specification of a Polars node: the pinned engine only."""

    return build_env_spec(
        requirements_text=effective_requirements(requirements_text),
        index_url=index_url,
        extra_index_urls=extra_index_urls,
    )


def resolve_polars_env(
    db: DBSession,
    *,
    workspace_id: str,
    requirements_text: Any = None,
    index_url: Any = None,
    extra_index_urls: Any = None,
) -> PythonEnv:
    """Resolve (never build) the venv row a Polars node runs on.

    DB-only, so the API process can call it: the build itself belongs to the
    worker, which is the only container that mounts the venv store.
    """

    try:
        spec = env_spec_for(
            requirements_text=requirements_text,
            index_url=index_url,
            extra_index_urls=extra_index_urls,
        )
    except RecipeError as exc:
        raise TabularError(code=exc.code, message=exc.message) from exc
    env = resolve_env(db, workspace_id=workspace_id, spec=spec)
    db.flush()
    return env


# ---------------------------------------------------------------------------
# Dispatch (caller side: API process or run-engine walker)
# ---------------------------------------------------------------------------


def create_polars_execution(
    db: DBSession,
    *,
    workspace_id: str,
    code: Any,
    sources: list[TransformSource],
    requirements_text: Any = None,
    output_name: str = "",
    persist: bool,
    row_limit: int | None = None,
    timeout_s: Any = None,
    run_id: str | None = None,
    node_id: str | None = None,
    produced_by: str = POLARS_TRANSFORM_SKILL_SLUG,
) -> RecipeExecution:
    """Stage one Polars run as a ``RecipeExecution`` row (not yet dispatched).

    Sources are pinned by **id**, not by slug: the catalog the author saw and
    the frames the worker reads must be the same rows, or a preview would
    describe a table the run never touched.
    """

    if not settings.recipe_execution_enabled:
        raise TabularError(
            code="POLARS_EXECUTION_DISABLED",
            message=(
                "Python transforms are disabled on this instance: the managed "
                "environment plane is not enabled."
            ),
        )
    script = validate_code(code)
    env = resolve_polars_env(
        db, workspace_id=workspace_id, requirements_text=requirements_text
    )
    execution = RecipeExecution(
        id=str(uuid4()),
        workspace_id=workspace_id,
        run_id=run_id,
        node_id=node_id,
        env_id=env.id,
        env_fingerprint=env.fingerprint,
        status="queued",
        code_sha256=hashlib.sha256(script.encode("utf-8")).hexdigest(),
        timeout_s=clamp_timeout(timeout_s),
        input_json={
            "kind": "polars_transform" if persist else "polars_preview",
            "persist": bool(persist),
            "output_name": str(output_name or ""),
            "produced_by": produced_by,
            "row_limit": int(row_limit) if row_limit else None,
            "sources": [
                {"view": source.view, "dataset_id": source.dataset.id}
                for source in sources
            ],
        },
    )
    db.add(execution)
    db.flush()
    return execution


def dispatch_polars_execution(
    db: DBSession, execution: RecipeExecution, *, code: str
) -> str:
    """Enqueue the worker task; eager mode runs it inline (dev/tests)."""

    if settings.worker_eager_mode:
        execution.celery_task_id = f"eager:{execution.id}"
        db.commit()
        run_polars_execution(execution.id, code)
        return execution.celery_task_id
    from app.workers.celery_app import celery_app

    async_result = celery_app.send_task(
        POLARS_EXECUTE_TASK,
        args=(execution.id, code),
        queue=settings.celery_task_default_queue,
    )
    execution.celery_task_id = async_result.id
    db.commit()
    return async_result.id


def submit_polars_run(
    db: DBSession,
    *,
    workspace_id: str,
    code: Any,
    requirements_text: Any = None,
    declared: Iterable[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    output_name: str = "",
    persist: bool,
    row_limit: int | None = None,
    timeout_s: Any = None,
    run_id: str | None = None,
    node_id: str | None = None,
) -> tuple[RecipeExecution, list[TransformSource]]:
    """Resolve the inputs, stage the row and dispatch it. One call, one run.

    Source resolution stays synchronous on purpose: an unwired node or a
    retired dataset must refuse with a coded error the author reads instantly,
    not as the terminal status of a queued job.
    """

    sources = resolve_sources(
        db, workspace_id=workspace_id, payload=payload, declared=declared
    )
    script = validate_code(code)
    execution = create_polars_execution(
        db,
        workspace_id=workspace_id,
        code=script,
        sources=sources,
        requirements_text=requirements_text,
        output_name=output_name,
        persist=persist,
        row_limit=row_limit,
        timeout_s=timeout_s,
        run_id=run_id,
        node_id=node_id,
    )
    db.commit()
    dispatch_polars_execution(db, execution, code=script)
    return execution, sources


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------


def _write_manifest(
    scratch: Path, sources: list[TransformSource], *, row_limit: int | None
) -> dict[str, Any]:
    """Materialize the inputs as Parquet and describe them for the harness."""

    inputs: dict[str, str] = {}
    for index, source in enumerate(sources):
        local = materialize(source.dataset, scratch / f"in_{index}.parquet")
        inputs[source.view] = str(local)
        inputs[f"input_{index + 1}"] = str(local)
        if index == 0:
            inputs.setdefault("input", str(local))
    manifest: dict[str, Any] = {
        "inputs": inputs,
        "output_path": str(scratch / "out.parquet"),
    }
    if row_limit:
        manifest["row_limit"] = int(row_limit)
    (scratch / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def _harness_failure(run: Any, timeout_s: float) -> str:
    """One error string carrying the code AND the author's last traceback line."""

    if run.status == "timed_out":
        return f"POLARS_TIMEOUT: the transform exceeded {int(timeout_s)}s"
    code = _EXIT_CODES.get(int(run.exit_code or 0), "POLARS_HARNESS_ERROR")
    detail = harness_error_line(run.stderr_tail, "the transform script failed")[:300]
    return f"{code}: {detail}"


def run_polars_execution(execution_id: str, code: str) -> dict[str, Any]:
    """Worker entrypoint: settle one Polars run end-to-end.

    Mirrors ``run_recipe_execution``'s lifecycle guards (terminal short-circuit,
    ``acks_late`` redelivery fail-closed, cooperative cancel) because it settles
    the same row type and the Builder polls it the same way.
    """

    import polars as pl

    from app.db.base import SessionLocal

    with SessionLocal() as db:
        execution = (
            db.query(RecipeExecution)
            .filter(RecipeExecution.id == execution_id)
            .first()
        )
        if execution is None:
            return {"id": execution_id, "status": "missing"}
        if execution.status in RECIPE_EXECUTION_TERMINAL_STATUSES:
            return {"id": execution_id, "status": execution.status}
        if execution.status == "running":
            finalize_execution(
                execution, status="failed", error="polars_worker_lost_after_claim"
            )
            db.commit()
            return {"id": execution_id, "status": "failed"}
        if not settings.recipe_execution_enabled:
            finalize_execution(
                execution, status="failed", error="POLARS_EXECUTION_DISABLED"
            )
            db.commit()
            return {"id": execution_id, "status": "failed"}
        if execution.cancel_requested:
            finalize_execution(
                execution, status="cancelled", error="cancel_requested"
            )
            db.commit()
            return {"id": execution_id, "status": "cancelled"}

        spec = dict(execution.input_json or {})
        workspace_id = execution.workspace_id
        persist = bool(spec.get("persist"))
        row_limit = spec.get("row_limit")
        timeout_s = clamp_timeout(execution.timeout_s)

        try:
            sources = resolve_sources(
                db,
                workspace_id=workspace_id,
                declared=[
                    entry
                    for entry in (spec.get("sources") or [])
                    if isinstance(entry, dict)
                ],
            )
        except TabularError as exc:
            finalize_execution(
                execution, status="failed", error=f"{exc.code}: {exc.message}"
            )
            db.commit()
            return {"id": execution_id, "status": "failed"}

        env = ensure_env_ready(db, execution)
        if env is None:
            return {"id": execution_id, "status": execution.status}
        if cancel_requested(db, execution_id):
            execution = (
                db.query(RecipeExecution)
                .filter(RecipeExecution.id == execution_id)
                .first()
            )
            finalize_execution(execution, status="cancelled", error="cancel_requested")
            db.commit()
            return {"id": execution_id, "status": "cancelled"}

        execution.status = "running"
        execution.started_at = datetime.utcnow()
        db.commit()

        venv_python = env_python(env.workspace_id, env.fingerprint)
        scratch = Path(tempfile.mkdtemp(prefix="polars-"))
        started = time.monotonic()
        status = "failed"
        error: str | None = None
        output: dict[str, Any] | None = None
        run = None
        try:
            script_path = scratch / "transform.py"
            script_path.write_text(code, encoding="utf-8")
            manifest = _write_manifest(scratch, sources, row_limit=row_limit)
            run = supervise_harness(
                [
                    str(venv_python),
                    str(harness_path()),
                    str(script_path),
                    str(scratch / "manifest.json"),
                    str(scratch / "result.json"),
                ],
                venv_python=venv_python,
                scratch=scratch,
                timeout_s=timeout_s,
                should_cancel=lambda: cancel_requested(db, execution_id),
                timeout_error=f"POLARS_TIMEOUT: exceeded {int(timeout_s)}s",
                memory_limit_mb=int(settings.tabular_polars_memory_limit_mb),
                extra_env={
                    "POLARS_MAX_THREADS": str(settings.tabular_polars_max_threads),
                },
            )
            if run.status == "cancelled":
                status, error = "cancelled", "cancel_requested"
            elif run.status is not None or run.exit_code != 0:
                status, error = "failed", _harness_failure(run, timeout_s)
            else:
                result_path = Path(manifest["output_path"])
                if not result_path.exists():
                    status, error = (
                        "failed",
                        "POLARS_RESULT_MISSING: the transform produced no frame",
                    )
                else:
                    # Reading the Parquet back IS the validation: from here on
                    # the result is an ordinary frame the platform owns.
                    frame = pl.read_parquet(result_path)
                    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
                    status, error, output = _settle_result(
                        db,
                        workspace_id=workspace_id,
                        frame=frame,
                        sources=sources,
                        spec=spec,
                        code=code,
                        persist=persist,
                        elapsed_ms=elapsed_ms,
                        run_id=execution.run_id,
                        node_id=execution.node_id,
                    )
        except Exception as exc:  # noqa: BLE001 - the row is the error channel
            logger.exception("tabular_polars: run crashed", execution_id=execution_id)
            status, error = "failed", f"POLARS_HARNESS_ERROR: {exc}"[:480]
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        db.expire_all()
        execution = (
            db.query(RecipeExecution)
            .filter(RecipeExecution.id == execution_id)
            .first()
        )
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
        mark_env_used(db, env)
        db.commit()
        logger.info(
            "tabular_polars: settled",
            execution_id=execution_id,
            status=status,
            persist=persist,
            duration_ms=execution.duration_ms,
        )
        return {"id": execution_id, "status": status}


def _settle_result(
    db: DBSession,
    *,
    workspace_id: str,
    frame: Any,
    sources: list[TransformSource],
    spec: dict[str, Any],
    code: str,
    persist: bool,
    elapsed_ms: float,
    run_id: str | None,
    node_id: str | None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Profile a preview, or register a node run as a new dataset version."""

    profile = profile_frame(frame)
    catalog = source_catalog(sources)
    if not persist:
        return (
            "succeeded",
            None,
            {
                "kind": "polars_preview",
                "row_count": profile["row_count"],
                "column_count": profile["column_count"],
                "schema": profile["schema"],
                "preview": profile["preview"],
                "stats": profile["stats"],
                "duration_ms": elapsed_ms,
                "sources": catalog,
            },
        )
    cap = int(settings.tabular_transform_max_rows)
    if frame.height > cap:
        return (
            "failed",
            f"POLARS_RESULT_TOO_LARGE: the result exceeds {cap:,} rows",
            None,
        )
    dataset = register_frame(
        db,
        workspace_id=workspace_id,
        name=str(spec.get("output_name") or "").strip() or "polars result",
        frame=frame,
        source="transform",
        produced_by=str(spec.get("produced_by") or POLARS_TRANSFORM_SKILL_SLUG),
        parent_ids=[source.dataset.id for source in sources],
        run_id=run_id,
        node_id=node_id,
        lineage={
            "engine": "polars",
            "code_lines": len(code.splitlines()),
            "sources": [
                {"view": source.view, "dataset_id": source.dataset.id}
                for source in sources
            ],
            "duration_ms": elapsed_ms,
        },
    )
    db.flush()
    return (
        "succeeded",
        None,
        {
            "kind": "polars_transform",
            **dataset_reference(dataset),
            "duration_ms": elapsed_ms,
            "sources": [source.view for source in sources],
        },
    )


__all__ = [
    "POLARS_DEFAULT_CODE",
    "POLARS_EXECUTE_TASK",
    "clamp_timeout",
    "create_polars_execution",
    "dispatch_polars_execution",
    "effective_requirements",
    "env_spec_for",
    "harness_path",
    "resolve_polars_env",
    "run_polars_execution",
    "submit_polars_run",
    "validate_code",
]
