"""One real trained artifact, built once, shared by the serving test suites.

The serving plane is the one place where stubbing the model would test almost
nothing: the properties that matter are that a fitted skrub pipeline recognizes
the frame the request path builds for it, that its probabilities survive the trip
to JSON, and that a hole in a production row still scores. So these suites run
the **production harness** on a small telecom-shaped frame and load what it wrote
through the same code path production uses.

It is a module-scoped fixture because the fit costs seconds and the artifact is
immutable once written — one fit per test module, reused by every test in it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CHURN_ROWS = 240

# The frame's columns, target included. Every suite derives its feature list from
# this by removing whichever column it is predicting.
CHURN_COLUMNS = ["plan", "tenure_months", "arpu", "support_tickets", "churn"]
CHURN_FEATURES = ["plan", "tenure_months", "arpu", "support_tickets"]


def churn_frame(rows: int = CHURN_ROWS):
    """A telecom churn frame with signal in it, deterministic across runs.

    The label is a noisy logit of tenure, tickets and ARPU rather than a
    threshold, so a fit lands somewhere honest instead of at a suspicious 1.0 —
    and a high-risk row really does score above a low-risk one.
    """

    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        {
            "plan": rng.choice(["prepaid", "postpaid", "hybrid"], rows),
            "tenure_months": rng.integers(1, 96, rows),
            "arpu": rng.normal(85, 25, rows).round(2),
            "support_tickets": rng.poisson(0.9, rows),
        }
    )
    logit = (
        -1.0
        + 0.06 * (60 - frame["tenure_months"]).clip(lower=0)
        + 1.2 * frame["support_tickets"]
        - 0.02 * frame["arpu"]
    )
    frame["churn"] = (rng.random(rows) < 1 / (1 + np.exp(-logit))).astype(int)
    return frame


def fit_churn_artifact(
    directory: Path, *, task: str = "classification", target: str = "churn"
) -> tuple[Path, dict]:
    """Run the production training harness once; return its model dir and summary.

    Knobs are turned down to what a test needs (25 iterations, 20 curve points):
    the point is a real artifact, not a good one.
    """

    from app.services.tabular_ml import harness_path

    directory.mkdir(parents=True, exist_ok=True)
    data = directory / "data.parquet"
    churn_frame().to_parquet(data)
    model_dir = directory / "model"
    manifest = {
        "data_path": str(data),
        "model_dir": str(model_dir),
        "task": task,
        "target": target,
        "features": [name for name in CHURN_FEATURES if name != target],
        "estimator": (
            "sklearn.ensemble.HistGradientBoostingClassifier"
            if task == "classification"
            else "sklearn.ensemble.HistGradientBoostingRegressor"
        ),
        "params": {"max_iter": 25, "random_state": 42},
        "scale": False,
        "test_size": 0.25,
        "cv": 0,
        "random_state": 42,
        "min_rows": 40,
        "max_classes": 24,
        "curve_points": 20,
        "importance_rows": 100,
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result_path = directory / "result.json"
    completed = subprocess.run(  # noqa: S603 - our interpreter, our harness
        [sys.executable, str(harness_path()), str(manifest_path), str(result_path)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stderr
    return model_dir, json.loads(result_path.read_text(encoding="utf-8"))
