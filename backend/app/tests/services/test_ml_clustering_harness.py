"""Actual fits prove distance preprocessing, bounded evidence and portable export."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

from app.resources import ml_clustering_harness as harness


def separated_frame():
    rng = np.random.default_rng(71)
    # Different units would dominate Euclidean distance without standardisation.
    locations = np.repeat([[-8., 0.], [0., 8.], [8., -8.]], 60, axis=0)
    values = locations + rng.normal(0, .25, locations.shape)
    values[:, 1] *= 1000
    frame = pd.DataFrame(values, columns=["load", "energy"])
    frame.loc[[0, 65, 122], "energy"] = np.nan
    return frame


@pytest.fixture(scope="module")
def fitted():
    frame = separated_frame()
    model, metrics = harness.train(frame, clusters=3, max_iter=100, seed=42)
    return frame, model, metrics


def test_separated_groups_have_measurable_stability_and_original_unit_profiles(fitted):
    frame, model, metrics = fitted
    labels = model.predict(frame)
    assert adjusted_rand_score(np.repeat(range(3), 60), labels) > .95
    assert metrics["primary"]["value"] > .8
    assert metrics["clustering"]["stability"]["mean"] > .95
    assert metrics["clustering"]["stability"]["runs"] == 3
    assert metrics["rows"] == {"total": 180, "train": 180, "test": 0}
    groups = metrics["clustering"]["clusters"]
    assert sum(group["count"] for group in groups) == len(frame)
    assert sum(group["share"] for group in groups) == pytest.approx(1)
    for group in groups:
        original = frame.iloc[labels == group["cluster"]]
        for profile in group["features"]:
            feature = profile["feature"]
            assert profile["mean"] == pytest.approx(original[feature].mean())
            assert profile["median"] == pytest.approx(original[feature].median())
            assert profile["missing"] == int(original[feature].isna().sum())
    assert "accuracy" not in [score["key"] for score in metrics["scores"]]
    assert not metrics.get("target") and not metrics.get("confusion")


def test_unit_changes_do_not_change_the_partition(fitted):
    frame, original, _ = fitted
    changed = frame.copy()
    changed["energy"] /= 1000
    model, _ = harness.train(changed, clusters=3, max_iter=100, seed=42)
    assert adjusted_rand_score(original.predict(frame), model.predict(changed)) == 1


def test_stability_refits_imputation_and_scaling_on_each_subsample(fitted, monkeypatch):
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    frame, model, _ = fitted
    observed = []
    imputer_fit = SimpleImputer.fit
    scaler_fit = StandardScaler.fit

    def impute(self, values, y=None):
        observed.append(("imputer", len(values), set(values.index)))
        return imputer_fit(self, values, y)

    def scale(self, values, y=None, sample_weight=None):
        observed.append(("scaler", len(values)))
        return scaler_fit(self, values, y, sample_weight)

    monkeypatch.setattr(SimpleImputer, "fit", impute)
    monkeypatch.setattr(StandardScaler, "fit", scale)
    labels = model.predict(frame)
    report = harness.stability(frame, labels, clusters=3, max_iter=100, seed=42,
                               sample=np.arange(40))
    assert report["sample_rows"] == 40 and report["subsample_rows"] == 144
    assert [entry[:2] for entry in observed] == [(kind, 144) for _ in range(3) for kind in ("imputer", "scaler")]
    assert len({frozenset(entry[2]) for entry in observed if entry[0] == "imputer"}) == 3
    # A relabelled reference must report precisely the same agreement.
    permuted = np.array([7, 3, 9])[labels]
    second = harness.stability(frame, permuted, clusters=3, max_iter=100, seed=42, sample=np.arange(40))
    assert second["values"] == report["values"]


@pytest.mark.parametrize("change", [
    lambda frame: frame.assign(load=np.inf),
    lambda frame: frame.assign(load=np.nan),
    lambda frame: frame.assign(load="text"),
    lambda frame: frame.assign(load=True),
    lambda frame: frame.head(4),
])
def test_actual_file_refuses_unusable_or_misprofiled_data(tmp_path, change):
    frame = change(separated_frame())
    path = tmp_path / "data.parquet"
    frame.to_parquet(path)
    with pytest.raises(ValueError):
        harness.read_frame(str(path), ["load", "energy"], min_rows=40, clusters=3)


def test_insufficient_distinct_profiles_fail_instead_of_claiming_empty_groups():
    frame = pd.DataFrame({"constant": np.ones(40), "two": np.tile([1., 2.], 20)})
    with pytest.raises(ValueError, match="distinct"):
        harness.train(frame, clusters=3, max_iter=100, seed=42)


def test_missing_rare_group_in_a_subsample_makes_overall_stability_unavailable():
    frame = pd.DataFrame({"x": [10.] + [0.] * 39})
    _, metrics = harness.train(frame, clusters=2, max_iter=100, seed=42)
    result = metrics["clustering"]["stability"]
    assert result["valid_runs"] < result["runs"]
    assert result["mean"] is None and result["std"] is None and result["min"] is None
    assert result["reason"] == "insufficient_distinct_subsample"
    assert metrics["warnings"] == [{"code": "ML_CLUSTER_STABILITY_PARTIAL", "reason": result["reason"]}]


def test_silhouette_and_stability_are_bounded_on_larger_data(monkeypatch):
    import sklearn.metrics

    frame = pd.concat([separated_frame()] * 15, ignore_index=True)
    original = sklearn.metrics.silhouette_score
    measured = []

    def measure(values, labels):
        measured.append(len(values))
        return original(values, labels)

    monkeypatch.setattr(sklearn.metrics, "silhouette_score", measure)
    _, result = harness.train(frame, clusters=3, max_iter=100, seed=42)
    assert measured == [2000]
    assert result["clustering"]["stability"]["sample_rows"] == 2000


def test_export_reloads_offline_without_application_and_verifies_all_bytes(tmp_path, fitted):
    from app.services.ml.artifacts import verify_bundle
    from app.services.tabular_datasets import TabularError

    frame, model, _ = fitted
    source = tmp_path / "source"
    summary = harness.save(model, frame, str(source))
    assert "skops" in (source / "MLmodel").read_text()
    verify_bundle(source, summary["artifact"])
    portable = tmp_path / "portable"
    shutil.copytree(source, portable)
    shutil.rmtree(source)
    probes = frame.iloc[[1, 63, 124]].copy()
    probes.loc[probes.index[1], "load"] = np.nan
    probes.to_parquet(tmp_path / "probes.parquet")
    expected = model.predict(probes).tolist()
    script = '''
import socket, sys, json
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden"))
import mlflow.pyfunc, pandas as pd
model = mlflow.pyfunc.load_model(sys.argv[1])
assert model.predict(pd.read_parquet(sys.argv[2])).tolist() == json.loads(sys.argv[3])
assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
print("portable clustering export passed")
'''
    run = subprocess.run([sys.executable, "-c", script, str(portable), str(tmp_path / "probes.parquet"), json.dumps(expected)],
                         capture_output=True, text=True, timeout=90, cwd=tmp_path,
                         env={**os.environ, "PYTHONPATH": "", "MLFLOW_TRACKING_URI": str(tmp_path / "mlruns"),
                              "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
    assert run.returncode == 0, run.stderr[-4000:]
    metadata = portable / "MLmodel"
    metadata.write_text(metadata.read_text() + "\n")
    with pytest.raises(TabularError) as error:
        verify_bundle(portable, summary["artifact"])
    assert error.value.code == "ML_ARTIFACT_TAMPERED"


def test_supervised_harness_contract_emits_progress_and_summary(tmp_path):
    data = tmp_path / "data.parquet"
    separated_frame().to_parquet(data)
    manifest = {"task": "clustering", "family": "clustering", "algo": "kmeans", "target": "",
                "features": ["load", "energy"], "spec": {}, "params": {"n_clusters": 3, "max_iter": 100},
                "random_state": 42, "data_path": str(data), "model_dir": str(tmp_path / "model"),
                "progress_path": str(tmp_path / "progress"), "min_rows": 40}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = tmp_path / "result.json"
    run = subprocess.run([sys.executable, harness.__file__, str(path), str(result)], capture_output=True,
                         text=True, timeout=90, env={**os.environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
                                                    "MLFLOW_TRACKING_URI": str(tmp_path / "mlruns")})
    assert run.returncode == 0, run.stderr[-4000:]
    summary = json.loads(result.read_text())
    assert summary["metrics"]["primary"]["key"] == "silhouette"
    assert summary["signature"]["output"]["clusters"] == [0, 1, 2]
    assert summary["classes"] == []
    assert (tmp_path / "progress").read_text().splitlines() == [
        "reading", "fitting:180", "scoring", "validating:1/3", "validating:2/3", "validating:3/3", "saving"]
