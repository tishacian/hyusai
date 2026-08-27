from __future__ import annotations

import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "scripts" / "agentium_storage_attestation.py"


def _module():
    spec = importlib.util.spec_from_file_location("agentium_storage_attestation_unit", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _empty_snapshot(module):
    object_entries: list[dict[str, object]] = []
    object_store = {
        "files": 0,
        "bytes": 0,
        "algorithm": "sha256-merkle-v1",
        "entry_fields": ["path_sha256", "size", "content_sha256"],
        "entries": object_entries,
        "content_manifest_sha256": module._canonical_json_sha256(object_entries),
    }
    minio = module._minio_inventory_from_rows([], bucket="private")
    bucket_hash = module._identifier_sha256("private")
    faiss = {
        **deepcopy(object_store),
        "source_id_sha256": module._identifier_sha256("/srv/agentium-data/faiss"),
        "device_id": 2,
        "inode": 42,
    }
    qdrant_rows = {
        "point_manifest_algorithm": module.QDRANT_POINT_MANIFEST_ALGORITHM,
        "point_manifest_fields": module.QDRANT_POINT_MANIFEST_FIELDS,
        "read_consistency": module.QDRANT_READ_CONSISTENCY,
        "points_count_exact": 0,
        "collections": [],
        "aliases": [],
    }
    return {
        "schema_version": 1,
        "profile": module.SNAPSHOT_PROFILE,
        "secure_deposit": {"manifest_sha256": "a" * 64},
        "object_store": object_store,
        "faiss": faiss,
        "object_store_bindings": {
            "backend": {
                "backend": "s3",
                "local_path_id_sha256": None,
                "s3_bucket_id_sha256": bucket_hash,
                "s3_endpoint_id_sha256": "c" * 64,
            },
            "worker_cpu": {
                "backend": "s3",
                "local_path_id_sha256": None,
                "s3_bucket_id_sha256": bucket_hash,
                "s3_endpoint_id_sha256": "c" * 64,
            },
        },
        "minio": minio,
        "qdrant": {
            **qdrant_rows,
            "inventory_sha256": module._canonical_json_sha256(qdrant_rows),
        },
        "container_mounts": {},
        "mounts": {
            "data": {
                "source": "/dev/sdb",
                "normalized_source": "/dev/sdb",
                "expected_source": "/dev/sdb",
                "source_matches_expected": True,
                "target": "/srv/agentium-data",
                "fstype": "ext4",
                "device_id": 2,
            },
            "secure_deposit": {
                "source": "/dev/sdc",
                "normalized_source": "/dev/sdc",
                "expected_source": "/dev/sdc",
                "source_matches_expected": True,
                "target": "/secure",
                "fstype": "ext4",
                "device_id": 3,
            },
        },
    }


def _object_store_with(module, entries):
    normalized = sorted(entries, key=lambda entry: entry["path_sha256"])
    return {
        "files": len(normalized),
        "bytes": sum(entry["size"] for entry in normalized),
        "algorithm": "sha256-merkle-v1",
        "entry_fields": ["path_sha256", "size", "content_sha256"],
        "entries": normalized,
        "content_manifest_sha256": module._canonical_json_sha256(normalized),
    }


def test_secure_deposit_detects_replacement_with_restored_size_and_mtime(
    tmp_path: Path,
) -> None:
    module = _module()
    root = tmp_path / "secure"
    root.mkdir()
    target = root / "customer-secret.pdf"
    target.write_bytes(b"first")
    original = target.stat()
    before = module._secure_deposit_aggregate(root)

    target.write_bytes(b"other")
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert target.stat().st_ino == original.st_ino
    after = module._secure_deposit_aggregate(root)

    assert before["files"] == after["files"] == 1
    assert before["bytes"] == after["bytes"] == 5
    assert before["manifest_sha256"] != after["manifest_sha256"]
    assert "customer-secret.pdf" not in json.dumps(before)
    # The content digest is what makes the assertion above hold at all: every
    # other field survives an equal-length rewrite whose timestamps were put
    # back, and putting them back is one ``os.utime`` call away for anyone who
    # can write the file.
    assert before["manifest_fields"] == [
        "kind",
        "path_sha256",
        "size",
        "inode",
        "mtime_ns",
        "ctime_ns",
        "content_sha256",
    ]


def test_object_store_merkle_hashes_content_without_leaking_paths(tmp_path: Path) -> None:
    module = _module()
    root = tmp_path / "object_store"
    nested = root / "andritz" / "private"
    nested.mkdir(parents=True)
    target = nested / "customer-contract.pdf"
    target.write_bytes(b"alpha")
    original = target.stat()
    before = module._object_store_snapshot(root)

    target.write_bytes(b"bravo")
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
    after = module._object_store_snapshot(root)

    assert before["files"] == after["files"] == 1
    assert before["bytes"] == after["bytes"] == 5
    assert before["content_manifest_sha256"] != after["content_manifest_sha256"]
    serialized = json.dumps(before)
    assert "andritz" not in serialized
    assert "customer-contract.pdf" not in serialized


def test_mount_contract_rejects_the_wrong_backing_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def fake_run(argv: list[str], **_kwargs: object) -> str:
        assert argv[0] == "findmnt"
        return json.dumps(
            {
                "filesystems": [
                    {
                        "source": "/dev/sdb",
                        "target": str(tmp_path),
                        "fstype": "ext4",
                        "options": "rw,relatime",
                    }
                ]
            }
        )

    monkeypatch.setattr(module, "_run", fake_run)
    mounted = module._mount(tmp_path, expected_source="/dev/sdb")
    assert mounted["source_matches_expected"] is True
    assert mounted["expected_source"] == "/dev/sdb"

    with pytest.raises(module.StorageAttestationError, match="unexpected backing device"):
        module._mount(tmp_path, expected_source="/dev/sdc")


def test_storage_apis_are_loopback_only_and_bypass_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    with pytest.raises(module.StorageAttestationError, match="loopback-only"):
        module._http_json("https://qdrant.example.test/collections", api_key="secret")
    with pytest.raises(module.StorageAttestationError, match="loopback-only"):
        module._signed_s3_xml(
            "https://minio.example.test",
            bucket="private",
            query=[("versions", "")],
            access_key="access",
            secret_key="secret",
        )

    captured: dict[str, object] = {}

    class FakeOpener:
        def open(self, request: object, *, timeout: int) -> str:
            captured["request"] = request
            captured["timeout"] = timeout
            return "response"

    def fake_build_opener(handler: object) -> FakeOpener:
        captured["proxies"] = getattr(handler, "proxies", None)
        return FakeOpener()

    monkeypatch.setattr(module.urllib.request, "build_opener", fake_build_opener)
    request = module.urllib.request.Request("http://127.0.0.1:9000")
    assert module._direct_urlopen(request, timeout=3) == "response"
    assert captured["proxies"] == {}
    assert captured["timeout"] == 3


def test_object_store_binding_is_hashed_and_backend_worker_must_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    values = {
        "OBJECT_STORE_BACKEND": "s3",
        "OBJECT_STORE_S3_BUCKET": "customer-private-bucket",
        "OBJECT_STORE_S3_ENDPOINT_URL": "http://agentium-minio:9000",
        "OBJECT_STORE_S3_ACCESS_KEY": "private-access",
        "OBJECT_STORE_S3_SECRET_KEY": "private-secret",
    }
    monkeypatch.setattr(module, "_docker_environment", lambda _container: values)
    bindings = module._object_store_bindings()
    serialized = json.dumps(bindings)
    assert bindings["backend"] == bindings["worker_cpu"]
    for secret in (
        "customer-private-bucket",
        "agentium-minio",
        "private-access",
        "private-secret",
    ):
        assert secret not in serialized

    monkeypatch.setattr(
        module,
        "_object_store_binding",
        lambda container: {"backend": "s3" if container == "agentium-backend" else "local"},
    )
    with pytest.raises(module.StorageAttestationError, match="bindings differ"):
        module._object_store_bindings()


def test_minio_inventory_is_version_aware_and_privacy_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    versioning_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
      <Status>Enabled</Status>
    </VersioningConfiguration>"""
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
      <IsTruncated>false</IsTruncated>
      <Version>
        <Key>customers/andritz/secret.pdf</Key>
        <VersionId>private-version-id</VersionId>
        <IsLatest>true</IsLatest>
        <LastModified>2026-07-22T10:00:00.000Z</LastModified>
        <ETag>"0123456789abcdef"</ETag>
        <Size>42</Size>
      </Version>
      <DeleteMarker>
        <Key>customers/octocity/removed.pdf</Key>
        <VersionId>private-delete-version</VersionId>
        <IsLatest>true</IsLatest>
        <LastModified>2026-07-22T10:01:00.000Z</LastModified>
      </DeleteMarker>
    </ListVersionsResult>"""
    monkeypatch.setattr(module, "_minio_credentials", lambda _path: ("access", "secret"))
    def signed_xml(*_args: object, **kwargs: object) -> bytes:
        query = kwargs.get("query")
        return versioning_xml if query == [("versioning", "")] else xml

    monkeypatch.setattr(module, "_signed_s3_xml", signed_xml)

    snapshot = module._minio_snapshot(
        "http://127.0.0.1:9000",
        bucket="agentium-private",
        env_path=None,
    )

    assert snapshot["versions"] == 2
    assert snapshot["versioning_status"] == "enabled"
    assert snapshot["latest_versions"] == 2
    assert snapshot["delete_markers"] == 1
    assert snapshot["bytes"] == 42
    serialized = json.dumps(snapshot)
    for private_value in (
        "agentium-private",
        "andritz",
        "octocity",
        "secret.pdf",
        "private-version-id",
        "0123456789abcdef",
    ):
        assert private_value not in serialized


@pytest.mark.parametrize(
    ("status_xml", "expected"),
    [
        (
            b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"/>',
            "unversioned",
        ),
        (
            b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Suspended</Status></VersioningConfiguration>',
            "suspended",
        ),
    ],
)
def test_minio_snapshot_refuses_non_enabled_versioning_before_inventory(
    monkeypatch: pytest.MonkeyPatch,
    status_xml: bytes,
    expected: str,
) -> None:
    module = _module()
    calls: list[object] = []

    def signed_xml(*_args: object, **kwargs: object) -> bytes:
        calls.append(kwargs.get("query"))
        return status_xml

    monkeypatch.setattr(module, "_minio_credentials", lambda _path: ("access", "secret"))
    monkeypatch.setattr(module, "_signed_s3_xml", signed_xml)

    with pytest.raises(module.StorageAttestationError, match=expected):
        module._minio_snapshot(
            "http://127.0.0.1:9000",
            bucket="agentium-private",
            env_path=None,
        )

    assert calls == [[("versioning", "")]]


def test_release_a_baseline_can_inventory_unversioned_without_accepting_suspended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    unversioned = b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"/>'
    listing = b'<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated></ListVersionsResult>'
    monkeypatch.setattr(module, "_minio_credentials", lambda _path: ("access", "secret"))
    monkeypatch.setattr(
        module,
        "_signed_s3_xml",
        lambda *_args, **kwargs: unversioned
        if kwargs.get("query") == [("versioning", "")]
        else listing,
    )
    snapshot = module._minio_snapshot(
        "http://127.0.0.1:9000",
        bucket="agentium-private",
        env_path=None,
        require_versioning=False,
    )
    assert snapshot["versioning_status"] == "unversioned"

    suspended = b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Suspended</Status></VersioningConfiguration>'
    monkeypatch.setattr(module, "_signed_s3_xml", lambda *_args, **_kwargs: suspended)
    with pytest.raises(module.StorageAttestationError, match="suspended"):
        module._minio_snapshot(
            "http://127.0.0.1:9000",
            bucket="agentium-private",
            env_path=None,
            require_versioning=False,
        )


def test_minio_inventory_digest_covers_etag_version_and_time() -> None:
    module = _module()
    base = [
        {
            "key": "hidden/key",
            "version_id": "v1",
            "size": 7,
            "etag": "etag-a",
            "last_modified": "2026-07-22T10:00:00Z",
            "is_latest": True,
            "delete_marker": False,
        }
    ]
    before = module._minio_inventory_from_rows(base, bucket="private")
    changed = [{**base[0], "etag": "etag-b"}]
    after = module._minio_inventory_from_rows(changed, bucket="private")
    assert before["inventory_sha256"] != after["inventory_sha256"]


def test_qdrant_inventory_covers_config_and_hashes_business_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    responses = {
        "http://127.0.0.1:6333/collections": {
            "result": {"collections": [{"name": "andritz-contracts"}]}
        },
        "http://127.0.0.1:6333/collections/andritz-contracts": {
            "result": {
                "status": "green",
                "optimizer_status": "ok",
                "points_count": 10,
                "vectors_count": 10,
                "indexed_vectors_count": 8,
                "segments_count": 2,
                "config": {"params": {"vectors": {"size": 1536}}},
                "payload_schema": {"workspace_id": {"data_type": "keyword"}},
            }
        },
        "http://127.0.0.1:6333/aliases": {
            "result": {
                "aliases": [
                    {
                        "alias_name": "andritz-current",
                        "collection_name": "andritz-contracts",
                    }
                ]
            }
        },
    }
    count_url = (
        "http://127.0.0.1:6333/collections/andritz-contracts/points/count"
        "?consistency=all"
    )
    scroll_url = (
        "http://127.0.0.1:6333/collections/andritz-contracts/points/scroll"
        "?consistency=all"
    )
    scroll_bodies: list[dict[str, object]] = []

    def fake_http_json(url: str, **kwargs: object) -> dict[str, object]:
        assert kwargs.get("api_key") == "hidden"
        body = kwargs.get("json_body")
        if url == count_url:
            assert body == {"exact": True}
            return {"result": {"count": 3}}
        if url == scroll_url:
            assert isinstance(body, dict)
            scroll_bodies.append(body)
            if "offset" not in body:
                return {
                    "result": {
                        "points": [
                            {
                                "id": "00000000-0000-0000-0000-000000000010",
                                "payload": {"customer": "andritz-secret-a"},
                                "vector": [0.123456, 0.654321],
                            },
                            {
                                "id": "00000000-0000-0000-0000-000000000020",
                                "payload": {"customer": "andritz-secret-b"},
                                "vector": {"dense": [0.4, 0.5]},
                            },
                        ],
                        "next_page_offset": "00000000-0000-0000-0000-000000000020",
                    }
                }
            assert body["offset"] == "00000000-0000-0000-0000-000000000020"
            return {
                "result": {
                    "points": [
                        {
                            "id": "00000000-0000-0000-0000-000000000030",
                            "payload": None,
                            "vector": [0.9, 0.8],
                        }
                    ],
                    "next_page_offset": None,
                }
            }
        response = responses.get(url)
        assert response is not None, url
        return response

    monkeypatch.setattr(module, "_http_json", fake_http_json)

    snapshot = module._qdrant_snapshot("http://127.0.0.1:6333", api_key="hidden")

    row = snapshot["collections"][0]
    assert row["segments_count"] == 2
    assert row["points_count_exact"] == 3
    assert len(row["point_manifest_sha256"]) == 64
    assert len(row["config_sha256"]) == 64
    assert len(row["payload_schema_sha256"]) == 64
    assert len(snapshot["inventory_sha256"]) == 64
    assert snapshot["points_count_exact"] == 3
    assert snapshot["read_consistency"] == "all"
    assert len(scroll_bodies) == 2
    assert all(body["with_payload"] is True for body in scroll_bodies)
    assert all(body["with_vector"] is True for body in scroll_bodies)
    serialized = json.dumps(snapshot)
    assert "andritz-contracts" not in serialized
    assert "andritz-current" not in serialized
    for private_value in (
        "00000000-0000-0000-0000-000000000010",
        "00000000-0000-0000-0000-000000000020",
        "00000000-0000-0000-0000-000000000030",
        "andritz-secret-a",
        "andritz-secret-b",
        "0.123456",
        "hidden",
    ):
        assert private_value not in serialized


def test_qdrant_point_manifest_is_pagination_independent_and_content_sensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    original = [
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "payload": {"workspace": "andritz", "text": "private-contract-a"},
            "vector": [0.125, 0.25],
        },
        {
            "id": "00000000-0000-0000-0000-000000000020",
            "payload": {"workspace": "andritz", "text": "private-contract-b"},
            "vector": {"dense": [0.5, 0.75]},
        },
        {
            "id": "00000000-0000-0000-0000-000000000030",
            "payload": None,
            "vector": [1.0, -1.0],
        },
    ]

    def capture(points: list[dict[str, object]], page_size: int) -> dict[str, object]:
        offsets: dict[object, int] = {}
        pages = [points[index : index + page_size] for index in range(0, len(points), page_size)]
        for index, page in enumerate(pages[:-1]):
            offsets[page[-1]["id"]] = index + 1

        def fake_http_json(url: str, **kwargs: object) -> dict[str, object]:
            body = kwargs.get("json_body")
            if "/points/count?" in url:
                assert body == {"exact": True}
                return {"result": {"count": len(points)}}
            assert "/points/scroll?" in url
            assert isinstance(body, dict)
            page_index = 0 if "offset" not in body else offsets[body["offset"]]
            next_offset = (
                pages[page_index][-1]["id"]
                if page_index < len(pages) - 1
                else None
            )
            return {
                "result": {
                    "points": pages[page_index],
                    "next_page_offset": next_offset,
                }
            }

        monkeypatch.setattr(module, "_http_json", fake_http_json)
        return module._qdrant_point_manifest(
            "http://127.0.0.1:6333",
            "opaque-collection",
            api_key="private-key",
        )

    one_page = capture(deepcopy(original), 3)
    three_pages = capture(deepcopy(original), 1)
    assert one_page["point_manifest_sha256"] == three_pages["point_manifest_sha256"]

    payload_changed = deepcopy(original)
    payload_changed[1]["payload"] = {"workspace": "andritz", "text": "changed"}
    vector_changed = deepcopy(original)
    vector_changed[1]["vector"] = {"dense": [0.5, 0.751]}
    id_changed = deepcopy(original)
    id_changed[1]["id"] = "00000000-0000-0000-0000-000000000021"
    for changed in (payload_changed, vector_changed, id_changed):
        assert (
            capture(changed, 2)["point_manifest_sha256"]
            != one_page["point_manifest_sha256"]
        )

    serialized = json.dumps(one_page)
    for private_value in (
        "00000000-0000-0000-0000-000000000010",
        "andritz",
        "private-contract",
        "0.125",
    ):
        assert private_value not in serialized


def test_qdrant_point_manifest_rejects_count_change_and_scroll_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    count_calls = 0

    def count_changed(url: str, **_kwargs: object) -> dict[str, object]:
        nonlocal count_calls
        if "/points/count?" in url:
            count_calls += 1
            return {"result": {"count": 1 if count_calls == 1 else 2}}
        return {
            "result": {
                "points": [{"id": 1, "payload": {}, "vector": [0.1]}],
                "next_page_offset": None,
            }
        }

    monkeypatch.setattr(module, "_http_json", count_changed)
    with pytest.raises(module.StorageAttestationError, match="changed or returned"):
        module._qdrant_point_manifest(
            "http://127.0.0.1:6333",
            "opaque-collection",
            api_key="private-key",
        )

    def cyclic_scroll(url: str, **kwargs: object) -> dict[str, object]:
        if "/points/count?" in url:
            return {"result": {"count": 2}}
        body = kwargs["json_body"]
        assert isinstance(body, dict)
        point_id = 1 if "offset" not in body else 2
        return {
            "result": {
                "points": [{"id": point_id, "payload": {}, "vector": [0.1]}],
                "next_page_offset": 1,
            }
        }

    monkeypatch.setattr(module, "_http_json", cyclic_scroll)
    with pytest.raises(module.StorageAttestationError, match="offset did not progress"):
        module._qdrant_point_manifest(
            "http://127.0.0.1:6333",
            "opaque-collection",
            api_key="private-key",
        )

    def unordered_scroll(url: str, **_kwargs: object) -> dict[str, object]:
        if "/points/count?" in url:
            return {"result": {"count": 2}}
        return {
            "result": {
                "points": [
                    {"id": 2, "payload": {}, "vector": [0.2]},
                    {"id": 1, "payload": {}, "vector": [0.1]},
                ],
                "next_page_offset": None,
            }
        }

    monkeypatch.setattr(module, "_http_json", unordered_scroll)
    with pytest.raises(module.StorageAttestationError, match="strictly ordered"):
        module._qdrant_point_manifest(
            "http://127.0.0.1:6333",
            "opaque-collection",
            api_key="private-key",
        )


def test_snapshot_comparison_requires_and_covers_all_storage_planes() -> None:
    module = _module()
    base = _empty_snapshot(module)
    assert module.compare_snapshots(base, base)["result"] == "passed"
    assert module.compare_snapshots(base, base)["profile"] == module.EXACT_COMPARISON_PROFILE

    changed = deepcopy(base)
    changed["minio"] = module._minio_inventory_from_rows(
        [
            {
                "key": "new/private/key",
                "version_id": "v1",
                "size": 7,
                "etag": "etag",
                "last_modified": "2026-07-22T10:00:00Z",
                "is_latest": True,
                "delete_marker": False,
            }
        ],
        bucket="private",
    )
    comparison = module.compare_snapshots(base, changed)
    assert comparison["result"] == "failed"
    assert "minio.inventory_sha256" in comparison["failed_checks"]

    incomplete = {**base, "object_store": {}}
    with pytest.raises(module.StorageAttestationError, match="ObjectStore inventory is invalid"):
        module.compare_snapshots(incomplete, base)


def test_release_a_comparison_allows_only_versioning_transition_with_exact_data() -> None:
    module = _module()
    after = _empty_snapshot(module)
    before = deepcopy(after)
    before["minio"]["versioning_status"] = "unversioned"

    result = module.compare_release_a_versioning_adoption(before, after)
    assert result["result"] == "passed"
    assert result["profile"] == "agentium-storage-release-a-versioning-comparison-v1"

    changed = deepcopy(after)
    changed["qdrant"]["collections"] = 1
    with pytest.raises(module.StorageAttestationError):
        module.compare_release_a_versioning_adoption(before, changed)


def test_snapshot_requires_minio_inventory_for_runtime_bucket() -> None:
    module = _module()
    snapshot = _empty_snapshot(module)
    snapshot["object_store_bindings"]["backend"]["s3_bucket_id_sha256"] = "f" * 64
    snapshot["object_store_bindings"]["worker_cpu"]["s3_bucket_id_sha256"] = "f" * 64

    with pytest.raises(module.StorageAttestationError, match="runtime S3 bucket"):
        module.compare_snapshots(snapshot, snapshot)


def test_validation_mount_transition_allows_only_application_binds_rw_to_ro() -> None:
    module = _module()
    before = _empty_snapshot(module)
    before["container_mounts"] = {
        "agentium-backend": [
            {
                "type": "bind",
                "source": "/srv/agentium-data/faiss",
                "destination": "/data/faiss_db",
                "rw": True,
                "name": "",
            },
            {
                "type": "bind",
                "source": "/srv/agentium-data/object_store",
                "destination": "/data/object_store",
                "rw": True,
                "name": "",
            },
        ]
    }
    after = deepcopy(before)
    after["container_mounts"]["agentium-backend"][0]["rw"] = False
    result = module.compare_snapshots(before, after)
    assert result["result"] == "passed"

    reversed_transition = module.compare_snapshots(after, before)
    assert reversed_transition["result"] == "failed"
    assert "container_mounts.validation_boundary" in reversed_transition["failed_checks"]

    unrelated = deepcopy(before)
    unrelated["container_mounts"] = {
        "agentium-minio": [
            {
                "type": "volume",
                "source": "/srv/agentium-data/minio",
                "destination": "/data",
                "rw": False,
                "name": "agentium_minio",
            }
        ]
    }
    before_unrelated = deepcopy(before)
    before_unrelated["container_mounts"] = deepcopy(unrelated["container_mounts"])
    before_unrelated["container_mounts"]["agentium-minio"][0]["rw"] = True
    result = module.compare_snapshots(before_unrelated, unrelated)
    assert result["result"] == "failed"
    assert "container_mounts.validation_boundary" in result["failed_checks"]


def test_release_a_opening_allows_only_reverse_application_mount_transition() -> None:
    module = _module()
    validation = _empty_snapshot(module)
    validation["container_mounts"] = {
        "agentium-backend": [
            {
                "type": "bind",
                "source": "/srv/agentium-data/object_store",
                "destination": "/data/object_store",
                "rw": False,
                "name": "",
            }
        ]
    }
    opened = deepcopy(validation)
    opened["container_mounts"]["agentium-backend"][0]["rw"] = True

    result = module.compare_release_a_opening_transition(validation, opened)
    assert result["result"] == "passed"

    rebound = deepcopy(opened)
    rebound["container_mounts"]["agentium-backend"][0]["source"] = "/srv/other"
    result = module.compare_release_a_opening_transition(validation, rebound)
    assert result["result"] == "failed"


def test_faiss_content_and_filesystem_identity_are_exact() -> None:
    module = _module()
    before = _empty_snapshot(module)
    after = deepcopy(before)
    after["faiss"]["inode"] += 1
    result = module.compare_snapshots(before, after)
    assert result["result"] == "failed"
    assert "faiss" in result["failed_checks"]

    after = deepcopy(before)
    after["faiss"] = {
        **after["faiss"],
        **_object_store_with(
            module,
            [
                {
                    "path_sha256": module._identifier_sha256("index.faiss"),
                    "size": 4,
                    "content_sha256": module._identifier_sha256("data"),
                }
            ],
        ),
    }
    result = module.compare_snapshots(before, after)
    assert result["result"] == "failed"
    assert "faiss" in result["failed_checks"]


def test_compare_cli_keeps_strict_default_and_requires_explicit_additions_flag() -> None:
    module = _module()
    strict = module._parser().parse_args(
        ["compare", "--before", "before.json", "--after", "after.json", "--output", "out.json"]
    )
    additions = module._parser().parse_args(
        [
            "compare",
            "--allow-object-additions",
            "--before",
            "before.json",
            "--after",
            "after.json",
            "--output",
            "out.json",
        ]
    )
    assert strict.allow_object_additions is False
    assert additions.allow_object_additions is True


def test_additions_mode_preserves_existing_entries_and_reports_anonymized_delta() -> None:
    module = _module()
    before = _empty_snapshot(module)
    after = deepcopy(before)
    object_entry = {
        "path_sha256": module._identifier_sha256("private/new.json"),
        "size": 5,
        "content_sha256": module._identifier_sha256("bytes"),
    }
    after["object_store"] = _object_store_with(module, [object_entry])
    after["minio"] = module._minio_inventory_from_rows(
        [
            {
                "key": "membrane/private/provenance.json",
                "version_id": "v1",
                "size": 9,
                "etag": "etag-private",
                "last_modified": "2026-07-22T10:00:00Z",
                "is_latest": True,
                "delete_marker": False,
            }
        ],
        bucket="private",
    )

    result = module.compare_canary_snapshots(before, after)

    assert result["result"] == "passed"
    assert result["profile"] == module.ADDITIONS_COMPARISON_PROFILE
    assert result["assurance"] == "cryptographic_entry_inclusion"
    assert result["additions"]["object_store"]["count"] == 1
    assert result["additions"]["object_store"]["bytes"] == 5
    assert result["additions"]["minio"]["count"] == 1
    assert result["additions"]["minio"]["bytes"] == 9
    assert result["deletions"]["object_store"]["entries"] == []
    assert result["deletions"]["minio"]["entries"] == []
    assert result["modifications"]["object_store"]["entries"] == []
    assert result["modifications"]["minio"]["entries"] == []
    serialized = json.dumps(result)
    assert "private/new.json" not in serialized
    assert "membrane/private" not in serialized
    assert "etag-private" not in serialized


@pytest.mark.parametrize("backend", ["object_store", "minio"])
@pytest.mark.parametrize("mutation", ["deletion", "modification"])
def test_additions_mode_rejects_deletion_and_modification(
    backend: str,
    mutation: str,
) -> None:
    module = _module()
    empty = _empty_snapshot(module)
    populated = deepcopy(empty)
    object_entry = {
        "path_sha256": module._identifier_sha256("private/existing.json"),
        "size": 5,
        "content_sha256": module._identifier_sha256("first"),
    }
    populated["object_store"] = _object_store_with(module, [object_entry])
    minio_rows = [
        {
            "key": "private/existing.json",
            "version_id": "v1",
            "size": 5,
            "etag": "etag-a",
            "last_modified": "2026-07-22T10:00:00Z",
            "is_latest": True,
            "delete_marker": False,
        }
    ]
    populated["minio"] = module._minio_inventory_from_rows(
        minio_rows,
        bucket="private",
    )
    after = deepcopy(populated)
    if backend == "object_store":
        if mutation == "deletion":
            after["object_store"] = empty["object_store"]
        else:
            after["object_store"] = _object_store_with(
                module,
                [{**object_entry, "content_sha256": module._identifier_sha256("other")}],
            )
    elif mutation == "deletion":
        after["minio"] = empty["minio"]
    else:
        after["minio"] = module._minio_inventory_from_rows(
            [{**minio_rows[0], "etag": "etag-b"}],
            bucket="private",
        )

    result = module.compare_canary_snapshots(populated, after)

    assert result["result"] == "failed"
    assert f"{backend}.preexisting_entries_preserved" in result["failed_checks"]
    assert result[f"{mutation}s"][backend]["count"] == 1


def test_additions_mode_rejects_new_minio_delete_marker() -> None:
    module = _module()
    before = _empty_snapshot(module)
    after = deepcopy(before)
    after["minio"] = module._minio_inventory_from_rows(
        [
            {
                "key": "private/deleted.json",
                "version_id": "v1",
                "size": 0,
                "etag": "",
                "last_modified": "2026-07-22T10:00:00Z",
                "is_latest": True,
                "delete_marker": True,
            }
        ],
        bucket="private",
    )

    result = module.compare_canary_snapshots(before, after)

    assert result["result"] == "failed"
    assert "minio.no_delete_marker_additions" in result["failed_checks"]


def test_additions_mode_rejects_a_new_version_of_a_preexisting_minio_key() -> None:
    module = _module()
    first = {
        "key": "private/existing.json",
        "version_id": "v1",
        "size": 5,
        "etag": "etag-a",
        "last_modified": "2026-07-22T10:00:00Z",
        "is_latest": False,
        "delete_marker": False,
    }
    before = _empty_snapshot(module)
    before["minio"] = module._minio_inventory_from_rows([first], bucket="private")
    after = deepcopy(before)
    after["minio"] = module._minio_inventory_from_rows(
        [
            first,
            {
                **first,
                "version_id": "v2",
                "etag": "etag-b",
                "last_modified": "2026-07-22T10:01:00Z",
                "is_latest": True,
            },
        ],
        bucket="private",
    )

    result = module.compare_canary_snapshots(before, after)

    assert result["result"] == "failed"
    assert "minio.preexisting_object_keys_not_reversioned" in result["failed_checks"]
