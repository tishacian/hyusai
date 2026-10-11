"""Offline smoke for each candidate image, without any tracking/storage service."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path


def qualify(*, diagnostics: bool):
    import mlflow.sklearn
    import numpy as np
    import pandas as pd
    import skops.io
    from sklearn.metrics import f1_score, mean_absolute_error

    from app.resources.ml_evaluation import read_partition, shared_holdout
    from app.resources.ml_train_harness import _trusted_types

    packages = {
        name: version(name)
        for name in ("skore", "skrub", "scikit-learn", "numpy", "pandas", "mlflow", "skops")
    }
    if packages["skore"] != "0.27.0":
        raise ValueError("Candidate image must use the qualified Skore 0.27.0 pin")
    harness = Path(__file__).resolve().parents[1] / "app" / "resources" / "ml_train_harness.py"
    result = {
        "packages": packages,
        "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "runtime": os.environ.get("ML_RUNTIME", "worker"),
        "cases": [],
    }
    rng = np.random.default_rng(42)
    with tempfile.TemporaryDirectory(prefix="skore-qualification-") as root:
        for task in ("classification", "regression"):
            scratch = Path(root) / task
            scratch.mkdir()
            x = pd.DataFrame({"x": rng.normal(size=2000), "z": rng.normal(size=2000)})
            truth = 3 * x.x + x.z + rng.normal(size=len(x))
            frame = x.assign(
                target=np.where(truth > 0, "accept", "reject")
                if task == "classification"
                else truth
            )
            data = scratch / "data.parquet"
            frame.to_parquet(data, index=False)
            manifest = {
                "data_path": str(data),
                "model_dir": str(scratch / "model"),
                "target": "target",
                "features": list(x.columns),
                "task": task,
                "dataset": {"id": "synthetic-qualification", "version": 1},
                "evaluation_path": str(scratch / "report" / "evaluation.json.gz"),
                "report_path": str(scratch / "report" / "state.joblib"),
                "report_state_limit_mb": 64,
                "random_state": 42,
                "test_size": 0.25,
                "cv": 2,
                "importance_rows": 40,
                "estimator": "sklearn.linear_model.LogisticRegression"
                if task == "classification"
                else "sklearn.linear_model.Ridge",
                "params": {"max_iter": 300} if task == "classification" else {"alpha": 1.0},
                "spec": {"positive_class": "accept", "calibration": "sigmoid", "threshold": "f1"}
                if task == "classification"
                else {},
                "diagnostics": {"enabled": diagnostics, "budget_s": 30, "max_rows": 300},
            }
            source, destination = scratch / "manifest.json", scratch / "result.json"
            source.write_text(json.dumps(manifest))
            started = time.monotonic()
            with (scratch / "harness.log").open("w") as log:
                subprocess.run(
                    [sys.executable, str(harness), str(source), str(destination)],
                    check=True,
                    timeout=180,
                    stdout=log,
                    stderr=log,
                )
            summary = json.loads(destination.read_text())
            metrics = summary["metrics"]
            partition = read_partition(
                Path(manifest["evaluation_path"]).read_bytes(),
                sha256=metrics["evaluation"]["sha256"],
            )
            holdout = shared_holdout(frame, [partition])
            model = mlflow.sklearn.load_model(manifest["model_dir"])
            predictions = model.predict(holdout[list(x.columns)])
            scores = {row["key"]: row["value"] for row in metrics["scores"]}
            expected = (
                f1_score(holdout.target, predictions, pos_label="accept")
                if task == "classification"
                else mean_absolute_error(holdout.target, predictions)
            )
            actual = scores["f1" if task == "classification" else "mae"]
            if abs(actual - expected) > 1e-6:
                raise ValueError("Served model differs from its recorded evaluation")
            portable = skops.io.loads(skops.io.dumps(model), trusted=_trusted_types(model))
            np.testing.assert_array_equal(portable.predict(holdout[list(x.columns)]), predictions)
            if metrics["diagnostics"]["status"] != ("completed" if diagnostics else "disabled"):
                raise ValueError(f"Unexpected diagnostic status: {metrics['diagnostics']}")
            if metrics["cv"].get("error") or metrics["cv"]["mean"] is None:
                raise ValueError("Cross-validation did not qualify")
            result["cases"].append(
                {
                    "task": task,
                    "elapsed_s": round(time.monotonic() - started, 3),
                    "model_bytes": sum(
                        path.stat().st_size
                        for path in (scratch / "model").rglob("*")
                        if path.is_file()
                    ),
                    "partition_bytes": metrics["evaluation"]["bytes"],
                    "report_bytes": summary["report_state"]["bytes"],
                    "diagnostics": metrics["diagnostics"],
                    "metric_semantics": metrics["metric_semantics"],
                }
            )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = qualify(diagnostics=args.diagnostics)
    encoded = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(encoded + "\n")
    print(encoded)


if __name__ == "__main__":
    main()
