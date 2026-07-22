"""Offline proof contract for build-once, digest-pinned Lot-9 releases."""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[4] / "scripts" / "agentium_release_contract.py"
SPEC = importlib.util.spec_from_file_location("agentium_release_contract", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ReleaseContractError = MODULE.ReleaseContractError
CosignCommandResult = MODULE.CosignCommandResult
_verify_release_contract = MODULE.verify_release_contract

SHA = "a" * 40
ISSUER = "https://gitlab.example"
IDENTITY = "project/agentium/release"


def verify_release_contract(
    release,
    *,
    expected_cosign_issuer: str = ISSUER,
    expected_cosign_identity: str = IDENTITY,
    **kwargs,
):
    kwargs.setdefault("deployment", _deployment(release))
    return _verify_release_contract(
        release,
        expected_cosign_issuer=expected_cosign_issuer,
        expected_cosign_identity=expected_cosign_identity,
        **kwargs,
    )


def _artifact(root: Path, name: str, content: str) -> dict[str, str]:
    path = root / name
    path.write_text(content, encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(content.encode()).hexdigest()}


def _dsse(statement: dict) -> str:
    payload = base64.b64encode(
        json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    return json.dumps(
        {
            "payloadType": "application/vnd.in-toto+json",
            "payload": payload,
            "signatures": [
                {
                    "keyid": "",
                    "sig": base64.b64encode(b"signed-by-cosign").decode(),
                }
            ],
        }
    )


def _cosign_attestation(
    root: Path,
    *,
    component: str,
    kind: str,
    predicate_type: str,
    statement: dict,
) -> dict:
    return {
        "verified": True,
        "tool": "cosign",
        "issuer": ISSUER,
        "identity": IDENTITY,
        "predicate_type": predicate_type,
        "verification": _artifact(
            root,
            f"{component}.{kind}.cosign-attestation.json",
            _dsse(statement),
        ),
    }


def _release(root: Path) -> dict:
    images = {}
    tested = {}
    for index, component in enumerate(("backend", "frontend", "worker"), start=1):
        reference = f"registry.example/agentium/{component}@sha256:{str(index) * 64}"
        repository, digest_ref = reference.rsplit("@", 1)
        digest = digest_ref.removeprefix("sha256:")
        issuer = ISSUER
        identity = IDENTITY
        root_ref = f"urn:agentium:{component}"
        dependency_ref = f"pkg:pypi/{component}-dependency@1.0.0"
        sbom_payload = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "serialNumber": f"urn:uuid:00000000-0000-4000-8000-00000000000{index}",
            "version": 1,
            "metadata": {
                "component": {
                    "type": "container",
                    "name": component,
                    "bom-ref": root_ref,
                }
            },
            "components": [
                {
                    "type": "library",
                    "name": f"{component}-dependency",
                    "version": "1.0.0",
                    "bom-ref": dependency_ref,
                    "purl": dependency_ref,
                }
            ],
            "dependencies": [{"ref": root_ref, "dependsOn": [dependency_ref]}],
        }
        sbom_predicate_type = "https://cyclonedx.org/bom/v1.5"
        sbom_statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": sbom_predicate_type,
            "subject": [{"name": repository, "digest": {"sha256": digest}}],
            "predicate": sbom_payload,
        }
        sbom_content = json.dumps(sbom_payload)
        sbom_sha256 = hashlib.sha256(sbom_content.encode()).hexdigest()
        build_id = f"build-{component}"
        provenance_payload = {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"name": repository, "digest": {"sha256": digest}}],
            "predicate": {
                "buildDefinition": {
                    "buildType": "https://gitlab.example/agentium/container-build/v1",
                    "externalParameters": {
                        "git_sha": SHA,
                        "component": component,
                        "repository_uri": "https://gitlab.example/agentium.git",
                        "ref": "refs/heads/demo/agentic",
                    },
                    "internalParameters": {
                        "pipeline_id": "42",
                        "build_job_id": "43",
                    },
                    "resolvedDependencies": [
                        {
                            "uri": "https://gitlab.example/agentium.git",
                            "digest": {"gitCommit": SHA},
                        }
                    ],
                },
                "runDetails": {
                    "builder": {"id": "https://gitlab.example/runner/agentium"},
                    "metadata": {
                        "invocationId": build_id,
                        "startedOn": "2026-07-22T10:00:00Z",
                        "finishedOn": "2026-07-22T10:05:00Z",
                    },
                    "byproducts": [
                        {
                            "name": f"{component}.sbom",
                            "digest": {"sha256": sbom_sha256},
                        }
                    ],
                },
            },
        }
        sbom = _artifact(
            root,
            f"{component}.sbom.json",
            sbom_content,
        )
        sbom["attestation"] = _cosign_attestation(
            root,
            component=component,
            kind="sbom",
            predicate_type=sbom_predicate_type,
            statement=sbom_statement,
        )
        provenance = _artifact(
            root,
            f"{component}.provenance.json",
            json.dumps(provenance_payload),
        )
        provenance["attestation"] = _cosign_attestation(
            root,
            component=component,
            kind="provenance",
            predicate_type="https://slsa.dev/provenance/v1",
            statement=provenance_payload,
        )
        images[component] = {
            "reference": reference,
            "revision": SHA,
            "build_id": build_id,
            "sbom": sbom,
            "provenance": provenance,
            "signature": {
                "verified": True,
                "tool": "cosign",
                "issuer": issuer,
                "identity": identity,
                "verification": _artifact(
                    root,
                    f"{component}.cosign-verify.json",
                    json.dumps(
                        [
                            {
                                "critical": {
                                    "identity": {"docker-reference": repository},
                                    "image": {"docker-manifest-digest": digest_ref},
                                },
                                "optional": {"Issuer": issuer, "Subject": identity},
                            }
                        ]
                    ),
                ),
            },
        }
        tested[component] = reference
    return {
        "schema_version": 2,
        "source": {
            "git_sha": SHA,
            "pipeline_id": "42",
            "build_job_id": "43",
            "repository_uri": "https://gitlab.example/agentium.git",
            "ref": "refs/heads/demo/agentic",
        },
        "images": images,
        "tested": {"git_sha": SHA, "images": tested},
    }


def _deployment(release: dict) -> dict:
    images = dict(release["tested"]["images"])
    return {
        "schema_version": 1,
        "git_sha": SHA,
        "environment": "production",
        "deployment_id": "deployment-44",
        "deployed_at": "2026-07-22T10:10:00Z",
        "deployed_by": "protected-release-job",
        "images": images,
        "served_build_info": {
            component: {"git_sha": SHA, "image": reference}
            for component, reference in images.items()
        },
    }


def _rewrite_attestation(
    root: Path,
    release: dict,
    *,
    component: str,
    kind: str,
    mutate,
) -> None:
    attestation = release["images"][component][kind]["attestation"]
    verification = attestation["verification"]
    path = root / verification["path"]
    envelope = json.loads(path.read_text(encoding="utf-8"))
    statement = json.loads(base64.b64decode(envelope["payload"]).decode())
    mutate(statement, envelope)
    envelope["payload"] = base64.b64encode(
        json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    path.write_text(json.dumps(envelope), encoding="utf-8")
    verification["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded_cosign_runner(root: Path, calls: list[tuple[str, ...]]):
    def run(command: tuple[str, ...]) -> CosignCommandResult:
        calls.append(command)
        reference = command[-1]
        component = reference.rsplit("/", 1)[-1].split("@", 1)[0]
        if command[1] == "verify":
            filename = f"{component}.cosign-verify.json"
        else:
            predicate_type = command[command.index("--type") + 1]
            kind = "provenance" if predicate_type == "https://slsa.dev/provenance/v1" else "sbom"
            filename = f"{component}.{kind}.cosign-attestation.json"
        return CosignCommandResult(0, (root / filename).read_text(encoding="utf-8"), "")

    return run


def test_exact_built_tested_and_deployed_digests_verify(tmp_path):
    release = _release(tmp_path)
    deployment = _deployment(release)

    result = verify_release_contract(
        release,
        deployment=deployment,
        artifact_root=tmp_path,
    )

    assert result["valid"] is True
    assert result["git_sha"] == SHA
    assert result["deployment_environment"] == "production"
    assert result["cosign_verification_mode"] == "recorded_offline"
    assert result["cryptographic_reverification"] is False
    assert set(result["images"]) == {"backend", "frontend", "worker"}
    assert len(result["contract_sha256"]) == 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda release: release["images"]["backend"].update(reference="registry/x:latest"),
            "pinned",
        ),
        (lambda release: release["images"]["worker"].update(revision="b" * 40), "revision"),
        (
            lambda release: release["images"]["frontend"].update(build_occurrences=2),
            "self-declared",
        ),
        (
            lambda release: release["images"]["backend"]["signature"].update(verified=False),
            "not verified",
        ),
        (
            lambda release: release["tested"]["images"].update(
                worker=f"registry.example/agentium/worker@sha256:{'9' * 64}"
            ),
            "tested worker",
        ),
    ],
)
def test_mutable_or_unproven_release_fails_closed(tmp_path, mutation, message):
    release = _release(tmp_path)
    mutation(release)
    with pytest.raises(ReleaseContractError, match=message):
        verify_release_contract(release, artifact_root=tmp_path)


def test_artifact_checksum_and_deployment_drift_fail_closed(tmp_path):
    release = _release(tmp_path)
    (tmp_path / "backend.sbom.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ReleaseContractError, match="checksum mismatch"):
        verify_release_contract(release, artifact_root=tmp_path)

    release = _release(tmp_path)
    deployment = _deployment(release)
    deployment["images"]["frontend"] = f"registry.example/agentium/frontend@sha256:{'8' * 64}"
    with pytest.raises(ReleaseContractError, match="deployed frontend"):
        verify_release_contract(release, deployment=deployment, artifact_root=tmp_path)


def test_provenance_and_cosign_output_are_bound_to_exact_subject(tmp_path):
    release = _release(tmp_path)
    provenance_path = tmp_path / "worker.provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["subject"][0]["digest"]["sha256"] = "9" * 64
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    release["images"]["worker"]["provenance"]["sha256"] = hashlib.sha256(
        provenance_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ReleaseContractError, match="exact OCI digest"):
        verify_release_contract(release, artifact_root=tmp_path)

    release = _release(tmp_path)
    verification_path = tmp_path / "backend.cosign-verify.json"
    verification = json.loads(verification_path.read_text())
    verification[0]["optional"]["Subject"] = "attacker/project"
    verification_path.write_text(json.dumps(verification), encoding="utf-8")
    release["images"]["backend"]["signature"]["verification"]["sha256"] = hashlib.sha256(
        verification_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ReleaseContractError, match="verification output"):
        verify_release_contract(release, artifact_root=tmp_path)


def test_cosign_signer_is_pinned_outside_the_self_declared_release(tmp_path):
    release = _release(tmp_path)
    attacker_issuer = "https://attacker.example"
    attacker_identity = "attacker/project/release"
    release["images"]["backend"]["signature"].update(
        issuer=attacker_issuer,
        identity=attacker_identity,
    )
    verification_path = tmp_path / "backend.cosign-verify.json"
    verification = json.loads(verification_path.read_text())
    verification[0]["optional"].update(
        Issuer=attacker_issuer,
        Subject=attacker_identity,
    )
    verification_path.write_text(json.dumps(verification), encoding="utf-8")
    release["images"]["backend"]["signature"]["verification"]["sha256"] = hashlib.sha256(
        verification_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ReleaseContractError, match="issuer differs from the configured"):
        verify_release_contract(release, artifact_root=tmp_path)

    release = _release(tmp_path)
    with pytest.raises(ReleaseContractError, match="identity differs from the configured"):
        verify_release_contract(
            release,
            artifact_root=tmp_path,
            expected_cosign_identity="trusted/other-release-job",
        )


def test_release_verification_requires_real_semantic_artifacts(tmp_path):
    release = _release(tmp_path)
    with pytest.raises(ReleaseContractError, match="artifact_root"):
        verify_release_contract(release)

    sbom_path = tmp_path / "frontend.sbom.json"
    sbom_path.write_text(json.dumps({"component": "frontend"}), encoding="utf-8")
    release["images"]["frontend"]["sbom"]["sha256"] = hashlib.sha256(
        sbom_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ReleaseContractError, match="CycloneDX or SPDX"):
        verify_release_contract(release, artifact_root=tmp_path)

    release = _release(tmp_path)
    empty_cyclonedx = {"bomFormat": "CycloneDX", "specVersion": "1.5"}
    sbom_path = tmp_path / "frontend.sbom.json"
    sbom_path.write_text(json.dumps(empty_cyclonedx), encoding="utf-8")
    release["images"]["frontend"]["sbom"]["sha256"] = hashlib.sha256(
        sbom_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ReleaseContractError, match="serialNumber"):
        verify_release_contract(release, artifact_root=tmp_path)


def test_release_requires_deployment_and_complete_slsa_run_details(tmp_path):
    release = _release(tmp_path)
    with pytest.raises(ReleaseContractError, match="deployment must be an object"):
        _verify_release_contract(
            release,
            expected_cosign_issuer=ISSUER,
            expected_cosign_identity=IDENTITY,
            deployment=None,
            artifact_root=tmp_path,
        )

    provenance_path = tmp_path / "worker.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["predicate"].pop("runDetails")
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    release["images"]["worker"]["provenance"]["sha256"] = hashlib.sha256(
        provenance_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ReleaseContractError, match="runDetails must be an object"):
        verify_release_contract(release, artifact_root=tmp_path)


def test_deployment_must_bind_served_build_info_to_exact_digest(tmp_path):
    release = _release(tmp_path)
    deployment = _deployment(release)
    deployment["served_build_info"]["frontend"][
        "image"
    ] = f"registry.example/agentium/frontend@sha256:{'9' * 64}"
    with pytest.raises(ReleaseContractError, match="served frontend build-info"):
        verify_release_contract(
            release,
            deployment=deployment,
            artifact_root=tmp_path,
        )


def test_artifact_path_cannot_escape_root(tmp_path):
    release = _release(tmp_path)
    release["images"]["backend"]["sbom"]["path"] = "../secret"
    with pytest.raises(ReleaseContractError, match="inside the artifact root"):
        verify_release_contract(release, artifact_root=tmp_path)


@pytest.mark.parametrize("artifact_kind", ["sbom", "provenance"])
def test_sbom_and_provenance_require_cosign_attestations(tmp_path, artifact_kind):
    release = _release(tmp_path)
    release["images"]["backend"][artifact_kind].pop("attestation")

    with pytest.raises(ReleaseContractError, match=r"attestation must be an object"):
        verify_release_contract(release, artifact_root=tmp_path)


@pytest.mark.parametrize("artifact_kind", ["sbom", "provenance"])
def test_attestation_subject_is_the_only_exact_oci_digest(tmp_path, artifact_kind):
    release = _release(tmp_path)
    _rewrite_attestation(
        tmp_path,
        release,
        component="worker",
        kind=artifact_kind,
        mutate=lambda statement, _envelope: statement["subject"][0]["digest"].update(
            sha256="9" * 64
        ),
    )

    with pytest.raises(ReleaseContractError, match="does not name the exact OCI digest"):
        verify_release_contract(release, artifact_root=tmp_path)

    release = _release(tmp_path)
    _rewrite_attestation(
        tmp_path,
        release,
        component="worker",
        kind=artifact_kind,
        mutate=lambda statement, _envelope: statement["subject"].append(
            {"name": "registry.example/attacker", "digest": {"sha256": "8" * 64}}
        ),
    )
    with pytest.raises(ReleaseContractError, match="exactly one OCI subject"):
        verify_release_contract(release, artifact_root=tmp_path)


def test_attested_payload_must_equal_content_addressed_artifact(tmp_path):
    release = _release(tmp_path)
    _rewrite_attestation(
        tmp_path,
        release,
        component="frontend",
        kind="sbom",
        mutate=lambda statement, _envelope: statement["predicate"].update(specVersion="1.4"),
    )
    with pytest.raises(ReleaseContractError, match="content-addressed SBOM"):
        verify_release_contract(release, artifact_root=tmp_path)

    release = _release(tmp_path)
    _rewrite_attestation(
        tmp_path,
        release,
        component="frontend",
        kind="provenance",
        mutate=lambda statement, _envelope: statement["predicate"]["buildDefinition"][
            "externalParameters"
        ].update(git_sha="b" * 40),
    )
    with pytest.raises(ReleaseContractError, match="content-addressed provenance"):
        verify_release_contract(release, artifact_root=tmp_path)


def test_attestation_requires_dsse_signature_and_external_trust_anchors(tmp_path):
    release = _release(tmp_path)
    release["images"]["backend"]["sbom"]["attestation"]["issuer"] = "https://attacker.example"
    with pytest.raises(ReleaseContractError, match="issuer differs from the configured"):
        verify_release_contract(release, artifact_root=tmp_path)

    release = _release(tmp_path)
    _rewrite_attestation(
        tmp_path,
        release,
        component="backend",
        kind="provenance",
        mutate=lambda _statement, envelope: envelope.update(signatures=[]),
    )
    with pytest.raises(ReleaseContractError, match="no DSSE signature"):
        verify_release_contract(release, artifact_root=tmp_path)


def test_legacy_unsigned_release_schema_is_rejected(tmp_path):
    release = _release(tmp_path)
    release["schema_version"] = 1

    with pytest.raises(ReleaseContractError, match="unsupported release schema_version"):
        verify_release_contract(release, artifact_root=tmp_path)


def test_spdx_attestation_uses_its_exact_supported_predicate_uri(tmp_path):
    release = _release(tmp_path)
    spdx_payload = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "spdxVersion": "SPDX-2.3",
        "name": "agentium-backend",
        "dataLicense": "CC0-1.0",
        "documentNamespace": "https://gitlab.example/agentium/sbom/backend",
        "creationInfo": {
            "created": "2026-07-22T10:00:00Z",
            "creators": ["Tool: syft-1.0"],
        },
        "packages": [
            {
                "SPDXID": "SPDXRef-Package-backend-dependency",
                "name": "backend-dependency",
                "versionInfo": "1.0.0",
            }
        ],
    }
    sbom_path = tmp_path / "backend.sbom.json"
    sbom_path.write_text(json.dumps(spdx_payload), encoding="utf-8")
    release["images"]["backend"]["sbom"]["sha256"] = hashlib.sha256(
        sbom_path.read_bytes()
    ).hexdigest()
    provenance_path = tmp_path / "backend.provenance.json"
    provenance_payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance_payload["predicate"]["runDetails"]["byproducts"][0]["digest"]["sha256"] = release[
        "images"
    ]["backend"]["sbom"]["sha256"]
    provenance_path.write_text(json.dumps(provenance_payload), encoding="utf-8")
    release["images"]["backend"]["provenance"]["sha256"] = hashlib.sha256(
        provenance_path.read_bytes()
    ).hexdigest()
    predicate_type = "https://spdx.dev/Document/v2.3"
    release["images"]["backend"]["sbom"]["attestation"]["predicate_type"] = predicate_type

    def replace_sbom(statement, _envelope):
        statement["predicateType"] = predicate_type
        statement["predicate"] = spdx_payload

    _rewrite_attestation(
        tmp_path,
        release,
        component="backend",
        kind="sbom",
        mutate=replace_sbom,
    )
    _rewrite_attestation(
        tmp_path,
        release,
        component="backend",
        kind="provenance",
        mutate=lambda statement, _envelope: statement["predicate"]["runDetails"]["byproducts"][0][
            "digest"
        ].update(sha256=release["images"]["backend"]["sbom"]["sha256"]),
    )
    calls: list[tuple[str, ...]] = []

    verify_release_contract(
        release,
        artifact_root=tmp_path,
        cosign_runner=_recorded_cosign_runner(tmp_path, calls),
    )

    backend_sbom_call = next(
        command
        for command in calls
        if command[1] == "verify-attestation"
        and command[-1] == release["images"]["backend"]["reference"]
        and command[command.index("--type") + 1] == predicate_type
    )
    assert backend_sbom_call[backend_sbom_call.index("--type") + 1] == predicate_type


def test_injected_cosign_runner_executes_nine_exact_pinned_checks(tmp_path):
    release = _release(tmp_path)
    calls: list[tuple[str, ...]] = []

    result = verify_release_contract(
        release,
        artifact_root=tmp_path,
        cosign_runner=_recorded_cosign_runner(tmp_path, calls),
        cosign_executable="/opt/tools/cosign",
    )

    assert result["cosign_verification_mode"] == "executed_live"
    assert result["cryptographic_reverification"] is True
    assert len(calls) == 9
    assert sum(command[1] == "verify" for command in calls) == 3
    assert sum(command[1] == "verify-attestation" for command in calls) == 6
    assert all(command[0] == "/opt/tools/cosign" for command in calls)
    assert all(command[-1] in release["tested"]["images"].values() for command in calls)
    assert all("--certificate-oidc-issuer" in command for command in calls)
    assert all(
        command[command.index("--certificate-oidc-issuer") + 1] == ISSUER for command in calls
    )
    assert all(
        command[command.index("--certificate-identity") + 1] == IDENTITY for command in calls
    )
    assert all("--new-bundle-format=true" in command for command in calls)
    assert all("--check-claims=true" in command for command in calls)
    assert all(not any("insecure" in argument for argument in command) for command in calls)
    attestation_types = {
        command[command.index("--type") + 1]
        for command in calls
        if command[1] == "verify-attestation"
    }
    assert attestation_types == {
        "https://cyclonedx.org/bom/v1.5",
        "https://slsa.dev/provenance/v1",
    }


def test_injected_cosign_runner_failure_and_live_subject_drift_fail_closed(tmp_path):
    release = _release(tmp_path)

    def failed(_command):
        return CosignCommandResult(23, "", "registry unavailable")

    with pytest.raises(ReleaseContractError, match="exit code 23"):
        verify_release_contract(
            release,
            artifact_root=tmp_path,
            cosign_runner=failed,
        )

    calls: list[tuple[str, ...]] = []
    recorded = _recorded_cosign_runner(tmp_path, calls)

    def drifted(command):
        result = recorded(command)
        if command[1] == "verify-attestation" and command[-1].endswith("1" * 64):
            return CosignCommandResult(
                0,
                (tmp_path / "frontend.sbom.cosign-attestation.json").read_text(encoding="utf-8"),
                "",
            )
        return result

    with pytest.raises(ReleaseContractError, match="exact OCI digest"):
        verify_release_contract(
            release,
            artifact_root=tmp_path,
            cosign_runner=drifted,
        )


def test_default_cli_path_never_starts_cosign_or_network_process(tmp_path, monkeypatch):
    release = _release(tmp_path)
    release_path = tmp_path / "release.json"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    deployment_path = tmp_path / "deployment.json"
    deployment_path.write_text(json.dumps(_deployment(release)), encoding="utf-8")

    def unexpected_process(*_args, **_kwargs):
        raise AssertionError("offline verification must not start a process")

    monkeypatch.setattr(MODULE.subprocess, "run", unexpected_process)
    result = MODULE.main(
        [
            "--release",
            str(release_path),
            "--deployment",
            str(deployment_path),
            "--artifact-root",
            str(tmp_path),
            "--cosign-issuer",
            ISSUER,
            "--cosign-identity",
            IDENTITY,
        ]
    )

    assert result == 0
