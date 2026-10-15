"""Render control-plane scaffolds and exercise the real launcher without a broker."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "ops/helm/agentium"
FLAGS = ("ACTIVITY_OBSERVABILITY_ENABLED", "EXECUTION_CONTROL_ENABLED", "EXECUTION_DURABLE_DISPATCH_ENABLED")
CONTROL_APP = "app.workers.execution_control:app"


def helm(*args):
    binary = shutil.which("helm")
    if not binary:
        pytest.skip("Helm is required to render the control-plane contract")
    return subprocess.run([binary, "template", "agentium", str(CHART), *args], capture_output=True, text=True)


def documents(*args):
    result = helm(*args)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def test_default_chart_has_no_control_process_and_all_flags_are_off():
    rendered = documents()
    assert not any(doc["metadata"]["name"].endswith("-control") for doc in rendered)
    config = next(doc["data"] for doc in rendered if doc["kind"] == "ConfigMap" and doc["metadata"]["name"].endswith("-config"))
    assert all(config[flag] == "false" for flag in FLAGS)
    assert config["EXECUTION_CANARY_WORKSPACES"] == "showcase"
    example = (ROOT / "docker/env/agentium.env.example").read_text()
    assert all(f"{flag}=false\n" in example for flag in FLAGS)
    assert "EXECUTION_CANARY_WORKSPACES=showcase\n" in example


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.parametrize("value", ["true", "1"])
def test_enabling_a_feature_without_control_capacity_is_refused(flag, value):
    result = helm("--set-string", f"config.{flag}={value}")
    assert result.returncode != 0
    assert "requires executionControl.enabled" in result.stderr


@pytest.mark.parametrize("queues", ["control", "cpu,control", "cpu, control"])
def test_general_worker_cannot_consume_control(queues):
    escaped = queues.replace(",", "\\,")
    result = helm("--set-string", f"worker.queues={escaped}")
    assert result.returncode != 0
    assert "worker.queues must exclude control" in result.stderr


def assert_process(container, process):
    command = container["command"]
    assert command[:5] == ["python", "-m", "celery", "-A", CONTROL_APP]
    if process == "worker":
        assert command[5:12] == ["worker", "-Q", "control", "-c", "1", "--pool", "solo"]
        assert "--beat" not in command
    else:
        assert command[5:8] == ["beat", "--max-interval", "1"]
        assert command[command.index("--schedule") + 1].startswith("/tmp/")


def test_helm_control_has_independent_processes_and_no_artifact_mount():
    rendered = documents("--set", "executionControl.enabled=true", "--set-string", "config.EXECUTION_CONTROL_ENABLED=true")
    for process, memory in [("worker", "512Mi"), ("scheduler", "256Mi")]:
        deployment = next(doc for doc in rendered if doc["metadata"]["name"] == f"agentium-{process}-control")
        spec = deployment["spec"]
        assert spec["replicas"] == 1 and spec["strategy"]["type"] == "Recreate"
        container = spec["template"]["spec"]["containers"][0]
        assert_process(container, process)
        assert container["resources"]["limits"]["memory"] == memory
        assert container["resources"]["limits"]["cpu"]
        assert container["resources"]["requests"]["cpu"]
        assert [mount["mountPath"] for mount in container["volumeMounts"]] == ["/tmp"]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        environment = {entry["name"]: entry.get("value") for entry in container["env"]}
        assert environment["CELERY_QUEUES"] == "control"
        assert environment["CELERY_CONTROL_QUEUE"] == "control"
        assert environment["CELERY_BEAT"] == "0"


def test_compose_overlay_reserves_opt_in_worker_and_single_scheduler(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose is required for the rendered contract")
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    base = ["docker", "compose", "-f", str(ROOT / "docker/compose.agentium.yml"), "-f", str(ROOT / "docker/compose.agentium.execution.yml")]
    environment = {**os.environ, "AGENTIUM_ENV_FILE": str(env_file), "AGENTIUM_IMAGE_TAG": "qualified-revision"}
    disabled = subprocess.run([*base, "config", "--format", "json"], env=environment, text=True, capture_output=True)
    assert disabled.returncode == 0, disabled.stderr
    assert not any(name.endswith("-control") for name in json.loads(disabled.stdout)["services"])
    result = subprocess.run([*base, "--profile", "execution-control", "config", "--format", "json"], env=environment, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for process, memory in [("worker", 512 * 1024**2), ("scheduler", 256 * 1024**2)]:
        service = services[f"agentium-{process}-control"]
        assert_process(service, process)
        assert service["profiles"] == ["execution-control"]
        assert service["image"] == "agentium-worker:qualified-revision"
        assert int(service["mem_limit"]) == memory and float(service["cpus"]) > 0
        assert service["read_only"] is True
        assert not service.get("ports") and not service.get("volumes")
        assert service["environment"]["CELERY_CONTROL_QUEUE"] == "control"
        assert set(service["depends_on"]) == {"agentium-rabbitmq"}


@pytest.mark.parametrize(("app", "queues", "concurrency", "beat", "pool", "allowed"), [
    ("app.workers.celery_app:celery_app", "cpu,control", "2", "0", "", False),
    ("app.workers.celery_app:celery_app", "cpu, control", "2", "0", "", False),
    ("app.workers.celery_app:celery_app", "cpu,recipes", "2", "1", "", True),
    (CONTROL_APP, "control", "1", "0", "solo", True),
    (CONTROL_APP, "control", "1", "0", "", True),
    (CONTROL_APP, "cpu,control", "1", "0", "solo", False),
    (CONTROL_APP, "control", "2", "0", "solo", False),
    (CONTROL_APP, "control", "1", "1", "solo", False),
    (CONTROL_APP, "control", "1", "0", "prefork", False),
])
def test_launcher_refuses_mixed_control_pool(tmp_path, app, queues, concurrency, beat, pool, allowed):
    executable = tmp_path / "python"
    executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    executable.chmod(0o755)
    result = subprocess.run(["sh", str(ROOT / "run_celery.sh")], text=True, capture_output=True,
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "CELERY_APP": app, "CELERY_QUEUES": queues,
             "CELERY_CONCURRENCY": concurrency, "CELERY_BEAT": beat, "CELERY_POOL": pool})
    assert (result.returncode == 0) is allowed, result.stderr
    if allowed and app == CONTROL_APP:
        assert "--pool\nsolo\n" in result.stdout
