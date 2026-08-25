"""Standalone sklearn training harness, executed as a supervised subprocess.

Why a harness at all when the code is ours
------------------------------------------
Unlike the transform harnesses this one runs **no author-written code**: the
estimator comes from a curated catalog and the preprocessing is decided by
skrub. So the subprocess is not about untrusted code, it is about the two
properties a fit cannot give from inside the API or the worker process:

* a fit is uninterruptible — ``KeyboardInterrupt`` does not reach a BLAS loop —
  so cancelling a training run means killing a process group;
* a fit is a resource event — threads, arenas, a multi-megabyte artifact — and
  ``RLIMIT_*`` only applies to a child.

It runs on the **application interpreter**, not on a managed venv, because the
serving path unpickles what training pickled: a version skew between two
sklearn installs is a load failure with no useful error.

What it produces
----------------
Two things, and they are different in kind:

* ``model_dir`` — an MLflow model directory, serialized by **skops**. Unlike
  pickle, skops refuses to reconstruct a type that was not declared trusted when
  the model was saved, and this harness computes that allowlist from the dumped
  pipeline and **refuses to save at all** if a type outside the expected module
  set shows up. That is what makes loading the artifact later a bounded action.
* ``result.json`` — the read model of the model card: metrics, curves, the class
  balance, permutation importances, and a per-feature input contract carrying
  the choices and ranges a prediction form can be built from without ever
  loading the pipeline.

Integer feature columns are cast to float before the fit. It looks cosmetic and
is not: MLflow enforces the signature at predict time, and an integer column
cannot carry a missing value, so a production row with one hole would be refused
by the very contract training wrote.

Exit codes are the machine contract with the supervising worker:
  0 success · 1 the fit raised · 2 the target is unusable · 3 too few usable rows ·
  4 the artifact could not be written or trusted · 5 harness/manifest error

Progress is the other half of that contract. A fit of a few hundred thousand rows
runs for minutes, and only this process knows when the reading ends, the fitting
ends and the scoring begins — so it appends those step names to
``manifest['progress_path']`` and the worker republishes what it reads onto the
polled row. A bare code, never a sentence: the surfaces reading it are French and
English.
"""
from __future__ import annotations

import json
import math
import sys
import time

# Types the saved pipeline is allowed to reference. The estimator comes from our
# own catalog and the preprocessing from skrub, so anything outside this set is
# a signal that the artifact is not what this harness thinks it is.
TRUSTED_MODULE_PREFIXES = (
    "sklearn.",
    "skrub.",
    "numpy.",
    "scipy.",
    "pandas.",
    "builtins.",
    "collections.",
)

_MAX_CHOICES = 12


def _fail(code: int, message: str) -> int:
    print(message, file=sys.stderr, flush=True)
    return code


def _progress(path, step: str) -> None:
    """Append one step name for the supervising worker to pick up.

    Appended and flushed line by line so a reader that catches the file mid-write
    sees the previous step rather than a partial one, and never fatal: a fit is
    not worth failing because a scratch file could not be touched.
    """

    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{step}\n")
            handle.flush()
    except OSError:
        pass


def _number(value) -> float | None:
    """A JSON-safe float, or None. Postgres JSON rejects NaN and Infinity."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, 6)


def _label(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)[:120]


def _scalar(value):
    """One cell, JSON-safe, keeping its type when JSON has one for it."""

    import numpy as np
    import pandas as pd

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return _number(value)
    if isinstance(value, (int,)):
        return int(value)
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001 - fall through to str()
            pass
    return str(value)[:200]


def _thin(xs, ys, limit: int) -> list[dict]:
    """Sample a curve down to ``limit`` points, keeping both endpoints."""

    total = len(xs)
    if total == 0:
        return []
    if total <= limit:
        indices = range(total)
    else:
        step = (total - 1) / (limit - 1)
        indices = sorted({int(round(i * step)) for i in range(limit)} | {0, total - 1})
    return [
        {"x": _number(xs[i]), "y": _number(ys[i])}
        for i in indices
        if _number(xs[i]) is not None and _number(ys[i]) is not None
    ]


def _input_contract(frame, signature_inputs: list[dict]) -> list[dict]:
    """Per-feature typing plus what a prediction form needs to be usable.

    The signature types the field; the frame says what a plausible value looks
    like. Carrying both means the playground can render a select for a plan code
    and a sane numeric default for an ARPU without loading the pipeline.
    """

    import pandas as pd

    by_name = {str(entry.get("name")): entry for entry in signature_inputs}
    contract: list[dict] = []
    for name in frame.columns:
        column = frame[name]
        declared = by_name.get(str(name), {})
        field: dict = {
            "name": str(name),
            "type": str(declared.get("type") or "string"),
            "required": bool(declared.get("required", True)),
        }
        if pd.api.types.is_numeric_dtype(column) and not pd.api.types.is_bool_dtype(
            column
        ):
            field["kind"] = "number"
            field["min"] = _number(column.min())
            field["max"] = _number(column.max())
            field["default"] = _number(column.median())
        elif pd.api.types.is_datetime64_any_dtype(column):
            field["kind"] = "datetime"
            field["default"] = _scalar(column.max())
        else:
            field["kind"] = "category"
            counts = column.astype("object").value_counts(dropna=True)
            if 0 < len(counts) <= _MAX_CHOICES:
                field["choices"] = [_label(value) for value in counts.index]
            field["default"] = (
                _label(counts.index[0]) if len(counts) else None
            )
        contract.append(field)
    return contract


def _classification_metrics(
    y_test, predicted, proba, classes, *, curve_points: int
) -> dict:
    from sklearn.metrics import (
        accuracy_score,
        balanced_accuracy_score,
        confusion_matrix,
        f1_score,
        precision_recall_curve,
        precision_score,
        recall_score,
        roc_auc_score,
        roc_curve,
    )

    labels = list(classes)
    binary = len(labels) == 2
    scores = [
        {"key": "accuracy", "value": _number(accuracy_score(y_test, predicted))},
        {
            "key": "balanced_accuracy",
            "value": _number(balanced_accuracy_score(y_test, predicted)),
        },
        {
            "key": "f1",
            "value": _number(
                f1_score(
                    y_test,
                    predicted,
                    average="binary" if binary else "macro",
                    pos_label=labels[-1] if binary else 1,
                    zero_division=0,
                )
            ),
        },
        {
            "key": "precision",
            "value": _number(
                precision_score(
                    y_test,
                    predicted,
                    average="binary" if binary else "macro",
                    pos_label=labels[-1] if binary else 1,
                    zero_division=0,
                )
            ),
        },
        {
            "key": "recall",
            "value": _number(
                recall_score(
                    y_test,
                    predicted,
                    average="binary" if binary else "macro",
                    pos_label=labels[-1] if binary else 1,
                    zero_division=0,
                )
            ),
        },
    ]

    curves: dict = {}
    auc = None
    if proba is not None:
        try:
            if binary:
                positive = proba[:, -1]
                auc = _number(roc_auc_score(y_test, positive))
                fpr, tpr, _ = roc_curve(y_test, positive, pos_label=labels[-1])
                curves["roc"] = _thin(fpr, tpr, curve_points)
                precision, recall, _ = precision_recall_curve(
                    y_test, positive, pos_label=labels[-1]
                )
                curves["pr"] = _thin(recall, precision, curve_points)
                curves["baseline"] = _number(
                    sum(1 for value in y_test if value == labels[-1]) / len(y_test)
                )
            else:
                auc = _number(
                    roc_auc_score(y_test, proba, multi_class="ovr", average="macro")
                )
        except Exception:  # noqa: BLE001 - a curve is never worth failing a fit on
            auc = None
    if auc is not None:
        scores.insert(0, {"key": "roc_auc", "value": auc})

    matrix = confusion_matrix(y_test, predicted, labels=labels)
    return {
        "primary": scores[0],
        "scores": scores,
        "confusion": {
            "labels": [_label(value) for value in labels],
            "matrix": [[int(cell) for cell in row] for row in matrix],
        },
        "curves": curves,
    }


def _regression_metrics(y_test, predicted, *, curve_points: int) -> dict:
    import numpy as np
    from sklearn.metrics import (
        mean_absolute_error,
        mean_squared_error,
        r2_score,
    )

    actual = np.asarray(y_test, dtype="float64")
    guess = np.asarray(predicted, dtype="float64")
    scores = [
        {"key": "r2", "value": _number(r2_score(actual, guess))},
        {"key": "mae", "value": _number(mean_absolute_error(actual, guess))},
        {
            "key": "rmse",
            "value": _number(math.sqrt(mean_squared_error(actual, guess))),
        },
    ]
    nonzero = actual != 0
    if nonzero.any():
        scores.append(
            {
                "key": "mape",
                "value": _number(
                    float(
                        np.mean(
                            np.abs(
                                (actual[nonzero] - guess[nonzero]) / actual[nonzero]
                            )
                        )
                        * 100
                    )
                ),
            }
        )
    order = np.argsort(actual)
    return {
        "primary": scores[0],
        "scores": scores,
        "curves": {
            # Predicted against actual: the regression equivalent of a ROC, and
            # the only chart that shows *where* a model is wrong.
            "fit": _thin(actual[order], guess[order], curve_points),
            "ideal": [
                {"x": _number(actual.min()), "y": _number(actual.min())},
                {"x": _number(actual.max()), "y": _number(actual.max())},
            ],
        },
    }


def _importances(pipeline, x_test, y_test, *, rows: int, scoring: str, seed: int):
    """Permutation importance on a capped sample: the honest feature ranking.

    Capped because it refits nothing but predicts ``n_repeats`` times per
    column, and a model card is not worth minutes of CPU.
    """

    from sklearn.inspection import permutation_importance

    take = min(int(rows), len(x_test))
    if take < 20:
        return []
    sample_x = x_test.iloc[:take]
    sample_y = y_test.iloc[:take]
    try:
        result = permutation_importance(
            pipeline,
            sample_x,
            sample_y,
            n_repeats=3,
            random_state=seed,
            scoring=scoring,
            n_jobs=1,
        )
    except Exception:  # noqa: BLE001 - decoration, never a blocker
        return []
    ranked = [
        {"feature": str(name), "value": _number(value)}
        for name, value in zip(sample_x.columns, result.importances_mean)
    ]
    ranked.sort(key=lambda row: abs(row["value"] or 0.0), reverse=True)
    return ranked


def _trusted_types(model) -> list[str]:
    """The skops allowlist for this pipeline, or raise if it is not ours.

    Computed rather than hardcoded because the set depends on which columns
    skrub decided to encode how; bounded by module prefix because an unexpected
    module means the artifact would deserialize something this harness never
    put in it.
    """

    import skops.io as sio

    untrusted = sio.get_untrusted_types(data=sio.dumps(model))
    rogue = sorted(
        name for name in untrusted if not str(name).startswith(TRUSTED_MODULE_PREFIXES)
    )
    if rogue:
        raise RuntimeError(f"untrusted_types: {', '.join(rogue[:6])}")
    return sorted(str(name) for name in untrusted)


def _tolerates_missing(estimator, *, fallback: bool) -> bool:
    """Whether this estimator reads a hole as a value, per sklearn's own tags.

    Asked of the estimator rather than tabulated here because the estimator is
    the authority: the boosted trees send NaN down a branch of their own and
    would lose that signal to an imputed median, while a logistic regression
    refuses the row outright. If a future sklearn moves the tag, the catalog's
    ``scale`` flag stands in — it marks the same two families, for the
    neighbouring reason that they read magnitudes rather than splits.
    """

    try:
        from sklearn.utils import get_tags

        return bool(get_tags(estimator).input_tags.allow_nan)
    except Exception:  # noqa: BLE001 - the catalog still knows, see above
        return fallback


def _resolve_estimator(dotted: str, params: dict):
    module_name, _, class_name = str(dotted).rpartition(".")
    if not module_name or not class_name:
        raise RuntimeError(f"estimator_unresolvable: {dotted}")
    if not module_name.startswith("sklearn."):
        raise RuntimeError(f"estimator_not_allowed: {dotted}")
    import importlib

    module = importlib.import_module(module_name)
    factory = getattr(module, class_name, None)
    if factory is None:
        raise RuntimeError(f"estimator_unresolvable: {dotted}")
    return factory(**dict(params or {}))


def main(argv: list[str]) -> int:  # noqa: C901 - one linear pipeline, read top down
    if len(argv) != 3:
        return _fail(5, "usage: ml_train_harness.py MANIFEST_JSON RESULT_JSON")
    manifest_path, result_path = argv[1:3]
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return _fail(5, f"ml_manifest_unreadable: {exc}")
    if not isinstance(manifest, dict):
        return _fail(5, "ml_manifest_not_object")

    data_path = manifest.get("data_path")
    model_dir = manifest.get("model_dir")
    target = manifest.get("target")
    features = manifest.get("features")
    task = manifest.get("task")
    if (
        not isinstance(data_path, str)
        or not isinstance(model_dir, str)
        or not isinstance(target, str)
        or not isinstance(features, list)
        or not features
        or task not in ("classification", "regression")
    ):
        return _fail(5, "ml_manifest_incomplete")

    progress_path = manifest.get("progress_path")
    seed = int(manifest.get("random_state") or 42)
    test_size = float(manifest.get("test_size") or 0.25)
    folds = int(manifest.get("cv") or 0)
    min_rows = int(manifest.get("min_rows") or 40)
    curve_points = int(manifest.get("curve_points") or 120)
    importance_rows = int(manifest.get("importance_rows") or 2000)

    started = time.monotonic()
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - the app venv has pandas
        return _fail(5, f"pandas_missing: {exc}")

    _progress(progress_path, "reading")
    try:
        frame = pd.read_parquet(data_path, columns=list({*features, target}))
    except Exception as exc:  # noqa: BLE001
        return _fail(5, f"ml_dataset_unreadable: {exc}")

    frame = frame.dropna(subset=[target])
    if len(frame) < min_rows:
        return _fail(
            3,
            f"ml_rows_insufficient: {len(frame)} usable rows, {min_rows} needed "
            "once rows without a target are dropped",
        )

    y = frame[target]
    x = frame[[column for column in features if column != target]].copy()
    # See the module docstring: an integer column cannot carry a hole, and the
    # signature this fit writes is enforced at predict time.
    for column in x.columns:
        if pd.api.types.is_integer_dtype(x[column]):
            x[column] = x[column].astype("float64")

    dropped: list[dict] = []
    for column in list(x.columns):
        if x[column].nunique(dropna=True) <= 1:
            dropped.append({"name": str(column), "reason": "constant"})
            x = x.drop(columns=[column])
    if x.empty or not len(x.columns):
        return _fail(2, "ml_features_unusable: every feature column is constant")

    stratify = None
    classes: list = []
    if task == "classification":
        y = y.astype("object") if y.dtype == object else y
        counts = y.value_counts()
        if len(counts) < 2:
            return _fail(
                2,
                f"ml_target_single_class: '{target}' holds one value only, so there "
                "is nothing to separate",
            )
        max_classes = int(manifest.get("max_classes") or 24)
        if len(counts) > max_classes:
            return _fail(
                2,
                f"ml_target_too_many_classes: '{target}' holds {len(counts)} distinct "
                f"values, more than the {max_classes} a classifier is offered for",
            )
        if int(counts.min()) < 2:
            return _fail(
                2,
                f"ml_target_class_too_rare: the rarest value of '{target}' appears "
                "once, so it cannot be in both the train and the test split",
            )
        stratify = y
        classes = list(counts.sort_index().index)
    else:
        y = pd.to_numeric(y, errors="coerce")
        keep = y.notna()
        if int(keep.sum()) < min_rows:
            return _fail(
                2,
                f"ml_target_not_numeric: '{target}' does not read as a number, so it "
                "cannot be regressed",
            )
        x, y = x[keep.values], y[keep]

    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline

    try:
        from skrub import TableVectorizer
    except ImportError as exc:  # pragma: no cover - the app venv has skrub
        return _fail(5, f"skrub_missing: {exc}")

    try:
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=test_size, random_state=seed, stratify=stratify
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(2, f"ml_split_failed: {exc}")

    try:
        estimator = _resolve_estimator(
            manifest.get("estimator"), manifest.get("params")
        )
    except RuntimeError as exc:
        return _fail(5, str(exc))

    steps = [TableVectorizer()]
    if not _tolerates_missing(estimator, fallback=not manifest.get("scale")):
        # skrub encodes the categories but leaves numeric holes exactly as it
        # found them, so an estimator that refuses NaN refuses them here — and
        # would go on refusing them at predict time, which is the worse half:
        # the signature this fit writes says a numeric column is nullable, so a
        # model without this step would reject production rows its own contract
        # accepts. Median rather than mean because a survey score or an ARPU is
        # skewed often enough that the mean is not a plausible value.
        from sklearn.impute import SimpleImputer

        steps.append(SimpleImputer(strategy="median"))
    if manifest.get("scale"):
        # Linear and distance-based estimators read magnitudes as importance, so
        # an unscaled ARPU column would outvote an unscaled ticket count. Trees
        # do not care, which is why this is per-algorithm and not always on.
        from sklearn.preprocessing import StandardScaler

        steps.append(StandardScaler())
    pipeline = make_pipeline(*steps, estimator)
    print(f"fitting {type(estimator).__name__} on {len(x_train)} rows", flush=True)
    _progress(progress_path, "fitting")
    try:
        pipeline.fit(x_train, y_train)
    except Exception as exc:  # noqa: BLE001 - the algorithm's refusal is the answer
        return _fail(1, f"ml_fit_failed: {type(exc).__name__}: {exc}")

    _progress(progress_path, "scoring")
    predicted = pipeline.predict(x_test)
    proba = None
    if task == "classification" and hasattr(pipeline, "predict_proba"):
        try:
            proba = pipeline.predict_proba(x_test)
            classes = list(pipeline.classes_)
        except Exception:  # noqa: BLE001
            proba = None

    if task == "classification":
        metrics = _classification_metrics(
            y_test, predicted, proba, classes, curve_points=curve_points
        )
        scoring = "roc_auc" if len(classes) == 2 else "accuracy"
        balance = [
            {"label": _label(value), "count": int(count)}
            for value, count in y.value_counts().sort_index().items()
        ]
        metrics["target"] = {
            "name": str(target),
            "classes": [_label(value) for value in classes],
            "positive": _label(classes[-1]) if len(classes) == 2 else None,
            "balance": balance,
        }
    else:
        metrics = _regression_metrics(y_test, predicted, curve_points=curve_points)
        scoring = "r2"
        metrics["target"] = {
            "name": str(target),
            "min": _number(y.min()),
            "max": _number(y.max()),
            "mean": _number(y.mean()),
        }

    metrics["task"] = task
    metrics["rows"] = {
        "total": int(len(x)),
        "train": int(len(x_train)),
        "test": int(len(x_test)),
    }
    metrics["columns"] = {
        "used": [str(column) for column in x.columns],
        "dropped": dropped,
    }
    metrics["importances"] = _importances(
        pipeline, x_test, y_test, rows=importance_rows, scoring=scoring, seed=seed
    )

    if folds >= 2:
        from sklearn.model_selection import cross_val_score

        try:
            values = cross_val_score(
                pipeline, x_train, y_train, cv=folds, scoring=scoring, n_jobs=1
            )
            metrics["cv"] = {
                "folds": folds,
                "metric": scoring,
                "mean": _number(values.mean()),
                "std": _number(values.std()),
                "scores": [_number(value) for value in values],
            }
        except Exception as exc:  # noqa: BLE001 - a fold that fails is not a fit that fails
            metrics["cv"] = {"folds": folds, "metric": scoring, "error": str(exc)[:200]}

    import mlflow.sklearn
    from mlflow.models import infer_signature

    example = x_train.head(3)
    signature = infer_signature(x_train.head(200), pipeline.predict(x_train.head(200)))
    signature_dict = signature.to_dict()
    try:
        declared_inputs = json.loads(signature_dict.get("inputs") or "[]")
    except ValueError:
        declared_inputs = []

    _progress(progress_path, "saving")
    try:
        trusted = _trusted_types(pipeline)
        mlflow.sklearn.save_model(
            pipeline,
            path=model_dir,
            signature=signature,
            input_example=example,
            skops_trusted_types=trusted,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(4, f"ml_artifact_unwritable: {type(exc).__name__}: {exc}")

    summary = {
        "metrics": metrics,
        "signature": {
            "inputs": _input_contract(x_train, declared_inputs),
            "output": {
                "task": task,
                "target": str(target),
                "classes": metrics.get("target", {}).get("classes") or [],
            },
        },
        "classes": metrics.get("target", {}).get("classes") or [],
        "input_example": [
            {str(name): _scalar(value) for name, value in row.items()}
            for _, row in example.iterrows()
        ],
        "trusted_types": trusted,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }
    try:
        with open(result_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    except (OSError, ValueError) as exc:
        return _fail(4, f"ml_summary_unwritable: {exc}")
    print("trained", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
