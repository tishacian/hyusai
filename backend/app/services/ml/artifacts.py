"""Verify complete portable deep-model bundles before executing their code."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from app.services.tabular_datasets import TabularError


def verify_bundle(directory: Path, artifact: dict) -> None:
    files = artifact.get("files")
    if not isinstance(files, dict) or not files or "MLmodel" not in files:
        raise TabularError(code="ML_ARTIFACT_UNVERIFIED", message="The model has no complete artifact fingerprints.", status_code=409)
    root = directory.resolve()
    actual = {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()}
    if actual != set(files):
        raise TabularError(code="ML_ARTIFACT_TAMPERED", message="The model bundle contents changed.", status_code=409)
    for name, expected in files.items():
        relative = PurePosixPath(name)
        path = directory / name
        if (relative.is_absolute() or ".." in relative.parts or not isinstance(expected, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or not path.resolve().is_relative_to(root)
                or any(part.is_symlink() for part in [path, *path.parents] if part != root and part.is_relative_to(root))):
            raise TabularError(code="ML_ARTIFACT_UNVERIFIED", message="The artifact fingerprint manifest is invalid.", status_code=409)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise TabularError(code="ML_ARTIFACT_TAMPERED", message="The model differs from the bundle produced by its training run.", status_code=409)
