"""Bounded, numeric KMeans segmentation without a supervised target or split."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.ml.families.base import Family

CLUSTERING = "clustering"
MAX_ROWS = 50_000
MAX_FEATURES = 50


def _refuse(code: str, message: str, **details: Any):
    from app.services.tabular_datasets import TabularError

    return TabularError(code=code, message=message, details=details or None)


def validate_clustering(dataset: Any, *, task: str, target: str, features: Any, algo: Any,
                        knobs: Any, test_size: Any, cross_validation: Any, name: Any,
                        spec: dict[str, Any]):
    from app.services.tabular_datasets import NUMERIC_KINDS
    from app.services.tabular_ml import ALGO_BY_KEY, TrainingSpec

    if target:
        raise _refuse("ML_CLUSTER_TARGET_UNSUPPORTED", "Segmentation has no target column.", field="target")
    if cross_validation not in (None, 0) or isinstance(cross_validation, bool):
        raise _refuse("ML_CLUSTER_OPTION_UNSUPPORTED", "Segmentation uses all rows without cross-validation.",
                      field="cross_validation")
    # Older shared forms send the supervised default even when no split is
    # shown. Normalize that neutral default; refuse an explicitly changed split.
    if test_size not in (None, 0, 0.25) or isinstance(test_size, bool):
        raise _refuse("ML_CLUSTER_OPTION_UNSUPPORTED", "Segmentation fits all rows without a test split.",
                      field="test_size")
    algo_key = str(algo or "").strip() or "kmeans"
    resolved = ALGO_BY_KEY.get(algo_key)
    if resolved is None:
        raise _refuse("ML_ALGO_UNKNOWN", "Choose an offered segmentation algorithm.", algo=algo_key)
    if not resolved.supports(CLUSTERING):
        raise _refuse("ML_ALGO_TASK_MISMATCH", "This algorithm does not segment rows.", algo=algo_key, task=task)
    if knobs is not None and not isinstance(knobs, dict):
        raise _refuse("ML_CLUSTER_KNOB_INVALID", "Segmentation settings must be an object.", field="knobs")
    chosen = knobs or {}
    known = {knob.key: knob for knob in resolved.knobs}
    for key, value in chosen.items():
        knob = known.get(key)
        if (knob is None or isinstance(value, bool) or not isinstance(value, (int, float))
                or not knob.minimum <= value <= knob.maximum or value != int(value)):
            raise _refuse("ML_CLUSTER_KNOB_INVALID", "Choose a whole-number setting within the offered bounds.",
                          field=key)
    params = resolved.resolve(chosen)
    rows = int(dataset.row_count or 0)
    minimum = max(int(settings.ml_train_min_rows), 2 * params["n_clusters"])
    maximum = min(int(settings.ml_train_max_rows), MAX_ROWS)
    if rows < minimum:
        raise _refuse("ML_ROWS_INSUFFICIENT", f"Segmentation requires at least {minimum:,} rows.",
                      rows=rows, min_rows=minimum)
    if rows > maximum:
        raise _refuse("ML_ROWS_TOO_MANY", f"Segmentation supports at most {maximum:,} rows.",
                      rows=rows, max_rows=maximum)
    if not isinstance(features, list) or not features or not all(isinstance(item, str) and item for item in features):
        raise _refuse("ML_FEATURES_REQUIRED", "Choose numeric columns to segment.", field="features")
    selected = list(dict.fromkeys(features))
    maximum_features = min(int(settings.ml_train_max_features), MAX_FEATURES)
    if len(selected) > maximum_features:
        raise _refuse("ML_TOO_MANY_FEATURES", f"Choose at most {maximum_features} numeric columns.",
                      max_features=maximum_features)
    kinds = {str(column.get("name")): column.get("kind") for column in dataset.schema_json or []}
    for column in selected:
        if column not in kinds:
            raise _refuse("ML_FEATURE_UNKNOWN", f"'{column}' is not a column of this dataset.", features=[column])
        if kinds[column] not in NUMERIC_KINDS:
            raise _refuse("ML_CLUSTER_FEATURE_NOT_NUMERIC", f"'{column}' must be numeric for segmentation.",
                          field="features", features=[column])
        profile = (dataset.stats_json or {}).get(column) or {}
        if int(profile.get("nulls") or 0) >= rows:
            raise _refuse("ML_CLUSTER_DATA_UNUSABLE", f"'{column}' has no observed numeric values.", features=[column])
    return TrainingSpec(dataset=dataset, task=CLUSTERING, target="", features=selected, algo=resolved,
                        knobs=params, test_size=0.0, cross_validation=0,
                        name=(str(name or "").strip() or f"{dataset.name} · segments")[:200],
                        warnings=[], family=CLUSTERING, spec=spec)


CLUSTERING_FAMILY = Family(
    key=CLUSTERING, tasks=(CLUSTERING,), runtime="worker", queue_setting="celery_ml_tabular_queue",
    serving="in_process", required_modules=("sklearn", "mlflow", "skops"),
    harness=Path(__file__).resolve().parents[3] / "resources" / "ml_clustering_harness.py",
    steps=("queued", "reading", "fitting", "scoring", "validating", "saving"),
    exit_codes={2: "ML_CLUSTER_DATA_UNUSABLE"}, validator=validate_clustering,
)
