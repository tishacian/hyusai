"""Offline jobs use verified evidence, real storage and registry transactions."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from datetime import datetime
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import settings
from app.models.huggingface import HubArtifact, HubArtifactGrant, HubImportReservation
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import bundles, offline, policy, registry
from app.services.huggingface.errors import HFError
from app.services.huggingface.fetch import base_manifest
from app.services.huggingface.storage import HubStore, blob_key


@pytest.fixture
def environment(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_BUNDLE_SPOOL_DIR", str(tmp_path / "spool"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "hf_disk_min_free_bytes", 0)
    user = User(id=str(uuid4()), username=str(uuid4()), role="admin", is_active=True)
    workspace = Workspace(id=str(uuid4()), name="Offline", slug=str(uuid4()), settings={})
    db_session.add_all([user, workspace])
    db_session.commit()
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    monkeypatch.setenv(
        "HF_BUNDLE_TRUST_KEYS_JSON", json.dumps({"test": base64.b64encode(public).decode()})
    )
    return db_session, workspace, user, key


def manifest(tag="mit", **flags):
    payload = b"four"
    source = {
        "size_bytes": len(payload),
        "upstream_hash": {"algorithm": "sha256", "value": hashlib.sha256(payload).hexdigest()},
    }
    metadata = {
        "hub_endpoint": "https://huggingface.co",
        "kind": "model",
        "repo_id": "acme/model",
        "revision": "a" * 40,
        "requested_ref": "main",
        "license": tag,
        "license_text": "license terms",
        "files": [{"path": "model.gguf", **source}],
        **flags,
    }
    files, plan = registry.select_files(metadata, {"format": "gguf", "variant": "model.gguf"})
    digest = registry.digest({"plan": plan, "files": files})
    artifact = HubArtifact(
        id=str(uuid4()),
        hub_endpoint=metadata["hub_endpoint"],
        kind="model",
        repo_id=metadata["repo_id"],
        revision=metadata["revision"],
        requested_ref="main",
        format="gguf",
        variant=plan.get("variant"),
        selection_digest=digest,
        selection_json=plan,
        files_json=files,
        metadata_json=metadata,
    )
    return {
        **base_manifest(artifact),
        "total_bytes": len(payload),
        "files": {
            "model.gguf": {
                **source,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "object_key": blob_key(artifact, "model.gguf"),
            }
        },
    }, payload


def upload_job(environment, manifest, payload):
    db, workspace, user, key = environment
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=workspace.id,
        kind="hf_bundle_import",
        title="Offline import",
        status="queued",
        created_by_user_id=user.id,
        input_ref={},
        result={},
    )
    db.add(job)
    db.commit()
    directory = offline.job_directory(job.id)
    directory.mkdir(mode=0o700)
    with (directory / "upload.tar").open("wb") as stream:
        bundles.export_bundle(
            stream,
            manifest=manifest,
            open_file=lambda _: io.BytesIO(payload),
            target_workspace_id=workspace.id,
            license_digest=policy.license_digest(manifest, manifest["license_text"]),
            signing_key=key,
            key_id="test",
            authorize=lambda *_: None,
            verify_hub_access=lambda *_: None,
        )
    return job


@pytest.mark.parametrize("restricted", [False, True])
def test_signed_import_publishes_before_grant_without_hub(environment, monkeypatch, restricted):
    db, workspace, _, _ = environment
    value, payload = manifest(gated=restricted)
    job = upload_job(environment, value, payload)
    from app.services.huggingface.client import HFClient

    monkeypatch.setattr(
        HFClient, "repo_info", lambda *_: pytest.fail("Offline replay must not contact Hub")
    )
    original = HubStore.publish_manifest

    def publish(store, artifact_id, manifest):
        assert db.get(HubArtifactGrant, (workspace.id, artifact_id)) is None
        return original(store, artifact_id, manifest)

    monkeypatch.setattr(HubStore, "publish_manifest", publish)
    result = offline.run_bundle_job(db, job.id)
    artifact = registry.require_artifact(db, workspace.id, result["artifact_id"])
    assert artifact.status == "ready"
    assert artifact.manifest_json == value
    assert db.get(HubImportReservation, job.id) is None
    assert not (offline.job_directory(job.id) / "upload.tar").exists()
    assert offline.run_bundle_job(db, job.id) == result


def test_corrupt_content_never_grants_and_releases_reservation(environment):
    db, workspace, _, _ = environment
    value, payload = manifest()
    job = upload_job(environment, value, payload)
    path = offline.job_directory(job.id) / "upload.tar"
    path.write_bytes(path.read_bytes().replace(b"four", b"five"))
    with pytest.raises(HFError) as error:
        offline.run_bundle_job(db, job.id)
    assert error.value.code == "HF_BUNDLE_CONTENT_MISMATCH"
    assert db.get(HubArtifactGrant, (workspace.id, value["artifact_id"])) is None
    assert db.get(HubImportReservation, job.id) is None
    assert db.get(WorkspaceJob, job.id).status == "failed"


@pytest.mark.parametrize(
    "tag,code", [("unknown", "HF_LICENSE_BLOCKED"), ("gemma", "HF_LICENSE_ACCEPTANCE_REQUIRED")]
)
def test_signed_license_still_requires_current_workspace_policy(environment, tag, code):
    db, workspace, _, _ = environment
    value, payload = manifest(tag=tag)
    job = upload_job(environment, value, payload)
    with pytest.raises(HFError) as error:
        offline.run_bundle_job(db, job.id)
    assert error.value.code == code
    assert db.get(HubArtifactGrant, (workspace.id, value["artifact_id"])) is None


def test_selection_identity_cannot_be_changed_even_by_signed_bundle(environment):
    db, workspace, _, _ = environment
    value, payload = manifest()
    value["selection_digest"] = "b" * 64
    job = upload_job(environment, value, payload)
    with pytest.raises(HFError, match="selection digest"):
        offline.run_bundle_job(db, job.id)
    assert db.get(HubArtifactGrant, (workspace.id, value["artifact_id"])) is None


def test_export_job_rechecks_current_grant(environment, monkeypatch, tmp_path):
    db, workspace, user, key = environment
    value, payload = manifest()
    source_job = upload_job(environment, value, payload)
    offline.run_bundle_job(db, source_job.id)
    signing = tmp_path / "signing.key"
    signing.write_bytes(
        key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("HF_BUNDLE_SIGNING_KEY_PATH", str(signing))
    monkeypatch.setenv("HF_BUNDLE_SIGNING_KEY_ID", "test")
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=workspace.id,
        kind="hf_bundle_export",
        title="Export",
        status="queued",
        created_by_user_id=user.id,
        input_ref={"artifact_id": value["artifact_id"]},
        result={},
    )
    db.add(job)
    db.commit()
    result = offline.run_bundle_job(db, job.id)
    assert result["download_available"] is True
    with (offline.job_directory(job.id) / "export.tar").open("rb") as stream:
        assert offline.inspect_bundle(stream, workspace.id) == value
    grant = db.get(HubArtifactGrant, (workspace.id, value["artifact_id"]))
    grant.revoked_at = datetime.utcnow()
    db.commit()
    job.status = "queued"
    db.commit()
    with pytest.raises(HFError) as error:
        offline.run_bundle_job(db, job.id)
    assert error.value.code == "HF_ACCESS_REVOKED"


def test_dataset_bundle_retains_result_without_source_download(environment):
    import polars as pl

    db, workspace, _, _ = environment
    content = io.BytesIO()
    pl.DataFrame({"value": [1, 2]}).write_parquet(content)
    payload = content.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    source = {"size_bytes": len(payload), "upstream_hash": {"algorithm": "sha256", "value": digest}}
    metadata = {
        "hub_endpoint": "https://huggingface.co",
        "kind": "dataset",
        "repo_id": "acme/data",
        "revision": "a" * 40,
        "requested_ref": "main",
        "license": "mit",
        "license_text": "license terms",
        "files": [{"path": "train.parquet", **source}],
    }
    files, plan = registry.select_files(metadata, {"format": "parquet", "files": ["train.parquet"]})
    artifact = HubArtifact(
        id=str(uuid4()),
        hub_endpoint=metadata["hub_endpoint"],
        kind="dataset",
        repo_id=metadata["repo_id"],
        revision=metadata["revision"],
        requested_ref="main",
        format="parquet",
        selection_digest=registry.digest({"plan": plan, "files": files}),
        selection_json=plan,
        files_json=files,
        metadata_json=metadata,
    )
    value = {
        **base_manifest(artifact),
        "files": {},
        "source_files": {"train.parquet": {**source, "sha256": digest}},
        "total_bytes": len(payload),
        "dataset_result": {
            "size_bytes": len(payload),
            "sha256": digest,
            "row_count": 2,
            "column_count": 1,
            "owner_workspace_id": "source-installation",
            "object_key": "untrusted/source/key",
        },
    }
    job = upload_job(environment, value, payload)
    offline.run_bundle_job(db, job.id)
    published = registry.require_artifact(db, workspace.id, artifact.id)
    result = published.manifest_json["dataset_result"]
    assert result["owner_workspace_id"] == workspace.id
    assert (
        result["object_key"]
        == f"workspaces/{workspace.id}/tabular/hub-artifacts/{artifact.id}/result.parquet"
    )
    assert result["sha256"] == digest
    assert published.manifest_json["source_files"] == value["source_files"]
