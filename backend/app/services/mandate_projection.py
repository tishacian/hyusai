"""Readable mandate and evidence, without promoting configuration to proof.

The caller must authorize the System, Run, Decisions and invocations before
passing them here. No business payload, prompt or held output is projected.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.services.control_policy_snapshot import (
    control_policy_execution_contract,
    thaw_control_policy,
    validated_control_policy_execution_contract,
)
from app.services.flow_contracts import validate_execution_contract
from app.services.membrane.spec import FACET_NAMES, MembraneSpec, resolve_membrane_spec
from app.services.projection_integrity import canonical_run_provenance, scrub_projection_mapping


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def configuration(policy: Any) -> dict[str, Any]:
    empty = {"policy_id": None, "policy_revision": None, "version": None,
             "mode": None, "spec": None, "configured_facets": []}
    if policy is None:
        return {**empty, "state": "not_configured"}
    try:
        spec = resolve_membrane_spec(control=policy)
        revision = control_policy_execution_contract(policy)["revision"]
    except (ValueError, TypeError, OverflowError):
        return {**empty, "policy_id": policy.id, "state": "invalid"}
    return {"state": "explicit" if spec.authoritative else "derived",
            "policy_id": policy.id, "policy_revision": revision,
            "version": spec.version, "mode": spec.effective_mode.value,
            "spec": _public_spec(spec), "configured_facets": sorted(
                spec.configured_facets() if spec.authoritative else
                spec.configured_facets() & {"capabilities", "valves"})}


def _public_spec(spec: MembraneSpec) -> dict[str, Any]:
    payload = spec.to_dict()
    # A storage address is infrastructure configuration, not a user source.
    payload["provenance"].pop("object_store_prefix", None)
    return scrub_projection_mapping(payload)


def published_configuration(*, system: Any, version: Any,
                            legacy_policy: Any = None) -> dict[str, Any]:
    """Describe the publication used by admission, without reading a draft.

    A legacy publication still uses its current policy. An explicit frozen
    absence or invalid frozen contract must never inherit that mutable policy.
    """
    identity = {"published_version_id": getattr(version, "id", None),
                "published_version_number": getattr(version, "version_number", None),
                "policy_snapshot_sha256": None}
    invalid = {**configuration(None), **identity, "state": "invalid", "policy_binding": "invalid"}
    expected_id = getattr(system, "published_flow_version_id", None)
    if version is None:
        return invalid if expected_id else {
            **configuration(legacy_policy), **identity, "policy_binding": "legacy_current"}
    if (version.system_id != system.id or version.workspace_id != system.workspace_id
            or expected_id is not None and version.id != expected_id):
        return invalid
    raw_contract = getattr(version, "execution_contract", None)
    try:
        contract = validate_execution_contract(raw_contract) if raw_contract is not None else {}
        if "control_policy_snapshot" not in contract:
            return {**configuration(legacy_policy), **identity, "policy_binding": "legacy_current"}
        frozen = contract["control_policy_snapshot"]
        policy = thaw_control_policy(frozen, workspace_id=system.workspace_id, system_id=system.id)
    except (ValueError, TypeError, OverflowError):
        return invalid
    return {**configuration(policy), **identity, "policy_binding": "frozen",
            "policy_snapshot_sha256": frozen["sha256"]}


def snapshot(policy: Any) -> dict[str, Any]:
    """Server-owned first-start observation; does not enable any enforcement."""
    value = configuration(policy)
    return {"schema_version": 1, **value}


def _applied(run: Any) -> dict[str, Any]:
    execution = _mapping(_mapping(run.input_ref).get("execution"))
    checkpoints = [_mapping(cp) for cp in (run.checkpoints or [])]
    boundary = next((cp for cp in checkpoints if cp.get("kind") == "mandate_snapshot"), {})
    if boundary:
        execution = boundary
    contract = validated_control_policy_execution_contract(execution.get("control_policy"))
    result = {"state": "not_recorded", "policy_id": None, "revision": None,
              "snapshot_at": None, "mode": None, "version": None, "spec": None,
              "policy_binding": None, "not_recorded_reason": None}
    # A pending Run can still contain caller-provided input. Only the engine's
    # first-start boundary owns execution metadata.
    if (run.status == "pending" or not execution.get("snapshot_at")
            or not (boundary or any(cp.get("kind") == "run_start" for cp in checkpoints))):
        return result
    frozen_contract = _mapping(getattr(run, "execution_contract", None))
    if "control_policy_snapshot" in frozen_contract:
        # The executable contract is authoritative, but is not proof of a
        # start until the engine recorded the same policy at its boundary.
        try:
            frozen_contract = validate_execution_contract(frozen_contract)
            policy = thaw_control_policy(frozen_contract["control_policy_snapshot"],
                                         workspace_id=run.workspace_id, system_id=run.system_id)
        except (ValueError, TypeError, OverflowError):
            return {**result, "policy_binding": "invalid", "not_recorded_reason": "frozen_mandate_invalid"}
        expected = (control_policy_execution_contract(policy) if policy is not None
                    else {"schema_version": 1, "state": "not_configured"})
        if not boundary or execution.get("control_policy") != expected:
            return {**result, "policy_binding": "frozen", "not_recorded_reason": "mandate_start_identity_mismatch"}
        actual = configuration(policy)
        return {**result, "state": "recorded", "policy_binding": "frozen",
                "policy_id": actual["policy_id"], "revision": actual["policy_revision"],
                "snapshot_at": execution["snapshot_at"], "mode": actual["mode"],
                "version": actual["version"], "spec": actual["spec"]}
    if contract:
        result.update(state="recorded", policy_id=contract["policy_id"],
                      revision=contract["revision"], snapshot_at=execution["snapshot_at"],
                      policy_binding="legacy_first_start" if boundary else "legacy_identity_only")
    elif boundary and execution.get("control_policy") == {"schema_version": 1, "state": "not_configured"}:
        result.update(state="recorded", snapshot_at=execution["snapshot_at"], policy_binding="legacy_first_start")
    recorded = _mapping(execution.get("mandate"))
    if (boundary and contract and recorded.get("schema_version") == 1
            and recorded.get("policy_id") == contract["policy_id"]
            and recorded.get("policy_revision") == contract["revision"]):
        try:
            spec = MembraneSpec.from_dict(recorded["spec"], authoritative=recorded.get("state") == "explicit")
        except (KeyError, TypeError, ValueError, OverflowError):
            return result
        result.update(mode=spec.effective_mode.value, version=spec.version, spec=_public_spec(spec))
    return result


def _event(identity: str, kind: str, facet: str, status: str, payload: dict,
           *, at: str | None = None, invocation_id: str | None = None,
           decision_id: str | None = None, child_run_id: str | None = None) -> dict[str, Any]:
    # Closed metadata allowlist: never copy a checkpoint's state, prompt,
    # citations, rationale body, artifact URL or held result into this surface.
    keys = {"mode", "disposition", "would_disposition", "reason", "reasons", "violations",
            "breaches", "citation_count", "filtered_count", "would_block",
            "sha256", "size_bytes", "decision_status", "human_confirmed", "child_status"}
    details = scrub_projection_mapping({key: value for key, value in payload.items() if key in keys})
    rules = details.get("breaches") or details.get("reasons") or details.get("violations") or []
    if not rules and isinstance(details.get("reason"), str):
        rules = [details["reason"]]
    return {"id": identity, "kind": kind, "facet": facet, "status": status,
            "at": at, "node_id": payload.get("node_id"), "invocation_id": invocation_id,
            "decision_id": decision_id, "child_run_id": child_run_id,
            "rule": str(rules[0]) if isinstance(rules, list) and rules else None,
            "details": details}


def run_mandate(run: Any, *, decisions: list[Any], invocations: list[Any],
                children: list[Any] | None = None,
                forwarded_decision_run_ids: dict[str, str] | None = None) -> dict[str, Any]:
    events = []
    decision_ids = {item.id for item in decisions}
    # Match the canonical Run serializer's active gate, not every historical
    # proposed Decision that happens to reference this Run.
    active_gate = next((cp for cp in reversed(run.checkpoints or [])
                        if isinstance(cp, Mapping) and cp.get("kind") == "hitl_pause"), {})
    provenance = canonical_run_provenance(run, invocations)
    provenance_pairs = {(item["uri"], item["sha256"]) for item in provenance}
    projected_provenance = set()
    forwarded_decision_run_ids = forwarded_decision_run_ids or {}
    for index, raw in enumerate(run.checkpoints or []):
        cp = _mapping(raw)
        kind = cp.get("kind")
        facet, status = None, "recorded"
        if kind == "membrane_egress_evaluated":
            facet = "outbound"
            disposition = str(cp.get("disposition") or "").lower()
            status = ("observed" if cp.get("mode") == "shadow" else
                      "blocked" if disposition == "block" else "recorded")
        elif kind == "membrane_valve_breach":
            facet = "valves"
            # A breach marker is not itself proof that execution stopped.
            stopped = (run.status in {"failed", "cancelled"}
                       and str(getattr(run, "error", None) or "").startswith("membrane_valve_breach:"))
            status = "blocked" if stopped else "observed"
        elif kind == "membrane_provenance":
            pair = (cp.get("uri"), cp.get("sha256"))
            if all(isinstance(value, str) for value in pair) and pair in provenance_pairs and pair not in projected_provenance:
                facet = "provenance"
                projected_provenance.add(pair)
        elif kind in {"hitl_pause", "hitl_resume"}:
            # The canonical authorized Decision below is the current gate
            # state. Historical pause checkpoints must not inflate open gates.
            if cp.get("decision_id") in decision_ids:
                continue
            facet = "outbound"
        if facet:
            events.append(_event(f"checkpoint:{index}", kind, facet, status, cp, at=cp.get("t")))

    for invocation in invocations:
        trace = _mapping(invocation.trace)
        inbound = _mapping(trace.get("membrane_inbound"))
        if inbound:
            events.append(_event(f"invocation:{invocation.id}:inbound", "membrane_inbound",
                                 "inbound", "observed" if inbound.get("mode") == "shadow" else "recorded",
                                 inbound, at=_iso(invocation.started_at), invocation_id=invocation.id))
        # The checkpoint above is projected once, only when the canonical
        # checksum/URI markers agree with an authorized invocation ledger.

    for decision in decisions:
        rationale = _mapping(decision.rationale)
        # Only a persisted canonical relationship binds a Decision to this Run.
        if not ((decision.scope == "run" and decision.target_id == run.id)
                or rationale.get("run_id") == run.id
                or forwarded_decision_run_ids.get(decision.id) == decision.target_id):
            continue
        if decision.kind not in {"policy_block", "policy_shadow", "policy_breach", "hitl_approval"}:
            continue
        facet = rationale.get("facet")
        if facet not in FACET_NAMES:
            facet = "outbound" if decision.kind == "hitl_approval" else (
                "valves" if decision.kind == "policy_breach" else "capabilities")
        status = {"policy_block": "blocked", "policy_shadow": "observed",
                  "policy_breach": "recorded"}.get(decision.kind, "recorded")
        human = bool(decision.human_confirmed_by and decision.human_confirmed_at)
        if decision.kind == "hitl_approval":
            active = (decision.id == active_gate.get("decision_id")
                      and decision.status == "proposed" and run.status == "hitl_pending")
            deadline = getattr(decision, "expires_at", None) or active_gate.get("expires_at")
            unexpired = True
            if active and deadline:
                try:
                    parsed = deadline if isinstance(deadline, datetime) else datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
                    unexpired = parsed.replace(tzinfo=UTC) > datetime.now(UTC) if parsed.tzinfo is None else parsed > datetime.now(UTC)
                except (ValueError, TypeError, OverflowError):
                    unexpired = False
            if active and unexpired:
                status = "awaiting_human"
            elif human and decision.status in {"accepted", "applied"}:
                status = "approved"
            elif human and decision.status == "rejected":
                status = "rejected"
        events.append(_event(f"decision:{decision.id}", decision.kind, facet, status,
                             {**rationale, "decision_status": decision.status, "human_confirmed": human},
                             at=_iso(decision.human_confirmed_at if human else decision.created_at),
                             decision_id=decision.id,
                             child_run_id=forwarded_decision_run_ids.get(decision.id)))
    for child in children or []:
        if (child.parent_run_id != run.id or child.workspace_id != run.workspace_id
                or child.trigger != "subflow" or not child.delegation_key or not child.delegation_node_id):
            continue
        events.append(_event(f"delegation:{child.id}", "subflow_run", "delegation", "recorded",
                             {"node_id": child.delegation_node_id, "child_status": child.status},
                             at=_iso(child.started_at), child_run_id=child.id))
    events.sort(key=lambda event: (event["at"] or "", event["id"]))
    facets = {}
    for facet in FACET_NAMES:
        rows = [event for event in events if event["facet"] == facet
                or (facet == "capabilities" and event["facet"] == "delegation")]
        breaches = sum(event["status"] == "blocked" for event in rows)
        facets[facet] = {"event_count": len(rows), "breach_count": breaches,
                         "state": "breached" if breaches else "recorded" if rows else "not_recorded"}
    applied = _applied(run)
    limitations = ["configuration_is_not_execution_proof", "absence_of_event_is_not_success"]
    if applied["not_recorded_reason"]:
        limitations.append(applied["not_recorded_reason"])
    elif applied["state"] == "recorded" and applied["policy_id"] is None:
        limitations.append("no_policy_at_first_start")
    elif applied["spec"] is None:
        limitations.append("historical_mandate_spec_not_recorded")
    else:
        limitations.append("mandate_snapshot_at_first_start")
    return {"run_id": run.id, "system_id": run.system_id, "status": run.status,
            "applied": applied, "events": events, "facets": facets,
            "counts": {"recorded_events": len(events),
                       "blocked": sum(e["status"] == "blocked" for e in events),
                       "awaiting_human": sum(e["status"] == "awaiting_human" for e in events)},
            "delegation_limit": 20, "limitations": limitations}
