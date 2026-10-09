"""Observed forecast quality, isolated from training/backtest metrics.

Actuals are explicitly bound to a dataset version or an opted-in version lineage.
Each measurement pins the bytes and uses forecasts issued before their target
instant. Repeated calls have one vote per series/date/horizon, earliest retained
issue first. The existing journal is bounded (64 points/call), so this reports
sample coverage, never pretends to measure every point of a large batch.

Scientific imports are local: importing an API router must stay inexpensive.
"""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.tabular import MLModel, MLPrediction, TabularDataset
from app.services.tabular_datasets import TabularError, materialize, register_frame

MAX_CALLS = 400
MAX_POINTS = 25_600
MAX_ROWS = 100_000
MAX_BYTES = 32 * 1024 * 1024
MAX_GROUPS = 200
MIN_INTERVALS = 20


class ActualsBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: str = Field(min_length=8, max_length=36)
    follow_latest: bool = False


@dataclass
class ForecastSnapshot:
    report: dict[str, Any]
    fingerprint: str
    actuals: TabularDataset
    actuals_sha256: str
    frame: Any
    now: datetime


def _refuse(code, message, status=422):
    raise TabularError(code=code, message=message, status_code=status)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def binding_for(model):
    return dict(((model.params_json or {}).get("mlops") or {}).get("forecast_actuals") or {})


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _instant(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _require_model(model):
    if model.family != "forecasting" or model.task != "forecasting":
        _refuse("ML_FORECAST_ACTUALS_UNSUPPORTED", "Observed forecasts require a forecasting model.", 409)
    if model.status != "ready":
        _refuse("ML_MODEL_NOT_READY", "The forecast model must be ready.", 409)


def _dataset(db, model, dataset_id):
    dataset = db.query(TabularDataset).filter_by(id=dataset_id, workspace_id=model.workspace_id).first()
    if dataset is None:
        _refuse("ML_FORECAST_ACTUALS_NOT_FOUND", "The observed dataset is not in this workspace.", 404)
    if dataset.status != "ready":
        _refuse("ML_FORECAST_ACTUALS_UNAVAILABLE", "The observed dataset is not ready.", 409)
    return dataset


def _read(dataset):
    """Pin one file once, check actual size and Parquet metadata before loading."""
    import polars as pl
    import pyarrow.parquet as pq

    if (dataset.row_count or 0) > MAX_ROWS or (dataset.size_bytes or 0) > MAX_BYTES:
        _refuse("ML_FORECAST_ACTUALS_TOO_LARGE", "Observed history is limited to 100,000 rows and 32 MiB.", 413)
    with tempfile.TemporaryDirectory(prefix="forecast-actuals-") as folder:
        try:
            path = materialize(dataset, Path(folder) / "data.parquet")
            if path.stat().st_size > MAX_BYTES:
                _refuse("ML_FORECAST_ACTUALS_TOO_LARGE", "Observed history exceeds 32 MiB.", 413)
            metadata = pq.read_metadata(path)
            if metadata.num_rows > MAX_ROWS or metadata.num_columns > 256:
                _refuse("ML_FORECAST_ACTUALS_TOO_LARGE", "Observed history exceeds its row or column budget.", 413)
            # Compressed inputs must not expand without bound on an API worker.
            if sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups)) > MAX_BYTES * 4:
                _refuse("ML_FORECAST_ACTUALS_TOO_LARGE", "Observed history exceeds its decoded byte budget.", 413)
            fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
            return pl.read_parquet(path), fingerprint
        except (FileNotFoundError, OSError, ValueError) as exc:
            _refuse("ML_FORECAST_ACTUALS_UNAVAILABLE", f"The observed dataset cannot be read ({type(exc).__name__}).", 409)


def _normalized(model, frame, *, training=False):
    """One exact key per observed point; never silently discard bad actuals."""
    import polars as pl

    spec = model.spec_json or {}
    time_column = spec.get("time_column")
    series_columns = list(spec.get("series_columns") or []) if spec.get("shape") == "panel" else []
    covariates = dict(spec.get("exog") or {}) if training else {}
    required = [time_column, model.target, *series_columns, *covariates]
    if not time_column or not set(required) <= set(frame.columns):
        _refuse("ML_FORECAST_ACTUALS_COLUMNS", "Observed history must contain the model's time, target, series and required covariate columns.")
    if frame.height == 0:
        _refuse("ML_FORECAST_ACTUALS_EMPTY", "The observed dataset is empty.")
    keys, names, instants, records = {}, {}, [], []
    for record in frame.to_dicts():
        instant = _instant(record[time_column])
        number = _number(record[model.target])
        if instant is None:
            _refuse("ML_FORECAST_ACTUALS_DATE", "Every observed row needs a valid date; naive dates mean UTC.")
        if number is None:
            _refuse("ML_FORECAST_ACTUALS_NUMERIC", "Every observed target must be a finite number.")
        parts = tuple(str(record[column]) for column in series_columns)
        if any(record[column] is None for column in series_columns):
            _refuse("ML_FORECAST_ACTUALS_SERIES", "Every panel row needs its series identifiers.")
        series = " · ".join(parts) if parts else str(model.target)
        if series in names and names[series] != parts:
            _refuse("ML_FORECAST_ACTUALS_SERIES_COLLISION", "Two panel identifiers produce the same forecast series name.")
        names[series] = parts
        key = (series, instant)
        if key in keys:
            _refuse("ML_FORECAST_ACTUALS_DUPLICATE", "Observed history repeats a series and timestamp.")
        keys[key] = len(records)
        for column, role in covariates.items():
            if record[column] is None or (role != "static" and _number(record[column]) is None):
                _refuse("ML_FORECAST_HISTORY_COVARIATE", "Retraining history needs every finite numeric covariate and non-null static attribute.")
        record[time_column] = instant.replace(tzinfo=None)
        record[model.target] = number
        records.append(record)
        instants.append(instant)
    if len(names) > MAX_GROUPS:
        _refuse("ML_FORECAST_ACTUALS_TOO_MANY_SERIES", f"Observed monitoring supports at most {MAX_GROUPS} series.", 413)
    return pl.DataFrame(records, infer_schema_length=None), keys


def associate(db, *, model, workspace, user, body: ActualsBinding):
    from app.services.mlops_jobs import can_configure_mlops

    if not can_configure_mlops(db, workspace=workspace, user=user, admin_only=True):
        _refuse("ML_FORECAST_ACTUALS_FORBIDDEN", "A workspace administrator must associate observed history.", 403)
    model = db.query(MLModel).filter_by(id=model.id, workspace_id=workspace.id).populate_existing().with_for_update().first()
    if model is None:
        _refuse("ML_MODEL_NOT_FOUND", "The forecast model is unavailable.", 404)
    _require_model(model)
    dataset = _dataset(db, model, body.dataset_id)
    frame, sha256 = _read(dataset)
    _normalized(model, frame)
    binding = {"dataset_id": dataset.id, "slug": dataset.slug, "minimum_version": dataset.version,
               "sha256": sha256, "follow_latest": body.follow_latest, "associated_at": datetime.utcnow().isoformat(),
               "associated_by": user.id}
    model.params_json = {**(model.params_json or {}), "mlops": {
        **((model.params_json or {}).get("mlops") or {}), "forecast_actuals": binding}}
    db.commit()
    return binding


def _resolve(db, model):
    binding = binding_for(model)
    if not binding:
        _refuse("ML_FORECAST_ACTUALS_UNCONFIGURED", "Associate a dataset of observed values first.", 409)
    dataset = _dataset(db, model, binding.get("dataset_id"))
    if dataset.slug != binding.get("slug") or dataset.version != binding.get("minimum_version"):
        _refuse("ML_FORECAST_ACTUALS_BINDING_CHANGED", "The observed dataset identity has changed.", 409)
    if binding.get("follow_latest"):
        dataset = db.query(TabularDataset).filter_by(workspace_id=model.workspace_id, slug=dataset.slug, status="ready").filter(
            TabularDataset.version >= dataset.version).order_by(TabularDataset.version.desc()).first()
    frame, fingerprint = _read(dataset)
    if dataset.id == binding.get("dataset_id") and fingerprint != binding.get("sha256"):
        _refuse("ML_FORECAST_ACTUALS_CHANGED", "The associated observed dataset bytes have changed; associate it again.", 409)
    normalized, keys = _normalized(model, frame)
    return dataset, fingerprint, normalized, keys, binding


def _metrics(points):
    count = len(points)
    intervals = [p for p in points if p["lower_bound"] is not None and p["upper_bound"] is not None]
    errors = [p["pred"] - p["actual"] for p in points]
    # hypot avoids an overflowing intermediate square for finite extreme values.
    mae = math.fsum(abs(error) / count for error in errors) if count else None
    rmse = math.hypot(*errors) / math.sqrt(count) if count else None
    percentages = []
    for point in points:
        scale = max(abs(point["pred"]), abs(point["actual"]))
        pred, actual = (point["pred"] / scale, point["actual"] / scale) if scale else (0, 0)
        percentages.append(200 * abs(pred - actual) / (abs(pred) + abs(actual)) if scale else 0)
    smape = math.fsum(value / count for value in percentages) if count else None
    missed = sum(not p["lower_bound"] <= p["actual"] <= p["upper_bound"] for p in intervals)
    numbers = {"mae": mae, "rmse": rmse, "smape": smape,
               "coverage": 1 - missed / len(intervals) if intervals else None,
               "mean_interval_width": math.fsum((p["upper_bound"] / len(intervals) - p["lower_bound"] / len(intervals)) for p in intervals) if intervals else None,
               "nominal_coverage": math.fsum(p["interval_level"] / len(intervals) for p in intervals) if intervals else None}
    return {"count": count, "interval_count": len(intervals), "anomalies": missed,
            **{key: round(value, 6) if value is not None and math.isfinite(value) else None for key, value in numbers.items()}}


def _empty(status, reason=None):
    return {"status": status, "reason": reason, "dataset": None, "overall": _metrics([]),
            "by_series": [], "by_horizon": [], "anomalies": [], "window": {},
            "policy": {"selection": "earliest_issued_per_series_timestamp_horizon", "timestamp_semantics": "UTC; forecast issued strictly before target timestamp",
                       "min_intervals": MIN_INTERVALS, "coverage_watch_gap": .1, "coverage_alert_gap": .2}}


def snapshot(db, *, model, now=None):
    _require_model(model)
    now = _instant(now or datetime.utcnow())
    dataset, sha256, frame, actual_keys, binding = _resolve(db, model)
    calls = db.query(MLPrediction).filter_by(workspace_id=model.workspace_id, served_id=model.id,
        served_version=model.version).order_by(MLPrediction.created_at.desc(), MLPrediction.id.desc()).limit(MAX_CALLS + 1).all()
    truncated = len(calls) > MAX_CALLS
    calls = calls[:MAX_CALLS]
    points, seen, late, future, duplicates, invalid, retained = [], set(), 0, 0, 0, 0, 0
    values = frame[model.target].to_list()
    journal = []
    for call in reversed(calls):
        output = call.output_json if isinstance(call.output_json, list) else []
        output = output[:64]
        journal.append((call.id, call.created_at, output))
        truncated |= (call.row_count or 0) > len(output)
        issued = _instant(call.created_at)
        per_series = defaultdict(int)
        for row in output:
            retained += 1
            if not isinstance(row, dict):
                invalid += 1
                continue
            series = str(row.get("series", ""))
            per_series[series] += 1
            horizon = row.get("step", per_series[series])
            instant, pred = _instant(row.get("timestamp")), _number(row.get("pred"))
            if instant is None or pred is None or type(horizon) is not int or not 1 <= horizon <= 1000 or issued is None:
                invalid += 1
                continue
            if issued >= instant:
                late += 1
                continue
            if instant > now:
                future += 1
                continue
            key = (series, instant, horizon)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            index = actual_keys.get((series, instant))
            if index is None:
                continue
            low, high = _number(row.get("lower_bound")), _number(row.get("upper_bound"))
            if low is None or high is None or low > high:
                low, high = None, None
            level = _number(row.get("interval_level"))
            # Legacy rows did not record the requested confidence level. They
            # support errors, but cannot establish nominal interval coverage.
            if level is None or not .5 <= level <= .99:
                low, high = None, None
            points.append({"series": series, "timestamp": instant.isoformat(), "horizon": horizon,
                "actual": values[index], "pred": pred, "lower_bound": low, "upper_bound": high,
                "interval_level": level, "prediction_id": call.id, "issued_at": issued.isoformat()})
    overall = _metrics(points)
    gap = ((overall["nominal_coverage"] or 0) - (overall["coverage"] or 0))
    status = "insufficient" if overall["interval_count"] < MIN_INTERVALS else "alert" if gap >= .2 - 1e-9 else "watch" if gap >= .1 - 1e-9 else "ok"
    result = _empty(status)
    result.update(dataset={"id": dataset.id, "name": dataset.name, "slug": dataset.slug, "version": dataset.version,
            "sha256": sha256, "associated_at": binding.get("associated_at"), "follow_latest": bool(binding.get("follow_latest")),
            "minimum_version": binding.get("minimum_version")}, overall=overall,
        window={"calls": len(calls), "retained_points": retained, "matched": len(points), "excluded_late": late,
                "excluded_future": future, "duplicates": duplicates, "invalid": invalid, "actual_rows": frame.height,
                "limit_calls": MAX_CALLS, "limit_points": MAX_POINTS, "truncated": bool(truncated)},
        anomalies=[p for p in points if p["lower_bound"] is not None and not p["lower_bound"] <= p["actual"] <= p["upper_bound"]][:40])
    for field, key in (("by_series", "series"), ("by_horizon", "horizon")):
        groups = defaultdict(list)
        for point in points:
            groups[point[key]].append(point)
        result[field] = [{key: name, **_metrics(group)} for name, group in sorted(groups.items())][:MAX_GROUPS]
        if len(groups) > MAX_GROUPS:
            result["window"]["truncated"] = True
    fingerprint = _digest({"model_id": model.id, "version": model.version, "dataset_id": dataset.id,
                           "dataset_version": dataset.version, "sha256": sha256, "journal": journal,
                           "eligible": [(p["prediction_id"], p["series"], p["timestamp"], p["horizon"]) for p in points]})
    result["window"]["sha256"] = fingerprint
    return ForecastSnapshot(result, fingerprint, dataset, sha256, frame, now)


def report(db, *, model):
    if model.family != "forecasting":
        return None
    try:
        return snapshot(db, model=model).report
    except TabularError as exc:
        return _empty("unconfigured" if exc.code == "ML_FORECAST_ACTUALS_UNCONFIGURED" else "unavailable", exc.code)


def materialize_training_history(db, *, model, snapshot: ForecastSnapshot, created_by=None):
    """Freeze complete history plus new observations, without filling covariates.

    Conflicting revisions of the original history are rejected; repeated equal
    rows count once. The pinned measurement frame is reused, so following a
    lineage cannot switch actual versions after human evidence was computed.
    """
    import polars as pl

    original = _dataset(db, model, model.dataset_id)
    train, train_sha = _read(original)
    train, train_keys = _normalized(model, train, training=True)
    actuals, actual_keys = _normalized(model, snapshot.frame, training=True)
    spec = model.spec_json or {}
    columns = list(dict.fromkeys([spec["time_column"], model.target, *(spec.get("series_columns") or []), *(spec.get("exog") or {})]))
    records = train.select(columns).to_dicts()
    observed = actuals.select(columns).to_dicts()
    if any(instant > snapshot.now for _, instant in train_keys):
        _refuse("ML_FORECAST_HISTORY_FUTURE", "The original training history contains future observations.", 409)
    new_rows = 0
    for key, index in actual_keys.items():
        if key[1] > snapshot.now:
            continue
        record = observed[index]
        if key in train_keys:
            if records[train_keys[key]] != record:
                _refuse("ML_FORECAST_HISTORY_CONFLICT", "Observed values conflict with the original training history.", 409)
        else:
            records.append(record)
            new_rows += 1
    if new_rows == 0:
        _refuse("ML_FORECAST_HISTORY_NO_NEW_ROWS", "Observed history adds no completed observations to training.", 409)
    if len(records) > MAX_ROWS:
        _refuse("ML_FORECAST_ACTUALS_TOO_LARGE", "Combined retraining history exceeds 100,000 rows.", 413)
    provenance = {"kind": "forecast_history", "source_model_id": model.id, "source_model_version": model.version,
        "training_dataset": {"id": original.id, "version": original.version, "sha256": train_sha},
        "actuals_dataset": {"id": snapshot.actuals.id, "version": snapshot.actuals.version, "sha256": snapshot.actuals_sha256},
        "window_sha256": snapshot.fingerprint, "new_rows": new_rows, "history_rows": len(records)}
    history = pl.DataFrame(records, infer_schema_length=None).sort([*(spec.get("series_columns") or []), spec["time_column"]])
    dataset = register_frame(db, workspace_id=model.workspace_id, name=f"{model.name[:150]} · observed history", frame=history,
        source="generated", produced_by="ml_forecast_monitoring", parent_ids=[original.id, snapshot.actuals.id],
        created_by=created_by, lineage=provenance)
    return dataset, provenance
