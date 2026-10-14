"""File transports keep bearer auth at its declared origin and freeze identity."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app.services.connectors.adapters import file_http
from app.services.connectors.adapters.sql import AdapterError


def deadline():
    return (datetime.now(UTC) + timedelta(minutes=1)).isoformat()


def graph(monkeypatch):
    return file_http.GraphFiles(
        {"drive_id": "drive-1", "prefix": "approved", "download_hosts": ["files.example.test"]},
        {"access_token": "fixture-bearer"},
        deadline(),
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1.0/drives/drive-1/items/a",
        "https://graph.microsoft.com/v1.0/drives/drive-2/items/a",
        "https://graph.microsoft.com/v1.0/drives/drive-1/items/../../drive-2/items/a",
        "https://graph.microsoft.com/v1.0/drives/drive-1/items/%2e%2e/../../me",
    ],
)
def test_graph_rejects_changed_origin_drive_and_path_traversal(monkeypatch, url):
    client = graph(monkeypatch)
    monkeypatch.setattr(
        file_http.http, "json_request", lambda *a, **kw: pytest.fail("must reject before request")
    )
    with pytest.raises(AdapterError, match="CONNECTOR_PAGINATION_INVALID"):
        client._get(url)


def test_graph_signed_download_never_gets_graph_token(monkeypatch, tmp_path):
    client = graph(monkeypatch)
    calls = []
    metadata = {
        "eTag": "v1",
        "@microsoft.graph.downloadUrl": "https://files.example.test/file.csv?signature=fixture",
    }
    monkeypatch.setattr(client, "_get", lambda url: metadata)

    def download(url, path, **kw):
        calls.append((url, kw))
        path.write_bytes(b"a\n1\n")
        return {}, 4, hashlib.sha256(path.read_bytes()).hexdigest()

    monkeypatch.setattr(file_http.http, "download", download)
    client.download({"id": "abc", "etag": "v1", "size": 4}, tmp_path / "object", 100)
    assert "headers" not in calls[0][1] and "fixture-bearer" not in str(calls)
    metadata["@microsoft.graph.downloadUrl"] = "https://unapproved.example/file.csv"
    with pytest.raises(AdapterError, match="CONNECTOR_DOWNLOAD_ORIGIN_DENIED"):
        client.download({"id": "abc", "etag": "v1", "size": 4}, tmp_path / "object", 100)


def test_graph_fails_if_metadata_changes_after_download(monkeypatch, tmp_path):
    client = graph(monkeypatch)
    versions = iter(
        [
            {"eTag": "v1", "@microsoft.graph.downloadUrl": "https://files.example.test/f.csv"},
            {"eTag": "v2"},
        ]
    )
    monkeypatch.setattr(client, "_get", lambda url: next(versions))
    monkeypatch.setattr(file_http.http, "download", lambda *a, **kw: ({}, 4, "a" * 64))
    with pytest.raises(AdapterError, match="CONNECTOR_SOURCE_CHANGED"):
        client.download({"id": "abc", "etag": "v1", "size": 4}, tmp_path / "object", 100)


def test_http_file_requires_size_and_checks_conditional_etag(monkeypatch, tmp_path):
    client = file_http.HTTPFile({"url": "https://files.example.test/f.csv"}, {}, deadline())
    monkeypatch.setattr(file_http.http, "request", lambda *a, **kw: ({}, b""))
    with pytest.raises(AdapterError, match="CONNECTOR_SOURCE_SIZE_REQUIRED"):
        client.manifest()
    monkeypatch.setattr(
        file_http.http, "request", lambda *a, **kw: ({"content-length": "4", "etag": "v1"}, b"")
    )
    item = client.manifest()[0]
    calls = []
    monkeypatch.setattr(
        file_http.http,
        "download",
        lambda *a, **kw: calls.append(kw) or ({"etag": "v2"}, 4, "a" * 64),
    )
    with pytest.raises(AdapterError, match="CONNECTOR_SOURCE_CHANGED"):
        client.download(item, tmp_path / "object", 100)
    assert calls[0]["headers"]["If-Match"] == "v1"
