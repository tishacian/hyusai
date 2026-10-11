"""Bounded offline TabICL train/holdout/export in the existing isolated worker."""

from __future__ import annotations

import json
import os
import sys
import time
from importlib.metadata import version
from pathlib import Path

if __package__:
    from .ml_artifact_contract import build_artifact_contract
    from .ml_evaluation import prepare, write_partition
    from .ml_tabicl_runtime import build_estimator, export_state, normalize_frame
else:
    from ml_artifact_contract import build_artifact_contract
    from ml_evaluation import prepare, write_partition
    from ml_tabicl_runtime import build_estimator, export_state, normalize_frame


def training_threads():
    """Honor the supervisor envelope, including deployments below four CPUs."""
    return max(1, min(4, int(os.environ.get("OMP_NUM_THREADS", "1"))))


def main(argv):
    if len(argv) != 3:
        return 5
    started = time.monotonic()
    try:
        import mlflow.pyfunc
        import numpy as np
        import pandas as pd
        from mlflow.models import infer_signature
        from sklearn.metrics import (
            accuracy_score,
            balanced_accuracy_score,
            f1_score,
            log_loss,
            mean_absolute_error,
            mean_squared_error,
            r2_score,
        )
        from sklearn.model_selection import train_test_split

        manifest = json.loads(Path(argv[1]).read_text())
        progress = Path(manifest["progress_path"])
        progress.write_text("reading")
        if (
            manifest.get("algo") != "tabicl_v2"
            or manifest.get("params")
            or manifest.get("cv")
            or manifest.get("tuning")
        ):
            raise ValueError("TabICL supports only the fixed pilot recipe")
        import pyarrow.parquet as parquet

        target, task = manifest["target"], manifest["task"]
        selected = [*manifest["features"], target]
        metadata = parquet.ParquetFile(manifest["data_path"])
        if (
            metadata.metadata.num_rows > 10_000
            or not 1 <= len(manifest["features"]) <= 100
            or len(set(selected)) != len(selected)
        ):
            raise ValueError("TabICL pilot Parquet dimensions exceed the qualified limits")
        frame = metadata.read(columns=selected).to_pandas()
        frame = frame.loc[frame[target].notna()].copy()
        X = normalize_frame(frame[manifest["features"]])
        y = (
            frame[target].astype(str)
            if task == "classification"
            else pd.to_numeric(frame[target], errors="raise")
        )
        if len(X) < manifest.get("min_rows", 20) or (
            task == "regression" and not np.isfinite(y).all()
        ):
            raise ValueError("Insufficient usable TabICL rows")
        if task == "classification" and (
            y.nunique() < 2
            or y.nunique() > manifest.get("max_classes", 24)
            or y.value_counts().min() < 2
        ):
            raise ValueError("Invalid TabICL class distribution")
        train, test = train_test_split(
            np.arange(len(X)),
            test_size=manifest["test_size"],
            random_state=manifest["random_state"],
            stratify=y if task == "classification" else None,
        )
        foundation = {key: value for key, value in manifest["foundation"].items() if key != "path"}
        estimator = build_estimator(
            task,
            manifest["foundation"]["path"],
            seed=manifest["random_state"],
            n_jobs=training_threads(),
            kv_cache=manifest["spec"].get("kv_cache", False),
        )
        progress.write_text("fitting")
        estimator.fit(X.iloc[train], y.iloc[train])
        fitted = time.monotonic()
        progress.write_text("scoring")
        predicted = estimator.predict(X.iloc[test])
        if task == "classification":
            proba = estimator.predict_proba(X.iloc[test])
            values = {
                "balanced_accuracy": balanced_accuracy_score(y.iloc[test], predicted),
                "accuracy": accuracy_score(y.iloc[test], predicted),
                "f1": f1_score(
                    y.iloc[test],
                    predicted,
                    **(
                        {"average": "binary", "pos_label": estimator.classes_[-1]}
                        if len(estimator.classes_) == 2
                        else {"average": "macro"}
                    ),
                ),
                "log_loss": log_loss(y.iloc[test], proba, labels=estimator.classes_),
            }
            classes = estimator.classes_.tolist()
        else:
            values = {
                "rmse": float(np.sqrt(mean_squared_error(y.iloc[test], predicted))),
                "mae": mean_absolute_error(y.iloc[test], predicted),
                "r2": r2_score(y.iloc[test], predicted),
            }
            classes = []
        scores = [{"key": key, "value": float(value)} for key, value in values.items()]
        metrics = {
            "primary": scores[0],
            "scores": scores,
            "rows": {"total": len(X), "train": len(train), "test": len(test)},
            "target": {
                "name": target,
                "classes": classes,
                "positive": classes[-1] if len(classes) == 2 else None,
            },
            "diagnostics": {"status": "unsupported", "reason": "tabicl_checks_not_qualified"},
            "foundation": {
                **foundation,
                "experimental": True,
                "frozen": True,
                "sensitive_context": True,
                "kv_cache_persisted": False,
            },
            "timings": {"prepare_fit_s": fitted - started, "holdout_s": time.monotonic() - fitted},
        }
        if manifest.get("evaluation_path"):
            proof = prepare(
                frame,
                columns=[*manifest["features"], target],
                train_indices=frame.index[train],
                test_indices=frame.index[test],
                dataset=manifest.get("dataset"),
                target=target,
                seed=manifest["random_state"],
                test_size=manifest["test_size"],
                positive_class=classes[-1] if len(classes) == 2 else None,
            )
            metrics["evaluation"] = write_partition(proof, manifest["evaluation_path"])
        progress.write_text("saving")
        state = Path(argv[2]).parent / "tabicl-state"
        export_state(estimator, X.iloc[train], y.iloc[train], state, foundation=foundation)
        signature = infer_signature(X.head(20), predicted[: min(20, len(predicted))])
        model_dir = Path(manifest["model_dir"])
        root = Path(__file__).parent
        mlflow.pyfunc.save_model(
            path=str(model_dir),
            python_model=str(root / "ml_tabicl_pyfunc.py"),
            signature=signature,
            artifacts={"state": str(state), "runtime": str(root / "ml_tabicl_runtime.py")},
            pip_requirements=["--extra-index-url https://download.pytorch.org/whl/cpu"]
            + [
                f"{name}=={version(name)}"
                for name in (
                    "tabicl",
                    "torch",
                    "safetensors",
                    "pandas",
                    "numpy",
                    "scipy",
                    "scikit-learn",
                    "mlflow",
                )
            ],
        )
        inputs = json.loads(signature.to_dict()["inputs"])
        summary = {
            "metrics": metrics,
            "artifact": build_artifact_contract(
                model_dir, family="tabular_foundation", serialization="json+safetensors"
            ),
            "signature": {
                "inputs": inputs,
                "output": {"task": task, "target": target, "classes": classes},
            },
            "classes": classes,
            "input_example": json.loads(X.head(3).to_json(orient="records")),
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }
        Path(argv[2]).write_text(json.dumps(summary, allow_nan=False))
        return 0
    except Exception as exc:
        print(f"ml_tabicl_failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 5


if __name__ == "__main__":
    sys.exit(main(sys.argv))
