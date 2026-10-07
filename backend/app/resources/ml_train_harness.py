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
* ``report_path`` — the skore report's own state, as ``to_dict()`` writes it.
  ``result.json`` is a *reading* of the evaluation, flattened for one card; this
  is the evaluation itself, carrying the split rows and the cached predictions,
  so ``EstimatorReport.from_dict`` rebuilds it and answers a question we did not
  think to flatten — without refitting and, more importantly, without guessing
  which rows the published numbers came from. Optional by construction: it is
  skipped above a row ceiling and never fails a fit.

Every number in that read model comes from **skore**, the evaluation library the
scikit-learn maintainers write. Not for the name: an ``EstimatorReport`` caches
its predictions, so the metric table, the ROC, the PR curve, the confusion matrix
and the permutation importances are all read off *one* pass over the test split
instead of the five a hand-rolled evaluation pays. It also reports ``log_loss``
and ``brier_score``, which say whether a probability is *calibrated* — the
question that matters when the number is about to be shown as a gauge on a
prediction form and believed. Binary fits pass ``pos_label`` explicitly, which is
what makes skore name the columns ``precision``/``recall`` rather than
``precision_<class>``: the positive class is a property of the question being
asked, not something to infer from label ordering.

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
import os
import sys
import time
from pathlib import Path

# Types the saved pipeline is allowed to reference. The estimator comes from our
# own catalog and the preprocessing from skrub, so anything outside this set is
# a signal that the artifact is not what this harness thinks it is.
#
# ``functools.`` is on the list, and it is the one entry that needs its reasoning
# written down: skrub's column selectors are built from ``functools.partial``, so
# without it no pipeline saves at all. A partial is a callable wrapping another
# callable, which sounds like exactly the hole an allowlist is for — except skops
# lists the wrapped callable *separately*, at any nesting depth, so it faces this
# same prefix rule on its own. A partial over ``os.system`` reports
# ``posix.system`` beside it and is refused there. Trusting the wrapper therefore
# grants no authority the wrapped function does not already have to earn. See
# ``test_a_trusted_partial_cannot_smuggle_an_untrusted_callable``.
TRUSTED_MODULE_PREFIXES = (
    "sklearn.",
    "skrub.",
    "numpy.",
    "scipy.",
    "pandas.",
    "builtins.",
    "collections.",
    "functools.",
)

_MAX_CHOICES = 12

# The metric vocabulary the model card has labels and hints for. skore's tables
# are wider than this (timings, per-class rows), and a chip whose label is a raw
# key is worse than no chip.
_CARD_METRICS = frozenset(
    {
        "roc_auc",
        "accuracy",
        "balanced_accuracy",
        "f1",
        "precision",
        "recall",
        "log_loss",
        "brier_score",
        "r2",
        "mae",
        "rmse",
        "mape",
    }
)


def _fail(code: int, message: str) -> int:
    print(message, file=sys.stderr, flush=True)
    return code


def _progress(path, step: str) -> None:
    """Append one step name for the supervising worker to pick up.

    Appended and flushed line by line so a reader that catches the file mid-write
    sees the previous step rather than a partial one, and never fatal: a fit is
    not worth failing because a scratch file could not be touched.

    A step may carry a count after a colon — ``fitting:6903``,
    ``validating:3/5`` — which the worker parses back out. Same convention as the
    ingest plane, and for the same reason: the number is the only part of a wait
    that says how much of it is left, and it cannot be a translated sentence
    because two locales poll the same row.
    """

    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{step}\n")
            handle.flush()
    except OSError:
        pass


class _NarratedSplitter:
    """A cross-validator that says which fold it is handing out.

    Cross-validation is the longest step of a run that asked for it — it refits
    the whole pipeline once per fold — and it is the one a silent spinner hurts
    most, because "validating" sits there unchanged for five times the length of
    the fit that preceded it. The plan's example of a wait worth narrating is
    literally "Fold 3/5".

    There is no callback to hook: ``CrossValidationReport`` takes a splitter and
    runs. But it *consumes* that splitter, one fold at a time, and a splitter is
    free to have opinions while it is being consumed — so the announcement rides
    on ``split()`` rather than on a progress API that does not exist. Delegation
    rather than subclassing because the wrapped object is whatever skore was
    given, and ``n_splits`` is the only other thing anyone asks a splitter for.
    """

    def __init__(self, inner, folds: int, progress_path) -> None:
        self._inner = inner
        self._folds = folds
        self._progress_path = progress_path

    def get_n_splits(self, X=None, y=None, groups=None) -> int:  # noqa: N803
        return self._inner.get_n_splits(X, y, groups)

    def split(self, X=None, y=None, groups=None):  # noqa: N803
        for index, fold in enumerate(self._inner.split(X, y, groups), start=1):
            _progress(self._progress_path, f"validating:{index}/{self._folds}")
            yield fold


def _fold_splitter(folds: int, task: str, y):
    """The splitter an integer fold count means, made explicit.

    ``check_cv`` is what sklearn itself calls when handed a number, so asking it
    is how the narrated wrapper stays behaviour-neutral: stratified for a
    classification target, plain for a regression one, unshuffled either way.
    Building one by hand would be a second opinion about what "5 folds" means,
    and the folds a model is judged on must not depend on who asked for them.
    """

    from sklearn.model_selection import check_cv

    return check_cv(folds, y, classifier=task == "classification")


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


def _summary_table(display) -> dict:
    """A skore metrics summary as a flat ``{metric: value}`` mapping.

    ``frame()`` is a Series for a lone estimator and a one-column frame when
    skore decides otherwise; both are the same reading.
    """

    frame = display.frame()
    series = frame.iloc[:, 0] if hasattr(frame, "columns") else frame
    return {str(name): _number(value) for name, value in series.items()}


def _pick(table: dict, base: str, positive: str | None) -> float | None:
    """Read a metric skore may have named per class, per macro average, or bare.

    With ``pos_label`` set skore writes ``recall``; without it — the multiclass
    case — the same quantity is ``recall_avg_macro``, and the per-class values
    sit under ``recall_<label>``.
    """

    for key in (base, f"{base}_avg_macro", f"{base}_{positive}" if positive else ""):
        if key and key in table and table[key] is not None:
            return table[key]
    return None


def _curve(frame, x_column: str, y_column: str, *, limit: int) -> list[dict]:
    """Thin one of skore's tidy curve frames into plottable points."""

    return _thin(
        frame[x_column].to_numpy(), frame[y_column].to_numpy(), limit
    )


def _classification_metrics(report, classes, *, curve_points: int) -> dict:
    """The model card's classification read model, entirely from skore.

    ``f1`` and ``balanced_accuracy`` are not in skore's default table, and are
    not recomputed here either: both are definitions over numbers skore already
    reported — f1 is the harmonic mean of precision and recall, balanced
    accuracy is the macro recall — so deriving them keeps one source of truth.
    """

    labels = list(classes)
    binary = len(labels) == 2
    positive = _label(labels[-1]) if binary else None
    table = _summary_table(report.metrics.summarize())

    matrix = [[0 for _ in labels] for _ in labels]
    index = {_label(value): position for position, value in enumerate(labels)}
    for row in report.metrics.confusion_matrix().frame().itertuples():
        true_at = index.get(_label(row.true_label))
        predicted_at = index.get(_label(row.predicted_label))
        if true_at is not None and predicted_at is not None:
            matrix[true_at][predicted_at] = int(row.value)

    precision = _pick(table, "precision", positive)
    recall = _pick(table, "recall", positive)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = _number(2 * precision * recall / (precision + recall))
    # Balanced accuracy is the mean of the per-class recalls, and it is read off
    # the matrix rather than the metric table on purpose: with ``pos_label`` set
    # skore reports the *positive* class's recall under the bare name ``recall``,
    # so averaging what the table offers would report the positive recall twice
    # and call it balanced.
    per_class = [
        row[position] / sum(row)
        for position, row in enumerate(matrix)
        if sum(row)
    ]
    balanced = _number(sum(per_class) / len(per_class)) if per_class else None

    ordered = [
        ("roc_auc", _pick(table, "roc_auc", positive)),
        ("accuracy", table.get("accuracy")),
        ("balanced_accuracy", balanced),
        ("f1", f1),
        ("precision", precision),
        ("recall", recall),
        ("log_loss", table.get("log_loss")),
        ("brier_score", table.get("brier_score")),
    ]
    scores = [
        {"key": key, "value": value} for key, value in ordered if value is not None
    ]

    curves: dict = {}
    if binary:
        try:
            curves["roc"] = _curve(
                report.metrics.roc().frame(), "fpr", "tpr", limit=curve_points
            )
            curves["pr"] = _curve(
                report.metrics.precision_recall().frame(),
                "recall",
                "precision",
                limit=curve_points,
            )
            # The PR curve's chance line is the positive rate, not 0.5.
            truth = report.y_test
            curves["baseline"] = _number(
                sum(1 for value in truth if _label(value) == positive) / len(truth)
            )
        except Exception:  # noqa: BLE001 - a curve is never worth failing a fit on
            curves.pop("roc", None)
            curves.pop("pr", None)

    return {
        "primary": scores[0] if scores else {"key": "accuracy", "value": None},
        "scores": scores,
        "confusion": {
            "labels": [_label(value) for value in labels],
            "matrix": matrix,
        },
        "curves": curves,
    }


def _regression_metrics(report, *, curve_points: int) -> dict:
    """The regression read model. skore reports rmse and mape natively.

    Note the unit skew: skore's ``mape`` is a ratio, the card's tile is a
    percentage.
    """

    import numpy as np

    table = _summary_table(report.metrics.summarize())
    ordered = [
        ("r2", table.get("r2")),
        ("mae", table.get("mae")),
        ("rmse", table.get("rmse")),
        (
            "mape",
            None if table.get("mape") is None else _number(table["mape"] * 100),
        ),
    ]
    scores = [
        {"key": key, "value": value} for key, value in ordered if value is not None
    ]

    errors = report.metrics.prediction_error().frame()
    actual = np.asarray(errors["y_true"], dtype="float64")
    guess = np.asarray(errors["y_pred"], dtype="float64")
    order = np.argsort(actual)
    return {
        "primary": scores[0] if scores else {"key": "r2", "value": None},
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


def _importances(report, *, rows: int, scoring: str, seed: int):
    """Permutation importance on a capped sample: the honest feature ranking.

    Capped by ``max_samples`` because it refits nothing but predicts
    ``n_repeats`` times per column, and a model card is not worth minutes of CPU.
    """

    test_rows = len(report.X_test)
    if test_rows < 20:
        return []
    fraction = 1.0 if rows >= test_rows else max(float(rows) / test_rows, 0.01)
    try:
        frame = report.inspection.permutation_importance(
            metric=scoring,
            n_repeats=3,
            max_samples=fraction,
            seed=seed,
            n_jobs=1,
        ).frame()
    except Exception:  # noqa: BLE001 - decoration, never a blocker
        return []
    ranked = [
        {"feature": str(row.feature), "value": _number(row.value_mean)}
        for row in frame.itertuples()
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


def _persist_report(report, path: str | None, *, limit_bytes: int) -> dict | None:
    """Write the report's own state beside the model. ``None`` when it is skipped.

    ``to_dict`` is skore's documented way to persist a report — deliberately not
    a pickle of the object, so a later skore can still read it. The state carries
    the split and the cached predictions, which is exactly the part
    ``result.json`` throws away: with it, a metric nobody asked for at fit time
    can still be computed later on *the rows the card reports on*.

    Guarded by a byte ceiling rather than a row count, because what makes a state
    large is the width of the frame as much as its length, and only the finished
    dump knows. Written to a temporary name and moved into place, so a reader
    never finds a half-written state; skipped, never fatal, because this is
    evidence about a fit and not the fit.
    """

    if not path:
        return None
    try:
        import joblib
        import skore

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_suffix(".partial")
        joblib.dump(report.to_dict(), staging, compress=3)
        written = staging.stat().st_size
        if written > limit_bytes:
            staging.unlink(missing_ok=True)
            return {"skipped": "too_large", "bytes": int(written)}
        os.replace(staging, target)
        return {"bytes": int(written), "skore": str(skore.__version__)}
    except Exception as exc:  # noqa: BLE001 - evidence about a fit, not the fit
        print(f"ml_report_state_unwritten: {exc}", file=sys.stderr, flush=True)
        return None


def _configure_text_encoder(pipeline, spec, seed):
    encoder = (spec or {}).get("text_encoder", "auto")
    if encoder != "auto":
        from skrub import MinHashEncoder, StringEncoder

        # Encoding is fitted inside the pipeline, so held-out vocabulary never
        # reaches the model. Explicit choices only replace high-cardinality text.
        vectorizer = pipeline.named_steps.get("tablevectorizer")
        if vectorizer is not None:
            vectorizer.set_params(high_cardinality=(
                StringEncoder(random_state=seed) if encoder == "string"
                else MinHashEncoder(n_jobs=1)
            ))


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
    report_path = manifest.get("report_path")
    report_limit_mb = float(manifest.get("report_state_limit_mb") or 0)
    seed = int(manifest["random_state"]) if manifest.get("random_state") is not None else 42
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

    from sklearn.base import clone
    from sklearn.model_selection import train_test_split

    try:
        from skrub import tabular_pipeline
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

    # `tabular_pipeline` asks the estimator what it needs and assembles it:
    # vectorize the frame, impute where the estimator refuses holes, scale where
    # it reads magnitudes as importance. Letting skrub decide rather than listing
    # the rules here is not laziness — the rules are a property of the estimator,
    # and a hand-kept list of which ones tolerate NaN goes stale silently the
    # first time sklearn changes its mind (it did: RandomForest accepts missing
    # numerics from 1.4 on, and a list written before that would still be paying
    # for an imputer it no longer needs).
    pipeline = tabular_pipeline(estimator)
    _configure_text_encoder(pipeline, manifest.get("spec"), seed)
    imputer = pipeline.named_steps.get("simpleimputer")
    if imputer is not None:
        # The one judgement skrub cannot make for us. Median rather than its
        # default mean because a survey score or an ARPU is skewed often enough
        # that the mean is not a plausible value — filling a hole with a number
        # nobody could have had is worse than filling it with a typical one.
        imputer.set_params(strategy="median")
    print(f"fitting {type(estimator).__name__} on {len(x_train)} rows", flush=True)
    _progress(progress_path, f"fitting:{len(x_train)}")
    try:
        pipeline.fit(x_train, y_train)
    except Exception as exc:  # noqa: BLE001 - the algorithm's refusal is the answer
        return _fail(1, f"ml_fit_failed: {type(exc).__name__}: {exc}")

    _progress(progress_path, "scoring")
    if task == "classification" and hasattr(pipeline, "classes_"):
        classes = list(pipeline.classes_)

    try:
        from skore import EstimatorReport
    except ImportError as exc:  # pragma: no cover - the app venv has skore
        return _fail(5, f"skore_missing: {exc}")

    # One report, one pass over the test split: skore caches the predictions, so
    # the table, the curves, the matrix and the importances below all read the
    # same cached arrays. The estimator is already fitted, so no train data is
    # handed over — skore rejects that combination on purpose.
    binary = task == "classification" and len(classes) == 2
    try:
        report = EstimatorReport(
            pipeline,
            X_test=x_test,
            y_test=y_test,
            **({"pos_label": classes[-1]} if binary else {}),
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(1, f"ml_report_failed: {type(exc).__name__}: {exc}")

    if task == "classification":
        metrics = _classification_metrics(
            report, classes, curve_points=curve_points
        )
        scoring = "roc_auc" if binary else "accuracy"
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
        metrics = _regression_metrics(report, curve_points=curve_points)
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
        report, rows=importance_rows, scoring=scoring, seed=seed
    )

    if folds >= 2:
        # A single split reports one number and hides its own variance. skore's
        # cross-validation report gives every metric a spread across folds, which
        # is the honest way to say "0.86" — and the only way to tell a real
        # improvement from a lucky split when two versions are compared.
        from skore import CrossValidationReport

        _progress(progress_path, f"validating:0/{folds}")
        try:
            folded = CrossValidationReport(
                clone(pipeline),
                X=x_train,
                y=y_train,
                splitter=_NarratedSplitter(
                    _fold_splitter(folds, task, y_train), folds, progress_path
                ),
                n_jobs=1,
                **({"pos_label": classes[-1]} if binary else {}),
            )
            table = folded.metrics.summarize().frame()
            means = [name for name in table.columns if name.endswith("_mean")]
            spreads = [name for name in table.columns if name.endswith("_std")]
            per_metric = []
            for name in table.index:
                # Only the keys the card has a label for. skore also reports
                # timings, and per-class rows when the target is multiclass;
                # neither belongs in a row of "metric ± spread" chips.
                if str(name) not in _CARD_METRICS:
                    continue
                mean = _number(table.loc[name, means[0]]) if means else None
                spread = _number(table.loc[name, spreads[0]]) if spreads else None
                if str(name) == "mape":
                    # Same unit skew as the single-split table: skore reports a
                    # ratio, the card's tile reads a percentage.
                    mean = None if mean is None else _number(mean * 100)
                    spread = None if spread is None else _number(spread * 100)
                if mean is not None:
                    per_metric.append(
                        {"key": str(name), "mean": mean, "std": spread}
                    )
            headline = next(
                (row for row in per_metric if row["key"] == scoring), None
            ) or next(iter(per_metric), None)
            metrics["cv"] = {
                "folds": folds,
                "metric": scoring,
                "mean": (headline or {}).get("mean"),
                "std": (headline or {}).get("std"),
                "metrics": per_metric,
            }
        except Exception as exc:  # noqa: BLE001 - a fold that fails is not a fit that fails
            metrics["cv"] = {"folds": folds, "metric": scoring, "error": str(exc)[:200]}

    # After the metrics, so the state carries the predictions they were read
    # from rather than making the next reader recompute them.
    report_state = (
        _persist_report(
            report, report_path, limit_bytes=int(report_limit_mb * 1024 * 1024)
        )
        if report_limit_mb > 0
        else None
    )

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
        "report_state": report_state,
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
