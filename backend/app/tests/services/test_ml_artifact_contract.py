"""Real MLflow/skops roundtrips and refusal before any deserialization."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

from app.core.config import settings
from app.resources.ml_artifact_contract import build_artifact_contract, safe_relative
from app.resources.ml_train_harness import _make_pipeline
from app.services.ml.artifacts import verify_model_bundle
from app.services.tabular_datasets import TabularError
from app.services.tabular_predict import _load_mlflow_model


def _data():
    count = 72
    frame = pd.DataFrame(
        {
            "number": np.arange(count, dtype=float),
            "category": ["a", "b", "c"] * 24,
            "text": [f"customer item {k} long text" for k in range(count)],
            "date": pd.date_range("2020-01-01", periods=count),
            "constant": ["known"] * count,
        }
    )
    return frame, np.arange(count) % 2


def _export(root: Path, estimator, frame, family="tabular"):
    import mlflow.sklearn
    import skops.io as sio

    types = sio.get_untrusted_types(data=sio.dumps(estimator))
    mlflow.sklearn.save_model(
        estimator,
        path=str(root),
        serialization_format="skops",
        skops_trusted_types=types,
        pip_requirements=[],
    )
    artifact = build_artifact_contract(
        root, family=family, serialization="skops", trusted_types=types
    )
    return artifact


@pytest.mark.parametrize("encoder", ["auto", "string", "minhash"])
@pytest.mark.parametrize("task", ["Classifier", "Regressor"])
def test_qualified_real_mlflow_roundtrip(tmp_path, encoder, task):
    frame, y = _data()
    model = _make_pipeline(
        "sklearn.ensemble.HistGradientBoosting" + task,
        {"max_iter": 3, "random_state": 13},
        spec={"text_encoder": encoder},
    )
    model.fit(frame, y)
    root = tmp_path / "model"
    artifact = _export(root, model, frame)
    verify_model_bundle(root, artifact, family="tabular")
    loaded = _load_mlflow_model(root)
    np.testing.assert_allclose(loaded.predict(frame), model.predict(frame))
    if task == "Classifier":
        np.testing.assert_allclose(loaded.predict_proba(frame), model.predict_proba(frame))


def test_calibration_and_threshold_roundtrip(tmp_path):
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator
    from sklearn.model_selection import FixedThresholdClassifier

    frame, y = _data()
    base = _make_pipeline("sklearn.linear_model.LogisticRegression", {"max_iter": 100})
    base.fit(frame.iloc[:48], y[:48])
    calibrated = CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid").fit(
        frame.iloc[48:], y[48:]
    )
    model = FixedThresholdClassifier(FrozenEstimator(calibrated), threshold=0.35).fit(frame, y)
    artifact = _export(tmp_path / "model", model, frame)
    verify_model_bundle(tmp_path / "model", artifact, family="tabular")
    loaded = _load_mlflow_model(tmp_path / "model")
    np.testing.assert_array_equal(loaded.predict(frame), model.predict(frame))
    np.testing.assert_allclose(loaded.predict_proba(frame), model.predict_proba(frame))


def test_clustering_roundtrip(tmp_path):
    from sklearn.cluster import KMeans
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 10.0, 11.0, 12.0]})
    model = make_pipeline(
        SimpleImputer(), StandardScaler(), KMeans(n_clusters=2, random_state=1)
    ).fit(frame)
    artifact = _export(tmp_path / "model", model, frame, "clustering")
    verify_model_bundle(tmp_path / "model", artifact, family="clustering")
    np.testing.assert_array_equal(
        _load_mlflow_model(tmp_path / "model").predict(frame), model.predict(frame)
    )


@pytest.fixture
def exported(tmp_path):
    frame, y = _data()
    model = _make_pipeline("sklearn.ensemble.HistGradientBoostingClassifier", {"max_iter": 2})
    model.fit(frame, y)
    root = tmp_path / "model"
    return root, _export(root, model, frame)


@pytest.mark.parametrize(
    "name", ["../outside", "/outside", "a/../b", "a\\b", "a//b", "./file", "a:b", ""]
)
def test_inventory_paths_are_canonical(name):
    assert not safe_relative(name)


@pytest.mark.parametrize(
    "change,code",
    [
        ("legacy", "ML_ARTIFACT_LEGACY_UNSUPPORTED"),
        ("runtime", "ML_ARTIFACT_RUNTIME_MISMATCH"),
        ("profile", "ML_ARTIFACT_UNVERIFIED"),
        ("tamper", "ML_ARTIFACT_TAMPERED"),
        ("extra", "ML_ARTIFACT_TAMPERED"),
        ("symlink", "ML_ARTIFACT_UNVERIFIED"),
        ("quota", "ML_ARTIFACT_LIMIT"),
    ],
)
def test_unqualified_bundle_refused_before_load(exported, monkeypatch, change, code):
    import mlflow.pyfunc
    import skops.io as sio

    root, original = exported
    artifact = copy.deepcopy(original)
    monkeypatch.setattr(sio, "load", lambda *a, **k: pytest.fail("deserialization must not run"))
    monkeypatch.setattr(
        mlflow.pyfunc, "load_model", lambda *a, **k: pytest.fail("MLflow must not run")
    )
    limit = 512 * 1024 * 1024
    if change == "legacy":
        artifact.pop("contract_version")
    if change == "runtime":
        artifact["runtime"]["scikit-learn"] = "0.0.0"
    if change == "profile":
        artifact["trust_profile"] = "allow-everything"
    if change == "tamper":
        (root / "MLmodel").write_text("tampered")
    if change == "extra":
        (root / "extra.py").write_text("raise Exception()")
    if change == "symlink":
        (root / "alias").symlink_to(root / "MLmodel")
    if change == "quota":
        limit = 10
    with pytest.raises(TabularError) as error:
        verify_model_bundle(root, artifact, family="tabular", max_bytes=limit)
    assert error.value.code == code


def test_artifact_cannot_expand_reader_trust_even_for_numpy(exported):
    root, artifact = exported
    config = yaml.safe_load((root / "MLmodel").read_text())
    config["flavors"]["sklearn"]["skops_trusted_types"].append("numpy.load")
    (root / "MLmodel").write_text(yaml.safe_dump(config))
    artifact = build_artifact_contract(
        root,
        family="tabular",
        serialization="skops",
        trusted_types=[*artifact["trusted_types"], "numpy.load"],
    )
    with pytest.raises(TabularError) as error:
        verify_model_bundle(root, artifact, family="tabular")
    assert error.value.code == "ML_ARTIFACT_UNTRUSTED_TYPES"


def test_decompressed_skops_budget_checked_before_type_inspection(exported, monkeypatch):
    import skops.io as sio

    root, artifact = exported
    with zipfile.ZipFile(root / "model.skops", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("schema.json", b"x" * 2_000_000)
    artifact = build_artifact_contract(
        root, family="tabular", serialization="skops", trusted_types=artifact["trusted_types"]
    )
    monkeypatch.setattr(
        sio, "get_untrusted_types", lambda **k: pytest.fail("inspect only bounded archives")
    )
    with pytest.raises(TabularError) as error:
        verify_model_bundle(root, artifact, family="tabular", max_bytes=100_000)
    assert error.value.code == "ML_ARTIFACT_LIMIT"


def test_download_uses_authorized_inventory_and_bounded_stream(exported, tmp_path, monkeypatch):
    from app.services.object_store import get_object_store
    from app.services.tabular_ml import download_model_dir, upload_model_dir

    root, artifact = exported
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    uri, _ = upload_model_dir(root, workspace_id="ws", model_id="model")
    model = SimpleNamespace(
        id="model", workspace_id="ws", model_uri=uri, metrics_json={"artifact": artifact}
    )
    target = tmp_path / "download"
    download_model_dir(model, target)
    verify_model_bundle(target, artifact, family="tabular")
    store = get_object_store()
    store.write_bytes(uri + "/extra", b"not inventoried")
    with pytest.raises(TabularError) as error:
        download_model_dir(model, tmp_path / "second")
    assert error.value.code == "ML_ARTIFACT_TAMPERED"
    with pytest.raises(ValueError):
        store.copy_to_local(uri + "/MLmodel", tmp_path / "bounded", max_bytes=1)
    assert not (tmp_path / "bounded").exists()


def test_cache_identity_changes_when_authorized_manifest_changes():
    from app.services.tabular_predict import _fingerprint

    model = SimpleNamespace(
        model_uri="model",
        status="ready",
        trained_at=None,
        updated_at=None,
        metrics_json={"artifact": {"files": {"MLmodel": "a"}}},
    )
    before = _fingerprint(model)
    model.metrics_json["artifact"]["files"]["MLmodel"] = "b"
    assert _fingerprint(model) != before


def test_serving_gate_refuses_before_mlflow_deserialization(exported, monkeypatch):
    import shutil

    from app.services import tabular_predict

    root, artifact = exported
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    model = SimpleNamespace(
        id="artifact-gate",
        status="ready",
        task="classification",
        family="tabular",
        trained_at=None,
        updated_at=None,
        model_uri="model",
        metrics_json={"artifact": artifact},
    )
    (root / "MLmodel").write_text("tampered")
    monkeypatch.setattr(
        tabular_predict,
        "download_model_dir",
        lambda _, directory: shutil.copytree(root, directory, dirs_exist_ok=True),
    )
    monkeypatch.setattr(
        tabular_predict, "_load_mlflow_model", lambda _: pytest.fail("must verify first")
    )
    with pytest.raises(TabularError) as error:
        tabular_predict.load_pipeline_traced(model)
    assert error.value.code == "ML_ARTIFACT_TAMPERED"
    assert not tabular_predict.drop_from_cache(model.id)


@pytest.mark.parametrize("task", ["classification", "regression"])
def test_tabicl_v1_export_is_refused_before_embedded_runtime_load(tmp_path, monkeypatch, task):
    import shutil

    from app.services import tabular_predict
    from app.services.huggingface import adapters

    root = tmp_path / "old-export"
    root.mkdir()
    (root / "MLmodel").write_text("flavors: {}")
    artifact = build_artifact_contract(
        root, family="tabular_foundation", serialization="json+safetensors"
    )
    assert artifact["trust_profile"] == "tabicl-json-safetensors-v2"
    artifact["trust_profile"] = "tabicl-json-safetensors-v1"
    model = SimpleNamespace(
        id=f"tabicl-old-profile-{task}",
        family="tabular_foundation",
        task=task,
        status="ready",
        trained_at=None,
        updated_at=None,
        model_uri="model",
        metrics_json={"artifact": artifact},
    )
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    monkeypatch.setattr(settings, "ml_runtime", "ml-deep")
    monkeypatch.setattr(adapters, "require_model_foundation", lambda _: None)
    monkeypatch.setattr(
        tabular_predict,
        "download_model_dir",
        lambda _, directory: shutil.copytree(root, directory, dirs_exist_ok=True),
    )
    monkeypatch.setattr(
        tabular_predict,
        "_load_mlflow_model",
        lambda _: pytest.fail("old bundled code must not load"),
    )
    with pytest.raises(TabularError) as refused:
        tabular_predict.load_pipeline_traced(model)
    assert refused.value.code == "ML_ARTIFACT_UNVERIFIED"
    assert not tabular_predict.drop_from_cache(model.id)


@pytest.mark.parametrize(
    "escape", ["../outside.joblib", "/tmp/outside.joblib", "https://example.test/model"]
)
def test_pyfunc_dependency_cannot_escape_verified_bundle(tmp_path, escape):
    import json

    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts/meta.json").write_text(
        json.dumps({"serialization": "joblib", "trusted": []})
    )
    (tmp_path / "artifacts/forecaster.joblib").write_bytes(b"never deserialized")
    (tmp_path / "ml_forecast_pyfunc.py").write_text("raise AssertionError('never executed')")
    config = {
        "flavors": {
            "python_function": {
                "loader_module": "mlflow.pyfunc.loaders.code_model",
                "model_code_path": "ml_forecast_pyfunc.py",
                "artifacts": {"forecaster": {"path": escape}},
            }
        }
    }
    (tmp_path / "MLmodel").write_text(yaml.safe_dump(config))
    artifact = build_artifact_contract(tmp_path, family="forecasting", serialization="joblib")
    with pytest.raises(TabularError) as error:
        verify_model_bundle(tmp_path, artifact, family="forecasting")
    assert error.value.code == "ML_ARTIFACT_UNVERIFIED"


@pytest.mark.parametrize("frequency", ["h", "D", "W", "MS", "QS"])
def test_forecast_profile_preserves_supported_calendar_frequencies(tmp_path, frequency):
    pytest.importorskip("skforecast")
    import skops.io as sio
    from skforecast.recursive import ForecasterRecursive
    from skforecast.utils import load_forecaster, save_forecaster
    from sklearn.linear_model import Ridge

    from app.services.ml.artifact_trust import FORECAST_TYPES

    series = pd.Series(
        np.arange(40, dtype=float), index=pd.date_range("2020-01-01", periods=40, freq=frequency)
    )
    model = ForecasterRecursive(Ridge(), lags=3)
    model.fit(series)
    path = str(tmp_path / "forecast.skops")
    save_forecaster(model, path, backend="skops", verbose=False)
    types = sio.get_untrusted_types(file=path)
    assert set(types).issubset(FORECAST_TYPES)
    loaded = load_forecaster(path, backend="skops", trusted=types, verbose=False)
    np.testing.assert_allclose(loaded.predict(steps=2), model.predict(steps=2))


def test_forecast_profile_roundtrips_catalog_seasonal_naive(tmp_path):
    pytest.importorskip("skforecast")
    import skops.io as sio
    from skforecast.recursive import ForecasterEquivalentDate
    from skforecast.utils import load_forecaster, save_forecaster

    from app.services.ml.artifact_trust import FORECAST_TYPES
    from app.services.ml.artifacts import validate_model_metadata

    series = pd.Series(
        12.0 + np.arange(84) % 7,
        index=pd.date_range("2026-01-01", periods=84, freq="D"),
    )
    # Exactly the catalog's seasonal_naive constructor: the default aggregator
    # is numpy.mean, serialized alongside ForecasterEquivalentDate by skops.
    model = ForecasterEquivalentDate(offset=7, n_offsets=1)
    model.fit(series)
    path = tmp_path / "forecast.skops"
    save_forecaster(model, str(path), backend="skops", verbose=False)
    types = sio.get_untrusted_types(file=str(path))
    assert "numpy.mean" in types
    assert set(types).issubset(FORECAST_TYPES)
    loaded = load_forecaster(str(path), backend="skops", trusted=types, verbose=False)
    np.testing.assert_allclose(loaded.predict(steps=28), model.predict(steps=28))

    # The reader still refuses another NumPy callable, even when a producer
    # records it. The forecast-only addition grants no imported-model trust.
    (tmp_path / "MLmodel").write_text("metadata-only trust check")
    artifact = build_artifact_contract(
        tmp_path, family="forecasting", serialization="skops", trusted_types=types
    )
    validate_model_metadata(artifact, family="forecasting")
    artifact["trusted_types"] = [*types, "numpy.load"]
    with pytest.raises(TabularError) as error:
        validate_model_metadata(artifact, family="forecasting")
    assert error.value.code == "ML_ARTIFACT_UNTRUSTED_TYPES"
    artifact.update(
        family="external", trust_profile="external-sklearn-skops-v1", trusted_types=["numpy.mean"]
    )
    with pytest.raises(TabularError) as error:
        validate_model_metadata(artifact, family="external")
    assert error.value.code == "ML_ARTIFACT_UNTRUSTED_TYPES"


def test_zip_entry_limit_precedes_eager_directory_allocation(tmp_path, monkeypatch):
    from app.services.ml import artifacts

    path = tmp_path / "large-directory.skops"
    with zipfile.ZipFile(path, "w") as archive:
        for k in range(3):
            archive.writestr(str(k), b"x")
    monkeypatch.setattr(artifacts, "MAX_ARCHIVE_ENTRIES", 2)
    monkeypatch.setattr(
        zipfile, "ZipFile", lambda *a, **k: pytest.fail("must check before allocation")
    )
    with pytest.raises(TabularError) as error:
        artifacts._check_skops_archive(path, max_bytes=1000)
    assert error.value.code == "ML_ARTIFACT_LIMIT"


def test_model_cannot_materialize_another_workspaces_namespace(tmp_path):
    from app.services.tabular_ml import download_model_dir

    model = SimpleNamespace(
        id="mine", workspace_id="mine", model_uri="workspaces/another/ml/models/other/model"
    )
    with pytest.raises(TabularError) as error:
        download_model_dir(model, tmp_path / "model")
    assert error.value.code == "ML_ARTIFACT_UNVERIFIED"
