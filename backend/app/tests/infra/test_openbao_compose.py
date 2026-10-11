"""OpenBao opt-in overlay: static contract, rendered topology and bootstrap flow."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
OVERLAY = ROOT / "docker/compose.agentium.openbao.yml"
HUB_OVERLAY = ROOT / "docker/compose.agentium.openbao-huggingface.yml"
CONFIG = ROOT / "docker/openbao/openbao.hcl"
BOOTSTRAP = ROOT / "scripts/agentium_openbao_bootstrap.py"
SNAPSHOT = ROOT / "scripts/agentium-openbao-snapshot.sh"
CLIENTS = ("agentium-backend", "agentium-migrate", "agentium-worker-cpu", "agentium-worker-recipes")


def _server(model: dict) -> dict:
    return model["services"]["agentium-openbao"]


def test_server_is_digest_pinned_internal_and_on_protected_storage():
    server = _server(yaml.safe_load(OVERLAY.read_text()))
    assert re.fullmatch(r"openbao/openbao@sha256:[0-9a-f]{64}", server["image"])
    assert server["profiles"] == ["openbao"]
    assert server["networks"] == ["agentium-net"]
    assert "ports" not in server and "expose" not in server
    assert server["cap_drop"] == ["ALL"] and server["cap_add"] == ["IPC_LOCK"]
    assert "no-new-privileges:true" in server["security_opt"]
    mounts = {m["target"]: m for m in server["volumes"]}
    data = mounts["/openbao/data"]
    assert data["source"] == "${AGENTIUM_OPENBAO_DATA_PATH:-/srv/agentium-data/openbao}"
    assert data["bind"]["create_host_path"] is False
    assert not data.get("read_only", False)
    key = mounts["/run/openbao-seal/unseal.key"]
    assert key["read_only"] is True and key["bind"]["create_host_path"] is False
    assert key["source"].startswith("${AGENTIUM_OPENBAO_UNSEAL_KEY_FILE:?")
    assert mounts["/openbao/config/openbao.hcl"]["read_only"] is True


def test_server_config_uses_static_seal_raft_and_declarative_audit():
    hcl = CONFIG.read_text()
    assert 'storage "raft"' in hcl and 'path    = "/openbao/data/raft"' in hcl
    assert 'seal "static"' in hcl
    assert 'current_key    = "file:///run/openbao-seal/unseal.key"' in hcl
    assert 'audit "file" "agentium-file"' in hcl
    assert "/openbao/data/audit/audit.log" in hcl
    assert "ui            = false" in hcl


def test_clients_get_their_own_approle_files_and_hub_reader_is_separate():
    model = yaml.safe_load(OVERLAY.read_text())
    for name in CLIENTS:
        service = model["services"][name]
        assert service["environment"]["OPENBAO_ADDR"] == "http://agentium-openbao:8200"
        expected = "BACKEND" if name in ("agentium-backend", "agentium-migrate") else "WORKER"
        assert service["env_file"] == [
            f"${{AGENTIUM_OPENBAO_{expected}_ENV_FILE:?Set the OpenBao "
            f"{expected.lower()} AppRole environment file}}"
        ]
    assert "agentium-hub-fetch" not in model["services"]
    hub = yaml.safe_load(HUB_OVERLAY.read_text())["services"]["agentium-hub-fetch"]
    assert hub["env_file"][0].startswith("${AGENTIUM_OPENBAO_HUB_ENV_FILE:?")


def test_rendered_overlay_keeps_server_internal(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI is unavailable")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("Docker Compose plugin is unavailable")
    files = {}
    for name in ("app", "hub", "backend", "worker", "hubbao"):
        files[name] = tmp_path / f"{name}.env"
        files[name].write_text("")
    environment = {
        **os.environ,
        "AGENTIUM_ENV_FILE": str(files["app"]),
        "AGENTIUM_HUB_ENV_FILE": str(files["hub"]),
        "AGENTIUM_OPENBAO_UNSEAL_KEY_FILE": str(tmp_path / "unseal.key"),
        "AGENTIUM_OPENBAO_BACKEND_ENV_FILE": str(files["backend"]),
        "AGENTIUM_OPENBAO_WORKER_ENV_FILE": str(files["worker"]),
        "AGENTIUM_OPENBAO_HUB_ENV_FILE": str(files["hubbao"]),
    }
    result = subprocess.run(
        [
            "docker", "compose",
            "-f", str(ROOT / "docker/compose.agentium.yml"),
            "-f", str(ROOT / "docker/compose.agentium.huggingface.yml"),
            "-f", str(OVERLAY),
            "-f", str(HUB_OVERLAY),
            "--profile", "openbao", "--profile", "huggingface", "--profile", "tools",
            "config", "--format", "json",
        ],
        env=environment, capture_output=True, text=True, check=True,
    )
    services = json.loads(result.stdout)["services"]
    server = services["agentium-openbao"]
    assert not server.get("ports")
    assert list(server["networks"]) == ["agentium-net"]
    assert server["container_name"] == "agentium-openbao"
    data = next(m for m in server["volumes"] if m["target"] == "/openbao/data")
    assert data["source"] == "/srv/agentium-data/openbao"
    assert data.get("bind", {}).get("create_host_path", False) is False
    for name in CLIENTS:
        assert services[name]["environment"]["OPENBAO_ADDR"] == "http://agentium-openbao:8200"
    assert services["agentium-hub-fetch"]["environment"]["OPENBAO_MOUNT"] == "agentium"
    for name, service in services.items():
        if name == "agentium-openbao":
            continue
        assert all(m.get("source") != data["source"] for m in service.get("volumes", []))


def _bootstrap():
    spec = importlib.util.spec_from_file_location("agentium_openbao_bootstrap_test", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeServer:
    def __init__(self) -> None:
        self.initialized = False
        self.root = "root-token-test"
        self.revoked = False
        self.calls: list[tuple[str, str]] = []
        self.mounts = {"sys/": {"type": "system"}}
        self.audits = {"agentium-file/": {"type": "file"}}
        self.policies: dict[str, str] = {}
        self.roles: dict[str, dict] = {}

    def __call__(self, method, path, *, token=None, body=None):
        self.calls.append((method, path))
        if path.startswith("sys/health"):
            return 200, {"initialized": self.initialized, "sealed": False}
        if path == "sys/init":
            assert body == {"recovery_shares": 1, "recovery_threshold": 1}
            self.initialized = True
            return 200, {"root_token": self.root, "recovery_keys_b64": ["recovery-test"]}
        if token != self.root or self.revoked:
            return 403, {"errors": ["permission denied"]}
        if path == "auth/token/revoke-self":
            self.revoked = True
            return 204, {}
        if path == "sys/mounts":
            return 200, {"data": self.mounts}
        if path.startswith("sys/mounts/"):
            self.mounts[path.removeprefix("sys/mounts/") + "/"] = body
            return 204, {}
        if path == "sys/audit":
            return 200, {"data": self.audits}
        if path == "sys/auth":
            return 200, {"data": {"token/": {}}}
        if path == "sys/auth/approle":
            return 204, {}
        if path.startswith("sys/policies/acl/"):
            self.policies[path.rsplit("/", 1)[1]] = body["policy"]
            return 204, {}
        role = path.split("/")[3]
        if path.endswith("/role-id"):
            return 200, {"data": {"role_id": f"role-{role}"}}
        if path.endswith("/secret-id"):
            return 200, {"data": {"secret_id": f"sid-{role}"}}
        self.roles[role] = body
        return 204, {}


def test_bootstrap_init_configures_approles_writes_0600_and_revokes_root(tmp_path, capsys):
    module = _bootstrap()
    server = FakeServer()
    token = module.init(server, tmp_path)
    module.configure(server, token, tmp_path)

    assert server.revoked
    assert server.mounts["agentium/"] == {"type": "kv", "options": {"version": "2"}}
    assert set(server.roles) == {"backend", "worker", "hub-fetch", "snapshot"}
    assert server.roles["hub-fetch"]["token_policies"] == ["agentium-hub-fetch"]
    assert 'path "agentium/data/*" { capabilities = ["read"] }' in server.policies["agentium-worker"]
    assert "create" not in server.policies["agentium-hub-fetch"]
    hub_policy = server.policies["agentium-hub-fetch"]
    assert "agentium/data/*" not in hub_policy
    assert [line for line in hub_policy.splitlines() if line.strip()] == [
        'path "agentium/data/platform/+/nodes/*" { capabilities = ["read"] }',
        'path "agentium/data/workspace/+/nodes/*" { capabilities = ["read"] }',
    ]
    for role in ("backend", "worker", "hub-fetch", "snapshot"):
        path = tmp_path / f"openbao-{role}.env"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.read_text() == f"OPENBAO_ROLE_ID=role-{role}\nOPENBAO_SECRET_ID=sid-{role}\n"
    assert stat.S_IMODE((tmp_path / "openbao-recovery.env").stat().st_mode) == 0o600
    out = capsys.readouterr().out
    for leaked in ("root-token-test", "recovery-test", "sid-"):
        assert leaked not in out

    with pytest.raises(module.BootstrapError, match="already initialised"):
        module.init(server, tmp_path)


def test_bootstrap_revokes_root_even_when_audit_device_is_missing(tmp_path):
    module = _bootstrap()
    server = FakeServer()
    server.audits = {}
    token = module.init(server, tmp_path)
    with pytest.raises(module.BootstrapError, match="audit device"):
        module.configure(server, token, tmp_path)
    assert server.revoked
    assert not (tmp_path / "openbao-backend.env").exists()


def test_bootstrap_prepare_writes_hex_key_0400_and_placeholders(tmp_path, monkeypatch):
    module = _bootstrap()
    monkeypatch.setattr(module.os, "chown", lambda *a: None)
    runtime_env = tmp_path / "runtime-env"
    data = tmp_path / "openbao"
    runtime_env.mkdir()
    data.mkdir()
    module.prepare(runtime_env, data, 100, 1000)
    key = runtime_env / "openbao-unseal.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o400
    assert re.fullmatch(r"[0-9a-f]{64}", key.read_text())
    first = key.read_text()
    module.prepare(runtime_env, data, 100, 1000)
    assert key.read_text() == first  # never rotated implicitly
    assert (runtime_env / "openbao-backend.env").read_text() == ""
    assert (data / "raft").is_dir() and (data / "audit").is_dir()
    with pytest.raises(module.BootstrapError):
        module.prepare(runtime_env, tmp_path / "absent", 100, 1000)


def test_snapshot_script_keeps_credentials_off_argv():
    script = SNAPSHOT.read_text()
    assert subprocess.run(["bash", "-n", str(SNAPSHOT)]).returncode == 0
    assert "--data @-" in script
    assert '-H "@$WORK/headers"' in script
    assert "/v1/sys/storage/raft/snapshot" in script
    assert "chmod 0600" in script
    assert "/srv/agentium-data/openbao-backups" in script
