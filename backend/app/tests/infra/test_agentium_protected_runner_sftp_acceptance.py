from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import stat
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "agentium_protected_runner_sftp_acceptance.py"

EXPECTED_SHA = "a" * 40
DEPLOYMENT_ID = "protected-runner-acceptance-20260723-v1"
USERNAME = "private.operator@example.invalid"
PASSWORD = "private-agentium-password"
API_TOKEN = "private-bearer-token"
HOST = "sftp.production.invalid"
FINGERPRINT = "SHA256:" + base64.b64encode(b"k" * 32).decode().rstrip("=")
WORKSPACE_ID = "private-workspace-id"
WORKSPACE_SLUG = "private-workspace-slug"
LINK_ID = "private-link-id"
ACCESS_ID = "private-access-id"
SFTP_PASSWORD = "private-sftp-password"


def _load_module() -> ModuleType:
    name = "agentium_protected_runner_sftp_acceptance_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> ModuleType:
    return _load_module()


def _settings(module: ModuleType) -> Any:
    return module.Settings(
        base_url="https://agentium.production.invalid",
        expected_sha=EXPECTED_SHA,
        deployment_id=DEPLOYMENT_ID,
        principal_class="operator_personal_admin",
        username=USERNAME,
        password=PASSWORD,
        sftp_host=HOST,
        sftp_port=2222,
        host_key_fingerprint=FINGERPRINT,
        timeout=10.0,
    )


class FakeApi:
    def __init__(
        self,
        *,
        backend_sha: str = EXPECTED_SHA,
        workspace_rows: list[dict[str, Any]] | None = None,
        health_by_slug: dict[str, tuple[int, Any]] | None = None,
        create_by_slug: dict[str, tuple[int, Any]] | None = None,
        revoke_status: int = 200,
    ) -> None:
        self.backend_sha = backend_sha
        self.workspace_rows = workspace_rows or [
            {"id": WORKSPACE_ID, "slug": WORKSPACE_SLUG, "name": "not-exported"}
        ]
        self.health_by_slug = health_by_slug or {
            WORKSPACE_SLUG: (200, {"enabled": True, "workspace": WORKSPACE_SLUG})
        }
        self.create_by_slug = create_by_slug or {
            WORKSPACE_SLUG: (
                200,
                {
                    "link": {
                        "id": LINK_ID,
                        "access_id": ACCESS_ID,
                        "generated_password": SFTP_PASSWORD,
                    }
                },
            )
        }
        self.revoke_status = revoke_status
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None,
        token: str | None,
        workspace_slug: str | None,
        timeout: float,
    ) -> tuple[int, Any]:
        path = "/" + url.split("/", 3)[3]
        self.calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "token": token,
                "workspace_slug": workspace_slug,
                "timeout": timeout,
            }
        )
        if path == "/api/v1/build-info":
            return 200, {
                "service": "backend",
                "revision": self.backend_sha,
                "revision_verified": True,
            }
        if path == "/build-info.json":
            return 200, {
                "service": "frontend",
                "revision": EXPECTED_SHA,
                "revision_verified": True,
            }
        if path == "/api/v1/auth/login":
            assert body == {
                "email": USERNAME,
                "password": PASSWORD,
                "remember_me": False,
            }
            assert token is None
            return 200, {"token": API_TOKEN}
        if path == "/api/v1/auth/workspaces":
            assert token == API_TOKEN
            return 200, self.workspace_rows
        if path == "/api/v1/sftp/health":
            assert token == API_TOKEN
            assert workspace_slug is not None
            return self.health_by_slug.get(workspace_slug, (404, {}))
        if path == "/api/v1/sftp/links":
            assert token == API_TOKEN
            assert workspace_slug is not None
            assert body is not None
            assert body["max_file_size_mb"] == 1
            assert body["allowed_extensions"] == []
            return self.create_by_slug.get(workspace_slug, (403, {}))
        if path == f"/api/v1/sftp/links/{LINK_ID}/revoke":
            assert token == API_TOKEN
            if self.revoke_status != 200:
                return self.revoke_status, {}
            return 200, {"link": {"id": LINK_ID, "status": "revoked"}}
        raise AssertionError(f"unexpected fake API path: {path}")


def _private_output(tmp_path: Path) -> Path:
    output = tmp_path / "evidence"
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    return output


def test_happy_path_emits_canonical_content_free_artifact(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    api = FakeApi()
    operations: list[tuple[str, dict[str, Any]]] = []

    async def positive(**kwargs: Any) -> None:
        operations.append(("positive", kwargs))

    async def denied(**kwargs: Any) -> None:
        operations.append(("denied", kwargs))

    output = _private_output(tmp_path)
    artifact_path = asyncio.run(
        module._execute(
            _settings(module),
            output,
            api_request=api,
            positive_probe=positive,
            denied_probe=denied,
        )
    )

    assert artifact_path == output.resolve() / "sftp-positive-auth.artifact"
    assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600
    raw = artifact_path.read_bytes()
    payload = json.loads(raw)
    assert raw == (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    assert payload["kind"] == "sftp-positive-auth.artifact"
    assert payload["result"] == "passed"
    assert payload["tested_sha"] == EXPECTED_SHA
    assert payload["deployment_id"] == DEPLOYMENT_ID
    assert payload["evidence_class"] == "acceptance"
    assert payload["formal_release_eligible"] is False
    assert payload["principal_class"] == "operator_personal_admin"
    assert "token" not in payload
    assert all(payload["checks"].values())
    assert len(operations) == 2
    assert operations[0][0] == "positive"
    assert operations[1][0] == "denied"

    text = raw.decode()
    for private_value in (
        USERNAME,
        PASSWORD,
        API_TOKEN,
        HOST,
        WORKSPACE_ID,
        WORKSPACE_SLUG,
        LINK_ID,
        ACCESS_ID,
        SFTP_PASSWORD,
        "not-exported",
    ):
        assert private_value not in text
    assert "generated_password" not in text
    assert "Bearer " not in text
    assert "getcwd" in text
    assert "stat_dot" in text
    assert "list" not in text
    assert "read" not in text
    assert "write" not in text


def test_positive_protocol_uses_only_getcwd_and_stat_dot(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, Any]] = []
    connection_options: list[dict[str, Any]] = []

    class Key:
        def get_algorithm(self) -> str:
            return "ssh-ed25519"

        def get_fingerprint(self, algorithm: str) -> str:
            assert algorithm == "sha256"
            return FINGERPRINT

        def export_public_key(self, format_name: str) -> bytes:
            assert format_name == "openssh"
            return b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake"

    class Sftp:
        async def __aenter__(self) -> Any:
            events.append(("sftp_enter", None))
            return self

        async def __aexit__(self, *_args: Any) -> None:
            events.append(("sftp_exit", None))

        async def getcwd(self) -> str:
            events.append(("getcwd", None))
            return "/private/path-never-exported"

        async def stat(self, path: str) -> object:
            events.append(("stat", path))
            return object()

    class Connection:
        async def __aenter__(self) -> Any:
            events.append(("authenticated", None))
            return self

        async def __aexit__(self, *_args: Any) -> None:
            events.append(("connection_exit", None))

        def start_sftp_client(self) -> Sftp:
            events.append(("start_sftp", None))
            return Sftp()

    async def get_server_host_key(**kwargs: Any) -> Key:
        events.append(("host_key", kwargs))
        return Key()

    def connect(**kwargs: Any) -> Connection:
        connection_options.append(kwargs)
        return Connection()

    monkeypatch.setitem(
        sys.modules,
        "asyncssh",
        SimpleNamespace(
            get_server_host_key=get_server_host_key,
            connect=connect,
            PermissionDenied=PermissionError,
        ),
    )

    asyncio.run(
        module._positive_sftp_probe(
            host=HOST,
            port=2222,
            username=ACCESS_ID,
            password=SFTP_PASSWORD,
            expected_fingerprint=FINGERPRINT,
            timeout=10.0,
        )
    )

    assert [event[0] for event in events] == [
        "host_key",
        "authenticated",
        "start_sftp",
        "sftp_enter",
        "getcwd",
        "stat",
        "sftp_exit",
        "connection_exit",
    ]
    assert ("stat", "/") in events
    options = connection_options[0]
    assert options["known_hosts"].startswith(f"[{HOST}]:2222 ".encode())
    assert options["public_key_auth"] is False
    assert options["kbdint_auth"] is False
    assert options["password_auth"] is True
    assert options["client_keys"] == []
    assert options["agent_path"] is None


def test_post_revoke_probe_accepts_only_explicit_permission_denial(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class PermissionDeniedError(Exception):
        pass

    class Key:
        def get_algorithm(self) -> str:
            return "ssh-ed25519"

        def get_fingerprint(self, algorithm: str) -> str:
            assert algorithm == "sha256"
            return FINGERPRINT

        def export_public_key(self, format_name: str) -> bytes:
            assert format_name == "openssh"
            return b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake"

    class DeniedConnection:
        async def __aenter__(self) -> Any:
            events.append("authentication_attempted")
            raise PermissionDeniedError("private endpoint and principal omitted")

        async def __aexit__(self, *_args: Any) -> None:
            raise AssertionError("a denied connection cannot be exited")

    async def get_server_host_key(**_kwargs: Any) -> Key:
        events.append("host_key_pinned")
        return Key()

    def connect(**kwargs: Any) -> DeniedConnection:
        assert kwargs["password_auth"] is True
        assert kwargs["public_key_auth"] is False
        return DeniedConnection()

    monkeypatch.setitem(
        sys.modules,
        "asyncssh",
        SimpleNamespace(
            get_server_host_key=get_server_host_key,
            connect=connect,
            PermissionDenied=PermissionDeniedError,
        ),
    )

    asyncio.run(
        module._post_revoke_denied_probe(
            host=HOST,
            port=2222,
            username=ACCESS_ID,
            password=SFTP_PASSWORD,
            expected_fingerprint=FINGERPRINT,
            timeout=10.0,
        )
    )
    assert events == ["host_key_pinned", "authentication_attempted"]


def test_link_is_revoked_when_positive_probe_fails(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    api = FakeApi()
    denied_called = False

    async def positive(**_kwargs: Any) -> None:
        raise module.SFTPAcceptanceError("safe protocol failure")

    async def denied(**_kwargs: Any) -> None:
        nonlocal denied_called
        denied_called = True

    with pytest.raises(module.SFTPAcceptanceError, match="safe protocol failure"):
        asyncio.run(
            module._execute(
                _settings(module),
                _private_output(tmp_path),
                api_request=api,
                positive_probe=positive,
                denied_probe=denied,
            )
        )

    assert any(call["path"].endswith(f"/{LINK_ID}/revoke") for call in api.calls)
    assert denied_called is False
    assert not list(tmp_path.rglob("*.artifact"))


def test_revocation_failure_is_fail_closed_and_skips_denial_probe(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    api = FakeApi(revoke_status=503)
    denied_called = False

    async def positive(**_kwargs: Any) -> None:
        return None

    async def denied(**_kwargs: Any) -> None:
        nonlocal denied_called
        denied_called = True

    with pytest.raises(
        module.SFTPAcceptanceError,
        match="credential revocation failed",
    ):
        asyncio.run(
            module._execute(
                _settings(module),
                _private_output(tmp_path),
                api_request=api,
                positive_probe=positive,
                denied_probe=denied,
            )
        )
    assert denied_called is False
    assert not list(tmp_path.rglob("*.artifact"))


def test_auto_discovery_skips_unavailable_workspaces(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    disabled = ("disabled-id", "disabled-workspace")
    forbidden = ("forbidden-id", "forbidden-workspace")
    enabled = (WORKSPACE_ID, WORKSPACE_SLUG)
    api = FakeApi(
        workspace_rows=[
            {"id": disabled[0], "slug": disabled[1]},
            {"id": forbidden[0], "slug": forbidden[1]},
            {"id": enabled[0], "slug": enabled[1]},
        ],
        health_by_slug={
            disabled[1]: (200, {"enabled": False}),
            forbidden[1]: (403, {}),
            enabled[1]: (200, {"enabled": True}),
        },
    )

    async def succeeds(**_kwargs: Any) -> None:
        return None

    asyncio.run(
        module._execute(
            _settings(module),
            _private_output(tmp_path),
            api_request=api,
            positive_probe=succeeds,
            denied_probe=succeeds,
        )
    )
    create_calls = [
        call for call in api.calls if call["path"] == "/api/v1/sftp/links"
    ]
    assert [call["workspace_slug"] for call in create_calls] == [WORKSPACE_SLUG]


def test_build_mismatch_stops_before_authentication(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    api = FakeApi(backend_sha="b" * 40)

    async def must_not_run(**_kwargs: Any) -> None:
        raise AssertionError("SFTP must not run")

    with pytest.raises(module.SFTPAcceptanceError, match="build binding"):
        asyncio.run(
            module._execute(
                _settings(module),
                _private_output(tmp_path),
                api_request=api,
                positive_probe=must_not_run,
                denied_probe=must_not_run,
            )
        )
    assert [call["path"] for call in api.calls] == ["/api/v1/build-info"]


def test_existing_artifact_is_never_overwritten(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    output = _private_output(tmp_path)
    destination = output / "sftp-positive-auth.artifact"
    destination.write_text("existing\n")
    destination.chmod(0o600)
    lease = module.TemporaryLink(
        workspace_id=WORKSPACE_ID,
        workspace_slug=WORKSPACE_SLUG,
        link_id=LINK_ID,
        access_id=ACCESS_ID,
        password=SFTP_PASSWORD,
    )
    with pytest.raises(module.SFTPAcceptanceError, match="already exists"):
        module._write_artifact(output, module._artifact(_settings(module), lease))
    assert destination.read_text() == "existing\n"


def test_cli_never_logs_secret_exception_text(
    module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = {
        "E2E_EXPECTED_SHA": EXPECTED_SHA,
        "E2E_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "E2E_PRINCIPAL_CLASS": "operator_personal_admin",
        "E2E_USERNAME": USERNAME,
        "E2E_PASSWORD": PASSWORD,
        "E2E_SFTP_HOST": HOST,
        "E2E_SFTP_PORT": "2222",
        "E2E_SFTP_HOST_KEY_SHA256": FINGERPRINT,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    async def failing_execute(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(f"private failure {USERNAME} {PASSWORD} {API_TOKEN}")

    monkeypatch.setattr(module, "_execute", failing_execute)
    result = module.main(["run", "--output", str(_private_output(tmp_path))])
    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "SFTP acceptance canary failed\n"
    assert USERNAME not in captured.err
    assert PASSWORD not in captured.err
    assert API_TOKEN not in captured.err
