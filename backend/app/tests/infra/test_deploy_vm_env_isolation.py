from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DEPLOY = ROOT / "scripts" / "deploy-vm.sh"
SAFE_DEPLOY = ROOT / "scripts" / "deploy-agentium-safe.sh"
POLLUTION = {
    "AGENTIUM_IMAGE_TAG": "polluted-image",
    "AGENTIUM_IMAGE_REVISION": "polluted-revision",
    "AGENTIUM_POSTGRES_DB": "polluted_database",
    "AGENTIUM_POSTGRES_USER": "polluted_user",
    "AGENTIUM_POSTGRES_PASSWORD": "polluted-password",
    "AGENTIUM_BACKEND_HOST_PORT": "1",
    "AGENTIUM_FRONTEND_HOST_PORT": "2",
    "AGENTIUM_OBJECT_STORE_PATH": "/tmp/polluted-object-store",
    "AGENTIUM_SECURE_DEPOSIT_PATH": "/tmp/polluted-secure-deposit",
    "AGENTIUM_FAISS_PATH": "/tmp/polluted-faiss",
    "AGENTIUM_QDRANT_SNAPSHOT_PATH": "/tmp/polluted-qdrant",
    "AGENTIUM_POSTGRES_VOLUME": "polluted-postgres-volume",
    "AGENTIUM_QDRANT_VOLUME": "polluted-qdrant-volume",
    "AGENTIUM_MINIO_VOLUME": "polluted-minio-volume",
    "AGENTIUM_ENV_FILE": "/tmp/polluted-application.env",
    "COMPOSE_PROJECT_NAME": "polluted-project",
    "DOCKER_HOST": "tcp://polluted.invalid:2375",
    "AGENTIUM_QDRANT_EFFECTIVE_API_KEY": "polluted-qdrant-key",
    "AGENTIUM_CELERY_BEAT": "1",
    "AGENTIUM_STARTUP_RECONCILIATION": "enabled",
}


def _shell_function(script: str, name: str) -> str:
    marker = f"\n{name}() {{\n"
    assert marker in script
    suffix = script.split(marker, 1)[1]
    body: list[str] = []
    heredoc: str | None = None
    for line in suffix.splitlines(keepends=True):
        if heredoc is not None:
            body.append(line)
            if line.strip() == heredoc:
                heredoc = None
            continue
        if line.rstrip("\n") == "}":
            return f"{name}() {{\n{''.join(body).rstrip(chr(10))}\n}}\n"
        body.append(line)
        match = re.search(
            r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))",
            line,
        )
        if match:
            heredoc = next(group for group in match.groups() if group is not None)
    raise AssertionError(f"shell function {name!r} has no closing brace")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _polluted_environment() -> dict[str, str]:
    result = os.environ.copy()
    result.update(POLLUTION)
    return result


def test_deploy_vm_is_valid_bash_and_reads_runtime_values_through_helper() -> None:
    subprocess.run(["bash", "-n", str(DEPLOY)], check=True)
    script = DEPLOY.read_text(encoding="utf-8")
    reader = _shell_function(script, "read_env_value")
    loader = _shell_function(script, "load_compose_env")

    assert '"$SAFE_ENV_BUNDLE_HELPER" value' in reader
    assert 'export PATH="$COMPOSE_CLEAN_PATH"' in script
    assert "export PYTHONDONTWRITEBYTECODE=1" in script
    assert "unset PYTHONBREAKPOINT PYTHONHOME PYTHONINSPECT PYTHONOPTIMIZE" in script
    assert '--role compose_main --key "$key"' in reader
    assert "bundle_role_path application" in loader
    for inherited in (
        "${AGENTIUM_IMAGE_TAG:-",
        "${AGENTIUM_POSTGRES_DB:-",
        "${AGENTIUM_POSTGRES_USER:-",
        "${AGENTIUM_BACKEND_HOST_PORT:-",
        "${AGENTIUM_FRONTEND_HOST_PORT:-",
    ):
        assert inherited not in loader


def test_compose_gateway_scrubs_polluted_shell_and_keeps_only_transaction_overrides(
    tmp_path: Path,
) -> None:
    script = DEPLOY.read_text(encoding="utf-8")
    dc = _shell_function(script, "dc")
    bin_dir = tmp_path / "bin"
    home = tmp_path / "home"
    bin_dir.mkdir()
    home.mkdir()
    captured_env = tmp_path / "docker.env"
    captured_args = tmp_path / "docker.args"
    helper = tmp_path / "env-helper"
    _write_executable(helper, "#!/bin/sh\nexit 0\n")
    _write_executable(
        bin_dir / "docker",
        "#!/bin/sh\n"
        f"/usr/bin/env | /usr/bin/sort > {shlex.quote(str(captured_env))}\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(captured_args))}\n",
    )
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "CHECK_ONLY=0\n"
        f"SAFE_ENV_BUNDLE_HELPER={shlex.quote(str(helper))}\n"
        "SAFE_ENV_BUNDLE_DIR=/safe/runtime-env\n"
        f"SAFE_CANDIDATE_SHA={'a' * 40}\n"
        "SAFE_DEPLOYMENT_ID=deployment-test\n"
        f"SAFE_ENV_MANIFEST_SHA256={'b' * 64}\n"
        "SAFE_QDRANT_OVERRIDE_FILE=/safe/qdrant-override.yml\n"
        "SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE=\n"
        "SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE=\n"
        f"SAFE_QDRANT_KEY={'q' * 32}\n"
        "SAFE_CELERY_BEAT=0\n"
        "SAFE_STARTUP_RECONCILIATION=disabled\n"
        f"COMPOSE_CLEAN_HOME={shlex.quote(str(home))}\n"
        f"COMPOSE_CLEAN_PATH={shlex.quote(str(bin_dir))}:/usr/bin:/bin\n"
        "ENV_FILE=/safe/runtime-env/compose.effective.env\n"
        "COMPOSE_FILE=compose.agentium.yml\n"
        "die() { printf '%s\\n' \"$*\" >&2; exit 1; }\n"
        f"{dc}"
        "dc config\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["bash", str(harness)],
        check=True,
        env=_polluted_environment(),
        text=True,
        capture_output=True,
    )

    effective = captured_env.read_text(encoding="utf-8").splitlines()
    assert f"AGENTIUM_QDRANT_EFFECTIVE_API_KEY={'q' * 32}" in effective
    assert "AGENTIUM_CELERY_BEAT=0" in effective
    assert "AGENTIUM_STARTUP_RECONCILIATION=disabled" in effective
    assert f"HOME={home}" in effective
    assert f"PATH={bin_dir}:/usr/bin:/bin" in effective
    for polluted, polluted_value in POLLUTION.items():
        assert f"{polluted}={polluted_value}" not in effective, polluted
    assert captured_args.read_text(encoding="utf-8").splitlines() == [
        "compose",
        "--env-file",
        "/safe/runtime-env/compose.effective.env",
        "-f",
        "compose.agentium.yml",
        "-f",
        "/safe/qdrant-override.yml",
        "config",
    ]


def test_orchestrator_compose_gateway_ignores_ambient_controls_and_shell_pollution(
    tmp_path: Path,
) -> None:
    script = SAFE_DEPLOY.read_text(encoding="utf-8")
    compose = _shell_function(script, "compose")
    bin_dir = tmp_path / "bin"
    home = tmp_path / "home"
    bin_dir.mkdir()
    home.mkdir()
    captured_env = tmp_path / "docker.env"
    captured_args = tmp_path / "docker.args"
    _write_executable(
        bin_dir / "docker",
        "#!/bin/sh\n"
        f"/usr/bin/env | /usr/bin/sort > {shlex.quote(str(captured_env))}\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(captured_args))}\n",
    )
    harness = tmp_path / "orchestrator-compose.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "unset AGENTIUM_QDRANT_EFFECTIVE_API_KEY AGENTIUM_CELERY_BEAT "
        "AGENTIUM_STARTUP_RECONCILIATION\n"
        f"REPO_DIR={shlex.quote(str(tmp_path))}\n"
        "mkdir -p \"$REPO_DIR/docker\"\n"
        f"COMPOSE_CLEAN_HOME={shlex.quote(str(home))}\n"
        f"COMPOSE_CLEAN_PATH={shlex.quote(str(bin_dir))}:/usr/bin:/bin\n"
        "ENV_FILE=/safe/runtime-env/compose.effective.env\n"
        "COMPOSE_FILE=compose.agentium.yml\n"
        "verify_runtime_env_bundle() { :; }\n"
        f"qdrant_effective_client_key() {{ printf '%s\\n' {'q' * 32}; }}\n"
        "compose_transaction_override() { printf '%s\\n' /safe/qdrant.yml; }\n"
        "die() { printf '%s\\n' \"$*\" >&2; exit 1; }\n"
        f"{compose}"
        "AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled compose config\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["bash", str(harness)],
        check=True,
        env=_polluted_environment(),
        text=True,
        capture_output=True,
    )

    effective = captured_env.read_text(encoding="utf-8").splitlines()
    assert f"AGENTIUM_QDRANT_EFFECTIVE_API_KEY={'q' * 32}" in effective
    assert "AGENTIUM_CELERY_BEAT=0" in effective
    assert "AGENTIUM_STARTUP_RECONCILIATION=disabled" in effective
    assert f"HOME={home}" in effective
    assert f"PATH={bin_dir}:/usr/bin:/bin" in effective
    for polluted in POLLUTION:
        assert not any(line == f"{polluted}={POLLUTION[polluted]}" for line in effective), polluted
    assert captured_args.read_text(encoding="utf-8").splitlines() == [
        "compose",
        "--env-file",
        "/safe/runtime-env/compose.effective.env",
        "-f",
        "compose.agentium.yml",
        "-f",
        "/safe/qdrant.yml",
        "config",
    ]


def test_loader_ignores_polluted_shell_and_uses_digest_bound_snapshot_values(
    tmp_path: Path,
) -> None:
    script = DEPLOY.read_text(encoding="utf-8")
    functions = "".join(
        _shell_function(script, name)
        for name in ("read_env_value", "bundle_role_path", "load_compose_env")
    )
    bundle = tmp_path / "runtime-env"
    bundle.mkdir()
    compose_env = bundle / "compose.effective.env"
    compose_env.write_text("frozen\n", encoding="utf-8")
    application_env = bundle / "source-application.env"
    application_env.write_text("APP=frozen\n", encoding="utf-8")
    helper_log = tmp_path / "helper.log"
    helper = tmp_path / "env-helper"
    _write_executable(
        helper,
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(helper_log))}\n"
        "command=$1\n"
        "shift\n"
        "key=\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  case "$1" in\n'
        "    --key) key=$2; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        'case "$command:$key" in\n'
        f"  role-path:) printf '%s\\n' {shlex.quote(str(application_env))} ;;\n"
        "  value:AGENTIUM_POSTGRES_PASSWORD) printf '%s\\n' frozen-password ;;\n"
        "  value:AGENTIUM_POSTGRES_DB) printf '%s\\n' frozen_database ;;\n"
        "  value:AGENTIUM_POSTGRES_USER) printf '%s\\n' frozen_user ;;\n"
        "  value:AGENTIUM_BACKEND_HOST_PORT) printf '%s\\n' 18001 ;;\n"
        "  value:AGENTIUM_FRONTEND_HOST_PORT) printf '%s\\n' 18081 ;;\n"
        "  value:AGENTIUM_IMAGE_TAG) printf '%s\\n' frozen-tag ;;\n"
        "  value:AGENTIUM_OBJECT_STORE_PATH) printf '%s\\n' /srv/agentium-data/object_store ;;\n"
        "  value:AGENTIUM_SECURE_DEPOSIT_PATH) printf '%s\\n' /srv/secure-deposit ;;\n"
        "  value:AGENTIUM_FAISS_PATH) printf '%s\\n' /srv/faiss-db ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
    )
    harness = tmp_path / "loader.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "CHECK_ONLY=0\n"
        f"REPO_DIR={shlex.quote(str(tmp_path))}\n"
        f"ENV_FILE={shlex.quote(str(compose_env))}\n"
        f"SAFE_ENV_BUNDLE_HELPER={shlex.quote(str(helper))}\n"
        f"SAFE_ENV_BUNDLE_DIR={shlex.quote(str(bundle))}\n"
        f"SAFE_CANDIDATE_SHA={'a' * 40}\n"
        "SAFE_DEPLOYMENT_ID=deployment-test\n"
        f"SAFE_ENV_MANIFEST_SHA256={'b' * 64}\n"
        "die() { printf '%s\\n' \"$*\" >&2; exit 1; }\n"
        f"{functions}"
        "load_compose_env\n"
        "printf '%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n' \"$AGENTIUM_ENV_FILE\" "
        "\"$AGENTIUM_POSTGRES_DB\" \"$AGENTIUM_POSTGRES_USER\" \"$BACKEND_PORT\" "
        "\"$FRONTEND_PORT\" \"$IMAGE_TAG\"\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["bash", str(harness)],
        check=True,
        env=_polluted_environment(),
        text=True,
        capture_output=True,
    )

    assert completed.stdout.strip().split("\t") == [
        str(application_env),
        "frozen_database",
        "frozen_user",
        "18001",
        "18081",
        "frozen-tag",
    ]
    helper_calls = helper_log.read_text(encoding="utf-8")
    assert helper_calls.count("value ") == 9
    assert "role-path " in helper_calls


def test_candidate_compose_storage_contract_is_fail_closed_and_exact() -> None:
    script = DEPLOY.read_text(encoding="utf-8")
    function = _shell_function(script, "validate_compose_storage_contract")

    assert "--profile tools --profile sftp config --format json" in function
    for service in (
        "agentium-migrate",
        "agentium-backend",
        "agentium-worker-cpu",
        "agentium-p4-maintenance",
        "agentium-sftp",
    ):
        assert f'"{service}"' in function
    for target in ("/data/object_store", "/data/secure_deposit", "/data/faiss_db"):
        assert f'"{target}"' in function
    assert "protected storage mount inventory is incomplete" in function
    assert "protected storage source or access mode differs" in function
    assert "validate_compose_storage_contract\n" in script


def test_candidate_compose_storage_contract_executes_and_rejects_drift(
    tmp_path: Path,
) -> None:
    function = _shell_function(
        DEPLOY.read_text(encoding="utf-8"), "validate_compose_storage_contract"
    )
    object_store = "/srv/agentium-data/object_store"
    secure_deposit = "/srv/secure-deposit"
    faiss = "/srv/faiss-db"
    expected = {
        "agentium-migrate": {
            "/data/object_store": (object_store, True),
            "/data/secure_deposit": (secure_deposit, True),
            "/data/faiss_db": (faiss, True),
        },
        "agentium-backend": {
            "/data/object_store": (object_store, False),
            "/data/secure_deposit": (secure_deposit, False),
            "/data/faiss_db": (faiss, True),
        },
        "agentium-worker-cpu": {
            "/data/object_store": (object_store, False),
            "/data/secure_deposit": (secure_deposit, True),
            "/data/faiss_db": (faiss, True),
        },
        "agentium-p4-maintenance": {
            "/data/object_store": (object_store, False),
            "/data/secure_deposit": (secure_deposit, True),
            "/data/faiss_db": (faiss, True),
        },
        "agentium-sftp": {"/data/secure_deposit": (secure_deposit, False)},
    }
    payload = {
        "services": {
            service: {
                "volumes": [
                    {
                        "type": "bind",
                        "source": source,
                        "target": target,
                        "read_only": read_only,
                    }
                    for target, (source, read_only) in mounts.items()
                ]
            }
            for service, mounts in expected.items()
        }
    }
    compose_json = tmp_path / "compose.json"
    repo = tmp_path / "repo"
    (repo / "docker").mkdir(parents=True)

    def run(value: dict[str, object]) -> subprocess.CompletedProcess[str]:
        compose_json.write_text(json.dumps(value), encoding="utf-8")
        harness = tmp_path / "storage-contract.sh"
        harness.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "CHECK_ONLY=0\n"
            f"REPO_DIR={shlex.quote(str(repo))}\n"
            f"COMPOSE_JSON={shlex.quote(str(compose_json))}\n"
            f"AGENTIUM_OBJECT_STORE_PATH={shlex.quote(object_store)}\n"
            f"AGENTIUM_SECURE_DEPOSIT_PATH={shlex.quote(secure_deposit)}\n"
            f"AGENTIUM_FAISS_PATH={shlex.quote(faiss)}\n"
            "dc() { cat \"$COMPOSE_JSON\"; }\n"
            "die() { printf '%s\\n' \"$*\" >&2; exit 1; }\n"
            "ok() { :; }\n"
            f"{function}"
            "validate_compose_storage_contract\n",
            encoding="utf-8",
        )
        return subprocess.run(
            ["bash", str(harness)], text=True, capture_output=True, check=False
        )

    assert run(payload).returncode == 0
    drifted = json.loads(json.dumps(payload))
    drifted["services"]["agentium-migrate"]["volumes"][0]["read_only"] = False
    rejected = run(drifted)
    assert rejected.returncode != 0
    assert "déplace ou ré-expose" in rejected.stderr
