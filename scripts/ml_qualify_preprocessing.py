#!/usr/bin/env python3
"""Reproduce the bounded P3 preprocessing/serialization qualification.

Run with each qualified runtime, for example:
  python scripts/ml_qualify_preprocessing.py --output /tmp/preprocessing.json

Synthetic data demonstrates compatibility, not business value or production
performance. Timing is a single observation; RSS is a cumulative process peak
including imports. The output contains no rows, labels or prediction vectors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"


def qualify():
    import mlflow.sklearn
    import numpy as np
    import pandas as pd
    from sklearn.metrics import accuracy_score, r2_score
    from sklearn.model_selection import train_test_split

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.resources import ml_preprocessing as preparation
    from app.resources.ml_train_harness import _make_pipeline, _trusted_types

    rng = np.random.default_rng(48)
    rows = 300
    frame = pd.DataFrame(
        {
            "amount": rng.normal(size=rows),
            "history": rng.normal(size=rows),
            "plan": rng.choice(["basic", "standard", "pro"], rows),
            "reference": [f"purchase item {index:04d}" for index in range(rows)],
            "date": pd.date_range("2024-01-01", periods=rows),
            "constant": [2.0] * rows,
            "missingness": np.where(np.arange(rows) % 3 == 0, np.nan, 1.0),
        }
    )
    records = []
    for task in ("classification", "regression"):
        target = (
            (frame.amount + 0.5 * frame.history > 0).astype(int)
            if task == "classification"
            else 2 * frame.amount + frame.history + rng.normal(scale=0.1, size=rows)
        )
        train, test, ytrain, ytest = train_test_split(
            frame,
            target,
            random_state=48,
            stratify=target if task == "classification" else None,
        )
        for encoder in ("auto", "string", "minhash"):
            pipeline = _make_pipeline(
                "sklearn.linear_model.LogisticRegression"
                if task == "classification"
                else "sklearn.linear_model.Ridge",
                {"random_state": 48, "max_iter": 300},
                spec={"text_encoder": encoder},
                seed=48,
            )
            started = time.perf_counter()
            pipeline.fit(train, ytrain)
            fit_ms = (time.perf_counter() - started) * 1000
            summary = preparation.record_fitted(pipeline, train, fit_time_ms=fit_ms)
            predictions = pipeline.predict(test)
            with tempfile.TemporaryDirectory(
                prefix="agentium-preprocessing-"
            ) as directory:
                path = Path(directory) / "model"
                mlflow.sklearn.save_model(
                    pipeline,
                    path=path,
                    serialization_format="skops",
                    skops_trusted_types=_trusted_types(pipeline),
                    pip_requirements=[],
                )
                model_bytes = sum(
                    item.stat().st_size for item in path.rglob("*") if item.is_file()
                )
                started = time.perf_counter()
                loaded = mlflow.sklearn.load_model(path)
                reload_ms = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                loaded_predictions = loaded.predict(test)
                predict_ms = (time.perf_counter() - started) * 1000
                np.testing.assert_allclose(predictions, loaded_predictions)
                assert preparation.describe(loaded) == summary
            records.append(
                {
                    "task": task,
                    "encoder": encoder,
                    "metric": "accuracy" if task == "classification" else "r2",
                    "score": float(
                        accuracy_score(ytest, predictions)
                        if task == "classification"
                        else r2_score(ytest, predictions)
                    ),
                    "fit_ms": round(fit_ms, 2),
                    "reload_ms": round(reload_ms, 2),
                    "predict_75_rows_ms": round(predict_ms, 2),
                    "model_bytes": model_bytes,
                    "process_peak_rss_mib": round(
                        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2
                    ),
                    "preprocessing_output_count": summary["output_count"],
                    "prediction_sha256": hashlib.sha256(
                        np.asarray(predictions, dtype="<f8").tobytes()
                    ).hexdigest(),
                    "roundtrip": "passed",
                }
            )
    return {
        "schema": 1,
        "recipe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "data": {
            "kind": "synthetic",
            "rows": rows,
            "train_rows": 225,
            "test_rows": 75,
            "seed": 48,
            "business_value": "not_evaluated",
        },
        "versions": {
            name: version(name)
            for name in ("skrub", "skops", "scikit-learn", "numpy", "pandas")
        },
        "telemetry_scope": {
            "threads": 1,
            "repetitions": 1,
            "rss": "cumulative_process_peak_including_imports",
            "timings": "observations_not_performance_comparison",
        },
        "records": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    destination = parser.parse_args().output
    destination.write_text(json.dumps(qualify(), indent=2, allow_nan=False) + "\n")
