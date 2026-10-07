"""Calibration and threshold selection using training rows only.

Loaded by path by the standalone harness. Fitting deliberately cannot receive a
holdout: evaluating calibration and decisions is a separate operation below.
Only sklearn classes enter the portable artifact.
"""
from __future__ import annotations


def enabled(spec):
    return spec.get("calibration", "off") != "off" or spec.get("threshold", "default") != "default"


def _threshold(y, probability, criterion, positive):
    import numpy as np
    from sklearn.metrics import precision_recall_curve, roc_curve

    binary = np.asarray(y) == positive
    if criterion == "f1":
        precision, recall, thresholds = precision_recall_curve(binary, probability)
        scores = np.divide(2 * precision[:-1] * recall[:-1], precision[:-1] + recall[:-1],
                           out=np.zeros_like(thresholds), where=(precision[:-1] + recall[:-1]) > 0)
    else:
        fpr, tpr, thresholds = roc_curve(binary, probability, drop_intermediate=False)
        scores = tpr - fpr
    finite = np.isfinite(thresholds) & (thresholds >= 0) & (thresholds <= 1)
    thresholds, scores = thresholds[finite], scores[finite]
    best = np.flatnonzero(scores == scores.max())
    # Ties prefer the closest decision to 0.5, then the smaller threshold.
    at = min(best, key=lambda i: (abs(float(thresholds[i]) - 0.5), float(thresholds[i])))
    return float(thresholds[at])


def fit(pipeline, x_train, y_train, *, spec, seed, folds, progress):
    import numpy as np
    from sklearn.base import clone
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator
    from sklearn.model_selection import FixedThresholdClassifier, StratifiedKFold, cross_val_predict, train_test_split

    method = spec.get("calibration", "off")
    criterion = spec.get("threshold", "default")
    x_fit, y_fit = x_train, y_train
    x_cal = y_cal = None
    context = {"warnings": []}
    if method != "off":
        try:
            fit_x, cal_x, fit_y, cal_y = train_test_split(
                x_train, y_train, test_size=0.2, stratify=y_train, random_state=seed,
            )
            if len(cal_y) >= 200 and cal_y.value_counts().min() >= 20:
                x_fit, y_fit, x_cal, y_cal = fit_x, fit_y, cal_x, cal_y
        except ValueError:
            pass  # A tiny rare class cannot be split; the full train remains usable.
        if x_cal is None:
            context["warnings"].append({"code": "ML_CALIBRATION_TOO_FEW"})
    progress(f"fitting:{len(x_fit)}")
    pipeline.fit(x_fit, y_fit)
    served = pipeline
    context["base"] = pipeline
    if x_cal is not None:
        progress("calibrating")
        method = ("isotonic" if len(x_cal) >= 1000 else "sigmoid") if method == "auto" else method
        served = CalibratedClassifierCV(FrozenEstimator(pipeline), method=method, n_jobs=1).fit(x_cal, y_cal)
        context["calibration"] = {"method": method, "fit_rows": len(x_fit), "calibration_rows": len(x_cal)}
    context["default"] = served
    classes = list(served.classes_)
    if criterion != "default" and len(classes) == 2:
        progress("calibrating")
        positive = classes[-1]
        if x_cal is not None:
            probability = served.predict_proba(x_cal)[:, -1]
            truth = y_cal
            source = "calibration"
        else:
            count = min(folds if folds >= 2 else 5, int(y_train.value_counts().min()))
            if count < 2:
                context["warnings"].append({"code": "ML_THRESHOLD_TOO_FEW"})
                return served, context
            splitter = StratifiedKFold(n_splits=count)
            def narrated():
                for k, split in enumerate(splitter.split(x_train, y_train), 1):
                    progress(f"calibrating:{k}/{count}")
                    yield split
            probability = cross_val_predict(clone(pipeline), x_train, y_train, cv=narrated(),
                                             method="predict_proba", n_jobs=1)[:, -1]
            truth = y_train
            source = "cross_validation"
        threshold = _threshold(truth, probability, criterion, positive)
        # FrozenEstimator prevents fit() cloning/refitting away the calibrated
        # state; FixedThresholdClassifier itself is portable sklearn behavior.
        served = FixedThresholdClassifier(FrozenEstimator(served), threshold=threshold,
                                          pos_label=positive, response_method="predict_proba").fit(x_train, y_train)
        context["decision"] = {"threshold": threshold, "criterion": criterion, "source": source}
    elif criterion != "default":
        context["warnings"].append({"code": "ML_THRESHOLD_BINARY_ONLY"})
    return served, context


def evaluate(served, context, x_test, y_test, *, number):
    import numpy as np
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import accuracy_score, brier_score_loss, f1_score, log_loss, precision_score, recall_score

    result = {}
    classes = list(served.classes_)
    positive = classes[-1]
    binary = len(classes) == 2
    if context.get("warnings"):
        result["warnings"] = context["warnings"]
    if "calibration" in context:
        calibration = dict(context["calibration"])
        for key, model in (("before", context["base"]), ("after", context["default"])):
            probability = model.predict_proba(x_test)
            values = {"brier_score": number(brier_score_loss(y_test, probability, labels=classes)),
                      "log_loss": number(log_loss(y_test, probability, labels=classes))}
            if binary:
                observed, predicted = calibration_curve(np.asarray(y_test) == positive, probability[:, -1],
                                                        n_bins=10, strategy="quantile")
                values["curve"] = [{"x": number(x), "y": number(y)} for x, y in zip(predicted, observed)]
            calibration[key] = values
        result["calibration"] = calibration
    if "decision" in context:
        decision = dict(context["decision"])
        for key, model in (("default_metrics", context["default"]), ("tuned_metrics", served)):
            predicted = model.predict(x_test)
            decision[key] = {
                "accuracy": number(accuracy_score(y_test, predicted)),
                "precision": number(precision_score(y_test, predicted, pos_label=positive, zero_division=0)),
                "recall": number(recall_score(y_test, predicted, pos_label=positive, zero_division=0)),
                "f1": number(f1_score(y_test, predicted, pos_label=positive, zero_division=0)),
            }
        result["decision"] = decision
    return result


def cross_validation(pipeline, x_train, y_train, *, spec, seed, folds, progress, summarize, number):
    """Refit every extension inside each fold; cloning a frozen fit would leak."""
    import numpy as np
    from sklearn.base import clone
    from sklearn.model_selection import StratifiedKFold
    from skore import EstimatorReport

    tables = []
    for k, (train, test) in enumerate(StratifiedKFold(n_splits=folds).split(x_train, y_train), 1):
        progress(f"validating:{k}/{folds}")
        model, _ = fit(clone(pipeline), x_train.iloc[train], y_train.iloc[train], spec=spec,
                       seed=seed, folds=folds, progress=lambda _: None)
        classes = list(model.classes_)
        report = EstimatorReport(model, X_test=x_train.iloc[test], y_test=y_train.iloc[test],
                                 **({"pos_label": classes[-1]} if len(classes) == 2 else {}))
        tables.append({row["key"]: row["value"] for row in summarize(report, classes)["scores"]})
    metrics = [{"key": key, "mean": number(np.mean([table[key] for table in tables])),
                "std": number(np.std([table[key] for table in tables]))}
               for key in tables[0] if all(table.get(key) is not None for table in tables)]
    scoring = "roc_auc" if len(model.classes_) == 2 else "accuracy"
    headline = next((row for row in metrics if row["key"] == scoring), {})
    return {"folds": folds, "metric": scoring, "mean": headline.get("mean"),
            "std": headline.get("std"), "metrics": metrics}
