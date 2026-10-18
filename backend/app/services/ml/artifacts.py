"""Bound and verify producer-anchored portable bundles before loading MLflow."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from app.resources.ml_artifact_contract import (
    CONTRACT_VERSION,
    MAX_ARCHIVE_ENTRIES,
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_FILES,
    PROFILES,
    runtime_versions,
    safe_relative,
)
from app.services.tabular_datasets import TabularError


def _refuse(code: str, message: str, **details):
    raise TabularError(code=code, message=message, status_code=409, details=details or None)


def artifact_fingerprint(artifact: dict) -> str:
    return hashlib.sha256(
        json.dumps(artifact, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def validate_inventory(artifact: dict, *, max_bytes: int = MAX_BUNDLE_BYTES) -> dict:
    files = artifact.get("files")
    if not isinstance(files, dict) or not files or "MLmodel" not in files:
        _refuse("ML_ARTIFACT_UNVERIFIED", "The model has no complete artifact fingerprints.")
    if len(files) > MAX_BUNDLE_FILES:
        _refuse("ML_ARTIFACT_LIMIT", "The artifact has too many files.")
    for name, digest in files.items():
        if (
            not safe_relative(name)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            _refuse("ML_ARTIFACT_UNVERIFIED", "The artifact inventory is invalid.")
    if artifact.get("contract_version") is not None:
        sizes = artifact.get("file_sizes")
        if (
            not isinstance(sizes, dict)
            or set(sizes) != set(files)
            or any(type(value) is not int or value < 0 for value in sizes.values())
            or type(artifact.get("total_bytes")) is not int
            or sum(sizes.values()) != artifact["total_bytes"]
        ):
            _refuse("ML_ARTIFACT_UNVERIFIED", "The artifact sizes are invalid.")
        if artifact["total_bytes"] > max_bytes:
            _refuse("ML_ARTIFACT_LIMIT", "The complete artifact exceeds the reader's byte budget.")
    return files


def verify_bundle(directory: Path, artifact: dict, *, max_bytes: int = MAX_BUNDLE_BYTES) -> None:
    """Check complete fingerprints, retaining the legacy integrity-only utility.

    Serving must call verify_model_bundle, which additionally requires the
    versioned producer contract. Hash-only legacy metadata is not certification.
    """
    files = validate_inventory(artifact, max_bytes=max_bytes)
    if directory.is_symlink():
        _refuse("ML_ARTIFACT_UNVERIFIED", "The artifact root cannot be a link.")
    root = directory.resolve()
    actual = set()
    total = 0
    for path in directory.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            _refuse("ML_ARTIFACT_UNVERIFIED", "Artifact links are not allowed.")
        if not path.is_file():
            continue
        actual.add(path.relative_to(directory).as_posix())
        total += path.stat().st_size
        if len(actual) > MAX_BUNDLE_FILES or total > max_bytes:
            _refuse("ML_ARTIFACT_LIMIT", "The materialized artifact exceeds the reader's budget.")
    if actual != set(files):
        _refuse("ML_ARTIFACT_TAMPERED", "The model bundle contents changed.")
    sizes = artifact.get("file_sizes") or {}
    for name, expected in files.items():
        path = directory / name
        if name in sizes and path.stat().st_size != sizes[name]:
            _refuse(
                "ML_ARTIFACT_TAMPERED", "The model file size differs from its producer's record."
            )
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            _refuse("ML_ARTIFACT_TAMPERED", "The model differs from its training run's bundle.")


def _check_skops_archive(path: Path, *, max_bytes: int) -> None:
    try:
        # ZipFile eagerly allocates ZipInfo objects for the entire directory.
        # Inspect the bounded end record (including ZIP64) first, so a large
        # directory cannot exhaust memory before the entry-count check runs.
        with path.open("rb") as stream:
            end_record = zipfile._EndRecData(stream)
        if end_record is None:
            _refuse("ML_ARTIFACT_UNVERIFIED", "The skops archive has no end record.")
        if end_record[zipfile._ECD_ENTRIES_TOTAL] > MAX_ARCHIVE_ENTRIES or end_record[
            zipfile._ECD_SIZE
        ] > min(max_bytes, 16 * 1024 * 1024):
            _refuse("ML_ARTIFACT_LIMIT", "The skops archive directory exceeds the reader's budget.")
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = [item.filename for item in members]
            if (
                len(members) > MAX_ARCHIVE_ENTRIES
                or sum(item.file_size for item in members) > max_bytes
            ):
                _refuse(
                    "ML_ARTIFACT_LIMIT", "The expanded skops artifact exceeds the reader's budget."
                )
            if (
                len(names) != len(set(names))
                or any(not safe_relative(name) for name in names)
                or any(
                    item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000
                    for item in members
                )
            ):
                _refuse("ML_ARTIFACT_UNVERIFIED", "The skops archive inventory is invalid.")
    except (OSError, zipfile.BadZipFile) as exc:
        _refuse(
            "ML_ARTIFACT_UNVERIFIED",
            "The skops artifact is not a valid archive.",
            reason=type(exc).__name__,
        )


def validate_model_metadata(
    artifact: dict, *, family: str, max_bytes: int = MAX_BUNDLE_BYTES
) -> None:
    """Cheap producer-record checks; never fetch or deserialize model files.

    This is also used by the serving status projection. Passing it does not
    certify bytes: every inference still enters verify_model_bundle.
    """
    if not isinstance(artifact, dict) or artifact.get("contract_version") != CONTRACT_VERSION:
        _refuse(
            "ML_ARTIFACT_LEGACY_UNSUPPORTED",
            "This artifact has no qualified reader contract. Keep its producer runtime or explicitly retrain it; no conversion was performed.",
            legacy=True,
            action="retain_producer_runtime",
        )
    serialization = artifact.get("serialization")
    expected_profile = PROFILES.get((family, serialization))
    if (
        not expected_profile
        or artifact.get("family") != family
        or artifact.get("trust_profile") != expected_profile
    ):
        _refuse("ML_ARTIFACT_UNVERIFIED", "The family, format or trust profile is not qualified.")
    validate_inventory(artifact, max_bytes=max_bytes)
    if serialization == "skops":
        from app.services.ml.artifact_trust import TRUSTED_PROFILES

        recorded = artifact.get("trusted_types")
        if (
            not isinstance(recorded, list)
            or any(not isinstance(name, str) for name in recorded)
            or not set(recorded).issubset(TRUSTED_PROFILES[expected_profile])
        ):
            _refuse(
                "ML_ARTIFACT_UNTRUSTED_TYPES",
                "The artifact requests types outside the qualified reader profile.",
            )


def runtime_digest(runtime: dict) -> str:
    """Canonical identity of a reader runtime, as attestations index it."""
    return hashlib.sha256(
        json.dumps(runtime, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def attested_reader(artifact: dict, current: dict, attested: Iterable = ()) -> Mapping | None:
    """The active attestation letting this reader load this exact artifact.

    ``attested`` is looked up by the caller (this module has no database). It
    is never trusted as given: an entry counts only when it names this exact
    artifact, this producer runtime and this reader runtime. A revoked or
    failed attempt is filtered out by the caller and grants nothing here.
    """
    recorded = artifact.get("runtime") if isinstance(artifact, dict) else None
    if not isinstance(recorded, dict) or not isinstance(current, dict):
        return None
    fingerprint = None
    for item in attested or ():
        if not isinstance(item, Mapping):
            continue
        if fingerprint is None:
            fingerprint = artifact_fingerprint(artifact)
        if (
            item.get("artifact_fingerprint") == fingerprint
            and item.get("producer_runtime") == recorded
            and item.get("reader_runtime") == current
        ):
            return item
    return None


def validate_model_runtime(artifact: dict, current: dict, attested: Iterable = ()) -> None:
    """Producer runtime equality, or a requalification attestation for this reader.

    Equality is unchanged from M4.1. The only other way in is an active
    qualified attestation whose fingerprint, producer and reader runtimes all
    match: reference predictions were replayed under exactly this reader.
    """
    recorded = artifact.get("runtime")
    if (
        isinstance(recorded, dict)
        and isinstance(current, dict)
        and "missing" not in current.values()
        and (recorded == current or attested_reader(artifact, current, attested) is not None)
    ):
        return
    _refuse(
        "ML_ARTIFACT_RUNTIME_MISMATCH",
        "This artifact's producer runtime differs from this reader's and no qualified requalification covers it. Requalify it against its reference predictions, or retrain it.",
        producer=recorded,
        reader=current,
        action="requalify_or_retrain",
    )


def verify_model_bundle(
    directory: Path,
    artifact: dict,
    *,
    family: str,
    max_bytes: int = MAX_BUNDLE_BYTES,
    attested: Iterable = (),
) -> None:
    """The only serving gate; artifact comes from the authorized MLModel row.

    ``attested`` carries the caller's active qualified attestations for this
    row (see ``ml_requalification.attested_runtimes``); empty keeps the strict
    producer-runtime equality.
    """
    validate_model_metadata(artifact, family=family, max_bytes=max_bytes)
    serialization = artifact.get("serialization")
    verify_bundle(directory, artifact, max_bytes=max_bytes)
    validate_model_runtime(artifact, runtime_versions(family, serialization), attested)
    _verify_loader(directory, artifact, family=family, max_bytes=max_bytes)


def verify_requalification_candidate(
    directory: Path, artifact: dict, *, family: str, max_bytes: int = MAX_BUNDLE_BYTES
) -> None:
    """Every serving check except producer-runtime equality.

    Only the isolated requalification harness calls this, to replay reference
    predictions under a different reader before any attestation exists. It
    never serves: the parent compares the outputs and decides. Hashes, sizes,
    trust profile, skops type allowlist and MLmodel loader checks still apply,
    and a reader that lacks a recorded package is still refused.
    """
    validate_model_metadata(artifact, family=family, max_bytes=max_bytes)
    serialization = artifact.get("serialization")
    verify_bundle(directory, artifact, max_bytes=max_bytes)
    current = runtime_versions(family, serialization)
    if "missing" in current.values():
        _refuse(
            "ML_ARTIFACT_RUNTIME_MISMATCH",
            "This reader lacks a package the artifact's runtime records.",
            reader=current,
            action="retrain",
        )
    _verify_loader(directory, artifact, family=family, max_bytes=max_bytes)


def _verify_loader(directory: Path, artifact: dict, *, family: str, max_bytes: int) -> None:
    serialization = artifact.get("serialization")
    expected_profile = PROFILES[(family, serialization)]
    import yaml

    # YAML is inert; this happens after hash and size verification and before
    # MLflow can execute a code file, pickle, joblib or skops reconstruction.
    config = yaml.safe_load((directory / "MLmodel").read_text(encoding="utf-8"))
    flavors = config.get("flavors", {}) if isinstance(config, dict) else {}
    pyfunc = flavors.get("python_function", {})
    if family in {"tabular", "tabular_deep", "clustering", "external"}:
        flavor = flavors.get("sklearn", {})
        name = "model.skops" if serialization == "skops" else "model.pkl"
        if (
            pyfunc.get("loader_module") != "mlflow.sklearn"
            or pyfunc.get("model_path") != name
            or flavor.get("pickled_model") != name
            or flavor.get("serialization_format") != serialization
            or pyfunc.get("code")
            or flavor.get("code")
        ):
            _refuse(
                "ML_ARTIFACT_UNVERIFIED", "The MLflow loader does not match the qualified format."
            )
        declared = flavor.get("skops_trusted_types") or []
    else:
        code_file = {
            "forecasting": "ml_forecast_pyfunc.py",
            "forecasting_deep": "ml_foundation_pyfunc.py",
            "tabular_foundation": "ml_tabicl_pyfunc.py",
        }[family]
        if (
            pyfunc.get("loader_module") != "mlflow.pyfunc.loaders.code_model"
            or Path(str(pyfunc.get("model_code_path", ""))).name != code_file
            or code_file not in artifact["files"]
            or pyfunc.get("code")
            or pyfunc.get("python_model")
        ):
            _refuse("ML_ARTIFACT_UNVERIFIED", "The model code loader is not qualified.")
        dependencies = pyfunc.get("artifacts")
        if not isinstance(dependencies, dict):
            _refuse("ML_ARTIFACT_UNVERIFIED", "The pyfunc artifact inventory is absent.")
        for dependency in dependencies.values():
            name = dependency.get("path") if isinstance(dependency, dict) else None
            if not safe_relative(name) or not any(
                item == name or item.startswith(name + "/") for item in artifact["files"]
            ):
                _refuse(
                    "ML_ARTIFACT_UNVERIFIED", "A pyfunc dependency escapes the verified bundle."
                )
        declared = artifact.get("trusted_types") or []
        if family == "forecasting":
            meta = json.loads((directory / "artifacts/meta.json").read_text())
            if meta.get("serialization") != serialization:
                _refuse(
                    "ML_ARTIFACT_UNVERIFIED",
                    "The forecast serialization differs from its producer contract.",
                )
            declared = meta.get("trusted") or []
    if serialization == "skops":
        from app.services.ml.artifact_trust import TRUSTED_PROFILES

        allowed = TRUSTED_PROFILES[expected_profile]
        recorded_types = artifact.get("trusted_types")
        if (
            not isinstance(declared, list)
            or not isinstance(recorded_types, list)
            or any(not isinstance(name, str) for name in [*declared, *recorded_types])
            or set(declared) != set(recorded_types)
            or not set(declared).issubset(allowed)
        ):
            _refuse(
                "ML_ARTIFACT_UNTRUSTED_TYPES",
                "The artifact requests types outside the reader's qualified profile.",
            )
        paths = [directory / name for name in artifact["files"] if name.endswith(".skops")]
        if len(paths) != 1:
            _refuse("ML_ARTIFACT_UNVERIFIED", "Expected one skops estimator.")
        _check_skops_archive(paths[0], max_bytes=max_bytes)
        import skops.io as sio

        actual_types = set(sio.get_untrusted_types(file=str(paths[0])))
        if actual_types != set(declared) or not actual_types.issubset(allowed):
            _refuse(
                "ML_ARTIFACT_UNTRUSTED_TYPES",
                "The serialized types differ from the approved reader profile.",
            )
