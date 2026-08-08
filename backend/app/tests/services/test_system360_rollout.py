"""State-machine tests for the structural, append-only Lot 6 rollout CLI."""

from __future__ import annotations

import copy
from datetime import datetime
from uuid import uuid4

import pytest

from app.db.base import SessionLocal
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.context import Context
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.tests.publication_baseline import LEGACY_FLOW_AUTHORITY
from scripts import rollout_system360_canary as rollout


def _membrane() -> dict:
    return {
        "version": 2,
        "enforcement_mode": "enforce",
        "inbound": {
            "collection_allowlist": ["evidence"],
            "reference_type_filters": [],
            "reject_cross_project_sources": True,
            "preserve_reference_types": True,
        },
        "outbound": {
            "expert_review_required": False,
            "gate_if_confidence_below": 0.65,
        },
        "capabilities": {
            "allowed_skills": list(rollout.REQUIRED_SKILLS),
            "allowed_models": ["test-model"],
            "allowed_delegations": [],
            "allowed_actions": ["system.engine.run"],
        },
        "provenance": {
            "require_citations": True,
            "object_store_prefix": "system-360/test",
        },
        "valves": {
            "max_cost_per_decision": 5,
            "max_latency_ms": 10_000,
            "hard_abort": True,
            "token_budget": 12_000,
            "circuit_breaker": {"failure_threshold": 3, "max_attempts": 5},
        },
    }


def _seed_target(db):
    workspace = Workspace(
        id=str(uuid4()),
        name="Structural showcase",
        slug=f"structural-{uuid4()}",
        settings={
            "showcase_seed": True,
            # The Lot 6 rollout writes the legacy mirror and refuses to run
            # while publication owns Flow state.
            "features": {
                **LEGACY_FLOW_AUTHORITY["features"],
                **{key: True for key in rollout.ROLLOUT_FEATURES},
            },
        },
    )
    capability = Capability(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=f"opaque-{uuid4()}",
        name="Structural capability",
    )
    original_flow = {
        "schema_version": 3,
        "io_mode": "overlay",
        "nodes": [],
        "edges": [],
    }
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Opaque system identity",
        objective="Test append-only rollout",
        capability_id=capability.id,
        flow_definition=original_flow,
        settings={
            "preexisting": True,
            "showcase_seed": True,
            "system_type": "contract",
        },
        status="active",
    )
    skills = [
        Skill(
            id=str(uuid4()),
            workspace_id=None,
            slug=slug,
            name=f"Required skill {index}",
        )
        for index, slug in enumerate(rollout.REQUIRED_SKILLS)
    ]
    context = Context(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        name="Opaque linked context",
        environment_state={"industry": "test", "region": "EU"},
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Structural membrane",
        scope="system",
        target_id=system.id,
        extra={"membrane_spec": _membrane()},
    )
    system.control_policy_id = policy.id
    historical_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        completed_at=datetime.utcnow(),
        trigger="preexisting",
    )
    db.add_all([workspace, capability, *skills, context, policy, system, historical_run])
    db.commit()
    return workspace, system, policy, historical_run, original_flow


def test_legacy_rollout_apply_is_blocked_by_flow_publication(db_session) -> None:
    workspace, system, _, _, original_flow = _seed_target(db_session)
    settings = copy.deepcopy(workspace.settings)
    settings.setdefault("features", {})["flow_publication_v1"] = True
    workspace.settings = settings
    db_session.commit()

    with pytest.raises(rollout.RolloutError, match="legacy rollout writes are disabled"):
        rollout.bootstrap(
            db_session,
            apply=True,
            actor="system:lot6-system360-rollout",
        )

    db_session.rollback()
    db_session.refresh(system)
    assert system.flow_definition == original_flow
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 0


def test_rollout_is_ordered_idempotent_append_only_and_reversible(db_session, monkeypatch):
    workspace, system, policy, historical_run, original_flow = _seed_target(db_session)

    bootstrap_preview = rollout.bootstrap(db_session, apply=False, actor="test")
    assert bootstrap_preview["mode"] == "dry_run"
    assert bootstrap_preview["changed"] is True
    assert "context.environment_state.audit_event_type" in bootstrap_preview["changed_fields"]
    assert rollout._experience(system).get("system_360_canary") is None
    preview_context = db_session.query(Context).filter_by(system_id=system.id).one()
    assert preview_context.environment_state == {"industry": "test", "region": "EU"}

    bootstrapped = rollout.bootstrap(db_session, apply=True, actor="test")
    assert bootstrapped["changed"] is True
    db_session.refresh(workspace)
    db_session.refresh(system)
    db_session.refresh(policy)
    assert rollout._experience(system).get("system_360_canary") == rollout.CANARY_MARKER
    assert system.context_id is not None
    context = db_session.query(Context).filter_by(id=system.context_id).one()
    assert context.environment_state == {
        "industry": "test",
        "region": "EU",
        "audit_event_type": "system.contract_risk.claims_audited",
    }
    assert (
        "context.environment_state.audit_event_type"
        in bootstrapped["changed_fields"]
    )
    required_skill_ids = {
        row.id
        for row in db_session.query(Skill)
        .filter(Skill.slug.in_(rollout.REQUIRED_SKILLS))
        .all()
    }
    capability = db_session.query(Capability).filter_by(id=system.capability_id).one()
    assert required_skill_ids.issubset(set(system.skill_ids))
    assert required_skill_ids.issubset(set(capability.skill_ids))
    assert all(not rollout._feature(workspace, key) for key in rollout.ROLLOUT_FEATURES)
    assert rollout._membrane_mode(policy) == "shadow"
    assert rollout.bootstrap(db_session, apply=True, actor="test")["changed"] is False

    preview = rollout.prepare(db_session, apply=False, actor="test")
    assert preview["mode"] == "dry_run"
    assert preview["changed"] is True
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 0

    prepared = rollout.prepare(db_session, apply=True, actor="test")
    assert prepared["phase"] == "prepared"
    db_session.refresh(workspace)
    db_session.refresh(system)
    db_session.refresh(policy)
    assert system.flow_definition == rollout.canonical_strict_flow()
    assert all(not rollout._feature(workspace, key) for key in rollout.ROLLOUT_FEATURES)
    assert rollout._membrane_mode(policy) == "shadow"
    assert db_session.query(Run).filter_by(id=historical_run.id).one().status == "completed"
    versions = (
        db_session.query(SystemVersion)
        .filter_by(system_id=system.id)
        .order_by(SystemVersion.version_number)
        .all()
    )
    assert [row.flow_definition for row in versions] == [
        original_flow,
        rollout.canonical_strict_flow(),
    ]

    version_count = len(versions)
    repeated = rollout.prepare(db_session, apply=True, actor="test")
    assert repeated["changed"] is False
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == version_count

    rollout.activate_flow(db_session, apply=True, actor="test")
    with pytest.raises(rollout.RolloutError, match="requires phase exercised"):
        rollout.activate_membrane(db_session, apply=True, actor="test")

    async def fake_real_dag(run_id: str):
        with SessionLocal() as worker_db:
            run = worker_db.query(Run).filter(Run.id == run_id).one()
            provenance = {
                "uri": "object://system-360/test/provenance.json",
                "key": "system-360/test/provenance.json",
                "sha256": "a" * 64,
                "size_bytes": 512,
                "created_at": datetime.utcnow().isoformat(),
            }
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.flow_snapshot = rollout.canonical_strict_flow()
            run.output_ref = {
                "id": str(uuid4()),
                "status": "recorded",
                "_membrane_provenance": provenance,
            }
            run.checkpoints = [
                {
                    "kind": "membrane_egress_evaluated",
                    "citation_count": 1,
                },
                {
                    "kind": "membrane_provenance",
                    "uri": provenance["uri"],
                    "sha256": provenance["sha256"],
                    "size_bytes": provenance["size_bytes"],
                },
            ]
            for node_id, skill_slug in zip(
                rollout.REQUIRED_NODE_IDS,
                rollout.REQUIRED_SKILLS,
                strict=True,
            ):
                output_ref = {}
                trace = {"node_id": node_id}
                if skill_slug == "llm_rag_answer_v1":
                    output_ref = {
                        "answer": "A grounded contract-risk answer.",
                        "citations": [{"source_id": "evidence-1"}],
                    }
                if skill_slug == "audit_log_v1":
                    trace["membrane_provenance"] = provenance
                worker_db.add(
                    SkillInvocation(
                        id=str(uuid4()),
                        run_id=run.id,
                        skill_slug=skill_slug,
                        status="completed",
                        completed_at=datetime.utcnow(),
                        output_ref=output_ref,
                        trace=trace,
                    )
                )
            worker_db.commit()
        return {"id": run_id, "status": "completed"}

    from app.services.run_engine import dag

    monkeypatch.setattr(dag, "execute_run_dag", fake_real_dag)
    exercise = rollout.exercise(
        db_session,
        apply=True,
        actor="test",
        query="Evaluate the available contract evidence",
    )
    assert exercise["exercise"]["required_skills_observed"] is True

    exercise_run_id = exercise["exercise"]["run_id"]
    first_invocation = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == exercise_run_id)
        .order_by(SkillInvocation.started_at, SkillInvocation.id)
        .first()
    )
    assert first_invocation is not None
    original_trace = dict(first_invocation.trace or {})
    first_invocation.trace = {**original_trace, "node_id": "unexpected-node"}
    db_session.commit()
    state = rollout._rollout_state(system)
    assert rollout._exercise_proof(db_session, state, system)["required_skills_observed"] is False
    first_invocation.trace = original_trace
    db_session.commit()

    answer_invocation = (
        db_session.query(SkillInvocation)
        .filter(
            SkillInvocation.run_id == exercise_run_id,
            SkillInvocation.skill_slug == "llm_rag_answer_v1",
        )
        .one()
    )
    original_answer_output = dict(answer_invocation.output_ref or {})
    answer_invocation.output_ref = {**original_answer_output, "citations": []}
    db_session.commit()
    missing_citations = rollout._exercise_proof(db_session, state, system)
    assert missing_citations["grounded_output_verified"] is False
    assert missing_citations["required_skills_observed"] is False
    answer_invocation.output_ref = original_answer_output
    db_session.commit()

    exercise_run = db_session.query(Run).filter(Run.id == exercise_run_id).one()
    original_output = dict(exercise_run.output_ref or {})
    invalid_provenance = dict(original_output["_membrane_provenance"])
    invalid_provenance["sha256"] = "not-a-sha256"
    exercise_run.output_ref = {
        **original_output,
        "_membrane_provenance": invalid_provenance,
    }
    db_session.commit()
    malformed_provenance = rollout._exercise_proof(db_session, state, system)
    assert malformed_provenance["canonical_provenance_verified"] is False
    assert malformed_provenance["required_skills_observed"] is False
    exercise_run.output_ref = original_output
    db_session.commit()

    rollout.activate_membrane(db_session, apply=True, actor="test")
    rollout.activate_axes(db_session, apply=True, actor="test")
    rollout.activate_projection(db_session, apply=True, actor="test")
    ready = rollout.status(db_session)
    assert ready["ready"] is True
    assert ready["marker_count"] == 1

    # A protected deployment job may be retried after it already succeeded.
    # Replaying the entire command sequence must validate the later phase then
    # no-op: no new Run/version/audit, no feature rollback and no state rewrite.
    before_replay = {
        "workspace_settings": copy.deepcopy(workspace.settings),
        "system_settings": copy.deepcopy(system.settings),
        "flow": copy.deepcopy(system.flow_definition),
        "policy_extra": copy.deepcopy(policy.extra),
        "versions": db_session.query(SystemVersion).filter_by(system_id=system.id).count(),
        "runs": db_session.query(Run).filter_by(system_id=system.id).count(),
        "invocations": (
            db_session.query(SkillInvocation)
            .join(Run, Run.id == SkillInvocation.run_id)
            .filter(Run.system_id == system.id)
            .count()
        ),
        "audits": db_session.query(AuditLog).filter_by(workspace_id=workspace.id).count(),
    }
    replayed = [
        rollout.bootstrap(db_session, apply=True, actor="retry"),
        rollout.prepare(db_session, apply=True, actor="retry"),
        rollout.activate_flow(db_session, apply=True, actor="retry"),
        rollout.exercise(db_session, apply=True, actor="retry", query=None),
        rollout.activate_membrane(db_session, apply=True, actor="retry"),
        rollout.activate_axes(db_session, apply=True, actor="retry"),
        rollout.activate_projection(db_session, apply=True, actor="retry"),
    ]
    assert all(item["changed"] is False for item in replayed)
    assert all(item["phase"] == "projection_active" for item in replayed)
    db_session.refresh(workspace)
    db_session.refresh(system)
    db_session.refresh(policy)
    assert workspace.settings == before_replay["workspace_settings"]
    assert system.settings == before_replay["system_settings"]
    assert system.flow_definition == before_replay["flow"]
    assert policy.extra == before_replay["policy_extra"]
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == before_replay["versions"]
    assert db_session.query(Run).filter_by(system_id=system.id).count() == before_replay["runs"]
    assert (
        db_session.query(SkillInvocation)
        .join(Run, Run.id == SkillInvocation.run_id)
        .filter(Run.system_id == system.id)
        .count()
        == before_replay["invocations"]
    )
    assert db_session.query(AuditLog).filter_by(workspace_id=workspace.id).count() == before_replay["audits"]
    assert rollout.status(db_session)["ready"] is True

    before_rollback_versions = db_session.query(SystemVersion).filter_by(system_id=system.id).count()
    rolled_back = rollout.rollback(db_session, apply=True, actor="test")
    assert rolled_back["ordered_actions"] == [
        "projection_off",
        "axes_off",
        "membrane_shadow",
        "strict_flow_off",
        "previous_flow_version",
    ]
    db_session.refresh(workspace)
    db_session.refresh(system)
    db_session.refresh(policy)
    assert system.flow_definition == original_flow
    assert all(not rollout._feature(workspace, key) for key in rollout.ROLLOUT_FEATURES)
    assert rollout._membrane_mode(policy) == "shadow"
    assert rollout._experience(system).get("system_360_canary") == rollout.CANARY_MARKER
    assert db_session.query(Run).filter_by(id=historical_run.id).count() == 1
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == before_rollback_versions + 1
    assert rollout.rollback(db_session, apply=True, actor="test")["changed"] is False


@pytest.mark.parametrize(
    ("drift", "message"),
    (
        ("marker", "exactly one System 360 marker"),
        ("flow", "canonical strict flow"),
        ("feature", "feature contract diverged"),
        ("membrane", "requires MembraneSpec mode shadow"),
        ("context", "lost its Context audit event binding"),
    ),
)
def test_prepare_revalidates_existing_phase_contract(db_session, drift, message):
    workspace, system, policy, _, original_flow = _seed_target(db_session)
    rollout.bootstrap(db_session, apply=True, actor="test")
    rollout.prepare(db_session, apply=True, actor="test")

    if drift == "marker":
        rollout._set_marker(system, None, present=False)
    elif drift == "flow":
        system.flow_definition = original_flow
    elif drift == "feature":
        rollout._set_feature(workspace, rollout.FEATURE_FLOW, True)
    elif drift == "membrane":
        rollout._set_membrane_mode(policy, rollout.EnforcementMode.ENFORCE)
    elif drift == "context":
        context = db_session.query(Context).filter_by(id=system.context_id).one()
        context.environment_state = {"industry": "test", "region": "EU"}
    db_session.commit()

    with pytest.raises(rollout.RolloutError, match=message):
        rollout.prepare(db_session, apply=True, actor="retry")


def test_discovery_fails_closed_when_showcase_workspace_is_not_unique(db_session):
    _seed_target(db_session)
    db_session.add(
        Workspace(
            id=str(uuid4()),
            name="Second showcase",
            slug=f"second-{uuid4()}",
            settings={"showcase_seed": True},
        )
    )
    db_session.commit()
    with pytest.raises(rollout.RolloutError, match="exactly one active showcase_seed workspace"):
        rollout.discover_target(db_session)


def test_marker_discovery_fails_closed_when_marker_is_absent(db_session):
    _seed_target(db_session)

    with pytest.raises(rollout.RolloutError, match="exactly one System 360 marker"):
        rollout.discover_target(db_session)


def test_marker_discovery_fails_closed_when_marker_is_duplicated(db_session):
    workspace, system, _, _, _ = _seed_target(db_session)
    rollout.bootstrap(db_session, apply=True, actor="test")
    duplicate = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Another opaque system",
        objective="Duplicate marker must fail closed",
        capability_id=system.capability_id,
        settings={"experience": {"system_360_canary": rollout.CANARY_MARKER}},
        status="active",
    )
    db_session.add(duplicate)
    db_session.commit()

    with pytest.raises(rollout.RolloutError, match="exactly one System 360 marker"):
        rollout.discover_target(db_session)
    with pytest.raises(rollout.RolloutError, match="at most one System 360 marker"):
        rollout.bootstrap(db_session, apply=False, actor="test")


def test_bootstrap_creates_policy_and_is_idempotent(db_session):
    workspace, system, policy, historical_run, _ = _seed_target(db_session)
    system.control_policy_id = None
    db_session.delete(policy)
    db_session.commit()

    audit_query = db_session.query(AuditLog).filter_by(
        workspace_id=workspace.id,
        event_type="system360.bootstrap.applied",
    )
    preview = rollout.bootstrap(db_session, apply=False, actor="bootstrap-test")
    assert preview["changed"] is True
    assert preview["policy_created"] is True
    assert audit_query.count() == 0
    assert system.control_policy_id is None

    applied = rollout.bootstrap(db_session, apply=True, actor="bootstrap-test")
    assert applied["changed"] is True
    assert applied["policy_created"] is True
    db_session.refresh(workspace)
    db_session.refresh(system)
    created_policy = db_session.query(ControlPolicy).filter_by(
        id=system.control_policy_id
    ).one()
    membrane = rollout.MembraneSpec.from_dict(
        created_policy.extra["membrane_spec"],
        authoritative=True,
    )
    assert membrane.effective_mode.value == "shadow"
    assert set(membrane.configured_facets()) == set(rollout.FACET_NAMES)
    assert created_policy.scope == "system"
    assert created_policy.target_id == system.id
    assert rollout._experience(system).get("system_360_canary") == rollout.CANARY_MARKER
    assert all(not rollout._feature(workspace, key) for key in rollout.ROLLOUT_FEATURES)
    assert db_session.query(Run).filter_by(id=historical_run.id).count() == 1

    audit = audit_query.one()
    assert set(audit.details) == {"changed_fields"}
    assert audit.details["changed_fields"] == applied["changed_fields"]
    audit_count = audit_query.count()
    repeated = rollout.bootstrap(db_session, apply=True, actor="bootstrap-test")
    assert repeated["changed"] is False
    assert repeated["changed_fields"] == []
    assert audit_query.count() == audit_count


def test_bootstrap_preserves_explicit_context_audit_event_type(db_session):
    _, system, _, _, _ = _seed_target(db_session)
    context = db_session.query(Context).filter_by(system_id=system.id).one()
    context.environment_state = {
        "industry": "test",
        "audit_event_type": "system.custom.audit",
    }
    db_session.commit()

    applied = rollout.bootstrap(db_session, apply=True, actor="test")

    db_session.refresh(context)
    assert context.environment_state["audit_event_type"] == "system.custom.audit"
    assert "context.environment_state.audit_event_type" not in applied["changed_fields"]
