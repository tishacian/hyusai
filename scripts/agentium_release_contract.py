#!/usr/bin/env python3
"""Verify the immutable Agentium release/deployment supply-chain contract.

Lot 9 moves production from VM-local builds to three images built once in CI
and selected only by registry digest.  Offline verification is the default: CI
performs the registry/signature operations and writes content-addressed evidence.
An explicit flag can re-run Cosign against the registry.  The script fails
closed unless source, tested images, signed SBOM/provenance attestations, image
signatures and deployed image digests all describe the same release.

Offline mode performs structural and semantic validation, not cryptographic
signature verification.  Its receipt is authoritative only when the artifacts
come from the protected job that ran Cosign.  Only explicit live mode re-runs
Cosign and cryptographically revalidates the registry objects.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, NamedTuple

SCHEMA_VERSION = 2
COMPONENTS = ("backend", "frontend", "worker")
IN_TOTO_STATEMENT_TYPES = {
    "https://in-toto.io/Statement/v0.1",
    "https://in-toto.io/Statement/v1",
}
SLSA_PROVENANCE_V1 = "https://slsa.dev/provenance/v1"
DSSE_PAYLOAD_TYPE = "application/vnd.in-toto+json"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_REF_RE = re.compile(r"^[^\s@]+@sha256:([0-9a-f]{64})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DOCUMENT_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+$")
_CYCLONEDX_SERIAL_RE = re.compile(
    r"^urn:uuid:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class ReleaseContractError(RuntimeError):
    """An immutable release contract is incomplete or inconsistent."""


class CosignCommandResult(NamedTuple):
    """Result returned by an explicitly supplied Cosign command runner."""

    returncode: int
    stdout: str
    stderr: str = ""


CosignCommandRunner = Callable[[tuple[str, ...]], CosignCommandResult]


def _record(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseContractError(f"{path} must be an object")
    return value


def _required_text(value: Any, path: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReleaseContractError(f"{path} is required")
    return text


def _timestamp(value: Any, path: str) -> datetime:
    rendered = _required_text(value, path)
    try:
        parsed = datetime.fromisoformat(rendered.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseContractError(f"{path} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ReleaseContractError(f"{path} must include a timezone")
    return parsed.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseContractError(
            "release evidence contains non-canonical JSON"
        ) from exc


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
        raise ReleaseContractError(
            "artifact_root is required for semantic release verification"
        )
    candidate = (artifact_root.resolve() / artifact["path"]).resolve()
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseContractError(f"{path} must be a valid JSON artifact") from exc
    return artifact, payload


def _parse_cosign_json(value: str, *, path: str) -> Any:
    """Parse Cosign JSON output without assuming array versus JSONL output."""

    rendered = value.strip()
    if not rendered:
        raise ReleaseContractError(f"{path} is empty")
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        rows: list[Any] = []
        for line_number, line in enumerate(rendered.splitlines(), start=1):
            candidate = line.strip()
            if not candidate:
                continue
            try:
                rows.append(json.loads(candidate))
            except json.JSONDecodeError as exc:
                raise ReleaseContractError(
                    f"{path} line {line_number} is not valid Cosign JSON"
                ) from exc
        if not rows:
            raise ReleaseContractError(f"{path} has no Cosign JSON records")
        return rows


def _cosign_json_artifact(
    value: Any,
    *,
    path: str,
    artifact_root: Path | None,
) -> tuple[dict[str, str], Any]:
    artifact = _artifact(value, path=path, artifact_root=artifact_root)
    if artifact_root is None:
        raise ReleaseContractError(
            "artifact_root is required for semantic release verification"
        )
    candidate = (artifact_root.resolve() / artifact["path"]).resolve()
    try:
        payload = _parse_cosign_json(candidate.read_text(encoding="utf-8"), path=path)
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseContractError(f"{path} must be readable Cosign JSON") from exc
    return artifact, payload


def _verify_sbom(payload: Any, *, component: str) -> tuple[str, frozenset[str]]:
    """Accept a populated, component-bound CycloneDX or SPDX document."""

    document = _record(payload, f"images.{component}.sbom document")
    if document.get("bomFormat") == "CycloneDX":
        version = _required_text(
            document.get("specVersion"),
            f"images.{component}.sbom.specVersion",
        )
        if _DOCUMENT_VERSION_RE.fullmatch(version) is None:
            raise ReleaseContractError(
                f"images.{component}.sbom.specVersion must be a numeric major.minor version"
            )
        serial_number = _required_text(
            document.get("serialNumber"),
            f"images.{component}.sbom.serialNumber",
        )
        if _CYCLONEDX_SERIAL_RE.fullmatch(serial_number) is None:
            raise ReleaseContractError(
                f"images.{component}.sbom.serialNumber must be a UUID URN"
            )
        document_version = document.get("version")
        if (
            not isinstance(document_version, int)
            or isinstance(document_version, bool)
            or document_version < 1
        ):
            raise ReleaseContractError(
                f"images.{component}.sbom.version must be a positive integer"
            )
        metadata = _record(
            document.get("metadata"), f"images.{component}.sbom.metadata"
        )
        root = _record(
            metadata.get("component"),
            f"images.{component}.sbom.metadata.component",
        )
        root_ref = _required_text(
            root.get("bom-ref"),
            f"images.{component}.sbom.metadata.component.bom-ref",
        )
        if root.get("name") != component or root.get("type") not in {
            "application",
            "container",
        }:
            raise ReleaseContractError(
                f"images.{component}.sbom root component differs from the release component"
            )
        components = document.get("components")
        if not isinstance(components, list) or not components:
            raise ReleaseContractError(
                f"images.{component}.sbom.components must contain dependencies"
            )
        component_refs: list[str] = []
        for index, raw_component in enumerate(components):
            item = _record(
                raw_component,
                f"images.{component}.sbom.components[{index}]",
            )
            reference = _required_text(
                item.get("bom-ref"),
                f"images.{component}.sbom.components[{index}].bom-ref",
            )
            _required_text(
                item.get("name"), f"images.{component}.sbom.components[{index}].name"
            )
            _required_text(
                item.get("version"),
                f"images.{component}.sbom.components[{index}].version",
            )
            if not str(item.get("purl") or "").strip() and not isinstance(
                item.get("hashes"), list
            ):
                raise ReleaseContractError(
                    f"images.{component}.sbom.components[{index}] requires purl or hashes"
                )
            component_refs.append(reference)
        if len(component_refs) != len(set(component_refs)):
            raise ReleaseContractError(
                f"images.{component}.sbom component references must be unique"
            )
        dependencies = document.get("dependencies")
        root_edges = (
            [
                row
                for row in dependencies
                if isinstance(row, Mapping) and row.get("ref") == root_ref
            ]
            if isinstance(dependencies, list)
            else []
        )
        if len(root_edges) != 1 or set(root_edges[0].get("dependsOn") or ()) != set(
            component_refs
        ):
            raise ReleaseContractError(
                f"images.{component}.sbom dependency graph must link the root to every component"
            )
        return (
            f"cyclonedx-{version}",
            frozenset({f"https://cyclonedx.org/bom/v{version}"}),
        )
    spdx_version = str(document.get("spdxVersion") or "").strip()
    if spdx_version.startswith("SPDX-"):
        version = spdx_version.removeprefix("SPDX-")
        if _DOCUMENT_VERSION_RE.fullmatch(version) is None:
            raise ReleaseContractError(
                f"images.{component}.sbom.spdxVersion must be SPDX-major.minor"
            )
        if (
            document.get("SPDXID") != "SPDXRef-DOCUMENT"
            or document.get("dataLicense") != "CC0-1.0"
            or not _required_text(document.get("name"), f"images.{component}.sbom.name")
            or not _required_text(
                document.get("documentNamespace"),
                f"images.{component}.sbom.documentNamespace",
            ).startswith("https://")
        ):
            raise ReleaseContractError(
                f"images.{component}.sbom SPDX document identity is incomplete"
            )
        creation = _record(
            document.get("creationInfo"),
            f"images.{component}.sbom.creationInfo",
        )
        _timestamp(
            creation.get("created"), f"images.{component}.sbom.creationInfo.created"
        )
        creators = creation.get("creators")
        if not isinstance(creators, list) or not creators:
            raise ReleaseContractError(
                f"images.{component}.sbom.creationInfo.creators is required"
            )
        packages = document.get("packages")
        if not isinstance(packages, list) or not packages:
            raise ReleaseContractError(
                f"images.{component}.sbom.packages must contain dependencies"
            )
        for index, package in enumerate(packages):
            row = _record(package, f"images.{component}.sbom.packages[{index}]")
            _required_text(
                row.get("SPDXID"), f"images.{component}.sbom.packages[{index}].SPDXID"
            )
            _required_text(
                row.get("name"), f"images.{component}.sbom.packages[{index}].name"
            )
            _required_text(
                row.get("versionInfo"),
                f"images.{component}.sbom.packages[{index}].versionInfo",
            )
        return (
            spdx_version.lower(),
            frozenset(
                {
                    "https://spdx.dev/Document",
                    f"https://spdx.dev/Document/v{version}",
                }
            ),
        )
    raise ReleaseContractError(
        f"images.{component}.sbom must be a CycloneDX or SPDX JSON document"
    )


def _verify_exact_statement_subject(
    document: Mapping[str, Any],
    *,
    path: str,
    repository: str,
    digest: str,
) -> None:
    subjects = document.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise ReleaseContractError(f"{path} must name exactly one OCI subject")
    subject = _record(subjects[0], f"{path}.subject[0]")
    subject_digest = _record(subject.get("digest"), f"{path}.subject[0].digest")
    if (
        subject.get("name") != repository
        or set(subject_digest) != {"sha256"}
        or subject_digest.get("sha256") != digest
    ):
        raise ReleaseContractError(f"{path} does not name the exact OCI digest")


def _verify_provenance(
    payload: Any,
    *,
    component: str,
    repository: str,
    digest: str,
    git_sha: str,
    repository_uri: str,
    source_ref: str,
    pipeline_id: str,
    build_job_id: str,
    build_id: str,
    sbom_sha256: str,
) -> None:
    """Bind an in-toto/SLSA statement to this exact source and OCI subject."""

    document = _record(payload, f"images.{component}.provenance document")
    if document.get("_type") != "https://in-toto.io/Statement/v1":
        raise ReleaseContractError(
            f"images.{component}.provenance is not in-toto Statement v1"
        )
    if document.get("predicateType") != SLSA_PROVENANCE_V1:
        raise ReleaseContractError(
            f"images.{component}.provenance is not SLSA provenance v1"
        )
    _verify_exact_statement_subject(
        document,
        path=f"images.{component}.provenance",
        repository=repository,
        digest=digest,
    )
    predicate = _record(
        document.get("predicate"), f"images.{component}.provenance.predicate"
    )
    build_definition = _record(
        predicate.get("buildDefinition"),
        f"images.{component}.provenance.predicate.buildDefinition",
    )
    build_type = _required_text(
        build_definition.get("buildType"),
        f"images.{component}.provenance.predicate.buildDefinition.buildType",
    )
    if not build_type.startswith("https://"):
        raise ReleaseContractError(
            f"images.{component}.provenance buildType must be an HTTPS URI"
        )
    external = _record(
        build_definition.get("externalParameters"),
        f"images.{component}.provenance.predicate.buildDefinition.externalParameters",
    )
    if set(external) != {"git_sha", "component", "repository_uri", "ref"} or (
        external.get("git_sha") != git_sha
        or external.get("component") != component
        or external.get("repository_uri") != repository_uri
        or external.get("ref") != source_ref
    ):
        raise ReleaseContractError(
            f"images.{component}.provenance source or component differs from the release"
        )
    internal = _record(
        build_definition.get("internalParameters"),
        f"images.{component}.provenance.predicate.buildDefinition.internalParameters",
    )
    if set(internal) != {"pipeline_id", "build_job_id"} or (
        str(internal.get("pipeline_id")) != pipeline_id
        or str(internal.get("build_job_id")) != build_job_id
    ):
        raise ReleaseContractError(
            f"images.{component}.provenance build invocation differs from the release"
        )
    dependencies = build_definition.get("resolvedDependencies")
    if not isinstance(dependencies, list) or len(dependencies) != 1:
        raise ReleaseContractError(
            f"images.{component}.provenance must resolve exactly one source revision"
        )
    dependency = _record(
        dependencies[0],
        f"images.{component}.provenance.predicate.buildDefinition.resolvedDependencies[0]",
    )
    dependency_digest = _record(
        dependency.get("digest"),
        f"images.{component}.provenance source digest",
    )
    if (
        dependency.get("uri") != repository_uri
        or set(dependency_digest) != {"gitCommit"}
        or dependency_digest.get("gitCommit") != git_sha
    ):
        raise ReleaseContractError(
            f"images.{component}.provenance resolved source differs from the release"
        )
    run_details = _record(
        predicate.get("runDetails"),
        f"images.{component}.provenance.predicate.runDetails",
    )
    builder = _record(
        run_details.get("builder"),
        f"images.{component}.provenance.predicate.runDetails.builder",
    )
    if not _required_text(
        builder.get("id"),
        f"images.{component}.provenance.predicate.runDetails.builder.id",
    ).startswith("https://"):
        raise ReleaseContractError(
            f"images.{component}.provenance builder id must be an HTTPS URI"
        )
    metadata = _record(
        run_details.get("metadata"),
        f"images.{component}.provenance.predicate.runDetails.metadata",
    )
    if metadata.get("invocationId") != build_id:
        raise ReleaseContractError(
            f"images.{component}.provenance invocationId differs from image.build_id"
        )
    started = _timestamp(
        metadata.get("startedOn"),
        f"images.{component}.provenance.predicate.runDetails.metadata.startedOn",
    )
    finished = _timestamp(
        metadata.get("finishedOn"),
        f"images.{component}.provenance.predicate.runDetails.metadata.finishedOn",
    )
    if finished < started:
        raise ReleaseContractError(
            f"images.{component}.provenance build finishes before it starts"
        )
    byproducts = run_details.get("byproducts")
    if not isinstance(byproducts, list) or len(byproducts) != 1:
        raise ReleaseContractError(
            f"images.{component}.provenance must bind exactly one SBOM byproduct"
        )
    sbom = _record(
        byproducts[0],
        f"images.{component}.provenance.predicate.runDetails.byproducts[0]",
    )
    sbom_digest = _record(
        sbom.get("digest"),
        f"images.{component}.provenance SBOM byproduct digest",
    )
    if (
        sbom.get("name") != f"{component}.sbom"
        or set(sbom_digest) != {"sha256"}
        or sbom_digest.get("sha256") != sbom_sha256
    ):
        raise ReleaseContractError(
            f"images.{component}.provenance SBOM byproduct differs from the release artifact"
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

    rows = payload if isinstance(payload, list) else [payload]
    if len(rows) != 1:
        raise ReleaseContractError(
            f"images.{component}.signature verification output must contain exactly one result"
        )
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


def _decode_cosign_attestation_statement(
    payload: Any,
    *,
    path: str,
) -> Mapping[str, Any]:
    """Decode exactly one DSSE envelope emitted by verify-attestation.

    Signature bytes are checked for presence here, not cryptographically.  That
    guarantee comes either from the protected job that recorded this Cosign
    output or from the explicitly injected live Cosign runner.
    """

    rows = payload if isinstance(payload, list) else [payload]
    if len(rows) != 1:
        raise ReleaseContractError(
            f"{path} must contain exactly one attestation envelope"
        )
    envelope = _record(rows[0], f"{path}[0]")
    if envelope.get("payloadType") != DSSE_PAYLOAD_TYPE:
        raise ReleaseContractError(f"{path} has an unsupported DSSE payload type")
    signatures = envelope.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        raise ReleaseContractError(f"{path} has no DSSE signature")
    for index, signature_value in enumerate(signatures):
        signature = _record(signature_value, f"{path}.signatures[{index}]")
        encoded_signature = _required_text(
            signature.get("sig"), f"{path}.signatures[{index}].sig"
        )
        try:
            base64.b64decode(encoded_signature, validate=True)
        except binascii.Error as exc:
            raise ReleaseContractError(
                f"{path}.signatures[{index}].sig is not valid base64"
            ) from exc
    encoded = _required_text(envelope.get("payload"), f"{path}.payload")
    try:
        decoded = base64.b64decode(encoded, validate=True)
        statement = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseContractError(
            f"{path}.payload is not valid base64 in-toto JSON"
        ) from exc
    return _record(statement, f"{path}.statement")


def _verify_cosign_attestation_result(
    payload: Any,
    *,
    component: str,
    artifact_kind: str,
    repository: str,
    digest: str,
    predicate_type: str,
    expected_payload: Any,
) -> None:
    path = f"images.{component}.{artifact_kind}.attestation verification output"
    statement = _decode_cosign_attestation_statement(payload, path=path)
    if statement.get("_type") not in IN_TOTO_STATEMENT_TYPES:
        raise ReleaseContractError(f"{path} is not a supported in-toto Statement")
    if statement.get("predicateType") != predicate_type:
        raise ReleaseContractError(
            f"{path} predicate type differs from the release contract"
        )
    _verify_exact_statement_subject(
        statement,
        path=path,
        repository=repository,
        digest=digest,
    )
    if artifact_kind == "sbom":
        if _canonical_json(statement.get("predicate")) != _canonical_json(
            expected_payload
        ):
            raise ReleaseContractError(
                f"{path} predicate differs from the content-addressed SBOM"
            )
    elif artifact_kind == "provenance":
        if _canonical_json(statement) != _canonical_json(expected_payload):
            raise ReleaseContractError(
                f"{path} differs from the content-addressed provenance statement"
            )
    else:  # pragma: no cover - only fixed contract kinds call this helper
        raise ReleaseContractError(f"unsupported attestation kind: {artifact_kind}")


def _cosign_evidence(
    value: Any,
    *,
    path: str,
    trusted_issuer: str,
    trusted_identity: str,
    artifact_root: Path,
) -> tuple[Mapping[str, Any], dict[str, str], Any]:
    evidence = _record(value, path)
    if evidence.get("verified") is not True:
        raise ReleaseContractError(f"{path} is not verified")
    if _required_text(evidence.get("tool"), f"{path}.tool") != "cosign":
        raise ReleaseContractError(f"{path}.tool must be cosign")
    issuer = _required_text(evidence.get("issuer"), f"{path}.issuer")
    identity = _required_text(evidence.get("identity"), f"{path}.identity")
    if issuer != trusted_issuer:
        raise ReleaseContractError(
            f"{path}.issuer differs from the configured trust anchor"
        )
    if identity != trusted_identity:
        raise ReleaseContractError(
            f"{path}.identity differs from the configured trust anchor"
        )
    verification, payload = _cosign_json_artifact(
        evidence.get("verification"),
        path=f"{path}.verification",
        artifact_root=artifact_root,
    )
    return evidence, verification, payload


def _cosign_verify_command(
    *,
    executable: str,
    reference: str,
    issuer: str,
    identity: str,
) -> tuple[str, ...]:
    return (
        executable,
        "verify",
        "--certificate-oidc-issuer",
        issuer,
        "--certificate-identity",
        identity,
        "--new-bundle-format=true",
        "--check-claims=true",
        "--output",
        "json",
        reference,
    )


def _cosign_verify_attestation_command(
    *,
    executable: str,
    reference: str,
    issuer: str,
    identity: str,
    predicate_type: str,
) -> tuple[str, ...]:
    # Cosign accepts either its canonical aliases or a predicate URI for
    # ``--type``.  Passing the URI deliberately makes the command filter equal
    # to the predicateType that this verifier checks in the decoded statement.
    return (
        executable,
        "verify-attestation",
        "--certificate-oidc-issuer",
        issuer,
        "--certificate-identity",
        identity,
        "--new-bundle-format=true",
        "--check-claims=true",
        "--type",
        predicate_type,
        "--output",
        "json",
        reference,
    )


def _run_cosign_json(
    command: tuple[str, ...],
    *,
    runner: CosignCommandRunner,
    path: str,
) -> Any:
    try:
        result = runner(command)
    except Exception as exc:
        raise ReleaseContractError(f"{path} command could not be executed") from exc
    if not isinstance(result, CosignCommandResult):
        raise ReleaseContractError(f"{path} command runner returned an invalid result")
    if result.returncode != 0:
        raise ReleaseContractError(
            f"{path} command failed with exit code {result.returncode}"
        )
    return _parse_cosign_json(result.stdout, path=f"{path} stdout")


def _subprocess_cosign_runner(command: tuple[str, ...]) -> CosignCommandResult:
    """Run Cosign only after the caller explicitly selects live verification."""

    completed = subprocess.run(  # noqa: S603 - argv only; never invokes a shell
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return CosignCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _image_reference(value: Any, path: str) -> tuple[str, str]:
    reference = _required_text(value, path)
    match = _DIGEST_REF_RE.fullmatch(reference)
    if match is None:
        raise ReleaseContractError(
            f"{path} must be a registry reference pinned by sha256 digest"
        )
    return reference, match.group(1)


def verify_release_contract(
    release: Mapping[str, Any],
    *,
    expected_cosign_issuer: str,
    expected_cosign_identity: str,
    deployment: Mapping[str, Any],
    artifact_root: Path | None = None,
    cosign_runner: CosignCommandRunner | None = None,
    cosign_executable: str = "cosign",
) -> dict[str, Any]:
    """Verify build-once/test/deploy identity and return a compact receipt.

    The default path is strictly offline and consumes content-addressed Cosign
    outputs.  It does not verify their signatures cryptographically and is
    authoritative only when a protected job vouches for those artifacts.  A
    caller may explicitly inject ``cosign_runner`` to re-run all nine
    cryptographic checks against the OCI registry; this function never starts a
    process or performs network I/O by itself.
    """

    trusted_issuer = _required_text(expected_cosign_issuer, "expected_cosign_issuer")
    trusted_identity = _required_text(
        expected_cosign_identity, "expected_cosign_identity"
    )
    if not trusted_issuer.startswith("https://"):
        raise ReleaseContractError(
            "expected_cosign_issuer must be an HTTPS trust anchor"
        )

    if release.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseContractError("unsupported release schema_version")
    source = _record(release.get("source"), "source")
    git_sha = _required_text(source.get("git_sha"), "source.git_sha").lower()
    if _GIT_SHA_RE.fullmatch(git_sha) is None:
        raise ReleaseContractError("source.git_sha must be a full lowercase Git SHA")
    pipeline_id = _required_text(source.get("pipeline_id"), "source.pipeline_id")
    build_job_id = _required_text(source.get("build_job_id"), "source.build_job_id")
    repository_uri = _required_text(
        source.get("repository_uri"), "source.repository_uri"
    )
    if not repository_uri.startswith("https://"):
        raise ReleaseContractError("source.repository_uri must be an HTTPS URI")
    source_ref = _required_text(source.get("ref"), "source.ref")

    images = _record(release.get("images"), "images")
    if set(images) != set(COMPONENTS):
        raise ReleaseContractError(
            "images must contain exactly backend, frontend and worker"
        )
    tested = _record(release.get("tested"), "tested")
    if tested.get("git_sha") != git_sha:
        raise ReleaseContractError("tested.git_sha differs from source.git_sha")
    tested_images = _record(tested.get("images"), "tested.images")
    if set(tested_images) != set(COMPONENTS):
        raise ReleaseContractError("tested.images must contain exactly all components")

    if artifact_root is None:
        raise ReleaseContractError("artifact_root is required for release verification")
    executable = _required_text(cosign_executable, "cosign_executable")

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
            raise ReleaseContractError(
                f"images.{component}.revision differs from source Git SHA"
            )
        build_id = _required_text(image.get("build_id"), f"images.{component}.build_id")
        if build_id in build_ids:
            raise ReleaseContractError(
                "each component must have one distinct CI build id"
            )
        build_ids.add(build_id)
        if "build_occurrences" in image:
            raise ReleaseContractError(
                f"images.{component}.build_occurrences is a self-declared non-proof; "
                "the exact provenance invocation is authoritative"
            )

        repository = reference.rsplit("@", 1)[0]
        sbom_source = _record(image.get("sbom"), f"images.{component}.sbom")
        sbom, sbom_payload = _json_artifact(
            sbom_source,
            path=f"images.{component}.sbom",
            artifact_root=artifact_root,
        )
        sbom_format, allowed_sbom_predicate_types = _verify_sbom(
            sbom_payload,
            component=component,
        )
        (
            sbom_attestation,
            sbom_verification,
            sbom_verification_payload,
        ) = _cosign_evidence(
            sbom_source.get("attestation"),
            path=f"images.{component}.sbom.attestation",
            trusted_issuer=trusted_issuer,
            trusted_identity=trusted_identity,
            artifact_root=artifact_root,
        )
        sbom_predicate_type = _required_text(
            sbom_attestation.get("predicate_type"),
            f"images.{component}.sbom.attestation.predicate_type",
        )
        if sbom_predicate_type not in allowed_sbom_predicate_types:
            raise ReleaseContractError(
                f"images.{component}.sbom.attestation.predicate_type differs from the SBOM format"
            )
        _verify_cosign_attestation_result(
            sbom_verification_payload,
            component=component,
            artifact_kind="sbom",
            repository=repository,
            digest=digest,
            predicate_type=sbom_predicate_type,
            expected_payload=sbom_payload,
        )

        provenance_source = _record(
            image.get("provenance"),
            f"images.{component}.provenance",
        )
        provenance, provenance_payload = _json_artifact(
            provenance_source,
            path=f"images.{component}.provenance",
            artifact_root=artifact_root,
        )
        _verify_provenance(
            provenance_payload,
            component=component,
            repository=repository,
            digest=digest,
            git_sha=git_sha,
            repository_uri=repository_uri,
            source_ref=source_ref,
            pipeline_id=pipeline_id,
            build_job_id=build_job_id,
            build_id=build_id,
            sbom_sha256=sbom["sha256"],
        )
        (
            provenance_attestation,
            provenance_verification,
            provenance_verification_payload,
        ) = _cosign_evidence(
            provenance_source.get("attestation"),
            path=f"images.{component}.provenance.attestation",
            trusted_issuer=trusted_issuer,
            trusted_identity=trusted_identity,
            artifact_root=artifact_root,
        )
        provenance_predicate_type = _required_text(
            provenance_attestation.get("predicate_type"),
            f"images.{component}.provenance.attestation.predicate_type",
        )
        if provenance_predicate_type != SLSA_PROVENANCE_V1:
            raise ReleaseContractError(
                f"images.{component}.provenance.attestation.predicate_type must be SLSA provenance v1"
            )
        _verify_cosign_attestation_result(
            provenance_verification_payload,
            component=component,
            artifact_kind="provenance",
            repository=repository,
            digest=digest,
            predicate_type=provenance_predicate_type,
            expected_payload=provenance_payload,
        )

        _, signature_verification, signature_verification_payload = _cosign_evidence(
            image.get("signature"),
            path=f"images.{component}.signature",
            trusted_issuer=trusted_issuer,
            trusted_identity=trusted_identity,
            artifact_root=artifact_root,
        )
        _verify_cosign_result(
            signature_verification_payload,
            component=component,
            repository=repository,
            digest=digest,
            issuer=trusted_issuer,
            identity=trusted_identity,
        )

        if cosign_runner is not None:
            live_signature = _run_cosign_json(
                _cosign_verify_command(
                    executable=executable,
                    reference=reference,
                    issuer=trusted_issuer,
                    identity=trusted_identity,
                ),
                runner=cosign_runner,
                path=f"images.{component}.signature live verification",
            )
            _verify_cosign_result(
                live_signature,
                component=component,
                repository=repository,
                digest=digest,
                issuer=trusted_issuer,
                identity=trusted_identity,
            )
            for artifact_kind, predicate_type, expected_payload in (
                ("sbom", sbom_predicate_type, sbom_payload),
                ("provenance", provenance_predicate_type, provenance_payload),
            ):
                live_attestation = _run_cosign_json(
                    _cosign_verify_attestation_command(
                        executable=executable,
                        reference=reference,
                        issuer=trusted_issuer,
                        identity=trusted_identity,
                        predicate_type=predicate_type,
                    ),
                    runner=cosign_runner,
                    path=f"images.{component}.{artifact_kind} live attestation",
                )
                _verify_cosign_attestation_result(
                    live_attestation,
                    component=component,
                    artifact_kind=artifact_kind,
                    repository=repository,
                    digest=digest,
                    predicate_type=predicate_type,
                    expected_payload=expected_payload,
                )

        for artifact in (
            sbom,
            sbom_verification,
            provenance,
            provenance_verification,
            signature_verification,
        ):
            if artifact["path"] in artifact_paths:
                raise ReleaseContractError(
                    "release evidence artifacts must use distinct paths"
                )
            artifact_paths.add(artifact["path"])
        tested_reference, _ = _image_reference(
            tested_images.get(component), f"tested.images.{component}"
        )
        if tested_reference != reference:
            raise ReleaseContractError(
                f"tested {component} image differs from release image"
            )
        normalized_images[component] = {
            "reference": reference,
            "digest": f"sha256:{digest}",
            "revision": git_sha,
            "build_id": build_id,
            "sbom": {
                **sbom,
                "format": sbom_format,
                "attestation": {
                    "tool": "cosign",
                    "predicate_type": sbom_predicate_type,
                    "issuer": trusted_issuer,
                    "identity": trusted_identity,
                    "verified": True,
                    "verification": sbom_verification,
                },
            },
            "provenance": {
                **provenance,
                "attestation": {
                    "tool": "cosign",
                    "predicate_type": provenance_predicate_type,
                    "issuer": trusted_issuer,
                    "identity": trusted_identity,
                    "verified": True,
                    "verification": provenance_verification,
                },
            },
            "signature": {
                "tool": "cosign",
                "issuer": trusted_issuer,
                "identity": trusted_identity,
                "verified": True,
                "verification": signature_verification,
            },
        }

    deployed = _record(deployment, "deployment")
    if deployed.get("schema_version") != 1:
        raise ReleaseContractError("deployment.schema_version must equal one")
    if deployed.get("git_sha") != git_sha:
        raise ReleaseContractError("deployment.git_sha differs from release source")
    deployment_environment = _required_text(
        deployed.get("environment"), "deployment.environment"
    )
    deployment_id = _required_text(
        deployed.get("deployment_id"), "deployment.deployment_id"
    )
    deployed_by = _required_text(deployed.get("deployed_by"), "deployment.deployed_by")
    deployed_at = _timestamp(deployed.get("deployed_at"), "deployment.deployed_at")
    deployed_images = _record(deployed.get("images"), "deployment.images")
    served_build_info = _record(
        deployed.get("served_build_info"), "deployment.served_build_info"
    )
    if set(deployed_images) != set(COMPONENTS) or set(served_build_info) != set(
        COMPONENTS
    ):
        raise ReleaseContractError(
            "deployment images and served_build_info must contain exactly all components"
        )
    for component in COMPONENTS:
        deployed_reference, _ = _image_reference(
            deployed_images.get(component), f"deployment.images.{component}"
        )
        if deployed_reference != normalized_images[component]["reference"]:
            raise ReleaseContractError(
                f"deployed {component} image differs from tested release image"
            )
        build_info = _record(
            served_build_info.get(component),
            f"deployment.served_build_info.{component}",
        )
        if set(build_info) != {"git_sha", "image"} or (
            build_info.get("git_sha") != git_sha
            or build_info.get("image") != deployed_reference
        ):
            raise ReleaseContractError(
                f"served {component} build-info differs from the deployed release"
            )

    canonical = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "git_sha": git_sha,
                "pipeline_id": pipeline_id,
                "build_job_id": build_job_id,
                "repository_uri": repository_uri,
                "ref": source_ref,
            },
            "images": normalized_images,
            "tested": {"git_sha": git_sha, "images": dict(tested_images)},
            "deployment": {
                "id": deployment_id,
                "environment": deployment_environment,
                "deployed_at": deployed_at.isoformat(),
                "deployed_by": deployed_by,
                "images": dict(deployed_images),
                "served_build_info": dict(served_build_info),
            },
            "cosign_verification_mode": (
                "executed_live" if cosign_runner is not None else "recorded_offline"
            ),
            "cryptographic_reverification": cosign_runner is not None,
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
        "repository_uri": repository_uri,
        "ref": source_ref,
        "deployment_id": deployment_id,
        "deployment_environment": deployment_environment,
        "deployed_at": deployed_at.isoformat(),
        "deployed_by": deployed_by,
        "cosign_verification_mode": (
            "executed_live" if cosign_runner is not None else "recorded_offline"
        ),
        "cryptographic_reverification": cosign_runner is not None,
        "images": {
            component: normalized_images[component]["reference"]
            for component in COMPONENTS
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
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--cosign-issuer", required=True)
    parser.add_argument("--cosign-identity", required=True)
    parser.add_argument(
        "--execute-cosign",
        action="store_true",
        help=(
            "explicitly execute Cosign and cryptographically verify against the registry; "
            "omitted means non-cryptographic offline validation of protected-job evidence"
        ),
    )
    parser.add_argument(
        "--cosign-bin",
        default="cosign",
        help="Cosign executable used only with --execute-cosign",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_release_contract(
            _load(args.release),
            expected_cosign_issuer=args.cosign_issuer,
            expected_cosign_identity=args.cosign_identity,
            deployment=_load(args.deployment),
            artifact_root=args.artifact_root,
            cosign_runner=_subprocess_cosign_runner if args.execute_cosign else None,
            cosign_executable=args.cosign_bin,
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
