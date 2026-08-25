"""Recipe execution lifecycle: dispatch, worker-side run, cancel, serialize.

Split of responsibilities with the walker wrapper (``python_recipe_v1``):

* the wrapper (backend process) creates the ``RecipeExecution`` row, enqueues
  ``agentium.recipe_execute`` and polls the row until terminal;
* the Celery worker resolves/builds the venv, runs the author script through
  the stdlib harness in a supervised subprocess (rlimits + hard timeout +
  cooperative cancel), and persists the terminal evidence.

The subprocess is container-level isolation only: it runs inside the worker
container as the worker uid, with CPU/memory/file-size rlimits and a scratch
working directory. Per-execution containers would need a Docker socket the
worker deliberately does not have.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
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
    EnvSpec,
    RecipeError,
    build_env,
    env_dir,
    env_python,
    mark_env_used,
    resolve_env,
)

logger = get_logger(__name__)

RECIPE_EXECUTE_TASK = "agentium.recipe_execute"
RECIPE_ENV_BUILD_TASK = "agentium.recipe_env_build"
RECIPE_ENV_SWEEP_TASK = "agentium.recipe_env_sweep"

_HARNESS_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "recipe_harness.py"
)
_CANCEL_POLL_INTERVAL_S = 0.5


def harness_path() -> Path:
    return _HARNESS_PATH


def clamp_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = float(settings.recipe_execution_default_timeout_s)
    if timeout <= 0:
        timeout = float(settings.recipe_execution_default_timeout_s)
    return min(timeout, float(settings.recipe_execution_max_timeout_s))


def validate_code(code: Any) -> str:
    if not isinstance(code, str) or not code.strip():
        raise RecipeError(
            code="RECIPE_CODE_REQUIRED",
            message="The recipe script is empty; write a `main(inputs)` function.",
        )
    if len(code.encode("utf-8")) > int(settings.recipe_execution_max_code_bytes):
        raise RecipeError(
            code="RECIPE_CODE_TOO_LARGE",
            message="The recipe script exceeds the allowed size.",
        )
    return code


def create_execution(
    db: DBSession,
    *,
    workspace_id: str,
    env: PythonEnv,
    code: str,
    inputs: dict[str, Any],
    timeout_s: float,
    run_id: str | None = None,
    node_id: str | None = None,
    invocation_id: str | None = None,
) -> RecipeExecution:
    execution = RecipeExecution(
        id=str(uuid4()),
        workspace_id=workspace_id,
        run_id=run_id,
        node_id=node_id,
        invocation_id=invocation_id,
        env_id=env.id,
        env_fingerprint=env.fingerprint,
        status="queued",
        code_sha256=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        timeout_s=timeout_s,
        input_json=inputs,
    )
    db.add(execution)
    db.flush()
    return execution


def dispatch_execution(
    db: DBSession, execution: RecipeExecution, *, code: str
) -> str:
    """Enqueue the Celery task; eager mode runs it inline (dev/tests)."""

    if settings.worker_eager_mode:
        execution.celery_task_id = f"eager:{execution.id}"
        db.commit()
        run_recipe_execution(execution.id, code)
        return execution.celery_task_id
    from app.workers.celery_app import celery_app

    async_result = celery_app.send_task(
        RECIPE_EXECUTE_TASK,
        args=(execution.id, code),
        queue=settings.celery_task_default_queue,
    )
    execution.celery_task_id = async_result.id
    db.commit()
    return async_result.id


def request_cancel(db: DBSession, execution: RecipeExecution) -> RecipeExecution:
    """Cooperative cancel; a still-queued task is also revoked best-effort."""

    if execution.status in RECIPE_EXECUTION_TERMINAL_STATUSES:
        return execution
    execution.cancel_requested = True
    if execution.status == "queued":
        task_id = execution.celery_task_id
        if task_id and not str(task_id).startswith("eager:"):
            try:
                from app.workers.celery_app import celery_app

                celery_app.control.revoke(task_id)
            except Exception:  # noqa: BLE001 - DB flag stays authoritative
                logger.warning(
                    "recipe_executions: revoke failed", execution_id=execution.id
                )
        finalize_execution(execution, status="cancelled", error="cancel_requested")
    db.commit()
    return execution


def finalize_execution(
    execution: RecipeExecution,
    *,
    status: str,
    error: str | None = None,
    exit_code: int | None = None,
) -> None:
    """Stamp a terminal status, its reason and the measured duration.

    Shared with the Polars transform plane, which settles the same row type: the
    lifecycle of a ``RecipeExecution`` has to be written in exactly one place or
    the Builder's polling would read two different truths.
    """

    execution.status = status
    execution.error = error
    if exit_code is not None:
        execution.exit_code = exit_code
    execution.finished_at = datetime.utcnow()
    if execution.started_at is not None:
        execution.duration_ms = (
            execution.finished_at - execution.started_at
        ).total_seconds() * 1000


def serialize_execution(execution: RecipeExecution) -> dict[str, Any]:
    return {
        "id": execution.id,
        "run_id": execution.run_id,
        "node_id": execution.node_id,
        "invocation_id": execution.invocation_id,
        "env_id": execution.env_id,
        "env_fingerprint": execution.env_fingerprint,
        "status": execution.status,
        "cancel_requested": bool(execution.cancel_requested),
        "timeout_s": execution.timeout_s,
        "exit_code": execution.exit_code,
        "stdout_tail": execution.stdout_tail,
        "stderr_tail": execution.stderr_tail,
        "output_json": execution.output_json,
        "error": execution.error,
        "created_at": execution.created_at.isoformat()
        if execution.created_at
        else None,
        "started_at": execution.started_at.isoformat()
        if execution.started_at
        else None,
        "finished_at": execution.finished_at.isoformat()
        if execution.finished_at
        else None,
        "duration_ms": execution.duration_ms,
    }


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------


def _subprocess_env(
    venv_python: Path, scratch: Path, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Minimal environment: venv first on PATH, no application secrets."""

    env = {
        "PATH": f"{venv_python.parent}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "VIRTUAL_ENV": str(venv_python.parent.parent),
    }
    env.update(extra or {})
    return env


def _apply_rlimits(
    memory_limit_mb: int, cpu_limit_s: int, fsize_limit_mb: int
) -> None:  # pragma: no cover - child process
    import resource

    cpu_s = int(cpu_limit_s)
    mem_bytes = int(memory_limit_mb) * 1024 * 1024
    fsize = int(fsize_limit_mb) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except (ValueError, OSError):
        pass
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass


def _read_tail(path: Path) -> str:
    limit = int(settings.recipe_execution_log_tail_chars)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text if len(text) <= limit else text[-limit:]


def cancel_requested(db: DBSession, execution_id: str) -> bool:
    """Re-read the cooperative cancel flag (the supervisor's stop condition)."""

    db.expire_all()
    value = (
        db.query(RecipeExecution.cancel_requested)
        .filter(RecipeExecution.id == execution_id)
        .scalar()
    )
    return bool(value)


def ensure_env_ready(
    db: DBSession, execution: RecipeExecution
) -> Optional[PythonEnv]:
    """Bring the row's venv to ``ready``, flipping the row to ``env_building``.

    Returns ``None`` after finalizing the execution as failed, so the caller's
    only job is to stop. Shared with the Polars plane: a first run in a
    workspace pays the build once, and the author watches that status.
    """

    env = (
        db.query(PythonEnv).filter(PythonEnv.id == execution.env_id).first()
        if execution.env_id
        else None
    )
    if env is None:
        finalize_execution(execution, status="failed", error="recipe_env_not_found")
        db.commit()
        return None
    if env.status != "ready" or not env_python(env.workspace_id, env.fingerprint).exists():
        execution.status = "env_building"
        db.commit()
        env = build_env(db, env.id)
        if env.status != "ready":
            finalize_execution(
                execution,
                status="failed",
                error=f"recipe_env_build_failed: {env.build_error or env.status}",
            )
            db.commit()
            return None
    return env


def run_recipe_execution(execution_id: str, code: str) -> dict[str, Any]:
    """Worker entrypoint: settle one RecipeExecution end-to-end."""

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
            # acks_late redelivery of a lost worker. The script may already
            # have produced side effects; fail closed instead of replaying.
            finalize_execution(
                execution, status="failed", error="recipe_worker_lost_after_claim"
            )
            db.commit()
            return {"id": execution_id, "status": "failed"}
        if not settings.recipe_execution_enabled:
            finalize_execution(execution, status="failed", error="recipe_execution_disabled")
            db.commit()
            return {"id": execution_id, "status": "failed"}
        if execution.cancel_requested:
            finalize_execution(execution, status="cancelled", error="cancel_requested")
            db.commit()
            return {"id": execution_id, "status": "cancelled"}

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

        status, error, exit_code, stdout_tail, stderr_tail, output = _run_supervised(
            db,
            execution_id=execution.id,
            env=env,
            code=code,
            inputs=dict(execution.input_json or {}),
            timeout_s=clamp_timeout(execution.timeout_s),
        )

        db.expire_all()
        execution = (
            db.query(RecipeExecution)
            .filter(RecipeExecution.id == execution_id)
            .first()
        )
        execution.stdout_tail = stdout_tail
        execution.stderr_tail = stderr_tail
        execution.output_json = output
        finalize_execution(execution, status=status, error=error, exit_code=exit_code)
        mark_env_used(db, env)
        db.commit()
        logger.info(
            "recipe_executions: settled",
            execution_id=execution.id,
            status=status,
            exit_code=exit_code,
            duration_ms=execution.duration_ms,
        )
        return {"id": execution.id, "status": status}


@dataclass(slots=True)
class SupervisedRun:
    """Outcome of one supervised harness subprocess.

    ``status`` is ``None`` when the process settled on its own — the caller then
    interprets ``exit_code`` against its harness contract. It is ``timed_out``
    or ``cancelled`` when the supervisor is the one that ended the process.
    """

    status: str | None
    error: str | None
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str


def supervise_harness(
    argv: list[str],
    *,
    venv_python: Path,
    scratch: Path,
    timeout_s: float,
    should_cancel: Callable[[], bool] | None = None,
    timeout_error: str | None = None,
    memory_limit_mb: int | None = None,
    cpu_limit_s: int | None = None,
    fsize_limit_mb: int = 64,
    extra_env: dict[str, str] | None = None,
) -> SupervisedRun:
    """Run one harness under rlimits, a hard timeout and a cooperative cancel.

    Shared by every node that runs work in a subprocess it does not trust to
    stop on its own (recipes, Polars and dbt transforms, sklearn training): the
    isolation posture is a property of the platform, not of one node type, so it
    lives in one place. The environment handed to the child carries no
    application variable — the interpreter on ``PATH`` and a scratch
    ``HOME``/``TMPDIR``, plus whatever ``extra_env`` the caller's engine needs.

    The three budgets are per-engine because the engines are not comparable:

    * ``memory_limit_mb`` caps the **virtual** address space (``RLIMIT_AS``), and
      an arena allocator reserves far more than it commits, so a dataframe
      engine needs a wider ceiling than a plain script to even finish importing;
    * ``cpu_limit_s`` is the last resort against a runaway loop, and a model fit
      is legitimately CPU-bound for minutes where a transform is not;
    * ``fsize_limit_mb`` caps any single file the child writes, so an engine
      that writes its own artifact (a serialized pipeline is megabytes) needs
      more room than one that writes a Parquet result.
    """

    budget = int(
        memory_limit_mb
        if memory_limit_mb is not None
        else settings.recipe_execution_memory_limit_mb
    )
    cpu_budget = int(
        cpu_limit_s
        if cpu_limit_s is not None
        else settings.recipe_execution_cpu_limit_s
    )
    fsize_budget = int(fsize_limit_mb)

    stdout_path = scratch / "stdout.log"
    stderr_path = scratch / "stderr.log"
    deadline = time.monotonic() + timeout_s
    status: str | None = None
    error: str | None = None
    with (
        open(stdout_path, "wb") as stdout_handle,
        open(stderr_path, "wb") as stderr_handle,
    ):
        process = subprocess.Popen(  # noqa: S603 - venv python + harness path
            argv,
            cwd=scratch,
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            env=_subprocess_env(venv_python, scratch, extra_env),
            start_new_session=True,
            # noqa: PLW1509 - single-threaded fork point
            preexec_fn=lambda: _apply_rlimits(budget, cpu_budget, fsize_budget),
        )
        last_cancel_check = 0.0
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                break
            now = time.monotonic()
            if now > deadline:
                _kill_process_group(process)
                process.wait(timeout=10)
                status, error, exit_code = (
                    "timed_out",
                    timeout_error or f"recipe_timeout_after_{int(timeout_s)}s",
                    None,
                )
                break
            if now - last_cancel_check >= 1.0:
                last_cancel_check = now
                if should_cancel is not None and should_cancel():
                    _kill_process_group(process)
                    process.wait(timeout=10)
                    status, error, exit_code = ("cancelled", "cancel_requested", None)
                    break
            time.sleep(_CANCEL_POLL_INTERVAL_S)

    return SupervisedRun(
        status=status,
        error=error,
        exit_code=exit_code,
        stdout_tail=_read_tail(stdout_path),
        stderr_tail=_read_tail(stderr_path),
    )


def _run_supervised(
    db: DBSession,
    *,
    execution_id: str,
    env: PythonEnv,
    code: str,
    inputs: dict[str, Any],
    timeout_s: float,
) -> tuple[str, str | None, int | None, str, str, dict[str, Any] | None]:
    """Run the harness subprocess; returns (status, error, exit_code, tails, output)."""

    venv_python = env_python(env.workspace_id, env.fingerprint)
    scratch = Path(tempfile.mkdtemp(prefix="recipe-", dir=None))
    try:
        script_path = scratch / "recipe.py"
        input_path = scratch / "input.json"
        output_path = scratch / "output.json"
        script_path.write_text(code, encoding="utf-8")
        input_path.write_text(json.dumps(inputs, ensure_ascii=False), encoding="utf-8")

        run = supervise_harness(
            [
                str(venv_python),
                str(harness_path()),
                str(script_path),
                str(input_path),
                str(output_path),
            ],
            venv_python=venv_python,
            scratch=scratch,
            timeout_s=timeout_s,
            should_cancel=lambda: cancel_requested(db, execution_id),
        )
        status = run.status
        error = run.error
        exit_code = run.exit_code
        stdout_tail = run.stdout_tail
        stderr_tail = run.stderr_tail
        output: dict[str, Any] | None = None
        if status is None:
            if exit_code == 0:
                try:
                    raw = output_path.read_bytes()
                    if len(raw) > int(settings.recipe_execution_output_max_bytes):
                        status, error = "failed", "recipe_output_too_large"
                    else:
                        parsed = json.loads(raw.decode("utf-8"))
                        if isinstance(parsed, dict):
                            status, output = "succeeded", parsed
                        else:
                            status, error = "failed", "recipe_output_not_object"
                except (OSError, ValueError):
                    status, error = "failed", "recipe_output_unreadable"
            else:
                summary = stderr_tail.strip().splitlines()
                status = "failed"
                error = (
                    f"recipe_exit_{exit_code}: {summary[-1][:300]}"
                    if summary
                    else f"recipe_exit_{exit_code}"
                )
        return status, error, exit_code, stdout_tail, stderr_tail, output
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def resolve_env_for_spec(
    db: DBSession, *, workspace_id: str, spec: EnvSpec
) -> PythonEnv:
    return resolve_env(db, workspace_id=workspace_id, spec=spec)


__all__ = [
    "RECIPE_ENV_BUILD_TASK",
    "RECIPE_ENV_SWEEP_TASK",
    "RECIPE_EXECUTE_TASK",
    "SupervisedRun",
    "cancel_requested",
    "clamp_timeout",
    "create_execution",
    "dispatch_execution",
    "ensure_env_ready",
    "env_dir",
    "finalize_execution",
    "harness_path",
    "request_cancel",
    "resolve_env_for_spec",
    "run_recipe_execution",
    "serialize_execution",
    "supervise_harness",
    "validate_code",
]
