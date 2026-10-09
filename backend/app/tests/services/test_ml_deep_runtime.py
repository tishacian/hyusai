from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.tabular import MLRuntimeHeartbeat
from app.services.ml import local_models, runtime


@pytest.fixture(autouse=True)
def clean_deep_heartbeats(db_session):
    runtime.runtime_fingerprint.cache_clear()
    # The shared conftest deliberately clears only its named runtime tables.
    db_session.query(MLRuntimeHeartbeat).filter(MLRuntimeHeartbeat.runtime == "ml-deep").delete(synchronize_session=False)
    db_session.commit()
    yield
    runtime.runtime_fingerprint.cache_clear()
    db_session.query(MLRuntimeHeartbeat).filter(MLRuntimeHeartbeat.runtime == "ml-deep").delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    directory = tmp_path / "chronos-2-small"
    directory.mkdir()
    (directory / "config.json").write_text('{"model_type":"chronos2"}')
    (directory / "model.safetensors").write_bytes(b"qualified weights")
    entry = {
        **local_models.MODEL_SPECS["chronos-2-small"],
        "revision": "a" * 40,
        "path": "chronos-2-small",
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir()},
    }
    (tmp_path / "manifest.json").write_text(json.dumps({"version": 1, "models": {"chronos-2-small": entry}}))
    monkeypatch.setattr(settings, "ml_deep_models_dir", str(tmp_path))
    monkeypatch.setattr(settings, "ml_runtime", "ml-deep")
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    return tmp_path


def test_verified_local_identity_and_manifest_provenance(bundle):
    model = local_models.resolve_model("chronos-2-small", kind="forecasting")
    assert model.path == bundle / "chronos-2-small"
    assert model.revision == "a" * 40
    assert model.upstream_id == "autogluon/chronos-2-small"
    assert len(model.fingerprint) == 64
    assert "path" not in model.public() and "files" not in model.public()
    assert local_models.local_model_descriptors()["chronos-2-small"] == model.public()
    with pytest.raises(local_models.LocalModelError, match="not offered"):
        local_models.resolve_model("https://remote/model", kind="forecasting")
    with pytest.raises(local_models.LocalModelError, match="not offered"):
        local_models.resolve_model("chronos-2-small", kind="embedding")


@pytest.mark.parametrize("mutation", ["hash", "extra", "missing", "escape", "symlink", "revision", "upstream"])
def test_refuse_changed_or_unallowlisted_model_bytes(bundle, mutation):
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = manifest["models"]["chronos-2-small"]
    directory = bundle / "chronos-2-small"
    if mutation == "hash":
        (directory / "model.safetensors").write_bytes(b"modified weights")
    elif mutation == "extra":
        (directory / "unlisted.py").write_text("raise RuntimeError")
    elif mutation == "missing":
        (directory / "model.safetensors").unlink()
    elif mutation == "escape":
        entry["path"] = "../another-model"
    elif mutation == "symlink":
        outside = bundle / "outside.bin"
        outside.write_bytes(b"qualified weights")
        (directory / "model.safetensors").unlink()
        (directory / "model.safetensors").symlink_to(outside)
    elif mutation == "revision":
        entry["revision"] = "main"
    elif mutation == "upstream":
        entry["upstream_id"] = "somebody/another-model"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(local_models.LocalModelError) as error:
        local_models.resolve_model("chronos-2-small", kind="forecasting")
    assert error.value.code == "ML_DEEP_MODEL_INVALID"
    assert "chronos-2-small" not in local_models.local_model_descriptors()


def test_heartbeat_cache_invalidates_and_training_never_reuses_hashes(bundle):
    assert local_models.local_model_descriptors()
    (bundle / "chronos-2-small" / "model.safetensors").write_bytes(b"unqualified bytes")
    assert local_models.local_model_descriptors() == {}
    with pytest.raises(local_models.LocalModelError, match="changed"):
        local_models.resolve_model("chronos-2-small", kind="forecasting")


def test_absent_model_cannot_appear_available(bundle, monkeypatch):
    with pytest.raises(local_models.LocalModelError) as error:
        local_models.resolve_model("multilingual-minilm", kind="embedding")
    assert error.value.code == "ML_DEEP_MODEL_MISSING"
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    assert runtime.model_availability("chronos-2-small") == (True, None)
    assert runtime.model_availability("multilingual-minilm") == (False, "model_missing")
    assert runtime.model_availability("unknown") == (False, "model_unknown")


def test_only_verified_live_training_worker_offers_model(bundle, db_session):
    now = datetime.utcnow()
    assert runtime.model_availability("chronos-2-small", db_session) == (False, "no_worker")
    runtime.beat(db_session, queues=["ml_deep_rpc"], hostname="deep", now=now)
    db_session.commit()
    assert runtime.model_availability("chronos-2-small", db_session, now=now) == (False, "no_worker")
    runtime.beat(db_session, queues=["ml_deep"], hostname="deep", now=now)
    db_session.commit()
    assert runtime.model_availability("chronos-2-small", db_session, now=now) == (True, None)
    assert runtime.model_availability("chronos-2-small", db_session, now=now + timedelta(hours=1)) == (False, "no_worker")
    public = runtime.model_descriptors(db_session)["chronos-2-small"]
    assert "path" not in public and public["fingerprint"]
    (bundle / "chronos-2-small" / "model.safetensors").write_bytes(b"changed")
    runtime.beat(db_session, queues=["ml_deep"], hostname="deep", now=now)
    db_session.commit()
    assert runtime.model_availability("chronos-2-small", db_session, now=now) == (False, "model_missing")


def test_mixed_worker_model_revisions_are_unavailable(bundle, db_session):
    runtime.beat(db_session, queues=["ml_deep"], hostname="deep-one")
    runtime.beat(db_session, queues=["ml_deep"], hostname="deep-two")
    db_session.commit()
    assert runtime.model_availability("chronos-2-small", db_session) == (True, None)
    row = db_session.get(MLRuntimeHeartbeat, ("ml-deep", "deep-two"))
    descriptor = dict(row.packages_json["agentium_models"]["chronos-2-small"], revision="b" * 40)
    row.packages_json = {"agentium_models": {"chronos-2-small": descriptor}}
    db_session.commit()
    assert runtime.model_availability("chronos-2-small", db_session) == (False, "model_missing")


def test_manifest_provisioning_is_explicit(bundle):
    script = Path(__file__).resolve().parents[3] / "scripts" / "provision_ml_deep_manifest.py"
    output = subprocess.run([sys.executable, str(script), "--models-dir", str(bundle), "--model-id", "chronos-2-small", "--path", "chronos-2-small", "--revision", "b" * 40], capture_output=True, text=True, timeout=20)
    assert output.returncode == 0, output.stderr
    assert json.loads(output.stdout)["revision"] == "b" * 40
    assert local_models.resolve_model("chronos-2-small", kind="forecasting").revision == "b" * 40
