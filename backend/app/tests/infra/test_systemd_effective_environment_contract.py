from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
INSTALLER = ROOT / "deploy" / "install-backend-service.sh"
SAFE_DEPLOYER = ROOT / "scripts" / "deploy-agentium-safe.sh"
SHA = "a" * 40


def _effective_environment_policy() -> str:
    script = INSTALLER.read_text(encoding="utf-8")
    function = script.split("\nassert_effective_environment() {\n", 1)[1].split(
        "\n}\n\nrestore_previous_dropin()", 1
    )[0]
    return function.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


def _fake_systemctl(path: Path) -> Path:
    executable = path / "systemctl"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "argument = next((item for item in sys.argv if item.startswith('--property=')), '')\n"
        "name = argument.partition('=')[2]\n"
        "value = os.environ.get('FAKE_SYSTEMD_' + name, '')\n"
        "sys.stdout.write(value + ('\\n' if value else ''))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _run_policy(
    tmp_path: Path,
    *,
    overrides: dict[str, str] | None = None,
    env_file_content: str = "DATABASE_URL=postgresql://private.example/agentium\n",
) -> subprocess.CompletedProcess[str]:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir(exist_ok=True)
    _fake_systemctl(binary_dir)
    env_file = tmp_path / "runtime.env"
    if "AGENTIUM_IMAGE_REVISION=" not in env_file_content:
        env_file_content += f"AGENTIUM_IMAGE_REVISION={SHA}\n"
    env_file.write_text(env_file_content, encoding="utf-8")
    env_file.chmod(0o600)
    fragment = "/etc/systemd/system/agentium-backend.service"
    dropin = "/etc/systemd/system/agentium-backend.service.d/" "99-agentium-safe-runtime-env.conf"
    properties = {
        "FragmentPath": fragment,
        "DropInPaths": dropin,
        "EnvironmentFiles": f"{env_file} (ignore_errors=no)",
        "Environment": ("STARTUP_RECONCILIATION=disabled AGENTIUM_DISABLE_DOTENV=1"),
        "PassEnvironment": "",
        "UnsetEnvironment": "",
    }
    properties.update(overrides or {})
    environment = os.environ.copy()
    environment["PATH"] = f"{binary_dir}{os.pathsep}{environment['PATH']}"
    environment.update({f"FAKE_SYSTEMD_{name}": value for name, value in properties.items()})
    return subprocess.run(
        [
            sys.executable,
            "-",
            "agentium-backend.service",
            fragment,
            dropin,
            str(env_file),
            SHA,
        ],
        input=_effective_environment_policy(),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )


def test_effective_environment_policy_accepts_only_the_canonical_contract(
    tmp_path: Path,
) -> None:
    completed = _run_policy(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""


@pytest.mark.parametrize(
    ("property_name", "value", "message"),
    [
        (
            "FragmentPath",
            "/run/systemd/system/agentium-backend.service",
            "FragmentPath is not the canonical unit",
        ),
        (
            "DropInPaths",
            "/etc/systemd/system/agentium-backend.service.d/99-agentium-safe-runtime-env.conf "
            "/run/systemd/system/agentium-backend.service.d/10-foreign.conf",
            "DropInPaths is not the sole frozen drop-in",
        ),
        (
            "EnvironmentFiles",
            "/tmp/foreign.env (ignore_errors=no)",
            "EnvironmentFiles is not the unique frozen snapshot",
        ),
        (
            "Environment",
            "STARTUP_RECONCILIATION=enabled AGENTIUM_DISABLE_DOTENV=1",
            "Environment does not enforce the startup controls",
        ),
        (
            "Environment",
            "STARTUP_RECONCILIATION=disabled AGENTIUM_DISABLE_DOTENV=1 EXTRA=value",
            "Environment does not enforce the startup controls",
        ),
        (
            "PassEnvironment",
            "STARTUP_RECONCILIATION",
            "PassEnvironment must be empty",
        ),
        (
            "UnsetEnvironment",
            "AGENTIUM_DISABLE_DOTENV",
            "UnsetEnvironment must be empty",
        ),
    ],
)
def test_effective_environment_policy_rejects_systemd_bypass_surfaces(
    tmp_path: Path, property_name: str, value: str, message: str
) -> None:
    completed = _run_policy(tmp_path, overrides={property_name: value})
    assert completed.returncode != 0
    assert message in completed.stderr


@pytest.mark.parametrize(
    "assignment",
    [
        "STARTUP_RECONCILIATION=enabled",
        "AGENTIUM_DISABLE_DOTENV=0",
        'export STARTUP_RECONCILIATION="disabled"',
    ],
)
def test_frozen_environment_file_cannot_shadow_startup_controls(
    tmp_path: Path, assignment: str
) -> None:
    completed = _run_policy(
        tmp_path,
        env_file_content=f"DATABASE_URL=private\n{assignment}\n",
    )
    assert completed.returncode != 0
    assert "EnvironmentFile shadows a non-mutating startup control" in completed.stderr


@pytest.mark.parametrize(
    "revision_line",
    ["AGENTIUM_IMAGE_REVISION=" + "b" * 40, "AGENTIUM_IMAGE_REVISION=development"],
)
def test_frozen_environment_file_must_match_expected_revision(
    tmp_path: Path, revision_line: str
) -> None:
    completed = _run_policy(
        tmp_path,
        env_file_content=f"DATABASE_URL=private\n{revision_line}\n",
    )
    assert completed.returncode != 0
    assert "EnvironmentFile is not bound to the expected revision" in completed.stderr


def test_effective_environment_failure_never_serializes_values(tmp_path: Path) -> None:
    secret = "do-not-serialize-this-secret"
    completed = _run_policy(
        tmp_path,
        overrides={
            "Environment": (
                "STARTUP_RECONCILIATION=enabled AGENTIUM_DISABLE_DOTENV=1 " f"DATABASE_URL={secret}"
            )
        },
    )
    assert completed.returncode != 0
    assert secret not in completed.stdout
    assert secret not in completed.stderr


def test_release_b_refuses_the_historical_public_systemd_preimage() -> None:
    script = SAFE_DEPLOYER.read_text(encoding="utf-8")
    body = script.split("\nassert_systemd_unit_adoptable() {\n", 1)[1].split(
        "\n}\n\nassert_systemd_unit_contract()", 1
    )[0]

    assert '"${allowed[0]}"' in body
    assert '"${allowed[1]}"' in body
    assert '"${allowed[2]}"' not in body
    assert "adoption obligatoire en Release A" in body
