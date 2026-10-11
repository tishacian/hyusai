"""Opt-in real MinIO qualification using disposable Docker containers only.

RUN_HF_MINIO_INTEGRATION=1 requires locally available MinIO and mc images.
HF_MINIO_TEST_IMAGE / HF_MINIO_TEST_MC_IMAGE can select preloaded mirrors.
No production endpoint or credential is accepted by this fixture.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.huggingface.errors import HFError
from app.services.huggingface.storage import PART_BYTES, HubStore

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HF_MINIO_INTEGRATION") != "1",
    reason="Opt-in real MinIO requires disposable Docker images; set RUN_HF_MINIO_INTEGRATION=1",
)


def _docker(*args):
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        }
    }
    result = subprocess.run(
        ["docker", "--host=unix:///var/run/docker.sock", *args],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout.strip()


@pytest.fixture()
def minio(tmp_path, monkeypatch):
    image = os.getenv("HF_MINIO_TEST_IMAGE", "minio/minio:RELEASE.2025-04-22T22-12-26Z")
    mc_image = os.getenv("HF_MINIO_TEST_MC_IMAGE", "minio/mc:RELEASE.2025-04-16T18-13-26Z")
    # Do not implicitly pull unknown images during a destructive integration
    # test. The operator first selects an available, qualified registry image.
    _docker("image", "inspect", image)
    _docker("image", "inspect", mc_image)
    identifier = "hf-minio-test-" + uuid4().hex[:12]
    network = identifier + "-net"
    bucket = "hf-artifacts-test"
    _docker("network", "create", network)
    started = False
    try:
        _docker(
            "run",
            "--detach",
            "--name",
            identifier,
            "--network",
            network,
            "--network-alias",
            "minio",
            "--publish",
            "127.0.0.1::9000",
            "--tmpfs",
            "/data:rw,size=128m",
            "--memory",
            "512m",
            "--env",
            "MINIO_ROOT_USER=hf-test-root",
            "--env",
            "MINIO_ROOT_PASSWORD=hf-test-root-private",
            image,
            "server",
            "/data",
        )
        started = True
        port = int(_docker("port", identifier, "9000/tcp").rsplit(":", 1)[1])
        endpoint = f"http://127.0.0.1:{port}"

        def client(access, secret):
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access,
                aws_secret_access_key=secret,
                region_name="us-east-1",
                config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 0}),
            )

        root = client("hf-test-root", "hf-test-root-private")
        deadline = time.monotonic() + 30
        while True:
            try:
                root.list_buckets()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        root.create_bucket(Bucket=bucket)
        root.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        script = Path(__file__).resolve().parents[4] / "scripts/agentium_hf_storage_policies.py"
        spec = importlib.util.spec_from_file_location("hf_minio_policies", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name, policy in module.policies(bucket).items():
            (tmp_path / f"{name}.json").write_text(json.dumps(policy))
        command = "\n".join(
            [
                "set -eu",
                "mc alias set hf http://minio:9000 hf-test-root hf-test-root-private >/dev/null",
                "mc admin user add hf hf-test-app hf-test-application-private >/dev/null",
                "mc admin user add hf hf-test-writer hf-test-writer-private >/dev/null",
                "mc admin policy create hf hf-app /policies/application.json >/dev/null",
                "mc admin policy create hf hf-writer /policies/hub-fetch.json >/dev/null",
                "mc admin policy attach hf hf-app --user hf-test-app >/dev/null",
                "mc admin policy attach hf hf-writer --user hf-test-writer >/dev/null",
            ]
        )
        _docker(
            "run",
            "--rm",
            "--network",
            network,
            "--entrypoint",
            "/bin/sh",
            "--mount",
            f"type=bind,src={tmp_path},dst=/policies,readonly",
            mc_image,
            "-c",
            command,
        )
        monkeypatch.setattr(settings, "object_store_backend", "s3")
        monkeypatch.setattr(settings, "object_store_s3_bucket", bucket)
        yield (
            root,
            client("hf-test-writer", "hf-test-writer-private"),
            client("hf-test-app", "hf-test-application-private"),
            bucket,
        )
    finally:
        if started:
            _docker("rm", "--force", identifier)
        _docker("network", "rm", network)


def _expected(content):
    return {
        "size_bytes": len(content),
        "upstream_hash": {"algorithm": "sha256", "value": hashlib.sha256(content).hexdigest()},
    }


def test_minio_multipart_conditional_publication_abort_and_version_purge(minio, monkeypatch):
    root, writer, _, bucket = minio
    store = HubStore(s3_client=writer)
    content = b"a" * (PART_BYTES + 19)
    expected = _expected(content)
    store.publish_verified("hub/blobs/model", [content], expected, max_bytes=len(content))
    assert root.get_object(Bucket=bucket, Key="hub/blobs/model")["Body"].read() == content
    with pytest.raises(HFError):
        store.publish_verified(
            "hub/blobs/corrupt", [content], _expected(b"b" * len(content)), max_bytes=len(content)
        )
    assert not root.list_multipart_uploads(Bucket=bucket).get("Uploads")
    root.put_object(Bucket=bucket, Key="hub/blobs/race", Body=b"winner")
    # Reproduce the race between a negative HEAD and conditional completion.
    monkeypatch.setattr(store, "exists", lambda key: False)
    with pytest.raises(HFError):
        store.publish_verified("hub/blobs/race", [b"losing"], _expected(b"losing"), max_bytes=6)
    assert root.get_object(Bucket=bucket, Key="hub/blobs/race")["Body"].read() == b"winner"
    assert not root.list_multipart_uploads(Bucket=bucket).get("Uploads")
    root.put_object(Bucket=bucket, Key="hub/blobs/model", Body=b"second version")
    store.delete("hub/blobs/model")
    versions = root.list_object_versions(Bucket=bucket, Prefix="hub/blobs/model")
    assert not versions.get("Versions") and not versions.get("DeleteMarkers")


def test_minio_application_cannot_write_models_but_can_publish_dataset_manifest(minio):
    root, writer, application, bucket = minio
    for key in ("hub/blobs/forbidden", "hub/tmp/forbidden"):
        with pytest.raises(ClientError) as error:
            application.put_object(Bucket=bucket, Key=key, Body=b"forbidden")
        assert error.value.response["Error"]["Code"] == "AccessDenied"
    writer.put_object(Bucket=bucket, Key="hub/blobs/allowed", Body=b"allowed")
    assert (
        application.get_object(Bucket=bucket, Key="hub/blobs/allowed")["Body"].read() == b"allowed"
    )
    store = HubStore(s3_client=application, use_hub_credentials=False)
    store.publish_manifest("dataset-test", {"version": 2, "artifact_id": "dataset-test"})
    assert (
        root.head_object(Bucket=bucket, Key="hub/artifacts/dataset-test/manifest.json")[
            "ContentLength"
        ]
        > 0
    )
    with pytest.raises(ClientError):
        application.delete_object(Bucket=bucket, Key="hub/blobs/allowed")
