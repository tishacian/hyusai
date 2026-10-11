"""Admission, publication fencing and workspace isolation against SQLite."""

import copy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.base import SessionLocal
from app.models.huggingface import (
    HFPlatformConfig,
    HubArtifact,
    HubArtifactGrant,
    HubImportReservation,
)
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import registry
from app.services.huggingface.errors import HFError
from app.services.huggingface.fetch import base_manifest
from app.services.huggingface.storage import blob_key

SHA = "a" * 40


@pytest.fixture
def hub(db_session, monkeypatch):
    monkeypatch.setattr(registry, "_schedule_cleanup", lambda *_: None)
    monkeypatch.setattr(registry, "_schedule_drain", lambda *_: None)
    monkeypatch.setattr(registry.settings, "hf_disk_min_free_bytes", 0)
    monkeypatch.setattr(registry.settings, "hf_cache_dir", "/tmp")
    db_session.query(HFPlatformConfig).delete()
    first = Workspace(id=str(uuid4()), name="Hub A", slug="hub-a-" + str(uuid4())[:8], settings={})
    second = Workspace(id=str(uuid4()), name="Hub B", slug="hub-b-" + str(uuid4())[:8], settings={})
    db_session.add_all([first, second])
    db_session.add(
        User(
            id="admin",
            username="hf-worker-admin",
            email="hf-worker-admin@example.test",
            role="admin",
            is_active=True,
        )
    )
    db_session.commit()
    return db_session, first, second


def metadata():
    return {
        "hub_endpoint": "https://huggingface.co",
        "kind": "model",
        "repo_id": "acme/gguf",
        "revision": SHA,
        "requested_ref": "main",
        "license": "mit",
        "license_text": "MIT terms",
        "files": [
            {
                "path": "Q4.gguf",
                "size_bytes": 8,
                "upstream_hash": {"algorithm": "sha256", "value": "b" * 64},
            },
            {
                "path": "Q8.gguf",
                "size_bytes": 16,
                "upstream_hash": {"algorithm": "sha256", "value": "c" * 64},
            },
            {
                "path": "config.json",
                "size_bytes": 4,
                "upstream_hash": {"algorithm": "git-blob-sha1", "value": "d" * 40},
            },
        ],
    }


def request(db, ws, variant="Q4.gguf", **kwargs):
    return registry.request_import(
        db,
        workspace_id=ws.id,
        actor_id="admin",
        metadata=metadata(),
        selection={"format": "gguf", "variant": variant},
        dispatch=False,
        **kwargs,
    )


def manifest(artifact):
    files = {
        path: {
            **entry,
            "sha256": entry["upstream_hash"]["value"]
            if entry["upstream_hash"]["algorithm"] == "sha256"
            else "e" * 64,
            "object_key": blob_key(artifact, path),
        }
        for path, entry in artifact.files_json.items()
    }
    return {
        **base_manifest(artifact),
        "files": files,
        "total_bytes": sum(e["size_bytes"] for e in files.values()),
    }


def publish(db, artifact, job):
    artifact, job = registry.claim_import(db, job.id)
    return registry.complete_import(
        db, job.id, manifest(artifact), lease_owner=job.result["lease_owner"]
    )


def test_quantifications_are_distinct_and_selection_order_is_canonical(hub):
    db, first, second = hub
    artifact4, job4 = request(db, first)
    publish(db, artifact4, job4)
    artifact8, _ = request(db, first, "Q8.gguf")
    same4, _ = registry.request_import(
        db,
        workspace_id=second.id,
        actor_id="admin",
        metadata=metadata(),
        selection={"format": "gguf", "paths": ["config.json", "Q4.gguf"]},
        dispatch=False,
    )
    assert artifact4.id != artifact8.id
    assert same4.id == artifact4.id


def test_ready_reuse_checks_new_workspace_quota(hub):
    db, first, second = hub
    artifact, job = request(db, first)
    publish(db, artifact, job)
    registry.set_limits(db, {"workspace_max_bytes": 10}, actor="platform")
    with pytest.raises(HFError) as error:
        request(db, second)
    assert error.value.code == "HF_QUOTA_EXCEEDED"
    db.rollback()
    assert db.get(HubArtifactGrant, (second.id, artifact.id)) is None


def test_one_worker_owns_a_shared_selection_and_peer_failure_does_not_fail_it(hub):
    db, first, second = hub
    artifact, a = request(db, first)
    _, b = request(db, second)
    registry.claim_import(db, a.id)
    with pytest.raises(HFError) as error:
        registry.claim_import(db, b.id)
    assert error.value.code == "HF_JOB_BUSY"
    db.rollback()
    registry.fail_import(db, b.id, "HF_IMPORT_FAILED")
    db.refresh(artifact)
    assert artifact.status == "fetching"
    assert db.get(HubImportReservation, a.id) is not None


def test_stale_worker_cannot_borrow_new_lease_or_complete_changed_manifest(hub):
    db, first, _ = hub
    artifact, job = request(db, first)
    artifact, job = registry.claim_import(db, job.id)
    old_lease = job.result["lease_owner"]
    reservation = db.get(HubImportReservation, job.id)
    reservation.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    _, job = registry.claim_import(db, job.id)
    new_lease = job.result["lease_owner"]
    assert old_lease != new_lease
    for lease in (None, old_lease):
        with pytest.raises(HFError) as error:
            registry.touch_import(db, job.id, "fetching", 40, lease_owner=lease)
        assert error.value.code == "HF_JOB_LEASE_LOST"
        db.rollback()
    changed = manifest(artifact)
    changed["files"]["Q4.gguf"]["sha256"] = "f" * 64
    with pytest.raises(HFError) as error:
        registry.complete_import(db, job.id, changed, lease_owner=new_lease)
    assert error.value.code == "HF_MANIFEST_INVALID"
    db.rollback()
    assert db.get(HubArtifact, artifact.id).status == "fetching"
    registry.complete_import(db, job.id, manifest(artifact), lease_owner=new_lease)


@pytest.mark.parametrize(
    "mutation", ["extra_file", "missing_file", "object_key", "selection", "total", "revision"]
)
def test_publication_requires_complete_immutable_manifest(hub, mutation):
    db, first, _ = hub
    artifact, job = request(db, first)
    artifact, job = registry.claim_import(db, job.id)
    value = copy.deepcopy(manifest(artifact))
    if mutation == "extra_file":
        value["files"]["evil.py"] = value["files"]["config.json"]
    elif mutation == "missing_file":
        del value["files"]["config.json"]
    elif mutation == "object_key":
        value["files"]["config.json"]["object_key"] = "workspaces/other/private.json"
    elif mutation == "selection":
        value["selection"]["variant"] = "Q8.gguf"
    elif mutation == "total":
        value["total_bytes"] = 1
    else:
        value["revision"] = "f" * 40
    with pytest.raises(HFError) as error:
        registry.complete_import(db, job.id, value, lease_owner=job.result["lease_owner"])
    assert error.value.code == "HF_MANIFEST_INVALID"


def test_grant_revocation_is_scoped_and_fresh_in_long_lived_session(hub):
    db, first, second = hub
    artifact, job = request(db, first)
    publish(db, artifact, job)
    request(db, second)
    assert registry.require_artifact(db, first.id, artifact.id)
    with SessionLocal() as other:
        registry.revoke_grant(other, first.id, artifact.id, actor="admin", reason="Access removed")
    with pytest.raises(HFError) as error:
        registry.require_artifact(db, first.id, artifact.id)
    assert error.value.code == "HF_ACCESS_REVOKED"
    assert registry.require_artifact(db, second.id, artifact.id).status == "ready"


def test_cancel_releases_reservation_and_prevents_late_publication(hub):
    db, first, _ = hub
    artifact, job = request(db, first)
    artifact, job = registry.claim_import(db, job.id)
    owner = job.result["lease_owner"]
    registry.cancel_import(db, first.id, job.id, actor="admin")
    assert db.get(HubImportReservation, job.id) is None
    assert db.get(HubArtifact, artifact.id).status == "failed"
    with pytest.raises(HFError) as error:
        registry.complete_import(db, job.id, manifest(artifact), lease_owner=owner)
    assert error.value.code == "HF_JOB_LEASE_LOST"


def test_same_request_key_cannot_name_a_new_quantification(hub):
    db, first, _ = hub
    original, job = request(db, first, job_key="request-1")
    same, same_job = request(db, first, job_key="request-1")
    assert (same.id, same_job.id) == (original.id, job.id)
    with pytest.raises(HFError) as error:
        request(db, first, "Q8.gguf", job_key="request-1")
    assert error.value.code == "HF_IDEMPOTENCY_CONFLICT"


def test_concurrent_admissions_atomically_reserve_platform_capacity(hub):
    from concurrent.futures import ThreadPoolExecutor

    db, first, second = hub
    registry.set_limits(db, {"platform_imports": 1}, actor="platform-admin")
    ids = [first.id, second.id]

    def admit(workspace_id):
        with SessionLocal() as session:
            try:
                registry.request_import(
                    session,
                    workspace_id=workspace_id,
                    actor_id="admin",
                    metadata=metadata(),
                    selection={"format": "gguf", "variant": "Q4.gguf"},
                    dispatch=False,
                )
                return "admitted"
            except HFError as error:
                session.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, ids))
    assert sorted(results) == ["HF_QUOTA_EXCEEDED", "admitted"]
    assert db.query(HubImportReservation).count() == 1


def test_offline_reservations_count_before_their_grant_exists(hub):
    db, first, _ = hub
    registry.set_limits(db, {"workspace_max_bytes": 20, "workspace_imports": 2}, actor="platform")
    artifact, _ = request(db, first)
    db.query(HubArtifactGrant).filter_by(workspace_id=first.id, artifact_id=artifact.id).delete()
    db.commit()
    with pytest.raises(HFError) as error:
        request(db, first, "Q8.gguf")
    assert error.value.code == "HF_QUOTA_EXCEEDED"
    assert "workspace model quota" in error.value.message


def test_bundle_spool_and_online_import_share_disk_admission(hub, monkeypatch):
    db, first, _ = hub
    registry.set_limits(db, {"workspace_imports": 2}, actor="platform")
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=first.id,
        kind="hf_bundle_import",
        title="bundle",
        status="created",
        stage="license_required",
        input_ref={"upload_bytes": 8},
    )
    db.add(job)
    db.commit()
    monkeypatch.setattr(registry.shutil, "disk_usage", lambda *_: SimpleNamespace(free=32))
    with pytest.raises(HFError) as error:
        request(db, first)
    assert error.value.code == "HF_QUOTA_EXCEEDED"
    assert "disk headroom" in error.value.message


def test_worker_cannot_publish_after_actor_loses_permission(hub):
    db, first, _ = hub
    artifact, job = request(db, first)
    artifact, job = registry.claim_import(db, job.id)
    lease_owner = job.result["lease_owner"]
    with SessionLocal() as other:
        actor = other.get(User, "admin")
        actor.role = "user"
        other.commit()
    with pytest.raises(HFError) as error:
        registry.complete_import(db, job.id, manifest(artifact), lease_owner=lease_owner)
    assert error.value.code == "WORKSPACE_PERMISSION_DENIED"
    db.rollback()
    assert db.get(HubArtifact, artifact.id).status == "fetching"


@pytest.mark.parametrize("deleted", [False, True])
def test_existing_grant_cannot_execute_in_disabled_or_deleted_workspace(hub, deleted):
    db, first, _ = hub
    artifact, job = request(db, first)
    publish(db, artifact, job)
    registry.require_artifact(db, first.id, artifact.id)
    with SessionLocal() as other:
        workspace = other.get(Workspace, first.id)
        if deleted:
            workspace.deleted_at = datetime.utcnow()
        else:
            workspace.is_active = False
        other.commit()
    with pytest.raises(HFError) as error:
        registry.require_artifact(db, first.id, artifact.id)
    assert error.value.code == "HF_WORKSPACE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_artifact_node_calls_recheck_grants_and_keep_provenance(hub, monkeypatch):
    import json

    from app.services.model_clients.openai_client import OpenAIClient
    from app.services.model_plane import execution, registration, serving_nodes

    db, first, second = hub
    artifact, job = request(db, first)
    publish(db, artifact, job)
    monkeypatch.setattr(
        serving_nodes.settings,
        "llm_serving_nodes_json",
        json.dumps([{"name": "gpu", "base_url": "http://node.example:9000", "token": "node-token"}]),
    )
    registered = registration.sync_from_node_snapshots(
        [
            {
                "name": "gpu",
                "base_url": "http://node.example:9000",
                "status": "active",
                "instances": [
                    {
                        "id": "deployment-one",
                        "provider": "llamacpp",
                        "port": 8080,
                        "status": "running",
                        "model": "served-model",
                        "artifact_id": artifact.id,
                        "revision": artifact.revision,
                        "variant": artifact.variant,
                        "runtime_version": "llamacpp-1",
                        "workspace_id": first.id,
                        "deployment_id": "deployment-one",
                    }
                ],
            }
        ]
    )
    key = registered[0]["key"]
    calls = []

    async def generate(self, model, prompt, **kwargs):
        calls.append((self.base_url, model, self.api_key))
        return {"content": "answer", "model": model}

    monkeypatch.setattr(OpenAIClient, "generate", generate)
    try:
        resolved = execution.resolve_model_execution(first, provider=key, model="served-model")
        assert resolved.public()["artifact_id"] == artifact.id
        client = execution.build_model_client(resolved)
        output = await client.generate("served-model", "Hi")
        assert output["huggingface"]["revision"] == SHA
        with pytest.raises(execution.ModelExecutionError):
            execution.resolve_model_execution(second, provider=key, model="served-model")
        registry.revoke_grant(db, first.id, artifact.id, actor="admin", reason="stop")
        with pytest.raises(HFError) as error:
            await client.generate("served-model", "Again")
        assert error.value.code == "HF_ACCESS_REVOKED"
        assert calls == [
            (
                "http://node.example:9000/api/v1/artifacts/deployments/deployment-one/v1",
                "served-model",
                "node-token",
            )
        ]
    finally:
        registration.clear_routable_providers()
