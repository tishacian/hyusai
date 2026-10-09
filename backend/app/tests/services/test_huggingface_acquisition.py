"""Acquisition verifies Git/LFS bytes, immutable publication and safe redirects."""

import hashlib
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from app.services.huggingface.client import HFClient
from app.services.huggingface.connection import Connection
from app.services.huggingface.errors import HFError
from app.services.huggingface.fetch import stream_file
from app.services.huggingface.storage import PART_BYTES, HubStore


def expected(content, algorithm="sha256"):
    digest = (
        hashlib.sha256(content).hexdigest()
        if algorithm == "sha256"
        else hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    )
    return {"size_bytes": len(content), "upstream_hash": {"algorithm": algorithm, "value": digest}}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    return HubStore()


@pytest.mark.parametrize("algorithm", ["sha256", "git-blob-sha1"])
def test_verified_publication_and_existing_selection_share_bytes(store, algorithm):
    content = b'{"model_type":"bert"}'
    entry = store.publish_verified(
        "hub/blobs/model/config.json",
        [content[:3], content[3:]],
        expected(content, algorithm),
        max_bytes=100,
    )
    assert entry["sha256"] == hashlib.sha256(content).hexdigest()

    def must_not_download():
        raise AssertionError("A verified shared file must not download again")
        yield b""

    assert (
        store.publish_verified(
            "hub/blobs/model/config.json",
            must_not_download(),
            expected(content, algorithm),
            max_bytes=100,
        )
        == entry
    )


def test_checksum_and_overflow_never_publish_or_leave_temporary_files(store, tmp_path):
    with pytest.raises(HFError, match="source checksum"):
        store.publish_verified("hub/blobs/bad", [b"wrong"], expected(b"right"), max_bytes=10)
    with pytest.raises(HFError, match="admitted byte length"):
        store.publish_verified("hub/blobs/large", [b"too many"], expected(b"ok"), max_bytes=10)
    assert not store.exists("hub/blobs/bad")
    assert not store.exists("hub/blobs/large")
    assert not list(tmp_path.rglob(".hf-part-*"))


def test_existing_published_key_is_never_replaced(store):
    store.publish_verified("hub/blobs/file", [b"good"], expected(b"good"), max_bytes=10)
    with pytest.raises(HFError):
        store.publish_verified("hub/blobs/file", [b"evil"], expected(b"evil"), max_bytes=10)
    with store.open("hub/blobs/file") as stream:
        assert stream.read() == b"good"


class S3Fake:
    def __init__(self):
        self.parts, self.completed, self.aborted = [], [], []

    def head_object(self, **kwargs):
        error = RuntimeError("not found")
        error.response = {"Error": {"Code": "NoSuchKey"}}
        raise error

    def create_multipart_upload(self, **kwargs):
        return {"UploadId": "upload"}

    def upload_part(self, **kwargs):
        self.parts.append(kwargs)
        return {"ETag": "part"}

    def complete_multipart_upload(self, **kwargs):
        self.completed.append(kwargs)

    def abort_multipart_upload(self, **kwargs):
        self.aborted.append(kwargs)


def test_multipart_bounds_parts_and_checks_before_conditional_completion(monkeypatch):
    monkeypatch.setattr(settings, "object_store_s3_bucket", "test")
    fake = S3Fake()
    store = HubStore(SimpleNamespace(backend="s3"), s3_client=fake)
    content = b"x" * (PART_BYTES + 31)
    store.publish_verified("hub/blobs/model", [content], expected(content), max_bytes=len(content))
    assert [len(part["Body"]) for part in fake.parts] == [PART_BYTES, 31]
    assert fake.completed[0]["IfNoneMatch"] == "*"
    assert not fake.aborted
    bad = S3Fake()
    with pytest.raises(HFError):
        HubStore(SimpleNamespace(backend="s3"), s3_client=bad).publish_verified(
            "hub/blobs/bad", [content], expected(b"y" * len(content)), max_bytes=len(content)
        )
    assert bad.aborted and not bad.completed


def test_physical_delete_removes_all_versions_but_not_neighbor_keys(monkeypatch):
    monkeypatch.setattr(settings, "object_store_s3_bucket", "test")
    deleted = []
    response = {
        "Versions": [
            {"Key": "hub/blobs/a", "VersionId": "v1"},
            {"Key": "hub/blobs/ab", "VersionId": "neighbor"},
        ],
        "DeleteMarkers": [{"Key": "hub/blobs/a", "VersionId": "marker"}],
    }
    client = SimpleNamespace(
        get_paginator=lambda _: SimpleNamespace(paginate=lambda **kw: [response]),
        delete_object=lambda **kw: deleted.append(kw),
    )
    HubStore(SimpleNamespace(backend="s3"), s3_client=client).delete("hub/blobs/a")
    assert {item["VersionId"] for item in deleted} == {"v1", "marker"}
    assert all(item["Key"] == "hub/blobs/a" for item in deleted)


def test_recovery_cleans_only_abandoned_temporary_sources(store, tmp_path):
    import os
    from datetime import UTC, datetime, timedelta

    for job in ("active", "expired"):
        store.publish_verified(
            f"hub/tmp/{job}/data", [b"source"], expected(b"source"), max_bytes=10
        )
        path = store.store._local_path(f"hub/tmp/{job}/data")
        os.utime(path, (0, 0))
    store.publish_verified("hub/blobs/model", [b"source"], expected(b"source"), max_bytes=10)
    assert (
        store.cleanup_abandoned_sources(
            active_job_ids={"active"}, older_than=datetime.now(UTC) - timedelta(hours=1)
        )
        == 1
    )
    assert store.exists("hub/tmp/active/data") and store.exists("hub/blobs/model")
    assert not store.exists("hub/tmp/expired/data")


def test_hub_download_strips_token_at_cdn_and_pins_sha():
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302, headers={"location": "https://cdn-lfs.huggingface.co/signed"}
            )
        return httpx.Response(200, content=b"model")

    client = HFClient(Connection(token="private-token"), transport=httpx.MockTransport(respond))
    assert (
        b"".join(
            stream_file(
                client,
                {"kind": "model", "repo_id": "org/model", "revision": "a" * 40},
                "model.safetensors",
            )
        )
        == b"model"
    )
    assert requests[0].headers["authorization"] == "Bearer private-token"
    assert "authorization" not in requests[1].headers
    assert f"/resolve/{'a' * 40}/" in str(requests[0].url)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/model",
        "http://cdn-lfs.huggingface.co/model",
        "https://cdn-lfs.huggingface.co.evil.example/model",
        "https://user:pass@cdn-lfs.huggingface.co/file",
        "https://cdn-lfs.huggingface.co:8443/model",
    ],
)
def test_download_rejects_untrusted_redirect_before_sending_request(url):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": url})

    client = HFClient(Connection(token="private-token"), transport=httpx.MockTransport(respond))
    with pytest.raises(HFError) as error:
        list(
            stream_file(
                client,
                {"kind": "model", "repo_id": "org/model", "revision": "a" * 40},
                "model.safetensors",
            )
        )
    assert error.value.code == "HF_REDIRECT_FORBIDDEN"
    assert len(requests) == 1
