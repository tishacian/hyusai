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
import re
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


_EXPLAIN_FEATURES = 8


def _inverse_scale(forecaster: Any, series: str) -> tuple[float, float]:
    """(scale, shift) undoing a linear series transformer, or (1, 0).

    A multivariate forecaster standardizes its series by default, so its
    estimator answers in standard units; a contribution is converted back
    with the same affine map, which keeps base + contributions = forecast.
    """

    transformers = getattr(forecaster, "transformer_series_", None) or {}
    transformer = transformers.get(series) if isinstance(transformers, dict) else None
    if transformer is None:
        return 1.0, 0.0
    scale = getattr(transformer, "scale_", None)
    mean = getattr(transformer, "mean_", None)
    if scale is None or mean is None:
        raise ValueError("non-linear series transformer")
    return float(scale[0]), float(mean[0])


def explain_forecast(entry: LoadedForecaster, model_input: Any, *, steps: int, answered: list[dict[str, Any]]):
    """What lifted or lowered each step of one series' forecast.

    The matrix the model predicted from (``create_predict_X``: lags — which,
    past the first step of a recursive forecast, are its own predictions —,
    calendar, covariates) is explained row by row, with the estimator that
    produced that row (one per step for a direct model). Contributions are
    summed per family, so each step reads as base + families = forecast, and
    the peak step also names its strongest features.

    One series: the one asked for, else the one whose forecast peaks highest.
    """

    import numpy as np

    info = entry.meta.get("explain") or {}
    kind = info.get("kind")
    if kind not in ("tree", "linear") or not answered:
        return None
    python_model = entry.pyfunc.unwrap_python_model()
    forecaster = python_model.forecaster
    meta = entry.meta
    peak_row = max(answered, key=lambda row: row.get("pred") if row.get("pred") is not None else float("-inf"))
    series = str(peak_row["series"])
    panel = meta.get("shape") == "panel"
    exog = python_model._exog(model_input, steps, [series] if panel else list(meta.get("levels") or []))
    if panel:
        matrix = forecaster.create_predict_X(steps=steps, levels=[series], exog=exog, suppress_warnings=True)
    else:
        matrix = forecaster.create_predict_X(steps=steps, exog=exog, suppress_warnings=True)
    if "level" in matrix.columns:
        matrix = matrix.drop(columns=["level"])
    columns = [str(column) for column in matrix.columns]
    groups = info.get("groups") or {}
    means = info.get("means") or {}
    # One estimator per step ahead, keyed by the step.
    direct = type(forecaster).__name__ in ("ForecasterDirect", "ForecasterDirectMultiVariate")
    scale, shift = _inverse_scale(forecaster, meta.get("target") if meta.get("shape") == "multivariate" else series)
    explainers: dict[int, Any] = {}
    by_step = []
    peak_features: list[dict[str, Any]] = []
    rows = [row for row in answered if str(row["series"]) == series]
    for index in range(min(len(matrix), len(rows))):
        estimator = forecaster.estimators_[index + 1] if direct else forecaster.estimator
        x = matrix.iloc[[index]].astype(float)
        if kind == "linear":
            coef = np.ravel(estimator.coef_)
            centre = np.array([means.get(column, 0.0) for column in columns])
            contributions = coef * (x.to_numpy()[0] - centre)
            base = float(np.ravel([estimator.intercept_])[0] + coef @ centre)
        else:
            import shap

            key = id(estimator)
            if key not in explainers:
                explainers[key] = shap.TreeExplainer(estimator)
            explainer = explainers[key]
            contributions = np.ravel(explainer.shap_values(x))
            base = float(np.ravel([explainer.expected_value])[0])
        contributions = contributions * scale
        base = base * scale + shift
        families: dict[str, float] = {}
        for column, value in zip(columns, contributions):
            family = groups.get(column) or groups.get(re.sub(r"_step_\d+$", "", column)) or "other"
            families[family] = families.get(family, 0.0) + float(value)
        row = rows[index]
        by_step.append(
            {
                "step": index + 1,
                "timestamp": row["timestamp"],
                "pred": row["pred"],
                "base": base,
                "groups": {family: round(value, 6) for family, value in families.items()},
            }
        )
        if row is peak_row:
            ranked = sorted(zip(columns, contributions, x.to_numpy()[0]), key=lambda item: -abs(item[1]))
            peak_features = [
                {
                    "feature": column,
                    "group": groups.get(column) or "other",
                    "contribution": float(value),
                    "value": float(raw),
                }
                for column, value, raw in ranked[:_EXPLAIN_FEATURES]
            ]
    peak = next((step for step in by_step if step["timestamp"] == peak_row["timestamp"]), None)
    return {
        "series": series,
        "method": "shap" if kind == "tree" else "linear",
        "steps": by_step,
        "peak": {**peak, "features": peak_features} if peak else None,
    }


def answer(
    model: Any, *, horizon: Any, level: Any, inputs: list[dict[str, Any]], explain: bool = False
) -> dict[str, Any]:
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
    model_input = _model_input(inputs, meta)
    try:
        frame = entry.pyfunc.predict(model_input, params={"horizon": steps, "interval_level": interval})
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
    explanation = None
    if explain:
        try:
            explanation = explain_forecast(entry, model_input, steps=steps, answered=rows)
        except Exception:  # noqa: BLE001 - an explanation is extra; the forecast stands
            logger.exception("forecast_serving: explanation failed", model_id=model.id)
    return {
        "forecast": rows,
        "explanation": explanation,
        "horizon": steps,
        "interval_level": interval,
        "series": sorted({str(row["series"]) for row in rows}),
        "frequency": meta.get("frequency"),
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        "load_ms": 0.0 if resident else entry.load_ms,
        "cached": resident,
    }


def answer_for(
    model_id: str, *, horizon: Any, level: Any, inputs: list[dict[str, Any]], explain: bool = False
) -> dict[str, Any]:
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
        return answer(model, horizon=horizon, level=level, inputs=inputs, explain=explain)
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
    explain: bool = False,
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
        result = answer_for(served.id, horizon=horizon, level=level, inputs=rows, explain=explain)
    else:
        from celery.exceptions import TimeoutError as CeleryTimeout

        from app.workers.celery_app import celery_app

        pending = celery_app.send_task(
            FORECAST_TASK,
            args=[served.id],
            kwargs={"horizon": horizon, "level": level, "inputs": rows, "explain": explain},
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
        "explanation": result.get("explanation"),
        "rows": len(forecast),
        "duration_ms": duration_ms,
        "load_ms": result.get("load_ms"),
        "cached": bool(result.get("cached")),
        "prediction_id": prediction_id,
    }


def public_forecast_path(model: Any) -> str:
    return f"{settings.api_v1_prefix}/ml-models/{model.id}/forecast"


# ---------------------------------------------------------------------------
# A forecast written as a dataset (the Flow node)
# ---------------------------------------------------------------------------

FORECAST_BATCH_TASK = "agentium.ml_forecast_batch"
FORECAST_SKILL_SLUG = "ml_forecast_v1"
# The batch-score step codes, which the Data page already renders: a forecast
# written as a dataset is read the same way as a scored one.
FORECAST_STEPS = ("queued", "reading", "scoring", "writing")
# What the node hands downstream inline: the series most likely to cross a
# line first, which is what an alert or a summary node reads.
_PEAKS = 12


def submit_forecast_dataset(
    db: Any,
    *,
    model: Any,
    workspace_id: str,
    horizon: Any = None,
    level: Any = None,
    future: Any = None,
    output_name: str | None = None,
    version: Any = None,
    run_id: str | None = None,
    node_id: str | None = None,
) -> Any:
    """Reserve the dataset a forecast will be written into, and dispatch it.

    The node that calls this runs in the general worker, which cannot load the
    forecast; the ml-ts serving worker can. So the work crosses the broker, and
    the reserved row is how the node learns it is done — it polls the row, the
    way a training node polls its model. Nothing waits on a task result.
    """

    from app.services.ml.families import get_family
    from app.services.ml.runtime import serving_availability
    from app.services.tabular_datasets import reserve_frame
    from app.services.tabular_predict import serving_version

    served = serving_version(db, model, version=version)
    family = get_family(served.family)
    if family.serving == "in_process":
        raise TabularError(
            code="ML_USE_PREDICT_ROUTE",
            message="This model answers rows: use the scoring node.",
            status_code=409,
        )
    available, reason = serving_availability(family, db)
    if not available:
        raise TabularError(
            code="ML_FAMILY_UNAVAILABLE",
            message="No forecasting worker is listening right now.",
            status_code=409,
            details={"family": family.key, "reason": reason},
        )
    if future is not None and future.status != "ready":
        raise TabularError(
            code="DATASET_NOT_READY",
            message="The dataset of future values is still being prepared.",
            status_code=409,
        )
    steps = int(horizon or (served.spec_json or {}).get("horizon") or 1)
    output = reserve_frame(
        db,
        workspace_id=workspace_id,
        name=(output_name or f"{served.name} · forecast +{steps}")[:200],
        source="score",
        produced_by=FORECAST_SKILL_SLUG,
        parent_ids=[future.id] if future is not None else [served.dataset_id] if served.dataset_id else [],
        run_id=run_id,
        node_id=node_id,
        step=FORECAST_STEPS[0],
        lineage={"kind": "forecast"},
    )
    kwargs = {
        "requested_id": model.id,
        "horizon": horizon,
        "level": level,
        "future_id": future.id if future is not None else None,
    }
    if settings.worker_eager_mode:
        forecast_into(output.id, served.id, **kwargs)
    else:
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            FORECAST_BATCH_TASK, args=[output.id, served.id], kwargs=kwargs, queue=family.serve_queue()
        )
    return output


def _peaks(frame: Any) -> list[dict[str, Any]]:
    """Per series, where the forecast peaks and how high its interval goes."""

    peaks = []
    for name, rows in frame.groupby("series"):
        top = rows.loc[rows["pred"].idxmax()]
        peaks.append(
            {
                "series": str(name),
                "timestamp": str(top["timestamp"]),
                "pred": float(top["pred"]),
                "upper_bound": float(top["upper_bound"]) if top["upper_bound"] == top["upper_bound"] else None,
            }
        )
    peaks.sort(key=lambda peak: -(peak["upper_bound"] if peak["upper_bound"] is not None else peak["pred"]))
    return peaks[:_PEAKS]


def forecast_into(
    output_id: str,
    served_id: str,
    *,
    requested_id: str | None = None,
    horizon: Any = None,
    level: Any = None,
    future_id: str | None = None,
) -> dict[str, Any]:
    """The task body: forecast every series and settle the reserved row.

    Idempotent on redelivery: a row that is no longer ``ingesting`` was already
    settled (or retired), so it is left alone rather than written twice.
    """

    import pandas as pd
    import polars as pl

    from app.db.base import SessionLocal
    from app.models.tabular import MLModel, TabularDataset
    from app.services.tabular_datasets import fail_frame, mark_step, read_frame, register_frame
    from app.services.tabular_predict import _served_block, journal_call, record_usage

    with SessionLocal() as db:
        output = db.query(TabularDataset).filter(TabularDataset.id == output_id).first()
        if output is None or output.status != "ingesting":
            return {"dataset_id": output_id, "status": getattr(output, "status", "missing")}
        started = time.monotonic()
        try:
            served = db.query(MLModel).filter(MLModel.id == served_id).first()
            if served is None or served.status != "ready":
                raise TabularError(code="ML_MODEL_NOT_READY", message="The model is not trained.", status_code=409)
            requested = db.query(MLModel).filter(MLModel.id == (requested_id or served_id)).first() or served
            inputs: list[dict[str, Any]] = []
            future = None
            if future_id:
                future = db.query(TabularDataset).filter(TabularDataset.id == future_id).first()
                if future is None or future.status != "ready":
                    raise TabularError(
                        code="DATASET_NOT_READY", message="The dataset of future values is gone.", status_code=409
                    )
                if int(future.row_count or 0) > int(settings.ml_forecast_max_rows):
                    raise TabularError(
                        code="ML_FORECAST_TOO_MANY_ROWS",
                        message=f"At most {int(settings.ml_forecast_max_rows):,} rows of future values.",
                        status_code=413,
                    )
                frame_in = read_frame(future).to_pandas()
                for column in frame_in.columns:
                    if pd.api.types.is_datetime64_any_dtype(frame_in[column]):
                        frame_in[column] = frame_in[column].dt.strftime("%Y-%m-%d %H:%M:%S")
                time_column = (served.spec_json or {}).get("time_column")
                if time_column and time_column in frame_in.columns and "timestamp" not in frame_in.columns:
                    frame_in = frame_in.rename(columns={time_column: "timestamp"})
                series_columns = list((served.spec_json or {}).get("series_columns") or [])
                if series_columns and "series" not in frame_in.columns and set(series_columns) <= set(frame_in.columns):
                    frame_in["series"] = frame_in[series_columns].astype(str).agg(" · ".join, axis=1)
                inputs = frame_in.to_dict(orient="records")
            db.expunge(served)
            mark_step(db, output, FORECAST_STEPS[1])
            result = answer(served, horizon=horizon, level=level, inputs=inputs)
            mark_step(db, output, FORECAST_STEPS[2])
            rows = result["forecast"]
            frame = pd.DataFrame(rows, columns=list(OUTPUT_COLUMNS))
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
            frame["step"] = frame.groupby("series").cumcount() + 1
            frame = frame[["series", "timestamp", "step", "pred", "lower_bound", "upper_bound"]]
            peaks = _peaks(frame)
            mark_step(db, output, FORECAST_STEPS[3])
            elapsed_ms = round((time.monotonic() - started) * 1000, 1)
            output = register_frame(
                db,
                workspace_id=output.workspace_id,
                name=output.name,
                frame=pl.from_pandas(frame),
                source="score",
                produced_by=FORECAST_SKILL_SLUG,
                parent_ids=list(output.parent_ids or []),
                into=output,
                lineage={
                    "kind": "forecast",
                    "engine": "skforecast",
                    "model": {
                        "model_id": served.id,
                        "slug": served.slug,
                        "version": int(served.version or 1),
                        "task": served.task,
                        "algo": served.algo,
                        "target": served.target,
                    },
                    "horizon": result["horizon"],
                    "interval_level": result["interval_level"],
                    "frequency": result.get("frequency"),
                    "series": len(result["series"]),
                    "peaks": peaks,
                    "sources": [{"dataset_id": future.id, "slug": future.slug}] if future is not None else [],
                    "duration_ms": elapsed_ms,
                },
            )
            record_usage(db, served, rows=len(rows))
            journal_call(
                db,
                requested=requested,
                served=served,
                caller="forecast",
                rows=inputs or [{"horizon": result["horizon"], "interval_level": result["interval_level"]}],
                answers=rows,
                duration_ms=elapsed_ms,
                dataset_id=output.id,
            )
            return {"dataset_id": output.id, "status": "ready", "block": _served_block(served)}
        except TabularError as exc:
            fail_frame(db, output, f"{exc.code}: {exc.message}"[:2000])
            return {"dataset_id": output_id, "status": "failed", "error": exc.payload()}
        except Exception as exc:  # noqa: BLE001 - the row must not outlive the work
            logger.exception("forecast_serving: forecast dataset failed", dataset_id=output_id)
            fail_frame(db, output, f"ML_FORECAST_FAILED: {type(exc).__name__}: {exc}"[:2000])
            return {"dataset_id": output_id, "status": "failed"}


__all__ = [
    "FORECAST_BATCH_TASK",
    "FORECAST_SKILL_SLUG",
    "FORECAST_TASK",
    "answer",
    "forecast_into",
    "submit_forecast_dataset",
    "answer_for",
    "load_forecaster",
    "public_forecast_path",
    "request_forecast",
    "reset_cache",
]
