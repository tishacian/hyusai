"""Lifecycle endpoints enforce scope before control-plane and storage actions."""

import io
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import Request

from app.api.v1.endpoints import huggingface_lifecycle as api
from app.models.huggingface import HubArtifactGrant, HubArtifactUsage
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import bundles, offline, policy
from app.services.huggingface.errors import HFError
from app.tests.services import test_huggingface_offline_jobs as offline_tests

environment = offline_tests.environment
manifest = offline_tests.manifest
upload_job = offline_tests.upload_job


@pytest.fixture
def prepared(environment):
    db, workspace, user, _ = environment
    value, payload = manifest()
    job = upload_job(environment, value, payload)
    offline.run_bundle_job(db, job.id)
    return db, workspace, user, value


def body(**kwargs):
    return api.DeploymentBody(
        node_name="node-a",
        architecture="llama",
        context_length=2048,
        required_memory_bytes=1024,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_node_deployment_is_durable_and_idempotent(prepared, monkeypatch):
    db, workspace, user, value = prepared
    requests = []

    async def remote(node, manifest, **kwargs):
        requests.append(kwargs["deployment_id"])
        kwargs["authorize"](manifest["artifact_id"])
        return {
            "deployment_id": kwargs["deployment_id"],
            "artifact_id": manifest["artifact_id"],
            "state": "preparing",
        }

    monkeypatch.setattr(api.nodes, "deploy_artifact", remote)
    first = await api.deploy(value["artifact_id"], body(), db=db, user=user, workspace=workspace)
    second = await api.deploy(value["artifact_id"], body(), db=db, user=user, workspace=workspace)
    assert first == second
    assert requests[0] == requests[1]
    assert db.query(HubArtifactUsage).filter_by(kind="llm").count() == 1
    changed = body(deployment_id=requests[0]).model_copy(update={"context_length": 4096})
    with pytest.raises(HFError) as error:
        await api.deploy(value["artifact_id"], changed, db=db, user=user, workspace=workspace)
    assert error.value.code == "HF_IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_control_cannot_cross_workspaces(prepared):
    db, workspace, user, value = prepared
    another = Workspace(id=str(uuid4()), name="Other", slug=str(uuid4()))
    db.add(another)
    db.add(
        HubArtifactUsage(
            workspace_id=workspace.id,
            artifact_id=value["artifact_id"],
            kind="llm",
            target_id="deployment",
            status="ready",
            details_json={"node_name": "node"},
        )
    )
    db.commit()
    with pytest.raises(HFError) as error:
        await api.deployment_status("deployment", db=db, user=user, workspace=another)
    assert error.value.code == "HF_NOT_FOUND"


@pytest.mark.asyncio
async def test_stop_remains_available_after_workspace_revocation(prepared, monkeypatch):
    db, workspace, user, value = prepared
    db.add(
        HubArtifactUsage(
            workspace_id=workspace.id,
            artifact_id=value["artifact_id"],
            kind="llm",
            target_id="deployment",
            status="unavailable",
            details_json={"node_name": "node"},
        )
    )
    db.get(HubArtifactGrant, (workspace.id, value["artifact_id"])).revoked_at = datetime.utcnow()
    db.commit()

    async def stop(node, deployment_id, **kwargs):
        kwargs["authorize_control"](kwargs["artifact_id"], deployment_id)
        return {
            "deployment_id": deployment_id,
            "artifact_id": kwargs["artifact_id"],
            "state": "stopped",
        }

    monkeypatch.setattr(api.nodes, "stop_deployment", stop)
    assert (await api.stop_deployment("deployment", db=db, user=user, workspace=workspace))[
        "state"
    ] == "stopped"
    with pytest.raises(HFError) as error:
        await api.refresh_deployment("deployment", db=db, user=user, workspace=workspace)
    assert error.value.code == "HF_ACCESS_REVOKED"


def request(data, *, declared=None):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": data, "more_body": False}

    headers = [(b"content-length", str(len(data) if declared is None else declared).encode())]
    return Request({"type": "http", "headers": headers}, receive)


@pytest.mark.asyncio
async def test_offline_license_can_be_reviewed_and_accepted_without_hub(environment, monkeypatch):
    db, workspace, user, key = environment
    value, payload = manifest(tag="gemma")
    stream = io.BytesIO()
    bundles.export_bundle(
        stream,
        manifest=value,
        open_file=lambda _: io.BytesIO(payload),
        target_workspace_id=workspace.id,
        license_digest=policy.license_digest(value, value["license_text"]),
        signing_key=key,
        key_id="test",
        authorize=lambda *_: None,
    )
    queued = []

    def dispatch(db, job, task_name, **kwargs):
        queued.append(task_name)
        db.commit()
        return {"job_id": job.id, "status": job.status}

    monkeypatch.setattr(api, "_dispatch", dispatch)
    result = await api.import_bundle(
        request(stream.getvalue()), db=db, user=user, workspace=workspace
    )
    assert result["stage"] == "license_required" and not queued
    detail = api.bundle_job_status(result["job_id"], db=db, user=user, workspace=workspace)
    assert detail["license"]["text"] == value["license_text"]
    api.accept_bundle_license(result["job_id"], db=db, user=user, workspace=workspace)
    assert queued == ["agentium.hf_bundle_import"]
    assert offline.run_bundle_job(db, result["job_id"])["artifact_id"] == value["artifact_id"]


@pytest.mark.asyncio
async def test_streaming_upload_cannot_exceed_reserved_length(environment):
    db, workspace, user, _ = environment
    with pytest.raises(HFError) as error:
        await api.import_bundle(
            request(b"too many bytes", declared=2), db=db, user=user, workspace=workspace
        )
    assert error.value.code == "HF_TOO_LARGE"
    job = db.query(WorkspaceJob).filter_by(kind="hf_bundle_import").one()
    assert job.status == "failed"
    assert not offline.job_directory(job.id).exists()


@pytest.mark.asyncio
async def test_non_admin_cannot_deploy_or_purge(prepared):
    db, workspace, _, value = prepared
    ordinary = User(id=str(uuid4()), username=str(uuid4()), role="user", is_active=True)
    db.add(ordinary)
    db.commit()
    with pytest.raises(HFError) as error:
        await api.deploy(value["artifact_id"], body(), db=db, user=ordinary, workspace=workspace)
    assert error.value.status_code == 403
    with pytest.raises(HFError) as error:
        api.purge(value["artifact_id"], db=db, user=ordinary, workspace=workspace)
    assert error.value.status_code == 403
