"""Create synthetic report states on the old runtime; verify on the candidate.

Run from backend with the respective Python interpreter:
    python scripts/qualify_skore_upgrade.py write /tmp/skore-upgrade
    python scripts/qualify_skore_upgrade.py verify /tmp/skore-upgrade
    python scripts/qualify_skore_upgrade.py fresh /tmp/skore-upgrade

Only load a directory produced by this script in a trusted test environment:
joblib is not an interchange format for untrusted inputs. No application store,
database, Hub or Project is used. The directory is disposable test evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

import joblib
import skore
from sklearn.datasets import make_classification, make_regression
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import train_test_split
from skore import ComparisonReport, CrossValidationReport, EstimatorReport

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.resources.ml_skore_adapter import (  # noqa: E402
    comparison_metrics,
    cross_validation_metrics,
    estimator_metrics,
)


def reports():
    result = {}
    for name, classes in (("binary", 2), ("multiclass", 3)):
        x, y = make_classification(
            n_samples=120,
            n_features=5,
            n_informative=3,
            n_redundant=0,
            n_classes=classes,
            random_state=42,
        )
        train, test, yt, yv = train_test_split(x, y, stratify=y, random_state=42)
        opts = {"pos_label": 1} if classes == 2 else {}
        result[name] = EstimatorReport(
            LogisticRegression(max_iter=300).fit(train, yt),
            X_test=test,
            y_test=yv,
            **opts,
        )
        if classes == 2:
            result["binary_alt"] = EstimatorReport(
                LogisticRegression(C=0.1, max_iter=300).fit(train, yt),
                X_test=test,
                y_test=yv,
                **opts,
            )
            result["cv_binary"] = CrossValidationReport(
                LogisticRegression(max_iter=300),
                train,
                yt,
                splitter=2,
                n_jobs=1,
                **opts,
            )
    x, y = make_regression(n_samples=100, n_features=4, noise=1, random_state=42)
    train, test, yt, yv = train_test_split(x, y, random_state=42)
    result["regression"] = EstimatorReport(Ridge().fit(train, yt), X_test=test, y_test=yv)
    result["cv_regression"] = CrossValidationReport(Ridge(), train, yt, splitter=2, n_jobs=1)
    return result


def snapshot(all_reports):
    result = {}
    for name, report in all_reports.items():
        if name.startswith("cv_"):
            result[name] = cross_validation_metrics(
                report.metrics.summarize(),
                keys={"accuracy", "roc_auc", "r2", "mae", "rmse", "mape"},
            )
        else:
            result[name] = {
                key: value
                for key, value in estimator_metrics(report.metrics.summarize()).items()
                if not key.endswith("_time")
            }
    result["comparison"] = comparison_metrics(
        ComparisonReport(
            {"v1": all_reports["binary"], "v2": all_reports["binary_alt"]}
        ).metrics.summarize(),
        names={"model-1": "v1", "model-2": "v2"},
    )
    return result


def equal(actual, expected, path="metrics"):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), f"{path}: keys changed"
        for key in expected:
            equal(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), f"{path}: length changed"
        for i, (left, right) in enumerate(zip(actual, expected, strict=True)):
            equal(left, right, f"{path}[{i}]")
    elif isinstance(expected, float):
        assert actual is not None and math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-6), (
            path
        )
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("write", "verify", "fresh"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    manifest = args.directory / "expected.json"
    if args.mode == "write":
        if manifest.exists():
            parser.error("refusing to replace the old-runtime baseline")
        args.directory.mkdir(parents=True, exist_ok=True)
        all_reports = reports()
        metrics = snapshot(all_reports)
        for name, report in all_reports.items():
            joblib.dump(report.to_dict(), args.directory / f"{name}.joblib")
        manifest.write_text(
            json.dumps({"skore": skore.__version__, "metrics": metrics}, indent=2, allow_nan=False)
            + "\n"
        )
        print(f"Wrote {len(all_reports)} synthetic states with Skore {skore.__version__}")
    else:
        baseline = json.loads(manifest.read_text())
        if args.mode == "fresh":
            # Compare newly trained reports even if old serialization cannot load.
            equal(snapshot(reports()), baseline["metrics"])
            print(f"PASS: {baseline['skore']} -> {skore.__version__}: fresh-fit metrics")
            return
        all_reports = {}
        # Reopening and evaluating the stored states must never retrain them.
        with (
            patch.object(LogisticRegression, "fit", side_effect=AssertionError("unexpected refit")),
            patch.object(Ridge, "fit", side_effect=AssertionError("unexpected refit")),
        ):
            for name in baseline["metrics"]:
                if name == "comparison":
                    continue
                cls = CrossValidationReport if name.startswith("cv_") else EstimatorReport
                all_reports[name] = cls.from_dict(joblib.load(args.directory / f"{name}.joblib"))
            equal(snapshot(all_reports), baseline["metrics"])
        # New fits must preserve the same deterministic numeric contract too.
        equal(snapshot(reports()), baseline["metrics"])
        print(
            f"PASS: {baseline['skore']} -> {skore.__version__}: {len(all_reports)} states, "
            "comparison, no-refit reopening and fresh-fit metrics"
        )


if __name__ == "__main__":
    main()
