"""Render real Helm manifests to verify dedicated queue and cgroup boundaries."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "ops/helm/agentium"
HELM = shutil.which("helm")


def render(*args):
    result = subprocess.run(
        [HELM, "template", "agentium", str(CHART), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return [value for value in yaml.safe_load_all(result.stdout) if value]


@pytest.mark.skipif(not HELM, reason="Helm is required to render deployment contracts")
def test_dedicated_worker_has_one_dataops_slot_and_4gib_2cpu():
    documents = render("-f", str(CHART / "values-dataops-showcase.yaml"))
    worker = next(row for row in documents if row["metadata"]["name"] == "agentium-worker-dataops")
    container = worker["spec"]["template"]["spec"]["containers"][0]
    env = {value["name"]: value["value"] for value in container["env"] if "value" in value}
    assert env["CELERY_QUEUES"] == "dataops" and env["CELERY_CONCURRENCY"] == "1"
    assert env["CELERY_BEAT"] == "0"
    assert container["resources"]["limits"]["memory"] == "4Gi"
    assert container["resources"]["limits"]["cpu"] == "2"
    assert env["DATAOPS_RUNNER_MEMORY_LIMIT_MB"] == "3072"
    config = next(
        row
        for row in documents
        if row["kind"] == "ConfigMap" and row["metadata"]["name"].endswith("-config")
    )
    assert "dataops" not in config["data"]["CELERY_QUEUES"].split(",")
    cron = next(row for row in documents if row["metadata"]["name"] == "agentium-dataops-watchdog")
    assert cron["spec"]["concurrencyPolicy"] == "Forbid"
    assert cron["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 120
    assert config["data"]["OBJECT_STORE_BACKEND"] == "s3"


@pytest.mark.skipif(not HELM, reason="Helm is required to render deployment contracts")
def test_shared_worker_cannot_accidentally_consume_dataops():
    result = subprocess.run(
        [
            HELM,
            "template",
            "agentium",
            str(CHART),
            "--set-string",
            r"worker.queues=cpu\,recipes\,dataops",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "worker.queues must exclude dataops" in result.stderr
