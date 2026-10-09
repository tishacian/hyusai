"""Hub API role boundaries, write-only config and job/artifact workspace scope."""

import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import huggingface
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.audit import AuditLog
from app.models.huggingface import HubArtifact, HubArtifactGrant
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import registry
from app.services.huggingface.client import HFClient
from app.services.huggingface.connection import set_platform_connection
from app.services.huggingface.fetch import base_manifest
from app.services.huggingface.storage import blob_key

SECRET = "hf-secret-must-never-leave-server"


@pytest.fixture
def api(db_session, monkeypatch):
    monkeypatch.setenv("CONNECTOR_SECRETS_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(registry.settings, "hf_disk_min_free_bytes", 0)
    monkeypatch.setattr(registry.settings, "hf_cache_dir", "/tmp")
    monkeypatch.setattr(registry, "dispatch_import", lambda *_: None)
    monkeypatch.setattr(registry, "_schedule_cleanup", lambda *_: None)
    monkeypatch.setattr(registry, "_schedule_drain", lambda *_: None)
    workspace = Workspace(id=str(uuid4()), name="HF", slug="hf-" + uuid4().hex[:8], settings={})
    other = Workspace(id=str(uuid4()), name="Other", slug="hf-" + uuid4().hex[:8], settings={})
    db_session.add_all([workspace, other])
    users = {}
    for role in ("owner", "contributor", "viewer", "platform"):
        user = User(
            id=str(uuid4()),
            username="hf-" + uuid4().hex[:8],
            email=uuid4().hex + "@example.test",
            role="admin" if role == "platform" else "user",
            is_active=True,
        )
        users[role] = user
        db_session.add(user)
        if role != "platform":
            db_session.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role="owner" if role == "owner" else "member",
                    role_template="workspace_" + role,
                )
            )
    db_session.commit()
    state = {
        "workspace": workspace,
        "user": users["owner"],
        "license": "mit",
        "gated": False,
        "requests": [],
    }

    def repo(_client, kind, repo_id, revision="main"):
        state["requests"].append((kind, repo_id, revision))
        return {
            "hub_endpoint": "https://huggingface.co",
            "kind": kind,
            "repo_id": repo_id,
            "revision": "a" * 40,
            "requested_ref": revision,
            "license": state["license"],
            "gated": state["gated"],
            "private": False,
            "files": [
                {
                    "path": "train.parquet" if kind == "dataset" else "model.safetensors",
                    "size_bytes": 8,
                    "upstream_hash": {"algorithm": "sha256", "value": "b" * 64},
                }
            ],
        }

    monkeypatch.setattr(HFClient, "repo_info", repo)
    monkeypatch.setattr(
        HFClient, "license_evidence", lambda *_: {"license_text": "Full license terms"}
    )
    monkeypatch.setattr(HFClient, "test", lambda *_: {"status": "connected"})
    app = FastAPI()
    app.include_router(huggingface.router, prefix="/huggingface")
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_current_workspace] = lambda: state["workspace"]
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app), state, users, workspace, other, db_session


def _import(client, kind="model", **extra):
    return client.post(
        "/huggingface/imports", json={"kind": kind, "repo_id": "acme/repository", **extra}
    )


def test_connection_is_write_only_in_api_and_audit(api):
    client, state, users, _, _, db = api
    saved = client.put("/huggingface/config", json={"values": {"token": SECRET}})
    assert saved.status_code == 200
    assert saved.json()["connection"]["token_set"]
    assert client.get("/huggingface/config").json()["can_configure"]
    state["user"] = users["viewer"]
    read = client.get("/huggingface/config")
    assert read.status_code == 200
    assert not read.json()["can_configure"]
    assert SECRET not in saved.text + read.text
    assert SECRET not in json.dumps([row.details for row in db.query(AuditLog).all()])


@pytest.mark.parametrize("role", ["viewer", "contributor"])
def test_workspace_admin_operations_cannot_be_used_by_members(api, role):
    client, state, users, *_ = api
    state["user"] = users[role]
    responses = [
        client.put("/huggingface/config", json={"values": {"token": SECRET}}),
        client.delete("/huggingface/config"),
        client.post("/huggingface/test"),
        client.put("/huggingface/policy", json={"overrides": {"mit": "blocked"}}),
        client.post("/huggingface/licenses/accept", json={"repo_id": "acme/repository"}),
        _import(client),
    ]
    assert [response.status_code for response in responses] == [403] * 6
    assert state["requests"] == []


def test_dataset_import_is_reserved_for_contributors_and_admins(api):
    client, state, users, *_ = api
    state["user"] = users["viewer"]
    assert _import(client, "dataset").status_code == 403
    state["user"] = users["contributor"]
    response = _import(client, "dataset", max_rows=10)
    assert response.status_code == 202, response.text
    assert response.json()["artifact"]["kind"] == "dataset"


def test_workspace_owner_has_no_platform_privileges(api):
    client, state, users, *_ = api
    responses = [
        client.get("/huggingface/platform/config"),
        client.put("/huggingface/platform/config", json={"values": {"token": SECRET}}),
        client.put("/huggingface/platform/limits", json={"model_max_bytes": 80 * 1024**3}),
        client.post(
            "/huggingface/licenses/exception",
            json={"repo_id": "acme/repository", "reason": "Research"},
        ),
        client.post("/huggingface/artifacts/unknown/revoke", json={"reason": "stop"}),
    ]
    assert [r.status_code for r in responses] == [403] * 5
    state["user"] = users["platform"]
    assert (
        client.put("/huggingface/platform/config", json={"values": {"token": SECRET}}).status_code
        == 200
    )
    response = client.get("/huggingface/platform/config")
    assert response.status_code == 200 and SECRET not in response.text


def test_import_uses_server_license_and_refusal_is_audited(api):
    client, state, _, _, _, db = api
    state["license"] = "cc-by-nc-4.0"
    response = _import(client, license="mit", metadata={"license": "mit"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "HF_LICENSE_BLOCKED"
    assert db.query(HubArtifact).count() == 0
    assert db.query(WorkspaceJob).filter_by(kind="hf_import").count() == 0
    assert (
        db.query(AuditLog).filter_by(event_type="hf.request.refused").one().details["code"]
        == "HF_LICENSE_BLOCKED"
    )


def test_acceptance_and_policy_hardening_apply_before_new_import(api):
    client, state, *_ = api
    state["license"] = "gemma"
    assert _import(client).json()["detail"]["code"] == "HF_LICENSE_ACCEPTANCE_REQUIRED"
    assert (
        client.post("/huggingface/licenses/accept", json={"repo_id": "acme/repository"}).status_code
        == 200
    )
    assert _import(client).status_code == 202
    assert (
        client.put("/huggingface/policy", json={"overrides": {"gemma": "blocked"}}).status_code
        == 200
    )
    assert _import(client).json()["detail"]["code"] == "HF_LICENSE_BLOCKED"


def test_platform_token_cannot_grant_gated_workspace_access(api):
    client, state, users, _, _, db = api
    set_platform_connection(db, {"token": SECRET}, actor=users["platform"].id)
    state["gated"] = True
    response = _import(client)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "HF_WORKSPACE_TOKEN_REQUIRED"
    assert db.query(HubArtifactGrant).count() == 0


def test_artifacts_jobs_and_cancellation_are_workspace_scoped(api):
    client, state, _, workspace, other, db = api
    created = _import(client).json()
    artifact_id, job_id = created["artifact"]["id"], created["job"]["id"]
    job = db.get(WorkspaceJob, job_id)
    job.result = {
        **job.result,
        "lease_owner": "private-worker-lease",
        "object_key": "private/storage/key",
    }
    db.commit()
    assert "private" not in client.get(f"/huggingface/jobs/{job_id}").text
    state["workspace"] = other
    assert client.get("/huggingface/artifacts").json() == {"artifacts": []}
    for path in (f"/huggingface/artifacts/{artifact_id}", f"/huggingface/jobs/{job_id}"):
        assert client.get(path).status_code == 404
    assert client.post(f"/huggingface/jobs/{job_id}/cancel").status_code == 404
    state["workspace"] = workspace
    assert client.post(f"/huggingface/jobs/{job_id}/cancel").json()["status"] == "cancelled"


def test_workspace_revocation_does_not_revoke_shared_artifact(api):
    client, state, users, workspace, other, db = api
    created = _import(client).json()
    artifact, job = registry.claim_import(db, created["job"]["id"])
    files = {
        path: {
            **entry,
            "sha256": entry["upstream_hash"]["value"],
            "object_key": blob_key(artifact, path),
        }
        for path, entry in artifact.files_json.items()
    }
    manifest = {**base_manifest(artifact), "files": files, "total_bytes": artifact.total_bytes}
    registry.complete_import(db, job.id, manifest, lease_owner=job.result["lease_owner"])
    db.add(
        WorkspaceMember(
            workspace_id=other.id,
            user_id=users["owner"].id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    db.commit()
    state["workspace"] = other
    assert _import(client).status_code == 202
    state["workspace"] = workspace
    assert (
        client.post(
            f"/huggingface/artifacts/{artifact.id}/revoke-grant", json={"reason": "done"}
        ).status_code
        == 200
    )
    db.refresh(artifact)
    assert artifact.status == "ready"
    assert registry.require_artifact(db, other.id, artifact.id)


def test_anonymous_requests_do_not_reach_hub_routes():
    app = FastAPI()
    app.include_router(huggingface.router, prefix="/huggingface")
    response = TestClient(app).get("/huggingface/config")
    assert response.status_code in {401, 403}


def test_bad_config_and_boolean_quotas_are_validation_errors(api):
    client, state, users, *_ = api
    response = client.put("/huggingface/config", json={"values": {"unknown": SECRET}})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "HF_CONFIG_INVALID"
    assert SECRET not in response.text
    state["user"] = users["platform"]
    response = client.put("/huggingface/platform/limits", json={"platform_imports": True})
    assert response.status_code == 422


def test_jobs_list_is_workspace_scoped_ordered_and_exposes_only_public_results(api):
    client, state, users, workspace, other, db = api
    now = datetime.utcnow()
    rows = []
    for index, (kind, scope) in enumerate(
        [
            ("hf_import", workspace.id),
            ("hf_bundle_export", workspace.id),
            ("hf_adapter_activate", workspace.id),
            ("hf_import", other.id),
            ("unrelated", workspace.id),
        ]
    ):
        row = WorkspaceJob(
            id=str(uuid4()),
            workspace_id=scope,
            kind=kind,
            title="Job",
            status="completed",
            created_by_user_id=users["owner"].id,
            created_at=now + timedelta(seconds=index),
            input_ref={"artifact_id": "artifact"},
            result={
                "download_available": True,
                "object_key": "secret/path",
                "lease_owner": "secret-lease",
                "probe": {"validation": "loaded_and_inferred", "local_path": "/secret/cache"},
            },
        )
        rows.append(row)
    db.add_all(rows)
    db.commit()
    state["user"] = users["viewer"]
    response = client.get("/huggingface/jobs?limit=2")
    assert response.status_code == 200
    assert [job["id"] for job in response.json()["jobs"]] == [rows[2].id, rows[1].id]
    assert [job["kind"] for job in response.json()["jobs"]] == [
        "hf_adapter_activate",
        "hf_bundle_export",
    ]
    assert "secret" not in response.text
    assert response.json()["jobs"][0]["result"]["probe"] == {"validation": "loaded_and_inferred"}
    assert client.get("/huggingface/jobs?limit=201").status_code == 422


@pytest.mark.parametrize(
    "change", ["user_disabled", "membership_removed", "workspace_disabled", "workspace_deleted"]
)
def test_queued_import_rechecks_actor_and_workspace_before_fetch(api, monkeypatch, change):
    from app.services.huggingface import fetch
    from app.services.huggingface.errors import HFError

    client, _, users, workspace, _, db = api
    created = _import(client).json()
    if change == "user_disabled":
        users["owner"].is_active = False
    elif change == "membership_removed":
        db.query(WorkspaceMember).filter_by(
            workspace_id=workspace.id, user_id=users["owner"].id
        ).delete()
    elif change == "workspace_disabled":
        workspace.is_active = False
    else:
        workspace.deleted_at = datetime.utcnow()
    db.commit()
    monkeypatch.setattr(
        fetch, "execute_import", lambda *_: pytest.fail("A revoked actor must not fetch data")
    )
    with pytest.raises(HFError) as error:
        registry.run_import(db, created["job"]["id"])
    assert error.value.code == "WORKSPACE_PERMISSION_DENIED"
    assert db.get(WorkspaceJob, created["job"]["id"]).status == "failed"
