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
    import shutil
    from contextlib import ExitStack
    from uuid import uuid4

    import numpy as np
    import pandas as pd
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.models.huggingface import HubArtifactGrant
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.workspace_job import WorkspaceJob
    from app.resources.ml_tabicl_notice import NOTICE_NAME, notice_document
    from app.resources.ml_tabicl_runtime import export_state
    from app.services.huggingface import bundles, offline, registry
    from app.services.huggingface.cache import ArtifactCache
    from app.services.huggingface.storage import HubStore
    from app.services.ml.local_models import resolve_artifact_model

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
    notice = notice_document()
    manifest = module.manifest_for(converted, notice["license_text"])
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

    # The provisioner's copy can disappear. The signed, inventoried notice must
    # travel via the ordinary ObjectStore/cache and autonomous export paths.
    shutil.rmtree(converted)
    cache = ArtifactCache(tmp_path / "cache", min_free_bytes=0)
    store = HubStore()
    with ExitStack() as streams:
        cache.materialize(
            artifact.manifest_json,
            lambda name, entry: streams.enter_context(store.open(entry["object_key"])),
        )
    local = resolve_artifact_model(
        artifact.id,
        kind="tabular_foundation",
        cache_dir=cache.root,
        manifest=artifact.manifest_json,
    )
    assert NOTICE_NAME in local.files
    # Export a tiny declared context without fitting or loading fake tensors.
    estimator = SimpleNamespace(
        model_path=local.path,
        classes_=np.array(["no", "yes"]),
        random_state=42,
        n_jobs=1,
        kv_cache=False,
    )
    exported = tmp_path / "exported"
    export_state(estimator, pd.DataFrame({"x": [1.0, 2.0]}), ["no", "yes"], exported)
    shutil.rmtree(cache.root)
    transported = exported / "foundation" / NOTICE_NAME
    assert json.loads(transported.read_text()) == notice
    assert hashlib.sha256(transported.read_bytes()).hexdigest() == local.files[NOTICE_NAME]
    assert (exported / "foundation" / "model.safetensors").read_bytes() == weight_bytes


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

    descriptor["task"] = kwargs["task"] = "regression"
    for cache_spec in ({}, {"kv_cache": False}, {"kv_cache": True}):
        kwargs["spec"] = {"artifact_id": artifact_id, **cache_spec}
        with pytest.raises(TabularError) as refused:
            tabular_ml.validate_training(dataset, **kwargs)
        assert refused.value.code == "ML_TABICL_PROFILE_UNQUALIFIED"
        assert refused.value.status_code == 409
        assert refused.value.details == {"task": "regression", "reason": "reload_parity"}


@pytest.mark.parametrize("kv_cache", [False, True])
def test_unqualified_regression_is_refused_before_warm_cache_or_grant(monkeypatch, kv_cache):
    from app.services import tabular_predict
    from app.services.huggingface import adapters
    from app.services.tabular_datasets import TabularError

    monkeypatch.setattr(settings, "ml_tabicl_enabled", True)
    monkeypatch.setattr(settings, "ml_tabicl_workspaces", ["w"])
    evicted, authorized = [], []
    monkeypatch.setattr(tabular_predict, "drop_from_cache", evicted.append)
    monkeypatch.setattr(adapters, "authorized_manifest", lambda *a, **k: authorized.append(a))
    model = SimpleNamespace(
        id="m",
        task="regression",
        family="tabular_foundation",
        workspace_id="w",
        spec_json={"kv_cache": kv_cache},
        params_json={"foundation": {"artifact_id": "a"}},
    )
    with pytest.raises(TabularError) as refused:
        adapters.require_model_foundation(model)
    assert refused.value.code == "ML_TABICL_PROFILE_UNQUALIFIED"
    assert evicted == ["m"] and not authorized
    assert model.spec_json["kv_cache"] is kv_cache
    model.task = "classification"
    adapters.require_model_foundation(model)
    assert authorized == [("w", "a")]


@pytest.mark.parametrize("kv_cache", [False, True])
def test_withdrawn_regression_cannot_run_publish_or_be_promoted(
    db_session, tmp_path, monkeypatch, kv_cache
):
    from collections import OrderedDict
    from uuid import uuid4

    from app.models.tabular import MLModel
    from app.services import tabular_ml, tabular_predict
    from app.services.ml import deep_serving, runtime
    from app.services.tabular_datasets import TabularError

    model = MLModel(
        id=str(uuid4()),
        workspace_id=str(uuid4()),
        name="Withdrawn pilot",
        slug="withdrawn-pilot",
        version=1,
        task="regression",
        family="tabular_foundation",
        algo="tabicl_v2",
        target="y",
        features=["x"],
        spec_json={"kv_cache": kv_cache},
        params_json={},
        status="ready",
        model_uri="existing-export",
        metrics_json={"artifact": {"trust_profile": "tabicl-json-safetensors-v2"}},
    )
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    monkeypatch.setattr(settings, "ml_runtime", "ml-deep")
    monkeypatch.setattr(tabular_predict, "champion_for", lambda *a, **k: model)
    monkeypatch.setattr(tabular_predict, "contract_fields", lambda _: [])
    monkeypatch.setattr(tabular_predict, "published_skill", lambda *a: None)
    monkeypatch.setattr(tabular_predict, "list_api_keys", lambda *a, **k: [])
    monkeypatch.setattr(runtime, "serving_availability", lambda *a: (True, None))
    monkeypatch.setattr(
        tabular_predict, "_load_mlflow_model", lambda _: pytest.fail("No deserialization allowed")
    )
    cached_dir = tmp_path / "cache"
    cached_dir.mkdir()
    entry = tabular_predict.LoadedModel(
        model.id, tabular_predict._fingerprint(model), object(), [], cached_dir, 0, 0
    )
    monkeypatch.setattr(tabular_predict, "_cache", OrderedDict({model.id: entry}))
    # The service policy precedes warm-cache reuse and does not confuse the v2
    # format/CPU contract with numerical qualification of a regression model.
    with pytest.raises(TabularError) as refused:
        tabular_predict.load_pipeline_traced(model)
    assert refused.value.code == "ML_TABICL_PROFILE_UNQUALIFIED"
    assert model.id not in tabular_predict._cache and not cached_dir.exists()

    for call in (
        lambda: deep_serving.request_rows(db_session, model, [{"x": 1}]),
        lambda: tabular_ml._write_manifest(tmp_path, model, tmp_path / "unread.parquet"),
        lambda: tabular_ml.set_champion(db_session, model),
        lambda: tabular_predict.publish_as_skill(db_session, model=model),
    ):
        with pytest.raises(TabularError) as refused:
            call()
        assert refused.value.code == "ML_TABICL_PROFILE_UNQUALIFIED"
    assert not model.is_champion
    serving = tabular_predict.serving_block(db_session, model)
    assert serving["callable"] is False
    assert serving["refusal"]["code"] == "ML_TABICL_PROFILE_UNQUALIFIED"
    assert serving["refusal"]["task"] == "regression"
    assert serving["refusal"]["reason"] == "reload_parity"


@pytest.mark.parametrize(
    "family,task", [("tabular_foundation", "classification"), ("tabular", "regression")]
)
def test_regression_withdrawal_does_not_restrict_other_profiles(family, task):
    from app.services.ml.families.tabular_foundation import require_qualified_model

    for kv_cache in (False, True):
        require_qualified_model(
            SimpleNamespace(family=family, task=task, spec_json={"kv_cache": kv_cache})
        )


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


@pytest.mark.parametrize("threads,expected", [("1", 1), ("2", 2), ("4", 4), ("32", 4), ("0", 1)])
def test_tabicl_training_respects_supervisor_thread_limit(monkeypatch, threads, expected):
    from app.resources.ml_tabicl_harness import training_threads

    monkeypatch.setenv("OMP_NUM_THREADS", threads)
    assert training_threads() == expected


@pytest.mark.parametrize(
    "requested,envelope,expected", [(4, "1", 1), (4, "2", 2), (2, "4", 2), (4, "32", 4)]
)
def test_tabicl_reload_profile_cannot_expand_worker_threads(
    monkeypatch, requested, envelope, expected
):
    from app.resources.ml_tabicl_runtime import execution_threads

    monkeypatch.setenv("OMP_NUM_THREADS", envelope)
    assert execution_threads(requested) == expected
