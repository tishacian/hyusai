from copy import deepcopy
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace as NS

from app.models.policy import ControlPolicy
from app.services.control_policy_snapshot import control_policy_execution_contract, freeze_control_policy
from app.services.flow_contracts import canonical_sha256
from app.services.mandate_projection import configuration, published_configuration, run_mandate, snapshot


def policy():
    return ControlPolicy(id="policy", workspace_id="ws", scope="system", target_id="system",
                         extra={"membrane_spec": {"version": 2, "enforcement_mode": "enforce",
                                "inbound": {"collection_allowlist": ["manuals"]},
                                "provenance": {"object_store_prefix": "private/prefix"}}})


def run(**kw):
    return NS(**{"id": "run", "system_id": "system", "workspace_id": "ws", "status": "completed",
                 "execution_contract": None,
                 "input_ref": {}, "output_ref": {}, "checkpoints": [], "error": None, **kw})


def executable(policy):
    value = {"schema_version": 1, "runtime_mode": "dag_overlay", "validation_mode": "observe",
             "ingresses": [], "nodes": {}, "outputs": [],
             "control_policy_snapshot": freeze_control_policy(policy, workspace_id="ws", system_id="system")}
    return {**value, "contract_sha256": canonical_sha256(value)}


def publication(contract):
    return NS(id="version-1", system_id="system", workspace_id="ws", version_number=1, execution_contract=contract)


def system():
    return NS(id="system", workspace_id="ws", published_flow_version_id="version-1")


def boundary(policy):
    return {"kind": "mandate_snapshot", "snapshot_at": "2026-09-17T10:00:00Z",
            "control_policy": control_policy_execution_contract(policy) if policy else {"schema_version": 1, "state": "not_configured"},
            "mandate": snapshot(policy)}


def test_published_mandate_uses_frozen_version_not_a_mutated_live_row():
    current = policy()
    version = publication(executable(current))
    current.extra = {"membrane_spec": {"version": 2, "enforcement_mode": "shadow"}}
    value = published_configuration(system=system(), version=version, legacy_policy=current)
    assert value["mode"] == "enforce"
    assert value["policy_binding"] == "frozen"
    assert value["published_version_number"] == 1
    assert value["policy_snapshot_sha256"] == version.execution_contract["control_policy_snapshot"]["sha256"]
    assert "object_store_prefix" not in value["spec"]["provenance"]


def test_published_explicit_absence_never_inherits_a_live_policy():
    value = published_configuration(system=system(), version=publication(executable(None)), legacy_policy=policy())
    assert value["state"] == "not_configured"
    assert value["policy_binding"] == "frozen"
    assert value["spec"] is None


def test_legacy_published_policy_is_labelled_current_and_missing_version_is_invalid():
    value = published_configuration(system=system(), version=publication(None), legacy_policy=policy())
    assert value["policy_binding"] == "legacy_current"
    assert value["mode"] == "enforce"
    assert value["policy_snapshot_sha256"] is None
    assert published_configuration(system=system(), version=None, legacy_policy=policy())["state"] == "invalid"


def test_invalid_frozen_publication_does_not_fall_back_to_live_policy():
    contract = executable(policy())
    contract["control_policy_snapshot"]["policy"]["extra"] = {}
    value = published_configuration(system=system(), version=publication(contract), legacy_policy=policy())
    assert value["state"] == value["policy_binding"] == "invalid"
    assert value["spec"] is None
    wrong = publication(executable(policy()))
    wrong.workspace_id = "other-tenant"
    assert published_configuration(system=system(), version=wrong, legacy_policy=policy())["state"] == "invalid"
    wrong = publication(executable(policy()))
    wrong.id = "old-version"
    assert published_configuration(system=system(), version=wrong, legacy_policy=policy())["state"] == "invalid"


def test_frozen_contract_requires_matching_actual_first_start_and_never_infers_queue_execution():
    current = policy()
    contract = executable(current)
    checkpoint = boundary(current)
    for item in [run(status="pending", execution_contract=contract), run(execution_contract=contract)]:
        assert run_mandate(item, decisions=[], invocations=[])["applied"]["state"] == "not_recorded"
    # A copied public summary is not authoritative over the executable policy.
    checkpoint["mandate"]["spec"]["enforcement_mode"] = "shadow"
    item = run(execution_contract=contract, checkpoints=[checkpoint])
    applied = run_mandate(item, decisions=[], invocations=[])["applied"]
    assert applied["state"] == "recorded" and applied["policy_binding"] == "frozen"
    assert applied["mode"] == "enforce"
    assert "object_store_prefix" not in applied["spec"]["provenance"]
    current.extra = {"membrane_spec": {"version": 2, "enforcement_mode": "shadow"}}
    item.checkpoints = [boundary(current)]
    mismatch = run_mandate(item, decisions=[], invocations=[])
    assert mismatch["applied"]["state"] == "not_recorded"
    assert "mandate_start_identity_mismatch" in mismatch["limitations"]


def test_tampered_frozen_run_is_not_presented_as_applied_even_with_matching_checkpoint():
    current = policy()
    contract = executable(current)
    contract["control_policy_snapshot"]["policy"]["extra"] = {}
    value = run_mandate(run(execution_contract=contract, checkpoints=[boundary(current)]), decisions=[], invocations=[])
    assert value["applied"]["state"] == "not_recorded"
    assert value["applied"]["spec"] is None
    assert "frozen_mandate_invalid" in value["limitations"]


def test_explicit_absence_at_first_start_is_recorded_without_fabricating_a_spec():
    value = run_mandate(run(execution_contract=executable(None), checkpoints=[boundary(None)]), decisions=[], invocations=[])
    assert value["applied"]["state"] == "recorded"
    assert value["applied"]["policy_id"] is None and value["applied"]["spec"] is None
    assert "no_policy_at_first_start" in value["limitations"]
    assert "historical_mandate_spec_not_recorded" not in value["limitations"]


def test_historical_input_keeps_digest_only_not_a_caller_supplied_full_mandate():
    execution = boundary(policy())
    item = run(input_ref={"execution": execution}, checkpoints=[{"kind": "run_start"}])
    value = run_mandate(item, decisions=[], invocations=[])
    assert value["applied"]["state"] == "recorded"
    assert value["applied"]["policy_binding"] == "legacy_identity_only"
    assert value["applied"]["spec"] is None
    assert value["applied"]["mode"] is None


def test_configuration_does_not_claim_actual_execution_and_strips_storage():
    value = configuration(policy())
    assert value["state"] == "explicit" and value["mode"] == "enforce"
    assert "object_store_prefix" not in value["spec"]["provenance"]
    evidence = run_mandate(run(), decisions=[], invocations=[])
    assert evidence["applied"]["state"] == "not_recorded"
    assert all(facet["state"] == "not_recorded" for facet in evidence["facets"].values())


def test_derived_defaults_are_not_counted_as_configured_controls():
    legacy = ControlPolicy(id="legacy", workspace_id="ws", extra={}, allowed_models=["model"])
    value = configuration(legacy)
    assert value["state"] == "derived"
    assert value["mode"] == "compat"
    assert value["configured_facets"] == ["capabilities"]
    assert configuration(None)["state"] == "not_configured"


def test_invalid_spec_stays_invalid_instead_of_becoming_empty_enforcement():
    bad = policy()
    bad.extra = {"membrane_spec": {"version": 2, "valves": {"token_budget": -1}}}
    assert configuration(bad)["state"] == "invalid"


def test_snapshot_requires_matching_policy_identity_and_never_reads_current_policy():
    current = policy()
    execution = {"snapshot_at": "2026-09-17T10:00:00Z",
                 "control_policy": control_policy_execution_contract(current),
                 "mandate": snapshot(current)}
    recorded = deepcopy(execution)
    current.extra = {"membrane_spec": {"version": 2, "enforcement_mode": "shadow"}}
    value = run_mandate(run(checkpoints=[{"kind": "mandate_snapshot", **execution}]), decisions=[], invocations=[])
    assert value["applied"]["mode"] == "enforce"
    assert execution == recorded
    execution["mandate"]["policy_revision"] = "changed"
    assert run_mandate(run(checkpoints=[{"kind": "mandate_snapshot", **execution}]), decisions=[], invocations=[])["applied"]["spec"] is None


def test_pending_caller_supplied_execution_cannot_claim_evidence():
    current = policy()
    execution = {"snapshot_at": "2026-09-17T10:00:00Z", "control_policy": control_policy_execution_contract(current),
                 "mandate": snapshot(current)}
    value = run_mandate(run(status="pending", input_ref={"execution": execution}), decisions=[], invocations=[])
    assert value["applied"]["state"] == "not_recorded"
    # A capability guard can fail before the engine's first-start snapshot.
    value = run_mandate(run(status="failed", input_ref={"execution": execution}), decisions=[], invocations=[])
    assert value["applied"]["state"] == "not_recorded"


def decision(**kw):
    return NS(**{"id": "decision", "scope": "run", "target_id": "run", "kind": "hitl_approval",
                 "status": "accepted", "rationale": {}, "created_at": datetime(2026, 9, 17),
                 "human_confirmed_by": None, "human_confirmed_at": None, **kw})


def test_only_explicit_human_confirmation_is_presented_as_human_approval():
    automatic = decision()
    confirmed = decision(id="human", human_confirmed_by="user", human_confirmed_at=datetime(2026, 9, 18))
    events = run_mandate(run(), decisions=[automatic, confirmed], invocations=[])["events"]
    assert {row["id"]: row["status"] for row in events} == {"decision:decision": "recorded", "decision:human": "approved"}
    assert next(row for row in events if row["id"] == "decision:human")["at"] == "2026-09-18T00:00:00"


def test_resolved_pause_is_not_still_counted_as_awaiting_human():
    item = run(checkpoints=[{"kind": "hitl_pause", "decision_id": "decision", "state": {"secret": "HELD_OUTPUT"}}])
    result = run_mandate(item, decisions=[decision()], invocations=[])
    assert result["counts"]["awaiting_human"] == 0
    assert "HELD_OUTPUT" not in str(result)


def test_only_latest_unexpired_gate_is_awaiting_human():
    item = run(status="hitl_pending", checkpoints=[
        {"kind": "hitl_pause", "decision_id": "old"},
        {"kind": "hitl_pause", "decision_id": "active"},
    ])
    old = decision(id="old", status="proposed")
    active = decision(id="active", status="proposed", expires_at=datetime.now(UTC) + timedelta(minutes=5))
    result = run_mandate(item, decisions=[old, active], invocations=[])
    states = {event["id"]: event["status"] for event in result["events"]}
    assert states == {"decision:active": "awaiting_human", "decision:old": "recorded"}
    assert result["counts"]["awaiting_human"] == 1
    active.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert run_mandate(item, decisions=[old, active], invocations=[])["counts"]["awaiting_human"] == 0
    active.expires_at = None
    item.checkpoints[-1]["expires_at"] = "invalid"
    assert run_mandate(item, decisions=[old, active], invocations=[])["counts"]["awaiting_human"] == 0


def test_shadow_egress_is_an_observation_and_actual_breach_is_blocked():
    item = run(status="failed", error="membrane_valve_breach:cost", checkpoints=[{"kind": "membrane_egress_evaluated", "mode": "shadow", "would_disposition": "block",
                            "disposition": "allow", "reasons": ["citations_required"], "prompt": "SECRET"},
                           {"kind": "membrane_valve_breach", "breaches": ["cost"]}])
    result = run_mandate(item, decisions=[], invocations=[])
    assert result["facets"]["outbound"]["breach_count"] == 0
    assert result["facets"]["valves"]["breach_count"] == 1
    assert "SECRET" not in str(result)
    item.status, item.error = "completed", None
    observed = run_mandate(item, decisions=[], invocations=[])
    assert observed["facets"]["valves"]["breach_count"] == 0


def test_historical_membrane_metadata_is_not_an_artifact_receipt():
    inv = NS(id="inv", run_id="run", trace={"membrane": {"authoritative": True, "decision": "approved"}}, started_at=None)
    assert run_mandate(run(), decisions=[], invocations=[inv])["events"] == []
    inv.trace = {"membrane_provenance": {"sha256": "a" * 64, "uri": "secret://internal", "size_bytes": 12}}
    value = run_mandate(run(), decisions=[], invocations=[inv])
    assert value["facets"]["provenance"]["event_count"] == 0
    assert "secret://" not in str(value)


def test_provenance_is_projected_once_only_when_runtime_markers_agree():
    receipt = {"sha256": "a" * 64, "uri": "object://membrane/run/provenance.json", "size_bytes": 12}
    inv = NS(id="inv", run_id="run", trace={"membrane_provenance": receipt}, started_at=None)
    item = run(checkpoints=[{"kind": "membrane_provenance", **receipt}])
    value = run_mandate(item, decisions=[], invocations=[inv])
    assert value["facets"]["provenance"]["event_count"] == 1
    assert "object://" not in str(value)
    inv.trace["membrane_provenance"] = {**receipt, "sha256": "b" * 64}
    assert run_mandate(item, decisions=[], invocations=[inv])["facets"]["provenance"]["event_count"] == 0


def test_same_digest_on_another_uri_and_repeated_receipt_do_not_inflate_provenance():
    receipt = {"sha256": "a" * 64, "uri": "object://membrane/run/provenance.json", "size_bytes": 12}
    inv = NS(id="inv", run_id="run", trace={"membrane_provenance": receipt}, started_at=None)
    item = run(checkpoints=[{"kind": "membrane_provenance", **receipt},
                           {"kind": "membrane_provenance", **receipt, "uri": "object://other/file"},
                           {"kind": "membrane_provenance", **receipt}])
    assert run_mandate(item, decisions=[], invocations=[inv])["facets"]["provenance"]["event_count"] == 1


def test_unrelated_decisions_are_never_attached_by_system_only():
    unrelated = decision(scope="system", target_id="system", rationale={"run_id": "another"})
    assert run_mandate(run(), decisions=[unrelated], invocations=[])["events"] == []


def test_postcheck_decision_proves_a_block_only_with_matching_persisted_stop():
    item = run(status="failed", error="membrane_valve_breach:cost_measurement_unavailable")
    breach = decision(kind="policy_breach", status="applied", rationale={
        "run_id": "run", "hard_abort": True, "mode": "enforce",
        "breaches": ["cost_measurement_unavailable"],
    })
    value = run_mandate(item, decisions=[breach], invocations=[])
    assert value["events"][0]["status"] == "blocked"
    assert value["counts"]["blocked"] == 1
    assert value["facets"]["valves"]["state"] == "breached"
    for status, error, abort in [
        ("completed", None, True),
        ("failed", "unrelated_error", True),
        ("failed", "membrane_valve_breach:latency", True),
        ("failed", "membrane_valve_breach:cost_measurement_unavailable", False),
    ]:
        item.status, item.error = status, error
        breach.rationale["hard_abort"] = abort
        assert run_mandate(item, decisions=[breach], invocations=[])["counts"]["blocked"] == 0
