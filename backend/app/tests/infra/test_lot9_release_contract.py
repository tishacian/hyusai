"""Offline proof contract for build-once, digest-pinned Lot-9 releases."""

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


def _release(root: Path) -> dict:
    images = {}
    tested = {}
    for index, component in enumerate(("backend", "frontend", "worker"), start=1):
        reference = f"registry.example/agentium/{component}@sha256:{str(index) * 64}"
        repository, digest_ref = reference.rsplit("@", 1)
        digest = digest_ref.removeprefix("sha256:")
        issuer = ISSUER
        identity = IDENTITY
        images[component] = {
            "reference": reference,
            "revision": SHA,
            "build_id": f"build-{component}",
            "build_occurrences": 1,
            "sbom": _artifact(
                root,
                f"{component}.sbom.json",
                json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5"}),
            ),
            "provenance": _artifact(
                root,
                f"{component}.provenance.json",
                json.dumps(
                    {
                        "_type": "https://in-toto.io/Statement/v1",
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [{"name": repository, "digest": {"sha256": digest}}],
                        "predicate": {
                            "buildDefinition": {
                                "externalParameters": {
                                    "git_sha": SHA,
                                    "component": component,
                                }
                            }
                        },
                    }
                ),
            ),
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
        "schema_version": 1,
        "source": {"git_sha": SHA, "pipeline_id": "42", "build_job_id": "43"},
        "images": images,
        "tested": {"git_sha": SHA, "images": tested},
    }


def test_exact_built_tested_and_deployed_digests_verify(tmp_path):
    release = _release(tmp_path)
    deployment = {
        "git_sha": SHA,
        "environment": "production",
        "images": dict(release["tested"]["images"]),
    }

    result = verify_release_contract(
        release,
        deployment=deployment,
        artifact_root=tmp_path,
    )

    assert result["valid"] is True
    assert result["git_sha"] == SHA
    assert result["deployment_environment"] == "production"
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
        (lambda release: release["images"]["frontend"].update(build_occurrences=2), "occurrences"),
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
    deployment = {
        "git_sha": SHA,
        "environment": "production",
        "images": dict(release["tested"]["images"]),
    }
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
    release["images"]["backend"]["signature"]["verification"]["sha256"] = (
        hashlib.sha256(verification_path.read_bytes()).hexdigest()
    )

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


def test_artifact_path_cannot_escape_root(tmp_path):
    release = _release(tmp_path)
    release["images"]["backend"]["sbom"]["path"] = "../secret"
    with pytest.raises(ReleaseContractError, match="inside the artifact root"):
        verify_release_contract(release, artifact_root=tmp_path)
