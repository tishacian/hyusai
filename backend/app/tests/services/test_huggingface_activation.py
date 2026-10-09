"""Adapter activation publishes only after a real probe and final grant check."""

import io
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.huggingface import HubArtifact, HubArtifactGrant, HubArtifactUsage
from app.models.user import User
from app.models.workspace import Workspace
from app.services.huggingface import activation, adapters, registry
from app.services.huggingface.cache import ArtifactCache
from app.tests.services.test_huggingface_runtime import manifest_for, tiny_onnx_files


@pytest.fixture
def ready(db_session, tmp_path, monkeypatch):
    from app.services.huggingface import cache as cache_module

    workspace = Workspace(
        id=str(uuid4()), name="Adapters", slug="adapter-" + uuid4().hex, settings={}
    )
    user = User(id=str(uuid4()), username="adapter-" + uuid4().hex, role="admin")
    db_session.add_all([workspace, user])
    files = tiny_onnx_files()
    identity = str(uuid4())
    manifest = manifest_for(files, artifact_id=identity, format="onnx")
    cache = ArtifactCache(tmp_path, min_free_bytes=0)
    cache.materialize(manifest, lambda name, entry: io.BytesIO(files[name]))
    metadata = {
        **manifest,
        "hub_endpoint": "https://huggingface.co",
        "license": "mit",
        "license_text": "MIT",
    }
    artifact = HubArtifact(
        id=identity,
        identity_hash=uuid4().hex * 2,
        hub_endpoint="https://huggingface.co",
        kind="model",
        repo_id=manifest["repo_id"],
        revision=manifest["revision"],
        requested_ref="main",
        format="onnx",
        selection_digest="c" * 64,
        manifest_json=manifest,
        files_json=manifest["files"],
        metadata_json=metadata,
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
    db_session.commit()
    monkeypatch.setattr(adapters, "configured_cache", lambda: cache)
    monkeypatch.setattr(cache_module, "configured_cache", lambda: cache)
    monkeypatch.setattr(activation, "dispatch_activation", lambda *_: None)
    return db_session, workspace, user, artifact, cache


def submit(ready):
    db, workspace, user, artifact, _ = ready
    return activation.request_activation(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact.id,
        usage="reranker",
        runtime="rag",
        actor=user.id,
    )


def test_actual_activation_is_idempotent_and_records_runtime(ready):
    db, workspace, user, artifact, _ = ready
    job = submit(ready)
    assert submit(ready).id == job.id
    assert not db.query(HubArtifactUsage).filter_by(artifact_id=artifact.id).first()
    result = activation.run_activation(job.id)
    assert result["status"] == "completed"
    row = db.query(HubArtifactUsage).filter_by(artifact_id=artifact.id, kind="adapter").one()
    assert row.status == "active"
    probe = row.details_json["validations"]["reranker:rag"]
    assert probe["validation"] == "loaded_and_inferred"
    assert probe["runtime"]["onnxruntime"]
    db.refresh(job)
    assert registry.public_job(job)["result"]["probe"]["usage"] == "reranker"
    assert "runtime_identity" not in registry.public_job(job)["result"]["probe"]
    assert activation.run_activation(job.id)["status"] == "completed"
    db.refresh(artifact)
    assert artifact.last_used_at is not None


def test_revocation_after_probe_prevents_activation_publication(ready, monkeypatch):
    db, workspace, user, artifact, _ = ready
    job = submit(ready)
    actual = adapters.validate_local_artifact

    def probe_and_revoke(*args, **kwargs):
        result = actual(*args, **kwargs)
        with SessionLocal() as session:
            registry.revoke_grant(
                session, workspace.id, artifact.id, actor=user.id, reason="Withdrawn during probe"
            )
        return result

    monkeypatch.setattr(adapters, "validate_local_artifact", probe_and_revoke)
    result = activation.run_activation(job.id)
    assert result["status"] == "failed" and result["error_code"] == "HF_ACCESS_REVOKED"
    assert not db.query(HubArtifactUsage).filter_by(artifact_id=artifact.id).first()


def test_cancelled_and_interrupted_activation_never_publish(ready):
    db, workspace, user, artifact, _ = ready
    job = submit(ready)
    activation.cancel_activation(db, workspace.id, job.id, actor=user.id)
    assert activation.run_activation(job.id)["status"] == "cancelled"
    retry = submit(ready)
    retry.status = "running"
    retry.updated_at = datetime.utcnow() - timedelta(seconds=settings.hf_import_timeout_seconds + 1)
    db.commit()
    assert activation.recover_activations(db) == 1
    db.refresh(retry)
    assert retry.status == "failed" and retry.error == "HF_ADAPTER_INTERRUPTED"
    assert not db.query(HubArtifactUsage).filter_by(artifact_id=artifact.id).first()


def test_wrong_ml_worker_cannot_qualify_an_artifact(ready, monkeypatch):
    db, workspace, user, artifact, _ = ready
    job = activation.request_activation(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact.id,
        usage="reranker",
        runtime="ml",
        actor=user.id,
    )
    monkeypatch.setattr(settings, "ml_runtime", "worker")
    assert activation.run_activation(job.id)["error_code"] == "HF_RUNTIME_MISSING"
    assert not db.query(HubArtifactUsage).filter_by(artifact_id=artifact.id).first()


def test_disabled_request_actor_cannot_activate_queued_artifact(ready):
    db, workspace, user, artifact, _ = ready
    job = submit(ready)
    user.is_active = False
    db.commit()
    result = activation.run_activation(job.id)
    assert result["status"] == "failed"
    assert not db.query(HubArtifactUsage).filter_by(artifact_id=artifact.id).first()


def test_actor_demotion_during_probe_prevents_publication(ready, monkeypatch):
    db, workspace, user, artifact, _ = ready
    job = submit(ready)
    actual = adapters.validate_local_artifact

    def probe_and_demote(*args, **kwargs):
        result = actual(*args, **kwargs)
        with SessionLocal() as session:
            actor = session.get(User, user.id)
            actor.role = "user"
            session.commit()
        return result

    monkeypatch.setattr(adapters, "validate_local_artifact", probe_and_demote)
    result = activation.run_activation(job.id)
    assert result["status"] == "failed" and result["error_code"] == "WORKSPACE_PERMISSION_DENIED"
    assert not db.query(HubArtifactUsage).filter_by(artifact_id=artifact.id).first()
