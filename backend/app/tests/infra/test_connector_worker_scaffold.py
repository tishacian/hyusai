"""Exercise C0 queue isolation with rendered deployments, without a broker."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "ops/helm/agentium"
IMAGE = "example.invalid/connector-runner@sha256:" + "a" * 64
POOLS = {
    "agentium-worker-connectors": "connectors",
    "agentium-worker-connectors-interactive": "connectors_interactive",
}


def _helm(*args):
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("Helm is required for rendered deployment contracts")
    return subprocess.run(
        [helm, "template", "agentium", str(CHART), *args],
        capture_output=True,
        text=True,
    )


def test_helm_defaults_do_not_start_connector_pools():
    result = _helm()
    assert result.returncode == 0, result.stderr
    assert "name: agentium-worker-connectors" not in result.stdout


def test_helm_reserves_separate_processes_and_bounded_scratch():
    result = _helm(
        "--set", "connectorWorkers.enabled=true", "--set-string", f"connectorWorkers.image={IMAGE}"
    )
    assert result.returncode == 0, result.stderr
    pools = {
        doc["metadata"]["name"]: doc
        for doc in yaml.safe_load_all(result.stdout)
        if doc and doc["metadata"]["name"] in POOLS
    }
    assert pools.keys() == POOLS.keys()
    for name, doc in pools.items():
        spec = doc["spec"]["template"]["spec"]
        container = spec["containers"][0]
        env = {entry["name"]: entry.get("value") for entry in container["env"]}
        assert container["image"] == IMAGE
        assert env["CELERY_QUEUES"] == POOLS[name]
        assert env["CELERY_APP"] == "app.workers.celery_connectors:celery_connectors"
        assert env["CELERY_CONCURRENCY"] == "1" and env["CELERY_BEAT"] == "0"
        assert spec["volumes"][0]["emptyDir"]["sizeLimit"] == "20Gi"
        assert container["resources"]["limits"]["cpu"] == "1"


@pytest.mark.parametrize("value", ["", "example.invalid/connector-runner:latest"])
def test_helm_refuses_unqualified_image_reference(value):
    result = _helm(
        "--set", "connectorWorkers.enabled=true", "--set-string", f"connectorWorkers.image={value}"
    )
    assert result.returncode != 0
    assert "connectorWorkers.image" in result.stderr


@pytest.mark.parametrize("queue", POOLS.values())
def test_helm_general_worker_refuses_connector_queue(queue):
    result = _helm("--set-string", f"worker.queues=cpu\\,{queue}")
    assert result.returncode != 0
    assert "worker.queues must exclude connector queues" in result.stderr


def test_compose_keeps_two_pools_opt_in_with_minimal_storage(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose is required")
    app_env = tmp_path / "app.env"
    app_env.write_text("")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker/compose.agentium.yml"),
            "-f",
            str(ROOT / "docker/compose.agentium.connectors.yml"),
            "--profile",
            "connectors",
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AGENTIUM_ENV_FILE": str(app_env),
            "AGENTIUM_CONNECTOR_RUNNER_IMAGE": IMAGE,
        },
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for name, queue in POOLS.items():
        service = services[name]
        assert service["profiles"] == ["connectors"]
        assert service["image"] == IMAGE
        assert service["environment"]["CELERY_QUEUES"] == queue
        assert service["environment"]["CELERY_BEAT"] == "0"
        assert sorted(mount["target"] for mount in service["volumes"]) == ["/data/connector_scratch", "/data/object_store"]
        assert not service.get("ports")


@pytest.mark.parametrize(
    ("app", "queues", "beat", "allowed"),
    [
        ("app.workers.celery_app:celery_app", "cpu,connectors", "0", False),
        ("app.workers.celery_app:celery_app", "connectors_interactive", "0", False),
        (
            "app.workers.celery_connectors:celery_connectors",
            "connectors,connectors_interactive",
            "0",
            False,
        ),
        ("app.workers.celery_connectors:celery_connectors", "connectors", "1", False),
        ("app.workers.celery_connectors:celery_connectors", "connectors", "0", True),
        ("app.workers.celery_connectors:celery_connectors", "connectors_interactive", "0", True),
        ("app.workers.celery_app:celery_app", "cpu,recipes", "0", True),
    ],
)
def test_worker_launcher_enforces_pool_boundary(tmp_path, app, queues, beat, allowed):
    # Stub only process execution: the real launcher decides whether to start.
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o755)
    result = subprocess.run(
        ["sh", str(ROOT / "run_celery.sh")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "CELERY_APP": app,
            "CELERY_QUEUES": queues,
            "CELERY_BEAT": beat,
        },
    )
    assert (result.returncode == 0) is allowed, result.stderr


def test_vm_bundle_treats_connectors_as_optional_but_checks_present_mounts():
    spec = importlib.util.spec_from_file_location(
        "connector_env_contract", ROOT / "scripts/agentium_runtime_env_bundle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in POOLS:
        assert name in module.VM_OPTIONAL_PROFILE_SERVICES
        assert module.VM_APPLICATION_STORAGE_MOUNTS[name] == {
            "/data/object_store": ("AGENTIUM_OBJECT_STORE_PATH", False),
            "/data/connector_scratch": ("AGENTIUM_CONNECTOR_SCRATCH_PATH", False),
        }


@pytest.mark.parametrize(
    ("size", "revision", "expected"),
    [
        (104857600, "a" * 40, 0),
        (104857601, "a" * 40, 1),
        (104857600, "b" * 40, 1),
        (104857600, "unknown", 1),
        ("bad", "a" * 40, 1),
    ],
)
def test_vm_refuses_wrong_revision_or_unqualified_size(tmp_path, size, revision, expected):
    script = (ROOT / "scripts/agentium-vm-deploy.sh").read_text()
    function = re.search(r"(?ms)^connector_image_check\(\) \{\n.*?^\}", script).group()
    harness = tmp_path / "image-check.sh"
    harness.write_text(
        "set -eu\nCONNECTORS=1\nCONNECTOR_IMAGE=test\nCONNECTOR_BUDGET=100\nR=/unused\nTAG=aaaaaaaaaaaa\n"
        'fail() { echo "$*" >&2; exit 1; }\n'
        'readonly_docker() { case "$*" in *Size*) echo "$FAKE_SIZE" ;; *agentium-backend:*) echo "$EXPECTED_REVISION" ;; *) echo "$FAKE_REVISION" ;; esac; }\n'
        'git() { echo "$WORKTREE_REVISION"; }\n' + function + "\nconnector_image_check\n"
    )
    result = subprocess.run(
        ["bash", str(harness)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FAKE_SIZE": str(size),
            "FAKE_REVISION": revision,
            "EXPECTED_REVISION": "a" * 40,
            "WORKTREE_REVISION": "c" * 40,
        },
    )
    assert result.returncode == expected, result.stderr


@pytest.mark.parametrize("budget,expected", [("", 1), ("99", 1), ("100", 0)])
def test_connector_image_budget_requires_a_measured_ceiling(tmp_path, budget, expected):
    docker = tmp_path / "docker"
    docker.write_text(
        '#!/bin/sh\n[ "$1 $2" = "image inspect" ] || exit 2\nshift 2\n'
        '[ "$1" = --format ] && shift 2\n[ $# -eq 1 ] || exit 1\n'
        "echo 104857600\n"
    )
    docker.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/agentium-image-budget.sh"), "abc123def456"],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "AGENTIUM_CONNECTOR_RUNNER_IMAGE": IMAGE,
            "AGENTIUM_IMAGE_BUDGET_MB_CONNECTOR_RUNNER": budget,
        },
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert IMAGE in result.stdout
