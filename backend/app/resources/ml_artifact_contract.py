"""Producer-owned portable artifact contract; only standard-library imports.

The result belongs in the authorized model row, not in a self-trusting file in
the downloaded bundle. Legacy bundles are never retroactively certified.
"""

from __future__ import annotations

import hashlib
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

CONTRACT_VERSION = 1
MAX_BUNDLE_FILES = 2048
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 100_000

PROFILES = {
    ("tabular", "skops"): "tabular-skops-v1",
    # M4.3: imported sklearn pipelines; the reader owns the type allowlist.
    ("external", "skops"): "external-sklearn-skops-v1",
    ("clustering", "skops"): "clustering-skops-v1",
    ("tabular_deep", "cloudpickle"): "embedding-cloudpickle-v1",
    ("forecasting", "skops"): "forecast-skops-v1",
    ("forecasting", "joblib"): "forecast-joblib-v1",
    ("forecasting_deep", "json"): "foundation-json-v1",
    # v2 requires the bundled adapter to honor the reader's CPU envelope.
    # v1 embedded an older runtime that could restore a larger thread pool.
    ("tabular_foundation", "json+safetensors"): "tabicl-json-safetensors-v2",
}


def safe_relative(name: str) -> bool:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and path.as_posix() == name
        and all(part not in {"", ".", ".."} and ":" not in part for part in path.parts)
    )


def runtime_versions(family: str, serialization: str) -> dict[str, str]:
    names = ["mlflow", "scikit-learn", "numpy", "scipy", "pandas"]
    if family in {"tabular", "tabular_deep"}:
        names.append("skrub")
    if serialization == "skops":
        names.append("skops")
    if serialization in {"joblib", "cloudpickle"}:
        names.append(serialization)
    if family.startswith("forecasting"):
        names.append("skforecast")
    if family in {"tabular_deep", "forecasting_deep"}:
        names.extend(["torch", "transformers", "safetensors"])
        names.append("sentence-transformers" if family == "tabular_deep" else "chronos-forecasting")
    if family == "tabular_foundation":
        names.extend(["torch", "tabicl", "safetensors"])
    result = {"python": ".".join(platform.python_version_tuple()[:2])}
    for name in names:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "missing"
    return result


def build_artifact_contract(
    directory, *, family: str, serialization: str, trusted_types=()
) -> dict:
    """Snapshot the completed export in the training producer's result."""
    root = Path(directory)
    files, sizes = {}, {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Artifact bundles cannot contain symlinks")
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if not safe_relative(name):
            raise ValueError("Invalid artifact path")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        files[name] = digest.hexdigest()
        sizes[name] = path.stat().st_size
    if "MLmodel" not in files or len(files) > MAX_BUNDLE_FILES:
        raise ValueError("Incomplete or excessive artifact inventory")
    return {
        "contract_version": CONTRACT_VERSION,
        "family": family,
        "serialization": serialization,
        "trust_profile": PROFILES[(family, serialization)],
        "runtime": runtime_versions(family, serialization),
        "trusted_types": sorted(set(trusted_types)),
        "files": files,
        "file_sizes": sizes,
        "total_bytes": sum(sizes.values()),
    }
