"""Offline bundles fail closed before license acceptance or publication."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.huggingface.bundles import export_bundle, import_bundle
from app.services.huggingface.errors import HFError
from app.services.huggingface.policy import license_digest

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
LICENSE = "Example license evidence preserved at the pinned revision."
LICENSE_DIGEST = license_digest({"license": "mit"}, LICENSE)
CONTENT = {"weights/model.gguf": b"immutable weights", "config.json": b'{"model":1}'}


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def manifest():
    return {
        "version": 2,
        "artifact_id": "hf-artifact-1",
        "kind": "model",
        "revision": "a" * 40,
        "private": False,
        "gated": False,
        "license_text": LICENSE,
        "license": "mit",
        "license_digest": LICENSE_DIGEST,
        "files": {
            path: {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in CONTENT.items()
        },
    }


def bundle(manifest, key, **kwargs):
    stream = io.BytesIO()
    export_bundle(
        stream,
        manifest=manifest,
        open_file=lambda path: io.BytesIO(CONTENT[path]),
        target_workspace_id="workspace-a",
        license_digest=LICENSE_DIGEST,
        signing_key=key,
        key_id="exporter-1",
        authorize=lambda *_: None,
        now=NOW,
        **kwargs,
    )
    return stream.getvalue()


def load(data, key, tmp_path, **kwargs):
    args = {
        "destination_dir": tmp_path / "artifact",
        "target_workspace_id": "workspace-a",
        "trust_keys": {"exporter-1": key.public_key()},
        "accept_license": lambda *_: True,
        "max_total_bytes": 1000,
        "max_file_bytes": 1000,
        "now": NOW + timedelta(seconds=1),
    }
    args.update(kwargs)
    return import_bundle(io.BytesIO(data), **args)


def members(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        return [(info, archive.extractfile(info).read()) for info in archive]


def repack(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for info, data in entries:
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def test_round_trip_verifies_content_before_license_and_publish(manifest, key, tmp_path):
    accepted = []

    def accept_license(value, digest):
        assert not (tmp_path / "artifact").exists()
        assert value == manifest
        accepted.append(digest)
        return True

    result = load(bundle(manifest, key), key, tmp_path, accept_license=accept_license)
    assert result == manifest
    assert accepted == [LICENSE_DIGEST]
    for path, expected in CONTENT.items():
        assert (tmp_path / "artifact" / "files" / path).read_bytes() == expected
    assert json.loads((tmp_path / "artifact" / "manifest.json").read_bytes()) == manifest


def test_export_size_limit_before_writing(manifest, key):
    with pytest.raises(HFError) as error:
        bundle(manifest, key, max_total_bytes=1)
    assert error.value.code == "HF_BUNDLE_TOO_LARGE"


@pytest.mark.parametrize("flag", ["private", "gated"])
def test_restricted_export_requires_current_workspace_hub_check(manifest, key, flag):
    manifest[flag] = True
    with pytest.raises(HFError, match="current target workspace Hub access check"):
        bundle(manifest, key)
    calls = []
    bundle(manifest, key, verify_hub_access=lambda m, ws: calls.append((m["artifact_id"], ws)))
    assert calls == [(manifest["artifact_id"], "workspace-a")]


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"target_workspace_id": "workspace-b"}, "HF_BUNDLE_PROOF_INVALID"),
        ({"now": NOW + timedelta(days=1)}, "HF_BUNDLE_PROOF_EXPIRED"),
        ({"now": NOW - timedelta(seconds=1)}, "HF_BUNDLE_PROOF_EXPIRED"),
        ({"trust_keys": {}}, "HF_BUNDLE_PROOF_INVALID"),
    ],
)
def test_proof_scope_expiry_and_trust_precede_acceptance(manifest, key, tmp_path, overrides, code):
    accepted = []
    with pytest.raises(HFError) as caught:
        load(
            bundle(manifest, key),
            key,
            tmp_path,
            accept_license=lambda *_: accepted.append(True),
            **overrides,
        )
    assert caught.value.code == code
    assert accepted == []
    assert list(tmp_path.iterdir()) == []


def test_missing_attestation_is_rejected_even_for_public_artifact(manifest, key, tmp_path):
    entries = members(bundle(manifest, key))
    with pytest.raises(HFError, match="attestation.json"):
        load(repack([entries[0], *entries[2:]]), key, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "field,value", [("gated", True), ("artifact_id", "forged"), ("license_text", "MIT")]
)
def test_manifest_is_bound_to_signature(manifest, key, tmp_path, field, value):
    entries = members(bundle(manifest, key))
    tampered = dict(manifest, **{field: value})
    data = json.dumps(tampered).encode()
    entries[0][0].size = len(data)
    entries[0] = (entries[0][0], data)
    with pytest.raises(HFError) as caught:
        load(repack(entries), key, tmp_path)
    assert caught.value.code == "HF_BUNDLE_PROOF_INVALID"


@pytest.mark.parametrize(
    "attack",
    [
        "traversal",
        "absolute",
        "backslash",
        "symlink",
        "hardlink",
        "duplicate",
        "unexpected",
        "missing",
        "pax",
    ],
)
def test_unsafe_or_inexact_archives_are_rejected(manifest, key, tmp_path, attack):
    entries = members(bundle(manifest, key))
    if attack in {"traversal", "absolute", "backslash", "unexpected"}:
        entries[-1][0].name = {
            "traversal": "files/../../escape",
            "absolute": "/tmp/escape",
            "backslash": "files/..\\escape",
            "unexpected": "files/unlisted.gguf",
        }[attack]
    elif attack in {"symlink", "hardlink", "pax"}:
        entries[-1][0].type = {
            "symlink": tarfile.SYMTYPE,
            "hardlink": tarfile.LNKTYPE,
            "pax": tarfile.XHDTYPE,
        }[attack]
        entries[-1][0].linkname = "/tmp/escape"
    elif attack == "duplicate":
        entries.append(entries[-1])
    elif attack == "missing":
        entries.pop()
    accepted = []
    with pytest.raises(HFError):
        load(repack(entries), key, tmp_path, accept_license=lambda *_: accepted.append(True))
    assert accepted == []
    assert list(tmp_path.iterdir()) == []


def test_corrupted_bytes_leave_no_published_or_partial_artifact(manifest, key, tmp_path):
    entries = members(bundle(manifest, key))
    info, data = entries[-1]
    entries[-1] = (info, b"x" * len(data))
    with pytest.raises(HFError) as caught:
        load(repack(entries), key, tmp_path)
    assert caught.value.code == "HF_BUNDLE_CONTENT_MISMATCH"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("limit", ["max_total_bytes", "max_file_bytes"])
def test_limits_checked_before_extraction(manifest, key, tmp_path, limit):
    with pytest.raises(HFError) as caught:
        load(bundle(manifest, key), key, tmp_path, **{limit: 1})
    assert caught.value.code == "HF_BUNDLE_TOO_LARGE"
    assert list(tmp_path.iterdir()) == []


def test_unaccepted_license_cannot_publish(manifest, key, tmp_path):
    with pytest.raises(HFError) as caught:
        load(bundle(manifest, key), key, tmp_path, accept_license=lambda *_: False)
    assert caught.value.code == "HF_LICENSE_ACCEPTANCE_REQUIRED"
    assert list(tmp_path.iterdir()) == []


def test_datasets_keep_only_materialized_result(manifest, key, tmp_path):
    result_bytes = b"immutable parquet result"
    manifest["kind"] = "dataset"
    manifest["dataset_result"] = {
        "path": "result.parquet",
        "size_bytes": len(result_bytes),
        "sha256": hashlib.sha256(result_bytes).hexdigest(),
        "object_key": "datasets/retained-result.parquet",
    }
    # Source files deliberately cannot be opened on an offline installation.
    stream = io.BytesIO()
    opened = []

    def open_result(path):
        opened.append(path)
        assert path == "result.parquet"
        return io.BytesIO(result_bytes)

    export_bundle(
        stream,
        manifest=manifest,
        open_file=open_result,
        target_workspace_id="workspace-a",
        license_digest=LICENSE_DIGEST,
        signing_key=key,
        key_id="exporter-1",
        authorize=lambda *_: None,
        now=NOW,
    )
    load(stream.getvalue(), key, tmp_path)
    assert opened == ["result.parquet"]
    assert (tmp_path / "artifact" / "files" / "result.parquet").read_bytes() == result_bytes
    assert not (tmp_path / "artifact" / "files" / "weights").exists()


def test_signature_is_cryptographically_verified(manifest, key, tmp_path):
    untrusted_key = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(HFError) as caught:
        load(bundle(manifest, key), key, tmp_path, trust_keys={"exporter-1": untrusted_key})
    assert caught.value.code == "HF_BUNDLE_PROOF_INVALID"


def test_truncated_and_concatenated_archives_are_rejected(manifest, key, tmp_path):
    data = bundle(manifest, key)
    for malicious in (data[:1500], data + data):
        with pytest.raises(HFError):
            load(malicious, key, tmp_path)
        assert list(tmp_path.iterdir()) == []


def test_export_rechecks_current_authorization(manifest, key):
    with pytest.raises(HFError, match="not authorized"):
        export_bundle(
            io.BytesIO(),
            manifest=manifest,
            open_file=lambda path: io.BytesIO(CONTENT[path]),
            target_workspace_id="workspace-a",
            license_digest=LICENSE_DIGEST,
            signing_key=key,
            key_id="exporter-1",
            authorize=lambda *_: False,
            now=NOW,
        )
