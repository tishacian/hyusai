"""OpenBao (Vault-compatible) KV v2 backend.

AppRole login with ``settings.openbao_role_id``/``openbao_secret_id`` against
``settings.openbao_addr``; values live in the KV v2 mount
``settings.openbao_mount`` at ``<scope>/<owner_key>/<secret_id>`` (or
``<scope>/<owner_key>/nodes/<secret_id>`` for serving-node and Hub tokens) as
``{"value": ...}``, one KV version per registry version. ``put`` returns
``StoredVersion(backend_ref="<path>#<kv_version>")``.

Every transport error, 5xx (sealed, standby), missing configuration or failed
login raises ``SECRET_BACKEND_UNAVAILABLE``; the registry never falls back to
the db backend for an ``openbao`` secret. The client token is cached until
shortly before its lease ends and refreshed once on a 403.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.models.secret import Secret, SecretVersion
from app.services.secrets.backends.base import StoredVersion
from app.services.secrets.values import SecretRegistryError, SecretValue

logger = get_logger(__name__)

TOKEN_RENEW_MARGIN_SECONDS = 30

# Secrets the Hub downloader (hub-fetch AppRole) resolves live under
# ``<scope>/<owner_key>/nodes/<secret_id>``; its policy grants only that segment.
NODES_SEGMENT = "nodes"
HUB_TOKEN_NAME = "huggingface-token"
NODE_TOKEN_PREFIX = "nodes-"


def is_node_secret(secret: Secret) -> bool:
    """LLM portal serving-node tokens and Hub tokens (platform or workspace scope)."""
    if secret.scope not in ("platform", "workspace"):
        return False
    name = secret.name or ""
    return name == HUB_TOKEN_NAME or name.startswith(NODE_TOKEN_PREFIX)


def _unavailable(message: str) -> SecretRegistryError:
    return SecretRegistryError("SECRET_BACKEND_UNAVAILABLE", message)


class OpenBaoSecretBackend:
    name = "openbao"

    def __init__(
        self,
        *,
        addr: str | None = None,
        mount: str | None = None,
        role_id: str | None = None,
        secret_id: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._addr = (addr if addr is not None else settings.openbao_addr).rstrip("/")
        self._mount = (mount if mount is not None else settings.openbao_mount).strip("/")
        self._role_id = role_id if role_id is not None else settings.openbao_role_id
        self._secret_id = secret_id if secret_id is not None else settings.openbao_secret_id
        self._timeout = timeout if timeout is not None else settings.openbao_timeout_seconds
        self._transport = transport
        self._client: httpx.Client | None = None
        self._token: str | None = None
        self._token_expires = 0.0
        self._lock = threading.Lock()

    # -- plumbing -----------------------------------------------------------

    def _http(self) -> httpx.Client:
        if not (self._addr and self._mount and self._role_id and self._secret_id):
            raise _unavailable("openbao backend is not configured")
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._addr, timeout=self._timeout, transport=self._transport
            )
        return self._client

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http().request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("secret_registry.openbao_unreachable", error=type(exc).__name__)
            raise _unavailable("openbao is unreachable") from exc
        if response.status_code >= 500:
            logger.warning("secret_registry.openbao_error", status=response.status_code)
            raise _unavailable(f"openbao answered {response.status_code}")
        return response

    def _login(self) -> str:
        response = self._send(
            "POST",
            "/v1/auth/approle/login",
            json={"role_id": self._role_id, "secret_id": self._secret_id},
        )
        if response.status_code != 200:
            raise _unavailable(f"openbao approle login failed ({response.status_code})")
        auth = (response.json() or {}).get("auth") or {}
        token = auth.get("client_token")
        if not token:
            raise _unavailable("openbao approle login returned no token")
        lease = int(auth.get("lease_duration") or 0)
        self._token = token
        self._token_expires = (
            time.monotonic() + max(lease - TOKEN_RENEW_MARGIN_SECONDS, 0) if lease else float("inf")
        )
        return token

    def _token_value(self, *, refresh: bool = False) -> str:
        with self._lock:
            if refresh or not self._token or time.monotonic() >= self._token_expires:
                return self._login()
            return self._token

    def _authed(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = self._send(
            method, url, headers={"X-Vault-Token": self._token_value()}, **kwargs
        )
        if response.status_code == 403:
            response = self._send(
                method, url, headers={"X-Vault-Token": self._token_value(refresh=True)}, **kwargs
            )
        if response.status_code == 403:
            raise _unavailable("openbao denied access to the secret path")
        return response

    def _path(self, secret: Secret) -> str:
        segment = f"{NODES_SEGMENT}/" if is_node_secret(secret) else ""
        return f"{secret.scope}/{secret.owner_key}/{segment}{secret.id}"

    def _parse_ref(self, secret: Secret, version: SecretVersion) -> tuple[str, int]:
        self._http()  # unconfigured fails closed before any ref validation
        ref = version.backend_ref or ""
        path, sep, kv_version = ref.rpartition("#")
        if not sep or not path or not kv_version.isdigit():
            raise SecretRegistryError("SECRET_VERSION_DESTROYED", f"version {version.version}")
        if path != self._path(secret):
            raise SecretRegistryError("SECRET_SCOPE_VIOLATION", "backend_ref does not match the secret")
        return path, int(kv_version)

    # -- SecretBackend --------------------------------------------------------

    def put(self, secret: Secret, version: int, value: SecretValue) -> StoredVersion:
        path = self._path(secret)
        response = self._authed(
            "POST", f"/v1/{self._mount}/data/{path}", json={"data": {"value": value.reveal()}}
        )
        if response.status_code not in (200, 204):
            raise _unavailable(f"openbao write failed ({response.status_code})")
        kv_version = ((response.json() or {}).get("data") or {}).get("version")
        if not isinstance(kv_version, int):
            raise _unavailable("openbao write returned no version")
        return StoredVersion(backend_ref=f"{path}#{kv_version}")

    def get(self, secret: Secret, version: SecretVersion) -> SecretValue:
        path, kv_version = self._parse_ref(secret, version)
        response = self._authed(
            "GET", f"/v1/{self._mount}/data/{path}", params={"version": kv_version}
        )
        if response.status_code == 404:
            raise SecretRegistryError("SECRET_VERSION_DESTROYED", f"version {version.version}")
        if response.status_code != 200:
            raise _unavailable(f"openbao read failed ({response.status_code})")
        data = (response.json() or {}).get("data") or {}
        metadata = data.get("metadata") or {}
        payload = data.get("data")
        if metadata.get("destroyed") or metadata.get("deletion_time") or not isinstance(
            payload, dict
        ):
            raise SecretRegistryError("SECRET_VERSION_DESTROYED", f"version {version.version}")
        clear = payload.get("value")
        if not isinstance(clear, str):
            raise SecretRegistryError("SECRET_VERSION_DESTROYED", f"version {version.version}")
        return SecretValue(clear)

    def destroy(self, secret: Secret, version: SecretVersion) -> None:
        if not version.backend_ref:
            return
        path, kv_version = self._parse_ref(secret, version)
        response = self._authed(
            "POST", f"/v1/{self._mount}/destroy/{path}", json={"versions": [kv_version]}
        )
        if response.status_code not in (200, 204, 404):
            raise _unavailable(f"openbao destroy failed ({response.status_code})")

    def health(self) -> dict:
        result: dict[str, Any] = {"ok": False, "backend": self.name}
        try:
            response = self._send("GET", "/v1/sys/health", params={"standbyok": "true", "sealedcode": 200, "uninitcode": 200}
            )
            body = response.json() if response.content else {}
            result["initialized"] = bool(body.get("initialized"))
            result["sealed"] = bool(body.get("sealed"))
            if not result["initialized"] or result["sealed"]:
                result["error"] = "SECRET_BACKEND_UNAVAILABLE"
                return result
            self._token_value()
            result["ok"] = True
        except SecretRegistryError as exc:
            result["error"] = exc.code
            result["detail"] = exc.message
        except Exception as exc:  # noqa: BLE001
            result["error"] = "SECRET_BACKEND_UNAVAILABLE"
            result["detail"] = type(exc).__name__
        return result
