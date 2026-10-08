"""Durable, opt-in challenger scoring. No shadow result is ever served.

The serving transaction saves a small intention beside its journal row. Beat
dispatches identifier-only messages; a compare-and-swap lease makes redelivery
safe. Both object-store I/O and native prediction run in a killable process.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, text

from app.core.config import settings
from app.core.logging import get_logger
from app.models.tabular import MLModel, MLPrediction
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.mlops_jobs import operational_job_id
from app.services.tabular_datasets import TabularError

logger = get_logger(__name__)
KIND = "ml_shadow"
MAX_ROWS = 64
MAX_PENDING = 100
MAX_ATTEMPTS = 2
LEASE_SECONDS = 90
WINDOW_LIMIT = 400
MAX_PAYLOAD_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024


class ShadowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    sample_percent: int = Field(default=10, ge=1, le=100)
    timeout_s: int = Field(default=15, ge=1, le=60)


def configuration(model):
    try:
        return ShadowConfig.model_validate(((model.params_json or {}).get("mlops") or {}).get("shadow") or {})
    except (TypeError, ValueError):
        return ShadowConfig()  # malformed legacy metadata never enables work


def supported(model):
    return (model.family or "tabular") == "tabular" and model.task in {"classification", "regression"}


def configure(db, *, model, config: ShadowConfig):
    model = db.query(MLModel).filter_by(id=model.id, workspace_id=model.workspace_id).populate_existing().with_for_update().one()
    if config.enabled and (not supported(model) or model.status != "ready"):
        raise TabularError(code="ML_SHADOW_UNSUPPORTED", message="Shadow scoring requires a ready tabular model.", status_code=409)
    params = dict(model.params_json or {})
    params["mlops"] = {**(params.get("mlops") or {}), "shadow": config.model_dump()}
    model.params_json = params
    db.commit()
    return model


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _snapshot(model):
    return {"id": model.id, "workspace_id": model.workspace_id, "slug": model.slug,
            "version": model.version, "task": model.task, "target": model.target,
            "family": model.family or "tabular", "model_uri": model.model_uri,
            "trained_at": model.trained_at.isoformat() if model.trained_at else None,
            "signature_json": model.signature_json or {}, "classes_json": model.classes_json or [],
            "metrics_json": {"target": (model.metrics_json or {}).get("target") or {}}}


def _identity(model):
    return hashlib.sha256(_json(_snapshot(model)).encode()).hexdigest()


def _skip(row, reason):
    previous = (row.scores_json or {}).get("shadow") or {}
    row.scores_json = {**(row.scores_json or {}), "shadow": {**previous, "status": "skipped", "error": reason}}


def stage(db, *, row: MLPrediction, served: MLModel):
    """Called inside a savepoint of the PRIMARY journal transaction; never commits."""
    config = configuration(served)
    if not config.enabled or not supported(served):
        return
    # Stable sampling survives a broker retry or worker redelivery.
    if int(hashlib.sha256(row.id.encode()).hexdigest()[:8], 16) % 100 >= config.sample_percent:
        return
    from app.services.tabular_ml import runner_up

    challenger = runner_up(db, served)
    if challenger is None or challenger.id == served.id:
        _skip(row, "ML_SHADOW_NO_CHALLENGER")
        return
    row.scores_json = {**(row.scores_json or {}), "shadow": {
        "challenger_id": challenger.id, "challenger_version": challenger.version}}
    names = {str(field.get("name")) for field in (served.signature_json or {}).get("inputs", [])}
    required = {str(field.get("name")) for field in (challenger.signature_json or {}).get("inputs", [])}
    if (not supported(challenger) or challenger.task != served.task or challenger.target != served.target
            or not required or not required.issubset(names)
            or (served.task == "classification" and set(map(str, challenger.classes_json or [])) != set(map(str, served.classes_json or [])))):
        _skip(row, "ML_SHADOW_INCOMPATIBLE")
        return
    if (challenger.artifact_bytes or 0) > MAX_ARTIFACT_BYTES:
        _skip(row, "ML_SHADOW_ARTIFACT_TOO_LARGE")
        return
    if len(_json(row.payload_json).encode()) > MAX_PAYLOAD_BYTES:
        _skip(row, "ML_SHADOW_PAYLOAD_TOO_LARGE")
        return
    # Short transaction lock serializes the workspace quota, never a provider
    # call. Nonblocking acquisition preserves primary latency under contention.
    if db.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(("ml-shadow:" + row.workspace_id).encode()).digest()[:8], "big", signed=True)
        if not db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}).scalar():
            _skip(row, "ML_SHADOW_BUSY")
            return
    count = db.query(WorkspaceJob.id).filter(WorkspaceJob.workspace_id == row.workspace_id,
        WorkspaceJob.kind == KIND, WorkspaceJob.status.in_(("queued", "running"))).limit(MAX_PENDING).count()
    if count >= MAX_PENDING:
        _skip(row, "ML_SHADOW_BACKLOG_FULL")
        return
    job_id = operational_job_id(KIND, row.workspace_id, row.id)
    job = WorkspaceJob(id=job_id, workspace_id=row.workspace_id, kind=KIND, title="Challenger shadow scoring",
        status="queued", stage="queued", queued_at=datetime.utcnow(),
        input_ref={"prediction_id": row.id, "served_id": served.id, "served_version": served.version,
                   "served_identity": _identity(served), "challenger_id": challenger.id,
                   "challenger_version": challenger.version, "challenger_identity": _identity(challenger),
                   "config": config.model_dump(), "rows": min(MAX_ROWS, len(row.payload_json or []))},
        result={"attempts": 0})
    db.add(job)
    db.flush()
    row.scores_json = {**(row.scores_json or {}), "shadow": {"status": "queued", "job_id": job_id}}


def _claim(db, job_id, now):
    job = db.query(WorkspaceJob).filter_by(id=job_id, kind=KIND).first()
    if job is None or job.status not in {"queued", "running"}:
        return None
    if job.status == "running" and job.updated_at > now - timedelta(seconds=LEASE_SECONDS):
        return None
    attempts = int((job.result or {}).get("attempts", 0))
    token = uuid4().hex
    if attempts >= MAX_ATTEMPTS:
        values = {"status": "failed", "stage": "failed", "error": "ML_SHADOW_RETRY_LIMIT", "completed_at": now, "updated_at": now}
    else:
        values = {"status": "running", "stage": "scoring", "started_at": now, "updated_at": now,
                  "error": None, "result": {"attempts": attempts + 1, "lease_token": token}}
    changed = db.query(WorkspaceJob).filter_by(id=job.id, status=job.status, updated_at=job.updated_at).update(values, synchronize_session=False)
    db.commit()
    if not changed or attempts >= MAX_ATTEMPTS:
        return None
    db.refresh(job)
    return job, token


def _references(db, job):
    data = job.input_ref
    workspace = db.get(Workspace, job.workspace_id, populate_existing=True)
    row = db.query(MLPrediction).filter_by(id=data["prediction_id"], workspace_id=job.workspace_id).populate_existing().first()
    models = {item.id: item for item in db.query(MLModel).filter(MLModel.workspace_id == job.workspace_id,
        MLModel.id.in_([data["served_id"], data["challenger_id"]])).populate_existing().all()}
    served, challenger = models.get(data["served_id"]), models.get(data["challenger_id"])
    if workspace is None or not workspace.is_active or row is None or served is None or challenger is None:
        raise TabularError(code="ML_SHADOW_SOURCE_UNAVAILABLE", message="The shadow source is no longer available.")
    if row.served_id != served.id or row.served_version != data["served_version"] or row.slug != challenger.slug:
        raise TabularError(code="ML_SHADOW_SOURCE_CHANGED", message="The shadow source identity changed.")
    if served.status != "ready" or challenger.status != "ready" or _identity(served) != data["served_identity"] or _identity(challenger) != data["challenger_identity"]:
        raise TabularError(code="ML_SHADOW_MODEL_CHANGED", message="A pinned model changed.")
    if not configuration(served).enabled:
        raise TabularError(code="ML_SHADOW_DISABLED", message="Shadow scoring was disabled.")
    return row, challenger


def _score_isolated(model, rows, *, timeout_s):
    """The child gets artifact-store access but no DB or provider credentials."""
    from app.services.recipe_executions import supervise_harness

    backend = Path(__file__).resolve().parents[2]
    harness = backend / "app" / "resources" / "ml_shadow_harness.py"
    with tempfile.TemporaryDirectory(prefix="ml-shadow-") as directory:
        scratch = Path(directory)
        manifest, output = scratch / "input.json", scratch / "result.json"
        manifest.write_text(_json({"model": _snapshot(model), "rows": rows, "max_artifact_bytes": MAX_ARTIFACT_BYTES,
                                  "parent_pid": os.getpid()}), encoding="utf-8")
        env = {"PYTHONPATH": str(backend), "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
               "ML_PREDICT_MAX_ROWS": str(MAX_ROWS), "ML_PREDICT_ENABLED": "true"}
        for key in ("object_store_backend", "object_store_s3_bucket", "object_store_s3_endpoint_url",
                    "object_store_s3_access_key", "object_store_s3_secret_key"):
            value = getattr(settings, key)
            if value is not None:
                env[key.upper()] = str(value)
        env["OBJECT_STORE_BASE_PATH"] = str(Path(settings.object_store_base_path).resolve())
        outcome = supervise_harness([sys.executable, str(harness), str(manifest), str(output)],
            venv_python=Path(sys.executable), scratch=scratch, timeout_s=timeout_s,
            memory_limit_mb=4096, cpu_limit_s=timeout_s + 5, fsize_limit_mb=256,
            extra_env=env, timeout_error="ML_SHADOW_TIMEOUT")
        if outcome.status == "timed_out":
            raise TabularError(code="ML_SHADOW_TIMEOUT", message="Shadow scoring exceeded its time budget.")
        if outcome.exit_code != 0 or not output.exists() or output.stat().st_size > 2 * 1024 * 1024:
            raise TabularError(code="ML_SHADOW_FAILED", message="The challenger could not score this sample.")
        value = json.loads(output.read_text(encoding="utf-8"))
        answers = value.get("predictions")
        if not isinstance(answers, list) or len(answers) != len(rows):
            raise TabularError(code="ML_SHADOW_INVALID_OUTPUT", message="The challenger returned an invalid sample.")
        _json(value)  # disallow nonfinite telemetry
        return value


def run_shadow(job_id: str):
    from app.db.base import SessionLocal

    with SessionLocal() as db:
        claim = _claim(db, job_id, datetime.utcnow())
        if claim is None:
            return {"status": "not_claimed"}
        job, token = claim
        started = time.monotonic()
        status, error, result = "completed", None, {}
        try:
            row, challenger = _references(db, job)
            rows = list(row.payload_json or [])[:MAX_ROWS]
            if not rows:
                raise TabularError(code="ML_SHADOW_SOURCE_UNAVAILABLE", message="No retained input rows.")
            config = ShadowConfig.model_validate(job.input_ref["config"])
            result = _score_isolated(challenger, rows, timeout_s=config.timeout_s)
            _references(db, job)  # do not publish stale/deleted workspace data
        except Exception as exc:
            error = exc.code if isinstance(exc, TabularError) else "ML_SHADOW_FAILED"
            status = "cancelled" if error in {"ML_SHADOW_DISABLED", "ML_SHADOW_SOURCE_UNAVAILABLE", "ML_SHADOW_MODEL_CHANGED"} else "failed"
        now = datetime.utcnow()
        # A dead/reclaimed producer cannot overwrite the new owner's answer.
        result = {**result, "attempts": job.result["attempts"], "lease_token": token,
                  "total_duration_ms": round((time.monotonic() - started) * 1000, 2)}
        changed = db.query(WorkspaceJob).filter_by(id=job.id, status="running", updated_at=job.updated_at).update(
            {"status": status, "stage": status, "progress": 100 if status == "completed" else 0,
             "result": result, "error": error, "completed_at": now, "updated_at": now}, synchronize_session=False)
        db.commit()
        return {"status": status if changed else "lease_lost", "job_id": job_id, "error": error}


def _dispatch(job_id):
    from app.workers.celery_app import celery_app

    celery_app.send_task("agentium.ml_shadow", args=[job_id],
        queue=settings.celery_ml_tabular_queue or settings.celery_task_default_queue, retry=False)


def recover(*, limit=50):
    """Bounded beat sweep; an unacknowledged publish never loses the intention."""
    from app.db.base import SessionLocal

    now = datetime.utcnow()
    dispatched, failed = 0, 0
    with SessionLocal() as db:
        jobs = db.query(WorkspaceJob).filter(WorkspaceJob.kind == KIND,
            or_((WorkspaceJob.status == "queued") & (WorkspaceJob.updated_at <= now - timedelta(seconds=30)),
                (WorkspaceJob.status == "running") & (WorkspaceJob.updated_at <= now - timedelta(seconds=LEASE_SECONDS))))
        for job in jobs.order_by(WorkspaceJob.updated_at, WorkspaceJob.id).limit(max(1, min(limit, 100))).all():
            if int((job.result or {}).get("attempts", 0)) >= MAX_ATTEMPTS:
                _claim(db, job.id, now)
                continue
            try:
                _dispatch(job.id)
                dispatched += 1
                # Only queued rows get a dispatch timestamp; a running row's
                # timestamp is its execution lease, never a broker lease.
                if job.status == "queued":
                    db.query(WorkspaceJob).filter_by(id=job.id, status="queued", updated_at=job.updated_at).update(
                        {"updated_at": now}, synchronize_session=False)
                    db.commit()
            except Exception:
                db.rollback()
                failed += 1
                logger.warning("ml_shadow: dispatch deferred", job_id=job.id)
    return {"dispatched": dispatched, "deferred": failed}


def _mean(values):
    return round(sum(values) / len(values), 6) if values else None


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def summary(db, *, model):
    from app.services.tabular_ml import runner_up

    contender = runner_up(db, model) if supported(model) else None
    if contender is not None and contender.id == model.id:
        contender = None
    rows = db.query(MLPrediction).filter_by(workspace_id=model.workspace_id, served_id=model.id).order_by(
        MLPrediction.created_at.desc(), MLPrediction.id.desc()).limit(WINDOW_LIMIT).all()
    by_id = {row.id: row for row in rows}
    ids = [operational_job_id(KIND, model.workspace_id, row.id) for row in rows]
    jobs = db.query(WorkspaceJob).filter(WorkspaceJob.kind == KIND, WorkspaceJob.workspace_id == model.workspace_id,
        WorkspaceJob.id.in_(ids)).order_by(WorkspaceJob.created_at.desc(), WorkspaceJob.id.desc()).all() if ids else []
    agree, differences, primary_correct, challenger_correct, primary_errors, challenger_errors = [], [], [], [], [], []
    primary_times, shadow_times, load_times, total_times = [], [], [], []
    compared = labeled = 0
    for job in jobs:
        row = by_id.get(job.input_ref.get("prediction_id"))
        if job.status != "completed" or row is None or contender is None or job.input_ref.get("challenger_id") != contender.id:
            continue
        answers = (job.result or {}).get("predictions") or []
        primary = list(row.output_json or [])
        pairs = list(zip(primary, answers))
        compared += len(pairs)
        if row.duration_ms is not None:
            primary_times.append(float(row.duration_ms))
        if _number(job.result.get("duration_ms")) is not None:
            shadow_times.append(float(job.result["duration_ms"]))
        if _number(job.result.get("load_ms")) is not None:
            load_times.append(float(job.result["load_ms"]))
        if _number(job.result.get("total_duration_ms")) is not None:
            total_times.append(float(job.result["total_duration_ms"]))
        for left, right in pairs:
            if model.task == "classification":
                agree.append(int(str(left.get("prediction")) == str(right.get("prediction"))))
            else:
                a, b = _number(left.get("prediction")), _number(right.get("prediction"))
                if a is not None and b is not None:
                    differences.append(abs(a - b))
        # Feedback has exactly one truth: for the first retained row only.
        if pairs and row.label is not None:
            left, right = pairs[0]
            if model.task == "classification" and str(row.label) in set(map(str, model.classes_json or [])):
                primary_correct.append(int(str(left.get("prediction")) == str(row.label)))
                challenger_correct.append(int(str(right.get("prediction")) == str(row.label)))
                labeled += 1
            elif model.task == "regression":
                a, b, truth = _number(left.get("prediction")), _number(right.get("prediction")), _number(row.label)
                if a is not None and b is not None and truth is not None:
                    primary_errors.append(abs(a - truth))
                    challenger_errors.append(abs(b - truth))
                    labeled += 1
    skipped = [row for row in rows if ((row.scores_json or {}).get("shadow") or {}).get("status") == "skipped"]
    recent = [{"prediction_id": job.input_ref.get("prediction_id"), "challenger_id": job.input_ref.get("challenger_id"),
        "version": job.input_ref.get("challenger_version"), "status": job.status, "error": job.error,
        "rows": job.input_ref.get("rows"), "created_at": job.created_at.isoformat(),
        "total_duration_ms": (job.result or {}).get("total_duration_ms")} for job in jobs[:10]]
    for row in skipped[:10]:
        marker = row.scores_json["shadow"]
        recent.append({"prediction_id": row.id, "challenger_id": marker.get("challenger_id"),
            "version": marker.get("challenger_version"), "status": "skipped", "error": marker.get("error"),
            "rows": min(MAX_ROWS, len(row.payload_json or [])), "created_at": row.created_at.isoformat(),
            "total_duration_ms": None})
    return {"supported": supported(model), "config": configuration(model).model_dump(), "can_configure": False,
        "challenger": {"id": contender.id, "version": contender.version} if contender else None,
        "limits": {"max_rows": MAX_ROWS, "max_pending": MAX_PENDING, "max_attempts": MAX_ATTEMPTS, "window": WINDOW_LIMIT},
        "comparison_scope": "current_pair",
        "window": {"jobs": len(jobs), "completed": sum(job.status == "completed" for job in jobs),
            "pending": sum(job.status in {"queued", "running"} for job in jobs),
            "failed": sum(job.status == "failed" for job in jobs),
            "skipped": len(skipped) + sum(job.status == "cancelled" for job in jobs),
            "compared_rows": compared, "labeled_pairs": labeled},
        "comparison": {"agreement": _mean(agree), "mean_absolute_difference": _mean(differences),
            "champion_accuracy": _mean(primary_correct), "challenger_accuracy": _mean(challenger_correct),
            "champion_mae": _mean(primary_errors), "challenger_mae": _mean(challenger_errors)},
        "latencies": {"primary_ms": _mean(primary_times), "shadow_ms": _mean(shadow_times),
                      "shadow_load_ms": _mean(load_times), "shadow_total_ms": _mean(total_times)},
        "recent": sorted(recent, key=lambda item: item["created_at"], reverse=True)[:10]}
