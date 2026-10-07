"""Small, bounded explanations of the served model on its held-out rows.

This sibling of the training harness has no application imports. Each section
is expendable evidence: an unsupported transformer or an exhausted deadline
must never turn a successful fit into a failed model.
"""
from __future__ import annotations

import json
import math
import time

EXPLAIN_ROWS = 5000
EXPLAIN_BUDGET_S = 60.0
EXPLAIN_MAX_BYTES = 200_000

def _number(value):
    try:
        value = float(value)
        return round(value, 6) if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _scalar(value):
    import numpy as np
    import pandas as pd
    if pd.isna(value):
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return _number(value)
    return str(value)[:200]


def inner_pipeline(model):
    # Same lightweight unwrapping as services.ml.model_structure. The harness
    # executes by path and cannot import app; predictions always use the outer
    # model, while only tree explanations inspect transformed feature columns.
    seen = set()
    wrappers = {"FixedThresholdClassifier", "CalibratedClassifierCV", "FrozenEstimator"}
    while type(model).__name__ in wrappers and id(model) not in seen:
        seen.add(id(model))
        model = getattr(model, "estimator_", None) or getattr(model, "estimator", model)
    return model


def _matrix(model, x):
    transform = inner_pipeline(model)[:-1]
    values = transform.transform(x)
    try:
        names = [str(value) for value in transform.get_feature_names_out()]
    except (AttributeError, ValueError):
        names = [str(name) for name in getattr(values, "columns", [])]
    if len(names) != values.shape[1]:
        names = [f"feature_{index}" for index in range(values.shape[1])]
    return values, names


def _paths(tree, names):
    paths = {}
    def visit(node, rules):
        feature = int(tree.tree_.feature[node])
        if feature < 0:
            paths[node] = rules
            return
        common = {"feature": names[feature], "value": _number(tree.tree_.threshold[node])}
        visit(tree.tree_.children_left[node], rules + [{**common, "op": "<="}])
        visit(tree.tree_.children_right[node], rules + [{**common, "op": ">"}])
    visit(0, [])
    return paths


def error_tree(model, x, y, *, task, seed):
    import numpy as np
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
    matrix, names = _matrix(model, x)
    predicted = model.predict(x)
    errors = (np.asarray(predicted) != np.asarray(y)) if task == "classification" else np.abs(np.asarray(predicted) - np.asarray(y))
    factory = DecisionTreeClassifier if task == "classification" else DecisionTreeRegressor
    tree = factory(max_depth=3, min_samples_leaf=max(20, math.ceil(0.02 * len(x))), random_state=seed).fit(matrix, errors)
    leaves = tree.apply(matrix)
    global_error = float(np.mean(errors))
    rows = []
    for leaf, rule in _paths(tree, names).items():
        mask = leaves == leaf
        error = float(np.mean(errors[mask]))
        rows.append({"rule": rule, "rows": int(mask.sum()), "error": _number(error),
                     "global_error": _number(global_error), "lift": _number(error / global_error) if global_error else None})
    rows.sort(key=lambda row: ((row["error"] - global_error) * row["rows"], row["rows"]), reverse=True)
    return {"rules": rows[:5], "global_error": _number(global_error), "rows": len(x)}


def surrogate(model, x, *, task, seed):
    import numpy as np
    from sklearn.metrics import accuracy_score, r2_score
    from sklearn.model_selection import train_test_split
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
    matrix, names = _matrix(model, x)
    predicted = np.asarray(model.predict(x))
    train, test = train_test_split(np.arange(len(x)), test_size=0.3, random_state=seed)
    subset = lambda positions: matrix.iloc[positions] if hasattr(matrix, "iloc") else matrix[positions]
    factory = DecisionTreeClassifier if task == "classification" else DecisionTreeRegressor
    tree = factory(max_depth=3, min_samples_leaf=max(20, math.ceil(0.02 * len(train))), random_state=seed).fit(subset(train), predicted[train])
    score = (accuracy_score if task == "classification" else r2_score)(predicted[test], tree.predict(subset(test)))
    score = float(score) if math.isfinite(float(score)) else 0.0
    leaves = tree.apply(subset(train))
    rows = []
    for leaf, rule in _paths(tree, names).items():
        mask = leaves == leaf
        guesses = predicted[train][mask]
        if task == "classification":
            values, counts = np.unique(guesses, return_counts=True)
            value = values[int(np.argmax(counts))]
        else:
            value = np.mean(guesses)
        rows.append({"rule": rule, "rows": int(mask.sum()), "prediction": _scalar(value)})
    rows.sort(key=lambda row: row["rows"], reverse=True)
    # A negative R² is retained as raw_fidelity; the display score has a floor
    # of zero so its 0–1 badge never implies a usable simplified explanation.
    return {"fidelity": _number(max(0, min(1, score))), "raw_fidelity": _number(score),
            "metric": "accuracy" if task == "classification" else "r2", "rules": rows[:5],
            "train_rows": len(train), "validation_rows": len(test)}


def partial_effect(model, x, feature, *, task, seed):
    import numpy as np
    import pandas as pd
    from sklearn.inspection import partial_dependence
    sample = x.sample(n=min(len(x), 1000), random_state=seed)
    categorical = not pd.api.types.is_numeric_dtype(sample[feature]) or pd.api.types.is_bool_dtype(sample[feature])
    custom = None
    if categorical:
        values = sorted(sample[feature].dropna().unique(), key=str)
        if not values:
            return {"feature": feature, "error": "empty"}
        custom = {list(sample.columns).index(feature): np.asarray(values[:20])}
    # sklearn does not support categorical ICE. Its average still supplies the
    # PDP; thirty direct interventions below supply the corresponding ICE.
    result = partial_dependence(model, sample, [feature], kind="average" if categorical else "both",
                                method="brute", response_method="predict_proba" if task == "classification" else "auto",
                                categorical_features=[feature] if categorical else None, grid_resolution=20,
                                custom_values=custom)
    grid = result.grid_values[0]
    classes = list(getattr(model, "classes_", []))
    target = len(classes) - 1 if len(classes) > 2 else 0
    if categorical:
        individuals = sample.sample(n=min(30, len(sample)), random_state=seed)
        columns = []
        for value in grid:
            changed = individuals.copy()
            changed[feature] = value
            prediction = model.predict_proba(changed)[:, -1] if task == "classification" else model.predict(changed)
            columns.append(prediction)
        ice = np.asarray(columns).T
    else:
        individual = result.individual[target]
        chosen = np.random.default_rng(seed).choice(len(individual), min(30, len(individual)), replace=False)
        ice = individual[chosen]
    return {"feature": feature, "kind": "categorical" if categorical else "numeric",
            "grid": [_scalar(value) for value in grid],
            "average": [_number(value) for value in result.average[target]],
            "ice": [[_number(value) for value in row] for row in ice],
            **({"class": _scalar(classes[-1])} if task == "classification" else {})}


def fairness(model, x, y, groups, *, task):
    import numpy as np
    import pandas as pd
    predicted = np.asarray(model.predict(x))
    truth = np.asarray(y)
    classes = list(getattr(model, "classes_", []))
    binary = task == "classification" and len(classes) == 2
    positive = classes[-1] if binary else None
    overall_mae = float(np.mean(np.abs(predicted - truth))) if task == "regression" else None
    result = []
    for name in groups.columns[:3]:
        column = groups[name]
        values = list(column.dropna().unique())
        if column.isna().any():
            values.append(None)
        if len(values) > 12:
            result.append({"column": str(name), "error": "too_many_groups"})
            continue
        rows = []
        for value in sorted(values, key=str):
            mask = np.asarray(column.isna() if value is None else column == value)
            actual, guess = truth[mask], predicted[mask]
            row = {"group": _scalar(value), "n": int(mask.sum()), "low_support": int(mask.sum()) < 30}
            if task == "regression":
                row.update(mae=_number(np.mean(np.abs(guess - actual))), bias=_number(np.mean(guess - actual)))
            else:
                row["accuracy"] = _number(np.mean(guess == actual))
                if binary:
                    selected = guess == positive
                    positives, negatives = actual == positive, actual != positive
                    row.update(selection_rate=_number(np.mean(selected)),
                               tpr=_number(np.mean(selected[positives])) if positives.any() else None,
                               fpr=_number(np.mean(selected[negatives])) if negatives.any() else None)
            rows.append(row)
        supported = [row for row in rows if not row["low_support"]]
        disparities = {}
        if binary and len(supported) >= 2:
            rates = [row["selection_rate"] for row in supported]
            disparities["selection_ratio"] = _number(min(rates) / max(rates)) if max(rates) else None
            gaps = []
            for key in ("tpr", "fpr"):
                measured = [row[key] for row in supported if row[key] is not None]
                if len(measured) >= 2:
                    gaps.append(max(measured) - min(measured))
            disparities["equalized_odds_diff"] = _number(max(gaps)) if gaps else None
        elif task == "regression" and len(supported) >= 2:
            maes = [row["mae"] for row in supported]
            disparities["mae_gap_ratio"] = _number((max(maes) - min(maes)) / overall_mae) if overall_mae else 0.0
        ratio = disparities.get("selection_ratio")
        result.append({"column": str(name), "groups": rows, **disparities,
                       "signal": ratio is not None and ratio < 0.8})
    return result


def _bounded(result):
    # Thin ICE before discarding evidence; one pipe message and the stored
    # metrics block share the same byte ceiling.
    if len(json.dumps(result, allow_nan=False).encode()) > EXPLAIN_MAX_BYTES:
        for item in result.get("pdp", []):
            item["ice"] = item.get("ice", [])[:10]
    return result if len(json.dumps(result, allow_nan=False).encode()) <= EXPLAIN_MAX_BYTES else {"error": "too_large"}


def _initial_result(x, names, groups, budget):
    result = {"rows": min(len(x), EXPLAIN_ROWS), "budget_s": budget,
              "error_tree": {"error": "budget"}, "surrogate": {"error": "budget"},
              "pdp": [{"feature": name, "error": "budget"} for name in names]}
    if groups is not None and len(groups.columns):
        result["fairness"] = {"error": "budget"}
    return result


def _pack_child(connection, model, x_test, y_test, task, seed, names, groups, budget):
    import numpy as np
    started = time.monotonic()
    result = _initial_result(x_test, names, groups, budget)
    positions = np.random.default_rng(seed).choice(len(x_test), min(len(x_test), EXPLAIN_ROWS), replace=False)
    x, y = x_test.iloc[positions], y_test.iloc[positions]
    protected = groups.iloc[positions] if groups is not None else None

    def publish():
        result["elapsed_s"] = _number(time.monotonic() - started)
        connection.send_bytes(json.dumps(_bounded(result), allow_nan=False).encode())

    def run(callback):
        if time.monotonic() - started >= budget:
            return {"error": "budget"}
        try:
            return callback()
        except Exception as exc:  # Each failed section leaves the others usable.
            return {"error": f"{type(exc).__name__}: {exc}"[:180]}

    try:
        result["error_tree"] = run(lambda: error_tree(model, x, y, task=task, seed=seed))
        publish()
        result["surrogate"] = run(lambda: surrogate(model, x, task=task, seed=seed))
        publish()
        for index, name in enumerate(names):
            result["pdp"][index] = {"feature": name, **run(lambda name=name: partial_effect(model, x, name, task=task, seed=seed))}
            publish()
        if protected is not None and len(protected.columns):
            result["fairness"] = run(lambda: fairness(model, x, y, protected, task=task))
            publish()
    finally:
        connection.close()


def pack(model, x_test, y_test, *, task, seed, importances, groups=None, budget_s=None):
    """A hard wall-clock budget, including native sklearn/BLAS work.

    Training already runs in a POSIX subprocess. A fork here inherits the fit
    without pickling a potentially large forest. The parent owns the clock and
    keeps a bounded JSON snapshot after each completed section; terminating a
    stuck native operation cannot lose the model or already-computed evidence.
    """
    import multiprocessing
    budget = EXPLAIN_BUDGET_S if budget_s is None else max(0, min(float(budget_s), EXPLAIN_BUDGET_S))
    started = time.monotonic()
    names = list(dict.fromkeys(str(row.get("feature")) for row in importances if str(row.get("feature")) in x_test.columns))[:4]
    result = _initial_result(x_test, names, groups, budget)
    if budget <= 0:
        return result
    try:
        context = multiprocessing.get_context("fork")
        receiver, sender = context.Pipe(duplex=False)
        worker = context.Process(target=_pack_child,
            args=(sender, model, x_test, y_test, task, seed, names, groups, budget), daemon=True)
        worker.start()
        sender.close()
    except Exception as exc:
        return {"error": f"worker_unavailable: {type(exc).__name__}"}
    try:
        while True:
            remaining = budget - (time.monotonic() - started)
            if remaining <= 0:
                break
            if receiver.poll(min(remaining, 0.05)):
                try:
                    result = json.loads(receiver.recv_bytes(maxlength=max(1024, EXPLAIN_MAX_BYTES)))
                except (EOFError, OSError, ValueError):
                    break
            elif not worker.is_alive():
                break
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=0.05)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=0.05)
        receiver.close()
    result["elapsed_s"] = _number(time.monotonic() - started)
    return _bounded(result)
