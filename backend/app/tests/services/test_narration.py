"""Real narration ledger/ObjectStore transitions with an HTTP transport double."""

import asyncio
import base64
import copy
import hashlib
import json
import threading
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.run import Run
from app.models.service_contract import AssetVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services import governed_assets as assets
from app.services.dataops import narration
from app.services.object_store import get_object_store


@pytest.fixture()
def setup(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    monkeypatch.setattr(settings, "narration_endpoint", "https://narration.example/v1")
    monkeypatch.setattr(settings, "narration_allowed_hosts", "narration.example")
    monkeypatch.setattr(
        narration.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    workspace = Workspace(id=str(uuid4()), name="Narration", slug="narration-" + uuid4().hex)
    user = User(id=str(uuid4()), username="narration-" + uuid4().hex, is_active=True)
    db_session.add_all([workspace, user])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    run = Run(
        id=str(uuid4()), workspace_id=workspace.id, initiated_by_user_id=user.id, status="running"
    )
    db_session.add(run)
    db_session.commit()
    ctx = {"workspace_id": workspace.id, "user_id": user.id, "run_id": run.id}
    return SimpleNamespace(db=db_session, workspace=workspace, user=user, run=run, ctx=ctx)


def make_payload(s, pages=1, images=0, metadata=None, **budget):
    content = b"actual uploaded source bytes"
    key = f"workspaces/{s.workspace.id}/original/{uuid4().hex}.pdf"
    get_object_store().write_bytes(key, content)
    sha = hashlib.sha256(content).hexdigest()
    units = [
        {"id": f"page-{i}", "kind": "page", "object_key": key, "sha256": sha, "page_number": i + 1}
        for i in range(pages)
    ] + [
        {"id": f"image-{i}", "kind": "image", "object_key": key, "sha256": sha}
        for i in range(images)
    ]
    source = assets.register_asset(
        s.db,
        s.workspace.id,
        "document_set",
        "original",
        {
            "objects": [{"key": key, "sha256": sha, "size_bytes": len(content)}],
            "units": units,
            **(metadata or {}),
        },
    )
    ref = assets.asset_ref(source)
    s.run.input_ref = {"asset_ref": ref}
    s.db.commit()
    return {
        "asset_ref": ref,
        "_narration": {
            "node_id": "narrate",
            "narration": {
                "source_ref": ref,
                "engine_revision": "engine-sha-123",
                "options": {"language": "fr"},
                "budgets": {"poll_interval_s": 0.05, **budget},
            },
        },
    }


def rendered(identifier, content=None):
    content = content or f"Narration of {identifier}".encode()
    return {
        "id": identifier,
        "status": "completed",
        "content_base64": base64.b64encode(content).decode(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mime_type": "text/plain",
    }


def gateway(monkeypatch, payload, responses):
    calls = []
    kwargs_seen = []
    original_client = httpx.Client

    def transport(request):
        calls.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        entry = responses.pop(0)
        if callable(entry):
            entry = entry(request)
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, httpx.Response):
            return entry
        body = {
            "protocol_version": 1,
            "job_id": "gateway_job",
            "engine_revision": "engine-sha-123",
            "source_digest": payload["asset_ref"]["digest"],
            **entry,
        }
        return httpx.Response(200, json=body)

    def client(**kwargs):
        kwargs_seen.append(kwargs)
        return original_client(transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(narration.httpx, "Client", client)
    return calls, kwargs_seen


def job(s):
    s.db.expire_all()
    return (
        s.db.query(WorkspaceJob).filter_by(workspace_id=s.workspace.id, kind=narration.KIND).one()
    )


async def test_actual_http_state_machine_creates_immutable_asset_and_unknown_cost(
    setup, monkeypatch
):
    s = setup
    payload = make_payload(s, pages=1, images=1)
    calls, options = gateway(
        monkeypatch,
        payload,
        [
            {"status": "queued"},
            {"status": "running", "units": [rendered("page-0")], "next_cursor": "one"},
            {"status": "completed", "units": [rendered("image-0")]},
        ],
    )
    result = await narration.run_narration(payload, s.ctx)
    assert result["technical_status"] == "completed"
    assert result["coverage"] == {
        "expected": 2,
        "processed": 2,
        "failed": 0,
        "missing": 0,
        "pages": {"expected": 1, "processed": 1, "failed": 0, "missing": 0},
        "images": {"expected": 1, "processed": 1, "failed": 0, "missing": 0},
    }
    assert result["cost"]["amount"] is None and result["tokens"] is None
    assert result["cost"]["reserved_amount"] == 10
    assert result["confidence"] is None and result["disposition"] == "review"
    derived = assets.resolve_asset_ref(s.db, s.workspace.id, result["asset_ref"])
    assert derived.kind == "document_set" and derived.parents_json == [payload["asset_ref"]]
    assert (
        get_object_store()
        .read_bytes(derived.manifest_json["objects"][0]["key"])
        .startswith(b"Narration of")
    )
    assert job(s).status == "completed" and job(s).progress == 100
    assert [request.method for request in calls] == ["POST", "GET", "GET"]
    assert calls[0].headers["idempotency-key"] == job(s).id
    assert calls[0].url.host == "93.184.216.34" and calls[0].headers["host"] == "narration.example"
    assert calls[0].extensions["sni_hostname"] == "narration.example"
    assert all(
        value == {"verify": True, "follow_redirects": False, "trust_env": False}
        for value in options
    )
    assert await narration.run_narration(payload, s.ctx) == result
    assert len(calls) == 3


async def test_500_page_manifest_uses_bounded_chunks_and_no_duplicate_processing(
    setup, monkeypatch
):
    s = setup
    payload = make_payload(s, pages=500)
    responses = [{"status": "queued"}]
    for start in range(0, 500, 100):
        responses.append(
            {
                "status": "completed" if start == 400 else "running",
                "units": [rendered(f"page-{i}") for i in range(start, start + 100)],
                "next_cursor": None if start == 400 else str(start + 100),
                "cost_usd": 0,
                "tokens": 0,
            }
        )
    calls, _ = gateway(monkeypatch, payload, responses)
    result = await narration.run_narration(payload, s.ctx)
    assert result["coverage"]["pages"]["processed"] == 500
    assert len(job(s).result["units"]) == 500
    assert job(s).result["output_bytes"] == sum(
        len(f"Narration of page-{i}".encode()) for i in range(500)
    )
    assert result["cost"]["amount"] == 0 and result["cost"]["measurement_coverage"] == "complete"
    assert len(calls) == 6 and len(json.loads(calls[0].content)["units"]) == 500


async def test_output_preserves_recorded_context_and_image_evidence_bytes(setup, monkeypatch):
    s = setup
    context = {
        "document_family": "manual-1",
        "source": "approved-manuals",
        "language": "fr",
        "task": "typed_questions",
    }
    payload = make_payload(s, pages=0, images=1, metadata=context)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
    )
    unit = {**rendered("image-0", png), "mime_type": "image/png"}
    gateway(monkeypatch, payload, [{"status": "completed", "units": [unit]}])
    result = await narration.run_narration(payload, s.ctx)
    manifest = assets.resolve_asset_ref(s.db, s.workspace.id, result["asset_ref"]).manifest_json
    assert {field: manifest[field] for field in context} == context
    evidence = manifest["evidence"][0]
    assert evidence["kind"] == "image" and evidence["mime_type"] == "image/png"
    assert evidence["sha256"] == hashlib.sha256(png).hexdigest()
    assert get_object_store().read_bytes(evidence["locator"]["object_key"]) == png


async def test_connection_failure_resumes_same_remote_cursor_and_checkpoint(setup, monkeypatch):
    s = setup
    payload = make_payload(s, pages=2)
    responses = [
        {"status": "queued"},
        {"status": "running", "units": [rendered("page-0")], "next_cursor": "checkpoint"},
        httpx.ReadError("secret provider trace"),
        {"status": "completed", "units": [rendered("page-0"), rendered("page-1")]},
    ]
    calls, _ = gateway(monkeypatch, payload, responses)
    with pytest.raises(narration.NarrationError, match="^NARRATION_NETWORK_UNAVAILABLE$"):
        await narration.run_narration(payload, s.ctx)
    saved = job(s)
    assert saved.status == "running" and len(saved.result["units"]) == 1
    assert "secret" not in saved.error
    first_bytes = saved.result["output_bytes"]
    result = await narration.run_narration(payload, s.ctx)
    assert result["coverage"]["processed"] == 2
    assert job(s).result["output_bytes"] == first_bytes + len(b"Narration of page-1")
    assert [request.method for request in calls].count("POST") == 1
    assert str(calls[-1].url).endswith("?cursor=checkpoint")


async def test_post_timeout_retries_identical_durable_idempotency_key(setup, monkeypatch):
    s = setup
    payload = make_payload(s)
    calls, _ = gateway(
        monkeypatch,
        payload,
        [
            httpx.ReadTimeout("unknown acceptance"),
            {"status": "completed", "units": [rendered("page-0")]},
        ],
    )
    with pytest.raises(narration.NarrationError, match="NARRATION_NETWORK_UNAVAILABLE"):
        await narration.run_narration(payload, s.ctx)
    assert job(s).status == "queued" and job(s).started_at is None
    await narration.run_narration(payload, s.ctx)
    assert calls[0].headers["idempotency-key"] == calls[1].headers["idempotency-key"]
    assert job(s).result["requests"] == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ({"engine_revision": "unexpected"}, "NARRATION_RESPONSE_IDENTITY_CHANGED"),
        ({"source_digest": "0" * 64}, "NARRATION_RESPONSE_IDENTITY_CHANGED"),
        ({"units": []}, "NARRATION_COVERAGE_INCOMPLETE"),
        ({"units": [rendered("foreign-unit")]}, "NARRATION_UNKNOWN_UNIT"),
        (
            {"units": [{**rendered("page-0"), "sha256": "0" * 64}]},
            "NARRATION_CONTENT_DIGEST_MISMATCH",
        ),
        ({"cost_usd": 11}, "NARRATION_BUDGET_EXHAUSTED"),
        ({"tokens": 100001}, "NARRATION_BUDGET_EXHAUSTED"),
        (
            {"units": [{**rendered("page-0"), "url": "http://169.254.169.254/"}]},
            "NARRATION_RESPONSE_INVALID",
        ),
    ],
)
async def test_invalid_or_uncovered_provider_result_never_publishes_asset(
    setup, monkeypatch, change, code
):
    s = setup
    payload = make_payload(s)
    gateway(
        monkeypatch, payload, [{"status": "completed", "units": [rendered("page-0")], **change}]
    )
    with pytest.raises(narration.NarrationError, match=code):
        await narration.run_narration(payload, s.ctx)
    assert job(s).status == "failed"
    assert s.db.query(AssetVersion).filter_by(workspace_id=s.workspace.id).count() == 1


async def test_missing_page_is_not_counted_as_failed_or_processed(setup, monkeypatch):
    s = setup
    payload = make_payload(s, pages=2, images=1)
    gateway(
        monkeypatch,
        payload,
        [
            {
                "status": "completed",
                "units": [rendered("page-0"), {"id": "image-0", "status": "failed"}],
            }
        ],
    )
    with pytest.raises(narration.NarrationError, match="NARRATION_COVERAGE_INCOMPLETE"):
        await narration.run_narration(payload, s.ctx)
    assert job(s).result["coverage"] == {
        "expected": 3,
        "processed": 1,
        "failed": 1,
        "missing": 1,
        "pages": {"expected": 2, "processed": 1, "failed": 0, "missing": 1},
        "images": {"expected": 1, "processed": 0, "failed": 1, "missing": 0},
    }


async def test_poll_budget_is_durable_and_cannot_loop_forever(setup, monkeypatch):
    s = setup
    payload = make_payload(s, max_requests=2)
    calls, _ = gateway(monkeypatch, payload, [{"status": "queued"}, {"status": "running"}])
    with pytest.raises(narration.NarrationError, match="NARRATION_REQUEST_BUDGET_EXHAUSTED"):
        await narration.run_narration(payload, s.ctx)
    assert len(calls) == job(s).result["requests"] == 2
    assert job(s).status == "failed"


async def test_output_byte_budget_blocks_storage_of_excess_chunk(setup, monkeypatch):
    s = setup
    payload = make_payload(s, max_output_bytes=4)
    gateway(monkeypatch, payload, [{"status": "completed", "units": [rendered("page-0")]}])
    with pytest.raises(narration.NarrationError, match="NARRATION_OUTPUT_BUDGET_EXHAUSTED"):
        await narration.run_narration(payload, s.ctx)
    assert job(s).result["output_bytes"] == 0


async def test_cancelled_run_sends_one_bounded_delete_and_persists_cancelled(setup, monkeypatch):
    s = setup
    payload = make_payload(s)

    def cancel(request):
        with SessionLocal() as db:
            db.get(Run, s.ctx["run_id"]).status = "cancelled"
            db.commit()
        return {"status": "running"}

    calls, _ = gateway(monkeypatch, payload, [{"status": "queued"}, cancel])
    with pytest.raises(narration.NarrationError, match="NARRATION_CANCELLED"):
        await narration.run_narration(payload, s.ctx)
    assert job(s).status == "cancelled" and calls[-1].method == "DELETE"
    assert len([request for request in calls if request.method == "DELETE"]) == 1


async def test_source_revision_change_cannot_reuse_existing_checkpoint(setup, monkeypatch):
    s = setup
    first = make_payload(s)
    calls, _ = gateway(monkeypatch, first, [{"status": "completed", "units": [rendered("page-0")]}])
    await narration.run_narration(first, s.ctx)
    changed = make_payload(s, pages=2)
    with pytest.raises(narration.NarrationError, match="NARRATION_REQUEST_CHANGED"):
        await narration.run_narration(changed, s.ctx)
    assert len(calls) == 1


async def test_async_cancellation_waits_for_bounded_remote_cancel(setup, monkeypatch):
    s = setup
    payload = make_payload(s)
    reached = threading.Event()
    release = threading.Event()

    def accepted(request):
        reached.set()
        assert release.wait(2)
        return {"status": "queued"}

    calls, _ = gateway(monkeypatch, payload, [accepted])
    task = asyncio.create_task(narration.run_narration(payload, s.ctx))
    assert await asyncio.to_thread(reached.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert job(s).status == "cancelled"
    assert [request.method for request in calls] == ["POST", "DELETE"]


async def test_persisted_deadline_prevents_timeout_budget_reset(setup, monkeypatch):
    s = setup
    payload = make_payload(s)
    calls, _ = gateway(monkeypatch, payload, [httpx.ReadTimeout("unknown acceptance")])
    with pytest.raises(narration.NarrationError, match="NARRATION_NETWORK_UNAVAILABLE"):
        await narration.run_narration(payload, s.ctx)
    row = job(s)
    row.result = {
        **row.result,
        "deadline_at": (narration._now() - timedelta(seconds=1)).isoformat(),
    }
    s.db.commit()
    with pytest.raises(narration.NarrationError, match="NARRATION_TIMEOUT"):
        await narration.run_narration(payload, s.ctx)
    assert len(calls) == 1 and job(s).status == "failed"


async def test_duplicate_active_worker_cannot_dispatch_second_job(setup, monkeypatch):
    s = setup
    payload = make_payload(s)
    reached = threading.Event()
    release = threading.Event()

    def complete(request):
        reached.set()
        assert release.wait(2)
        return {"status": "completed", "units": [rendered("page-0")]}

    calls, _ = gateway(monkeypatch, payload, [complete])
    first = asyncio.create_task(narration.run_narration(payload, s.ctx))
    assert await asyncio.to_thread(reached.wait, 2)
    try:
        with pytest.raises(narration.NarrationError, match="NARRATION_BUSY"):
            await narration.run_narration(payload, s.ctx)
    finally:
        release.set()
    assert (await first)["technical_status"] == "completed"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "endpoint,hosts,code",
    [
        ("", "narration.example", "NARRATION_ENDPOINT_UNCONFIGURED"),
        ("http://narration.example", "narration.example", "NARRATION_DESTINATION_DENIED"),
        ("https://narration.example", "other.example", "NARRATION_DESTINATION_DENIED"),
        (
            "https://user:secret@narration.example",
            "narration.example",
            "NARRATION_DESTINATION_DENIED",
        ),
    ],
)
async def test_unconfigured_or_unapproved_gateway_refuses_without_job(
    setup, monkeypatch, endpoint, hosts, code
):
    s = setup
    payload = make_payload(s)
    monkeypatch.setattr(settings, "narration_endpoint", endpoint)
    monkeypatch.setattr(settings, "narration_allowed_hosts", hosts)
    with pytest.raises(narration.NarrationError, match=code):
        await narration.run_narration(payload, s.ctx)
    assert s.db.query(WorkspaceJob).filter_by(workspace_id=s.workspace.id).count() == 0


async def test_dns_rebinding_and_redirect_cannot_reach_metadata(setup, monkeypatch):
    s = setup
    payload = make_payload(s)
    calls, _ = gateway(
        monkeypatch, payload, [httpx.Response(302, headers={"location": "http://169.254.169.254/"})]
    )
    with pytest.raises(narration.NarrationError, match="NARRATION_REDIRECT_DENIED"):
        await narration.run_narration(payload, s.ctx)
    assert len(calls) == 1
    monkeypatch.setattr(
        narration.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 443))]
    )
    with pytest.raises(narration.NarrationError, match="NARRATION_DESTINATION_DENIED"):
        await narration.run_narration(payload, s.ctx)
    assert len(calls) == 1


async def test_tenant_source_and_unit_limit_are_enforced_before_dispatch(setup, monkeypatch):
    s = setup
    payload = make_payload(s, pages=501)
    calls, _ = gateway(monkeypatch, payload, [])
    with pytest.raises(narration.NarrationError, match="NARRATION_UNIT_BUDGET_EXHAUSTED"):
        await narration.run_narration(payload, s.ctx)
    payload = make_payload(s)
    payload["asset_ref"]["workspace_id"] = str(uuid4())
    payload["_narration"]["narration"]["source_ref"] = copy.deepcopy(payload["asset_ref"])
    with pytest.raises(assets.GovernanceError, match="ASSET_SCOPE_DENIED"):
        await narration.run_narration(payload, s.ctx)
    assert calls == []
