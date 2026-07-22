#!/usr/bin/env python3
"""Verify the immutable Agentium release/deployment supply-chain contract.

Lot 9 moves production from VM-local builds to three images built once in CI
and selected only by registry digest.  This verifier is intentionally offline:
CI performs the registry/signature operations, writes their evidence, and this
script fails closed unless source, tested images, SBOMs, provenance, signatures
and deployed image digests all describe the same release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
COMPONENTS = ("backend", "frontend", "worker")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_REF_RE = re.compile(r"^[^\s@]+@sha256:([0-9a-f]{64})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseContractError(RuntimeError):
    """An immutable release contract is incomplete or inconsistent."""


def _record(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseContractError(f"{path} must be an object")
    return value


def _required_text(value: Any, path: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReleaseContractError(f"{path} is required")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(
    value: Any,
    *,
    path: str,
    artifact_root: Path | None,
) -> dict[str, str]:
    record = _record(value, path)
    relative = _required_text(record.get("path"), f"{path}.path")
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ReleaseContractError(f"{path}.path must stay inside the artifact root")
    expected = _required_text(record.get("sha256"), f"{path}.sha256").lower()
    if _SHA256_RE.fullmatch(expected) is None:
        raise ReleaseContractError(f"{path}.sha256 must be a SHA-256 digest")
    if artifact_root is not None:
        candidate = (artifact_root / relative).resolve()
        root = artifact_root.resolve()
        if root not in candidate.parents and candidate != root:
            raise ReleaseContractError(f"{path}.path escapes the artifact root")
        if not candidate.is_file():
            raise ReleaseContractError(f"{path}.path does not exist")
        actual = _sha256_file(candidate)
        if actual != expected:
            raise ReleaseContractError(f"{path} checksum mismatch")
    return {"path": relative, "sha256": expected}


def _json_artifact(
    value: Any,
    *,
    path: str,
    artifact_root: Path | None,
) -> tuple[dict[str, str], Any]:
    """Load one content-addressed JSON artifact from the trusted job output.

    A checksum declared next to an absent artifact is not evidence.  Semantic
    release verification therefore requires the artifact root and validates
    the bytes after the existing path-confinement and checksum checks.
    """

    artifact = _artifact(value, path=path, artifact_root=artifact_root)
    if artifact_root is None:
        raise ReleaseContractError("artifact_root is required for semantic release verification")
    candidate = (artifact_root.resolve() / artifact["path"]).resolve()
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseContractError(f"{path} must be a valid JSON artifact") from exc
    return artifact, payload


def _verify_sbom(payload: Any, *, component: str) -> str:
    """Accept only a recognizable CycloneDX or SPDX JSON document."""

    document = _record(payload, f"images.{component}.sbom document")
    if document.get("bomFormat") == "CycloneDX":
        version = _required_text(
            document.get("specVersion"),
            f"images.{component}.sbom.specVersion",
        )
        return f"cyclonedx-{version}"
    spdx_version = str(document.get("spdxVersion") or "").strip()
    if spdx_version.startswith("SPDX-"):
        return spdx_version.lower()
    raise ReleaseContractError(
        f"images.{component}.sbom must be a CycloneDX or SPDX JSON document"
    )


def _verify_provenance(
    payload: Any,
    *,
    component: str,
    repository: str,
    digest: str,
    git_sha: str,
) -> None:
    """Bind an in-toto/SLSA statement to this exact source and OCI subject."""

    document = _record(payload, f"images.{component}.provenance document")
    if document.get("_type") != "https://in-toto.io/Statement/v1":
        raise ReleaseContractError(f"images.{component}.provenance is not in-toto Statement v1")
    if document.get("predicateType") != "https://slsa.dev/provenance/v1":
        raise ReleaseContractError(f"images.{component}.provenance is not SLSA provenance v1")
    subjects = document.get("subject")
    if not isinstance(subjects, list) or not any(
        isinstance(subject, Mapping)
        and subject.get("name") == repository
        and isinstance(subject.get("digest"), Mapping)
        and subject["digest"].get("sha256") == digest
        for subject in subjects
    ):
        raise ReleaseContractError(
            f"images.{component}.provenance does not name the exact OCI digest"
        )
    predicate = _record(document.get("predicate"), f"images.{component}.provenance.predicate")
    build_definition = _record(
        predicate.get("buildDefinition"),
        f"images.{component}.provenance.predicate.buildDefinition",
    )
    external = _record(
        build_definition.get("externalParameters"),
        f"images.{component}.provenance.predicate.buildDefinition.externalParameters",
    )
    if external.get("git_sha") != git_sha or external.get("component") != component:
        raise ReleaseContractError(
            f"images.{component}.provenance source or component differs from the release"
        )


def _verify_cosign_result(
    payload: Any,
    *,
    component: str,
    repository: str,
    digest: str,
    issuer: str,
    identity: str,
) -> None:
    """Validate the JSON emitted by ``cosign verify --output=json``.

    Cryptographic and transparency-log verification remains Cosign's job.  The
    offline contract nevertheless refuses a bare ``verified: true`` assertion:
    it requires the content-addressed verifier output to bind repository,
    manifest digest, OIDC issuer and certificate identity together.
    """

    rows = payload if isinstance(payload, list) else []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        critical = row.get("critical")
        optional = row.get("optional")
        if not isinstance(critical, Mapping) or not isinstance(optional, Mapping):
            continue
        image = critical.get("image")
        signed_identity = critical.get("identity")
        if not isinstance(image, Mapping) or not isinstance(signed_identity, Mapping):
            continue
        if (
            image.get("docker-manifest-digest") == f"sha256:{digest}"
            and signed_identity.get("docker-reference") == repository
            and optional.get("Issuer") == issuer
            and optional.get("Subject") == identity
        ):
            return
    raise ReleaseContractError(
        f"images.{component}.signature verification output does not match the release subject"
    )


def _image_reference(value: Any, path: str) -> tuple[str, str]:
    reference = _required_text(value, path)
    match = _DIGEST_REF_RE.fullmatch(reference)
    if match is None:
        raise ReleaseContractError(f"{path} must be a registry reference pinned by sha256 digest")
    return reference, match.group(1)


def verify_release_contract(
    release: Mapping[str, Any],
    *,
    expected_cosign_issuer: str,
    expected_cosign_identity: str,
    deployment: Mapping[str, Any] | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Verify build-once/test/deploy identity and return a compact receipt."""

    trusted_issuer = _required_text(expected_cosign_issuer, "expected_cosign_issuer")
    trusted_identity = _required_text(expected_cosign_identity, "expected_cosign_identity")
    if not trusted_issuer.startswith("https://"):
        raise ReleaseContractError("expected_cosign_issuer must be an HTTPS trust anchor")

    if release.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseContractError("unsupported release schema_version")
    source = _record(release.get("source"), "source")
    git_sha = _required_text(source.get("git_sha"), "source.git_sha").lower()
    if _GIT_SHA_RE.fullmatch(git_sha) is None:
        raise ReleaseContractError("source.git_sha must be a full lowercase Git SHA")
    pipeline_id = _required_text(source.get("pipeline_id"), "source.pipeline_id")
    build_job_id = _required_text(source.get("build_job_id"), "source.build_job_id")

    images = _record(release.get("images"), "images")
    if set(images) != set(COMPONENTS):
        raise ReleaseContractError("images must contain exactly backend, frontend and worker")
    tested = _record(release.get("tested"), "tested")
    if tested.get("git_sha") != git_sha:
        raise ReleaseContractError("tested.git_sha differs from source.git_sha")
    tested_images = _record(tested.get("images"), "tested.images")
    if set(tested_images) != set(COMPONENTS):
        raise ReleaseContractError("tested.images must contain exactly all components")

    if artifact_root is None:
        raise ReleaseContractError("artifact_root is required for release verification")

    normalized_images: dict[str, dict[str, Any]] = {}
    references: set[str] = set()
    build_ids: set[str] = set()
    artifact_paths: set[str] = set()
    for component in COMPONENTS:
        image = _record(images[component], f"images.{component}")
        reference, digest = _image_reference(
            image.get("reference"), f"images.{component}.reference"
        )
        if reference in references:
            raise ReleaseContractError("components must use distinct image references")
        references.add(reference)
        if image.get("revision") != git_sha:
            raise ReleaseContractError(f"images.{component}.revision differs from source Git SHA")
        build_id = _required_text(image.get("build_id"), f"images.{component}.build_id")
        if build_id in build_ids:
            raise ReleaseContractError("each component must have one distinct CI build id")
        build_ids.add(build_id)
        if int(image.get("build_occurrences") or 0) != 1:
            raise ReleaseContractError(f"images.{component}.build_occurrences must equal one")

        repository = reference.rsplit("@", 1)[0]
        sbom, sbom_payload = _json_artifact(
            image.get("sbom"),
            path=f"images.{component}.sbom",
            artifact_root=artifact_root,
        )
        sbom_format = _verify_sbom(sbom_payload, component=component)
        provenance, provenance_payload = _json_artifact(
            image.get("provenance"),
            path=f"images.{component}.provenance",
            artifact_root=artifact_root,
        )
        _verify_provenance(
            provenance_payload,
            component=component,
            repository=repository,
            digest=digest,
            git_sha=git_sha,
        )
        signature = _record(image.get("signature"), f"images.{component}.signature")
        if signature.get("verified") is not True:
            raise ReleaseContractError(f"images.{component}.signature is not verified")
        signature_tool = _required_text(signature.get("tool"), f"images.{component}.signature.tool")
        if signature_tool != "cosign":
            raise ReleaseContractError(f"images.{component}.signature.tool must be cosign")
        issuer = _required_text(signature.get("issuer"), f"images.{component}.signature.issuer")
        identity = _required_text(
            signature.get("identity"), f"images.{component}.signature.identity"
        )
        if issuer != trusted_issuer:
            raise ReleaseContractError(
                f"images.{component}.signature.issuer differs from the configured trust anchor"
            )
        if identity != trusted_identity:
            raise ReleaseContractError(
                f"images.{component}.signature.identity differs from the configured trust anchor"
            )
        verification, verification_payload = _json_artifact(
            signature.get("verification"),
            path=f"images.{component}.signature.verification",
            artifact_root=artifact_root,
        )
        _verify_cosign_result(
            verification_payload,
            component=component,
            repository=repository,
            digest=digest,
            issuer=trusted_issuer,
            identity=trusted_identity,
        )
        for artifact in (sbom, provenance, verification):
            if artifact["path"] in artifact_paths:
                raise ReleaseContractError("release evidence artifacts must use distinct paths")
            artifact_paths.add(artifact["path"])
        tested_reference, _ = _image_reference(
            tested_images.get(component), f"tested.images.{component}"
        )
        if tested_reference != reference:
            raise ReleaseContractError(f"tested {component} image differs from release image")
        normalized_images[component] = {
            "reference": reference,
            "digest": f"sha256:{digest}",
            "revision": git_sha,
            "build_id": build_id,
            "sbom": {**sbom, "format": sbom_format},
            "provenance": provenance,
            "signature": {
                "tool": signature_tool,
                "issuer": trusted_issuer,
                "identity": trusted_identity,
                "verified": True,
                "verification": verification,
            },
        }

    deployment_environment = None
    if deployment is not None:
        if deployment.get("git_sha") != git_sha:
            raise ReleaseContractError("deployment.git_sha differs from release source")
        deployment_environment = _required_text(
            deployment.get("environment"), "deployment.environment"
        )
        deployed_images = _record(deployment.get("images"), "deployment.images")
        if set(deployed_images) != set(COMPONENTS):
            raise ReleaseContractError("deployment.images must contain exactly all components")
        for component in COMPONENTS:
            deployed_reference, _ = _image_reference(
                deployed_images.get(component), f"deployment.images.{component}"
            )
            if deployed_reference != normalized_images[component]["reference"]:
                raise ReleaseContractError(
                    f"deployed {component} image differs from tested release image"
                )

    canonical = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "git_sha": git_sha,
                "pipeline_id": pipeline_id,
                "build_job_id": build_job_id,
            },
            "images": normalized_images,
            "tested": {"git_sha": git_sha, "images": dict(tested_images)},
            "deployment_environment": deployment_environment,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": True,
        "git_sha": git_sha,
        "pipeline_id": pipeline_id,
        "build_job_id": build_job_id,
        "deployment_environment": deployment_environment,
        "images": {
            component: normalized_images[component]["reference"] for component in COMPONENTS
        },
        "contract_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _load(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseContractError(f"cannot read JSON: {path}") from exc
    return _record(payload, str(path))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--deployment", type=Path)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--cosign-issuer", required=True)
    parser.add_argument("--cosign-identity", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_release_contract(
            _load(args.release),
            expected_cosign_issuer=args.cosign_issuer,
            expected_cosign_identity=args.cosign_identity,
            deployment=_load(args.deployment) if args.deployment else None,
            artifact_root=args.artifact_root,
        )
    except ReleaseContractError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
