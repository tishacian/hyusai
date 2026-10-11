"""Focused safety tests for the Andritz MembraneSpec v2 shadow preparation."""
from __future__ import annotations

import copy
from uuid import uuid4

import pytest

from app.models.audit import AuditLog
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.membrane.spec import EnforcementMode, MembraneSpec
from scripts import prepare_andritz_membrane_shadow as shadow


@pytest.fixture(autouse=True)
def _ready_lot6_showcase(monkeypatch):
    monkeypatch.setattr(
        shadow,
        "_lot6_showcase_status",
        lambda _db: {
            "ready": True,
            "phase": "projection_active",
            "workspace_id": "showcase-workspace-id",
            "capability_id": "showcase-capability-id",
            "system_id": "showcase-system-id",
        },
    )


def _v1_membrane():
    return {
        "version": 1,
        "inbound": {
            "collection_allowlist": ["opaque-evidence"],
            "reference_type_filters": ["document_name"],
            "reject_cross_project_sources": True,
            "preserve_reference_types": True,
        },
        "outbound": {
            "expert_review_required": False,
            "gate_if_confidence_below": 0.45,
        },
        "capabilities": {
            "allowed_skills": ["opaque_skill"],
            "allowed_models": ["opaque-model"],
        },
        "provenance": {
            "require_citations": True,
            "object_store_prefix": "membrane/opaque/",
        },
        "valves": {
            "max_cost_per_decision": 2,
            "max_latency_ms": 20_000,
            "hard_abort": False,
            "circuit_breaker": {"max_attempts": 3},
            "token_budget": 4_000,
        },
    }


def _seed_target(db, *, family="andritz", membrane=None):
    workspace = Workspace(
        id=str(uuid4()),
        name="Opaque industrial workspace",
        slug=f"opaque-{uuid4()}",
        settings={"family": family},
    )
    flow = {"schema_version": 3, "nodes": [], "edges": []}
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Opaque governed system",
        objective="Test append-only shadow",
        flow_definition=copy.deepcopy(flow),
        status="active",
        settings={"seed_origin": f"canonical-{uuid4()}"},
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Opaque membrane",
        scope="system",
        target_id=system.id,
        max_latency_ms=20_000,
        allowed_models=["opaque-model"],
        allowed_skills=["opaque_skill"],
        extra={
            "membrane_origin": f"canonical-{uuid4()}",
            "membrane_spec": copy.deepcopy(membrane or _v1_membrane()),
            "operator_extension": {"preserved": True},
        },
    )
    system.control_policy_id = policy.id
    historical_flow = {"schema_version": 2, "nodes": [], "edges": []}
    historical = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=7,
        flow_definition=copy.deepcopy(historical_flow),
        message="Historical version",
        created_by="historical-user",
    )
    db.add_all([workspace, policy, system, historical])
    db.commit()
    return workspace, system, policy, historical, flow


def test_dry_run_is_inert_and_apply_clones_policy_append_only(db_session):
    workspace, system, source_policy, historical, flow = _seed_target(db_session)
    original_policy_extra = copy.deepcopy(source_policy.extra)
    original_history = copy.deepcopy(historical.flow_definition)

    preview = shadow.prepare(db_session, apply=False, actor="operator")
    assert preview["ready"] is True
    assert preview["prerequisite"] == {
        "kind": shadow.LOT6_SHOWCASE_PREREQUISITE_KIND,
        "source": "database",
        "ready": True,
        "workspace_id": "showcase-workspace-id",
        "capability_id": "showcase-capability-id",
        "system_id": "showcase-system-id",
        "phase": "projection_active",
        "status_ref": preview["prerequisite"]["status_ref"],
    }
    assert preview["prerequisite"]["status_ref"].startswith("sha256:")
    assert preview["changed_count"] == 1
    assert preview["targets"][0]["target_mode"] == "shadow"
    assert system.control_policy_id == source_policy.id
    assert db_session.query(ControlPolicy).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 1

    applied = shadow.prepare(db_session, apply=True, actor="operator")
    assert applied["changed_count"] == 1
    db_session.refresh(system)
    db_session.refresh(source_policy)
    db_session.refresh(historical)
    assert source_policy.extra == original_policy_extra
    assert historical.flow_definition == original_history
    assert historical.version_number == 7
    assert system.flow_definition == flow
    assert system.control_policy_id != source_policy.id

    prepared = db_session.query(ControlPolicy).filter_by(id=system.control_policy_id).one()
    marker = prepared.extra[shadow.SHADOW_MARKER_KEY]
    assert marker["source_policy_id"] == source_policy.id
    assert (
        marker["lot6_showcase_status_ref"]
        == preview["prerequisite"]["status_ref"]
    )
    assert marker["lot6_showcase_system_id"] == "showcase-system-id"
    assert prepared.extra["operator_extension"] == {"preserved": True}
    spec = MembraneSpec.from_dict(prepared.extra["membrane_spec"], authoritative=True)
    assert spec.version == 2
    assert spec.effective_mode is EnforcementMode.SHADOW
    versions = (
        db_session.query(SystemVersion)
        .filter_by(system_id=system.id)
        .order_by(SystemVersion.version_number)
        .all()
    )
    assert [version.version_number for version in versions] == [7, 8]
    assert versions[-1].flow_definition == flow
    assert versions[0].configuration_snapshot is None
    assert versions[-1].configuration_snapshot == {
        "schema_version": 1,
        "bindings": {"control_policy_id": prepared.id},
        "transition": {
            "kind": "control_policy_rebind",
            "previous_control_policy_id": source_policy.id,
            "enforcement_mode": "shadow",
            "source_contract_sha256": marker["source_membrane_sha256"],
            "target_contract_sha256": marker["target_membrane_sha256"],
        },
    }
    assert marker["configuration_snapshot_sha256"] == shadow._sha256(
        versions[-1].configuration_snapshot
    )
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.andritz.membrane_shadow.prepared",
        )
        .count()
        == 1
    )
    preparation_audit = (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.andritz.membrane_shadow.prepared",
        )
        .one()
    )
    assert (
        preparation_audit.details["lot6_showcase_status_ref"]
        == preview["prerequisite"]["status_ref"]
    )

    repeated = shadow.prepare(db_session, apply=True, actor="retry")
    assert repeated["changed_count"] == 0
    assert db_session.query(ControlPolicy).filter_by(workspace_id=workspace.id).count() == 2
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 2


def test_prepare_requires_ready_lot6_showcase_database_status(
    db_session,
    monkeypatch,
):
    workspace, system, source_policy, historical, _flow = _seed_target(db_session)
    monkeypatch.setattr(
        shadow,
        "_lot6_showcase_status",
        lambda _db: {
            "ready": False,
            "phase": "axes_active",
            "workspace_id": "showcase-workspace-id",
            "capability_id": "showcase-capability-id",
            "system_id": "showcase-system-id",
        },
    )

    preview = shadow.prepare(db_session, apply=False, actor="operator")
    assert preview["ready"] is True
    assert preview["blockers"] == []
    assert preview["prerequisite"]["ready"] is False
    assert preview["prerequisite"]["phase"] == "axes_active"
    assert preview["prerequisite"]["status_ref"].startswith("sha256:")

    with pytest.raises(shadow.AndritzShadowError, match="lot6_showcase_not_ready"):
        shadow.prepare(db_session, apply=True, actor="operator")
    db_session.rollback()
    assert system.control_policy_id == source_policy.id
    assert db_session.query(ControlPolicy).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).one().id == historical.id


def test_discovery_requires_canonical_family_and_explicit_membrane_marker(db_session):
    workspace, system, policy, _, _ = _seed_target(db_session, family="generic")
    report = shadow.prepare(db_session, apply=False, actor="operator")
    assert report["ready"] is False
    assert report["blockers"] == [{"code": "no_canonical_family", "family": "andritz"}]

    workspace.settings = {"family": "andritz"}
    extra = dict(policy.extra)
    extra.pop("membrane_origin")
    policy.extra = extra
    db_session.commit()
    report = shadow.prepare(db_session, apply=False, actor="operator")
    assert report["ready"] is False
    assert report["blockers"] == [
        {"code": "no_marked_membrane_system", "workspace_id": workspace.id}
    ]
    assert system.control_policy_id == policy.id


def test_enforce_source_is_reported_and_apply_is_blocked(db_session):
    membrane = _v1_membrane()
    membrane["version"] = 2
    membrane["enforcement_mode"] = "enforce"
    membrane["capabilities"]["allowed_delegations"] = []
    membrane["capabilities"]["allowed_actions"] = []
    workspace, system, policy, historical, _ = _seed_target(
        db_session,
        membrane=membrane,
    )

    report = shadow.prepare(db_session, apply=False, actor="operator")
    assert report["ready"] is False
    assert report["blockers"][0]["code"] == "unsafe_membrane_contract"
    assert "enforce" in report["blockers"][0]["reason"]

    with pytest.raises(shadow.AndritzShadowError, match="preflight is blocked"):
        shadow.prepare(db_session, apply=True, actor="operator")
    db_session.rollback()
    assert system.control_policy_id == policy.id
    assert db_session.query(ControlPolicy).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).one().id == historical.id


def test_v1_legacy_delegation_is_reported_instead_of_guessed(db_session):
    membrane = _v1_membrane()
    membrane["capabilities"]["allowed_delegations"] = ["legacy-target"]
    _seed_target(db_session, membrane=membrane)

    report = shadow.prepare(db_session, apply=False, actor="operator")
    assert report["ready"] is False
    assert report["blockers"][0]["code"] == "unsafe_membrane_contract"
    assert "allowed_delegations" in report["blockers"][0]["reason"]


def test_existing_identical_flow_gets_configuration_only_version(db_session):
    workspace, system, policy, historical, flow = _seed_target(db_session)
    historical.flow_definition = copy.deepcopy(flow)
    db_session.commit()

    report = shadow.prepare(db_session, apply=False, actor="operator")
    assert report["ready"] is True
    assert report["blockers"] == []
    assert report["model_contract"]["system_version_scope"] == (
        "flow_and_allowlisted_configuration_evidence"
    )

    applied = shadow.prepare(db_session, apply=True, actor="operator")
    assert applied["changed_count"] == 1
    db_session.refresh(system)
    db_session.refresh(historical)
    assert system.control_policy_id != policy.id
    assert historical.flow_definition == flow
    assert historical.configuration_snapshot is None
    versions = (
        db_session.query(SystemVersion)
        .filter_by(system_id=system.id)
        .order_by(SystemVersion.version_number)
        .all()
    )
    assert len(versions) == 2
    assert versions[0].flow_definition == versions[1].flow_definition
    assert versions[1].configuration_snapshot["bindings"] == {
        "control_policy_id": system.control_policy_id
    }


def test_prepared_configuration_evidence_drift_blocks_idempotent_retry(db_session):
    workspace, system, _, _, _ = _seed_target(db_session)
    shadow.prepare(db_session, apply=True, actor="operator")
    transition = (
        db_session.query(SystemVersion)
        .filter_by(system_id=system.id)
        .order_by(SystemVersion.version_number.desc())
        .first()
    )
    transition.configuration_snapshot = {
        **transition.configuration_snapshot,
        "bindings": {"control_policy_id": "drifted-policy-reference"},
    }
    db_session.commit()

    report = shadow.prepare(db_session, apply=False, actor="operator")
    assert report["ready"] is False
    assert report["blockers"] == [
        {
            "code": "transition_configuration_snapshot_drift",
            "workspace_id": workspace.id,
            "system_id": system.id,
            "policy_id": system.control_policy_id,
            "system_version_id": transition.id,
        }
    ]


def test_shadow_rollback_is_dry_run_safe_append_only_and_idempotent(db_session):
    workspace, system, source_policy, historical, flow = _seed_target(db_session)
    shadow.prepare(db_session, apply=True, actor="operator")
    db_session.refresh(system)
    shadow_policy_id = system.control_policy_id
    shadow_policy = db_session.query(ControlPolicy).filter_by(id=shadow_policy_id).one()
    source_extra = copy.deepcopy(source_policy.extra)
    shadow_extra = copy.deepcopy(shadow_policy.extra)

    preview = shadow.rollback(db_session, apply=False, actor="operator")
    assert preview["ready"] is True
    assert preview["changed_count"] == 1
    assert preview["targets"] == [
        {
            "workspace_id": workspace.id,
            "system_id": system.id,
            "shadow_policy_id": shadow_policy.id,
            "source_policy_id": source_policy.id,
            "changed": True,
            "restored_mode": "compat",
        }
    ]
    assert system.control_policy_id == shadow_policy.id

    result = shadow.rollback(db_session, apply=True, actor="rollback-operator")
    assert result["changed_count"] == 1
    db_session.refresh(system)
    db_session.refresh(source_policy)
    db_session.refresh(shadow_policy)
    db_session.refresh(historical)
    assert system.control_policy_id == source_policy.id
    assert source_policy.extra == source_extra
    assert shadow_policy.extra == shadow_extra
    assert historical.version_number == 7
    assert historical.flow_definition != flow

    versions = (
        db_session.query(SystemVersion)
        .filter_by(system_id=system.id)
        .order_by(SystemVersion.version_number)
        .all()
    )
    assert [version.version_number for version in versions] == [7, 8, 9]
    rollback_version = versions[-1]
    assert rollback_version.flow_definition == flow
    marker = shadow_policy.extra[shadow.SHADOW_MARKER_KEY]
    assert rollback_version.configuration_snapshot == {
        "schema_version": 1,
        "bindings": {"control_policy_id": source_policy.id},
        "transition": {
            "kind": "control_policy_rebind",
            "previous_control_policy_id": shadow_policy.id,
            "enforcement_mode": "compat",
            "source_contract_sha256": marker["target_membrane_sha256"],
            "target_contract_sha256": marker["source_membrane_sha256"],
        },
    }
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.andritz.membrane_shadow.rolled_back",
        )
        .count()
        == 1
    )


def test_rollback_never_depends_on_showcase_status(db_session, monkeypatch):
    workspace, system, source_policy, _historical, _flow = _seed_target(db_session)
    shadow.prepare(db_session, apply=True, actor="operator")
    db_session.refresh(system)
    assert system.control_policy_id != source_policy.id

    monkeypatch.setattr(
        shadow,
        "_lot6_showcase_status",
        lambda _db: pytest.fail("rollback must not read the Showcase prerequisite"),
    )
    preview = shadow.rollback(db_session, apply=False, actor="operator")
    assert preview["ready"] is True
    applied = shadow.rollback(db_session, apply=True, actor="operator")
    assert applied["changed_count"] == 1
    db_session.refresh(system)
    assert system.control_policy_id == source_policy.id

    repeated = shadow.rollback(db_session, apply=True, actor="retry")
    assert repeated["changed_count"] == 0
    assert repeated["targets"][0]["changed"] is False
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 3
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.andritz.membrane_shadow.rolled_back",
        )
        .count()
        == 1
    )


def test_prepare_rollback_prepare_uses_latest_append_only_generation(db_session):
    workspace, system, source_policy, _, _ = _seed_target(db_session)

    first_prepare = shadow.prepare(db_session, apply=True, actor="operator-1")
    first_shadow_id = first_prepare["targets"][0]["policy_id"]
    shadow.rollback(db_session, apply=True, actor="rollback-1")
    db_session.refresh(system)
    assert system.control_policy_id == source_policy.id

    second_prepare = shadow.prepare(db_session, apply=True, actor="operator-2")
    second_shadow_id = second_prepare["targets"][0]["policy_id"]
    assert second_shadow_id != first_shadow_id
    assert db_session.query(ControlPolicy).filter_by(workspace_id=workspace.id).count() == 3

    preview = shadow.rollback(db_session, apply=False, actor="rollback-2")
    assert preview["ready"] is True
    assert preview["blockers"] == []
    assert preview["targets"][0]["shadow_policy_id"] == second_shadow_id
    applied = shadow.rollback(db_session, apply=True, actor="rollback-2")
    assert applied["changed_count"] == 1
    db_session.refresh(system)
    assert system.control_policy_id == source_policy.id

    repeated = shadow.rollback(db_session, apply=True, actor="retry")
    assert repeated["changed_count"] == 0
    assert repeated["targets"][0]["shadow_policy_id"] == second_shadow_id

def test_shadow_rollback_fails_closed_on_binding_or_contract_drift(db_session):
    workspace, system, source_policy, _, _ = _seed_target(db_session)
    shadow.prepare(db_session, apply=True, actor="operator")
    db_session.refresh(system)
    shadow_policy = db_session.query(ControlPolicy).filter_by(id=system.control_policy_id).one()

    other_policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Unrelated policy",
        scope="system",
        target_id=system.id,
        extra={"membrane_spec": _v1_membrane()},
    )
    db_session.add(other_policy)
    system.control_policy_id = other_policy.id
    db_session.commit()
    report = shadow.rollback(db_session, apply=False, actor="operator")
    assert report["ready"] is False
    assert report["blockers"][0]["code"] == "unsafe_shadow_rollback"
    assert "binding drift" in report["blockers"][0]["reason"]

    system.control_policy_id = shadow_policy.id
    extra = copy.deepcopy(source_policy.extra)
    extra["membrane_spec"]["valves"]["token_budget"] = 9999
    source_policy.extra = extra
    db_session.commit()
    report = shadow.rollback(db_session, apply=False, actor="operator")
    assert report["ready"] is False
    assert report["blockers"][0]["code"] == "unsafe_shadow_rollback"
    assert "digest drift" in report["blockers"][0]["reason"]

    with pytest.raises(shadow.AndritzShadowError, match="preflight is blocked"):
        shadow.rollback(db_session, apply=True, actor="operator")


@pytest.mark.parametrize("operation", [shadow.prepare, shadow.rollback])
def test_apply_rejects_an_empty_actor_before_discovery_or_locking(
    db_session,
    monkeypatch,
    operation,
):
    monkeypatch.setattr(
        shadow,
        "analyze" if operation is shadow.prepare else "analyze_rollback",
        lambda *_args, **_kwargs: pytest.fail("discovery must not run"),
    )

    with pytest.raises(shadow.AndritzShadowError, match="non-empty actor"):
        operation(db_session, apply=True, actor="   ")


def test_prepare_revalidation_detects_subject_drift_after_discovery(
    db_session,
    monkeypatch,
):
    workspace, system, source_policy, historical, _flow = _seed_target(db_session)

    def _drift(db, *, targets):
        target_policy = targets[0]["policy"]
        extra = copy.deepcopy(target_policy.extra)
        extra["membrane_spec"]["valves"]["token_budget"] += 1
        target_policy.extra = extra
        db.add(target_policy)
        db.flush()

    monkeypatch.setattr(shadow, "_lock_exact_subjects", _drift)

    with pytest.raises(shadow.AndritzShadowError, match="concurrent_preflight_drift"):
        shadow.prepare(db_session, apply=True, actor="operator")
    db_session.rollback()

    assert system.control_policy_id == source_policy.id
    assert db_session.query(ControlPolicy).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).one().id == historical.id


def test_rollback_reports_a_malformed_prepared_generation_instead_of_crashing(
    db_session,
):
    workspace, system, _source_policy, _historical, _flow = _seed_target(db_session)
    prepared = shadow.prepare(db_session, apply=True, actor="operator")
    shadow.rollback(db_session, apply=True, actor="rollback")
    shadow_policy = db_session.query(ControlPolicy).filter_by(
        id=prepared["targets"][0]["policy_id"]
    ).one()
    extra = copy.deepcopy(shadow_policy.extra)
    extra[shadow.SHADOW_MARKER_KEY]["system_version_number"] = "not-an-integer"
    shadow_policy.extra = extra
    db_session.commit()

    report = shadow.rollback(db_session, apply=False, actor="operator")

    assert report["ready"] is False
    assert report["blockers"] == [
        {
            "code": "invalid_shadow_marker",
            "workspace_id": workspace.id,
            "system_id": system.id,
            "reason": "invalid prepared policy generation",
        }
    ]


@pytest.mark.parametrize(
    "report",
    [
        {"ready": False, "prerequisite": {"ready": True}},
        {"ready": True, "prerequisite": {"ready": False}},
    ],
)
def test_cli_returns_two_when_structure_or_showcase_prerequisite_is_blocked(
    monkeypatch,
    report,
):
    class _DB:
        def rollback(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(shadow, "SessionLocal", _DB)
    monkeypatch.setattr(shadow, "prepare", lambda *_args, **_kwargs: report)
    monkeypatch.setattr("sys.argv", ["prepare_andritz_membrane_shadow"])

    assert shadow.main() == 2
