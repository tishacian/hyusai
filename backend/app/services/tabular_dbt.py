"""dbt transform node: a small, tested model project over dataset frames.

Why a third engine
------------------
The SQL node answers one question with one statement; the Polars node answers
one question with one script. A dbt node answers a *pipeline*: staging model,
feature model, published mart, each referring to the previous through
``ref()``, and each guarded by data tests that decide whether the result is fit
to publish at all. That last property is the reason this node exists — a
transform that refuses to version its output because ``unique(msisdn)`` failed
on three rows is a data-quality gate, not an error.

Posture
-------
Everything else is deliberately identical to the Polars plane, because the
isolation and lifecycle problems are identical: author-written SQL wrapped in
Jinja is arbitrary code (dbt macros can call the adapter), so it runs on a
**managed venv interpreter** through the standalone
:mod:`app.resources.dbt_harness`, in a supervised subprocess, tracked as a
``RecipeExecution`` row settled by ``agentium.tabular_dbt_execute``. The
workshop therefore gets the same statuses, the same cancel button and the same
evidence trail as every other managed node, for free.

Data path
---------
Inputs are materialized as Parquet in the scratch directory and loaded into a
throwaway duckdb file, which is the project's warehouse. The published model is
copied back out as Parquet by duckdb itself — so the venv only ever needs
``dbt-duckdb``, not a dataframe library — and the worker reads that Parquet to
profile it (preview) or register it as a new dataset version (node run).
"""

from __future__ import annotations

import hashlib
import json
import re
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
    DBT_TRANSFORM_SKILL_SLUG,
    TransformSource,
    resolve_sources,
    source_catalog,
)

logger = get_logger(__name__)

DBT_EXECUTE_TASK = "agentium.tabular_dbt_execute"

_HARNESS_PATH = Path(__file__).resolve().parent.parent / "resources" / "dbt_harness.py"

# dbt model names are relation names: lowercase snake_case is both the dbt
# convention and what keeps them safe to quote into duckdb DDL.
_MODEL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# Machine reasons the harness exits with, mapped to the codes the UI translates.
_EXIT_CODES = {
    1: "DBT_BUILD_FAILED",
    2: "DBT_TESTS_FAILED",
    3: "DBT_OUTPUT_MODEL_MISSING",
    4: "DBT_RESULT_NO_COLUMNS",
    5: "DBT_RESULT_UNWRITABLE",
    6: "DBT_HARNESS_ERROR",
}

DBT_DEFAULT_MODELS: list[dict[str, str]] = [
    {
        "name": "stg_input",
        "sql": (
            "-- Staging: rename and cast, one row per source row.\n"
            "select *\n"
            "from {{ source('inputs', 'input') }}\n"
        ),
    },
    {
        "name": "mart_output",
        "sql": (
            "-- Mart: what this node publishes.\n"
            "select *\n"
            "from {{ ref('stg_input') }}\n"
        ),
    },
]

DBT_DEFAULT_TESTS_YML = """version: 2

models:
  - name: mart_output
    description: The dataset this node publishes.
    # Declare a test and the node refuses to publish a result that fails it.
    # columns:
    #   - name: msisdn
    #     tests: [not_null, unique]
"""


def harness_path() -> Path:
    return _HARNESS_PATH


def clamp_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = float(settings.tabular_dbt_default_timeout_s)
    if timeout <= 0:
        timeout = float(settings.tabular_dbt_default_timeout_s)
    return min(timeout, float(settings.recipe_execution_max_timeout_s))


def validate_models(models: Any) -> list[dict[str, str]]:
    """Return the model files, or raise with a reason the author can act on."""

    entries = models if isinstance(models, list) else []
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    limit = int(settings.tabular_dbt_max_model_chars)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        sql = entry.get("sql")
        sql = sql if isinstance(sql, str) else ""
        if not name and not sql.strip():
            continue
        if not _MODEL_NAME_RE.match(name):
            raise TabularError(
                code="DBT_MODEL_NAME_INVALID",
                message=(
                    f"'{name or '(empty)'}' is not a usable model name: use "
                    "lowercase letters, digits and underscores."
                ),
                details={"name": name},
            )
        if name in seen:
            raise TabularError(
                code="DBT_MODEL_NAME_DUPLICATE",
                message=f"Two models are named '{name}'; each model is one file.",
                details={"name": name},
            )
        if not sql.strip():
            raise TabularError(
                code="DBT_MODEL_EMPTY",
                message=f"Model '{name}' is empty; write the select it materializes.",
                details={"name": name},
            )
        if len(sql) > limit:
            raise TabularError(
                code="DBT_MODEL_TOO_LARGE",
                message=f"Model '{name}' exceeds {limit:,} characters.",
                details={"name": name},
            )
        seen.add(name)
        cleaned.append({"name": name, "sql": sql})
    if not cleaned:
        raise TabularError(
            code="DBT_MODELS_REQUIRED",
            message="Write at least one model before running the node.",
        )
    maximum = int(settings.tabular_dbt_max_models)
    if len(cleaned) > maximum:
        raise TabularError(
            code="DBT_TOO_MANY_MODELS",
            message=f"A transform node carries at most {maximum} models.",
            details={"count": len(cleaned), "max": maximum},
        )
    return cleaned


def validate_tests_yml(tests_yml: Any) -> str:
    text = tests_yml if isinstance(tests_yml, str) else ""
    if len(text) > int(settings.tabular_dbt_max_model_chars):
        raise TabularError(
            code="DBT_TESTS_TOO_LARGE",
            message="The tests file exceeds the allowed size.",
        )
    return text


def resolve_output_model(models: list[dict[str, str]], requested: Any) -> str:
    """The model whose table is published; the last one by default.

    Defaulting to the last model matches how a project reads top to bottom
    (staging first, mart last) and means a freshly dropped node publishes
    something without the author choosing anything.
    """

    names = [entry["name"] for entry in models]
    wanted = str(requested or "").strip()
    if not wanted:
        return names[-1]
    if wanted not in names:
        raise TabularError(
            code="DBT_OUTPUT_MODEL_MISSING",
            message=f"'{wanted}' is not a model of this project.",
            details={"output_model": wanted, "models": names},
        )
    return wanted


def effective_requirements(requirements_text: Any) -> str:
    """The author's libraries, with the pinned adapter prepended.

    Prepending rather than assuming: the fingerprint must change when the pin
    changes, so a platform upgrade of dbt rebuilds the env instead of running a
    project against an adapter it was never compiled for.
    """

    lines = [settings.tabular_dbt_requirement.strip()]
    for raw in str(requirements_text or "").splitlines():
        line = raw.strip()
        if line:
            lines.append(line)
    return "\n".join(line for line in lines if line)


def env_spec_for(
    *,
    requirements_text: Any = None,
    index_url: Any = None,
    extra_index_urls: Any = None,
):
    """Environment specification of a dbt node (adapter pin + author extras)."""

    return build_env_spec(
        requirements_text=effective_requirements(requirements_text),
        index_url=index_url,
        extra_index_urls=extra_index_urls,
    )


def resolve_dbt_env(
    db: DBSession,
    *,
    workspace_id: str,
    requirements_text: Any = None,
    index_url: Any = None,
    extra_index_urls: Any = None,
) -> PythonEnv:
    """Resolve (never build) the venv row a dbt node runs on.

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


def project_sha256(models: list[dict[str, str]], tests_yml: str) -> str:
    """Content address of the whole project, for the execution row's evidence."""

    payload = json.dumps(
        {"models": models, "tests_yml": tests_yml}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_dbt_execution(
    db: DBSession,
    *,
    workspace_id: str,
    models: list[dict[str, str]],
    tests_yml: str,
    output_model: str,
    sources: list[TransformSource],
    requirements_text: Any = None,
    output_name: str = "",
    persist: bool,
    row_limit: int | None = None,
    timeout_s: Any = None,
    run_id: str | None = None,
    node_id: str | None = None,
    produced_by: str = DBT_TRANSFORM_SKILL_SLUG,
) -> RecipeExecution:
    """Stage one dbt run as a ``RecipeExecution`` row (not yet dispatched).

    The project travels in ``input_json`` rather than as a task argument: a
    model tree is far too large to be a Celery payload, and the row is the
    evidence trail the Builder polls anyway.
    """

    if not settings.recipe_execution_enabled:
        raise TabularError(
            code="DBT_EXECUTION_DISABLED",
            message=(
                "dbt transforms are disabled on this instance: the managed "
                "environment plane is not enabled."
            ),
        )
    env = resolve_dbt_env(
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
        code_sha256=project_sha256(models, tests_yml),
        timeout_s=clamp_timeout(timeout_s),
        input_json={
            "kind": "dbt_transform" if persist else "dbt_preview",
            "persist": bool(persist),
            "output_name": str(output_name or ""),
            "produced_by": produced_by,
            "row_limit": int(row_limit) if row_limit else None,
            "models": models,
            "tests_yml": tests_yml,
            "output_model": output_model,
            "sources": [
                {"view": source.view, "dataset_id": source.dataset.id}
                for source in sources
            ],
        },
    )
    db.add(execution)
    db.flush()
    return execution


def dispatch_dbt_execution(db: DBSession, execution: RecipeExecution) -> str:
    """Enqueue the worker task; eager mode runs it inline (dev/tests)."""

    if settings.worker_eager_mode:
        execution.celery_task_id = f"eager:{execution.id}"
        db.commit()
        run_dbt_execution(execution.id)
        return execution.celery_task_id
    from app.workers.celery_app import celery_app

    async_result = celery_app.send_task(
        DBT_EXECUTE_TASK,
        args=(execution.id,),
        queue=settings.celery_task_default_queue,
    )
    execution.celery_task_id = async_result.id
    db.commit()
    return async_result.id


def submit_dbt_run(
    db: DBSession,
    *,
    workspace_id: str,
    models: Any,
    tests_yml: Any = None,
    output_model: Any = None,
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

    Project validation and source resolution stay synchronous on purpose: a
    misnamed model or an unwired node must refuse with a coded error the author
    reads instantly, not as the terminal status of a queued job.
    """

    project = validate_models(models)
    tests = validate_tests_yml(tests_yml)
    selected = resolve_output_model(project, output_model)
    sources = resolve_sources(
        db, workspace_id=workspace_id, payload=payload, declared=declared
    )
    _refuse_shadowed_models(project, sources)
    execution = create_dbt_execution(
        db,
        workspace_id=workspace_id,
        models=project,
        tests_yml=tests,
        output_model=selected,
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
    dispatch_dbt_execution(db, execution)
    return execution, sources


def _refuse_shadowed_models(
    models: list[dict[str, str]], sources: list[TransformSource]
) -> None:
    """A model may not be named after a source: both are relations in ``main``.

    dbt would fail deep in the adapter with "table already exists"; naming the
    collision here tells the author which of their two names to change.
    """

    reserved = {source.view for source in sources}
    reserved.update(f"input_{index + 1}" for index in range(len(sources)))
    if sources:
        reserved.add("input")
    for entry in models:
        if entry["name"] in reserved:
            raise TabularError(
                code="DBT_MODEL_SHADOWS_SOURCE",
                message=(
                    f"Model '{entry['name']}' has the same name as an input; "
                    "rename the model."
                ),
                details={"name": entry["name"]},
            )


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------


def _write_manifest(
    scratch: Path,
    sources: list[TransformSource],
    spec: dict[str, Any],
    *,
    row_limit: int | None,
) -> dict[str, Any]:
    """Materialize the inputs as Parquet and describe the project for the harness."""

    inputs: dict[str, str] = {}
    for index, source in enumerate(sources):
        local = materialize(source.dataset, scratch / f"in_{index}.parquet")
        inputs[source.view] = str(local)
        inputs[f"input_{index + 1}"] = str(local)
        if index == 0:
            inputs.setdefault("input", str(local))
    manifest: dict[str, Any] = {
        "models": spec.get("models") or [],
        "tests_yml": spec.get("tests_yml") or "",
        "output_model": spec.get("output_model") or "",
        "sources": inputs,
        "output_path": str(scratch / "out.parquet"),
        "threads": int(settings.tabular_dbt_max_threads),
    }
    if row_limit:
        manifest["row_limit"] = int(row_limit)
    (scratch / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def read_summary(path: Path) -> dict[str, Any] | None:
    """The harness summary, which exists even when the build failed."""

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _harness_failure(
    run: Any, summary: dict[str, Any] | None, timeout_s: float
) -> str:
    """One error string carrying the code AND the sentence the author needs.

    dbt's own structured result is a far better source than the stderr tail: a
    duckdb binder error ends in a caret line, while the node result carries the
    message that names the missing column. The tail is only the fallback.
    """

    if run.status == "timed_out":
        return f"DBT_TIMEOUT: the project exceeded {int(timeout_s)}s"
    code = _EXIT_CODES.get(int(run.exit_code or 0), "DBT_HARNESS_ERROR")
    detail = ""
    if summary:
        if code == "DBT_TESTS_FAILED":
            failed = [
                node
                for node in summary.get("nodes") or []
                if node.get("kind") == "test"
                and node.get("status") not in ("pass", "success")
            ]
            detail = ", ".join(
                f"{node.get('name')} ({int(node.get('failures') or 0)} rows)"
                for node in failed[:3]
            )
        else:
            broken = [
                node
                for node in summary.get("nodes") or []
                if node.get("status") not in ("success", "pass", "skipped")
            ]
            if broken:
                message = str(broken[0].get("message") or "").strip()
                detail = " ".join(message.split())[:300]
    if not detail:
        detail = harness_error_line(run.stderr_tail, "the dbt project failed")[:300]
    return f"{code}: {detail}"


def run_dbt_execution(execution_id: str) -> dict[str, Any]:
    """Worker entrypoint: settle one dbt run end-to-end.

    Mirrors ``run_polars_execution``'s lifecycle guards (terminal short-circuit,
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
                execution, status="failed", error="dbt_worker_lost_after_claim"
            )
            db.commit()
            return {"id": execution_id, "status": "failed"}
        if not settings.recipe_execution_enabled:
            finalize_execution(
                execution, status="failed", error="DBT_EXECUTION_DISABLED"
            )
            db.commit()
            return {"id": execution_id, "status": "failed"}
        if execution.cancel_requested:
            finalize_execution(execution, status="cancelled", error="cancel_requested")
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
        scratch = Path(tempfile.mkdtemp(prefix="dbt-"))
        started = time.monotonic()
        status = "failed"
        error: str | None = None
        output: dict[str, Any] | None = None
        run = None
        try:
            manifest = _write_manifest(scratch, sources, spec, row_limit=row_limit)
            run = supervise_harness(
                [
                    str(venv_python),
                    str(harness_path()),
                    str(scratch / "manifest.json"),
                    str(scratch / "result.json"),
                ],
                venv_python=venv_python,
                scratch=scratch,
                timeout_s=timeout_s,
                should_cancel=lambda: cancel_requested(db, execution_id),
                timeout_error=f"DBT_TIMEOUT: exceeded {int(timeout_s)}s",
                memory_limit_mb=int(settings.tabular_dbt_memory_limit_mb),
                extra_env={"DO_NOT_TRACK": "1", "DBT_SEND_ANONYMOUS_USAGE_STATS": "0"},
            )
            summary = read_summary(scratch / "result.json")
            if run.status == "cancelled":
                status, error = "cancelled", "cancel_requested"
            elif run.status is not None or run.exit_code != 0:
                status = "failed"
                error = _harness_failure(run, summary, timeout_s)
                # A failed build still has a verdict worth rendering: which
                # model broke, which test refused the data.
                output = {"kind": "dbt_failed", "dbt": _build_report(summary)}
            else:
                result_path = Path(manifest["output_path"])
                if not result_path.exists():
                    status, error = (
                        "failed",
                        "DBT_RESULT_MISSING: the project produced no table",
                    )
                else:
                    frame = pl.read_parquet(result_path)
                    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
                    status, error, output = _settle_result(
                        db,
                        workspace_id=workspace_id,
                        frame=frame,
                        sources=sources,
                        spec=spec,
                        summary=summary,
                        persist=persist,
                        elapsed_ms=elapsed_ms,
                        run_id=execution.run_id,
                        node_id=execution.node_id,
                    )
        except Exception as exc:  # noqa: BLE001 - the row is the error channel
            logger.exception("tabular_dbt: run crashed", execution_id=execution_id)
            status, error = "failed", f"DBT_HARNESS_ERROR: {exc}"[:480]
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
            "tabular_dbt: settled",
            execution_id=execution_id,
            status=status,
            persist=persist,
            duration_ms=execution.duration_ms,
        )
        return {"id": execution_id, "status": status}


def _build_report(summary: dict[str, Any] | None) -> dict[str, Any]:
    """The dbt verdict, shaped for the workshop's Tests panel."""

    source = summary or {}
    nodes = [node for node in source.get("nodes") or [] if isinstance(node, dict)]
    return {
        "nodes": nodes,
        "models_total": int(source.get("models_total") or 0),
        "tests_total": int(source.get("tests_total") or 0),
        "tests_failed": int(source.get("tests_failed") or 0),
        "selected": str(source.get("selected") or ""),
    }


def _settle_result(
    db: DBSession,
    *,
    workspace_id: str,
    frame: Any,
    sources: list[TransformSource],
    spec: dict[str, Any],
    summary: dict[str, Any] | None,
    persist: bool,
    elapsed_ms: float,
    run_id: str | None,
    node_id: str | None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Profile a preview, or register a node run as a new dataset version."""

    profile = profile_frame(frame)
    catalog = source_catalog(sources)
    report = _build_report(summary)
    if not persist:
        return (
            "succeeded",
            None,
            {
                "kind": "dbt_preview",
                "row_count": profile["row_count"],
                "column_count": profile["column_count"],
                "schema": profile["schema"],
                "preview": profile["preview"],
                "stats": profile["stats"],
                "duration_ms": elapsed_ms,
                "sources": catalog,
                "dbt": report,
            },
        )
    cap = int(settings.tabular_transform_max_rows)
    if frame.height > cap:
        return (
            "failed",
            f"DBT_RESULT_TOO_LARGE: the result exceeds {cap:,} rows",
            {"kind": "dbt_failed", "dbt": report},
        )
    models = spec.get("models") if isinstance(spec.get("models"), list) else []
    dataset = register_frame(
        db,
        workspace_id=workspace_id,
        name=str(spec.get("output_name") or "").strip() or "dbt result",
        frame=frame,
        source="transform",
        produced_by=str(spec.get("produced_by") or DBT_TRANSFORM_SKILL_SLUG),
        parent_ids=[source.dataset.id for source in sources],
        run_id=run_id,
        node_id=node_id,
        lineage={
            "engine": "dbt-duckdb",
            "models": [str(entry.get("name") or "") for entry in models],
            "output_model": report["selected"] or str(spec.get("output_model") or ""),
            "tests_total": report["tests_total"],
            "tests_failed": report["tests_failed"],
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
            "kind": "dbt_transform",
            **dataset_reference(dataset),
            "duration_ms": elapsed_ms,
            "sources": [source.view for source in sources],
            "dbt": report,
        },
    )


__all__ = [
    "DBT_DEFAULT_MODELS",
    "DBT_DEFAULT_TESTS_YML",
    "DBT_EXECUTE_TASK",
    "clamp_timeout",
    "create_dbt_execution",
    "dispatch_dbt_execution",
    "effective_requirements",
    "env_spec_for",
    "harness_path",
    "project_sha256",
    "read_summary",
    "resolve_dbt_env",
    "resolve_output_model",
    "run_dbt_execution",
    "submit_dbt_run",
    "validate_models",
    "validate_tests_yml",
]
