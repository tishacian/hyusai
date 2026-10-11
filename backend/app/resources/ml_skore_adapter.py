"""Read Skore metrics into the existing Hyusai contracts, without I/O.

Shared by standalone training harnesses and the comparison API. This module
owns the public display-API boundary, not evaluation, persistence or model
selection. No Skore Project/Hub or additional artifact store is involved.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping


def _frame(display):
    """Request machine-readable names and reject ambiguous metric indices."""
    frame = display.frame(verbose_name=False, flat_index=True, aggregate=("mean", "std"))
    if frame.index.nlevels != 1 or not frame.index.is_unique:
        raise ValueError("Unexpected Skore metric index: expected unique flat keys")
    if not all(isinstance(key, str) for key in frame.index):
        raise ValueError("Unexpected Skore metric index: expected string keys")
    return frame


def _number(value, *, rounded: bool = True) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 6) if rounded else number


def estimator_metrics(display) -> dict[str, float | None]:
    """Return the model card's six-decimal metric values from one estimator."""
    frame = _frame(display)
    if hasattr(frame, "columns"):
        if frame.shape[1] != 1:
            raise ValueError("Expected exactly one Skore estimator metric column")
        frame = frame.iloc[:, 0]
    # Since 0.27, summarize() includes the estimator's opaque .score() as well.
    # Hyusai's existing contract uses explicit named metrics, not default_score.
    return {key: _number(value) for key, value in frame.items() if key != "default_score"}


def cross_validation_metrics(display, *, keys: Collection[str]) -> list[dict]:
    """Return the existing CV rows, including Hyusai's percent-valued MAPE."""
    frame = _frame(display)
    if not hasattr(frame, "columns") or not frame.columns.is_unique:
        raise ValueError("Expected Skore cross-validation mean/std columns")
    means = [key for key in frame.columns if isinstance(key, str) and key.endswith("_mean")]
    if len(means) != 1 or set(frame.columns) != {means[0], means[0][:-5] + "_std"}:
        raise ValueError("Expected one matching pair of Skore mean/std columns")
    mean_key, std_key = means[0], means[0][:-5] + "_std"
    rows = []
    for key in frame.index:
        if key not in keys:
            continue
        mean, spread = _number(frame.loc[key, mean_key]), _number(frame.loc[key, std_key])
        if key == "mape":
            mean = None if mean is None else _number(mean * 100)
            spread = None if spread is None else _number(spread * 100)
        if mean is not None:
            rows.append({"key": key, "mean": mean, "std": spread})
    return rows


def comparison_metrics(display, *, names: Mapping[str, str]) -> list[dict]:
    """Return API comparison rows keyed by model IDs, preserving precision."""
    frame = _frame(display)
    if (
        not hasattr(frame, "columns")
        or not frame.columns.is_unique
        or len(set(names.values())) != len(names)
        or set(frame.columns) != set(names.values())
    ):
        raise ValueError("Skore comparison columns do not match the requested models")

    def value(key, name):
        number = _number(frame.loc[key, name], rounded=False)
        return (
            _number(number * 100, rounded=False) if key == "mape" and number is not None else number
        )

    return [
        {
            "key": key,
            **{model_id: value(key, name) for model_id, name in names.items()},
        }
        for key in frame.index
        if not key.endswith("_time") and key != "default_score"
    ]
