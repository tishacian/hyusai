"""Offline CPU qualification; provision ML_DEEP_TEST_MODEL_DIR for real fits."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from app.resources import ml_foundation_harness as harness


def frame(rows=100, *, series="a"):
    return pd.DataFrame({"time": pd.date_range("2024-01-01", periods=rows, freq="D"),
                         "value": np.arange(rows, dtype=float), "series": series})


SPEC = {"time_column": "time", "shape": "single", "horizon": 7, "backtest_folds": 3}


@pytest.mark.parametrize("change,message", [
    (lambda f: pd.concat([f, f.iloc[:1]]), "duplicates"),
    (lambda f: f.assign(value=np.inf), "finite"),
    (lambda f: f.drop(index=4), "gaps"),
    (lambda f: f.assign(time=f["time"].where(f.index != 4, pd.NaT)), "dates"),
])
def test_unusable_history_is_refused(change, message):
    with pytest.raises(ValueError, match=message):
        harness.read_series(change(frame()), SPEC, "value")


def test_panel_requires_aligned_dates_and_unambiguous_identifiers():
    panel = pd.concat([frame(), frame(series="b").iloc[1:]], ignore_index=True)
    with pytest.raises(ValueError, match="alignment"):
        harness.read_series(panel, {**SPEC, "shape": "panel", "series_columns": ["series"]}, "value")
    panel = pd.concat([frame().assign(left="a · b", right="c"), frame().assign(left="a", right="b · c")])
    with pytest.raises(ValueError, match="collide"):
        harness.read_series(panel, {**SPEC, "shape": "panel", "series_columns": ["left", "right"]}, "value")


def test_zero_fill_is_explicit_and_preserves_regular_grid():
    series, frequency, holes = harness.read_series(frame().drop(index=4), {**SPEC, "fill": "zero", "frequency": "D"}, "value")
    assert frequency == "D" and holes == 1 and series["value"].iloc[4] == 0


class PrefixOnly:
    def __init__(self):
        self.contexts = []

    def fit(self, *, series):
        self.series = series
        self.contexts.append({key: values.copy() for key, values in series.items()})

    def predict_interval(self, *, steps, interval):
        blocks = []
        for name, values in self.series.items():
            index = pd.date_range(values.index[-1] + values.index.freq, periods=steps, freq=values.index.freq)
            blocks.append(pd.DataFrame({"level": name, "pred": values.iloc[-1],
                                        "lower_bound": values.iloc[-1] - 1, "upper_bound": values.iloc[-1] + 1}, index=index))
        return pd.concat(blocks)


def test_backtest_supplies_only_prefix_and_naive_never_reads_current_horizon():
    series, _, _ = harness.read_series(frame(), SPEC, "value")
    model = PrefixOnly()
    points, initial = harness.evaluate(model, series, horizon=10, folds=3, level=.8, season=7)
    assert initial == 70 and [len(item["value"]) for item in model.contexts] == [70, 80, 90]
    first = points[points.fold == 0]
    assert first.pred.eq(69).all()
    assert first.scale.eq(1).all()  # Catalogue MASE uses one-step changes of the prefix.
    assert first.naive.tolist() == [63., 64., 65., 66., 67., 68., 69., 63., 64., 65.]
    mutated = {"value": series["value"].copy()}
    mutated["value"].iloc[70:] = 1e9
    second, _ = harness.evaluate(PrefixOnly(), mutated, horizon=10, folds=3, level=.8, season=7)
    assert second[second.fold == 0].pred.equals(first.pred)


@pytest.fixture(scope="module")
def local_weights():
    pytest.importorskip("chronos")
    root = Path(os.environ.get("ML_DEEP_TEST_MODEL_DIR", "/data/models/chronos-2-small"))
    if not (root / "model.safetensors").exists():
        pytest.skip("provision chronos-2-small for offline qualification")
    return root


@pytest.fixture(scope="module", params=[1, 2], ids=["single", "panel"])
def trained(request, tmp_path_factory, local_weights):
    from scripts.gen_nawa_telecom_data import network_cell_frame
    root = tmp_path_factory.mktemp(f"foundation-{request.param}")
    network_cell_frame(cells=request.param, days=21).to_pandas().to_parquet(root / "data.parquet")
    files = {name: harness._sha256(local_weights / name) for name in harness.WEIGHT_FILES}
    spec = {"time_column": "ts", "shape": "single" if request.param == 1 else "panel",
            "horizon": 24, "backtest_folds": 3, "interval_level": .8}
    if request.param == 2:
        spec["series_columns"] = ["cell_id"]
    manifest = {"family": "forecasting_deep", "task": "forecasting", "algo": "chronos_zero_shot",
                "target": "prb_utilization_pct", "features": [], "params": {}, "spec": spec,
                "data_path": str(root / "data.parquet"), "model_dir": str(root / "model"),
                "progress_path": str(root / "progress"),
                "foundation": {"path": str(local_weights), "model_id": "chronos-2-small",
                               "revision": "ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a", "files": files}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    run = subprocess.run([sys.executable, harness.__file__, str(root / "manifest.json"), str(root / "result.json")],
                         capture_output=True, text=True, timeout=180,
                         env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                              "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MLFLOW_TRACKING_URI": str(root / "mlruns")})
    assert run.returncode == 0, run.stderr[-6000:]
    return root, json.loads((root / "result.json").read_text()), request.param


def test_real_nawa_backtest_native_intervals_and_unchanged_weights(trained, local_weights):
    root, result, cells = trained
    metrics = result["metrics"]
    scores = {row["key"]: row["value"] for row in metrics["scores"]}
    assert scores["mae"] >= 0 and 0 <= scores["coverage"] <= 1 and metrics["baseline"]["mae"] >= 0
    assert metrics["rows"]["backtest"] == cells * 24 * 3
    assert metrics["forecast"]["interval_method"] == "model"
    assert metrics["foundation"]["zero_shot"] and metrics["foundation"]["weights_unchanged"]
    for name, digest in metrics["foundation"]["files"].items():
        assert digest == harness._sha256(local_weights / name)
        assert digest == harness._sha256(root / "model" / "artifacts" / "foundation" / name)
    assert not list((root / "model").rglob("*.joblib"))


def test_export_reloads_offline_without_application_imports(trained):
    root, result, cells = trained
    script = '''
import socket
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden"))
import mlflow.pyfunc, pandas as pd, sys
model=mlflow.pyfunc.load_model(sys.argv[1])
levels=model.unwrap_python_model().meta["levels"]
frame=model.predict(pd.DataFrame({"series":[levels[0]]}),params={"horizon":7,"interval_level":.9})
assert len(frame)==7 and frame.series.nunique()==1
assert frame[["pred","lower_bound","upper_bound"]].notna().all().all()
assert not any(name.startswith("app.") for name in sys.modules)
for params in ({"horizon":65},{"interval_level":.99}):
 try: model.predict(pd.DataFrame(),params=params)
 except ValueError: pass
 else: raise AssertionError("invalid range accepted")
print("portable offline export passed")
'''
    portable = root / "portable-export"
    shutil.copytree(root / "model", portable)
    run = subprocess.run([sys.executable, "-c", script, str(portable)], cwd=root,
                         capture_output=True, text=True, timeout=90,
                         env={**os.environ, "PYTHONPATH": "", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                              "MLFLOW_TRACKING_URI": str(root / "mlruns"), "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
    assert run.returncode == 0, run.stderr[-5000:]


def test_all_exported_bytes_checked_before_code_loading(trained):
    from app.services.ml.artifacts import verify_bundle
    from app.services.tabular_datasets import TabularError
    root, result, _ = trained
    verify_bundle(root / "model", result["artifact"])
    path = root / "model" / "artifacts" / "meta.json"
    original = path.read_bytes()
    try:
        path.write_bytes(original + b" ")
        with pytest.raises(TabularError):
            verify_bundle(root / "model", result["artifact"])
    finally:
        path.write_bytes(original)


def test_backtest_does_not_update_neural_state(local_weights):
    forecaster = harness.build_forecaster(local_weights)
    model = forecaster.estimator.adapter._pipeline.model
    def state_hash():
        result = hashlib.sha256()
        for key, value in sorted(model.state_dict().items()):
            result.update(key.encode())
            result.update(value.detach().cpu().contiguous().numpy().tobytes())
        return result.hexdigest()
    before = state_hash()
    series, _, _ = harness.read_series(frame(), SPEC, "value")
    harness.evaluate(forecaster, series, horizon=7, folds=3, level=.8, season=7)
    forecaster.fit(series=series)
    assert state_hash() == before
