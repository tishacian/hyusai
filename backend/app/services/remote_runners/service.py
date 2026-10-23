"""Runners, their jobs and the tick that drives them.

Agentium polls the machine; the machine never calls back. A tick launches
queued jobs within each runner's concurrency, probes active ones, forwards
cancellations and deadlines as signals to the job's process group, and on
success reads ``result.json`` and copies the declared artifacts to the object
store. Every transition is a conditional update, so two overlapping ticks
cannot launch the same job twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.remote_runner import (
    JOB_ACTIVE_STATUSES,
    JOB_TERMINAL_STATUSES,
    RemoteRunner,
    RemoteRunnerJob,
)
from app.services.audit_logger import emit_audit_event
from app.services.remote_runners import catalog
from app.services.remote_runners.transport import (
    LocalTransport,
    Transport,
    TransportError,
    job_dir,
    relative_in,
)

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_LOG_TAIL_BYTES = 8192
_RESULT_MAX_BYTES = 1024 * 1024
_LAUNCH_ADOPT_AFTER = timedelta(minutes=10)
_UNREACHABLE_GRACE = timedelta(hours=1)


class RunnerError(ValueError):
    def __init__(self, code: str, status_code: int = 400, detail: str | None = None):
        self.code, self.status_code = code, status_code
        super().__init__(detail or code)


def utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

_RUNNER_FIELDS = {
    "slug",
    "name",
    "transport",
    "host",
    "port",
    "username",
    "host_key",
    "key_secret_ref",
    "bastion",
    "work_root",
    "allowed_commands",
    "labels",
    "max_concurrent_jobs",
    "enabled",
}


def _clean_runner(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    unknown = set(values) - _RUNNER_FIELDS
    if unknown:
        raise RunnerError("REMOTE_RUNNER_FIELD_UNKNOWN", detail=", ".join(sorted(unknown)))
    out = dict(values)
    if "slug" in out and not (isinstance(out["slug"], str) and _SLUG_RE.match(out["slug"])):
        raise RunnerError("REMOTE_RUNNER_SLUG_INVALID")
    if "transport" in out:
        if out["transport"] not in {"ssh", "local"}:
            raise RunnerError("REMOTE_RUNNER_TRANSPORT_INVALID")
        if out["transport"] == "local" and not settings.remote_runner_local_transport_enabled:
            raise RunnerError("REMOTE_RUNNER_LOCAL_DISABLED", 403)
    for key in ("name", "host", "username", "host_key", "key_secret_ref", "work_root"):
        if key in out and not (isinstance(out[key], str) and out[key].strip()):
            raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail=key)
    if "key_secret_ref" in out and not out["key_secret_ref"].startswith("secret://workspace/"):
        raise RunnerError("REMOTE_RUNNER_SECRET_REF_INVALID")
    if "work_root" in out:
        root = PurePosixPath(out["work_root"])
        if not root.is_absolute() or ".." in root.parts or str(root) == "/":
            raise RunnerError("REMOTE_RUNNER_WORK_ROOT_INVALID")
        out["work_root"] = str(root)
    if "port" in out and not (isinstance(out["port"], int) and 0 < out["port"] < 65536):
        raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail="port")
    if "max_concurrent_jobs" in out and not (
        isinstance(out["max_concurrent_jobs"], int) and 1 <= out["max_concurrent_jobs"] <= 64
    ):
        raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail="max_concurrent_jobs")
    if "allowed_commands" in out:
        commands = out["allowed_commands"]
        if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
            raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail="allowed_commands")
        for key in commands:
            try:
                catalog.get(key)
            except catalog.CatalogError as exc:
                raise RunnerError(exc.code, detail=key) from None
        out["allowed_commands"] = sorted(set(commands))
    if "labels" in out and not (
        isinstance(out["labels"], dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in out["labels"].items())
    ):
        raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail="labels")
    if "bastion" in out and out["bastion"] is not None:
        bastion = out["bastion"]
        if not isinstance(bastion, dict) or set(bastion) - {"host", "port", "username", "host_key"}:
            raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail="bastion")
        if not all(
            isinstance(bastion.get(k), str) and bastion[k] for k in ("host", "username", "host_key")
        ):
            raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail="bastion")
        port = bastion.get("port", 22)
        if not (isinstance(port, int) and 0 < port < 65536):
            raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail="bastion.port")
        out["bastion"] = {**bastion, "port": port}
    if "enabled" in out and not isinstance(out["enabled"], bool):
        raise RunnerError("REMOTE_RUNNER_FIELD_INVALID", detail="enabled")
    if not partial:
        missing = {
            "slug",
            "name",
            "host",
            "username",
            "host_key",
            "key_secret_ref",
            "work_root",
        } - set(out)
        if missing:
            raise RunnerError("REMOTE_RUNNER_FIELD_MISSING", detail=", ".join(sorted(missing)))
    return out


def create_runner(
    db: Session, *, workspace_id: str, user_id: str | None, values: dict
) -> RemoteRunner:
    clean = _clean_runner(values, partial=False)
    if db.query(RemoteRunner.id).filter_by(workspace_id=workspace_id, slug=clean["slug"]).first():
        raise RunnerError("REMOTE_RUNNER_SLUG_TAKEN", 409)
    now = utcnow()
    row = RemoteRunner(
        workspace_id=workspace_id,
        transport=clean.pop("transport", "ssh"),
        port=clean.pop("port", 22),
        allowed_commands=clean.pop("allowed_commands", []),
        labels=clean.pop("labels", {}),
        max_concurrent_jobs=clean.pop("max_concurrent_jobs", 1),
        enabled=clean.pop("enabled", True),
        created_by=user_id,
        created_at=now,
        updated_at=now,
        **clean,
    )
    db.add(row)
    db.flush()
    _audit(
        db, workspace_id, "remote_runner.created", user_id, {"runner_id": row.id, "slug": row.slug}
    )
    return row


def update_runner(
    db: Session, runner: RemoteRunner, *, user_id: str | None, values: dict
) -> RemoteRunner:
    clean = _clean_runner(values, partial=True)
    if "slug" in clean and clean["slug"] != runner.slug:
        raise RunnerError("REMOTE_RUNNER_SLUG_IMMUTABLE")
    for key, value in clean.items():
        setattr(runner, key, value)
    runner.updated_at = utcnow()
    db.flush()
    _audit(
        db,
        runner.workspace_id,
        "remote_runner.updated",
        user_id,
        {"runner_id": runner.id, "fields": sorted(clean)},
    )
    return runner


def get_runner(db: Session, workspace_id: str, runner_id: str) -> RemoteRunner:
    row = db.query(RemoteRunner).filter_by(id=runner_id, workspace_id=workspace_id).first()
    if row is None:
        raise RunnerError("REMOTE_RUNNER_NOT_FOUND", 404)
    return row


def runner_view(row: RemoteRunner) -> dict:
    return {
        "id": row.id,
        "slug": row.slug,
        "name": row.name,
        "transport": row.transport,
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "host_key": row.host_key,
        "key_secret_ref": row.key_secret_ref,
        "bastion": row.bastion,
        "work_root": row.work_root,
        "allowed_commands": list(row.allowed_commands or []),
        "labels": dict(row.labels or {}),
        "max_concurrent_jobs": row.max_concurrent_jobs,
        "enabled": row.enabled,
        "last_probe": row.last_probe,
        "last_probe_at": row.last_probe_at.isoformat() if row.last_probe_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def open_transport(db: Session, runner: RemoteRunner) -> Transport:
    if runner.transport == "local":
        if not settings.remote_runner_local_transport_enabled:
            raise RunnerError("REMOTE_RUNNER_LOCAL_DISABLED", 403)
        return LocalTransport(runner.work_root)
    from app.services.remote_runners.ssh import Endpoint, SshTransport
    from app.services.secrets import registry
    from app.services.secrets.registry import SecretConsumer
    from app.services.secrets.values import SecretRegistryError

    try:
        key = registry.resolve(
            db,
            runner.key_secret_ref,
            consumer=SecretConsumer(
                kind="remote_runner", id=runner.id, workspace_id=runner.workspace_id
            ),
        )
    except SecretRegistryError as exc:
        raise RunnerError("REMOTE_RUNNER_SECRET_UNAVAILABLE", 409, detail=exc.code) from None
    bastion = None
    if runner.bastion:
        bastion = Endpoint(
            runner.bastion["host"],
            int(runner.bastion.get("port", 22)),
            runner.bastion["username"],
            runner.bastion["host_key"],
        )
    return SshTransport(
        Endpoint(runner.host, runner.port, runner.username, runner.host_key),
        key.reveal(),
        bastion=bastion,
        connect_timeout=settings.remote_runner_connect_timeout_s,
    )


def probe_runner(db: Session, runner: RemoteRunner, *, user_id: str | None = None) -> dict:
    """Run the read-only probe now and keep its answer on the runner."""

    _, _, argv = catalog.validate(catalog.PROBE.key, {})

    async def go():
        transport = open_transport(db, runner)
        try:
            return await transport.run(argv, timeout=catalog.PROBE.timeout_s)
        finally:
            await transport.close()

    checked_at = utcnow()
    try:
        result = asyncio.run(go())
        probe = {"reachable": result.exit_status == 0, **catalog.parse_probe(result.stdout)}
        if result.exit_status != 0:
            probe["error_code"] = "REMOTE_RUNNER_PROBE_FAILED"
    except TransportError as exc:
        probe = {"reachable": False, "error_code": exc.code}
    runner.last_probe, runner.last_probe_at = probe, checked_at
    db.flush()
    _audit(
        db,
        runner.workspace_id,
        "remote_runner.probed",
        user_id,
        {"runner_id": runner.id, "reachable": probe["reachable"]},
    )
    return probe


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def submit_job(
    db: Session,
    *,
    workspace_id: str,
    runner_id: str,
    command: str,
    params: dict | None = None,
    user_id: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
    timeout_s: int | None = None,
    correlation_key: str | None = None,
    notify_system_id: str | None = None,
    input_file_ids: list[str] | None = None,
) -> RemoteRunnerJob:
    if correlation_key is not None and not (
        isinstance(correlation_key, str) and 0 < len(correlation_key) <= 200
    ):
        raise RunnerError("REMOTE_JOB_CORRELATION_INVALID")
    if timeout_s is not None and (isinstance(timeout_s, bool) or not isinstance(timeout_s, int)):
        raise RunnerError("REMOTE_JOB_TIMEOUT_INVALID")
    if notify_system_id is not None:
        from app.models.system import System

        if (
            not db.query(System.id)
            .filter_by(id=notify_system_id, workspace_id=workspace_id)
            .first()
        ):
            raise RunnerError("REMOTE_JOB_NOTIFY_SYSTEM_NOT_FOUND", 404)
    runner = get_runner(db, workspace_id, runner_id)
    if not runner.enabled:
        raise RunnerError("REMOTE_RUNNER_DISABLED", 409)
    if command not in (runner.allowed_commands or []):
        raise RunnerError("REMOTE_COMMAND_NOT_ALLOWED", 403, detail=command)
    try:
        spec, model, _argv = catalog.validate(command, params)
    except catalog.CatalogError as exc:
        raise RunnerError(exc.code, detail=str(exc)) from None
    if spec.mode != "detached":
        raise RunnerError("REMOTE_COMMAND_NOT_DETACHED", detail=command)
    ceiling = int(settings.remote_runner_max_job_hours * 3600)
    seconds = min(int(timeout_s or spec.timeout_s), spec.timeout_s, ceiling)
    if seconds <= 0:
        raise RunnerError("REMOTE_JOB_TIMEOUT_INVALID")
    now = utcnow()
    job = RemoteRunnerJob(
        workspace_id=workspace_id,
        runner_id=runner.id,
        command=command,
        params=model.model_dump(mode="json"),
        run_id=run_id,
        node_id=node_id,
        correlation_key=correlation_key,
        notify_system_id=notify_system_id,
        status="queued",
        artifacts=[],
        inputs=[],
        cancel_requested=False,
        created_by=user_id,
        created_at=now,
        deadline_at=now + timedelta(seconds=seconds),
    )
    db.add(job)
    db.flush()
    job.remote_dir = job_dir(runner.work_root, job.id)
    job.inputs = _stage_inputs(db, job, input_file_ids or [])
    db.flush()
    _audit(
        db,
        workspace_id,
        "remote_runner.job_submitted",
        user_id,
        {"job_id": job.id, "runner_id": runner.id, "command": command, "run_id": run_id},
    )
    return job


_INPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")


def _stage_inputs(db: Session, job: RemoteRunnerJob, file_ids: list[str]) -> list[dict]:
    """Snapshot deposit files of the job's workspace into the object store.

    The bytes a job will receive are fixed at submission: a later change to the
    deposit cannot alter what the machine processes. Each file lands in the job
    directory under ``inputs/<filename>``.
    """

    if not file_ids:
        return []
    if (
        not isinstance(file_ids, list)
        or len(file_ids) > 50
        or not all(isinstance(item, str) and item for item in file_ids)
    ):
        raise RunnerError("REMOTE_JOB_INPUTS_INVALID")
    from app.models.secure_deposit import DepositFile
    from app.services.collection_source_backing import SourceBackingError, read_backing_source_bytes
    from app.services.object_store import get_object_store

    store = get_object_store()
    limit = settings.remote_runner_artifact_max_mb * 1024 * 1024
    staged, names = [], set()
    for file_id in file_ids:
        row = db.query(DepositFile).filter_by(id=file_id, workspace_id=job.workspace_id).first()
        if row is None:
            raise RunnerError("REMOTE_JOB_INPUT_NOT_FOUND", 404, detail=file_id)
        name = str(row.filename or "").rsplit("/", 1)[-1]
        if not _INPUT_NAME_RE.match(name) or name in names:
            raise RunnerError("REMOTE_JOB_INPUT_NAME_INVALID", detail=name)
        names.add(name)
        try:
            data = read_backing_source_bytes(
                db,
                workspace_id=job.workspace_id,
                locator={"kind": "secure_deposit_file", "deposit_file_id": row.id},
            )
        except SourceBackingError as exc:
            raise RunnerError("REMOTE_JOB_INPUT_UNREADABLE", 409, detail=str(exc)) from None
        if len(data) > limit:
            raise RunnerError("REMOTE_JOB_INPUT_TOO_LARGE", detail=name)
        key = store.key("remote-runners", job.workspace_id, job.id, "inputs", name)
        store.write_bytes(key, data)
        staged.append(
            {
                "path": f"inputs/{name}",
                "key": key,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "deposit_file_id": row.id,
            }
        )
    return staged


async def _upload_inputs(transport: Transport, job: RemoteRunnerJob) -> None:
    if not job.inputs:
        return
    from app.services.object_store import get_object_store

    store = get_object_store()
    with tempfile.TemporaryDirectory(prefix="remote-runner-in-") as scratch:
        for index, item in enumerate(job.inputs):
            local = Path(scratch) / f"input-{index}"
            local.write_bytes(store.read_bytes(item["key"]))
            if hashlib.sha256(local.read_bytes()).hexdigest() != item["sha256"]:
                raise RunnerError("REMOTE_JOB_INPUT_CHANGED", detail=item["path"])
            await transport.put(local, relative_in(job.remote_dir, item["path"]))


def get_job(db: Session, workspace_id: str, job_id: str) -> RemoteRunnerJob:
    row = db.query(RemoteRunnerJob).filter_by(id=job_id, workspace_id=workspace_id).first()
    if row is None:
        raise RunnerError("REMOTE_JOB_NOT_FOUND", 404)
    return row


def cancel_job(db: Session, job: RemoteRunnerJob, *, user_id: str | None = None) -> RemoteRunnerJob:
    if job.status in JOB_TERMINAL_STATUSES:
        return job
    job.cancel_requested = True
    if job.status == "queued":
        _finish(job, "cancelled", "REMOTE_JOB_CANCELLED", utcnow())
    db.flush()
    _audit(db, job.workspace_id, "remote_runner.job_cancel_requested", user_id, {"job_id": job.id})
    return job


def job_view(row: RemoteRunnerJob) -> dict:
    iso = lambda value: value.isoformat() if value else None  # noqa: E731
    return {
        "id": row.id,
        "runner_id": row.runner_id,
        "command": row.command,
        "params": row.params,
        "run_id": row.run_id,
        "node_id": row.node_id,
        "correlation_key": row.correlation_key,
        "notify_system_id": row.notify_system_id,
        "status": row.status,
        "exit_code": row.exit_code,
        "result": row.result,
        "inputs": list(row.inputs or []),
        "artifacts": list(row.artifacts or []),
        "log_tail": row.log_tail,
        "error_code": row.error_code,
        "error_detail": row.error_detail,
        "cancel_requested": row.cancel_requested,
        "created_at": iso(row.created_at),
        "deadline_at": iso(row.deadline_at),
        "launched_at": iso(row.launched_at),
        "last_seen_at": iso(row.last_seen_at),
        "finished_at": iso(row.finished_at),
    }


def read_job_log(
    db: Session, job: RemoteRunnerJob, *, stream: str = "stderr", max_bytes: int = 65536
) -> str | None:
    if stream not in {"stdout", "stderr"}:
        raise RunnerError("REMOTE_JOB_LOG_STREAM_INVALID")
    if job.status in JOB_TERMINAL_STATUSES and job.status != "succeeded" and not job.launched_at:
        return None
    runner = db.get(RemoteRunner, job.runner_id)

    async def go():
        transport = open_transport(db, runner)
        try:
            return await transport.read_tail(
                relative_in(job.remote_dir, f"{stream}.log"), min(max_bytes, 1024 * 1024)
            )
        finally:
            await transport.close()

    try:
        return asyncio.run(go())
    except TransportError as exc:
        raise RunnerError(exc.code, 502) from None


def _finish(
    job: RemoteRunnerJob,
    status: str,
    error_code: str | None,
    now: datetime,
    detail: str | None = None,
) -> None:
    job.status = status
    job.error_code = error_code
    job.error_detail = detail[-2000:] if detail else None
    job.finished_at = now


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Advance every runner that has queued or active jobs. Returns counters."""

    now = now or utcnow()
    counters = {"launched": 0, "finished": 0, "signalled": 0, "errors": 0}
    runner_ids = [
        rid
        for (rid,) in db.query(RemoteRunnerJob.runner_id)
        .filter(RemoteRunnerJob.status.notin_(JOB_TERMINAL_STATUSES))
        .distinct()
        .all()
    ]
    for runner_id in runner_ids:
        runner = db.get(RemoteRunner, runner_id)
        if runner is None:
            continue
        try:
            asyncio.run(_tick_runner(db, runner, now, counters))
        except Exception:  # noqa: BLE001 - one runner never stops the others
            db.rollback()
            counters["errors"] += 1
            logger.exception("remote_runner.tick_failed", extra={"runner_id": runner_id})
    counters["announced"] = announce_finished(db)
    return counters


def finished_event_payload(job: RemoteRunnerJob) -> dict:
    payload = {
        "job_id": job.id,
        "runner_id": job.runner_id,
        "command": job.command,
        "status": job.status,
        "exit_code": job.exit_code,
        "error_code": job.error_code,
        "result": job.result,
        "artifacts": list(job.artifacts or []),
        "origin_run_id": job.run_id,
        "origin_node_id": job.node_id,
    }
    if job.correlation_key:
        payload["correlation_key"] = job.correlation_key
    return payload


def announce_finished(db: Session, *, limit: int = 100) -> int:
    """Hand each terminal job once to the trigger registry (``remote_runner.job_finished``).

    The stamp is written after the hand-off: a crash in between re-announces the
    job, and the registry's delivery dedup absorbs the repeat.
    """

    from app.services.run_engine.triggers import EVENT_REMOTE_JOB_FINISHED, emit_event

    jobs = (
        db.query(RemoteRunnerJob)
        .filter(
            RemoteRunnerJob.status.in_(JOB_TERMINAL_STATUSES),
            RemoteRunnerJob.event_emitted_at.is_(None),
        )
        .order_by(RemoteRunnerJob.finished_at)
        .limit(limit)
        .all()
    )
    announced = 0
    for job in jobs:
        try:
            emit_event(
                EVENT_REMOTE_JOB_FINISHED,
                job.workspace_id,
                finished_event_payload(job),
                system_id=job.notify_system_id,
            )
        except Exception:  # noqa: BLE001 - retried on the next tick
            logger.exception("remote_runner.announce_failed", extra={"job_id": job.id})
            continue
        job.event_emitted_at = utcnow()
        db.commit()
        announced += 1
    return announced


async def _tick_runner(db: Session, runner: RemoteRunner, now: datetime, counters: dict) -> None:
    jobs = (
        db.query(RemoteRunnerJob)
        .filter(
            RemoteRunnerJob.runner_id == runner.id,
            RemoteRunnerJob.status.notin_(JOB_TERMINAL_STATUSES),
        )
        .order_by(RemoteRunnerJob.created_at)
        .all()
    )
    # Settle what needs no machine first: queued jobs cancelled or expired.
    for job in jobs:
        if job.status == "queued" and (job.cancel_requested or job.deadline_at <= now):
            _finish(
                job,
                "cancelled" if job.cancel_requested else "timed_out",
                "REMOTE_JOB_CANCELLED" if job.cancel_requested else "REMOTE_JOB_QUEUE_TIMEOUT",
                now,
            )
            counters["finished"] += 1
    db.commit()
    jobs = [job for job in jobs if job.status not in JOB_TERMINAL_STATUSES]
    if not jobs:
        return
    try:
        transport = open_transport(db, runner)
    except RunnerError as exc:
        _mark_unreachable(db, jobs, now, exc.code, counters)
        return
    try:
        for job in [j for j in jobs if j.status in JOB_ACTIVE_STATUSES]:
            await _advance_active(db, runner, transport, job, now, counters)
        active = sum(1 for j in jobs if j.status in JOB_ACTIVE_STATUSES)
        if runner.enabled:
            for job in [j for j in jobs if j.status == "queued"]:
                if active >= runner.max_concurrent_jobs:
                    break
                if await _launch(db, transport, job, now):
                    counters["launched"] += 1
                    active += 1
    except TransportError as exc:
        db.rollback()
        _mark_unreachable(db, jobs, now, exc.code, counters)
    finally:
        await transport.close()


def _mark_unreachable(
    db: Session, jobs: list[RemoteRunnerJob], now: datetime, code: str, counters: dict
) -> None:
    """A machine we cannot reach keeps its jobs until well past their deadline."""

    for job in jobs:
        if job.status in JOB_ACTIVE_STATUSES and job.deadline_at + _UNREACHABLE_GRACE <= now:
            _finish(job, "lost", code, now, "runner unreachable past the job deadline")
            counters["finished"] += 1
    counters["errors"] += 1
    db.commit()


async def _launch(db: Session, transport: Transport, job: RemoteRunnerJob, now: datetime) -> bool:
    claimed = (
        db.query(RemoteRunnerJob)
        .filter_by(id=job.id, status="queued", cancel_requested=False)
        .update({"status": "launching", "launched_at": now}, synchronize_session=False)
    )
    db.commit()
    db.refresh(job)
    if claimed != 1:
        return False
    try:
        _spec, _model, argv = catalog.validate(job.command, job.params)
        await _upload_inputs(transport, job)
        pid = await transport.start(job.remote_dir, argv)
    except RunnerError as exc:
        _finish(job, "failed", exc.code, utcnow(), str(exc))
        db.commit()
        return False
    except catalog.CatalogError as exc:
        _finish(job, "failed", exc.code, utcnow(), str(exc))
        db.commit()
        return False
    except TransportError as exc:
        # The directory may exist without a process: never relaunch blindly.
        _finish(job, "failed", exc.code, utcnow(), str(exc))
        db.commit()
        return False
    job.pid, job.status, job.last_seen_at = pid, "running", utcnow()
    db.commit()
    return True


async def _advance_active(
    db: Session,
    runner: RemoteRunner,
    transport: Transport,
    job: RemoteRunnerJob,
    now: datetime,
    counters: dict,
) -> None:
    if job.pid is None:
        # Crashed between the claim and the pid: adopt the pid file or give up.
        text = await transport.read_tail(relative_in(job.remote_dir, "pid"), 64)
        if text and text.strip().isdigit():
            job.pid, job.status = int(text.strip()), "running"
            db.commit()
        elif job.launched_at and job.launched_at + _LAUNCH_ADOPT_AFTER <= now:
            _finish(job, "lost", "REMOTE_JOB_LAUNCH_UNKNOWN", now)
            counters["finished"] += 1
            db.commit()
            return
        else:
            return
    probe = await transport.status(job.remote_dir, job.pid)
    job.last_seen_at = now
    if probe.state == "exited":
        await _settle_exit(db, transport, job, probe.exit_code, now)
        counters["finished"] += 1
        return
    if probe.state == "gone":
        if job.status == "cancelling":
            timed_out = job.error_code == "REMOTE_JOB_TIMEOUT"
            _finish(
                job,
                "timed_out" if timed_out else "cancelled",
                "REMOTE_JOB_TIMEOUT" if timed_out else "REMOTE_JOB_CANCELLED",
                now,
            )
        else:
            _finish(
                job,
                "lost",
                "REMOTE_JOB_PROCESS_GONE",
                now,
                await transport.read_tail(
                    relative_in(job.remote_dir, "stderr.log"), _LOG_TAIL_BYTES
                ),
            )
        counters["finished"] += 1
        db.commit()
        return
    # Still running.
    if job.status == "cancelling":
        grace = timedelta(seconds=settings.remote_runner_cancel_grace_s)
        if job.cancel_sent_at and job.cancel_sent_at + grace <= now:
            await transport.signal(job.pid, "KILL")
            counters["signalled"] += 1
    elif job.cancel_requested or job.deadline_at <= now:
        await transport.signal(job.pid, "TERM")
        job.status, job.cancel_sent_at = "cancelling", now
        if not job.cancel_requested:
            job.error_code = "REMOTE_JOB_TIMEOUT"
        counters["signalled"] += 1
    db.commit()


async def _settle_exit(
    db: Session, transport: Transport, job: RemoteRunnerJob, exit_code: int | None, now: datetime
) -> None:
    job.exit_code = exit_code
    stderr = await transport.read_tail(relative_in(job.remote_dir, "stderr.log"), _LOG_TAIL_BYTES)
    stdout = await transport.read_tail(relative_in(job.remote_dir, "stdout.log"), _LOG_TAIL_BYTES)
    job.log_tail = "\n".join(part for part in (stdout, stderr) if part)[-_LOG_TAIL_BYTES:] or None
    if exit_code != 0:
        _finish(job, "failed", "REMOTE_JOB_EXIT_NONZERO", now, stderr)
        db.commit()
        return
    try:
        job.result = await _read_result(transport, job)
        job.artifacts = await _collect_artifacts(transport, job)
    except (TransportError, RunnerError) as exc:
        _finish(job, "failed", getattr(exc, "code", "REMOTE_JOB_COLLECT_FAILED"), now, str(exc))
        db.commit()
        return
    _finish(job, "succeeded", None, now)
    db.commit()


async def _read_result(transport: Transport, job: RemoteRunnerJob) -> dict | None:
    text = await transport.read_tail(
        relative_in(job.remote_dir, "result.json"), _RESULT_MAX_BYTES + 1
    )
    if text is None:
        return None
    if len(text.encode()) > _RESULT_MAX_BYTES:
        raise RunnerError("REMOTE_JOB_RESULT_TOO_LARGE")
    try:
        value = json.loads(text)
    except ValueError:
        raise RunnerError("REMOTE_JOB_RESULT_INVALID") from None
    if not isinstance(value, dict):
        raise RunnerError("REMOTE_JOB_RESULT_INVALID")
    return value


async def _collect_artifacts(transport: Transport, job: RemoteRunnerJob) -> list[dict]:
    from app.services.object_store import get_object_store

    spec = catalog.get(job.command)
    if not spec.artifacts:
        return []
    store = get_object_store()
    limit = settings.remote_runner_artifact_max_mb * 1024 * 1024
    collected = []
    with tempfile.TemporaryDirectory(prefix="remote-runner-") as scratch:
        for index, relative in enumerate(spec.artifacts):
            local = Path(scratch) / f"artifact-{index}"
            size = await transport.fetch(relative_in(job.remote_dir, relative), local, limit)
            if size is None:
                collected.append({"path": relative, "present": False})
                continue
            digest = hashlib.sha256(local.read_bytes()).hexdigest()
            key = store.key("remote-runners", job.workspace_id, job.id, relative)
            store.write_file(key, local)
            collected.append(
                {"path": relative, "present": True, "key": key, "size": size, "sha256": digest}
            )
    return collected


def _audit(db: Session, workspace_id: str, event: str, actor: str | None, details: dict) -> None:
    emit_audit_event(
        workspace_id=workspace_id, event_type=event, actor=actor or "system", details=details, db=db
    )
