"""Utilities for mirroring the local ObjectStore into S3-compatible storage."""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


CHUNK_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True)
class ObjectStoreEntry:
    key: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ObjectStoreDiff:
    missing_target: list[str]
    extra_target: list[str]
    mismatched: list[str]

    @property
    def strict_match(self) -> bool:
        return not self.missing_target and not self.extra_target and not self.mismatched


@dataclass(frozen=True)
class ObjectStoreMirrorReport:
    source_count: int
    source_bytes: int
    target_count: int
    target_bytes: int
    uploaded: list[str]
    overwritten: list[str]
    skipped: list[str]
    diff: ObjectStoreDiff
    dry_run: bool

    @property
    def strict_match(self) -> bool:
        return self.diff.strict_match

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["strict_match"] = self.strict_match
        return payload


def _clean_key(key: str) -> str:
    path = PurePosixPath(str(key).replace("\\", "/"))
    parts = [p for p in path.parts if p not in ("", "/", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"Invalid object key: {key!r}")
    return "/".join(parts)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_remote_file(fs: Any, path: str) -> str:
    digest = hashlib.sha256()
    with fs.open(path, "rb") as src:
        for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_object_manifest(base_path: Path, prefix: str = "") -> list[ObjectStoreEntry]:
    """Return a strict manifest for files below a local ObjectStore root."""
    base = base_path.resolve()
    clean_prefix = _clean_key(prefix) if prefix else ""
    root = (base / clean_prefix).resolve() if clean_prefix else base
    if base not in root.parents and root != base:
        raise ValueError(f"Prefix escapes object store root: {prefix!r}")
    if not root.exists():
        return []
    files: Iterable[Path]
    if root.is_file():
        files = [root]
    else:
        files = (path for path in root.rglob("*") if path.is_file())
    entries = [
        ObjectStoreEntry(
            key=path.relative_to(base).as_posix(),
            size=path.stat().st_size,
            sha256=_hash_file(path),
        )
        for path in files
    ]
    return sorted(entries, key=lambda item: item.key)


def compare_manifests(
    source: Iterable[ObjectStoreEntry],
    target: Iterable[ObjectStoreEntry],
) -> ObjectStoreDiff:
    source_by_key = {entry.key: entry for entry in source}
    target_by_key = {entry.key: entry for entry in target}
    source_keys = set(source_by_key)
    target_keys = set(target_by_key)
    common = source_keys & target_keys
    return ObjectStoreDiff(
        missing_target=sorted(source_keys - target_keys),
        extra_target=sorted(target_keys - source_keys),
        mismatched=sorted(
            key
            for key in common
            if source_by_key[key].size != target_by_key[key].size
            or source_by_key[key].sha256 != target_by_key[key].sha256
        ),
    )


def build_s3_filesystem(
    *,
    endpoint_url: str | None,
    access_key: str | None,
    secret_key: str | None,
) -> Any:
    try:
        import fsspec  # type: ignore
    except ImportError as exc:
        raise RuntimeError("fsspec and s3fs are required for S3 object-store migration") from exc

    kwargs: dict[str, Any] = {}
    if endpoint_url:
        kwargs["client_kwargs"] = {"endpoint_url": endpoint_url}
    return fsspec.filesystem("s3", key=access_key, secret=secret_key, **kwargs)


def ensure_s3_bucket(fs: Any, bucket: str) -> None:
    if not fs.exists(bucket):
        fs.mkdir(bucket)


def _remote_path(bucket: str, key: str) -> str:
    return f"{bucket}/{_clean_key(key)}"


def s3_object_manifest(fs: Any, bucket: str, prefix: str = "") -> list[ObjectStoreEntry]:
    clean_prefix = _clean_key(prefix) if prefix else ""
    root = f"{bucket}/{clean_prefix}" if clean_prefix else bucket
    if not fs.exists(root):
        return []
    entries: list[ObjectStoreEntry] = []
    for raw_path in sorted(str(path) for path in fs.find(root)):
        if raw_path.rstrip("/") == bucket:
            continue
        if not raw_path.startswith(f"{bucket}/"):
            continue
        try:
            info = fs.info(raw_path)
        except FileNotFoundError:
            continue
        if str(info.get("type", "file")) == "directory":
            continue
        key = raw_path[len(bucket) + 1 :]
        size = int(info.get("size") or fs.size(raw_path))
        entries.append(
            ObjectStoreEntry(
                key=key,
                size=size,
                sha256=_hash_remote_file(fs, raw_path),
            )
        )
    return sorted(entries, key=lambda item: item.key)


def mirror_local_to_s3(
    *,
    source_base_path: Path,
    fs: Any,
    bucket: str,
    prefix: str = "",
    dry_run: bool = True,
) -> ObjectStoreMirrorReport:
    source = local_object_manifest(source_base_path, prefix=prefix)
    target = s3_object_manifest(fs, bucket, prefix=prefix)
    target_by_key = {entry.key: entry for entry in target}

    uploaded: list[str] = []
    overwritten: list[str] = []
    skipped: list[str] = []
    for entry in source:
        target_entry = target_by_key.get(entry.key)
        if target_entry and target_entry.size == entry.size and target_entry.sha256 == entry.sha256:
            skipped.append(entry.key)
            continue

        if target_entry:
            overwritten.append(entry.key)
        else:
            uploaded.append(entry.key)

        if dry_run:
            continue
        local_path = (source_base_path / entry.key).resolve()
        remote = _remote_path(bucket, entry.key)
        with local_path.open("rb") as src, fs.open(remote, "wb") as dst:
            shutil.copyfileobj(src, dst, length=CHUNK_SIZE)

    final_target = target if dry_run else s3_object_manifest(fs, bucket, prefix=prefix)
    diff = compare_manifests(source, final_target)
    return ObjectStoreMirrorReport(
        source_count=len(source),
        source_bytes=sum(entry.size for entry in source),
        target_count=len(final_target),
        target_bytes=sum(entry.size for entry in final_target),
        uploaded=uploaded,
        overwritten=overwritten,
        skipped=skipped,
        diff=diff,
        dry_run=dry_run,
    )
