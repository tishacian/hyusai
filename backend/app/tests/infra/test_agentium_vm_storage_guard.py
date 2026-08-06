from __future__ import annotations

import importlib.util
import os
import re
import shlex
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "scripts" / "agentium_runtime_env_bundle.py"
LAUNCHER = ROOT / "scripts" / "agentium-vm-deploy.sh"
BASE_COMPOSE = ROOT / "docker" / "compose.agentium.yml"
VM_OVERLAY = ROOT / "docker" / "compose.agentium.vm-runtime.yml"
LOCAL_OVERLAY = ROOT / "docker" / "compose.agentium.local-storage.yml"

EXPECTED_ENV = {
    "AGENTIUM_MINIO_VOLUME": "agentium_minio_block",
    "AGENTIUM_MINIO_VOLUME_EXTERNAL": "true",
    "AGENTIUM_QDRANT_VOLUME": "agentium_qdrant_block",
    "AGENTIUM_QDRANT_SNAPSHOT_PATH": "/srv/agentium-data/qdrant-snapshots",
}


def _module():
    spec = importlib.util.spec_from_file_location("agentium_vm_storage_guard_test", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _compose_model() -> dict:
    return {
        "services": {
            "agentium-minio": {
                "volumes": [
                    {
                        "type": "volume",
                        "source": "agentium_minio",
                        "target": "/data",
                        "read_only": False,
                    }
                ]
            },
            "agentium-qdrant": {
                "volumes": [
                    {
                        "type": "volume",
                        "source": "qdrant_data",
                        "target": "/qdrant/storage",
                        "read_only": False,
                    },
                    {
                        "type": "bind",
                        "source": "/srv/agentium-data/qdrant-snapshots",
                        "target": "/qdrant/snapshots",
                        "read_only": False,
                    },
                ]
            },
        },
        "volumes": {
            "agentium_minio": {
                "name": "agentium_minio_block",
                "external": True,
            },
            "qdrant_data": {
                "name": "agentium_qdrant_block",
                "external": True,
            },
        },
    }


def _active_containers() -> list[dict]:
    return [
        {
            "Name": "/agentium-minio",
            "State": {"Running": True},
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": "agentium_minio_block",
                    "Destination": "/data",
                    "RW": True,
                }
            ],
        },
        {
            "Name": "/qdrant",
            "State": {"Running": True},
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": "agentium_qdrant_block",
                    "Destination": "/qdrant/storage",
                    "RW": True,
                },
                {
                    "Type": "bind",
                    "Source": "/srv/agentium-data/qdrant-snapshots",
                    "Destination": "/qdrant/snapshots",
                    "RW": True,
                },
            ],
        },
    ]


@pytest.mark.parametrize("key", sorted(EXPECTED_ENV))
@pytest.mark.parametrize("failure", ["absent", "false"])
def test_production_storage_environment_fails_closed(key: str, failure: str) -> None:
    module = _module()
    values = dict(EXPECTED_ENV)
    if failure == "absent":
        del values[key]
    else:
        values[key] = "polluted-value"
    content = "".join(f"{name}={value}\n" for name, value in values.items()).encode()

    with pytest.raises(module.RuntimeEnvBundleError, match="block-backed contract"):
        module.assert_vm_storage_environment(content)


def test_rendered_compose_requires_literal_block_volumes_and_snapshot_bind() -> None:
    module = _module()
    model = _compose_model()
    module.assert_vm_compose_storage(model)

    root_local = deepcopy(model)
    root_local["volumes"]["agentium_minio"]["name"] = "agentium_minio"
    with pytest.raises(module.RuntimeEnvBundleError, match="volume contract"):
        module.assert_vm_compose_storage(root_local)

    wrong_snapshot = deepcopy(model)
    wrong_snapshot["services"]["agentium-qdrant"]["volumes"][1]["source"] = "/tmp/qdrant"
    with pytest.raises(module.RuntimeEnvBundleError, match="snapshot bind"):
        module.assert_vm_compose_storage(wrong_snapshot)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "missing or ambiguous"),
        (
            [
                {
                    "Name": "agentium_minio_block",
                    "Driver": "local",
                    "Mountpoint": "/var/lib/docker/volumes/agentium_minio_block/_data",
                    "Options": {
                        "device": "/var/lib/docker/minio",
                        "o": "bind",
                        "type": "none",
                    },
                }
            ],
            "bind options differ",
        ),
        (
            [
                {
                    "Name": "agentium_minio_block",
                    "Driver": "local",
                    "Mountpoint": "/var/lib/docker/volumes/agentium_minio/_data",
                    "Options": {
                        "device": "/srv/agentium-data/minio",
                        "o": "bind",
                        "type": "none",
                    },
                }
            ],
            "bind options differ",
        ),
    ],
)
def test_existing_volume_must_exist_with_exact_bind(payload: list[dict], message: str) -> None:
    module = _module()
    with pytest.raises(module.RuntimeEnvBundleError, match=message):
        module.assert_vm_volume_inspect(payload, volume_name="agentium_minio_block")


def test_existing_volume_and_active_mounts_accept_only_protected_identity() -> None:
    module = _module()
    module.assert_vm_volume_inspect(
        [
            {
                "Name": "agentium_minio_block",
                "Driver": "local",
                "Mountpoint": "/var/lib/docker/volumes/agentium_minio_block/_data",
                "Options": {
                    "device": "/srv/agentium-data/minio",
                    "o": "bind",
                    "type": "none",
                },
            }
        ],
        volume_name="agentium_minio_block",
    )
    module.assert_vm_active_storage_mounts(_active_containers())

    wrong = _active_containers()
    wrong[0]["Mounts"][0]["Name"] = "agentium_minio"
    with pytest.raises(module.RuntimeEnvBundleError, match="mount identity differs"):
        module.assert_vm_active_storage_mounts(wrong)


@pytest.mark.parametrize(("source", "accepted"), [("/dev/sdb", True), ("/dev/sda1", False), ("", False)])
def test_data_device_check_rejects_wrong_or_absent_dev_sdb(
    tmp_path: Path, source: str, accepted: bool
) -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    findmnt = bin_dir / "findmnt"
    findmnt.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        f"  *SOURCE*) printf '%s\\n' {shlex.quote(source)} ;;\n"
        "  *TARGET*) printf '%s\\n' /srv/agentium-data ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    findmnt.chmod(0o755)
    harness = tmp_path / "device-check.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"COMPOSE_CLEAN_PATH={shlex.quote(str(bin_dir))}:/usr/bin:/bin\n"
        "COMPOSE_CLEAN_HOME=/tmp\n"
        "DATA_ROOT=/srv/agentium-data\n"
        "EXPECTED_DATA_SOURCE=/dev/sdb\n"
        + _shell_function(script, "fail")
        + _shell_function(script, "clean_exec")
        + _shell_function(script, "assert_data_device")
        + "assert_data_device\n",
        encoding="utf-8",
    )
    result = subprocess.run(["bash", str(harness)], check=False, capture_output=True, text=True)
    assert (result.returncode == 0) is accepted


@pytest.mark.parametrize(
    ("source", "target_kind", "symlink", "accepted"),
    [
        ("/dev/sdb", "data-root", False, True),
        ("/dev/sda1", "filesystem-root", False, False),
        ("/dev/sdb", "protected-path", False, False),
        ("/dev/sdb", "data-root", True, False),
    ],
)
def test_protected_data_path_rejects_root_nested_and_symlink_backing(
    tmp_path: Path,
    source: str,
    target_kind: str,
    symlink: bool,
    accepted: bool,
) -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    data_root = tmp_path / "agentium-data"
    data_root.mkdir()
    protected = data_root / "minio"
    if symlink:
        real_path = tmp_path / "root-backed-minio"
        real_path.mkdir()
        protected.symlink_to(real_path, target_is_directory=True)
    else:
        protected.mkdir()
    targets = {
        "data-root": data_root,
        "filesystem-root": Path("/"),
        "protected-path": protected,
    }
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    findmnt = bin_dir / "findmnt"
    findmnt.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        f"  *SOURCE*) printf '%s\\n' {shlex.quote(source)} ;;\n"
        f"  *TARGET*) printf '%s\\n' {shlex.quote(str(targets[target_kind]))} ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    findmnt.chmod(0o755)
    readlink = bin_dir / "readlink"
    readlink.write_text(
        "#!/bin/sh\nfor value do :; done\nprintf '%s\\n' \"$value\"\n",
        encoding="utf-8",
    )
    readlink.chmod(0o755)
    stat = bin_dir / "stat"
    stat.write_text("#!/bin/sh\nprintf '2049\\n'\n", encoding="utf-8")
    stat.chmod(0o755)
    harness = tmp_path / "protected-path-check.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"COMPOSE_CLEAN_PATH={shlex.quote(str(bin_dir))}:/usr/bin:/bin\n"
        "COMPOSE_CLEAN_HOME=/tmp\n"
        f"DATA_ROOT={shlex.quote(str(data_root))}\n"
        "EXPECTED_DATA_SOURCE=/dev/sdb\n"
        + _shell_function(script, "fail")
        + _shell_function(script, "clean_exec")
        + _shell_function(script, "assert_protected_data_path")
        + f"assert_protected_data_path {shlex.quote(str(protected))}\n",
        encoding="utf-8",
    )
    result = subprocess.run(["bash", str(harness)], check=False, capture_output=True, text=True)
    assert (result.returncode == 0) is accepted


@pytest.mark.parametrize(
    ("source", "target_matches", "symlink", "accepted"),
    [
        ("/dev/sdb[/minio]", True, False, True),
        ("/dev/sda1[/minio]", True, False, False),
        ("/dev/sdb[/other]", True, False, False),
        ("/dev/sdb[/minio]", False, False, False),
        ("/dev/sdb[/minio]", True, True, False),
    ],
)
def test_volume_mountpoint_requires_exact_active_dev_sdb_bind(
    tmp_path: Path,
    source: str,
    target_matches: bool,
    symlink: bool,
    accepted: bool,
) -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    data_root = tmp_path / "agentium-data"
    data_root.mkdir()
    volume_root = tmp_path / "volumes"
    volume_dir = volume_root / "agentium_minio_block"
    volume_dir.mkdir(parents=True)
    mountpoint = volume_dir / "_data"
    if symlink:
        real_path = tmp_path / "root-backed-volume"
        real_path.mkdir()
        mountpoint.symlink_to(real_path, target_is_directory=True)
    else:
        mountpoint.mkdir()
    reported_target = mountpoint if target_matches else data_root
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    findmnt = bin_dir / "findmnt"
    findmnt.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        f"  *SOURCE*) printf '%s\\n' {shlex.quote(source)} ;;\n"
        f"  *TARGET*) printf '%s\\n' {shlex.quote(str(reported_target))} ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    findmnt.chmod(0o755)
    readlink = bin_dir / "readlink"
    readlink.write_text(
        "#!/bin/sh\nfor value do :; done\nprintf '%s\\n' \"$value\"\n",
        encoding="utf-8",
    )
    readlink.chmod(0o755)
    stat = bin_dir / "stat"
    stat.write_text("#!/bin/sh\nprintf '2049\\n'\n", encoding="utf-8")
    stat.chmod(0o755)
    harness = tmp_path / "volume-mountpoint-check.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"COMPOSE_CLEAN_PATH={shlex.quote(str(bin_dir))}:/usr/bin:/bin\n"
        "COMPOSE_CLEAN_HOME=/tmp\n"
        f"DATA_ROOT={shlex.quote(str(data_root))}\n"
        "EXPECTED_DATA_SOURCE=/dev/sdb\n"
        f"DOCKER_VOLUME_ROOT={shlex.quote(str(volume_root))}\n"
        + _shell_function(script, "fail")
        + _shell_function(script, "clean_exec")
        + _shell_function(script, "assert_volume_mountpoint")
        + "assert_volume_mountpoint agentium_minio_block /minio\n",
        encoding="utf-8",
    )
    result = subprocess.run(["bash", str(harness)], check=False, capture_output=True, text=True)
    assert (result.returncode == 0) is accepted


def test_vm_overlay_is_literal_and_local_storage_requires_explicit_overlay() -> None:
    base = BASE_COMPOSE.read_text(encoding="utf-8")
    vm = yaml.safe_load(VM_OVERLAY.read_text(encoding="utf-8"))
    local = yaml.safe_load(LOCAL_OVERLAY.read_text(encoding="utf-8"))

    assert "${AGENTIUM_QDRANT_VOLUME:-agentium_qdrant_block}" in base
    assert "${AGENTIUM_MINIO_VOLUME:-agentium_minio_block}" in base
    assert "${AGENTIUM_MINIO_VOLUME_EXTERNAL:-true}" in base
    assert vm["volumes"] == {
        "agentium_minio": {"external": True, "name": "agentium_minio_block"},
        "qdrant_data": {"external": True, "name": "agentium_qdrant_block"},
    }
    assert "${" not in VM_OVERLAY.read_text(encoding="utf-8")
    assert local["volumes"] == {
        "agentium_minio": {"external": False, "name": "agentium_minio"},
        "qdrant_data": {"external": False, "name": "qdrant_data"},
    }


def test_launcher_scrubs_shell_and_gates_only_closed_application_commands() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    compose = _shell_function(script, "compose")
    storage = _shell_function(script, "storage_check")

    assert "/usr/bin/env -i" in compose
    assert 'docker --host "$DOCKER_SOCKET" compose -p agentium' in compose
    assert 'clean_exec docker --host "$DOCKER_SOCKET" "$@"' in script
    for polluted in (
        "AGENTIUM_MINIO_VOLUME",
        "AGENTIUM_MINIO_VOLUME_EXTERNAL",
        "AGENTIUM_QDRANT_VOLUME",
        "AGENTIUM_QDRANT_SNAPSHOT_PATH",
        "COMPOSE_PROFILES",
        "DOCKER_HOST",
    ):
        assert f"{polluted}=" not in compose
    assert "compose --profile infra config --format json" in storage
    assert "volume inspect agentium_minio_block" in storage
    assert "volume inspect agentium_qdrant_block" in storage
    assert "inspect --type container agentium-minio qdrant" in storage
    assert "compose up" not in storage
    assert "compose run" not in storage
    assert "migrate)       storage_check; compose run --rm --no-deps agentium-migrate" in script
    assert (
        "up)            storage_check; compose up -d --no-build --no-deps "
        "agentium-backend agentium-worker-cpu agentium-frontend"
    ) in script
    for stateful in ("agentium-pg", "agentium-minio", "agentium-qdrant", "agentium-rabbitmq"):
        assert f"compose up -d {stateful}" not in script


def test_launcher_compose_gateway_drops_ambient_storage_pollution(tmp_path: Path) -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    captured = tmp_path / "environment"
    captured_args = tmp_path / "arguments"
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f"/usr/bin/env | /usr/bin/sort > {shlex.quote(str(captured))}\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(captured_args))}\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    harness = tmp_path / "compose-gateway.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"COMPOSE_CLEAN_PATH={shlex.quote(str(bin_dir))}:/usr/bin:/bin\n"
        "COMPOSE_CLEAN_HOME=/tmp\n"
        "D=/deployment\n"
        "W=/worktree/docker\n"
        "TAG=0123456789ab\n"
        "ADMIN=qdrant-private\n"
        "WORKERS=8\n"
        "DOCKER_SOCKET=unix:///var/run/docker.sock\n"
        + _shell_function(script, "compose")
        + "compose config\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "AGENTIUM_MINIO_VOLUME": "agentium_minio",
            "AGENTIUM_QDRANT_VOLUME": "qdrant_data",
            "AGENTIUM_QDRANT_SNAPSHOT_PATH": "/tmp/polluted",
            "COMPOSE_PROFILES": "infra",
            "DOCKER_HOST": "tcp://polluted.invalid:2375",
        }
    )
    subprocess.run(["bash", str(harness)], check=True, env=environment)
    effective = captured.read_text(encoding="utf-8").splitlines()
    assert "COMPOSE_PROJECT_NAME=agentium" in effective
    assert "AGENTIUM_IMAGE_TAG=0123456789ab" in effective
    assert not any("polluted" in row or row.endswith("=qdrant_data") for row in effective)
    assert captured_args.read_text(encoding="utf-8").splitlines()[:3] == [
        "--host",
        "unix:///var/run/docker.sock",
        "compose",
    ]
