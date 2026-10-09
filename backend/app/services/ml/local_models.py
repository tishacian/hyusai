"""Allowlisted, operator-provisioned model files, with no provider imports.

The API reads public provenance from the worker heartbeat. Only the deep worker
opens these files; every fit verifies their bytes again, even when its heartbeat
has a cached verification. Provisioning is explicit and never downloads a model.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL_SPECS = {
    "chronos-2-small": {"kind": "forecasting", "upstream_id": "autogluon/chronos-2-small"},
    "multilingual-minilm": {
        "kind": "embedding",
        "upstream_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    },
}
MAX_FILES = 10_000


class LocalModelError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LocalModel:
    path: Path
    model_id: str
    revision: str
    kind: str
    fingerprint: str
    upstream_id: str
    files: dict[str, str]

    def public(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "kind": self.kind,
            "revision": self.revision,
            "upstream_id": self.upstream_id,
            "fingerprint": self.fingerprint,
        }


def _root(models_dir: str | Path | None) -> Path:
    if models_dir is None:
        from app.core.config import settings
        models_dir = settings.ml_deep_models_dir
    return Path(models_dir).resolve()


def _invalid(message: str) -> None:
    raise LocalModelError("ML_DEEP_MODEL_INVALID", message)


def _inside(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        _invalid("Model files must use relative POSIX paths.")
    relative = Path(raw)
    if relative.is_absolute() or any(part in (".", "..") for part in raw.split("/")):
        _invalid("Model files must remain inside their provisioned directory.")
    path = root / relative
    if not path.resolve().is_relative_to(root):
        _invalid("A model symlink leaves its provisioned directory.")
    return path


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(path: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in path.rglob("*"):
        if not item.resolve().is_relative_to(path.resolve()):
            _invalid("A model symlink leaves its provisioned directory.")
        # A symlinked directory can hide an unchecked subtree from rglob.
        if item.is_symlink() and item.is_dir():
            _invalid("Symlinked model directories are not supported.")
        if item.is_dir():
            continue
        if not item.is_file():
            _invalid("A model entry is not a regular file.")
        result[item.relative_to(path).as_posix()] = item
        if len(result) > MAX_FILES:
            _invalid("Too many files in a provisioned model.")
    return result


def _manifest(root: Path) -> dict:
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise LocalModelError("ML_DEEP_MODEL_MISSING", "No local model manifest is provisioned.")
    if not manifest.resolve().is_relative_to(root) or manifest.stat().st_size > 1024 * 1024:
        _invalid("Invalid local model manifest.")
    try:
        content = json.loads(manifest.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        _invalid("The local model manifest cannot be read.")
    if not isinstance(content, dict) or content.get("version") != 1 or not isinstance(content.get("models"), dict):
        _invalid("Unsupported local model manifest.")
    return content


def resolve_model(model_id: str, *, kind: str, models_dir: str | Path | None = None) -> LocalModel:
    """Verify all bytes and return the local model. No network or cached hashes."""
    try:
        return _resolve_model(model_id, kind=kind, models_dir=models_dir)
    except (OSError, RuntimeError) as exc:
        raise LocalModelError("ML_DEEP_MODEL_INVALID", "The provisioned model files cannot be read.") from exc


def _resolve_model(model_id: str, *, kind: str, models_dir: str | Path | None) -> LocalModel:
    expected = MODEL_SPECS.get(model_id)
    if expected is None or expected["kind"] != kind:
        _invalid("This model is not offered for the requested capability.")
    root = _root(models_dir)
    entry = _manifest(root)["models"].get(model_id)
    if entry is None:
        raise LocalModelError("ML_DEEP_MODEL_MISSING", f"The local model {model_id} is not provisioned.")
    if not isinstance(entry, dict) or entry.get("kind") != kind or entry.get("upstream_id") != expected["upstream_id"]:
        _invalid("The provisioned model does not match the allowed model identity.")
    revision = entry.get("revision")
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40,64}", revision) is None:
        _invalid("A model requires an immutable upstream revision.")
    path = _inside(root, entry.get("path"))
    if not path.is_dir() or path.is_symlink():
        _invalid("The provisioned model directory is missing or is a symlink.")
    files = entry.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        _invalid("The model manifest must list every file hash.")
    inventory = _inventory(path)
    if inventory.keys() != files.keys():
        _invalid("The model directory differs from its declared file inventory.")
    for name, expected_hash in files.items():
        file_path = _inside(path.resolve(), name)
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            _invalid("The model manifest contains an invalid file hash.")
        if file_hash(file_path) != expected_hash:
            _invalid(f"A provisioned model file has changed: {name}.")
    fingerprint = hashlib.sha256(json.dumps({"model_id": model_id, "revision": revision, "files": files}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return LocalModel(path.resolve(), model_id, revision, kind, fingerprint, expected["upstream_id"], dict(files))


def _stamp(root: Path) -> tuple:
    """Metadata for heartbeat caching only; a fit always hashes all bytes."""
    if not root.is_dir():
        return ()
    paths = [root / "manifest.json"]
    try:
        for entry in _manifest(root)["models"].values():
            if isinstance(entry, dict):
                path = _inside(root, entry.get("path"))
                paths.extend(_inventory(path).values())
    except (LocalModelError, OSError):
        # Cache malformed manifests until the operator changes their metadata.
        pass
    stamp = []
    for path in paths:
        try:
            stat = path.stat()
            stamp.append((str(path), stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        except OSError:
            stamp.append((str(path), None))
    return tuple(sorted(stamp))


@lru_cache(maxsize=4)
def _verified_descriptors(root: str, stamp: tuple) -> dict[str, dict[str, str]]:
    del stamp
    result = {}
    for model_id, spec in MODEL_SPECS.items():
        try:
            result[model_id] = resolve_model(model_id, kind=spec["kind"], models_dir=root).public()
        except (LocalModelError, OSError):
            continue
    return result


def local_model_descriptors(models_dir: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Verified public metadata for the heartbeat; absent/invalid entries omitted."""
    root = _root(models_dir)
    # Return a copy: callers must never alter the cache's verified descriptors.
    return {key: dict(value) for key, value in _verified_descriptors(str(root), _stamp(root)).items()}
