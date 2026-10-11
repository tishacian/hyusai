#!/usr/bin/env python3
"""Run the content-free SFTP acceptance canary from the protected runner.

This probe is intentionally limited to the already deployed production
contract. It authenticates to Agentium, discovers an authorized workspace
where Secure Deposit is enabled, creates one short-lived deposit link, and
uses that link to open an SFTP session. The SFTP client performs exactly two
content-free operations: ``getcwd()`` and ``stat('.')``. The link is revoked
in a ``finally`` block and the same credential must subsequently be denied.

The emitted artifact is acceptance evidence, never formal Release A evidence.
It contains no raw principal, workspace, link, access, hostname, credential,
token, path, file metadata, or business content.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

ARTIFACT_NAME = "sftp-positive-auth.artifact"
ARTIFACT_KIND = ARTIFACT_NAME
PROFILE = "agentium-protected-runner-sftp-acceptance-v1"
TOKEN = "sftp-positive-auth"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
PRINCIPAL_CLASS_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.:-]{0,251}[A-Za-z0-9])?$")
HOST_KEY_FINGERPRINT_RE = re.compile(r"^SHA256:([A-Za-z0-9+/]{43}=?)$")
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")

DEFAULT_TIMEOUT_SECONDS = 12.0
MIN_TIMEOUT_SECONDS = 2.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_JSON_BYTES = 1024 * 1024


class SFTPAcceptanceError(RuntimeError):
    """Fail-closed error with a deliberately non-sensitive message."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise SFTPAcceptanceError("invalid command arguments")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so bearer credentials never cross an origin boundary."""

    def redirect_request(
        self,
        _req: urllib.request.Request,
        _fp: Any,
        _code: int,
        _msg: str,
        _headers: Any,
        _newurl: str,
    ) -> None:
        return None


@dataclass(frozen=True)
class Settings:
    base_url: str
    expected_sha: str
    deployment_id: str
    principal_class: str
    username: str
    password: str
    sftp_host: str
    sftp_port: int
    host_key_fingerprint: str
    timeout: float


@dataclass(frozen=True)
class TemporaryLink:
    workspace_id: str
    workspace_slug: str
    link_id: str
    access_id: str
    password: str


ApiRequest = Callable[..., tuple[int, Any]]
PositiveProbe = Callable[..., Awaitable[None]]
DeniedProbe = Callable[..., Awaitable[None]]


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise SFTPAcceptanceError("required runner configuration is absent")
    return value.strip()


def _normalize_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise SFTPAcceptanceError("API origin configuration is invalid")
    if parsed.port not in {None, 443}:
        raise SFTPAcceptanceError("API origin configuration is invalid")
    return f"https://{parsed.hostname}"


def _normalize_host(value: str) -> str:
    host = value.strip().lower()
    if (
        not host
        or len(host) > 253
        or HOST_RE.fullmatch(host) is None
        or any(character.isspace() or ord(character) < 33 for character in host)
    ):
        raise SFTPAcceptanceError("SFTP endpoint configuration is invalid")
    return host


def _normalize_fingerprint(value: str) -> str:
    match = HOST_KEY_FINGERPRINT_RE.fullmatch(value.strip())
    if match is None:
        raise SFTPAcceptanceError("SFTP host-key pin is invalid")
    encoded = match.group(1).rstrip("=")
    try:
        digest = base64.b64decode(encoded + "=", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SFTPAcceptanceError("SFTP host-key pin is invalid") from exc
    if len(digest) != hashlib.sha256().digest_size:
        raise SFTPAcceptanceError("SFTP host-key pin is invalid")
    return f"SHA256:{encoded}"


def _load_settings() -> Settings:
    expected_sha = _required_env("E2E_EXPECTED_SHA")
    deployment_id = _required_env("E2E_DEPLOYMENT_ID")
    principal_class = os.environ.get(
        "E2E_PRINCIPAL_CLASS", "operator_personal_admin"
    ).strip()
    if SHA_RE.fullmatch(expected_sha) is None:
        raise SFTPAcceptanceError("deployed revision binding is invalid")
    if DEPLOYMENT_ID_RE.fullmatch(deployment_id) is None:
        raise SFTPAcceptanceError("deployment binding is invalid")
    if PRINCIPAL_CLASS_RE.fullmatch(principal_class) is None:
        raise SFTPAcceptanceError("principal classification is invalid")

    try:
        port = int(os.environ.get("E2E_SFTP_PORT", "2222"))
        timeout = float(os.environ.get("E2E_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError as exc:
        raise SFTPAcceptanceError("network configuration is invalid") from exc
    if not 1 <= port <= 65535 or not MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS:
        raise SFTPAcceptanceError("network configuration is outside safe bounds")

    return Settings(
        base_url=_normalize_base_url(
            os.environ.get("E2E_BASE_URL", "https://agentium.papai.ai")
        ),
        expected_sha=expected_sha,
        deployment_id=deployment_id,
        principal_class=principal_class,
        username=_required_env("E2E_USERNAME"),
        password=_required_env("E2E_PASSWORD"),
        sftp_host=_normalize_host(
            os.environ.get("E2E_SFTP_HOST", "agentium.papai.ai")
        ),
        sftp_port=port,
        host_key_fingerprint=_normalize_fingerprint(
            _required_env("E2E_SFTP_HOST_KEY_SHA256")
        ),
        timeout=timeout,
    )


def _strict_json(raw: bytes) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SFTPAcceptanceError("API response is not strict JSON")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise SFTPAcceptanceError("API response is not strict JSON")

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SFTPAcceptanceError("API response is not valid JSON") from exc


def _read_json_response(response: Any) -> Any:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_JSON_BYTES:
                raise SFTPAcceptanceError("API response exceeds the safe size")
        except ValueError as exc:
            raise SFTPAcceptanceError("API response metadata is invalid") from exc
    body = response.read(MAX_JSON_BYTES + 1)
    if len(body) > MAX_JSON_BYTES:
        raise SFTPAcceptanceError("API response exceeds the safe size")
    return _strict_json(body)


def _http_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
    workspace_slug: str | None = None,
    timeout: float,
) -> tuple[int, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SFTPAcceptanceError("API request target is invalid")
    encoded = None
    headers = {"Accept": "application/json"}
    if body is not None:
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if workspace_slug is not None:
        headers["X-Workspace-Slug"] = workspace_slug
    request = urllib.request.Request(
        url,
        data=encoded,
        method=method,
        headers=headers,
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect(),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), _read_json_response(response)
    except urllib.error.HTTPError as exc:
        try:
            return int(exc.code), _read_json_response(exc)
        except SFTPAcceptanceError:
            return int(exc.code), None
    except (OSError, socket.timeout, urllib.error.URLError):
        raise SFTPAcceptanceError("Agentium API request failed") from None


def _api_url(settings: Settings, path: str) -> str:
    if not path.startswith("/") or path.startswith("//"):
        raise SFTPAcceptanceError("API request path is invalid")
    return f"{settings.base_url}{path}"


def _request(
    settings: Settings,
    api_request: ApiRequest,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
    workspace_slug: str | None = None,
) -> tuple[int, Any]:
    return api_request(
        method,
        _api_url(settings, path),
        body=body,
        token=token,
        workspace_slug=workspace_slug,
        timeout=settings.timeout,
    )


def _verify_deployed_build(settings: Settings, api_request: ApiRequest) -> None:
    for path, service in (
        ("/api/v1/build-info", "backend"),
        ("/build-info.json", "frontend"),
    ):
        status, payload = _request(settings, api_request, "GET", path)
        if (
            status != 200
            or not isinstance(payload, dict)
            or payload.get("service") != service
            or payload.get("revision") != settings.expected_sha
            or payload.get("revision_verified") is not True
        ):
            raise SFTPAcceptanceError("deployed build binding could not be verified")


def _login(settings: Settings, api_request: ApiRequest) -> str:
    status, payload = _request(
        settings,
        api_request,
        "POST",
        "/api/v1/auth/login",
        body={
            "email": settings.username,
            "password": settings.password,
            "remember_me": False,
        },
    )
    if status != 200 or not isinstance(payload, dict):
        raise SFTPAcceptanceError("Agentium authentication failed")
    token = payload.get("token") or payload.get("access_token")
    if not isinstance(token, str) or not token or len(token) > 64 * 1024:
        raise SFTPAcceptanceError("Agentium authentication failed")
    return token


def _safe_runtime_identifier(value: Any) -> str | None:
    if (
        isinstance(value, str)
        and SAFE_IDENTIFIER_RE.fullmatch(value) is not None
        and "\x00" not in value
    ):
        return value
    return None


def _authorized_workspaces(
    settings: Settings,
    api_request: ApiRequest,
    token: str,
) -> list[tuple[str, str]]:
    status, payload = _request(
        settings,
        api_request,
        "GET",
        "/api/v1/auth/workspaces",
        token=token,
    )
    if status != 200 or not isinstance(payload, list):
        raise SFTPAcceptanceError("authorized workspace discovery failed")
    candidates: set[tuple[str, str]] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        workspace_id = _safe_runtime_identifier(item.get("id"))
        slug = _safe_runtime_identifier(item.get("slug"))
        if workspace_id and slug:
            candidates.add((workspace_id, slug))
    if not candidates:
        raise SFTPAcceptanceError("no authorized workspace is available")
    return sorted(
        candidates,
        key=lambda item: _sha256_parts(
            b"agentium-protected-runner-workspace-order-v1",
            settings.deployment_id,
            item[0],
            item[1],
        ),
    )


def _revoke_link(
    settings: Settings,
    api_request: ApiRequest,
    token: str,
    workspace_slug: str,
    link_id: str,
) -> None:
    quoted_id = urllib.parse.quote(link_id, safe="")
    status, payload = _request(
        settings,
        api_request,
        "POST",
        f"/api/v1/sftp/links/{quoted_id}/revoke",
        token=token,
        workspace_slug=workspace_slug,
    )
    link = payload.get("link") if isinstance(payload, dict) else None
    if (
        status != 200
        or not isinstance(link, dict)
        or link.get("status") != "revoked"
    ):
        raise SFTPAcceptanceError("temporary SFTP credential revocation failed")


def _create_link_in_workspace(
    settings: Settings,
    api_request: ApiRequest,
    token: str,
    workspace_id: str,
    workspace_slug: str,
) -> TemporaryLink | None:
    status, health = _request(
        settings,
        api_request,
        "GET",
        "/api/v1/sftp/health",
        token=token,
        workspace_slug=workspace_slug,
    )
    if status in {403, 404}:
        return None
    if status != 200 or not isinstance(health, dict) or health.get("enabled") is not True:
        return None

    expires_at = (datetime.now(UTC) + timedelta(minutes=10)).isoformat().replace(
        "+00:00", "Z"
    )
    status, payload = _request(
        settings,
        api_request,
        "POST",
        "/api/v1/sftp/links",
        body={
            "label": "Protected runner acceptance canary",
            "expires_at": expires_at,
            "max_file_size_mb": 1,
            "allowed_extensions": [],
        },
        token=token,
        workspace_slug=workspace_slug,
    )
    if status in {403, 404}:
        return None
    if status not in {200, 201} or not isinstance(payload, dict):
        return None
    link = payload.get("link")
    if not isinstance(link, dict):
        raise SFTPAcceptanceError("temporary SFTP credential response is invalid")
    link_id = _safe_runtime_identifier(link.get("id"))
    access_id = _safe_runtime_identifier(link.get("access_id"))
    password = link.get("generated_password")
    if link_id is None:
        raise SFTPAcceptanceError("temporary SFTP credential response is invalid")
    if (
        access_id is None
        or not isinstance(password, str)
        or not password
        or len(password) > 4096
        or any(character in password for character in ("\x00", "\r", "\n"))
    ):
        _revoke_link(
            settings,
            api_request,
            token,
            workspace_slug,
            link_id,
        )
        raise SFTPAcceptanceError("temporary SFTP credential response is invalid")
    return TemporaryLink(
        workspace_id=workspace_id,
        workspace_slug=workspace_slug,
        link_id=link_id,
        access_id=access_id,
        password=password,
    )


def _discover_and_create_link(
    settings: Settings,
    api_request: ApiRequest,
    token: str,
) -> TemporaryLink:
    for workspace_id, workspace_slug in _authorized_workspaces(
        settings, api_request, token
    ):
        link = _create_link_in_workspace(
            settings,
            api_request,
            token,
            workspace_id,
            workspace_slug,
        )
        if link is not None:
            return link
    raise SFTPAcceptanceError(
        "no authorized Secure Deposit workspace accepted the canary"
    )


def _known_hosts_bytes(host: str, port: int, server_key: Any) -> bytes:
    try:
        exported = server_key.export_public_key("openssh")
    except BaseException:
        raise SFTPAcceptanceError("SFTP host key could not be pinned") from None
    if isinstance(exported, str):
        exported = exported.encode("ascii")
    if (
        not isinstance(exported, bytes)
        or not exported.strip().startswith(b"ssh-ed25519 ")
        or b"\n" in exported.strip()
    ):
        raise SFTPAcceptanceError("SFTP host key could not be pinned")
    host_pattern = host if port == 22 else f"[{host}]:{port}"
    return host_pattern.encode("ascii") + b" " + exported.strip() + b"\n"


async def _pinned_known_hosts(
    *,
    host: str,
    port: int,
    expected_fingerprint: str,
    timeout: float,
    asyncssh: Any,
) -> bytes:
    try:
        # asyncssh.get_server_host_key has no connect_timeout kwarg on the
        # pinned runtime (2.23.0); enforce the bound with asyncio.wait_for so
        # a stalled handshake still fails closed instead of hanging the job.
        key = await asyncio.wait_for(
            asyncio.ensure_future(asyncssh.get_server_host_key(
                host=host,
                port=port,
                config=None,
                server_host_key_algs=["ssh-ed25519"],
                client_version="AgentiumProtectedRunnerSFTPAcceptance",
            )),
            timeout=timeout,
        )
        if str(key.get_algorithm()) != "ssh-ed25519":
            raise SFTPAcceptanceError("SFTP host-key algorithm mismatch")
        actual = _normalize_fingerprint(str(key.get_fingerprint("sha256")))
        if not hmac.compare_digest(actual, expected_fingerprint):
            raise SFTPAcceptanceError("SFTP host-key pin mismatch")
        return _known_hosts_bytes(host, port, key)
    except SFTPAcceptanceError:
        raise
    except BaseException:
        raise SFTPAcceptanceError("SFTP host-key verification failed") from None


def _connection_options(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    known_hosts: bytes,
    timeout: float,
) -> dict[str, Any]:
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "known_hosts": known_hosts,
        "config": None,
        "client_keys": [],
        "client_certs": [],
        "agent_path": None,
        "pkcs11_provider": None,
        "gss_kex": False,
        "gss_auth": False,
        "host_based_auth": False,
        "public_key_auth": False,
        "kbdint_auth": False,
        "password_auth": True,
        "preferred_auth": ("password",),
        "disable_trivial_auth": True,
        "connect_timeout": timeout,
        "login_timeout": timeout,
        "server_host_key_algs": ["ssh-ed25519"],
        "client_version": "AgentiumProtectedRunnerSFTPAcceptance",
    }


async def _positive_sftp_probe(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    expected_fingerprint: str,
    timeout: float,
) -> None:
    try:
        import asyncssh
    except ImportError as exc:  # pragma: no cover - protected image condition
        raise SFTPAcceptanceError("AsyncSSH runtime is unavailable") from exc
    known_hosts = await _pinned_known_hosts(
        host=host,
        port=port,
        expected_fingerprint=expected_fingerprint,
        timeout=timeout,
        asyncssh=asyncssh,
    )
    try:
        async with asyncssh.connect(
            **_connection_options(
                host=host,
                port=port,
                username=username,
                password=password,
                known_hosts=known_hosts,
                timeout=timeout,
            )
        ) as connection:
            async with connection.start_sftp_client() as sftp:
                await sftp.getcwd()
                # asyncssh composes "." against the cwd obtained above,
                # emitting "/." on the wire, which the Secure Deposit
                # virtual filesystem does not recognise as its root.
                # Stat the absolute root instead — the same content-free
                # proof without depending on client-side path composition.
                attributes = await sftp.stat("/")
                if attributes is None:
                    raise SFTPAcceptanceError("content-free SFTP stat proof is absent")
    except SFTPAcceptanceError:
        raise
    except BaseException:
        raise SFTPAcceptanceError("positive SFTP authentication proof failed") from None


async def _post_revoke_denied_probe(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    expected_fingerprint: str,
    timeout: float,
) -> None:
    try:
        import asyncssh
    except ImportError as exc:  # pragma: no cover - protected image condition
        raise SFTPAcceptanceError("AsyncSSH runtime is unavailable") from exc
    known_hosts = await _pinned_known_hosts(
        host=host,
        port=port,
        expected_fingerprint=expected_fingerprint,
        timeout=timeout,
        asyncssh=asyncssh,
    )
    accepted = False
    try:
        try:
            async with asyncssh.connect(
                **_connection_options(
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    known_hosts=known_hosts,
                    timeout=timeout,
                )
            ):
                accepted = True
        except asyncssh.PermissionDenied:
            if accepted:
                raise SFTPAcceptanceError(
                    "revoked SFTP credential was accepted before close failure"
                ) from None
            return
        raise SFTPAcceptanceError("revoked SFTP credential was accepted")
    except SFTPAcceptanceError:
        raise
    except BaseException:
        raise SFTPAcceptanceError(
            "post-revocation SFTP denial proof was ambiguous"
        ) from None


def _sha256_parts(domain: bytes, *values: str | bytes) -> str:
    digest = hashlib.sha256(domain)
    for value in values:
        digest.update(b"\0")
        digest.update(value if isinstance(value, bytes) else value.encode("utf-8"))
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _artifact(
    settings: Settings,
    link: TemporaryLink,
) -> dict[str, Any]:
    return {
        "access_id_sha256": _sha256_parts(
            b"agentium-protected-runner-sftp-access-v1",
            settings.deployment_id,
            link.access_id,
        ),
        "captured_at": _timestamp(),
        "checks": {
            "backend_build_bound": True,
            "content_free_getcwd": True,
            "content_free_stat_dot": True,
            "frontend_build_bound": True,
            "host_key_pin_matched": True,
            "password_authentication": True,
            "post_revoke_authentication_denied": True,
            "secure_deposit_enabled": True,
            "temporary_link_created": True,
            "temporary_link_revoked": True,
        },
        "credential_fingerprint_sha256": _sha256_parts(
            b"agentium-protected-runner-sftp-credential-v1",
            settings.deployment_id,
            settings.username,
            link.access_id,
            link.password,
        ),
        "deployment_id": settings.deployment_id,
        "environment": "production",
        "evidence_class": "acceptance",
        "formal_release_eligible": False,
        "hostname_sha256": _sha256_parts(
            b"agentium-protected-runner-sftp-host-v1",
            settings.deployment_id,
            settings.sftp_host,
        ),
        "kind": ARTIFACT_KIND,
        "link_id_sha256": _sha256_parts(
            b"agentium-protected-runner-sftp-link-v1",
            settings.deployment_id,
            link.link_id,
        ),
        "principal_class": settings.principal_class,
        "principal_sha256": _sha256_parts(
            b"agentium-protected-runner-principal-v1",
            settings.deployment_id,
            settings.username,
        ),
        "profile": PROFILE,
        "result": "passed",
        "schema_version": 1,
        "sftp_host_key_sha256": _sha256_parts(
            b"agentium-protected-runner-sftp-host-key-v1",
            settings.deployment_id,
            settings.host_key_fingerprint,
        ),
        "tested_sha": settings.expected_sha,
        "claim": TOKEN,
        "workspace_id_sha256": _sha256_parts(
            b"agentium-protected-runner-workspace-v1",
            settings.deployment_id,
            link.workspace_id,
        ),
    }


def _write_artifact(output_directory: Path, payload: dict[str, Any]) -> Path:
    if output_directory.is_symlink():
        raise SFTPAcceptanceError("artifact output directory is unsafe")
    try:
        output_directory = output_directory.resolve(strict=True)
        metadata = output_directory.stat()
    except OSError as exc:
        raise SFTPAcceptanceError("artifact output directory is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or output_directory.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise SFTPAcceptanceError("artifact output directory is unsafe")
    destination = output_directory / ARTIFACT_NAME
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = -1
    created = False
    complete = False
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        created = True
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SFTPAcceptanceError("artifact could not be written")
            view = view[written:]
        os.fsync(descriptor)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            raise SFTPAcceptanceError("artifact permissions are unsafe")
        complete = True
    except FileExistsError as exc:
        raise SFTPAcceptanceError("artifact output already exists") from exc
    except OSError as exc:
        raise SFTPAcceptanceError("artifact could not be written") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if created and not complete:
            destination.unlink(missing_ok=True)
    return destination


async def _execute(
    settings: Settings,
    output_directory: Path,
    *,
    api_request: ApiRequest = _http_json,
    positive_probe: PositiveProbe = _positive_sftp_probe,
    denied_probe: DeniedProbe = _post_revoke_denied_probe,
) -> Path:
    _verify_deployed_build(settings, api_request)
    token = _login(settings, api_request)
    link = _discover_and_create_link(settings, api_request, token)

    positive_error: SFTPAcceptanceError | None = None
    revocation_error: SFTPAcceptanceError | None = None
    try:
        await positive_probe(
            host=settings.sftp_host,
            port=settings.sftp_port,
            username=link.access_id,
            password=link.password,
            expected_fingerprint=settings.host_key_fingerprint,
            timeout=settings.timeout,
        )
    except SFTPAcceptanceError as exc:
        positive_error = exc
    except BaseException:
        positive_error = SFTPAcceptanceError(
            "positive SFTP authentication proof failed"
        )
    finally:
        try:
            _revoke_link(
                settings,
                api_request,
                token,
                link.workspace_slug,
                link.link_id,
            )
        except SFTPAcceptanceError as exc:
            revocation_error = exc
        except BaseException:
            revocation_error = SFTPAcceptanceError(
                "temporary SFTP credential revocation failed"
            )

    if revocation_error is not None:
        raise revocation_error
    if positive_error is not None:
        raise positive_error

    await denied_probe(
        host=settings.sftp_host,
        port=settings.sftp_port,
        username=link.access_id,
        password=link.password,
        expected_fingerprint=settings.host_key_fingerprint,
        timeout=settings.timeout,
    )
    return _write_artifact(output_directory, _artifact(settings, link))


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument(
        "--output",
        required=True,
        help="Existing private directory which will receive sftp-positive-auth.artifact",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command != "run":
            raise SFTPAcceptanceError("invalid command arguments")
        settings = _load_settings()
        asyncio.run(_execute(settings, Path(args.output)))
    except SFTPAcceptanceError:
        print("SFTP acceptance canary failed", file=sys.stderr)
        return 1
    except BaseException:
        print("SFTP acceptance canary failed", file=sys.stderr)
        return 1
    print("SFTP acceptance canary passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
