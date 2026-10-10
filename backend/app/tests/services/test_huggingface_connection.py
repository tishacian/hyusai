"""Hub connections, immutable metadata and license gates: no live HTTP."""

import gzip
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.models.huggingface import HFLicenseAcceptance, HFLicenseException, HFPlatformConfig
from app.models.workspace import Workspace
from app.services.connectors.generic import service as generic
from app.services.huggingface import policy
from app.services.huggingface.client import HFClient
from app.services.huggingface.connection import (
    Connection,
    public_platform_config,
    set_platform_connection,
    validate_endpoint,
)
from app.services.huggingface.errors import HFError

SHA = "a" * 40
SECRET = "hf-test-private-do-not-echo"


@pytest.fixture
def hf_workspace(db_session, monkeypatch):
    monkeypatch.setenv(generic.ENV_MASTER_KEY, Fernet.generate_key().decode())
    for model in (HFLicenseAcceptance, HFLicenseException, HFPlatformConfig):
        db_session.query(model).delete()
    ws = Workspace(id=str(uuid4()), name="Hub test", slug="hub-" + str(uuid4())[:8], settings={})
    db_session.add(ws)
    db_session.commit()
    return db_session, ws


def metadata(license_tag="mit", **overrides):
    return {
        "hub_endpoint": "https://huggingface.co",
        "kind": "model",
        "repo_id": "acme/model",
        "revision": SHA,
        "license": license_tag,
        "files": [],
        **overrides,
    }


def test_workspace_connection_has_no_platform_privilege_fallback(hf_workspace):
    db, ws = hf_workspace
    set_platform_connection(db, {"token": SECRET}, actor="admin")
    assert Connection.resolve(db, ws).source == "platform"
    generic.set_config(db, ws, "huggingface", {"endpoint": "https://huggingface.co"}, actor="admin")
    resolved = Connection.resolve(db, ws)
    assert resolved.source == "workspace" and resolved.token is None
    assert SECRET not in repr(resolved)
    assert SECRET not in json.dumps(public_platform_config(db))


def test_hf_secret_requires_encryption_and_never_reads_plaintext(hf_workspace, monkeypatch):
    db, ws = hf_workspace
    monkeypatch.delenv(generic.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(generic.ENV_MASTER_KEY_FALLBACK, raising=False)
    with pytest.raises(HFError, match="Configure CONNECTOR"):
        generic.set_config(db, ws, "huggingface", {"token": SECRET}, actor="admin")
    assert "huggingface" not in (ws.settings.get("generic_connectors") or {})
    ws.settings = {
        "generic_connectors": {
            "huggingface": {"secrets": {"token": generic._encrypt_secret(SECRET)}}
        }
    }
    with pytest.raises(HFError) as error:
        Connection.resolve(db, ws)
    assert error.value.code == "HF_CREDENTIAL_UNREADABLE"
    assert SECRET not in str(error.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://huggingface.co",
        "https://localhost",
        "https://127.0.0.1",
        "https://huggingface.co@evil.example",
        "https://huggingface.co/x",
        "https://huggingface.co?x=y",
    ],
)
def test_untrusted_endpoints_are_refused(endpoint):
    with pytest.raises(HFError):
        validate_endpoint(endpoint)


def test_enterprise_endpoint_change_cannot_reuse_token(hf_workspace, monkeypatch):
    db, ws = hf_workspace
    monkeypatch.setenv("HF_ALLOWED_ENDPOINTS", "https://enterprise.example")
    generic.set_config(db, ws, "huggingface", {"token": SECRET}, actor="admin")
    with pytest.raises(HFError) as error:
        generic.set_config(
            db, ws, "huggingface", {"endpoint": "https://enterprise.example"}, actor="admin"
        )
    assert error.value.code == "HF_TOKEN_ENDPOINT_CHANGED"
    assert Connection.resolve(db, ws).endpoint == "https://huggingface.co"


def test_metadata_uses_resolved_sha_and_distinguishes_git_lfs_hashes():
    seen = []

    def handler(request):
        seen.append(request)
        if "/revision/" in request.url.path:
            return httpx.Response(
                200, json={"id": "acme/model", "sha": SHA, "cardData": {"license": "mit"}}
            )
        assert request.url.path.endswith("/tree/" + SHA)
        return httpx.Response(
            200,
            json=[
                {"path": "config.json", "type": "file", "size": 30, "oid": "b" * 40},
                {
                    "path": "model.safetensors",
                    "type": "file",
                    "size": 80,
                    "oid": "c" * 40,
                    "lfs": {"oid": "d" * 64, "size": 80},
                },
            ],
        )

    client = HFClient(Connection(token=SECRET), transport=httpx.MockTransport(handler))
    result = client.repo_info("model", "acme/model", "main")
    assert result["revision"] == SHA
    assert result["requested_ref"] == "main"
    assert [row["upstream_hash"]["algorithm"] for row in result["files"]] == [
        "git-blob-sha1",
        "sha256",
    ]
    assert all(request.headers["Authorization"] == "Bearer " + SECRET for request in seen)


def test_gzip_metadata_is_decoded_once():
    def handler(request):
        if "/revision/" in request.url.path:
            body = json.dumps({"id": "acme/model", "sha": SHA}).encode()
            return httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, content=gzip.compress(body)
            )
        return httpx.Response(200, json=[])

    client = HFClient(Connection(), transport=httpx.MockTransport(handler))
    assert client.repo_info("model", "acme/model", "main")["revision"] == SHA


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://evil.example/steal"}),
        httpx.Response(200, headers={"Link": '<https://evil.example/steal>; rel="next"'}, json=[]),
    ],
)
def test_redirects_and_pagination_cannot_exfiltrate_token(response):
    seen = []

    def handler(request):
        seen.append(request)
        return response

    hub = HFClient(Connection(token=SECRET), transport=httpx.MockTransport(handler))
    with pytest.raises(HFError) as error:
        hub.tree("model", "acme/model", SHA)
    assert error.value.code == "HF_REDIRECT_FORBIDDEN"
    assert len(seen) == 1


def test_private_and_gated_access_cannot_use_platform_credential():
    hub = HFClient(Connection(token=SECRET, source="platform"))
    with pytest.raises(HFError) as error:
        hub.check_access(metadata(gated=True))
    assert error.value.code == "HF_WORKSPACE_TOKEN_REQUIRED"


def test_gated_access_probes_payload_not_public_readme():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(403)

    hub = HFClient(
        Connection(token=SECRET, source="workspace"), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(HFError) as error:
        hub.check_access(
            metadata(gated=True, files=[{"path": "README.md"}, {"path": "model.safetensors"}])
        )
    assert error.value.code == "HF_ACCESS_DENIED"
    assert seen[0].method == "HEAD" and seen[0].url.path.endswith("model.safetensors")


def test_license_acceptance_is_bound_to_workspace_revision_text_and_policy(hf_workspace):
    db, ws = hf_workspace
    data = metadata("gemma")
    with pytest.raises(HFError) as missing:
        policy.require_acceptance(db, ws, data, "License terms")
    assert missing.value.code == "HF_LICENSE_ACCEPTANCE_REQUIRED"
    policy.accept_license(db, ws, data, "License terms", actor="admin")
    assert policy.require_acceptance(db, ws, data, "License terms")["accepted"]
    for changed_data, text in (
        (data, "Changed terms"),
        ({**data, "revision": "b" * 40}, "License terms"),
    ):
        with pytest.raises(HFError):
            policy.require_acceptance(db, ws, changed_data, text)
    policy.set_workspace_policy(db, ws, {"gemma": "blocked"}, actor="admin")
    with pytest.raises(HFError) as blocked:
        policy.require_acceptance(db, ws, data, "License terms")
    assert blocked.value.code == "HF_LICENSE_BLOCKED"


def test_policy_cannot_weaken_and_exception_is_scoped(hf_workspace):
    db, ws = hf_workspace
    with pytest.raises(HFError) as weakening:
        policy.set_workspace_policy(db, ws, {"cc-by-nc-4.0": "allowed"}, actor="admin")
    assert weakening.value.code == "HF_POLICY_WEAKENING"
    data = metadata("cc-by-nc-4.0")
    policy.grant_exception(
        db,
        ws,
        data,
        "Terms",
        actor="platform-admin",
        reason="Research evaluation",
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    policy.accept_license(db, ws, data, "Terms", actor="workspace-admin")
    assert policy.require_acceptance(db, ws, data, "Terms")["accepted"]
    stranger = SimpleNamespace(id="other-workspace", settings={})
    assert policy.assess(db, stranger, data, "Terms")["license_class"] == "blocked"
    policy.set_workspace_policy(db, ws, {"cc-by-nc-4.0": "blocked"}, actor="admin")
    assert policy.assess(db, ws, data, "Terms")["license_class"] == "blocked"


@pytest.mark.asyncio
async def test_inference_license_refusal_does_not_call_provider_or_fallback(
    hf_workspace, monkeypatch
):
    from app.services.huggingface.inference import HFInferenceClient
    from app.services.model_plane import execution

    db, ws = hf_workspace
    generic.set_config(db, ws, "huggingface", {"token": SECRET}, actor="admin")
    resolved = execution.resolve_model_execution(ws, provider="huggingface", model="acme/model")
    monkeypatch.setattr(HFClient, "repo_info", lambda *args: metadata("cc-by-nc-4.0"))
    monkeypatch.setattr(
        HFClient, "license_evidence", lambda *args: {"license_text": "Non-commercial only"}
    )

    async def unexpected(*args, **kwargs):
        pytest.fail("A blocked model must never start provider work")

    monkeypatch.setattr(HFInferenceClient, "generate", unexpected)
    ctx = {
        "_model_before_dispatch": lambda *args: pytest.fail(
            "No cost reservation before license gate"
        )
    }
    with pytest.raises(HFError) as error:
        await execution.complete_model(resolved, "test", ctx, stream=False)
    assert error.value.code == "HF_LICENSE_BLOCKED"
    assert ctx["_model_resolution_evidence"]["attempts"][0]["status"] == "blocked"
    assert not ctx["_model_resolution_evidence"]["attempts"][0]["dispatch_started"]


@pytest.mark.asyncio
async def test_inference_rechecks_policy_between_direct_calls(hf_workspace, monkeypatch):
    from app.services.huggingface.inference import HFInferenceClient
    from app.services.model_clients.openai_client import OpenAIClient

    db, ws = hf_workspace
    generic.set_config(db, ws, "huggingface", {"token": SECRET}, actor="admin")
    monkeypatch.setattr(HFClient, "repo_info", lambda *args: metadata("mit"))
    monkeypatch.setattr(HFClient, "license_evidence", lambda *args: {"license_text": "MIT terms"})
    calls = []

    async def generate(self, model, prompt, **kwargs):
        calls.append((self.base_url, self.api_key))
        return {"content": "answer", "model": model}

    monkeypatch.setattr(OpenAIClient, "generate", generate)
    client = HFInferenceClient(ws.id)
    result = await client.generate("acme/model", "Hello")
    assert result["huggingface"]["revision"] == SHA
    policy.set_workspace_policy(db, ws, {"mit": "blocked"}, actor="admin")
    with pytest.raises(HFError):
        await client.generate("acme/model", "Hello again")
    assert calls == [("https://router.huggingface.co/v1", SECRET)]


@pytest.mark.asyncio
async def test_inference_stops_before_hub_access_for_disabled_workspace(hf_workspace, monkeypatch):
    from app.services.huggingface.inference import HFInferenceClient

    db, ws = hf_workspace
    generic.set_config(db, ws, "huggingface", {"token": SECRET}, actor="admin")
    client = HFInferenceClient(ws.id)
    ws.is_active = False
    db.commit()
    monkeypatch.setattr(
        HFClient,
        "repo_info",
        lambda *_: pytest.fail("A disabled workspace must not contact the Hub"),
    )
    with pytest.raises(HFError) as error:
        await client.generate("acme/model", "Hello")
    assert error.value.code == "HF_WORKSPACE_UNAVAILABLE"
