"""Unit fixtures for the C0 contract, not a live connector certification kit."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.services.connectors.certification import (
    Capabilities,
    ComponentIdentity,
    EvidenceBundle,
    EvidencePayload,
    certification_level,
    evidence_digest,
    required_suites,
)

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


def identity(**changes):
    return ComponentIdentity.model_validate(
        {
            "profile_key": "fixture_only",
            "profile_version": "1",
            "profile_sha256": "a" * 64,
            "capabilities": {"read": True, "consistency": "snapshot"},
            "drivers": [{"package": "fixture-driver", "version": "1.2.3"}],
            "runner_image_sha256": "b" * 64,
            "kit_version": "fixture-v1",
            "kit_sha256": "c" * 64,
            "server_version": "16.3",
            **changes,
        }
    )


def bundle(
    current=None,
    *,
    kind="suite",
    at=None,
    failure=None,
    source="real",
    environment=None,
    environment_id="fixture-host",
):
    current = current or identity()
    names = required_suites(current.capabilities) if kind == "suite" else {"canary", "revocation"}
    payload = EvidencePayload.model_validate(
        {
            "kind": kind,
            "identity": current,
            "source_revision": "d" * 40,
            "environment": environment or ("container" if kind == "suite" else "deployed"),
            "environment_id": environment_id,
            "source": source,
            "completed_at": at or NOW - timedelta(hours=1),
            "results": [
                {
                    "suite": name,
                    "status": "failed" if name == failure else "passed",
                    "evidence_sha256": "e" * 64,
                }
                for name in sorted(names)
            ],
        }
    )
    return EvidenceBundle(payload=payload, sha256=evidence_digest(payload))


def level(*bundles, current=None, **kwargs):
    return certification_level(
        current or identity(), bundles, now=NOW, deployed_environment_id="fixture-host", **kwargs
    ).level


def test_empty_catalog_does_not_invent_a_qualification():
    assert level() == "unverified"
    assert level(bundle()) == "verified"
    assert level(bundle(), bundle(kind="canary")) == "certified"
    assert level(bundle(kind="canary")) == "unverified"


def test_rerunning_unchanged_suite_preserves_a_current_canary():
    assert level(bundle(), bundle(kind="canary", at=NOW - timedelta(days=1))) == "certified"


@pytest.mark.parametrize(
    "change",
    [
        {"profile_version": "2"},
        {"profile_sha256": "f" * 64},
        {"capabilities": {"read": True, "read_partitioned": True}},
        {"drivers": [{"package": "fixture-driver", "version": "1.2.4"}]},
        {"runner_image_sha256": "f" * 64},
        {"kit_version": "fixture-v2"},
        {"kit_sha256": "f" * 64},
        {"server_version": "17.0"},
    ],
)
def test_every_changed_component_loses_both_levels(change):
    assert (
        level(bundle(), bundle(kind="canary"), current=identity(**change))
        == "needs_requalification"
    )


def test_another_profile_cannot_supply_evidence():
    assert level(bundle(identity(profile_key="another"))) == "unverified"


def test_canary_expiry_preserves_current_suite_but_not_certification():
    suite = bundle(at=NOW - timedelta(days=40))
    assert level(suite, bundle(kind="canary", at=NOW - timedelta(days=30))) == "verified"
    assert (
        level(suite, bundle(kind="canary", at=NOW - timedelta(days=30) + timedelta(seconds=1)))
        == "certified"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"source": "demo"},
        {"source": "emulator"},
        {"environment": "test_account"},
        {"environment_id": "another-host"},
        {"failure": "revocation"},
        {"at": NOW + timedelta(seconds=1)},
    ],
)
def test_non_live_wrong_environment_or_invalid_canary_never_certifies(change):
    assert level(bundle(), bundle(kind="canary", **change)) == "verified"


def test_failed_new_suite_overrides_old_success_independently_of_input_order():
    old = bundle(at=NOW - timedelta(days=1))
    failed = bundle(failure="security")
    assert level(old, failed) == level(failed, old) == "unverified"


def test_conflicting_simultaneous_evidence_fails_closed():
    assert level(bundle(), bundle(failure="security")) == "unverified"
    assert level(bundle(), bundle()) == "verified"


def test_failed_recent_canary_overrides_older_canary():
    suite = bundle(at=NOW - timedelta(days=2))
    old = bundle(kind="canary", at=NOW - timedelta(days=1))
    assert level(suite, old, bundle(kind="canary", failure="canary")) == "verified"


def test_third_party_is_never_promoted_by_native_evidence():
    assert level(bundle(), bundle(kind="canary"), origin="third_party") == "third_party"


def test_read_only_profile_requires_refusal_proofs_not_fake_write_success():
    required = required_suites(identity().capabilities)
    assert "unsupported:write_upsert" in required
    assert "write_upsert" not in required
    assert "write_unknown_outcome" not in required
    assert "consistency:snapshot" in required


def test_file_export_has_its_own_capability_and_outcome_tests():
    required = required_suites(
        Capabilities(export_files=True, write_outcome_check="conditional_put")
    )
    assert {
        "export_files",
        "outcome:conditional_put",
        "write_unknown_outcome",
        "unsupported:write_upsert",
    } <= required


@pytest.mark.parametrize(
    "change",
    [
        {"read": "true"},
        {"read_partitioned": True},
        {"watch": True},
        {"create_table": True},
        {"write_outcome_check": "marker_table"},
        {"invented": True},
    ],
)
def test_capabilities_reject_coercion_unknown_operations_and_incoherence(change):
    with pytest.raises(ValidationError):
        Capabilities.model_validate(change)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "na"])
def test_suite_cannot_skip_or_forge_applicability(mutation):
    values = bundle().payload.model_dump(mode="json")
    if mutation == "missing":
        values["results"].pop()
    elif mutation == "duplicate":
        values["results"].append(values["results"][0])
    elif mutation == "extra":
        values["results"].append(
            {"suite": "invented", "status": "passed", "evidence_sha256": "e" * 64}
        )
    else:
        values["results"][0]["status"] = "not_applicable"
    with pytest.raises(ValidationError):
        EvidencePayload.model_validate(values)


def test_skipped_required_test_does_not_verify():
    values = bundle().payload.model_dump(mode="json")
    values["results"][0]["status"] = "skipped"
    payload = EvidencePayload.model_validate(values)
    assert level(EvidenceBundle(payload=payload, sha256=evidence_digest(payload))) == "unverified"


def test_mutated_bundle_and_naive_time_are_rejected():
    values = bundle().model_dump(mode="json")
    values["payload"]["results"][0]["status"] = "failed"
    with pytest.raises(ValidationError, match="DIGEST_MISMATCH"):
        EvidenceBundle.model_validate(values)
    values["payload"]["completed_at"] = "2026-10-14T11:00:00"
    with pytest.raises(ValidationError, match="TIMEZONE_REQUIRED"):
        EvidencePayload.model_validate(values["payload"])


def test_future_suite_and_demo_fallback_never_verify():
    assert level(bundle(at=NOW + timedelta(seconds=1))) == "unverified"
    assert level(bundle(source="demo")) == "unverified"


def test_hana_requires_a_real_server_not_showcase_demo_or_container():
    hana = identity(profile_key="sap_hana")
    assert level(bundle(hana), current=hana) == "unverified"
    assert (
        level(bundle(hana, source="demo", environment="test_account"), current=hana) == "unverified"
    )
    assert level(bundle(hana, environment="test_account"), current=hana) == "verified"


def test_driver_order_is_not_a_component_change_but_duplicates_are_invalid():
    drivers = [{"package": "alpha", "version": "1.0"}, {"package": "beta", "version": "2.0"}]
    assert identity(drivers=drivers).sha256 == identity(drivers=list(reversed(drivers))).sha256
    with pytest.raises(ValidationError, match="DUPLICATE_DRIVER"):
        identity(drivers=[drivers[0], drivers[0]])
    with pytest.raises(ValidationError):
        identity(drivers=[{"package": "alpha", "version": ">=1.0"}])


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_age_policy_must_be_positive_whole_days(value):
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        level(max_age_days=value)
