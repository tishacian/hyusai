"""Qualify the ml-ts image: real forecasts, under the worker's own limits.

Run inside the forecasting image, on the host it will run on::

    sudo docker run --rm agentium-ml-ts:<sha12> python -m scripts.qualify_ml_ts

It fits Nawa's network cells (one cell, then a panel) through the same
``supervise_harness`` call the worker makes — same RLIMIT_AS, CPU and file
budgets — which is the check a laptop cannot make: numba compiles
skforecast's statistical kernels on first use, and LLVM reserves address space
a capped process may not have. It then loads each saved model the way serving
will and times the first and second forecast.

Exit 0 when every case fitted and forecast; the table is the release evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _cases(cells: int, days: int):
    from scripts.gen_nawa_telecom_data import network_cell_frame

    frame = network_cell_frame(cells=cells, days=days).to_pandas()
    one = frame[frame["cell_id"] == frame["cell_id"].iloc[0]].drop(
        columns=["cell_id", "site_code", "region", "technology"]
    )
    gbm = "sklearn.ensemble.HistGradientBoostingRegressor"
    return [
        ("single · gradient boosting", one, "gradient_boosting", gbm, {"random_state": 42}, {}),
        ("single · ETS (numba)", one, "ets", "skforecast.stats.Ets", {}, {}),
        ("single · ARIMA (numba)", one, "arima", "skforecast.stats.Arima", {}, {}),
        (
            f"panel · {cells} cells",
            frame,
            "gradient_boosting",
            gbm,
            {"random_state": 42},
            {"shape": "panel", "series_columns": ["cell_id"], "exog": {"technology": "static"}},
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cells", type=int, default=24)
    parser.add_argument("--days", type=int, default=56)
    parser.add_argument("--horizon", type=int, default=48)
    args = parser.parse_args()

    from app.core.config import settings
    from app.services.ml.families import FORECASTING_FAMILY
    from app.services.recipe_executions import harness_error_line, supervise_harness

    missing = FORECASTING_FAMILY.missing_modules()
    if missing:
        print(f"not a forecasting image: {', '.join(missing)} missing", file=sys.stderr)
        return 2

    rows, failed = [], False
    for label, frame, algo, estimator, params, extra in _cases(args.cells, args.days):
        scratch = Path(tempfile.mkdtemp(prefix="qualify-ml-ts-"))
        frame.to_parquet(scratch / "data.parquet")
        spec = {"time_column": "ts", "horizon": args.horizon, "backtest_folds": 3, **extra}
        manifest = {
            "family": "forecasting",
            "spec": spec,
            "data_path": str(scratch / "data.parquet"),
            "model_dir": str(scratch / "model"),
            "task": "forecasting",
            "algo": algo,
            "target": "prb_utilization_pct",
            "features": list(extra.get("exog") or {}),
            "estimator": estimator,
            "params": params,
            "progress_path": str(scratch / "progress.txt"),
        }
        (scratch / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        threads = str(int(settings.ml_train_threads))
        started = time.monotonic()
        run = supervise_harness(
            [sys.executable, str(FORECASTING_FAMILY.harness), str(scratch / "manifest.json"), str(scratch / "result.json")],
            venv_python=Path(sys.executable),
            scratch=scratch,
            timeout_s=float(settings.ml_train_timeout_s),
            memory_limit_mb=int(settings.ml_train_memory_limit_mb),
            cpu_limit_s=int(settings.ml_train_cpu_limit_s),
            fsize_limit_mb=int(settings.ml_train_artifact_limit_mb),
            extra_env={
                "OMP_NUM_THREADS": threads,
                "OPENBLAS_NUM_THREADS": threads,
                "MKL_NUM_THREADS": threads,
                "MLFLOW_TRACKING_URI": str(scratch / "mlruns"),
                "NUMBA_CACHE_DIR": str(scratch / "numba"),
            },
        )
        fit_s = time.monotonic() - started
        if run.status is not None or run.exit_code != 0:
            failed = True
            detail = harness_error_line(run.stderr_tail, f"status={run.status} exit={run.exit_code}")
            rows.append((label, "FAILED", f"{fit_s:.0f}s", detail[:90], "", "", ""))
            continue
        metrics = json.loads((scratch / "result.json").read_text())["metrics"]
        scores = {score["key"]: score["value"] for score in metrics["scores"]}
        naive = metrics["baseline"].get("mae")
        gain = f"{1 - scores['mae'] / naive:+.0%}" if naive else "-"

        import mlflow.pyfunc
        import pandas as pd

        load_started = time.monotonic()
        model = mlflow.pyfunc.load_model(str(scratch / "model"))
        empty = pd.DataFrame({"series": pd.Series([], dtype=str), "timestamp": pd.Series([], dtype=str)})
        first_started = time.monotonic()
        answer = model.predict(empty, params={"horizon": args.horizon})
        second_started = time.monotonic()
        model.predict(empty, params={"horizon": args.horizon})
        done = time.monotonic()
        rows.append(
            (
                label,
                "ok",
                f"{fit_s:.0f}s",
                f"MASE {scores.get('mase', float('nan')):.2f} · cov {scores.get('coverage', float('nan')):.2f} · vs naive {gain}",
                metrics["forecast"]["serialization"],
                f"load {first_started - load_started:.1f}s",
                f"{len(answer)} rows in {second_started - first_started:.2f}s / {done - second_started:.2f}s",
            )
        )

    widths = [max(len(str(row[index])) for row in rows) for index in range(7)]
    for row in rows:
        print("  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)))
    print(
        f"limits: RLIMIT_AS {settings.ml_train_memory_limit_mb} MB, CPU {settings.ml_train_cpu_limit_s}s, "
        f"threads {settings.ml_train_threads}, horizon {args.horizon}, {args.cells} cells × {args.days} days"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
