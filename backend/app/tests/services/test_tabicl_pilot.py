"""TabICL pilot admission and non-executable artifact contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.resources.ml_tabicl_runtime import CHECKPOINTS, REVISION, expected_config, validate_weights
from app.services.ml.families import get_family


def test_family_does_not_reuse_embedding_harness():
    family = get_family("tabular_foundation")
    assert family.runtime == "ml-deep" and family.serving == "remote"
    assert family.harness.name == "ml_tabicl_harness.py"
    assert (
        family.parse_spec({"artifact_id": "f80d6db0-7a15-4bcc-b3fa-4dc6d7d927a8"})["kv_cache"]
        is False
    )
    with pytest.raises(ValueError):
        family.parse_spec(
            {"artifact_id": "f80d6db0-7a15-4bcc-b3fa-4dc6d7d927a8", "model_path": "/tmp/unchecked"}
        )


def test_pilot_is_unavailable_by_default(monkeypatch):
    from app.services.ml.runtime import family_availability

    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_tabicl_enabled", False)
    assert family_availability(get_family("tabular_foundation")) == (False, "experimental_disabled")


def _weight_config(task="classification"):
    return {
        "schema": 1,
        "tabicl": "2.2.0",
        "architectures": ["OmniragTabICLv2"],
        "task": task,
        "config": expected_config(task),
        "revision": REVISION,
        "source_sha256": CHECKPOINTS[task][1],
        "weights_sha256": "0" * 64,
    }


def test_configuration_cannot_allocate_arbitrary_architecture(tmp_path):
    config = _weight_config()
    config["config"]["embed_dim"] = 2**30
    (tmp_path / "config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="configuration"):
        validate_weights(tmp_path)


def test_changed_weights_are_refused_before_tensor_loading(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(_weight_config()))
    (tmp_path / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        validate_weights(tmp_path)


def test_revoked_grant_evicts_a_warm_model(monkeypatch):
    from app.services import tabular_predict
    from app.services.huggingface import adapters
    from app.services.huggingface.errors import HFError
    from app.services.tabular_datasets import TabularError

    monkeypatch.setattr(settings, "ml_tabicl_enabled", True)
    monkeypatch.setattr(settings, "ml_tabicl_workspaces", ["w"])
    evicted = []
    monkeypatch.setattr(tabular_predict, "drop_from_cache", lambda value: evicted.append(value))

    def revoked(*args, **kwargs):
        assert kwargs["usage"] == "tabular_foundation"
        raise HFError("HF_ACCESS_REVOKED", "Revoked")

    monkeypatch.setattr(adapters, "authorized_manifest", revoked)
    model = SimpleNamespace(
        id="m",
        family="tabular_foundation",
        workspace_id="w",
        params_json={"foundation": {"artifact_id": "a"}},
    )
    with pytest.raises(TabularError) as refused:
        adapters.require_model_foundation(model)
    assert refused.value.code == "HF_ACCESS_REVOKED"
    assert evicted == ["m"]


def test_no_legacy_grant_bypass(monkeypatch):
    from app.services import tabular_predict
    from app.services.huggingface import adapters
    from app.services.tabular_datasets import TabularError

    monkeypatch.setattr(settings, "ml_tabicl_enabled", True)
    monkeypatch.setattr(settings, "ml_tabicl_workspaces", ["w"])
    monkeypatch.setattr(tabular_predict, "drop_from_cache", lambda _: None)
    model = SimpleNamespace(id="m", family="tabular_foundation", workspace_id="w", params_json={})
    with pytest.raises(TabularError, match="grant"):
        adapters.require_model_foundation(model)


def test_converted_bundle_uses_existing_offline_store_and_grant(db_session, tmp_path, monkeypatch):
    import base64
    import hashlib
    from uuid import uuid4

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.models.huggingface import HubArtifactGrant
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.workspace_job import WorkspaceJob
    from app.services.huggingface import bundles, offline, registry
    from app.services.huggingface.storage import HubStore

    script = Path(__file__).resolve().parents[3] / "scripts" / "package_tabicl_bundle.py"
    module_spec = importlib.util.spec_from_file_location("package_tabicl_bundle", script)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    # Admission verifies provenance and bytes; actual tensor loading is separately
    # qualified using the official weights. No bogus tensor enters activation.
    converted = tmp_path / "converted"
    converted.mkdir()
    weight_bytes = b"admission-only-fake-tensor"
    (converted / "model.safetensors").write_bytes(weight_bytes)
    config = _weight_config()
    config["weights_sha256"] = hashlib.sha256(weight_bytes).hexdigest()
    (converted / "config.json").write_text(json.dumps(config))
    manifest = module.manifest_for(converted, "BSD-3-Clause test license evidence")
    assert manifest["repo_id"] == "omnirag-converted/tabicl-v2-classification"
    assert manifest["revision"] != REVISION
    assert manifest["conversion"]["source_revision"] == REVISION
    monkeypatch.setenv("HF_BUNDLE_SPOOL_DIR", str(tmp_path / "spool"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "hf_disk_min_free_bytes", 0)
    user = User(id=str(uuid4()), username=str(uuid4()), role="admin", is_active=True)
    workspace = Workspace(id=str(uuid4()), name="TabICL pilot", slug=str(uuid4()), settings={})
    db_session.add_all([user, workspace])
    db_session.commit()
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    monkeypatch.setenv(
        "HF_BUNDLE_TRUST_KEYS_JSON", json.dumps({"test": base64.b64encode(public).decode()})
    )
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=workspace.id,
        kind="hf_bundle_import",
        title="TabICL import",
        status="queued",
        created_by_user_id=user.id,
        input_ref={},
        result={},
    )
    db_session.add(job)
    db_session.commit()
    directory = offline.job_directory(job.id)
    directory.mkdir()
    with (directory / "upload.tar").open("wb") as output:
        bundles.export_bundle(
            output,
            manifest=manifest,
            open_file=lambda name: (converted / name).open("rb"),
            target_workspace_id=workspace.id,
            license_digest=manifest["license_digest"],
            signing_key=key,
            key_id="test",
            authorize=lambda *_: True,
        )
    original = HubStore.publish_manifest

    def publish(store, artifact_id, value):
        assert db_session.get(HubArtifactGrant, (workspace.id, artifact_id)) is None
        return original(store, artifact_id, value)

    monkeypatch.setattr(HubStore, "publish_manifest", publish)
    result = offline.run_bundle_job(db_session, job.id)
    artifact = registry.require_artifact(
        db_session, workspace.id, result["artifact_id"], usage="tabular_foundation"
    )
    assert artifact.manifest_json["conversion"] == manifest["conversion"]
    assert artifact.status == "ready"
    assert db_session.get(HubArtifactGrant, (workspace.id, artifact.id)) is not None


def test_training_checks_checkpoint_task_before_dispatch(monkeypatch):
    from app.services import tabular_ml
    from app.services.ml import runtime
    from app.services.tabular_datasets import TabularError

    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_tabicl_enabled", True)
    monkeypatch.setattr(settings, "ml_tabicl_workspaces", ["w"])
    monkeypatch.setattr(tabular_ml, "family_availability", lambda *_: (True, None))
    artifact_id = "f80d6db0-7a15-4bcc-b3fa-4dc6d7d927a8"
    descriptor = {"kind": "tabular_foundation", "task": "regression"}
    monkeypatch.setattr(runtime, "model_descriptors", lambda *a, **k: {artifact_id: descriptor})
    dataset = SimpleNamespace(
        status="ready",
        workspace_id="w",
        lineage_json={},
        produced_by="upload",
        row_count=100,
        name="Pilot",
        schema_json=[{"name": "x", "kind": "float"}, {"name": "target", "kind": "integer"}],
        stats_json={"target": {"distinct": 2}},
    )
    kwargs = {
        "task": "classification",
        "target": "target",
        "algo": "tabicl_v2",
        "spec": {"artifact_id": artifact_id},
    }
    with pytest.raises(TabularError, match="matching the task"):
        tabular_ml.validate_training(dataset, **kwargs)
    descriptor["task"] = "classification"
    result = tabular_ml.validate_training(dataset, **kwargs)
    assert result.family == "tabular_foundation" and result.algo.key == "tabicl_v2"
    assert result.spec["artifact_id"] == artifact_id


def test_harness_refuses_oversized_parquet_before_loading_rows(tmp_path, monkeypatch):
    import pandas as pd
    import pyarrow.parquet as parquet

    from app.resources import ml_tabicl_harness

    path = tmp_path / "large.parquet"
    pd.DataFrame({"x": range(10_001), "target": range(10_001)}).to_parquet(path)
    manifest = {
        "algo": "tabicl_v2",
        "data_path": str(path),
        "target": "target",
        "task": "regression",
        "features": ["x"],
        "progress_path": str(tmp_path / "progress"),
    }
    spec_path = tmp_path / "manifest.json"
    spec_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        parquet.ParquetFile,
        "read",
        lambda *_a, **_k: pytest.fail("Oversized table must not be materialized"),
    )
    assert ml_tabicl_harness.main(["harness", str(spec_path), str(tmp_path / "result.json")]) == 5
    assert not (tmp_path / "result.json").exists()
