"""A migration proves identity and preserves the trained export and its history."""

import copy
import io
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.huggingface import HubArtifact, HubArtifactGrant, HubArtifactUsage
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace
from app.services.huggingface import adapters, legacy_migration, registry
from app.services.huggingface.cache import ArtifactCache
from app.services.huggingface.errors import HFError
from app.services.ml.local_models import MODEL_SPECS, resolve_model
from app.services.tabular_datasets import TabularError
from app.tests.services.test_huggingface_runtime import (
    manifest_for,
    tiny_sentence_transformer_files,
)


@pytest.fixture
def legacy(db_session, tmp_path, monkeypatch):
    from app.services.huggingface import cache as cache_module

    files = tiny_sentence_transformer_files(tmp_path)
    legacy_root = tmp_path / "legacy"
    path = legacy_root / "mini"
    path.mkdir(parents=True)
    for name, data in files.items():
        destination = path / name
        destination.parent.mkdir(exist_ok=True, parents=True)
        destination.write_bytes(data)
    identity = str(uuid4())
    manifest = manifest_for(files, artifact_id=identity)
    manifest["repo_id"] = MODEL_SPECS["multilingual-minilm"]["upstream_id"]
    hashes = {name: entry["sha256"] for name, entry in manifest["files"].items()}
    (legacy_root / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "models": {
                    "multilingual-minilm": {
                        **MODEL_SPECS["multilingual-minilm"],
                        "revision": manifest["revision"],
                        "path": "mini",
                        "files": hashes,
                    }
                },
            }
        )
    )
    monkeypatch.setattr(settings, "ml_deep_models_dir", str(legacy_root))
    monkeypatch.setattr(settings, "ml_runtime", "ml-deep")
    local = resolve_model("multilingual-minilm", kind="embedding")
    cache = ArtifactCache(tmp_path / "cache", min_free_bytes=0)
    snapshot = cache.materialize(manifest, lambda name, entry: io.BytesIO(files[name]))
    monkeypatch.setattr(cache_module, "configured_cache", lambda: cache)
    monkeypatch.setattr(adapters, "configured_cache", lambda: cache)
    monkeypatch.setattr(legacy_migration, "dispatch_migration", lambda *_: None)
    workspace = Workspace(
        id=str(uuid4()), name="Migration", slug="migration-" + uuid4().hex, settings={}
    )
    user = User(id=str(uuid4()), username="migration-" + uuid4().hex, role="admin")
    db_session.add_all([workspace, user])
    artifact = HubArtifact(
        id=identity,
        identity_hash=uuid4().hex * 2,
        hub_endpoint="https://huggingface.co",
        kind="model",
        repo_id=manifest["repo_id"],
        revision=manifest["revision"],
        requested_ref="main",
        format="safetensors",
        selection_digest="c" * 64,
        manifest_json=manifest,
        files_json=manifest["files"],
        metadata_json={
            **manifest,
            "hub_endpoint": "https://huggingface.co",
            "license": "mit",
            "license_text": "MIT",
        },
        total_bytes=manifest["total_bytes"],
        status="ready",
    )
    db_session.add(artifact)
    db_session.add(
        HubArtifactGrant(
            workspace_id=workspace.id,
            artifact_id=identity,
            granted_by=user.id,
            license_digest="d" * 64,
            policy_version="policy",
        )
    )
    model = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Original",
        slug="original-" + uuid4().hex,
        family="tabular_deep",
        task="classification",
        algo="linear",
        target="class",
        status="ready",
        params_json={"foundation": local.public(), "original_setting": 123},
        runtime_json={"original_runtime": True},
        model_uri="s3://existing-trained-export",
    )
    db_session.add(model)
    db_session.commit()
    # Record a real local load+inference qualification, not metadata-only approval.
    probe = adapters.validate_local_artifact(workspace.id, identity, "embedding")
    registry.register_usage(
        db_session,
        workspace.id,
        identity,
        "adapter",
        identity,
        details={"validations": {"embedding:ml": probe}},
    )
    db_session.commit()
    return db_session, workspace, user, artifact, model, local, snapshot


def test_migration_preserves_trained_history_and_enforces_new_grant(legacy):
    db, workspace, user, artifact, model, local, snapshot = legacy
    original = copy.deepcopy((model.params_json, model.runtime_json, model.model_uri))
    job = legacy_migration.request_migration(
        db, workspace_id=workspace.id, model_id=model.id, artifact_id=artifact.id, actor=user.id
    )
    assert legacy_migration.run_migration(job.id)["status"] == "completed"
    db.refresh(model)
    assert (model.params_json, model.runtime_json, model.model_uri) == original
    migration = legacy_migration.migration_for(db, model)
    assert migration.artifact_id == artifact.id
    assert migration.details_json["original_foundation"] == original[0]["foundation"]
    adapters.require_model_foundation(model, db)
    registry.revoke_grant(
        db, workspace.id, artifact.id, actor=user.id, reason="Authorization withdrawn"
    )
    # An unavailable migration must never silently resume unguarded v1 serving.
    with pytest.raises(TabularError) as caught:
        adapters.require_model_foundation(model, db)
    assert caught.value.code == "HF_ACCESS_REVOKED"


@pytest.mark.parametrize("change", ["history", "revision", "repo", "files"])
def test_identity_comparison_refuses_near_matches(legacy, change):
    _, _, _, _, model, local, snapshot = legacy
    source = dict(model.params_json["foundation"])
    manifest = copy.deepcopy(snapshot.manifest)
    if change == "history":
        source["fingerprint"] = "f" * 64
    elif change == "revision":
        manifest["revision"] = "e" * 40
    elif change == "repo":
        manifest["repo_id"] = "another/model"
    else:
        manifest["files"].pop("config.json")
    with pytest.raises(HFError) as caught:
        legacy_migration.verify_legacy_identity(source, local, replace(snapshot, manifest=manifest))
    assert caught.value.code == "HF_MIGRATION_IDENTITY_MISMATCH"


def test_migration_requires_actual_activation_and_ready_trained_model(legacy):
    db, workspace, user, artifact, model, _, _ = legacy
    db.query(HubArtifactUsage).filter_by(kind="adapter", target_id=artifact.id).delete()
    db.commit()
    with pytest.raises(HFError) as caught:
        legacy_migration.request_migration(
            db, workspace_id=workspace.id, model_id=model.id, artifact_id=artifact.id, actor=user.id
        )
    assert caught.value.code == "HF_ADAPTER_NOT_VALIDATED"
    db.rollback()
    model.status = "pending"
    db.commit()
    with pytest.raises(HFError) as caught:
        legacy_migration.request_migration(
            db, workspace_id=workspace.id, model_id=model.id, artifact_id=artifact.id, actor=user.id
        )
    assert caught.value.code == "HF_MIGRATION_INCOMPATIBLE"
