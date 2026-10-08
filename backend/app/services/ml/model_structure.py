"""Lightweight structural access without importing sklearn in the API."""
from __future__ import annotations


def inner_pipeline(model):
    """Unwrap our sklearn postprocessing only, keeping fitted estimators first.

    Predictions and explanations must still call the outer served model. This
    helper is for structural inspection such as transformed feature names.
    """
    seen = set()
    wrappers = {"FixedThresholdClassifier", "CalibratedClassifierCV", "FrozenEstimator"}
    while type(model).__name__ in wrappers and id(model) not in seen:
        seen.add(id(model))
        model = getattr(model, "estimator_", None) or getattr(model, "estimator", model)
    return model
