"""Forecasts on demand: ``POST /ml-models/{id}/forecast``, both halves.

A forecasting model is fitted in the ml-ts image and its artifact only loads
where skforecast is installed, so the API never unpickles it (see
``tabular_predict.load_pipeline_traced``). A forecast request therefore crosses
the broker:

* **the API side** (:func:`request_forecast`) resolves the version that answers,
  checks that a worker is listening on the family's serving queue, sends one
  ``agentium.ml_forecast`` task and waits for its answer under a timeout — then
  journals the call like any prediction, so a forecast is counted, keyed and
  monitored the same way;
* **the worker side** (:func:`answer_for`), in the ml-ts serving worker (a
  threads pool, so one cache serves every thread), downloads the model once,
  checks that the artifact and the model's code file are the ones the harness
  vouched for, keeps the loaded pyfunc in a small LRU cache, and answers.

Errors cross the broker as data (``{"error": {...}, "status": ...}``), never
as pickled exceptions: the API re-raises them as the same coded refusals a
tabular prediction uses, so the Playground renders both alike.

Nothing heavy is imported at module scope: the API imports this module.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.tabular_datasets import TabularError

logger = get_logger(__name__)

FORECAST_TASK = "agentium.ml_forecast"
CODE_FILE = "ml_forecast_pyfunc.py"
OUTPUT_COLUMNS = ("series", "timestamp", "pred", "lower_bound", "upper_bound")


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------


@dataclass
class LoadedForecaster:
    fingerprint: str
    pyfunc: Any
    meta: dict[str, Any]
    load_ms: float
    directory: Path = field(repr=False)


_cache: OrderedDict[str, LoadedForecaster] = OrderedDict()
_cache_lock = threading.Lock()
# One load per model at a time: two threads asking for a cold model must not
# both download and unpickle it.
_load_locks: dict[str, threading.Lock] = {}


def _fingerprint(model: Any) -> str:
    artifact = (model.metrics_json or {}).get("artifact") or {}
    return f"{model.id}:{model.model_uri}:{artifact.get('sha256', '')}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify(model: Any, directory: Path) -> None:
    """The bytes about to be executed are the ones the harness wrote.

    A models-from-code pyfunc runs its code file at load, and a joblib
    artifact runs whatever it was pickled with: both are checked against the
    sha256 the training run recorded before either is touched.
    """

    artifact = (model.metrics_json or {}).get("artifact") or {}
    expected_code = artifact.get("code_sha256")
    expected_artifact = artifact.get("sha256")
    serialization = artifact.get("serialization") or "skops"
    if not expected_code or not expected_artifact:
        raise TabularError(
            code="ML_ARTIFACT_UNVERIFIED",
            message="This forecast was saved without the fingerprints serving checks.",
            status_code=409,
        )
    code = directory / CODE_FILE
    stored = directory / "artifacts" / f"forecaster.{serialization}"
    if not code.is_file() or not stored.is_file():
        raise TabularError(
            code="ML_ARTIFACT_UNLOADABLE",
            message="The forecast's model directory is incomplete.",
            status_code=409,
        )
    if _sha256(code) != expected_code or _sha256(stored) != expected_artifact:
        raise TabularError(
            code="ML_ARTIFACT_TAMPERED",
            message="The stored forecast is not the one its training run produced.",
            status_code=409,
        )


def _evict(entry: LoadedForecaster) -> None:
    shutil.rmtree(entry.directory, ignore_errors=True)


def load_forecaster(model: Any) -> tuple[LoadedForecaster, bool]:
    """The loaded model, and whether it was already resident."""

    fingerprint = _fingerprint(model)
    with _cache_lock:
        cached = _cache.get(model.id)
        if cached is not None and cached.fingerprint == fingerprint:
            _cache.move_to_end(model.id)
            return cached, True
        lock = _load_locks.setdefault(model.id, threading.Lock())
    with lock:
        with _cache_lock:
            cached = _cache.get(model.id)
            if cached is not None and cached.fingerprint == fingerprint:
                return cached, True
        started = time.monotonic()
        from app.services.tabular_ml import download_model_dir

        directory = Path(tempfile.mkdtemp(prefix="ml-forecast-"))
        try:
            download_model_dir(model, directory)
            _verify(model, directory)
            import json

            import mlflow.pyfunc

            pyfunc = mlflow.pyfunc.load_model(str(directory))
            meta = json.loads((directory / "artifacts" / "meta.json").read_text(encoding="utf-8"))
        except TabularError:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001 - the caller renders a code, not a trace
            shutil.rmtree(directory, ignore_errors=True)
            logger.exception("forecast_serving: load failed", model_id=model.id)
            raise TabularError(
                code="ML_ARTIFACT_UNLOADABLE",
                message=f"The forecast could not be loaded: {type(exc).__name__}",
                status_code=409,
            ) from exc
        entry = LoadedForecaster(
            fingerprint=fingerprint,
            pyfunc=pyfunc,
            meta=meta,
            load_ms=round((time.monotonic() - started) * 1000, 1),
            directory=directory,
        )
        with _cache_lock:
            previous = _cache.pop(model.id, None)
            if previous is not None:
                _evict(previous)
            _cache[model.id] = entry
            while len(_cache) > int(settings.ml_predict_cache_size):
                _, oldest = _cache.popitem(last=False)
                _evict(oldest)
        return entry, False


def reset_cache() -> None:
    with _cache_lock:
        for entry in _cache.values():
            _evict(entry)
        _cache.clear()


def _model_input(inputs: list[dict[str, Any]], meta: dict[str, Any]):
    import pandas as pd

    future = list(meta.get("exog_future") or [])
    frame = pd.DataFrame(inputs or [])
    for column in ("series", "timestamp"):
        frame[column] = frame[column].astype(str) if column in frame else pd.Series([], dtype=str)
    if frame.empty:
        frame = pd.DataFrame({"series": pd.Series([], dtype=str), "timestamp": pd.Series([], dtype=str)})
    for column in future:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    known = ["series", "timestamp", *future]
    return frame[[column for column in known if column in frame]]


def answer(model: Any, *, horizon: Any, level: Any, inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """One forecast from a ready forecasting model, in long form."""

    entry, resident = load_forecaster(model)
    meta = entry.meta
    ceiling = int(meta.get("max_steps") or settings.ml_ts_max_horizon)
    try:
        steps = int(horizon if horizon is not None else meta.get("horizon") or 1)
        interval = float(level if level is not None else meta.get("interval_level") or 0.8)
    except (TypeError, ValueError) as exc:
        raise TabularError(
            code="ML_FORECAST_PARAMS_INVALID",
            message="horizon must be a whole number and interval_level a number.",
            status_code=422,
        ) from exc
    if not 1 <= steps <= ceiling:
        raise TabularError(
            code="ML_FORECAST_HORIZON_INVALID",
            message=f"This model forecasts between 1 and {ceiling} steps ahead.",
            status_code=422,
            details={"max": ceiling},
        )
    if not 0.5 <= interval <= 0.99:
        raise TabularError(
            code="ML_FORECAST_PARAMS_INVALID",
            message="interval_level must be between 0.5 and 0.99.",
            status_code=422,
        )
    started = time.monotonic()
    try:
        frame = entry.pyfunc.predict(
            _model_input(inputs, meta), params={"horizon": steps, "interval_level": interval}
        )
    except ValueError as exc:
        # The pyfunc says what is missing in a sentence: a future covariate,
        # an unknown series. That sentence is the answer.
        raise TabularError(
            code="ML_FORECAST_INPUT_INVALID",
            message=str(exc)[:300],
            status_code=422,
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("forecast_serving: predict failed", model_id=model.id)
        raise TabularError(
            code="ML_FORECAST_FAILED",
            message=f"The forecast failed: {type(exc).__name__}",
            status_code=500,
        ) from exc
    rows = []
    for record in frame.to_dict(orient="records"):
        rows.append({key: record.get(key) for key in OUTPUT_COLUMNS})
    return {
        "forecast": rows,
        "horizon": steps,
        "interval_level": interval,
        "series": sorted({str(row["series"]) for row in rows}),
        "frequency": meta.get("frequency"),
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        "load_ms": 0.0 if resident else entry.load_ms,
        "cached": resident,
    }


def answer_for(model_id: str, *, horizon: Any, level: Any, inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """The task body: load the row, answer, and turn a refusal into data."""

    from app.db.base import SessionLocal
    from app.models.tabular import MLModel

    try:
        with SessionLocal() as db:
            model = db.query(MLModel).filter(MLModel.id == model_id).first()
            if model is None or model.status != "ready":
                raise TabularError(
                    code="ML_MODEL_NOT_READY", message="The model is not trained.", status_code=409
                )
            db.expunge(model)
        return answer(model, horizon=horizon, level=level, inputs=inputs)
    except TabularError as exc:
        return {"error": exc.payload(), "status": exc.status_code}


# ---------------------------------------------------------------------------
# API side
# ---------------------------------------------------------------------------


def _raise_from(result: dict[str, Any]) -> None:
    error = result.get("error") or {}
    raise TabularError(
        code=str(error.get("code") or "ML_FORECAST_FAILED"),
        message=str(error.get("message") or "The forecast failed."),
        status_code=int(result.get("status") or 500),
        details={key: value for key, value in error.items() if key not in {"code", "message", "error"}} or None,
    )


def request_forecast(
    db: Any,
    model: Any,
    *,
    horizon: Any = None,
    level: Any = None,
    inputs: list[dict[str, Any]] | None = None,
    version: Any = None,
    caller: str = "session",
) -> dict[str, Any]:
    """Answer ``POST /forecast``: the version that serves, through its worker."""

    from app.services.ml.families import get_family
    from app.services.ml.runtime import serving_availability
    from app.services.tabular_predict import journal_call, record_usage, serving_version

    served = serving_version(db, model, version=version)
    family = get_family(served.family)
    if family.serving == "in_process":
        raise TabularError(
            code="ML_USE_PREDICT_ROUTE",
            message="This model answers rows: call /predict.",
            status_code=409,
        )
    rows = list(inputs or [])
    if len(rows) > int(settings.ml_forecast_max_rows):
        raise TabularError(
            code="ML_FORECAST_TOO_MANY_ROWS",
            message=f"At most {int(settings.ml_forecast_max_rows):,} rows of future values per call.",
            status_code=413,
        )
    available, reason = serving_availability(family, db)
    if not available:
        raise TabularError(
            code="ML_FAMILY_UNAVAILABLE",
            message="No forecasting worker is listening right now.",
            status_code=409,
            details={"family": family.key, "reason": reason},
        )
    started = time.monotonic()
    if settings.worker_eager_mode:
        result = answer_for(served.id, horizon=horizon, level=level, inputs=rows)
    else:
        from celery.exceptions import TimeoutError as CeleryTimeout

        from app.workers.celery_app import celery_app

        pending = celery_app.send_task(
            FORECAST_TASK,
            args=[served.id],
            kwargs={"horizon": horizon, "level": level, "inputs": rows},
            queue=family.serve_queue(),
            # A forecast nobody collected in time is not worth computing later.
            expires=float(settings.ml_forecast_timeout_s),
        )
        try:
            result = pending.get(timeout=float(settings.ml_forecast_timeout_s), propagate=False)
        except CeleryTimeout as exc:
            raise TabularError(
                code="ML_FORECAST_TIMEOUT",
                message=f"The forecasting worker did not answer within {int(settings.ml_forecast_timeout_s)}s.",
                status_code=504,
            ) from exc
        finally:
            pending.forget() if hasattr(pending, "forget") else None
    if not isinstance(result, dict):
        raise TabularError(code="ML_FORECAST_FAILED", message="The forecasting worker failed.", status_code=500)
    if result.get("error"):
        _raise_from(result)
    duration_ms = round((time.monotonic() - started) * 1000, 1)
    forecast = list(result.get("forecast") or [])
    prediction_id = journal_call(
        db,
        requested=model,
        served=served,
        caller=caller,
        rows=rows or [{"horizon": result.get("horizon"), "interval_level": result.get("interval_level")}],
        answers=forecast,
        duration_ms=duration_ms,
    )
    record_usage(db, served, rows=len(forecast))
    return {
        "served": {
            "model_id": served.id,
            "name": served.name,
            "slug": served.slug,
            "version": int(served.version or 1),
            "is_champion": bool(served.is_champion),
            "task": served.task,
        },
        "task": served.task,
        "target": served.target,
        "horizon": result.get("horizon"),
        "interval_level": result.get("interval_level"),
        "frequency": result.get("frequency"),
        "series": result.get("series") or [],
        "forecast": forecast,
        "rows": len(forecast),
        "duration_ms": duration_ms,
        "load_ms": result.get("load_ms"),
        "cached": bool(result.get("cached")),
        "prediction_id": prediction_id,
    }


def public_forecast_path(model: Any) -> str:
    return f"{settings.api_v1_prefix}/ml-models/{model.id}/forecast"


__all__ = [
    "FORECAST_TASK",
    "answer",
    "answer_for",
    "load_forecaster",
    "public_forecast_path",
    "request_forecast",
    "reset_cache",
]
