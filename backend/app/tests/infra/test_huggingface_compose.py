"""Validate the rendered opt-in topology, including Compose inheritance."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def test_hub_writer_and_offline_readers_have_separate_mounts_and_credentials(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI is unavailable")
    version = subprocess.run(["docker", "compose", "version"], capture_output=True)
    if version.returncode:
        pytest.skip("Docker Compose plugin is unavailable")
    app_env = tmp_path / "app.env"
    hub_env = tmp_path / "hub.env"
    app_env.write_text("HF_S3_ACCESS_KEY=test-reader\nHF_S3_SECRET_KEY=test-reader-secret\n")
    hub_env.write_text("HF_S3_ACCESS_KEY=test-writer\nHF_S3_SECRET_KEY=test-writer-secret\n")
    environment = {
        **os.environ,
        "AGENTIUM_ENV_FILE": str(app_env),
        "AGENTIUM_HUB_ENV_FILE": str(hub_env),
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker/compose.agentium.yml"),
            "-f",
            str(ROOT / "docker/compose.agentium.huggingface.yml"),
            "--profile",
            "huggingface",
            "--profile",
            "ml-deep",
            "--profile",
            "tools",
            "config",
            "--format",
            "json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    readers = (
        "agentium-backend",
        "agentium-worker-cpu",
        "agentium-worker-ml-deep",
        "agentium-worker-ml-deep-serve",
    )
    for name in (*readers, "agentium-hub-fetch"):
        service = services[name]
        mounts = {item["target"]: item for item in service["volumes"]}
        cache = mounts["/data/hub-cache"]
        assert cache["source"] == environment.get(
            "AGENTIUM_HUB_CACHE_PATH", "/srv/agentium-data/hub-cache"
        )
        assert cache.get("read_only", False) == (name in readers)
        assert cache.get("bind", {}).get("create_host_path", False) is False
        assert service["environment"]["HF_S3_ACCESS_KEY"] == (
            "test-reader" if name in readers else "test-writer"
        )
        if name in readers:
            assert service["environment"]["HF_HUB_OFFLINE"] == "1"
        if name not in readers[2:]:
            assert not mounts["/data/hub-bundles"].get("read_only", False)
    assert services["agentium-hub-fetch"]["environment"]["CELERY_QUEUES"] == "hub_fetch"
    assert services["agentium-hub-fetch"]["environment"]["CELERY_BEAT"] == "0"
    for name in ("agentium-backend", "agentium-migrate", "agentium-worker-cpu"):
        assert services[name]["build"]["args"]["INSTALL_HF_RAG"] == "1"
