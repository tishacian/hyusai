"""Targetless numeric KMeans, fitted and exported as a native sklearn pipeline.

All rows fit the final segmentation. Silhouette is an internal, bounded-sample
description; stability compares assignments after refitting *all preprocessing*
on three independent 80% subsamples. Neither is held-out predictive accuracy.
The exported model contains no application class and needs no network access.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

MAX_ROWS = 50_000
MAX_FEATURES = 50
SAMPLE_ROWS = 2_000
STABILITY_RUNS = 3


def _shared():
    spec = importlib.util.spec_from_file_location(
        "agentium_ml_train_harness", Path(__file__).with_name("ml_train_harness.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _number(value):
    number = float(value)
    return number if math.isfinite(number) else None


def read_frame(path: str, features: list[str], *, min_rows: int, clusters: int):
    """Enforce bounds against the actual file, not only its registry profile."""
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    if (not isinstance(features, list) or not 1 <= len(features) <= MAX_FEATURES
            or not all(isinstance(name, str) and name for name in features)
            or len(set(features)) != len(features)):
        raise ValueError("clustering requires explicit, unique numeric features")
    rows = pq.ParquetFile(path).metadata.num_rows
    if not max(min_rows, 2 * clusters) <= rows <= MAX_ROWS:
        raise ValueError(f"clustering row count must be in [{max(min_rows, 2 * clusters)}, {MAX_ROWS}]")
    frame = pd.read_parquet(path, columns=features)
    for name in features:
        column = frame[name]
        if (not pd.api.types.is_numeric_dtype(column) or pd.api.types.is_bool_dtype(column)
                or pd.api.types.is_complex_dtype(column)):
            raise ValueError(f"feature {name!r} must be numeric")
        frame[name] = column.astype("float64")
        if np.isinf(frame[name].to_numpy()).any():
            raise ValueError(f"feature {name!r} contains infinite values")
        if frame[name].isna().all():
            raise ValueError(f"feature {name!r} has no observed values")
    return frame


def make_pipeline(*, clusters: int, max_iter: int, seed: int):
    from sklearn.cluster import KMeans
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("kmeans", KMeans(n_clusters=clusters, n_init=10, max_iter=max_iter,
                          random_state=seed, algorithm="lloyd")),
    ])


def stability(frame, labels, *, clusters: int, max_iter: int, seed: int, sample, progress=None):
    """ARI is invariant to cluster label permutations; labels are not classes.

    The reference assignments come from the final fit, including sample rows.
    This measures sensitivity to resampling, not performance on unseen labels.
    """
    import numpy as np
    from sklearn.metrics import adjusted_rand_score

    rng = np.random.default_rng(seed)
    size = int(math.floor(len(frame) * .8))
    values = []
    reasons = []
    for run in range(STABILITY_RUNS):
        if progress:
            progress(f"validating:{run + 1}/{STABILITY_RUNS}")
        selected = rng.choice(len(frame), size=size, replace=False)
        candidate = make_pipeline(clusters=clusters, max_iter=max_iter, seed=(seed + run + 1) % 2**32)
        candidate.fit(frame.iloc[selected])
        if len(np.unique(candidate.named_steps["kmeans"].labels_)) != clusters:
            reasons.append("insufficient_distinct_subsample")
            continue
        if candidate.named_steps["kmeans"].n_iter_ >= max_iter:
            reasons.append("iteration_limit")
        assigned = candidate.predict(frame.iloc[sample])
        values.append(float(adjusted_rand_score(labels[sample], assigned)))
    complete = len(values) == STABILITY_RUNS
    return {
        "metric": "adjusted_rand_index", "runs": STABILITY_RUNS, "valid_runs": len(values),
        "sample_rows": len(sample), "subsample_rows": size, "subsample_fraction": .8,
        "values": values, "mean": float(np.mean(values)) if complete else None,
        "std": float(np.std(values)) if complete else None,
        "min": min(values) if complete else None,
        **({"reason": reasons[0]} if reasons else {}),
    }


def profiles(frame, labels, *, clusters: int):
    """Profiles describe observed values in original units, never imputed ones."""
    baseline = {name: (frame[name].mean(), frame[name].std(ddof=0)) for name in frame}
    groups = []
    for group in range(clusters):
        rows = frame.iloc[labels == group]
        features = []
        for name in frame:
            column = rows[name]
            mean, spread = baseline[name]
            group_mean = column.mean()
            features.append({
                "feature": name, "mean": _number(group_mean), "median": _number(column.median()),
                "std": _number(column.std(ddof=0)), "missing": int(column.isna().sum()),
                "overall_mean": _number(mean),
                "standardized_difference": _number((group_mean - mean) / spread) if spread > 0 else None,
            })
        groups.append({"cluster": group, "count": len(rows), "share": len(rows) / len(frame),
                       "features": features})
    return groups


def train(frame, *, clusters: int, max_iter: int, seed: int, progress=None):
    import numpy as np
    from sklearn.metrics import silhouette_score

    if progress:
        progress(f"fitting:{len(frame)}")
    model = make_pipeline(clusters=clusters, max_iter=max_iter, seed=seed)
    transformed = model[:-1].fit_transform(frame)
    if len(np.unique(transformed, axis=0)) < clusters:
        raise ValueError("fewer distinct numeric profiles than requested groups")
    labels = model.named_steps["kmeans"].fit_predict(transformed)
    if len(np.unique(labels)) != clusters:
        raise ValueError("the selected variables cannot separate the requested groups")
    if progress:
        progress("scoring")
    sample = np.sort(np.random.default_rng(seed).choice(len(frame), min(SAMPLE_ROWS, len(frame)), replace=False))
    sampled_labels = labels[sample]
    unique = len(np.unique(sampled_labels))
    silhouette = {"value": None, "sample_rows": len(sample), "sample_clusters": unique}
    if 2 <= unique < len(sample):
        silhouette["value"] = _number(silhouette_score(transformed[sample], sampled_labels))
    else:
        silhouette["reason"] = "insufficient_sample_groups"
    stability_result = stability(frame, labels, clusters=clusters, max_iter=max_iter,
                                 seed=seed, sample=sample, progress=progress)
    warnings = []
    constants = [name for name in frame if frame[name].nunique(dropna=True) <= 1]
    if constants:
        warnings.append({"code": "ML_CLUSTER_CONSTANT_FEATURES", "features": constants})
    empty_rows = int(frame.isna().all(axis=1).sum())
    if empty_rows:
        warnings.append({"code": "ML_CLUSTER_IMPUTED_ROWS", "rows": empty_rows})
    if model.named_steps["kmeans"].n_iter_ >= max_iter:
        warnings.append({"code": "ML_CLUSTER_ITERATION_LIMIT"})
    if stability_result.get("reason"):
        warnings.append({"code": "ML_CLUSTER_STABILITY_PARTIAL", "reason": stability_result["reason"]})
    metrics = {
        "task": "clustering", "primary": {"key": "silhouette", "value": silhouette["value"]},
        "scores": [{"key": "silhouette", "value": silhouette["value"]},
                   {"key": "stability_ari", "value": stability_result["mean"]}],
        "rows": {"total": len(frame), "train": len(frame), "test": 0},
        "columns": {"used": list(frame.columns), "dropped": []}, "warnings": warnings,
        "clustering": {
            "algorithm": "kmeans", "n_clusters": clusters, "features": list(frame.columns),
            "rows": len(frame), "silhouette": silhouette, "stability": stability_result,
            "clusters": profiles(frame, labels, clusters=clusters), "warnings": warnings,
            "preprocessing": {"imputation": "median", "scaling": "standard"},
            "label_scope": "model_version", "random_state": seed,
        },
    }
    return model, metrics


def save(model, frame, model_dir: str):
    import mlflow.sklearn
    from mlflow.models import infer_signature
    from mlflow.models.signature import ModelSignature
    from mlflow.types import ColSpec, Schema

    shared = _shared()
    example = frame.head(3)
    # Doubles accept null values even when training had none. Require the
    # columns themselves; the native imputer handles holes within those columns.
    inferred = infer_signature(example, model.predict(example))
    signature = ModelSignature(
        inputs=Schema([ColSpec("double", name=name) for name in frame]),
        outputs=inferred.outputs,
    )
    trusted = shared._trusted_types(model)
    from importlib.metadata import version

    requirements = [f"{name}=={version(name)}" for name in
                    ("mlflow", "scikit-learn", "skops", "numpy", "scipy", "pandas")]
    mlflow.sklearn.save_model(model, path=model_dir, signature=signature, input_example=example,
                             serialization_format="skops", skops_trusted_types=trusted,
                             pip_requirements=requirements)
    bundle = Path(model_dir)
    files = {str(path.relative_to(bundle)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in bundle.rglob("*") if path.is_file()}
    inputs = shared._input_contract(frame, json.loads(signature.to_dict()["inputs"]))
    return {
        "signature": {"inputs": inputs, "output": {"task": "clustering", "target": "",
                      "classes": [], "clusters": list(range(model.named_steps["kmeans"].n_clusters))}},
        "classes": [], "input_example": [{name: shared._scalar(value) for name, value in row.items()}
                                        for _, row in example.iterrows()],
        "trusted_types": trusted, "artifact": {"serialization": "skops", "files": files},
    }


def main(argv=None) -> int:
    argv = argv or sys.argv
    if len(argv) != 3:
        return 5
    started = time.monotonic()
    shared = _shared()
    try:
        manifest = json.loads(Path(argv[1]).read_text())
        if (manifest.get("task") != "clustering" or manifest.get("family") != "clustering"
                or manifest.get("algo") != "kmeans" or manifest.get("target")
                or manifest.get("spec") or manifest.get("cv")):
            raise ValueError("expected targetless KMeans manifest without supervised options")
        params = manifest.get("params") or {}
        if set(params) - {"n_clusters", "max_iter", "n_init", "random_state"}:
            raise ValueError("unknown KMeans parameter")
        clusters, max_iter = params.get("n_clusters", 5), params.get("max_iter", 300)
        if (type(clusters) is not int or not 2 <= clusters <= 20
                or type(max_iter) is not int or not 50 <= max_iter <= 500
                or params.get("n_init", 10) != 10):
            raise ValueError("invalid KMeans budget")
        seed = int(manifest.get("random_state", 42))
        def progress(step):
            shared._progress(manifest.get("progress_path"), step)
        progress("reading")
        frame = read_frame(manifest["data_path"], manifest["features"],
                           min_rows=int(manifest.get("min_rows", 40)), clusters=clusters)
    except Exception as exc:
        return shared._fail(2, f"ml_cluster_data_unusable: {type(exc).__name__}: {exc}")
    try:
        model, metrics = train(frame, clusters=clusters, max_iter=max_iter, seed=seed, progress=progress)
    except ValueError as exc:
        return shared._fail(2, f"ml_cluster_data_unusable: {exc}")
    except Exception as exc:
        return shared._fail(1, f"ml_fit_failed: {type(exc).__name__}: {exc}")
    try:
        progress("saving")
        summary = {"metrics": metrics, **save(model, frame, manifest["model_dir"]),
                   "duration_ms": round((time.monotonic() - started) * 1000, 1)}
        Path(argv[2]).write_text(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        return shared._fail(4, f"ml_artifact_unwritable: {type(exc).__name__}: {exc}")
    print("trained", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
