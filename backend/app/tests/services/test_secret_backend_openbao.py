"""OpenBao KV v2 + AppRole backend against an in-memory httpx mock server."""

from __future__ import annotations

import json

import httpx
import pytest

from app.models.secret import Secret, SecretVersion
from app.services.secrets.backends.base import SecretBackend
from app.services.secrets.backends.openbao import OpenBaoSecretBackend
from app.services.secrets.values import SecretRegistryError, SecretValue

ROLE_ID = "role-test"
SECRET_ID = "secret-id-test"
PLAIN = "sk-test-openbao-0001"


class FakeBao:
    """Just enough of OpenBao: AppRole login, KV v2 data/destroy, sys/health."""

    def __init__(self) -> None:
        self.versions: dict[str, list[dict]] = {}
        self.tokens: set[str] = set()
        self.logins = 0
        self.sealed = False
        self.down = False
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        path = request.url.path
        if path == "/v1/sys/health":
            return httpx.Response(200, json={"initialized": True, "sealed": self.sealed})
        if self.sealed:
            return httpx.Response(503, json={"errors": ["Vault is sealed"]})
        if path == "/v1/auth/approle/login":
            creds = json.loads(request.content)
            if creds != {"role_id": ROLE_ID, "secret_id": SECRET_ID}:
                return httpx.Response(400, json={"errors": ["invalid role or secret ID"]})
            self.logins += 1
            token = f"tok-{self.logins}"
            self.tokens.add(token)
            return httpx.Response(
                200, json={"auth": {"client_token": token, "lease_duration": 3600}}
            )
        if request.headers.get("X-Vault-Token") not in self.tokens:
            return httpx.Response(403, json={"errors": ["permission denied"]})
        if path.startswith("/v1/agentium/data/"):
            key = path.removeprefix("/v1/agentium/data/")
            if request.method == "POST":
                value = json.loads(request.content)["data"]
                self.versions.setdefault(key, []).append({"data": value, "destroyed": False})
                return httpx.Response(200, json={"data": {"version": len(self.versions[key])}})
            wanted = int(request.url.params["version"])
            rows = self.versions.get(key, [])
            if not 1 <= wanted <= len(rows):
                return httpx.Response(404, json={"errors": []})
            row = rows[wanted - 1]
            if row["destroyed"]:
                return httpx.Response(
                    404,
                    json={"data": {"data": None, "metadata": {"destroyed": True, "version": wanted}}},
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "data": row["data"],
                        "metadata": {"destroyed": False, "deletion_time": "", "version": wanted},
                    }
                },
            )
        if path.startswith("/v1/agentium/destroy/") and request.method == "POST":
            key = path.removeprefix("/v1/agentium/destroy/")
            for wanted in json.loads(request.content)["versions"]:
                self.versions[key][wanted - 1]["destroyed"] = True
            return httpx.Response(204)
        return httpx.Response(404, json={"errors": []})


@pytest.fixture()
def bao() -> FakeBao:
    return FakeBao()


def _backend(bao: FakeBao, **overrides) -> OpenBaoSecretBackend:
    options = {
        "addr": "http://agentium-openbao:8200",
        "mount": "agentium",
        "role_id": ROLE_ID,
        "secret_id": SECRET_ID,
        "timeout": 1.0,
        "transport": httpx.MockTransport(bao),
    }
    options.update(overrides)
    return OpenBaoSecretBackend(**options)


def _secret() -> Secret:
    return Secret(id="sec-1", scope="workspace", owner_key="ws-1", name="n", backend="openbao")


def _version(ref: str | None, number: int = 1) -> SecretVersion:
    return SecretVersion(secret_id="sec-1", version=number, backend_ref=ref)


def test_put_get_destroy_round_trip(bao):
    backend = _backend(bao)
    assert isinstance(backend, SecretBackend)
    stored = backend.put(_secret(), 1, SecretValue(PLAIN))
    assert stored.ciphertext is None
    assert stored.backend_ref == "workspace/ws-1/sec-1#1"
    second = backend.put(_secret(), 2, SecretValue("other"))
    assert second.backend_ref == "workspace/ws-1/sec-1#2"

    assert backend.get(_secret(), _version(stored.backend_ref)).reveal() == PLAIN
    assert bao.logins == 1  # token cached across calls

    backend.destroy(_secret(), _version(stored.backend_ref))
    with pytest.raises(SecretRegistryError) as err:
        backend.get(_secret(), _version(stored.backend_ref))
    assert err.value.code == "SECRET_VERSION_DESTROYED"
    assert backend.get(_secret(), _version(second.backend_ref, 2)).reveal() == "other"


def test_token_is_refreshed_once_on_403(bao):
    backend = _backend(bao)
    stored = backend.put(_secret(), 1, SecretValue(PLAIN))
    bao.tokens.clear()  # token revoked server-side
    assert backend.get(_secret(), _version(stored.backend_ref)).reveal() == PLAIN
    assert bao.logins == 2


def test_policy_denial_fails_closed(bao):
    backend = _backend(bao)
    backend.put(_secret(), 1, SecretValue(PLAIN))
    original = bao.__call__

    def deny(request):
        if "/data/" in request.url.path:
            return httpx.Response(403, json={"errors": ["permission denied"]})
        return original(request)

    denied = _backend(bao, transport=httpx.MockTransport(deny))
    with pytest.raises(SecretRegistryError) as err:
        denied.get(_secret(), _version("workspace/ws-1/sec-1#1"))
    assert err.value.code == "SECRET_BACKEND_UNAVAILABLE"


@pytest.mark.parametrize("state", ["down", "sealed", "bad_login", "unconfigured"])
def test_unavailable_states_fail_closed(bao, state):
    overrides = {}
    if state == "down":
        bao.down = True
    elif state == "sealed":
        bao.sealed = True
    elif state == "bad_login":
        overrides["secret_id"] = "wrong"
    else:
        overrides["addr"] = ""
    backend = _backend(bao, **overrides)
    for call in (
        lambda: backend.put(_secret(), 1, SecretValue(PLAIN)),
        lambda: backend.get(_secret(), _version("workspace/ws-1/sec-1#1")),
        lambda: backend.destroy(_secret(), _version("workspace/ws-1/sec-1#1")),
    ):
        with pytest.raises(SecretRegistryError) as err:
            call()
        assert err.value.code == "SECRET_BACKEND_UNAVAILABLE"
        assert PLAIN not in str(err.value)
    health = backend.health()
    assert health["ok"] is False
    assert health["error"] == "SECRET_BACKEND_UNAVAILABLE"


def test_health_ok_when_unsealed_and_login_works(bao):
    assert _backend(bao).health() == {
        "ok": True,
        "backend": "openbao",
        "initialized": True,
        "sealed": False,
    }


def test_backend_ref_must_belong_to_the_secret(bao):
    backend = _backend(bao)
    with pytest.raises(SecretRegistryError) as err:
        backend.get(_secret(), _version("workspace/ws-2/sec-9#1"))
    assert err.value.code == "SECRET_SCOPE_VIOLATION"
    with pytest.raises(SecretRegistryError) as err:
        backend.get(_secret(), _version(None))
    assert err.value.code == "SECRET_VERSION_DESTROYED"
    assert not any("/data/" in r.url.path for r in bao.requests)


@pytest.mark.parametrize(
    ("scope", "owner", "name", "expected"),
    [
        ("workspace", "ws-1", "nodes-gpu-a-token", "workspace/ws-1/nodes/sec-1"),
        ("workspace", "ws-1", "huggingface-token", "workspace/ws-1/nodes/sec-1"),
        ("platform", "platform", "huggingface-token", "platform/platform/nodes/sec-1"),
        ("workspace", "ws-1", "mcp-crm-token", "workspace/ws-1/sec-1"),
        ("system", "sys-1", "nodes-gpu-a-token", "system/sys-1/sec-1"),
    ],
)
def test_hub_fetch_secrets_live_under_the_nodes_segment(bao, scope, owner, name, expected):
    backend = _backend(bao)
    secret = Secret(id="sec-1", scope=scope, owner_key=owner, name=name, backend="openbao")
    stored = backend.put(secret, 1, SecretValue(PLAIN))
    assert stored.backend_ref == f"{expected}#1"
    assert backend.get(secret, _version(stored.backend_ref)).reveal() == PLAIN


def test_secret_value_never_sent_outside_the_kv_write(bao):
    backend = _backend(bao)
    backend.put(_secret(), 1, SecretValue(PLAIN))
    carrying = [r for r in bao.requests if PLAIN.encode() in r.content]
    assert [r.url.path for r in carrying] == ["/v1/agentium/data/workspace/ws-1/sec-1"]
    assert all(PLAIN not in str(r.url) for r in bao.requests)
