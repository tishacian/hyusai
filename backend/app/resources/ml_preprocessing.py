"""Bounded evidence from the fitted skrub pipeline, with no data values.

This sibling of the training harness uses public fitted TableVectorizer attributes.
It never fits or transforms data to describe a model. Input metadata is recorded
once on the fitted vectorizer and travels through its existing skops artifact.
"""

from __future__ import annotations

import json
from importlib.metadata import version

MAX_COLUMNS = 64
MAX_BYTES = 65_536
_MAX_LABEL = 160
_MAX_TRANSFORMERS = 8


def _inner_pipeline(model):
    seen = set()
    wrappers = {"FixedThresholdClassifier", "CalibratedClassifierCV", "FrozenEstimator"}
    while type(model).__name__ in wrappers and id(model) not in seen:
        seen.add(id(model))
        model = getattr(model, "estimator_", None) or getattr(model, "estimator", model)
    return model


def _qualified(value):
    return f"{type(value).__module__}.{type(value).__name__}"[:_MAX_LABEL]


def _transformer_names(steps):
    names = []
    for step in steps:
        # skrub's final per-output conversions are a mapping whose keys may
        # contain category values. Only their transformer classes are exposed.
        candidates = step.values() if isinstance(step, dict) else (step,)
        for candidate in candidates:
            name = _qualified(candidate)
            if name not in names:
                names.append(name)
            if len(names) == _MAX_TRANSFORMERS:
                return names
    return names


def learned_columns(model):
    """Full input names for internal contracts; the public summary is bounded."""
    pipeline = _inner_pipeline(model)
    vectorizer = getattr(pipeline, "named_steps", {}).get("tablevectorizer")
    if vectorizer is None or not hasattr(vectorizer, "all_outputs_"):
        return [], []
    outputs = set(vectorizer.all_outputs_)
    reasons = getattr(vectorizer, "_agentium_exclusion_reasons_", {})
    used, dropped = [], []
    for name in vectorizer.feature_names_in_:
        if outputs.intersection(vectorizer.input_to_outputs_.get(name, ())):
            used.append(str(name))
        else:
            dropped.append({"name": str(name), "reason": reasons.get(str(name), "uninformative")})
    return used, dropped


def record_fitted(model, inputs, *, fit_time_ms, fit_rows=None):
    """Record train-only metadata after fitting, without changing learned choices.

    ``fit_time_ms`` measures the complete fit stage (including requested calibration
    and threshold selection); it is not presented as preprocessing-only telemetry.
    """
    pipeline = _inner_pipeline(model)
    vectorizer = getattr(pipeline, "named_steps", {}).get("tablevectorizer")
    if vectorizer is None:
        return describe(model)
    vectorizer._agentium_input_dtypes_ = {
        str(name): str(inputs[name].dtype)[:_MAX_LABEL] for name in vectorizer.feature_names_in_
    }
    _, dropped = learned_columns(model)
    reasons = {}
    for entry in dropped:
        column = inputs[entry["name"]]
        reasons[entry["name"]] = (
            "all_missing"
            if column.isna().all()
            else "constant"
            if column.nunique(dropna=False) == 1
            else "uninformative"
        )
    vectorizer._agentium_exclusion_reasons_ = reasons
    vectorizer._agentium_fit_time_ms_ = round(float(fit_time_ms), 1)
    vectorizer._agentium_fit_rows_ = int(fit_rows if fit_rows is not None else len(inputs))
    # Keep producer versions in the artifact; inspecting an older model must
    # not mislabel it with the reader's currently installed versions.
    vectorizer._agentium_versions_ = {
        name: version(name) for name in ("skrub", "scikit-learn", "pandas", "numpy")
    }
    return describe(model)


def describe(model):
    """Return the same structural evidence before and after artifact reload."""
    pipeline = _inner_pipeline(model)
    vectorizer = getattr(pipeline, "named_steps", {}).get("tablevectorizer")
    if vectorizer is None or not hasattr(vectorizer, "all_outputs_"):
        return {"schema": 1, "status": "unavailable", "reason": "fitted_vectorizer_missing"}
    outputs = set(vectorizer.all_outputs_)
    used, dropped = learned_columns(model)
    reasons = {entry["name"]: entry["reason"] for entry in dropped}
    dtypes = getattr(vectorizer, "_agentium_input_dtypes_", {})
    names = list(vectorizer.feature_names_in_)
    columns = []
    for name in names[:MAX_COLUMNS]:
        count = len(outputs.intersection(vectorizer.input_to_outputs_.get(name, ())))
        columns.append(
            {
                "name": str(name)[:_MAX_LABEL],
                "input_dtype": dtypes.get(str(name)),
                "kind": vectorizer.column_to_kind_.get(name),
                "transformers": _transformer_names(vectorizer.all_processing_steps_.get(name, ())),
                "output_count": count,
                "excluded": count == 0,
                "reason": reasons.get(str(name)),
            }
        )
    final_estimator = pipeline.steps[-1][1]
    result = {
        "schema": 1,
        "status": "available",
        "learning_scope": "training_folds",
        "constant_selection": "fitted_table_vectorizer",
        "versions": getattr(vectorizer, "_agentium_versions_", {}),
        "input_count": len(names),
        "retained_count": len(used),
        "excluded_count": len(dropped),
        "vectorized_count": len(vectorizer.all_outputs_),
        "output_count": int(final_estimator.n_features_in_)
        if hasattr(final_estimator, "n_features_in_")
        else None,
        "fit_rows": getattr(vectorizer, "_agentium_fit_rows_", None),
        "fit_time_ms": getattr(vectorizer, "_agentium_fit_time_ms_", None),
        "preprocessing_time_ms": None,
        "steps": [_qualified(step) for _, step in pipeline.steps[:-1]][:_MAX_TRANSFORMERS],
        "columns": columns,
        "truncated": len(names) > len(columns)
        or any(len(str(name)) > _MAX_LABEL for name in names),
    }
    while len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_BYTES and columns:
        columns.pop()
        result["truncated"] = True
    return result
