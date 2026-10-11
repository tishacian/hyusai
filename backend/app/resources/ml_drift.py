"""Bounded training references and two-sample drift tests.

No scientific dependency is imported by merely importing this module in the API.
References contain train rows only; histogram midpoints are never KS samples.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import math
from numbers import Real

REFERENCE_LIMIT = 400
FEATURE_LIMIT = 32
CATEGORY_LIMIT = 100
MIN_SAMPLES = 20


def finite_number(value):
    if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def category_key(value):
    # Hash the complete category; do not persist text excerpts in model metrics.
    if value is None or (isinstance(value, Real) and not math.isfinite(value)):
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def build_reference(frame, *, seed=42):
    """Called by the training harness on X_train, before any held-out evidence."""
    from pandas.api.types import is_bool_dtype, is_numeric_dtype, is_string_dtype

    sample = frame.sample(n=min(len(frame), REFERENCE_LIMIT), random_state=seed)
    features = {}
    for name in list(frame.columns)[:FEATURE_LIMIT]:
        series = sample[name].dropna()
        if is_numeric_dtype(series.dtype) and not is_bool_dtype(series.dtype):
            values = [number for value in series.tolist() if (number := finite_number(value)) is not None]
            features[str(name)] = {"kind": "number", "n": len(values), "values": values}
        elif is_bool_dtype(series.dtype) or is_string_dtype(series.dtype) or str(series.dtype) == "category":
            counts = Counter(key for value in series.tolist() if (key := category_key(value)) is not None)
            features[str(name)] = {"kind": "category", "n": sum(counts.values()),
                                   "counts": dict(counts) if len(counts) <= CATEGORY_LIMIT else {},
                                   "reason": "high_cardinality" if len(counts) > CATEGORY_LIMIT else None}
        else:
            features[str(name)] = {"kind": "unknown", "n": len(series), "reason": "unsupported_type"}
    return {"version": 1, "source": "train", "sampling": "uniform_without_replacement",
            "limit": REFERENCE_LIMIT, "train_rows": len(frame), "features": features}


def feature_test(reference, values):
    """Return an unavailable result when test assumptions are not satisfied."""
    ref = reference if isinstance(reference, dict) else {}
    kind = ref.get("kind")
    result = {"method": {"number": "ks", "category": "chi2"}.get(kind),
              "status": "unknown", "statistic": None, "p_value": None,
              "p_value_adjusted": None, "n_reference": ref.get("n", 0),
              "n_current": 0, "reason": None}
    if not ref:
        return {**result, "reason": "reference_unavailable"}
    if kind == "number":
        actual = [number for value in values[:REFERENCE_LIMIT]
                  if (number := finite_number(value)) is not None]
        expected = [number for value in (ref.get("values") or [])[:REFERENCE_LIMIT]
                    if (number := finite_number(value)) is not None]
        result.update(n_reference=len(expected), n_current=len(actual))
        if min(len(expected), len(actual)) < MIN_SAMPLES:
            return {**result, "reason": "insufficient_samples"}
        from scipy.stats import ks_2samp

        measured = ks_2samp(expected, actual, alternative="two-sided", method="auto")
    elif kind == "category":
        actual = Counter(key for value in values[:REFERENCE_LIMIT] if (key := category_key(value)) is not None)
        expected = ref.get("counts") or {}
        result["n_current"] = sum(actual.values())
        if ref.get("reason") or len(set(expected) | set(actual)) > CATEGORY_LIMIT:
            return {**result, "reason": ref.get("reason") or "high_cardinality"}
        result["n_reference"] = sum(expected.values())
        if min(result["n_reference"], result["n_current"]) < MIN_SAMPLES:
            return {**result, "reason": "insufficient_samples"}
        keys = sorted(set(expected) | set(actual))
        if len(keys) < 2:
            return {**result, "reason": "sparse_categories"}
        from scipy.stats import chi2_contingency

        measured = chi2_contingency([[expected.get(key, 0) for key in keys],
                                    [actual.get(key, 0) for key in keys]], correction=False)
        # Pearson's asymptotic approximation requires adequate expected counts.
        if (measured.expected_freq < 5).any():
            return {**result, "reason": "sparse_categories"}
    else:
        return {**result, "reason": "unsupported_type"}
    statistic, p = float(measured.statistic), float(measured.pvalue)
    if not math.isfinite(statistic) or not math.isfinite(p):
        return {**result, "reason": "insufficient_samples"}
    return {**result, "statistic": statistic, "p_value": p}


def adjust_tests(tests):
    """Holm controls family-wise error across this report's testable features."""
    available = sorted((test for test in tests if test["p_value"] is not None), key=lambda test: test["p_value"])
    previous = 0.0
    for index, test in enumerate(available):
        adjusted = min(1.0, max(previous, test["p_value"] * (len(available) - index)))
        previous = adjusted
        test["p_value_adjusted"] = adjusted
        test["status"] = "alert" if adjusted < .01 else "watch" if adjusted < .05 else "ok"
