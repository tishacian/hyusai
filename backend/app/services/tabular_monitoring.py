"""Drift and feedback over the serving journal.

Three measurements, all from ``ml_predictions``:

* **data drift** — PSI (numeric) and a frequency-PSI (categorical) of the
  payloads against the training dataset's ``stats_json`` / input contract;
* **score drift** — served scores against the recorded final-test reference,
  with an explicitly labelled previous-window fallback for legacy models;
* **concept drift** — row-aligned classification or regression ground truth,
  compared with the final-test metrics recorded at training time.

Thresholds are the usual PSI bands: below 0.10 is fine, 0.10–0.25 wants a
look, above 0.25 is an alert. The badge on the Models list is the worst of
the three, or absent when nothing has been served.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.models.tabular import MLModel, MLPrediction, TabularDataset
from app.resources.ml_drift import adjust_tests, feature_test, finite_number
from app.services.ml_feedback import iter_labeled_samples, samples_metadata
from app.services.tabular_datasets import (
    NUMERIC_KINDS,
    TabularError,
    register_frame,
)

logger = get_logger(__name__)

WINDOW_LIMIT = 400
PSI_OK = 0.10
PSI_WATCH = 0.25
AUC_WATCH = 0.02
AUC_ALERT = 0.05
MIN_PSI_SAMPLES = 8
MIN_AUC_SAMPLES = 8
MIN_MATERIALIZE = 2

STATUSES = ("unknown", "ok", "watch", "alert")
_STATUS_RANK = {name: index for index, name in enumerate(STATUSES)}


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def population_stability(
    expected: list[float], actual: list[float], *, bins: int = 10
) -> float | None:
    """PSI between two numeric samples, or None when either side is too thin."""

    if len(expected) < MIN_PSI_SAMPLES or len(actual) < MIN_PSI_SAMPLES:
        return None
    ordered = sorted(float(value) for value in expected)
    raw_edges = [
        ordered[min(len(ordered) - 1, int(round(i * (len(ordered) - 1) / bins)))]
        for i in range(bins + 1)
    ]
    edges = [raw_edges[0]]
    for edge in raw_edges[1:]:
        if edge > edges[-1]:
            edges.append(edge)
    if len(edges) == 1:
        pivot = edges[0]

        def collapsed_hist(values):
            counts = [0, 0, 0]
            for value in values:
                same = math.isclose(value, pivot, rel_tol=1e-6, abs_tol=1e-6)
                counts[1 if same else 0 if value < pivot else 2] += 1
            return counts

        return _psi_from_counts(collapsed_hist(expected), collapsed_hist(actual))
    if len(edges) < 3:
        # A collapsed reference (every train score the same) still drifts
        # when the served mass sits somewhere else.
        mid = sum(value / len(expected) for value in expected)
        return _psi_from_counts(
            [
                sum(1 for value in expected if value <= mid),
                sum(1 for value in expected if value > mid),
            ],
            [
                sum(1 for value in actual if value <= mid),
                sum(1 for value in actual if value > mid),
            ],
        )

    def _hist(values: list[float]) -> list[int]:
        counts = [0] * (len(edges) - 1)
        last = len(counts) - 1
        for value in values:
            placed = False
            for index in range(last):
                if value <= edges[index + 1]:
                    counts[index] += 1
                    placed = True
                    break
            if not placed:
                counts[last] += 1
        return counts

    expected_hist = _hist([float(value) for value in expected])
    actual_hist = _hist([float(value) for value in actual])
    return _psi_from_counts(expected_hist, actual_hist)


def frequency_stability(expected: dict[str, int], actual: dict[str, int]) -> float | None:
    """PSI over two categorical frequency tables."""

    if sum(expected.values()) < MIN_PSI_SAMPLES or sum(actual.values()) < MIN_PSI_SAMPLES:
        return None
    keys = set(expected) | set(actual)
    expected_hist = [int(expected.get(key, 0)) for key in keys]
    actual_hist = [int(actual.get(key, 0)) for key in keys]
    return _psi_from_counts(expected_hist, actual_hist)


def _psi_from_counts(expected: list[int], actual: list[int]) -> float:
    n_expected = max(sum(expected), 1)
    n_actual = max(sum(actual), 1)
    total = 0.0
    for left, right in zip(expected, actual):
        pe = max(left / n_expected, 1e-4)
        pa = max(right / n_actual, 1e-4)
        total += (pa - pe) * math.log(pa / pe)
    return float(total)


def drift_status(value: float | None, *, ok: float = PSI_OK, watch: float = PSI_WATCH) -> str:
    if value is None:
        return "unknown"
    if value < ok:
        return "ok"
    if value < watch:
        return "watch"
    return "alert"


def worst_status(statuses: Iterable[str]) -> str:
    worst = "unknown"
    for status in statuses:
        if _STATUS_RANK.get(status, 0) > _STATUS_RANK.get(worst, 0):
            worst = status
    return worst


def rolling_auc(labels: list[str], scores: list[float], *, positive: str | None) -> float | None:
    """AUC on the annotated window, or None when the labels do not split."""

    if len(labels) < MIN_AUC_SAMPLES or len(labels) != len(scores):
        return None
    if positive is None:
        # Two distinct labels: the last in sort order, matching the harness.
        distinct = sorted({str(label) for label in labels})
        if len(distinct) != 2:
            return None
        positive = distinct[-1]
    y_true = [1 if str(label) == str(positive) else 0 for label in labels]
    if len(set(y_true)) < 2:
        return None
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(y_true, scores))
    except Exception:  # noqa: BLE001 - a missing score is not a failed read
        return None


# ---------------------------------------------------------------------------
# Journal projection
# ---------------------------------------------------------------------------


def _recent(
    db: DBSession, model: MLModel, *, limit: int = WINDOW_LIMIT, lineage: bool = False
) -> list[MLPrediction]:
    return (
        db.query(MLPrediction)
        .options(selectinload(MLPrediction.feedback_samples))
        .populate_existing()
        .filter(
            MLPrediction.workspace_id == model.workspace_id,
            MLPrediction.slug == model.slug if lineage else MLPrediction.served_id == model.id,
        )
        .order_by(MLPrediction.created_at.desc(), MLPrediction.id.desc())
        .limit(limit)
        .all()
    )


def _payload_values(rows: list[MLPrediction], feature: str) -> list[Any]:
    values: list[Any] = []
    for row in rows:
        payload = row.payload_json if isinstance(row.payload_json, list) else []
        for record in payload:
            if isinstance(record, dict) and feature in record:
                values.append(record[feature])
    return values


def _served_scores(rows: list[MLPrediction], *, confidence=False) -> list[float]:
    scores: list[float] = []
    for row in rows:
        block = row.scores_json if isinstance(row.scores_json, dict) else {}
        raw = block.get("scores") if isinstance(block.get("scores"), list) else []
        if confidence:
            raw = [
                item.get("confidence") for item in row.output_json or [] if isinstance(item, dict)
            ]
        for value in raw:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                number = float(value)
                if number == number and abs(number) != float("inf"):
                    scores.append(number)
    return scores


def _expected_numeric(stats: dict[str, Any]) -> list[float] | None:
    histogram = stats.get("histogram")
    if not isinstance(histogram, list) or not histogram:
        return None
    values: list[float] = []
    previous = stats.get("min")
    for bucket in histogram:
        if not isinstance(bucket, dict):
            continue
        upper = bucket.get("upper")
        count = int(bucket.get("count") or 0)
        if upper is None or count <= 0:
            continue
        try:
            top = float(upper)
            bottom = float(previous) if previous is not None else top
        except (TypeError, ValueError):
            continue
        mid = (bottom + top) / 2
        values.extend([mid] * min(count, 400))
        previous = top
    return values or None


def _expected_categorical(stats: dict[str, Any]) -> dict[str, int] | None:
    top = stats.get("top_values")
    if not isinstance(top, list) or not top:
        choices = stats.get("choices")
        if isinstance(choices, list) and choices:
            return {str(choice): 1 for choice in choices}
        return None
    counts: dict[str, int] = {}
    for bucket in top:
        if not isinstance(bucket, dict):
            continue
        value = bucket.get("value")
        if value is None:
            continue
        counts[str(value)] = int(bucket.get("count") or 0)
    return counts or None


def _feature_kind(stats: dict[str, Any], contract: dict[str, Any]) -> str:
    kind = str(stats.get("kind") or contract.get("kind") or "")
    if kind in NUMERIC_KINDS or kind == "number":
        return "number"
    if kind in {"string", "boolean", "category"} or contract.get("choices"):
        return "category"
    return kind or "unknown"


def _train_auc(model: MLModel) -> float | None:
    metrics = model.metrics_json if isinstance(model.metrics_json, dict) else {}
    primary = metrics.get("primary") if isinstance(metrics.get("primary"), dict) else {}
    if primary.get("key") == "roc_auc" and isinstance(primary.get("value"), (int, float)):
        return float(primary["value"])
    for score in metrics.get("scores") or []:
        if isinstance(score, dict) and score.get("key") == "roc_auc":
            raw = score.get("value")
            if isinstance(raw, (int, float)):
                return float(raw)
    return None


def _positive_label(model: MLModel) -> str | None:
    metrics = model.metrics_json if isinstance(model.metrics_json, dict) else {}
    target = metrics.get("target") if isinstance(metrics.get("target"), dict) else {}
    positive = target.get("positive")
    return str(positive) if positive is not None else None


def _labeled_pairs(rows: list[MLPrediction]) -> tuple[list[str], list[float]]:
    labels, scores = [], []
    for row in rows:
        for sample in iter_labeled_samples(row):
            number = finite_number(sample["score"])
            if number is not None:
                labels.append(str(sample["label"]))
                scores.append(number)
    return labels, scores


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def data_drift(
    model: MLModel, rows: list[MLPrediction], dataset: TabularDataset | None
) -> dict[str, Any]:
    if model.family == "external":
        # An imported model brings no training distribution, and its
        # importer-chosen validation rows are not one: no input drift is shown
        # rather than a drift measured against an arbitrary sample.
        return {"status": "unknown", "reason": "no_training_distribution", "features": []}
    stats = (
        dataset.stats_json if dataset is not None and isinstance(dataset.stats_json, dict) else {}
    )
    signature = model.signature_json if isinstance(model.signature_json, dict) else {}
    contract_fields = {
        str(field.get("name")): field
        for field in (signature.get("inputs") or [])
        if isinstance(field, dict) and field.get("name")
    }
    features: list[dict[str, Any]] = []
    reference = (model.metrics_json or {}).get("monitoring_reference") or {}
    reference_features = reference.get("features", {}) if reference.get("version") == 1 else {}
    for name in list(model.features or [])[:32]:
        column_stats = stats.get(name) if isinstance(stats.get(name), dict) else {}
        contract = contract_fields.get(name) or {}
        kind = _feature_kind(column_stats, contract)
        actual_values = _payload_values(rows, name)
        value = None
        if kind == "number":
            expected = _expected_numeric(column_stats)
            actual = [
                number for item in actual_values if (number := finite_number(item)) is not None
            ]
            value = population_stability(expected or [], actual) if expected else None
        else:
            expected_cat = _expected_categorical(column_stats) or _expected_categorical(contract)
            actual_cat = Counter(str(item) for item in actual_values if item is not None)
            value = frequency_stability(expected_cat, dict(actual_cat)) if expected_cat else None
        features.append(
            {
                "name": name,
                "kind": kind or "category",
                "value": None if value is None else round(value, 4),
                "status": drift_status(value),
                "psi_status": drift_status(value),
                "test": feature_test(reference_features.get(name), actual_values),
            }
        )
    adjust_tests([feature["test"] for feature in features])
    for feature in features:
        feature["status"] = worst_status([feature["psi_status"], feature["test"]["status"]])
    measured = [row["status"] for row in features if row["status"] != "unknown"]
    return {
        "status": worst_status(measured) if measured else "unknown",
        "features": features,
    }


def score_drift(rows: list[MLPrediction], model: MLModel | None = None) -> dict[str, Any]:
    reference = (
        (((model.metrics_json or {}).get("monitoring_reference") or {}).get("scores") or {})
        if model is not None
        else {}
    )
    scores = _served_scores(rows, confidence=reference.get("kind") == "confidence")
    if reference.get("source") == "final_test":
        values = reference.get("values") or []
        value = population_stability(values, scores)
        return {
            "status": drift_status(value),
            "value": round(value, 4) if value is not None else None,
            "served_mean": sum(value / len(scores) for value in scores) if scores else None,
            "reference_mean": reference.get("mean"),
            "n": len(scores),
            "reference_source": "final_test",
            "reference_n": reference.get("n", 0),
        }
    if len(scores) < MIN_PSI_SAMPLES * 2:
        return {
            "status": "unknown",
            "value": None,
            "served_mean": round(sum(value / len(scores) for value in scores), 4)
            if scores
            else None,
            "reference_mean": None,
            "n": len(scores),
            "reference_source": "previous_window",
        }
    split = max(MIN_PSI_SAMPLES, len(scores) // 2)
    # rows are newest-first, so the tail is the older window.
    recent = scores[:split]
    reference = scores[split:]
    value = population_stability(reference, recent)
    return {
        "status": drift_status(value),
        "value": None if value is None else round(value, 4),
        "served_mean": round(sum(value / len(recent) for value in recent), 4),
        "reference_mean": round(sum(value / len(reference) for value in reference), 4),
        "n": len(scores),
        "reference_source": "previous_window",
    }


def _metric(model, name):
    metrics = model.metrics_json or {}
    primary = metrics.get("primary") or {}
    entries = [primary, *(metrics.get("scores") or [])]
    value = next(
        (finite_number(entry.get("value")) for entry in entries if entry.get("key") == name), None
    )
    if value is None:
        value = finite_number(
            ((metrics.get("monitoring_reference") or {}).get("concept") or {}).get(name)
        )
    if (
        value is None
        and name == "f1_macro"
        and (metrics.get("metric_semantics") or {}).get("averaging") == "macro"
    ):
        value = next(
            (finite_number(entry.get("value")) for entry in entries if entry.get("key") == "f1"),
            None,
        )
    return value


def concept_drift(model: MLModel, rows: list[MLPrediction]) -> dict[str, Any]:
    classes = (
        (model.metrics_json or {}).get("target", {}).get("classes") or model.classes_json or []
    )
    if model.task != "regression" and len(classes) <= 2:
        labels, scores = _labeled_pairs(rows)
        auc = rolling_auc(labels, scores, positive=_positive_label(model))
        train = _train_auc(model)
        delta = None if auc is None or train is None else train - auc
        status = (
            "unknown"
            if delta is None
            else "alert"
            if delta >= AUC_ALERT
            else "watch"
            if delta >= AUC_WATCH
            else "ok"
        )
        return {
            "status": status,
            "metric": "roc_auc",
            "rolling_auc": auc,
            "train_auc": train,
            "value": auc,
            "reference": train,
            "delta": delta,
            "labeled": len(labels),
        }
    samples = [value for row in rows for value in iter_labeled_samples(row)]
    measured = []
    for sample in samples:
        predicted = sample["output"].get("prediction")
        actual = sample["label"]
        if model.task == "regression":
            actual, predicted = _feedback_number(actual), _feedback_number(predicted)
            if actual is None or predicted is None:
                continue
        elif predicted is None:
            continue
        measured.append((actual, predicted))
    metrics = []
    if len(measured) >= MIN_AUC_SAMPLES:
        if model.task == "regression":
            errors = [float(actual) - float(predicted) for actual, predicted in measured]
            if not all(math.isfinite(value) for value in errors):
                return {
                    "status": "unknown",
                    "metric": "mae",
                    "value": None,
                    "reference": _metric(model, "mae"),
                    "delta": None,
                    "labeled": len(measured),
                    "metrics": [],
                    "rolling_auc": None,
                    "train_auc": None,
                    "reason": "numeric_range_exceeded",
                }
            values = {
                "mae": sum(abs(v) / len(errors) for v in errors),
                "rmse": math.hypot(*(v / math.sqrt(len(errors)) for v in errors)),
            }
            watch, alert = (
                float(getattr(settings, "ml_concept_regression_watch", 0.10)),
                float(getattr(settings, "ml_concept_regression_alert", 0.25)),
            )
            for name, value in values.items():
                reference = _metric(model, name)
                delta = (
                    None
                    if reference is None
                    else (value - reference) / reference
                    if reference > 0
                    else (0.0 if value == 0 else None)
                )
                # Positive error against a perfect reference is an alert; keep
                # JSON finite and explicitly state that the ratio is undefined.
                status = (
                    "unknown"
                    if reference is None
                    else "alert"
                    if reference == 0 and value > 0 or delta is not None and delta >= alert
                    else "watch"
                    if delta is not None and delta >= watch
                    else "ok"
                )
                metrics.append(
                    {
                        "metric": name,
                        "value": value,
                        "reference": reference,
                        "delta": delta,
                        "status": status,
                        "delta_kind": "relative",
                    }
                )
        else:
            pairs = [(str(a), str(p)) for a, p in measured]
            universe = sorted(
                set(map(str, classes)) | {a for a, _ in pairs} | {p for _, p in pairs}
            )
            f1 = []
            for label in universe:
                tp = sum(a == p == label for a, p in pairs)
                fp = sum(p == label and a != label for a, p in pairs)
                fn = sum(a == label and p != label for a, p in pairs)
                f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
            values = {
                "accuracy": sum(a == p for a, p in pairs) / len(pairs),
                "f1_macro": sum(f1) / len(f1),
            }
            watch, alert = (
                float(getattr(settings, "ml_concept_multiclass_watch", 0.02)),
                float(getattr(settings, "ml_concept_multiclass_alert", 0.05)),
            )
            for name, value in values.items():
                reference = _metric(model, name)
                delta = None if reference is None else reference - value
                status = (
                    "unknown"
                    if delta is None
                    else "alert"
                    if delta >= alert
                    else "watch"
                    if delta >= watch
                    else "ok"
                )
                metrics.append(
                    {
                        "metric": name,
                        "value": value,
                        "reference": reference,
                        "delta": delta,
                        "status": status,
                        "delta_kind": "absolute",
                    }
                )
    first = metrics[0] if metrics else {}
    return {
        "status": worst_status(value["status"] for value in metrics),
        "metric": first.get("metric"),
        "value": first.get("value"),
        "reference": first.get("reference"),
        "delta": first.get("delta"),
        "labeled": len(measured),
        "metrics": metrics,
        "rolling_auc": None,
        "train_auc": None,
    }


def report(db: DBSession, *, model: MLModel) -> dict[str, Any]:
    """The Monitoring tab's read model, computed on the request."""

    from app.services.ml_retraining import monitoring_view
    from app.services.ml_shadow import summary as shadow_summary

    if model.task == "forecasting":
        from app.services.ml.forecast_monitoring import report as forecast_report

        actuals = forecast_report(db, model=model)
        status = actuals["status"]
        return {
            "badge": status if status in {"ok", "watch", "alert"} else None,
            "window": {
                "predictions": actuals["window"].get("calls", 0),
                "labeled": actuals["overall"]["count"],
                "limit": WINDOW_LIMIT,
                "model_id": model.id,
                "served_version": model.version,
            },
            "data_drift": {"status": "unknown", "features": []},
            "score_drift": score_drift([]),
            "concept_drift": concept_drift(model, []),
            "scheduled": monitoring_view(db, model),
            "shadow": shadow_summary(db, model=model),
            "forecast_actuals": actuals,
        }

    rows = _recent(db, model)
    dataset = (
        db.query(TabularDataset)
        .filter(
            TabularDataset.id == model.dataset_id, TabularDataset.workspace_id == model.workspace_id
        )
        .first()
        if model.dataset_id
        else None
    )
    data = data_drift(model, rows, dataset)
    scores = score_drift(rows, model)
    concept = concept_drift(model, rows)
    labeled = sum(1 for row in rows for _ in iter_labeled_samples(row))
    badge = worst_status(
        status
        for status in (data["status"], scores["status"], concept["status"])
        if status != "unknown"
    )
    if not rows:
        badge = None
    elif badge == "unknown":
        badge = "ok"
    return {
        "badge": badge,
        "window": {
            "predictions": len(rows),
            "labeled": labeled,
            "limit": WINDOW_LIMIT,
            "model_id": model.id,
            "served_version": model.version,
        },
        "data_drift": data,
        "score_drift": scores,
        "concept_drift": concept,
        "scheduled": monitoring_view(db, model),
        "shadow": shadow_summary(db, model=model),
    }


def badges_for(db: DBSession, models: list[MLModel]) -> dict[str, str | None]:
    """One badge per served version, using a bounded window for each model."""

    if not models:
        return {}
    model_ids = {row.id for row in models}
    ranked = (
        db.query(
            MLPrediction.id,
            func.row_number()
            .over(
                partition_by=MLPrediction.served_id,
                order_by=(MLPrediction.created_at.desc(), MLPrediction.id.desc()),
            )
            .label("position"),
        )
        .filter(
            MLPrediction.served_id.in_(list(model_ids)),
            MLPrediction.workspace_id.in_({model.workspace_id for model in models}),
        )
        .subquery()
    )
    rows = (
        db.query(MLPrediction)
        .join(ranked, ranked.c.id == MLPrediction.id)
        .filter(ranked.c.position <= WINDOW_LIMIT)
        .order_by(MLPrediction.created_at.desc(), MLPrediction.id.desc())
        .all()
    )
    by_model: dict[str, list[MLPrediction]] = {}
    for row in rows:
        bucket = by_model.setdefault(row.served_id, [])
        if len(bucket) < WINDOW_LIMIT:
            bucket.append(row)
    dataset_ids = {model.dataset_id for model in models if model.dataset_id}
    datasets = {
        row.id: row
        for row in (
            db.query(TabularDataset).filter(TabularDataset.id.in_(list(dataset_ids))).all()
            if dataset_ids
            else []
        )
    }
    badges: dict[str, str | None] = {}
    for model in models:
        if model.task == "forecasting":
            from app.services.ml.forecast_monitoring import snapshot

            try:
                state = snapshot(db, model=model).report["status"]
            except TabularError:
                state = "unknown"
            badges[model.id] = state if state in {"ok", "watch", "alert"} else None
            continue
        window = [
            row for row in by_model.get(model.id, []) if row.workspace_id == model.workspace_id
        ]
        if not window:
            badges[model.id] = None
            continue
        dataset = datasets.get(model.dataset_id)
        data = data_drift(
            model,
            window,
            dataset if dataset is not None and dataset.workspace_id == model.workspace_id else None,
        )
        scores = score_drift(window, model)
        concept = concept_drift(model, window)
        badge = worst_status(
            status
            for status in (data["status"], scores["status"], concept["status"])
            if status != "unknown"
        )
        badges[model.id] = "ok" if badge == "unknown" else badge
    return badges


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


def get_prediction(db: DBSession, *, prediction_id: str, workspace_id: str) -> MLPrediction:
    row = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.id == prediction_id,
            MLPrediction.workspace_id == workspace_id,
        )
        .first()
    )
    if row is None:
        raise TabularError(
            code="ML_PREDICTION_NOT_FOUND",
            message="That prediction is not in this workspace.",
            status_code=404,
            details={"prediction_id": prediction_id},
        )
    return row


def attach_feedback(
    db: DBSession,
    *,
    model: MLModel,
    prediction_id: str,
    label: Any,
    labeled_by: str | None = None,
    sample_id: str | None = None,
) -> MLPrediction:
    from app.services.ml_feedback import attach

    _require_feedback_task(model)
    return attach(
        db,
        model=model,
        prediction_id=prediction_id,
        label=label,
        labeled_by=labeled_by,
        sample_id=sample_id,
    )


def _require_feedback_task(model: MLModel) -> None:
    if model.task == "clustering":
        raise TabularError(
            code="ML_CLUSTER_FEEDBACK_UNSUPPORTED",
            message="Cluster identifiers are not ground-truth labels.",
            status_code=409,
        )


def _feedback_number(label: Any) -> float | None:
    """Share validation with legacy feedback materialization, including NaN/inf."""

    try:
        number = float(str(label).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def serialize_prediction(row: MLPrediction) -> dict[str, Any]:
    return {
        "id": row.id,
        "served_id": row.served_id,
        "served_version": int(row.served_version or 1),
        "caller": row.caller,
        "row_count": int(row.row_count or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "label": row.label,
        "labeled_at": row.labeled_at.isoformat() if row.labeled_at else None,
        "dataset_id": row.dataset_id,
        "samples": samples_metadata(row),
    }


def materialize_labeled(
    db: DBSession, *, model: MLModel, created_by: str | None = None
) -> TabularDataset:
    """Turn annotated journal rows into a dataset the studio can retrain on.

    Each explicitly labelled persisted sample contributes its own ground truth
    under the model's target name. That is the feedback → dataset hop; retrain
    and promote stay the same buttons they already are.
    """

    _require_feedback_task(model)
    rows = _recent(db, model, limit=WINDOW_LIMIT, lineage=True)
    records = []
    for row in rows:
        for sample in iter_labeled_samples(row):
            label = (
                _feedback_number(sample["label"]) if model.task == "regression" else sample["label"]
            )
            if label is not None:
                records.append({**sample["payload"], str(model.target): label})
    if len(records) < MIN_MATERIALIZE:
        raise TabularError(
            code="ML_FEEDBACK_TOO_FEW",
            message=(
                f"Need at least {MIN_MATERIALIZE} labeled predictions to "
                f"build a dataset, have {len(records)}."
            ),
            status_code=409,
            details={"labeled": len(records), "need": MIN_MATERIALIZE},
        )
    import polars as pl

    frame = pl.DataFrame(records)
    dataset = register_frame(
        db,
        workspace_id=model.workspace_id,
        name=f"{model.name} · feedback",
        frame=frame,
        source="generated",
        produced_by="ml_feedback",
        parent_ids=[model.dataset_id] if model.dataset_id else [],
        created_by=created_by,
        lineage={
            "kind": "feedback",
            "model": {
                "model_id": model.id,
                "slug": model.slug,
                "version": int(model.version or 1),
            },
            "labeled": len(records),
            "skipped": max(
                0,
                sum(
                    int(row.row_count or 0)
                    if row.label is not None
                    else len(list(iter_labeled_samples(row)))
                    for row in rows
                )
                - len(records),
            ),
        },
    )
    db.commit()
    return dataset


__all__ = [
    "attach_feedback",
    "badges_for",
    "concept_drift",
    "data_drift",
    "drift_status",
    "frequency_stability",
    "get_prediction",
    "materialize_labeled",
    "population_stability",
    "report",
    "rolling_auc",
    "score_drift",
    "serialize_prediction",
    "worst_status",
]
