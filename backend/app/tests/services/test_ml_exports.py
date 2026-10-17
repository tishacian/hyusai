"""A verified bundle remains usable by the real, standalone MLflow HTTP server."""

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.core.config import settings
from app.resources.ml_artifact_contract import build_artifact_contract
from app.services.ml_exports import build_export
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import upload_model_dir


@pytest.fixture
def exported_model(tmp_path, monkeypatch):
    import mlflow.sklearn
    import skops.io as sio
    from mlflow.models import infer_signature
    from sklearn.linear_model import LogisticRegression

    frame = pd.DataFrame({"x": [-2.0, -1.0, 1.0, 2.0], "z": [0.0, 1.0, 0.0, 1.0]})
    estimator = LogisticRegression().fit(frame, [0, 0, 1, 1])
    types = sio.get_untrusted_types(data=sio.dumps(estimator))
    source = tmp_path / "producer"
    from app.resources.ml_artifact_contract import runtime_versions

    requirements = [
        f"{name}=={version}"
        for name, version in runtime_versions("tabular", "skops").items()
        if name != "python"
    ]
    mlflow.sklearn.save_model(
        estimator,
        path=str(source),
        serialization_format="skops",
        skops_trusted_types=types,
        signature=infer_signature(frame, estimator.predict(frame)),
        input_example=frame,
        pip_requirements=requirements,
    )
    artifact = build_artifact_contract(
        source, family="tabular", serialization="skops", trusted_types=types
    )
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    uri, size = upload_model_dir(source, workspace_id="workspace", model_id="model")
    model = SimpleNamespace(
        id="model",
        workspace_id="workspace",
        version=7,
        family="tabular",
        task="classification",
        status="ready",
        model_uri=uri,
        metrics_json={"artifact": artifact},
        artifact_bytes=size,
    )
    return model, estimator, frame, source


def test_export_preserves_producer_files_and_complete_hashes(exported_model, tmp_path):
    model, _, _, source = exported_model
    path, metadata = build_export(model, tmp_path / "export")
    assert metadata["archive_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("export-manifest.json"))
        assert manifest["model"]["version"] == 7
        assert set(archive.namelist()) == set(manifest["files"]) | {"export-manifest.json"}
        for name, item in manifest["files"].items():
            payload = archive.read(name)
            assert len(payload) == item["bytes"]
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]
        for name in model.metrics_json["artifact"]["files"]:
            assert archive.read("model/" + name) == (source / name).read_bytes()
        assert json.loads(archive.read("artifact-contract.json")) == model.metrics_json["artifact"]
        assert b"mlflow models serve -m . --env-manager local" in archive.read("README.md")


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("tamper", "ML_ARTIFACT_TAMPERED"),
        ("runtime", "ML_ARTIFACT_RUNTIME_MISMATCH"),
        ("legacy", "ML_ARTIFACT_LEGACY_UNSUPPORTED"),
        ("namespace", "ML_ARTIFACT_UNVERIFIED"),
        ("status", "ML_MODEL_NOT_READY"),
    ],
)
def test_export_refuses_unverified_sources_before_deserialization(
    exported_model, tmp_path, monkeypatch, mutation, code
):
    import mlflow.pyfunc
    import skops.io as sio

    from app.services.object_store import get_object_store

    model, _, _, _ = exported_model
    monkeypatch.setattr(
        mlflow.pyfunc, "load_model", lambda *a, **k: pytest.fail("no model loading during export")
    )
    monkeypatch.setattr(
        sio, "load", lambda *a, **k: pytest.fail("no estimator reconstruction during export")
    )
    if mutation == "tamper":
        get_object_store().write_bytes(model.model_uri + "/MLmodel", b"tampered")
    elif mutation == "runtime":
        model.metrics_json["artifact"]["runtime"]["mlflow"] = "0.0.0"
    elif mutation == "legacy":
        model.metrics_json["artifact"].pop("contract_version")
    elif mutation == "namespace":
        model.model_uri = model.model_uri.replace("workspace", "other-workspace")
    else:
        model.status = "training"
    with pytest.raises(TabularError) as error:
        build_export(model, tmp_path / "refused")
    assert error.value.code == code


def test_real_mlflow_http_server_predicts_without_repo_or_registry(exported_model, tmp_path):
    model, estimator, frame, _ = exported_model
    archive, _ = build_export(model, tmp_path / "export")
    isolated = tmp_path / "standalone"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(isolated)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ
    }
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.update(
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR="false",
    )
    log = tmp_path / "standalone-server.log"
    with log.open("w") as output:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mlflow",
                "models",
                "serve",
                "-m",
                ".",
                "--env-manager",
                "local",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
            ],
            cwd=isolated / "model",
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    pytest.fail("MLflow server exited: " + log.read_text()[-4000:])
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/ping", timeout=1
                    ) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                pytest.fail("MLflow did not start: " + log.read_text()[-4000:])
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/invocations",
                data=(isolated / "model/serving_input_example.json").read_bytes(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read())
            np.testing.assert_array_equal(result["predictions"], estimator.predict(frame))
            assert result["predictions"] == [0, 0, 1, 1]
        finally:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)


def test_an_attested_reader_exports_with_its_attestation(exported_model, tmp_path):
    """M4.2: an older producer runtime exports only under an attested reader."""
    from app.resources.ml_artifact_contract import runtime_versions
    from app.services.ml.artifacts import artifact_fingerprint

    model, _, _, _ = exported_model
    model.metrics_json["artifact"]["runtime"]["scikit-learn"] = "0.0.0"
    artifact = model.metrics_json["artifact"]
    with pytest.raises(TabularError) as refused:
        build_export(model, tmp_path / "refused")
    assert refused.value.code == "ML_ARTIFACT_RUNTIME_MISMATCH"
    attestation = {
        "id": "attestation-1",
        "artifact_fingerprint": artifact_fingerprint(artifact),
        "producer_runtime": artifact["runtime"],
        "reader_runtime": runtime_versions("tabular", "skops"),
        "reference_sha256": "a" * 64,
        "rows_compared": 7,
        "metrics": {"label_disagreements": 0},
        "tolerances": {"proba_atol": 1e-6},
        "created_at": "2026-10-16T10:00:00",
    }
    path, metadata = build_export(model, tmp_path / "export", attested=[attestation])
    assert metadata["attestations"] == ["attestation-1"]
    with zipfile.ZipFile(path) as archive:
        shipped = json.loads(archive.read("runtime-attestations.json"))
        manifest = json.loads(archive.read("export-manifest.json"))
        readme = archive.read("README.md").decode()
    assert shipped["attestations"] == [attestation]
    assert "runtime-attestations.json" in manifest["files"]
    assert "OR under a reader runtime listed in" in readme


def test_an_unattested_export_ships_no_attestation_file(exported_model, tmp_path):
    model, _, _, _ = exported_model
    path, metadata = build_export(model, tmp_path / "export")
    assert metadata["attestations"] == []
    with zipfile.ZipFile(path) as archive:
        assert "runtime-attestations.json" not in archive.namelist()
