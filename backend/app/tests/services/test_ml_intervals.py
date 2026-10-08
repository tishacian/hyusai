"""Conformal evidence comes only from training residuals; the test judges it."""

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_regression
from sklearn.model_selection import train_test_split

from app.tests.services.test_ml_training import _manifest_for, _run_harness


@pytest.mark.slow
def test_conformal_coverage_and_test_labels_cannot_choose_the_quantiles(tmp_path):
    x, y = make_regression(n_samples=5000, n_features=4, noise=10, random_state=42)
    features = [f"x{i}" for i in range(4)]
    frame = pd.DataFrame(x, columns=features)
    frame["y"] = y
    data = tmp_path / "regression.parquet"
    frame.to_parquet(data)
    manifest = _manifest_for(
        data, tmp_path, task="regression", target="y", features=features,
        estimator="sklearn.linear_model.Ridge", params={"alpha": 1.0},
        spec={"intervals": "conformal"},
    )
    code, summary, stderr = _run_harness(tmp_path / "run", manifest)
    assert code == 0, stderr
    evidence = summary["metrics"]["intervals"]
    assert evidence["folds"] == 5
    assert evidence["residual_rows"] == summary["metrics"]["rows"]["train"] == 3750
    assert [row["q"] for row in evidence["levels"]] == sorted(row["q"] for row in evidence["levels"])
    for row in evidence["levels"]:
        assert row["coverage"] == pytest.approx(row["level"], abs=0.05)
        assert row["width"] == pytest.approx(2 * row["q"])
    progress = (tmp_path / "run/progress.txt").read_text().splitlines()
    assert [step for step in progress if step.startswith("calibrating:")] == [f"calibrating:{k}/5" for k in range(1, 6)]

    # Change only the held-out outcomes. A leaked calibration would widen its
    # intervals; honest calibration stays fixed and reports failed coverage.
    _, held_out = train_test_split(np.arange(len(frame)), test_size=0.25, random_state=42)
    frame.loc[held_out, "y"] += 10000
    frame.to_parquet(data)
    manifest.pop("progress_path", None)
    manifest["model_dir"] = str(tmp_path / "changed-model")
    code, changed, stderr = _run_harness(tmp_path / "changed-run", manifest)
    assert code == 0, stderr
    assert [row["q"] for row in changed["metrics"]["intervals"]["levels"]] == [row["q"] for row in evidence["levels"]]
    assert all(row["coverage"] == 0 for row in changed["metrics"]["intervals"]["levels"])


def test_requested_fold_count_and_tiny_samples_have_finite_quantiles(tmp_path):
    from sklearn.linear_model import LinearRegression

    from app.resources.ml_train_harness import _conformal_quantiles

    x = pd.DataFrame({"x": [1., 2., 3., 4.]})
    evidence = _conformal_quantiles(LinearRegression(), x, pd.Series([1., 4., 7., 9.]), folds=2,
                                   progress_path=str(tmp_path / "progress.txt"))
    assert evidence["folds"] == 2 and evidence["residual_rows"] == 4
    assert all(np.isfinite(row["q"]) for row in evidence["levels"])
