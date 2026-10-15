"""Render the opt-in native candidate without claiming its image was qualified."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
IMAGE = "registry.example/agentium-orchestration@sha256:" + "a" * 64


def render(tmp_path, *profiles, supplied=True):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose required for scaffold rendering")
    env_file = tmp_path / "disabled.env"
    env_file.write_text("EXECUTION_TEMPORAL_ENABLED=false\nEXECUTION_CANARY_WORKSPACES=showcase\n")
    environment = {**os.environ, "AGENTIUM_ENV_FILE": str(env_file)}
    for key in ("AGENTIUM_ORCHESTRATION_IMAGE", "EXECUTION_TEMPORAL_ADDRESS"):
        environment.pop(key, None)
    if supplied:
        environment.update(
            AGENTIUM_ORCHESTRATION_IMAGE=IMAGE, EXECUTION_TEMPORAL_ADDRESS="temporal.example:7233"
        )
    args = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "docker/compose.agentium.yml"),
        "-f",
        str(ROOT / "docker/compose.agentium.execution.yml"),
        "-f",
        str(ROOT / "docker/compose.agentium.temporal.yml"),
    ]
    for profile in profiles:
        args += ["--profile", profile]
    return subprocess.run(
        [*args, "config", "--format", "json"], env=environment, capture_output=True, text=True
    )


def test_optional_runtime_requires_explicit_image_address_and_control_profile(tmp_path):
    missing = render(tmp_path, "execution-control", "execution-temporal", supplied=False)
    assert missing.returncode != 0
    assert (
        "AGENTIUM_ORCHESTRATION_IMAGE" in missing.stderr
        or "EXECUTION_TEMPORAL_ADDRESS" in missing.stderr
    )
    disabled = render(tmp_path)
    assert disabled.returncode == 0, disabled.stderr
    assert not any("orchestration" in name for name in json.loads(disabled.stdout)["services"])
    incomplete = render(tmp_path, "execution-temporal")
    assert incomplete.returncode != 0
    assert "control" in incomplete.stderr


def test_native_starter_and_temporal_worker_are_separate_and_do_not_enable_admission(tmp_path):
    result = render(tmp_path, "execution-control", "execution-temporal")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    starter = services["agentium-orchestration-starter"]
    worker = services["agentium-orchestration-worker"]
    assert starter["command"][:12] == [
        "python",
        "-m",
        "celery",
        "-A",
        "app.workers.temporal_execution:app",
        "worker",
        "-Q",
        "orchestration",
        "-c",
        "1",
        "--pool",
        "solo",
    ]
    assert worker["command"] == ["python", "-m", "app.workers.temporal_execution", "worker"]
    assert not starter.get("volumes")
    mounts = {mount["target"]: mount for mount in worker["volumes"]}
    assert {
        "/data/object_store",
        "/data/secure_deposit",
        "/data/faiss_db",
        "/data/recipe_envs",
    } == set(mounts)
    assert mounts["/data/secure_deposit"]["read_only"] is True
    for service in (starter, worker):
        assert service["image"] == IMAGE
        assert service["profiles"] == ["execution-temporal"]
        assert service["read_only"] is True and not service.get("ports")
        assert int(service["mem_limit"]) > 0 and float(service["cpus"]) > 0
        assert service["environment"]["EXECUTION_TEMPORAL_ENABLED"] == "false"
        assert service["environment"]["EXECUTION_TEMPORAL_TLS"] == "true"
        assert service["environment"]["CELERY_BEAT"] == "0"
        assert len(service["tmpfs"]) == 1
        assert set(service["depends_on"]) == {
            "agentium-rabbitmq",
            "agentium-worker-control",
            "agentium-scheduler-control",
        }
    assert not any(
        service.get("image", "").startswith("temporalio/") for service in services.values()
    )


@pytest.mark.parametrize(
    ("expected", "actual", "allowed"),
    [
        ("a" * 40, "a" * 40, True),
        ("a" * 40, "b" * 40, False),
        ("unknown", "unknown", False),
        ("", "a" * 40, False),
        ("short", "short", False),
    ],
)
def test_image_build_guard_executes_against_the_inherited_revision(expected, actual, allowed):
    dockerfile = (ROOT / "docker/Dockerfile.agentium-orchestration").read_text()
    line = next(line for line in dockerfile.splitlines() if line.startswith("RUN python -c "))
    guard = shlex.split(line.removeprefix("RUN "))[2]
    result = subprocess.run(
        [sys.executable, "-c", guard],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "EXPECTED_WORKER_REVISION": expected,
            "AGENTIUM_IMAGE_REVISION": actual,
            "PYTHONOPTIMIZE": "1",
        },
    )
    assert (result.returncode == 0) is allowed
    assert "ENV AGENTIUM_IMAGE_REVISION" not in dockerfile


def test_optional_image_keeps_sdk_and_source_separate_from_base_requirements():
    optional = [
        line.strip()
        for line in (ROOT / "backend/requirements_temporal.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert optional == ["temporalio==1.34.0"]
    assert "temporalio" not in (ROOT / "backend/requirements.txt").read_text().lower()
    dockerfile = (ROOT / "docker/Dockerfile.agentium-orchestration").read_text()
    assert "FROM ${WORKER_BASE_IMAGE}" in dockerfile
    assert "--system-site-packages /opt/agentium-temporal" in dockerfile
    assert "--constraint=/tmp/temporal-requirements/constraints-demo-app.txt" in dockerfile
    assert "--constraint=/tmp/temporal-requirements/constraints-temporal.txt" in dockerfile
    pins = [
        line
        for line in (ROOT / "backend/constraints-temporal.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert pins == ["temporalio==1.34.0", "nexus-rpc==1.4.0", "types-protobuf==7.35.1.20260906"]
    assert "COPY ." not in dockerfile and "COPY backend/app" not in dockerfile


@pytest.mark.parametrize(
    ("app", "queues", "pool", "concurrency", "beat", "allowed"),
    [
        ("app.workers.celery_app:celery_app", "cpu,orchestration", "", "2", "0", False),
        ("app.workers.celery_app:celery_app", "cpu, orchestration", "", "2", "0", False),
        ("app.workers.temporal_execution:app", "orchestration", "", "1", "0", True),
        ("app.workers.temporal_execution:app", "orchestration", "solo", "1", "0", True),
        ("app.workers.temporal_execution:app", "orchestration,cpu", "solo", "1", "0", False),
        ("app.workers.temporal_execution:app", "orchestration", "solo", "2", "0", False),
        ("app.workers.temporal_execution:app", "orchestration", "solo", "1", "1", False),
        ("app.workers.temporal_execution:app", "orchestration", "prefork", "1", "0", False),
    ],
)
def test_launcher_preserves_the_independent_orchestration_pool(
    tmp_path, app, queues, pool, concurrency, beat, allowed
):
    executable = tmp_path / "python"
    executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    executable.chmod(0o755)
    result = subprocess.run(
        ["sh", str(ROOT / "run_celery.sh")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "CELERY_APP": app,
            "CELERY_QUEUES": queues,
            "CELERY_POOL": pool,
            "CELERY_CONCURRENCY": concurrency,
            "CELERY_BEAT": beat,
            "CELERY_ORCHESTRATION_QUEUE": "orchestration",
        },
    )
    assert (result.returncode == 0) is allowed, result.stderr
    if allowed:
        assert "--pool\nsolo\n" in result.stdout and "--beat" not in result.stdout


@pytest.mark.parametrize(
    ("queues", "name"),
    [
        ("orchestration", "orchestration"),
        ("cpu, orchestration", "orchestration"),
        ("cpu,custom_native", "custom_native"),
    ],
)
def test_chart_general_worker_cannot_steal_orchestration_tasks(queues, name):
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("Helm required to validate rendered queue isolation")
    result = subprocess.run(
        [
            helm,
            "template",
            "agentium",
            str(ROOT / "ops/helm/agentium"),
            "--set-string",
            "worker.queues=" + queues.replace(",", "\\,"),
            "--set-string",
            "config.CELERY_ORCHESTRATION_QUEUE=" + name,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "worker.queues must exclude orchestration" in result.stderr
