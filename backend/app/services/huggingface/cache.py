"""Verified local artifact snapshots; only the preparation worker writes here.

An inference process opens an already provisioned snapshot and takes a shared
flock on its lease file. Admission and eviction use exclusive locks. Lock files
are never removed: unlinking a locked inode would let a second writer bypass it.
Downloads happen through an explicitly supplied object-store reader, never HF.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Iterator

from app.services.huggingface.errors import HFError

MAX_FILES = 10_000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024


class ArtifactError(HFError):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, status_code=409)


def _fail(code: str, message: str) -> None:
    raise ArtifactError(code, message)


def artifact_name(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        _fail("HF_MANIFEST_INVALID", "Invalid artifact identifier.")
    return value


def relative_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
        or PurePosixPath(value).is_absolute()
        or any(p in {"", ".", ".."} for p in value.split("/"))
    ):
        _fail("HF_MANIFEST_INVALID", "Artifact paths must be relative POSIX paths.")
    if value == "manifest.json":
        _fail("HF_MANIFEST_INVALID", "manifest.json is reserved for the artifact manifest.")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(manifest: dict, *, artifact_id: str | None = None) -> dict:
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != 2
        or manifest.get("kind") != "model"
    ):
        _fail("HF_MANIFEST_INVALID", "A version 2 model artifact manifest is required.")
    identity = artifact_name(manifest.get("artifact_id"))
    if artifact_id is not None and identity != artifact_id:
        _fail("HF_MANIFEST_INVALID", "The manifest belongs to another artifact.")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("revision", ""))):
        _fail("HF_MANIFEST_INVALID", "An immutable 40-character Hub commit is required.")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        _fail("HF_MANIFEST_INVALID", "The manifest must inventory all model files.")
    total = 0
    for name, entry in files.items():
        relative_name(name)
        if not isinstance(entry, dict) or not re.fullmatch(
            r"[0-9a-f]{64}", str(entry.get("sha256", ""))
        ):
            _fail("HF_MANIFEST_INVALID", "Every cached file requires a SHA-256 digest.")
        size = entry.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            _fail("HF_MANIFEST_INVALID", "Every cached file requires its byte length.")
        total += size
    if manifest.get("total_bytes") != total:
        _fail("HF_MANIFEST_INVALID", "Artifact byte totals do not match the inventory.")
    return manifest


def _read_manifest(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
        _fail("HF_CACHE_INVALID", "The cached manifest is missing or invalid.")
    try:
        return validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError) as exc:
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError("HF_CACHE_INVALID", "The cached manifest cannot be read.") from exc


@dataclass(frozen=True)
class Snapshot:
    path: Path
    manifest: dict

    @property
    def artifact_id(self) -> str:
        return self.manifest["artifact_id"]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def verify_snapshot(path: Path, manifest: dict | None = None) -> Snapshot:
    """Read-only verification on every load; no metadata or hash cache."""
    path = Path(path)
    if not path.is_dir() or path.is_symlink():
        _fail("HF_CACHE_MISSING", "Materialize this artifact on the preparation worker first.")
    saved = _read_manifest(path / "manifest.json")
    if manifest is not None:
        validate_manifest(manifest)
        if saved != manifest:
            _fail("HF_CACHE_INVALID", "The cached snapshot differs from the registry manifest.")
    inventory = {}
    for item in path.rglob("*"):
        if item.is_symlink() or not item.resolve().is_relative_to(path.resolve()):
            _fail("HF_CACHE_INVALID", "Symlinks are not allowed in artifact snapshots.")
        if item.is_dir():
            continue
        if not item.is_file():
            _fail("HF_CACHE_INVALID", "Artifact entries must be regular files.")
        name = item.relative_to(path).as_posix()
        if name != "manifest.json":
            inventory[name] = item
        if len(inventory) > MAX_FILES:
            _fail("HF_CACHE_INVALID", "Too many artifact files.")
    if inventory.keys() != saved["files"].keys():
        _fail("HF_CACHE_INVALID", "The cache differs from the manifest file inventory.")
    for name, item in inventory.items():
        expected = saved["files"][name]
        if item.stat().st_size != expected["size_bytes"] or sha256_file(item) != expected["sha256"]:
            _fail("HF_CHECKSUM_MISMATCH", f"Cached artifact file failed verification: {name}.")
    return Snapshot(path.resolve(), saved)


class ArtifactCache:
    def __init__(
        self,
        root: str | Path,
        *,
        max_bytes: int = 40 * 1024**3,
        min_free_bytes: int = 2 * 1024**3,
        retained: Callable[[str], bool] | None = None,
        last_used: Callable[[str], float] | None = None,
    ):
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        self.retained = retained or (lambda artifact_id: False)
        self.last_used = last_used

    def _prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".leases").mkdir(exist_ok=True)

    @contextmanager
    def lease(self, artifact_id: str, manifest: dict | None = None) -> Iterator[Snapshot]:
        """An inference lease requires only a read-only mount of this cache."""
        identity = artifact_name(artifact_id)
        try:
            handle = (self.root / ".leases" / identity).open("rb")
        except FileNotFoundError as exc:
            raise ArtifactError(
                "HF_CACHE_MISSING", "Artifact has not been materialized on this runtime."
            ) from exc
        with handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            try:
                yield verify_snapshot(self.root / identity, manifest)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _usage(self) -> int:
        return sum(
            item.stat().st_size
            for item in self.root.rglob("*")
            if item.is_file() and not item.is_symlink()
        )

    def _evict(self, required: int, *, keep: str) -> None:
        candidates = sorted(
            (
                p
                for p in self.root.iterdir()
                if p.is_dir() and not p.name.startswith(".") and p.name != keep
            ),
            key=lambda p: self.last_used(p.name) if self.last_used else p.stat().st_mtime,
        )
        for candidate in candidates:
            if (
                self._usage() + required <= self.max_bytes
                and shutil.disk_usage(self.root).free - required >= self.min_free_bytes
            ):
                return
            lease_path = self.root / ".leases" / candidate.name
            with lease_path.open("a+b") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                try:
                    if self.retained(candidate.name):
                        continue
                    shutil.rmtree(candidate)
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
        if (
            self._usage() + required > self.max_bytes
            or shutil.disk_usage(self.root).free - required < self.min_free_bytes
        ):
            _fail(
                "HF_CACHE_FULL", "Insufficient cache capacity; active runtime leases are retained."
            )

    def materialize(self, manifest: dict, read_file: Callable[[str, dict], BinaryIO]) -> Snapshot:
        """Preparation worker only. Stream verified object-store bytes into an atomic snapshot.

        ``read_file(relative_path, file_entry)`` returns a binary stream. It is
        injected by hub-fetch, so runtime code cannot obtain network credentials.
        Admission serializes staging to account for temporary and final bytes.
        """
        validate_manifest(manifest)
        identity = manifest["artifact_id"]
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_MANIFEST_BYTES:
            _fail("HF_MANIFEST_INVALID", "The artifact manifest is too large.")
        self._prepare()
        with (self.root / ".admission.lock").open("a+b") as admission:
            fcntl.flock(admission, fcntl.LOCK_EX)
            # Staging is serialized under this lock; leftovers therefore belong
            # to a terminated preparation worker and can never be active leases.
            for abandoned in self.root.glob(".staging-*"):
                if abandoned.is_dir() and not abandoned.is_symlink():
                    shutil.rmtree(abandoned)
            lease_path = self.root / ".leases" / identity
            lease_path.touch(exist_ok=True)
            target = self.root / identity
            if target.exists():
                snapshot = verify_snapshot(target, manifest)
                # Preparations record access through the sole cache writer;
                # inference runtimes keep their mount entirely read-only.
                os.utime(target, None)
                return snapshot
            required = manifest["total_bytes"] + len(encoded)
            self._evict(required, keep=identity)
            stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.root))
            try:
                for name, entry in manifest["files"].items():
                    destination = stage / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    transferred = 0
                    source = read_file(name, entry)
                    try:
                        with destination.open("xb") as output:
                            for block in iter(lambda: source.read(1024 * 1024), b""):
                                transferred += len(block)
                                if transferred > entry["size_bytes"]:
                                    _fail(
                                        "HF_CHECKSUM_MISMATCH",
                                        "The object exceeded its declared size.",
                                    )
                                digest.update(block)
                                output.write(block)
                            output.flush()
                            os.fsync(output.fileno())
                    finally:
                        source.close()
                    if transferred != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]:
                        _fail(
                            "HF_CHECKSUM_MISMATCH", f"Object-store verification failed for {name}."
                        )
                    destination.chmod(0o444)
                with (stage / "manifest.json").open("xb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                (stage / "manifest.json").chmod(0o444)
                os.rename(stage, target)
                directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                return verify_snapshot(target, manifest)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)

    def remove(self, artifact_id: str) -> bool:
        """Preparation/purge worker only. False means an inference still holds it."""
        identity = artifact_name(artifact_id)
        self._prepare()
        with (self.root / ".admission.lock").open("a+b") as admission:
            fcntl.flock(admission, fcntl.LOCK_EX)
            with (self.root / ".leases" / identity).open("a+b") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return False
                try:
                    target = self.root / identity
                    if target.exists():
                        shutil.rmtree(target)
                    return True
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def configured_cache() -> ArtifactCache:
    from app.core.config import settings

    return ArtifactCache(
        settings.hf_cache_dir,
        max_bytes=settings.hf_cache_max_bytes,
        min_free_bytes=settings.hf_cache_min_free_bytes,
        retained=_registry_retained,
        last_used=_registry_last_used,
    )


def _registry_retained(artifact_id: str) -> bool:
    from datetime import UTC, datetime

    from app.db.base import SessionLocal
    from app.models.huggingface import HubArtifactUsage
    from app.services.huggingface.lifecycle import retained_usage

    with SessionLocal() as db:
        usages = db.query(HubArtifactUsage).filter_by(artifact_id=artifact_id).all()
        return any(retained_usage(usage, now=datetime.now(UTC)) for usage in usages)


def _registry_last_used(artifact_id: str) -> float:
    from datetime import UTC

    from app.db.base import SessionLocal
    from app.models.huggingface import HubArtifact

    with SessionLocal() as db:
        artifact = db.get(HubArtifact, artifact_id)
        stamp = (
            (artifact.last_used_at or artifact.imported_at or artifact.created_at)
            if artifact
            else None
        )
        return stamp.replace(tzinfo=UTC).timestamp() if stamp else 0.0
