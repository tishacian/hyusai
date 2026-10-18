"""Exact TreeSHAP for one served tabular row, computed where ``shap`` lives.

``shap`` is installed in the ml-ts image only (it already explains forecasts
there) and stays out of the API and general-worker images. So an explanation
by Shapley values crosses the broker the way a forecast does:

* **the API side** (:func:`explain_served_row`) decides from the loaded
  pipeline whether its final estimator is a tree ensemble TreeExplainer reads
  exactly (class names only — nothing here imports ``shap``), checks that an
  ml-ts RPC consumer is alive and can read this artifact, sends one
  ``agentium.ml_tree_shap`` task and waits at most ``ML_EXPLAIN_TIMEOUT_S``.
  Every way this can fail is a *reason*, returned so the caller answers with
  the counterfactual instead; only an explicit ``explain_method="shap"`` turns
  a reason into a 409.
* **the worker side** (:func:`answer_for`) loads the model through the normal
  verified path (``load_pipeline_traced`` → ``verify_model_bundle``),
  transforms the row with the pipeline's own preprocessing, explains the final
  estimator, and sums the Shapley values of every output column back onto the
  input field that produced it. A sum over a group of features preserves
  additivity, so ``base + Σ contributions`` is still the model's output.

What is explained is the estimator's own output space, stated on the answer:
a forest's class probability, a boosting model's log-odds (binary) or class
raw score (multiclass, before the softmax), a regressor's value.

Two places where ``shap.TreeExplainer`` cannot be handed the estimator as is,
both verified against the estimator's own output by the additivity gap:

* ``HistGradientBoosting*`` — shap 0.52 reads only numeric thresholds (a
  categorical bitset split would be read as a threshold) and ignores the
  estimator's internal ``_preprocessor``, which reorders categorical columns
  first. Path-dependent TreeSHAP only reads the explained row to choose which
  child of a split the row follows, so each tree is rebuilt *for this row*:
  every categorical split becomes the branch the row really takes under
  sklearn's own rule, and the trees are given to TreeExplainer in its
  documented dictionary form. The algorithm, and its exactness, are shap's.
* multiclass ``GradientBoostingClassifier`` — not parsed by shap; its
  per-class trees are given in the same dictionary form.

Nothing heavy is imported at module scope: the API imports this module.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from contextlib import suppress
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.tabular_datasets import TabularError

logger = get_logger(__name__)

TASK = "agentium.ml_tree_shap"
METHODS = ("auto", "shap", "counterfactual")

# Final estimators whose trees TreeExplainer reads exactly, by class name and
# only from scikit-learn: the harness never fits anything else.
TREE_ESTIMATORS = frozenset(
    {
        "DecisionTreeClassifier",
        "DecisionTreeRegressor",
        "RandomForestClassifier",
        "RandomForestRegressor",
        "ExtraTreesClassifier",
        "ExtraTreesRegressor",
        "GradientBoostingClassifier",
        "GradientBoostingRegressor",
        "HistGradientBoostingClassifier",
        "HistGradientBoostingRegressor",
    }
)
# HistGradientBoostingRegressor losses whose raw prediction *is* the value.
# A log-link loss (poisson, gamma) would explain log(value): not offered.
_IDENTITY_LOSSES = frozenset({"squared_error", "absolute_error", "quantile"})
_WRAPPERS = frozenset({"FixedThresholdClassifier", "CalibratedClassifierCV", "FrozenEstimator"})


# ---------------------------------------------------------------------------
# Shared: what the served pipeline is
# ---------------------------------------------------------------------------


def tree_pipeline(pipeline: Any) -> tuple[Any | None, str | None]:
    """The inner sklearn Pipeline whose last step is a supported tree, or why not.

    A decision threshold (``FixedThresholdClassifier``) only changes which label
    a probability selects, so its probabilities are the inner model's and the
    explanation stands. A calibrator does not: the served probability is a
    function of several fold models' outputs, which no tree explains, so a
    calibrated model keeps the counterfactual.
    """

    seen: set[int] = set()
    model = pipeline
    while type(model).__name__ in _WRAPPERS and id(model) not in seen:
        if type(model).__name__ == "CalibratedClassifierCV":
            return None, "calibrated_model"
        seen.add(id(model))
        model = getattr(model, "estimator_", None) or getattr(model, "estimator", model)
    steps = getattr(model, "steps", None)
    if not steps:
        return None, "not_a_tree_model"
    final = steps[-1][1]
    name = type(final).__name__
    if name not in TREE_ESTIMATORS or not type(final).__module__.startswith("sklearn."):
        return None, "not_a_tree_model"
    if name == "HistGradientBoostingRegressor" and str(getattr(final, "loss", "")) not in (
        _IDENTITY_LOSSES
    ):
        return None, "unsupported_tree"
    return model, None


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------

_explainers: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_explainers_lock = threading.Lock()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    number = _number(value)
    return round(number, 6) if number is not None else str(value)[:200]


def _vectorizer(inner: Any) -> Any | None:
    for _, step in inner.steps[:-1]:
        if hasattr(step, "output_to_input_"):
            return step
    return None


def _output_names(inner: Any, width: int) -> list[str]:
    transform = inner[:-1]
    try:
        names = [str(name) for name in transform.get_feature_names_out()]
    except (AttributeError, ValueError):
        names = []
    if len(names) != width:
        raise TabularError(
            code="ML_EXPLAIN_FEATURE_MAPPING",
            message="The pipeline's output columns cannot be named.",
            status_code=409,
            details={"reason": "feature_mapping_unavailable"},
        )
    return names


def _field_of(name: str, vectorizer: Any, inputs: set[str]) -> str | None:
    """The input field an output column was produced from.

    skrub records it (``output_to_input_``) for every column its vectorizer
    writes, including the many columns one text field becomes. An imputer
    after it may add ``missingindicator_<column>``, which belongs to the same
    field. Anything else is refused rather than guessed.
    """

    mapping = getattr(vectorizer, "output_to_input_", None) or {}
    if name in mapping:
        return str(mapping[name])
    prefix = "missingindicator_"
    if name.startswith(prefix) and name[len(prefix) :] in mapping:
        return str(mapping[name[len(prefix) :]])
    return name if name in inputs else None


def _sklearn_tree(tree: Any, *, scale: float = 1.0) -> dict[str, Any]:
    """One fitted sklearn ``Tree`` in TreeExplainer's dictionary form."""

    import numpy as np

    left = tree.children_left.astype(np.int32)
    right = tree.children_right.astype(np.int32)
    missing_left = getattr(tree, "missing_go_to_left", None)
    default = np.where(missing_left.astype(bool), left, right) if missing_left is not None else left
    return {
        "children_left": left,
        "children_right": right,
        "children_default": default.astype(np.int32),
        "features": tree.feature.astype(np.int32),
        "thresholds": tree.threshold.astype(np.float64),
        "values": (tree.value[:, 0, 0].astype(np.float64) * scale).reshape(-1, 1),
        "node_sample_weight": tree.weighted_n_node_samples.astype(np.float64),
    }


def _in_bitset(bitsets: Any, value: float, row: int) -> bool:
    code = int(value)
    return bool((int(bitsets[row, code // 32]) >> (code % 32)) & 1)


def _hgb_tree_for_row(predictor: Any, x: Any, known: Any, f_idx_map: Any) -> dict[str, Any]:
    """One HGB tree with each categorical split resolved for this row.

    Mirrors ``_predict_one_from_raw_data`` in sklearn's ``_predictor.pyx``:
    missing → the split's missing side; a negative or unknown category is
    treated as missing; otherwise the left bitset decides. The resolved branch
    is written as a numeric split the row satisfies (``x <= +inf`` goes left,
    ``x <= -inf`` goes right), with the same branch as the missing default, so
    shap's traversal and sklearn's agree for this row and only this row.
    """

    import numpy as np

    nodes = predictor.nodes
    count = len(nodes)
    left = np.full(count, -1, dtype=np.int32)
    right = np.full(count, -1, dtype=np.int32)
    default = np.full(count, -1, dtype=np.int32)
    features = np.full(count, -2, dtype=np.int32)
    thresholds = np.zeros(count, dtype=np.float64)
    for index, node in enumerate(nodes):
        if node["is_leaf"]:
            continue
        feature = int(node["feature_idx"])
        features[index] = feature
        left[index], right[index] = int(node["left"]), int(node["right"])
        missing_side = left[index] if node["missing_go_to_left"] else right[index]
        if not node["is_categorical"]:
            thresholds[index] = float(node["num_threshold"])
            default[index] = missing_side
            continue
        value = float(x[feature])
        if math.isnan(value) or value < 0:
            goes = missing_side
        elif _in_bitset(predictor.raw_left_cat_bitsets, value, int(node["bitset_idx"])):
            goes = left[index]
        elif known is not None and _in_bitset(known, value, int(f_idx_map[feature])):
            goes = right[index]
        else:
            goes = missing_side
        thresholds[index] = math.inf if goes == left[index] else -math.inf
        default[index] = goes
    return {
        "children_left": left,
        "children_right": right,
        "children_default": default,
        "features": features,
        "thresholds": thresholds,
        "values": nodes["value"].astype(np.float64).reshape(-1, 1),
        "node_sample_weight": nodes["count"].astype(np.float64),
    }


def _hgb_input(estimator: Any, x: Any) -> tuple[Any, list[int]]:
    """The matrix HGB's trees index, and each column's position in ``x``.

    With categorical columns, HGB encodes them through its own
    ``_preprocessor`` (a ColumnTransformer emitting the categorical columns
    first), and the trees' ``feature_idx`` refer to that order.
    """

    import numpy as np

    preprocessor = getattr(estimator, "_preprocessor", None)
    width = x.shape[1]
    if preprocessor is None:
        return np.asarray(x, dtype=np.float64), list(range(width))
    order: list[int] = []
    for _, transformer, columns in preprocessor.transformers_:
        if transformer == "drop":
            continue
        mask = np.asarray(columns)
        positions = np.flatnonzero(mask).tolist() if mask.dtype == bool else [int(c) for c in mask]
        order.extend(positions)
    if sorted(order) != list(range(width)):
        raise TabularError(
            code="ML_EXPLAIN_FEATURE_MAPPING",
            message="The boosting model's internal column order could not be read.",
            status_code=409,
            details={"reason": "feature_mapping_unavailable"},
        )
    return np.asarray(preprocessor.transform(x), dtype=np.float64), order


def _hgb_ensemble(estimator: Any, matrix: Any, class_index: int) -> dict[str, Any]:
    import numpy as np

    known = getattr(estimator, "_bin_mapper", None)
    known_bitsets, f_idx_map = (None, None)
    if known is not None and hasattr(known, "make_known_categories_bitsets"):
        known_bitsets, f_idx_map = known.make_known_categories_bitsets()
    row = matrix[0]
    baseline = np.ravel(estimator._baseline_prediction)
    return {
        "trees": [
            _hgb_tree_for_row(stage[class_index], row, known_bitsets, f_idx_map)
            for stage in estimator._predictors
        ],
        "base_offset": float(baseline[class_index if len(baseline) > 1 else 0]),
        "tree_output": "raw_value",
        "input_dtype": np.float64,
        "internal_dtype": np.float64,
    }


def _gbc_ensemble(estimator: Any, frame: Any, matrix: Any, class_index: int) -> dict[str, Any]:
    """Multiclass sklearn gradient boosting, one class's trees."""

    import numpy as np

    trees = estimator.estimators_[:, class_index]
    rate = float(estimator.learning_rate)
    raw = float(np.asarray(estimator.decision_function(frame))[0, class_index])
    # The stage trees are fitted on arrays inside the ensemble, never on frames.
    summed = sum(float(tree.predict(matrix)[0]) for tree in trees) * rate
    return {
        "trees": [_sklearn_tree(tree.tree_, scale=rate) for tree in trees],
        # The init estimator's raw prediction, read back from public outputs.
        "base_offset": raw - summed,
        "tree_output": "raw_value",
        "input_dtype": np.float64,
        "internal_dtype": np.float64,
    }


def _explainer_state(key: tuple[str, str] | None) -> dict[str, Any]:
    if key is None:
        return {}
    with _explainers_lock:
        state = _explainers.get(key)
        if state is None:
            state = {}
            _explainers[key] = state
            while len(_explainers) > int(settings.ml_predict_cache_size):
                _explainers.popitem(last=False)
        else:
            _explainers.move_to_end(key)
        return state


def explain_pipeline(
    pipeline: Any,
    frame: Any,
    *,
    row: dict[str, Any],
    fields: list[str],
    task: str,
    classes: list[str],
    label: str | None,
    top: int,
    cache_key: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """TreeSHAP for the one row in ``frame``, grouped back onto ``fields``.

    ``label`` is the class the explanation is about (the predicted class of a
    multiclass model, the positive class of a binary one). ``cache_key``
    names the loaded artifact, so a model whose exact explanation exceeded
    ``ML_EXPLAIN_SHAP_EXACT_BUDGET_S`` once is explained approximately
    afterwards, like ``forecast_serving.explain_forecast``.
    """

    import warnings

    with warnings.catch_warnings():
        # shap and sklearn warn about array/frame feature names on every call;
        # the columns are positionally the ones the estimator was fitted on.
        warnings.simplefilter("ignore")
        return _explain(
            pipeline,
            frame,
            row=row,
            fields=fields,
            task=task,
            classes=classes,
            label=label,
            top=top,
            cache_key=cache_key,
        )


def _explain(pipeline, frame, *, row, fields, task, classes, label, top, cache_key):
    import numpy as np
    import shap

    inner, reason = tree_pipeline(pipeline)
    if inner is None:
        raise TabularError(
            code="ML_EXPLAIN_UNAVAILABLE",
            message="This model is not a tree ensemble TreeSHAP can explain.",
            status_code=409,
            details={"reason": reason},
        )
    estimator = inner.steps[-1][1]
    kind = type(estimator).__name__
    transformed = inner[:-1].transform(frame)
    matrix = np.asarray(transformed.to_numpy() if hasattr(transformed, "to_numpy") else transformed)
    names = _output_names(inner, matrix.shape[1])
    vectorizer = _vectorizer(inner)
    known_fields = set(fields)
    owners = [_field_of(name, vectorizer, known_fields) for name in names]
    if any(owner is None or owner not in known_fields for owner in owners):
        raise TabularError(
            code="ML_EXPLAIN_FEATURE_MAPPING",
            message="An output column could not be traced back to an input field.",
            status_code=409,
            details={"reason": "feature_mapping_unavailable"},
        )

    classifier = task == "classification"
    labels = [str(value) for value in classes]
    class_index = labels.index(label) if classifier and label in labels else None
    if classifier and class_index is None:
        raise TabularError(
            code="ML_EXPLAIN_UNAVAILABLE",
            message="The explained class is not one of the model's classes.",
            status_code=409,
            details={"reason": "class_unknown"},
        )
    binary = classifier and len(labels) == 2

    state = _explainer_state(cache_key)
    approximate = bool(state.get("approximate"))
    sign = 1.0
    # ``positions`` maps each column of the explained matrix back to ``names``.
    positions = list(range(matrix.shape[1]))
    if kind.startswith("HistGradientBoosting"):
        explained, positions = _hgb_input(estimator, transformed)
        stacked = len(estimator._predictors[0])
        tree_index = class_index if classifier and stacked > 1 else 0
        explainer = shap.TreeExplainer(_hgb_ensemble(estimator, explained, tree_index))
        if classifier:
            space = "log_odds" if stacked == 1 else "raw_score"
            sign = -1.0 if stacked == 1 and class_index == 0 else 1.0
            raw = np.ravel(np.asarray(estimator.decision_function(transformed)))
            output = float(raw[0] if stacked == 1 else raw[class_index]) * sign
        else:
            space = "value"
            output = float(np.ravel(estimator.predict(transformed))[0])
        pick = None
    elif kind == "GradientBoostingClassifier" and not binary:
        explained = matrix.astype(np.float64)
        explainer = shap.TreeExplainer(
            _gbc_ensemble(estimator, transformed, explained, class_index)
        )
        space = "raw_score"
        output = float(np.asarray(estimator.decision_function(transformed))[0, class_index])
        pick = None
    else:
        explained = matrix.astype(np.float64)
        explainer = state.get("explainer")
        if explainer is None:
            explainer = shap.TreeExplainer(estimator)
            state["explainer"] = explainer
        if kind == "GradientBoostingClassifier":
            space = "log_odds"
            sign = -1.0 if class_index == 0 else 1.0
            output = float(np.ravel(estimator.decision_function(transformed))[0]) * sign
            pick = None
        elif classifier:
            space = "probability"
            output = float(estimator.predict_proba(transformed)[0, class_index])
            pick = class_index
        else:
            space = "value"
            output = float(np.ravel(estimator.predict(transformed))[0])
            pick = None

    started = time.monotonic()
    values = np.asarray(
        explainer.shap_values(explained, approximate=approximate, check_additivity=False)
    )
    if not approximate and cache_key is not None:
        state["approximate"] = time.monotonic() - started > float(
            settings.ml_explain_shap_exact_budget_s
        )
    expected = np.ravel(np.asarray(explainer.expected_value, dtype=np.float64))
    if values.ndim == 3:
        values = values[0, :, pick if pick is not None else 0]
        base = float(expected[pick if pick is not None else 0])
    else:
        values = values.reshape(-1)[: explained.shape[1]] if values.ndim == 1 else values[0]
        base = float(expected[0])
    values = values * sign
    base = base * sign

    by_field = {name: 0.0 for name in fields}
    for column, contribution in zip(positions, values):
        by_field[owners[column]] += float(contribution)
    ranked = sorted(by_field.items(), key=lambda item: abs(item[1]), reverse=True)
    shown, rest = ranked[: max(1, int(top))], ranked[max(1, int(top)) :]
    total = base + sum(value for _, value in ranked)
    return {
        "method": "tree_shap_approximate" if approximate else "tree_shap",
        "output_space": space,
        "estimator": kind,
        "class": label if classifier else None,
        "base": round(base, 6),
        "output": round(output, 6),
        "contributions": [
            {"field": name, "value": _json_value(row.get(name)), "contribution": round(value, 6)}
            for name, value in shown
        ],
        "other": (
            {"fields": len(rest), "contribution": round(sum(value for _, value in rest), 6)}
            if rest
            else None
        ),
        "additivity_gap": round(abs(total - output), 9),
    }


def answer_for(model_id: str, row: dict[str, Any], *, label: str | None = None) -> dict[str, Any]:
    """The task body in the ml-ts RPC worker; a refusal crosses back as data."""

    from app.db.base import SessionLocal
    from app.models.tabular import MLModel
    from app.services.tabular_predict import (
        build_frame,
        coerce_rows,
        contract_fields,
        load_pipeline_traced,
    )

    try:
        if settings.ml_runtime != "ml-ts" and not settings.worker_eager_mode:
            raise TabularError(
                code="ML_RUNTIME_MISSING",
                message="TreeSHAP runs in the ml-ts runtime.",
                status_code=409,
                details={"reason": "shap_unavailable"},
            )
        try:
            import shap  # noqa: F401
        except ImportError as exc:
            raise TabularError(
                code="ML_EXPLAIN_UNAVAILABLE",
                message="shap is not installed in this runtime.",
                status_code=409,
                details={"reason": "shap_unavailable"},
            ) from exc
        with SessionLocal() as db:
            model = db.get(MLModel, model_id)
            if model is None or model.status != "ready" or (model.family or "tabular") != "tabular":
                raise TabularError(
                    code="ML_MODEL_NOT_READY",
                    message="The model is not a ready tabular model.",
                    status_code=409,
                )
            db.expunge(model)
        entry, _ = load_pipeline_traced(model)
        fields = contract_fields(model)
        coerced = coerce_rows(model, [row])[0]
        frame = build_frame(fields, [coerced])
        started = time.monotonic()
        explanation = explain_pipeline(
            entry.pipeline,
            frame,
            row=coerced,
            fields=[str(spec["name"]) for spec in fields],
            task=str(model.task),
            classes=entry.classes,
            label=label,
            top=int(settings.ml_explain_shap_top_fields),
            cache_key=(entry.model_id, entry.fingerprint),
        )
        explanation["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
        return {"explanation": explanation}
    except TabularError as exc:
        return {"error": exc.payload(), "status": exc.status_code}
    except Exception as exc:  # noqa: BLE001 - an explanation failure is a reason
        logger.warning(
            "tree_explanations: explanation failed", model_id=model_id, error=type(exc).__name__
        )
        return {
            "error": {
                "code": "ML_EXPLAIN_FAILED",
                "message": "The explanation could not be computed.",
                "reason": "explain_failed",
            },
            "status": 409,
        }


# ---------------------------------------------------------------------------
# API side
# ---------------------------------------------------------------------------

# Error codes a worker returns, read as the reason the counterfactual answered.
_REASONS = {
    "ML_ARTIFACT_RUNTIME_MISMATCH": "runtime_mismatch",
    "ML_ARTIFACT_RUNTIME_UNVERIFIED": "runtime_mismatch",
    "ML_FAMILY_UNAVAILABLE": "shap_unavailable",
    "ML_RUNTIME_MISSING": "shap_unavailable",
}


class ExplanationUnavailableError(Exception):
    """Why TreeSHAP did not answer; the caller falls back or refuses."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _shap_runtime() -> Any:
    """The tabular family as the ml-ts RPC worker would serve it."""

    from dataclasses import replace

    from app.services.ml.families import get_family

    return replace(
        get_family("tabular"),
        runtime="ml-ts",
        serving="remote",
        serve_queue_setting="celery_ml_ts_serve_queue",
    )


def _require_consumer(db: Any, model: Any) -> None:
    """A live ml-ts RPC consumer whose reader stack loads this artifact."""

    from importlib.util import find_spec

    if settings.worker_eager_mode:
        # Inline in this process: the question is whether *this* interpreter
        # has shap, which is exactly what an image without it answers "no" to.
        try:
            present = find_spec("shap") is not None
        except (ImportError, ValueError):
            present = False
        if not present:
            raise ExplanationUnavailableError("shap_unavailable")
        return
    from app.services.ml.runtime import _heard_on, require_artifact_runtime

    queue = str(settings.celery_ml_ts_serve_queue or "").strip()
    alive, _ = _heard_on("ml-ts", queue, db, None)
    if not alive:
        raise ExplanationUnavailableError("shap_unavailable")
    try:
        require_artifact_runtime(
            _shap_runtime(), (model.metrics_json or {}).get("artifact") or {}, db
        )
    except TabularError as exc:
        raise ExplanationUnavailableError(_REASONS.get(exc.code, "runtime_mismatch")) from exc


def request_explanation(db: Any, model: Any, row: dict[str, Any], *, label: str | None) -> dict:
    """Send the row to the ml-ts worker and wait, bounded by the explain timeout."""

    if settings.worker_eager_mode:
        result = answer_for(model.id, row, label=label)
    else:
        from celery.exceptions import TimeoutError as CeleryTimeout

        from app.workers.celery_app import celery_app

        timeout = float(settings.ml_explain_timeout_s)
        pending = celery_app.send_task(
            TASK,
            args=[model.id, row],
            kwargs={"label": label},
            queue=str(settings.celery_ml_ts_serve_queue),
            # Bounds the wait in the queue only: a task that started will finish
            # and leave its model loaded, which is what warms the next call.
            expires=timeout,
        )
        try:
            result = pending.get(timeout=timeout, propagate=False)
        except CeleryTimeout as exc:
            raise ExplanationUnavailableError("timeout") from exc
        except Exception as exc:  # noqa: BLE001 - a broker failure is a reason
            raise ExplanationUnavailableError("shap_unavailable") from exc
        finally:
            if hasattr(pending, "forget"):
                # The rpc:// result backend stores nothing and cannot forget.
                with suppress(NotImplementedError, Exception):
                    pending.forget()
    if not isinstance(result, dict):
        raise ExplanationUnavailableError("explain_failed")
    if result.get("error"):
        error = result.get("error") or {}
        code = str(error.get("code") or "")
        raise ExplanationUnavailableError(
            str(error.get("reason") or _REASONS.get(code) or "explain_failed")
        )
    explanation = result.get("explanation")
    if not isinstance(explanation, dict):
        raise ExplanationUnavailableError("explain_failed")
    return explanation


def explain_served_row(
    db: Any, model: Any, pipeline: Any, row: dict[str, Any], *, label: str | None
) -> dict[str, Any]:
    """TreeSHAP for one served row, or :class:`ExplanationUnavailableError`."""

    if (getattr(model, "family", None) or "tabular") != "tabular" or model.task not in {
        "classification",
        "regression",
    }:
        raise ExplanationUnavailableError("not_a_tree_model")
    if not settings.ml_explain_shap_enabled:
        raise ExplanationUnavailableError("shap_disabled")
    _, reason = tree_pipeline(pipeline)
    if reason:
        raise ExplanationUnavailableError(reason)
    _require_consumer(db, model)
    return request_explanation(db, model, row, label=label)


def refusal(reason: str) -> TabularError:
    """The 409 an explicit ``explain_method="shap"`` gets instead of a fallback."""

    return TabularError(
        code="ML_EXPLAIN_UNAVAILABLE",
        message="A TreeSHAP explanation is not available for this prediction.",
        status_code=409,
        details={"reason": reason},
    )


def reset_cache() -> None:
    with _explainers_lock:
        _explainers.clear()


__all__ = [
    "METHODS",
    "TASK",
    "TREE_ESTIMATORS",
    "ExplanationUnavailableError",
    "answer_for",
    "explain_pipeline",
    "explain_served_row",
    "refusal",
    "request_explanation",
    "reset_cache",
    "tree_pipeline",
]
