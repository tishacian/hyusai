from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import settings as app_settings
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.value_loop import ValueLoopOperation, ValueScenario, ValueSimulation
from app.models.workspace import Workspace, WorkspaceMember
from app.services.control_policy_snapshot import control_policy_execution_contract
from app.services.system_perspective import OBJECT_LENSES, build_system_perspective
from app.services.value_loop_gate import value_loop_policy_chain_reference


def _seed(db_session, *, with_runtime: bool = True):
    workspace = Workspace(
        id="ws-system360",
        slug="agentium-showcase",
        name="Showcase",
        settings={"features": {"cockpit_router_axes_v4": True, "system_360_projection_v1": True}},
    )
    user = User(id="user-system360", username="system360@test", email="system360@test")
    member = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="admin",
        role_template="workspace_admin",
    )
    capability = Capability(
        id="cap-contract",
        workspace_id=workspace.id,
        slug="video_contract_risk",
        name="Contract Risk",
        sla={
            "latency_ms": 5000,
            "success_rate": 0.95,
            "Authorization": "Bearer system-sla-secret",
            "nested": {"privateKey": "system-private-key"},
        },
    )
    skills = [
        Skill(id="skill-search", slug="semantic_search_v1", name="Search", workspace_id=None),
        Skill(id="skill-answer", slug="llm_rag_answer_v1", name="Answer", workspace_id=None),
    ]
    system = System(
        id="system-contract",
        workspace_id=workspace.id,
        name="Contract Risk Copilot",
        objective="Review a contract against governed evidence.",
        capability_id=capability.id,
        skill_ids=[skill.id for skill in skills],
        status="active",
        settings={
            "experience": {"system_360_canary": "v1"},
            "steering_model": {
                "version": "contract-risk-v1",
                "confidence": 0.7,
                "assumptions": ["same evidence mix"],
                "forecasts": {
                    "mandatory_hitl_if_confidence_below": [
                        {
                            "minimum": 0,
                            "maximum": 1,
                            "include_maximum": True,
                            "cost_multiplier": 0.9,
                            "value_multiplier": 1.1,
                        }
                    ]
                },
            },
        },
        flow_definition={
            "schema_version": 3,
            "io_mode": "strict",
            "variable_namespaces": ["context"],
            "nodes": [
                {"id": "retrieve", "kind": "task", "skill_ref": "semantic_search_v1"},
                {"id": "answer", "kind": "task", "skill_ref": "llm_rag_answer_v1"},
            ],
            "edges": [{"from": "retrieve", "to": "answer"}],
        },
    )
    version = SystemVersion(
        id="version-contract",
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=1,
        flow_definition=system.flow_definition,
        created_by=user.email,
        message="System 360 canary",
    )
    db_session.add_all([workspace, user, member, capability, *skills, system, version])
    if with_runtime:
        run = Run(
            id="run-contract",
            workspace_id=workspace.id,
            system_id=system.id,
            capability_id=capability.id,
            status="completed",
            started_at=datetime.utcnow() - timedelta(minutes=2),
            completed_at=datetime.utcnow() - timedelta(minutes=1),
            duration_ms=1200,
            confidence=0.9,
            efficiency=0.8,
            cost_internal=2.0,
            value_estimated=8.0,
            value_source="auto",
            output_ref={"answer": "ok"},
        )
        invocation = SkillInvocation(
            id="invocation-contract",
            run_id=run.id,
            skill_id="skill-search",
            skill_slug="semantic_search_v1",
            status="completed",
            latency_ms=300,
            cost=2.0,
            cost_measured=True,
        )
        decision = Decision(
            id="decision-contract",
            workspace_id=workspace.id,
            scope="system",
            target_id=system.id,
            title="Reduce review latency",
            status="proposed",
        )
        audit = AuditLog(
            id="audit-contract",
            workspace_id=workspace.id,
            event_type="system.updated",
            actor=user.email,
            agent_id=system.id,
            details={"system_id": system.id, "fields": ["flow_definition"]},
        )
        db_session.add_all([run, invocation, decision, audit])
    db_session.commit()
    return workspace, user, system


def _fact(payload: dict, facet: str, block_id: str, key: str) -> dict:
    block = next(item for item in payload["facets"][facet]["blocks"] if item["id"] == block_id)
    return next(item for item in block["facts"] if item["key"] == key)


def test_four_lenses_keep_identity_header_and_facets_but_change_projection(db_session):
    workspace, user, system = _seed(db_session)
    payloads = {
        lens: build_system_perspective(
            db_session,
            workspace=workspace,
            user=user,
            system=system,
            lens=lens,
            window="30d",
        )
        for lens in OBJECT_LENSES
    }

    identities = {str(payload["identity"]) for payload in payloads.values()}
    headers = {str(payload["header"]) for payload in payloads.values()}
    snapshots = {payload["snapshot_id"] for payload in payloads.values()}
    assert len(identities) == 1
    assert len(headers) == 1
    assert len(snapshots) == 1
    assert all(tuple(payload["facets"]) == ("overview", "runs", "design", "context") for payload in payloads.values())

    block_signatures = {
        lens: tuple(
            block["id"]
            for facet in payload["facets"].values()
            for block in facet["blocks"]
        )
        for lens, payload in payloads.items()
    }
    assert len(set(block_signatures.values())) == 4
    assert _fact(payloads["build"], "design", "flow", "io_mode")["value"] == "strict"
    assert _fact(payloads["operate"], "runs", "runs", "p50_latency")["value"] == 1200.0
    sla = _fact(payloads["operate"], "overview", "sla", "target")["value"]
    assert sla["Authorization"] == "[redacted]"
    assert sla["nested"]["privateKey"] == "[redacted]"
    assert "system-sla-secret" not in str(payloads)
    assert "system-private-key" not in str(payloads)
    assert _fact(payloads["steer"], "overview", "outcomes", "roi")["value"] == 300.0
    simulation = _fact(payloads["steer"], "design", "simulation", "preview")
    assert simulation["state"] == "not_configured"
    assert simulation["value"] is None
    assert _fact(payloads["govern"], "design", "versions", "history")["state"] == "available"
    assert _fact(payloads["govern"], "design", "change-history", "sensitive_values")["state"] == "restricted"


def test_system_snapshot_fingerprints_steering_and_governance_rows(db_session):
    workspace, user, system = _seed(db_session)
    before = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="build",
    )
    decision = db_session.query(Decision).filter_by(id="decision-contract").one()
    decision.title = "Changed steering decision"
    db_session.commit()
    after = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="build",
    )

    assert before["snapshot_id"] != after["snapshot_id"]


def test_steer_projects_persisted_value_loop_only_behind_unique_marker(
    db_session,
    monkeypatch,
):
    workspace, user, system = _seed(db_session)
    baseline = db_session.query(Run).filter_by(id="run-contract").one()
    revision = "a" * 40
    monkeypatch.setattr(app_settings, "agentium_image_revision", revision)

    gate_off = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="steer",
    )
    assert "value-loop" not in {
        block["id"] for block in gate_off["facets"]["overview"]["blocks"]
    }

    workspace.settings = {
        **workspace.settings,
        "features": {**workspace.settings["features"], "value_loop_v1": True},
    }
    system.settings = {
        **system.settings,
        "experience": {
            **system.settings["experience"],
            "value_loop_canary": "v1",
        },
        "_lot8_value_loop_rollout_v1": {
            "schema_version": 1,
            "prepared": None,
            "activations": [
                {
                    "system_id": system.id,
                    "revision": revision,
                    "activated_at": datetime.now(UTC).isoformat(),
                    "evidence_ref": "sha256:" + "c" * 64,
                    "artifact_ref": "sha256:" + "d" * 64,
                }
            ],
            "deactivations": [],
            "policy_transitions": [],
        },
        "value_loop": {
            "actuators": {
                "control_policy.guardrails.patch.v1": {
                    "enabled": True,
                    "fields": {
                        "max_cost_per_decision": {"min": 0, "max": 50},
                        "max_latency_ms": {"min": 100, "max": 30_000},
                        "mandatory_hitl_if_confidence_below": {"min": 0, "max": 1},
                    },
                }
            }
        },
    }
    policy = ControlPolicy(
        id="value-loop-policy",
        workspace_id=workspace.id,
        name="Value loop policy",
        scope="system",
        target_id=system.id,
        mandatory_hitl_if_confidence_below=0.4,
        extra={
            "membrane_spec": {
                "version": 2,
                "enforcement_mode": "enforce",
                "capabilities": {
                    "allowed_actions": ["control_policy.guardrails.patch.v1"]
                },
            }
        },
    )
    system.control_policy_id = policy.id
    rollout_state = system.settings["_lot8_value_loop_rollout_v1"]
    activation = rollout_state["activations"][0]
    policy_reference = control_policy_execution_contract(policy)
    chain_created_at = activation["activated_at"]
    activation.update(
        {
            "policy_chain_ref": value_loop_policy_chain_reference(
                system_id=system.id,
                revision=revision,
                created_at=chain_created_at,
                control_policy=policy_reference,
            ),
            "policy_chain_created_at": chain_created_at,
            "control_policy": policy_reference,
        }
    )
    create_operation = ValueLoopOperation(
        id="value-operation-create",
        workspace_id=workspace.id,
        idempotency_key="value-create",
        request_sha256="a" * 64,
        operation="scenario.create",
        result_type="value_scenario",
        result_id="value-scenario",
    )
    simulate_operation = ValueLoopOperation(
        id="value-operation-simulate",
        workspace_id=workspace.id,
        idempotency_key="value-simulate",
        request_sha256="b" * 64,
        operation="simulate",
        result_type="value_simulation",
        result_id="value-simulation",
    )
    scenario = ValueScenario(
        id="value-scenario",
        workspace_id=workspace.id,
        system_id=system.id,
        source_run_id=baseline.id,
        operation_id=create_operation.id,
        status="simulated",
        objective="Improve measured outcome",
        baseline_outcome={"value": 8.0, "value_source": "auto"},
    )
    decision = Decision(
        id="value-decision",
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        scope="system",
        target_id=system.id,
        kind="value_loop",
        status="proposed",
        title="Governed value decision",
    )
    simulation = ValueSimulation(
        id="value-simulation",
        workspace_id=workspace.id,
        system_id=system.id,
        scenario_id=scenario.id,
        operation_id=simulate_operation.id,
        status="available",
        model="system-steering:contract-risk-v1",
        assumptions={"configured": ["same evidence mix"]},
        projected_outcome={"value": 8.8, "evidence_type": "simulation"},
        recommended_action={
            "actuator": "control_policy.guardrails.patch.v1",
            "patch": {"mandatory_hitl_if_confidence_below": 0.6},
        },
        provenance={"scope": "system", "system_id": system.id},
        confidence=0.7,
    )
    db_session.add_all(
        [policy, create_operation, simulate_operation, scenario, decision, simulation]
    )
    db_session.commit()

    steer = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="steer",
    )
    lifecycle = _fact(steer, "overview", "value-loop", "lifecycle")
    scenarios = _fact(steer, "overview", "value-loop", "scenarios")
    actuator = _fact(steer, "design", "value-actuator", "actuator")
    preview = _fact(steer, "design", "simulation", "preview")

    assert lifecycle["value"] == "simulated"
    assert scenarios["sample_count"] == 1
    assert scenarios["value"][0]["simulation"]["evidence_type"] == "simulation"
    assert scenarios["value"][0]["simulation"]["provenance"]["system_id"] == system.id
    assert actuator["value"] == "control_policy.guardrails.patch.v1"
    assert preview["state"] == "available"
    assert preview["value"]["measured"] is False
    assert preview["value"]["projected_outcome"]["value"] == 8.8
    assert preview["value"]["provenance"]["system_id"] == system.id

    drifted_settings = dict(system.settings)
    drifted_settings["value_loop"] = {"actuators": {}}
    system.settings = drifted_settings
    db_session.commit()
    drifted = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="steer",
    )
    drifted_lifecycle = _fact(
        drifted,
        "overview",
        "value-loop",
        "lifecycle",
    )
    drifted_actuator = _fact(
        drifted,
        "design",
        "value-actuator",
        "actuator",
    )
    assert drifted_lifecycle["value"] == "simulated"
    assert drifted_actuator["state"] == "not_configured"
    assert drifted_actuator["value"] is None


def test_system_cost_and_roi_ignore_unmeasured_run_aggregate(db_session):
    workspace, user, system = _seed(db_session)
    run = db_session.query(Run).filter_by(id="run-contract").one()
    run.cost_internal = 1001.0
    db_session.add(
        SkillInvocation(
            id="invocation-contract-unmeasured",
            run_id=run.id,
            skill_slug="synthetic_cost",
            status="completed",
            cost=999.0,
            cost_measured=False,
        )
    )
    db_session.add(
        Run(
            id="run-contract-value-without-cost",
            workspace_id=workspace.id,
            system_id=system.id,
            capability_id=run.capability_id,
            status="completed",
            started_at=datetime.utcnow() - timedelta(seconds=30),
            completed_at=datetime.utcnow(),
            value_estimated=100.0,
            value_source="unset",
            cost_internal=9999.0,
        )
    )
    db_session.commit()

    operate = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="operate",
    )
    steer = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="steer",
    )

    measured_cost = _fact(operate, "runs", "runs", "cost")
    assert measured_cost["value"] == 2.0
    assert measured_cost["sample_count"] == 1
    assert _fact(steer, "overview", "outcomes", "cost")["value"] == 2.0
    measured_value = _fact(steer, "overview", "outcomes", "value")
    assert measured_value["value"] == 8.0
    assert measured_value["sample_count"] == 1
    assert _fact(steer, "overview", "outcomes", "roi")["value"] == 300.0
    assert _fact(steer, "overview", "outcomes", "roi")["sample_count"] == 1
    simulation = _fact(steer, "design", "simulation", "preview")
    assert simulation["state"] == "not_configured"
    assert simulation["sample_count"] is None


def test_system_provenance_uses_only_corroborated_runtime_markers(db_session):
    workspace, user, system = _seed(db_session)
    run = db_session.query(Run).filter_by(id="run-contract").one()
    invocation = (
        db_session.query(SkillInvocation)
        .filter_by(id="invocation-contract")
        .one()
    )
    uri = "object://provenance/system-run.json"
    sha256 = "a" * 64
    run.output_ref = {"result": {"uri": uri, "sha256": sha256}}
    run.checkpoints = [{"kind": "node_complete", "uri": uri, "sha256": sha256}]
    invocation.trace = {"membrane_provenance": {"uri": uri, "sha256": sha256}}
    db_session.commit()

    untrusted = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="govern",
    )
    assert _fact(untrusted, "context", "provenance", "artifacts")[
        "state"
    ] == "not_measured"

    run.output_ref = {"_membrane_provenance": {"uri": uri, "sha256": sha256}}
    run.checkpoints = [
        {"kind": "membrane_provenance", "uri": uri, "sha256": sha256}
    ]
    db_session.commit()
    corroborated = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="govern",
    )
    artifacts = _fact(corroborated, "context", "provenance", "artifacts")
    assert artifacts["state"] == "available"
    assert artifacts["sample_count"] == 1
    assert artifacts["value"][0]["run_id"] == run.id
    assert artifacts["value"][0]["verification"] == "runtime_markers_agree"


def test_missing_runtime_is_explicit_and_never_fabricated_as_zero(db_session):
    workspace, user, system = _seed(db_session, with_runtime=False)
    payload = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="operate",
    )

    run_count = payload["header"]["run_count"]
    latency = _fact(payload, "runs", "runs", "p50_latency")
    assert run_count["state"] == "not_measured"
    assert run_count["value"] is None
    assert latency["state"] == "not_measured"
    assert latency["value"] is None


def test_showcase_seed_fixtures_are_not_reported_as_system_measurements(db_session):
    workspace, user, system = _seed(db_session, with_runtime=False)
    seeded = Run(
        id="synthetic-showcase-run",
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=datetime.utcnow() - timedelta(minutes=2),
        completed_at=datetime.utcnow() - timedelta(minutes=1),
        duration_ms=1,
        cost_internal=999.0,
        value_estimated=9999.0,
        input_ref={"query": "fixture"},
    )
    invocation = SkillInvocation(
        id="synthetic-showcase-invocation",
        run_id=seeded.id,
        skill_slug="semantic_search_v1",
        status="completed",
        metrics={"showcase_seed": True},
    )
    db_session.add_all([seeded, invocation])
    db_session.commit()

    operate = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="operate",
    )
    steer = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="steer",
    )

    assert operate["header"]["run_count"]["state"] == "not_measured"
    assert operate["header"]["run_count"]["value"] is None
    assert _fact(steer, "overview", "outcomes", "value")["state"] == "not_measured"
    assert _fact(steer, "overview", "outcomes", "value")["value"] is None


def test_govern_uses_resolved_legacy_admin_and_canonical_audit_read(db_session):
    workspace, user, system = _seed(db_session)
    member = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one()
    member.role = "member"
    member.role_template = "workspace_viewer"
    db_session.commit()

    payload = build_system_perspective(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        lens="govern",
    )
    history = _fact(payload, "design", "versions", "history")
    events = _fact(payload, "runs", "execution-audit", "events")
    # Ordinary System mutations historically had no additional role gate;
    # Govern reports that resolver result in compat instead of inventing one.
    assert history["state"] == "available"
    assert history["value"]
    assert events["state"] == "restricted"
    assert events["value"] is None
