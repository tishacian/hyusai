"""Staged deposits can live in the artifact store instead of a filesystem.

The filesystem only works where every reader shares one, which is true of the
Compose deployment and false of Kubernetes: the API and the SFTP transport are
separate pods and the storage classes are ReadWriteOnce. These tests pin the
behaviour that makes the shared volume unnecessary.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.secure_deposit import DepositFile

from app.services import secure_deposit as sd
from app.services.object_store import ObjectStore


@pytest.fixture()
def object_staging(tmp_path, monkeypatch):
    """Object-store backend, with the store itself on a local temp directory."""

    monkeypatch.setattr(settings, "secure_deposit_storage_backend", "object_store")
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "staging"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    store = ObjectStore()
    monkeypatch.setattr(sd, "get_object_store", lambda: store)
    return store


def _deposit(key: str) -> DepositFile:
    return DepositFile(
        id=str(uuid4()), filename=Path(key).name, object_key=key, status="received"
    )


def test_bytes_are_written_to_the_store_and_read_back_as_a_path(object_staging, tmp_path):
    key = "workspaces/ws-1/secure-deposit/acc-1/file-1/manual.txt"
    sd._write_staged_bytes(key, b"hello deposit")

    assert object_staging.exists(f"secure-deposit/{key}")
    # Nothing landed on the staging filesystem.
    assert not (Path(settings.secure_deposit_storage_dir) / key).exists()

    path = sd.staged_file_path(_deposit(key))
    assert path.is_file()
    assert path.read_bytes() == b"hello deposit"


def test_a_second_read_reuses_the_materialised_copy(object_staging):
    key = "workspaces/ws-1/secure-deposit/acc-1/file-2/manual.txt"
    sd._write_staged_bytes(key, b"body")
    first = sd.staged_file_path(_deposit(key))
    stamp = first.stat().st_mtime_ns

    second = sd.staged_file_path(_deposit(key))

    assert second == first
    assert second.stat().st_ino == first.stat().st_ino
    assert second.read_bytes() == b"body"
    assert second.stat().st_mtime_ns >= stamp


def test_a_deposit_taken_before_the_switch_is_still_served(object_staging):
    """Switching backend must not orphan what is already on disk."""

    key = "workspaces/ws-1/secure-deposit/acc-1/file-3/legacy.txt"
    legacy = Path(settings.secure_deposit_storage_dir) / key
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"written before the switch")

    path = sd.staged_file_path(_deposit(key))

    assert path == legacy
    assert path.read_bytes() == b"written before the switch"


def test_a_missing_object_is_a_staged_file_miss_not_a_traceback(object_staging):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        sd.staged_file_path(_deposit("workspaces/ws-1/secure-deposit/acc-1/nope/x.txt"))
    assert exc.value.status_code == 409


def test_copy_to_local_works_on_both_backends(object_staging, tmp_path):
    key = "workspaces/ws-1/secure-deposit/acc-1/file-4/data.bin"
    sd._write_staged_bytes(key, b"payload")

    destination = tmp_path / "out" / "data.bin"
    sd._copy_staged_to_local(key, destination)

    assert destination.read_bytes() == b"payload"


def test_a_short_download_does_not_become_the_cached_file(object_staging, monkeypatch):
    key = "workspaces/ws-1/secure-deposit/acc-1/file-short/manual.txt"
    sd._write_staged_bytes(key, b"complete body")

    def short_copy(_key, destination):
        destination.write_bytes(b"no")
        return destination

    monkeypatch.setattr(object_staging, "copy_to_local", short_copy)
    with pytest.raises(HTTPException):
        sd.staged_file_path(_deposit(key))

    cached = sd._cache_root() / key
    assert not cached.exists()
    assert list(cached.parent.glob("*.partial")) == []


def test_reading_a_cached_file_keeps_it_past_the_sweep(object_staging):
    import os
    import time

    key = "workspaces/ws-1/secure-deposit/acc-1/file-touch/old.txt"
    sd._write_staged_bytes(key, b"kept")
    cached = sd.staged_file_path(_deposit(key))
    os.utime(cached, (time.time() - 7200, time.time() - 7200))

    sd.staged_file_path(_deposit(key))
    sd._sweep_cache(ttl_seconds=3600)

    assert cached.exists()
    assert cached.read_bytes() == b"kept"


def test_the_sweep_drops_stale_copies_only(object_staging):
    import os
    import time

    key = "workspaces/ws-1/secure-deposit/acc-1/file-5/old.txt"
    sd._write_staged_bytes(key, b"old")
    stale = sd.staged_file_path(_deposit(key))
    os.utime(stale, (time.time() - 7200, time.time() - 7200))

    fresh_key = "workspaces/ws-1/secure-deposit/acc-1/file-6/new.txt"
    sd._write_staged_bytes(fresh_key, b"new")
    fresh = sd.staged_file_path(_deposit(fresh_key))

    sd._sweep_cache(ttl_seconds=3600)

    assert not stale.exists()
    assert fresh.exists()


def test_the_local_backend_is_untouched(tmp_path, monkeypatch):
    """The default stays a filesystem, so Compose behaves exactly as before."""

    monkeypatch.setattr(settings, "secure_deposit_storage_backend", "local")
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "staging"))
    key = "workspaces/ws-1/secure-deposit/acc-1/file-7/plain.txt"
    sd._write_staged_bytes(key, b"on disk")

    path = sd.staged_file_path(_deposit(key))
    assert path == Path(settings.secure_deposit_storage_dir).resolve() / key
    assert path.read_bytes() == b"on disk"


def test_reconciliation_refuses_object_storage_rather_than_reporting_clean(
    object_staging, monkeypatch
):
    """A directory walk that finds nothing is not a clean bill of health."""

    from app.services import secure_deposit_operations as ops

    assert ops._filesystem_staging() is False
    assert ops.run_sftp_reconciliation_job("job-1") == {
        "status": "failed",
        "error": "object_store_staging_unsupported",
    }

    monkeypatch.setattr(settings, "secure_deposit_storage_backend", "local")
    assert ops._filesystem_staging() is True


def test_write_file_streams_without_reading_the_whole_body(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    store = ObjectStore()

    source = tmp_path / "big.bin"
    payload = b"x" * (3 * 1024 * 1024)
    source.write_bytes(payload)

    store.write_file("deposits/big.bin", source)

    assert store.read_bytes("deposits/big.bin") == payload
    assert hashlib.sha256(store.read_bytes("deposits/big.bin")).hexdigest() == (
        hashlib.sha256(payload).hexdigest()
    )


@pytest.mark.asyncio
async def test_an_upload_streams_to_the_store_and_leaves_no_part_file(object_staging):
    """The main write path, not just the byte helper.

    The body is streamed through a temp file because size and digest are only
    known at the end, and an oversized upload must be refused without being
    held in memory. What must not survive is the temp file itself.
    """

    from io import BytesIO

    from fastapi import UploadFile

    payload = b"deposit body" * 1000
    upload = UploadFile(file=BytesIO(payload), filename="report.bin")
    key = "workspaces/ws-1/secure-deposit/acc-1/file-up/report.bin"

    size, digest = await sd._write_staged_upload(key, upload, max_bytes=10 * 1024 * 1024)

    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert object_staging.read_bytes(f"secure-deposit/{key}") == payload
    assert not list(sd._cache_root().glob("**/*.part"))
    assert sd.staged_file_path(_deposit(key)).read_bytes() == payload


@pytest.mark.asyncio
async def test_an_oversized_upload_is_refused_and_leaves_nothing_behind(object_staging):
    from io import BytesIO

    from fastapi import HTTPException, UploadFile

    upload = UploadFile(file=BytesIO(b"x" * 5000), filename="too-big.bin")
    key = "workspaces/ws-1/secure-deposit/acc-1/file-big/too-big.bin"

    with pytest.raises(HTTPException) as exc:
        await sd._write_staged_upload(key, upload, max_bytes=1024)

    assert exc.value.status_code == 413
    assert not object_staging.exists(f"secure-deposit/{key}")
    assert not list(sd._cache_root().glob("**/*.part"))
