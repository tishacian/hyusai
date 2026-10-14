"""Incomplete or stale live reports must never produce a positive badge."""

from datetime import UTC, datetime, timedelta

import pytest

from app.cli import connector_evidence as cli
from app.services.connectors.certification import (
    ComponentIdentity,
    EvidenceBundle,
    certification_level,
    required_suites,
)
from app.services.connectors.evidence_store import ProofReport
from app.services.connectors.kit_identity import kit_identity
from app.services.connectors.profiles import get_profile


def campaign():
    profile = get_profile("postgresql")
    kit = kit_identity()
    identity = ComponentIdentity(
        profile_key=profile.key,
        profile_version="1",
        profile_sha256=profile.digest,
        capabilities=profile.capabilities,
        drivers=[
            {"package": "psycopg2-binary", "version": cli.metadata.version("psycopg2-binary")}
        ],
        runner_image_sha256="a" * 64,
        server_version="17.11",
        kit_version=kit["version"],
        kit_sha256=kit["sha256"],
    )
    return dict(
        identity=identity.model_dump(mode="json"),
        reports=[
            ProofReport(suite=name, status="passed", code="FIXTURE_ONLY", elapsed_ms=1).model_dump(
                mode="json"
            )
            for name in sorted(required_suites(profile.capabilities))
        ],
        revision="b" * 40,
        environment="container",
        environment_id="fixture-only",
        kind="suite",
        completed_at=datetime.now(UTC) - timedelta(seconds=1),
    )


def test_reports_must_cover_exact_capabilities_without_duplicates():
    args = campaign()
    with pytest.raises(ValueError, match="CONNECTOR_EVIDENCE_SUITES_INCOMPLETE"):
        cli.assemble(**(args | {"reports": args["reports"][:-1]}))
    with pytest.raises(ValueError, match="CONNECTOR_EVIDENCE_SUITES_INCOMPLETE"):
        cli.assemble(**(args | {"reports": args["reports"] + args["reports"][:1]}))


def test_changed_driver_or_kit_cannot_borrow_reports():
    args = campaign()
    args["identity"]["drivers"][0]["version"] = "0.0"
    with pytest.raises(ValueError, match="CONNECTOR_EVIDENCE_DRIVER_CHANGED"):
        cli.assemble(**args)
    args = campaign()
    args["identity"]["kit_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="CONNECTOR_EVIDENCE_COMPONENT_CHANGED"):
        cli.assemble(**args)


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_nonpassing_live_report_is_retained_and_cannot_verify(status):
    args = campaign()
    args["reports"][0]["status"] = status
    result = cli.assemble(**args)
    bundle = EvidenceBundle.model_validate(result["bundle"])
    assert any(r.status == status for r in bundle.payload.results)
    assert (
        certification_level(
            bundle.payload.identity,
            [bundle],
            now=datetime.now(UTC),
            deployed_environment_id="fixture-only",
        ).level
        == "unverified"
    )


def test_demo_metadata_and_future_proofs_are_rejected():
    args = campaign()
    with pytest.raises(ValueError, match="CONNECTOR_EVIDENCE_SOURCE_INVALID"):
        cli.assemble(**(args | {"identity": {"source": "demo", "identity": args["identity"]}}))
    with pytest.raises(ValueError, match="CONNECTOR_EVIDENCE_FROM_FUTURE"):
        cli.assemble(**(args | {"completed_at": datetime.now(UTC) + timedelta(hours=1)}))
