from __future__ import annotations

import copy
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.iam.decision_plane import ActionResolution
from app.services.object_perspective import (
    OBJECT_LENSES,
    build_capability_perspective,
    build_run_perspective,
    build_skill_invocation_perspective,
    projection_feature_enabled,
)
from app.services.projection_gate import (
    PROJECTION_FINALIZATION_AUDIT_EVENT,
    projection_activation_audit_details,
    projection_activation_sha256,
    with_projection_activation,
)
from app.services.projection_integrity import invocation_cost_is_measured
from app.services.run_engine.engine import _snapshot_run_flow
from app.services.system_perspective import build_system_perspective

TEST_TRUSTED_RUNNER = {
    "issuer": "https://gitlab.example.test",
    "project_id": "42",
    "pipeline_id": "314",
    "job_id": "159",
    "commit_sha": "a" * 40,
    "ref": "demo/agentic",
    "ref_protected": True,
}


@pytest.fixture(autouse=True)
def _deployed_projection_revision(monkeypatch):
    monkeypatch.setattr(settings, "agentium_image_revision", "a" * 40)
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_oidc_issuer",
        TEST_TRUSTED_RUNNER["issuer"],
    )
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_project_id",
        TEST_TRUSTED_RUNNER["project_id"],
    )
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_ref",
        TEST_TRUSTED_RUNNER["ref"],
    )


def _projection_settings(*projections: str) -> dict:
    settings: dict = {"features": {}}
    for projection in projections:
        settings = with_projection_activation(
            settings,
            projection=projection,
            evidence_sha256="a" * 64,
            revision="a" * 40,
            system_id="system-lot7",
            capability_id="cap-lot7",
        )
    return settings


def _canary_settings(db_session, workspace_settings: dict, *, workspace_id: str) -> dict:
    rows = workspace_settings["_lot7_projection_gate_v1"]["activations"]
    activations = []
    for row in rows:
        pilot_audit_id = str(uuid4())
        activation = {
            **dict(row),
            "trusted_runner": dict(TEST_TRUSTED_RUNNER),
            "pilot_observation": {
                "audit_id": pilot_audit_id,
                "observation_ref": f"sha256:{'b' * 64}",
                "participant_ref": f"sha256:{'c' * 64}",
                "profile": "operator",
            },
            "activated_by": "lot7-test-runner",
            "activated_at": "2026-01-01T00:00:00+00:00",
            "probation_lease_id": str(uuid4()),
        }
        activation["activation_sha256"] = projection_activation_sha256(activation)
        audit_id = str(uuid4())
        db_session.add(
            AuditLog(
                id=audit_id,
                workspace_id=workspace_id,
                event_type=PROJECTION_FINALIZATION_AUDIT_EVENT,
                actor=activation["activated_by"],
                agent_id=row["system_id"],
                details=projection_activation_audit_details(activation),
            )
        )
        activation["audit_id"] = audit_id
        activations.append(activation)
    return {
        "experience": {"system_360_canary": "v1"},
        "_lot7_projection_rollout_v1": {
            "schema_version": 1,
            "activations": activations,
            "probations": [],
            "deactivations": [],
        },
    }


def _seed(db_session):
    workspace_settings = _projection_settings("capability", "run", "skill_invocation")
    workspace = Workspace(
        id="ws-lot7-perspective",
        slug="lot7-perspective",
        name="Lot 7",
        settings=workspace_settings,
    )
    user = User(
        id="user-lot7-perspective",
        username="lot7@test",
        email="lot7@test",
        role="admin",
    )
    member = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="admin",
        role_template="workspace_admin",
    )
    capability = Capability(
        id="cap-lot7",
        workspace_id=workspace.id,
        slug="lot7_contract_risk",
        name="Contract Risk",
        description="Find contractual risks with evidence.",
        skill_ids=["skill-lot7"],
        value_per_outcome=10.0,
        confidence_threshold=0.8,
        sla={"success_rate": 0.9},
        roi_model={"kind": "per_outcome"},
    )
    skill = Skill(
        id="skill-lot7",
        workspace_id=workspace.id,
        slug="claim_audit_lot7",
        name="Claim Audit",
        version="1",
        input_schema={"claim": {"type": "string"}},
        output_schema={"verdict": {"type": "string"}},
        execution={"mode": "sync", "idempotent": True},
        certification_level="production",
    )
    system = System(
        id="system-lot7",
        workspace_id=workspace.id,
        name="Contract Risk Copilot",
        objective="Audit one contract.",
        capability_id=capability.id,
        skill_ids=[skill.id],
        status="active",
        settings=_canary_settings(
            db_session,
            workspace_settings,
            workspace_id=workspace.id,
        ),
    )
    run = Run(
        id="run-lot7",
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        started_at=datetime.utcnow() - timedelta(minutes=2),
        completed_at=datetime.utcnow() - timedelta(minutes=1),
        duration_ms=800,
        decision="review",
        confidence=0.9,
        value_estimated=10.0,
        value_source="auto",
        cost_internal=2.0,
        efficiency=0.75,
        input_ref={
            "contract_id": "contract-1",
            "api_token": "secret",
            "Authorization": "Bearer authorization-secret",
            "authorization_endpoint": "https://identity.example.test/oauth/authorize",
            "database_url": "postgresql://projection:dsn-secret@db.example.test/app",
            "prompt": "Use Authorization: Bearer prompt-inline-secret for this call",
            "model_key": "sk-proj-abcdefghijklmnopqrstuvwxyz123456",
            "nested": {
                "credentials": {"password": "deep-secret"},
                "privateKey": "private-key-secret",
                "client_private_key": "client-private-key-secret",
                "proxyAuthorization": "proxy-authorization-secret",
                "authorizationHeader": "authorization-header-secret",
                "bearer": "bare-bearer-secret",
                "bearerToken": "bearer-token-secret",
                "dsn": "bare-dsn-secret",
                "sentryDsn": "dsn-key-secret",
                "Cookie": "cookie-secret",
                "cookies": "cookies-secret",
                "set-cookie": "set-cookie-secret",
                "sessionCookie": "session-cookie-secret",
                "cookieJar": "cookie-jar-secret",
                "safe": [
                    {"access_token": "list-secret"},
                    {"header_value": "Bearer inline-secret"},
                    "visible",
                ],
            },
        },
        output_ref={"verdict": "review"},
        flow_snapshot={
            "schema_version": 3,
            "io_mode": "strict",
            "nodes": [{"id": "audit"}],
            "edges": [],
        },
        checkpoints=[{"kind": "node_complete", "node_id": "audit", "secret": "hidden"}],
    )
    invocation = SkillInvocation(
        id="invocation-lot7",
        run_id=run.id,
        skill_id=skill.id,
        skill_slug=skill.slug,
        status="completed",
        started_at=run.started_at,
        completed_at=run.completed_at,
        latency_ms=500,
        cost=1.5,
        cost_measured=True,
        execution_snapshot={
            "schema_version": 1,
            "resolution": "resolved",
            "skill": {
                "id": skill.id,
                "slug": skill.slug,
                "scope": "workspace",
                "version": "1",
                "provider": "internal",
                "certification_level": "production",
            },
            "digests": {
                "input_contract_sha256": "a" * 64,
                "output_contract_sha256": "b" * 64,
                "execution_sha256": "c" * 64,
            },
        },
        input_ref={"claim": "Clause 7"},
        output_ref={"verdict": "review"},
        metrics={"quality": 0.95, "confidence": 0.9},
        trace={"provider": "internal", "password": "hidden"},
    )
    decision = Decision(
        id="decision-lot7",
        workspace_id=workspace.id,
        scope="run",
        target_id=run.id,
        kind="recommendation",
        status="proposed",
        title="Review Clause 7",
    )
    evaluation = EvaluationScore(
        id="evaluation-lot7",
        workspace_id=workspace.id,
        run_id=run.id,
        composite_score=92,
    )
    audit = AuditLog(
        id="audit-lot7",
        workspace_id=workspace.id,
        event_type="run.completed",
        actor=user.email,
        trace_id=run.id,
        details={"run_id": run.id, "secret": "hidden"},
    )
    db_session.add_all(
        [
            workspace,
            user,
            member,
            capability,
            skill,
            system,
            run,
            invocation,
            decision,
            evaluation,
            audit,
        ]
    )
    db_session.commit()
    return workspace, user, capability, run, invocation


def _fact(payload, facet, block_id, key):
    block = next(item for item in payload["facets"][facet]["blocks"] if item["id"] == block_id)
    return next(item for item in block["facts"] if item["key"] == key)


def _assert_four_distinct(payloads, facets):
    assert len({str(item["identity"]) for item in payloads.values()}) == 1
    assert len({str(item["header"]) for item in payloads.values()}) == 1
    assert len({item["snapshot_id"] for item in payloads.values()}) == 1
    assert all(tuple(item["facets"]) == facets for item in payloads.values())
    signatures = {
        lens: tuple(
            block["id"] for facet in payload["facets"].values() for block in facet["blocks"]
        )
        for lens, payload in payloads.items()
    }
    assert len(set(signatures.values())) == 4


def _decision_mode(
    db_session,
    *,
    workspace: Workspace,
    mode: str,
) -> WorkspaceIAMConfig:
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"decision.read": mode},
            }
        },
    )
    db_session.add(config)
    db_session.commit()
    return config


def _decision_titles(payload, *, system: bool = False) -> set[str]:
    fact = (
        _fact(payload, "overview", "recommendations", "decisions")
        if system
        else _fact(payload, "outcomes", "outcomes", "open_decisions")
    )
    return {str(item["title"]) for item in fact["value"] or []}


def test_capability_four_lenses_are_distinct_with_invariant_identity(db_session):
    workspace, user, capability, _run, _invocation = _seed(db_session)
    payloads = {
        lens: build_capability_perspective(
            db_session,
            workspace=workspace,
            user=user,
            capability=capability,
            lens=lens,
        )
        for lens in OBJECT_LENSES
    }
    _assert_four_distinct(payloads, ("overview", "systems", "outcomes", "policies"))
    assert _fact(payloads["build"], "overview", "promise", "description")["state"] == "available"
    assert _fact(payloads["operate"], "overview", "runtime-health", "p95_latency")["value"] == 800.0
    assert _fact(payloads["steer"], "overview", "value", "roi")[
        "value"
    ] == pytest.approx(566.6666667)
    actions = _fact(payloads["govern"], "overview", "authorization", "actions")["value"]
    assert actions["read"]["effective_allowed"] is True


def test_snapshot_fingerprints_data_exposed_by_other_lenses(db_session):
    workspace, user, capability, _run, _invocation = _seed(db_session)
    before = build_capability_perspective(
        db_session,
        workspace=workspace,
        user=user,
        capability=capability,
        lens="build",
    )
    decision = db_session.query(Decision).filter_by(id="decision-lot7").one()
    decision.title = "Changed steering recommendation"
    db_session.commit()
    after = build_capability_perspective(
        db_session,
        workspace=workspace,
        user=user,
        capability=capability,
        lens="build",
    )

    assert before["snapshot_id"] != after["snapshot_id"]


def test_capability_decisions_shadow_preserves_legacy_and_aggregates_evidence(
    db_session,
):
    workspace, user, capability, _run, _invocation = _seed(db_session)
    user.role = "member"
    membership = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one()
    membership.role = "member"
    membership.role_template = "workspace_contributor"
    system = db_session.query(System).filter_by(id="system-lot7").one()
    other = User(
        id="user-lot7-decision-other",
        username="lot7-decision-other@test",
        email="lot7-decision-other@test",
    )
    other_run = Run(
        id="run-lot7-decision-other",
        workspace_id=workspace.id,
        initiated_by_user_id=other.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        trigger="manual",
        started_at=datetime.utcnow() - timedelta(minutes=1),
    )
    non_owner = Decision(
        id="decision-lot7-non-owner",
        workspace_id=workspace.id,
        scope="run",
        target_id=other_run.id,
        status="proposed",
        title="Non-owner legacy decision",
    )
    ownerless = Decision(
        id="decision-lot7-ownerless",
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        status="proposed",
        title="Ownerless legacy decision",
    )
    db_session.add_all([other, other_run, non_owner, ownerless])
    _decision_mode(db_session, workspace=workspace, mode="shadow")

    payload = build_capability_perspective(
        db_session,
        workspace=workspace,
        user=user,
        capability=capability,
        lens="steer",
    )

    assert _decision_titles(payload) == {
        "Review Clause 7",
        "Non-owner legacy decision",
        "Ownerless legacy decision",
    }
    evidence = [
        item
        for item in db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="iam.shadow.evaluation",
        )
        .all()
        if item.details.get("action") == "decision.read"
    ]
    assert len(evidence) == 1
    assert evidence[0].details["summary"] is True
    assert evidence[0].details["evaluation_count"] == 3
    assert evidence[0].details["mismatches"] == 2


def test_capability_and_system_decisions_enforce_owner_scope_roles_and_tenant(
    db_session,
    attest_authorization_v2,
):
    workspace, contributor, capability, _run, _invocation = _seed(db_session)
    contributor.role = "member"
    contributor_membership = (
        db_session.query(WorkspaceMember).filter_by(user_id=contributor.id).one()
    )
    contributor_membership.role = "member"
    contributor_membership.role_template = "workspace_contributor"
    system = db_session.query(System).filter_by(id="system-lot7").one()
    other = User(
        id="user-lot7-decision-enforce-other",
        username="lot7-decision-enforce-other@test",
        email="lot7-decision-enforce-other@test",
    )
    reviewer = User(
        id="user-lot7-decision-reviewer",
        username="lot7-decision-reviewer@test",
        email="lot7-decision-reviewer@test",
    )
    admin = User(
        id="user-lot7-decision-admin",
        username="lot7-decision-admin@test",
        email="lot7-decision-admin@test",
    )
    other_run = Run(
        id="run-lot7-decision-enforce-other",
        workspace_id=workspace.id,
        initiated_by_user_id=other.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        trigger="manual",
        started_at=datetime.utcnow() - timedelta(minutes=1),
    )
    non_owner = Decision(
        id="decision-lot7-enforce-non-owner",
        workspace_id=workspace.id,
        scope="run",
        target_id=other_run.id,
        status="proposed",
        title="Enforce non-owner decision",
    )
    ownerless = Decision(
        id="decision-lot7-enforce-ownerless",
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        kind="policy_breach",
        status="proposed",
        title="Enforce ownerless decision",
        rationale={"facet": "inbound"},
    )
    foreign_workspace = Workspace(
        id="ws-lot7-decision-foreign",
        slug="lot7-decision-foreign",
        name="Foreign Decision Tenant",
        settings={},
    )
    foreign = Decision(
        id="decision-lot7-enforce-foreign",
        workspace_id=foreign_workspace.id,
        scope="system",
        target_id=system.id,
        status="proposed",
        title="FOREIGN DECISION SECRET",
    )
    db_session.add_all(
        [
            other,
            reviewer,
            admin,
            WorkspaceMember(
                user_id=reviewer.id,
                workspace_id=workspace.id,
                role="reviewer",
                role_template="workspace_reviewer",
            ),
            WorkspaceMember(
                user_id=admin.id,
                workspace_id=workspace.id,
                role="admin",
                role_template="workspace_admin",
            ),
            other_run,
            non_owner,
            ownerless,
            foreign_workspace,
            foreign,
        ]
    )
    policy = ControlPolicy(
        id="policy-lot7-decision-enforce",
        workspace_id=workspace.id,
        name="Decision projection membrane",
        scope="system",
        target_id=system.id,
        extra={
            "membrane_spec": {
                "version": 2,
                "enforcement_mode": "enforce",
                "inbound": {"collection_allowlist": ["contracts"]},
            }
        },
    )
    system.control_policy_id = policy.id
    db_session.add(policy)
    config = _decision_mode(db_session, workspace=workspace, mode="enforce")
    attest_authorization_v2(config, ["decision.read"])
    db_session.commit()

    expected_contributor = {"Review Clause 7"}
    expected_privileged = {
        "Review Clause 7",
        "Enforce non-owner decision",
        "Enforce ownerless decision",
    }
    for actor, expected in (
        (contributor, expected_contributor),
        (reviewer, expected_privileged),
        (admin, expected_privileged),
    ):
        capability_payload = build_capability_perspective(
            db_session,
            workspace=workspace,
            user=actor,
            capability=capability,
            lens="steer",
        )
        system_payload = build_system_perspective(
            db_session,
            workspace=workspace,
            user=actor,
            system=system,
            lens="steer",
        )
        capability_govern = build_capability_perspective(
            db_session,
            workspace=workspace,
            user=actor,
            capability=capability,
            lens="govern",
        )
        system_govern = build_system_perspective(
            db_session,
            workspace=workspace,
            user=actor,
            system=system,
            lens="govern",
        )
        assert _decision_titles(capability_payload) == expected
        assert _decision_titles(system_payload, system=True) == expected
        assert "FOREIGN DECISION SECRET" not in str(capability_payload)
        assert "FOREIGN DECISION SECRET" not in str(system_payload)
        governed_decisions = _fact(
            capability_govern,
            "outcomes",
            "decision-audit",
            "decisions",
        )
        if actor is contributor:
            assert governed_decisions["state"] == "restricted"
            assert governed_decisions["value"] is None
        else:
            assert {row["title"] for row in governed_decisions["value"]} == expected
        membrane_states = _fact(
            system_govern,
            "overview",
            "constraints",
            "membrane",
        )["value"]
        assert membrane_states["inbound"] == (
            "enforced" if actor is contributor else "breached"
        )
        assert "FOREIGN DECISION SECRET" not in str(capability_govern)
        assert "FOREIGN DECISION SECRET" not in str(system_govern)


def test_run_four_lenses_preserve_run_and_redact_sensitive_keys(db_session):
    workspace, user, _capability, run, _invocation = _seed(db_session)
    payloads = {
        lens: build_run_perspective(
            db_session,
            workspace=workspace,
            user=user,
            run=run,
            lens=lens,
        )
        for lens in OBJECT_LENSES
    }
    _assert_four_distinct(payloads, ("overview", "invocations", "payloads", "checkpoints"))
    input_fact = _fact(payloads["build"], "payloads", "typed-io", "input")
    assert input_fact["value"]["api_token"] == "[redacted]"
    assert input_fact["value"]["Authorization"] == "[redacted]"
    assert input_fact["value"]["authorization_endpoint"].endswith("/oauth/authorize")
    assert input_fact["value"]["database_url"] == "[redacted]"
    assert input_fact["value"]["prompt"] == "[redacted]"
    assert input_fact["value"]["model_key"] == "[redacted]"
    assert input_fact["value"]["nested"]["credentials"] == "[redacted]"
    assert input_fact["value"]["nested"]["privateKey"] == "[redacted]"
    assert input_fact["value"]["nested"]["client_private_key"] == "[redacted]"
    assert input_fact["value"]["nested"]["proxyAuthorization"] == "[redacted]"
    assert input_fact["value"]["nested"]["authorizationHeader"] == "[redacted]"
    assert input_fact["value"]["nested"]["bearer"] == "[redacted]"
    assert input_fact["value"]["nested"]["bearerToken"] == "[redacted]"
    assert input_fact["value"]["nested"]["dsn"] == "[redacted]"
    assert input_fact["value"]["nested"]["sentryDsn"] == "[redacted]"
    assert input_fact["value"]["nested"]["Cookie"] == "[redacted]"
    assert input_fact["value"]["nested"]["cookies"] == "[redacted]"
    assert input_fact["value"]["nested"]["set-cookie"] == "[redacted]"
    assert input_fact["value"]["nested"]["sessionCookie"] == "[redacted]"
    assert input_fact["value"]["nested"]["cookieJar"] == "[redacted]"
    assert input_fact["value"]["nested"]["safe"][0]["access_token"] == "[redacted]"
    assert input_fact["value"]["nested"]["safe"][1]["header_value"] == "[redacted]"
    assert "deep-secret" not in str(payloads)
    assert "list-secret" not in str(payloads)
    assert "private-key-secret" not in str(payloads)
    assert "inline-secret" not in str(payloads)
    assert "prompt-inline-secret" not in str(payloads)
    assert "sk-proj-" not in str(payloads)
    assert _fact(payloads["operate"], "overview", "runtime", "duration")["value"] == 800.0
    outcome = _fact(payloads["steer"], "overview", "outcome", "outcome")["value"]
    assert outcome["cost_internal"] == 1.5
    assert outcome["cost_internal_state"] == "available"
    assert _fact(payloads["steer"], "overview", "outcome", "roi")[
        "value"
    ] == pytest.approx(566.6666667)


def test_runtime_errors_are_summarized_without_provider_or_credential_payloads(db_session):
    workspace, user, _capability, run, invocation = _seed(db_session)
    run.error = (
        "provider rejected Bearer run-secret while opening "
        "postgresql://run-user:run-password@db.example.test/app"
    )
    invocation.error = (
        "-----BEGIN PRIVATE KEY----- invocation-secret -----END PRIVATE KEY----- "
        "prompt=confidential-customer-text"
    )
    db_session.commit()

    run_payload = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="operate",
    )
    invocation_payload = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="operate",
    )

    assert _fact(run_payload, "overview", "runtime", "error")["value"] == (
        "Runtime error recorded; details are restricted."
    )
    assert _fact(invocation_payload, "overview", "status", "error")["value"] == (
        "Runtime error recorded; details are restricted."
    )
    rendered = str({"run": run_payload, "invocation": invocation_payload})
    for secret in (
        "run-secret",
        "run-password",
        "PRIVATE KEY",
        "invocation-secret",
        "confidential-customer-text",
    ):
        assert secret not in rendered


def test_run_and_capability_costs_only_use_measured_invocations(db_session):
    workspace, user, capability, run, measured_invocation = _seed(db_session)
    run.cost_internal = 1000.5
    unmeasured_invocation = SkillInvocation(
        id="invocation-lot7-unmeasured",
        run_id=run.id,
        skill_slug="synthetic_cost",
        status="completed",
        cost=999.0,
        cost_measured=False,
    )
    db_session.add(unmeasured_invocation)
    db_session.commit()

    run_steer = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="steer",
    )
    outcome = _fact(run_steer, "overview", "outcome", "outcome")["value"]
    assert outcome["cost_internal"] == 1.5
    assert outcome["cost_internal_sample_count"] == 1
    assert _fact(run_steer, "overview", "outcome", "roi")["value"] == pytest.approx(
        566.6666667
    )
    cost_rows = _fact(run_steer, "invocations", "cost-contribution", "costs")
    assert cost_rows["sample_count"] == 1
    assert [row["cost"] for row in cost_rows["value"]] == [1.5, None]

    db_session.add(
        Run(
            id="run-lot7-value-without-cost",
            workspace_id=workspace.id,
            system_id=run.system_id,
            capability_id=capability.id,
            status="completed",
            started_at=datetime.utcnow() - timedelta(seconds=30),
            completed_at=datetime.utcnow(),
            value_estimated=100.0,
            value_source="unset",
            cost_internal=9999.0,
        )
    )
    db_session.commit()
    capability_steer = build_capability_perspective(
        db_session,
        workspace=workspace,
        user=user,
        capability=capability,
        lens="steer",
    )
    assert _fact(capability_steer, "overview", "value", "cost")["value"] == 1.5
    assert _fact(capability_steer, "overview", "value", "cost")["sample_count"] == 1
    measured_value = _fact(capability_steer, "overview", "value", "value")
    assert measured_value["value"] == 10.0
    assert measured_value["sample_count"] == 1
    assert _fact(capability_steer, "overview", "value", "roi")[
        "value"
    ] == pytest.approx(566.6666667)
    assert _fact(capability_steer, "overview", "value", "roi")["sample_count"] == 1
    system_rollup = _fact(
        capability_steer,
        "systems",
        "value-by-system",
        "systems",
    )["value"][0]
    assert system_rollup["run_count"] == 2
    assert system_rollup["cost_measured_run_count"] == 1
    assert system_rollup["cost_coverage_percent"] == 50.0
    assert system_rollup["value"] == 10.0
    assert system_rollup["value_run_count"] == 1
    assert system_rollup["roi_eligible_run_count"] == 1

    measured_invocation.cost_measured = False
    db_session.commit()
    unknown = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="steer",
    )
    unknown_outcome = _fact(unknown, "overview", "outcome", "outcome")["value"]
    assert unknown_outcome["cost_internal"] is None
    assert unknown_outcome["cost_internal_state"] == "not_measured"
    assert _fact(unknown, "overview", "outcome", "roi")["state"] == "not_measured"
    assert _fact(unknown, "invocations", "cost-contribution", "costs")[
        "state"
    ] == "not_measured"

    measured_invocation.cost = 0.0
    measured_invocation.cost_measured = True
    db_session.commit()
    measured_zero = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="steer",
    )
    zero_outcome = _fact(measured_zero, "overview", "outcome", "outcome")["value"]
    assert zero_outcome["cost_internal"] == 0.0
    assert zero_outcome["cost_internal_state"] == "available"
    assert _fact(measured_zero, "overview", "outcome", "roi")[
        "state"
    ] == "not_measured"


def test_run_build_uses_run_and_version_snapshots_not_mutable_catalog(db_session):
    workspace, user, capability, run, _invocation = _seed(db_session)
    system = db_session.query(System).filter_by(id=run.system_id).one()
    version = SystemVersion(
        id="version-lot7-run",
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=7,
        flow_definition=run.flow_snapshot,
        configuration_snapshot={
            "schema_version": 1,
            "bindings": {"control_policy_id": None},
        },
        created_at=run.started_at,
        created_by=user.email,
    )
    system.name = "Mutated current System"
    system.status = "retired"
    capability.name = "Mutated current Capability"
    capability.tier = "experimental"
    db_session.add(version)
    db_session.flush()
    _snapshot_run_flow(db_session, run, system, first_start=True)
    db_session.commit()

    assert run.flow_version_id == version.id

    payload = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="build",
    )

    evidence_block = next(
        block
        for block in payload["facets"]["overview"]["blocks"]
        if block["id"] == "execution-evidence"
    )
    assert evidence_block["title"] == "Execution evidence"
    assert "current catalog objects" in evidence_block["description"]
    assert _fact(payload, "overview", "execution-evidence", "system")["value"] == {
        "id": system.id
    }
    assert _fact(payload, "overview", "execution-evidence", "capability")[
        "value"
    ] == {"id": capability.id}
    assert _fact(payload, "overview", "execution-evidence", "flow_snapshot")[
        "value"
    ]["node_ids"] == ["audit"]
    configuration = _fact(
        payload,
        "overview",
        "execution-evidence",
        "configuration_snapshot",
    )["value"]
    assert configuration["system_version_id"] == version.id
    assert configuration["version_number"] == 7
    assert "Mutated current System" not in str(payload)
    assert "Mutated current Capability" not in str(payload)
    assert "Execution contract" not in str(payload)

    run.capability_id = None
    db_session.commit()
    without_historical_capability = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="build",
    )
    assert without_historical_capability["identity"]["capability_id"] is None
    assert _fact(
        without_historical_capability,
        "overview",
        "execution-evidence",
        "capability",
    )["state"] == "not_configured"

    run.flow_snapshot = None
    run.flow_version_id = None
    system.flow_definition = {"nodes": [{"id": "current-only-node"}], "edges": []}
    db_session.commit()
    without_snapshot = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="build",
    )
    assert _fact(
        without_snapshot,
        "overview",
        "execution-evidence",
        "flow_snapshot",
    )["state"] == "not_configured"
    assert "current-only-node" not in str(without_snapshot)


def test_run_provenance_requires_matching_typed_runtime_markers(db_session):
    workspace, user, _capability, run, invocation = _seed(db_session)
    sha256 = "a" * 64
    uri = "object://provenance/run-lot7.json"
    run.output_ref = {
        "business_artifact": {"uri": "object://untrusted.json", "sha256": "b" * 64}
    }
    run.checkpoints = [
        {
            "kind": "node_complete",
            "uri": "object://untrusted-checkpoint.json",
            "sha256": "c" * 64,
        }
    ]
    invocation.trace = {"membrane_provenance": {"uri": uri, "sha256": sha256}}
    db_session.commit()

    arbitrary = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="govern",
    )
    assert _fact(arbitrary, "payloads", "provenance", "artifacts")[
        "state"
    ] == "not_measured"

    run.output_ref = {
        "_membrane_provenance": {"uri": uri, "sha256": sha256, "size_bytes": 128}
    }
    run.checkpoints = [
        {
            "kind": "membrane_provenance",
            "uri": uri,
            "sha256": "d" * 64,
        }
    ]
    db_session.commit()
    mismatch = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="govern",
    )
    assert _fact(mismatch, "payloads", "provenance", "artifacts")[
        "state"
    ] == "not_measured"

    run.checkpoints = [
        {"kind": "membrane_provenance", "uri": uri, "sha256": sha256}
    ]
    db_session.commit()
    corroborated = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="govern",
    )
    artifacts = _fact(corroborated, "payloads", "provenance", "artifacts")
    assert artifacts["state"] == "available"
    assert artifacts["sample_count"] == 1
    assert artifacts["value"] == [
        {
            "uri": uri,
            "sha256": sha256,
            "verification": "runtime_markers_agree",
            "evidence_sources": [
                "runs.output_ref._membrane_provenance",
                "runs.checkpoints[kind=membrane_provenance]",
                "skill_invocations.trace.membrane_provenance",
            ],
            "size_bytes": 128,
        }
    ]

    run.output_ref = {
        "_membrane_provenance": {"uri": "https://example.test/proof", "sha256": sha256}
    }
    run.checkpoints = [
        {
            "kind": "membrane_provenance",
            "uri": "https://example.test/proof",
            "sha256": sha256,
        }
    ]
    invocation.trace = {
        "membrane_provenance": {
            "uri": "https://example.test/proof",
            "sha256": sha256,
        }
    }
    db_session.commit()
    malformed = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="govern",
    )
    assert _fact(malformed, "payloads", "provenance", "artifacts")[
        "state"
    ] == "not_measured"

    uppercase_sha = "A" * 64
    run.output_ref = {
        "_membrane_provenance": {"uri": uri, "sha256": uppercase_sha}
    }
    run.checkpoints = [
        {"kind": "membrane_provenance", "uri": uri, "sha256": uppercase_sha}
    ]
    invocation.trace = {
        "membrane_provenance": {"uri": uri, "sha256": uppercase_sha}
    }
    db_session.commit()
    malformed_digest = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="govern",
    )
    assert _fact(malformed_digest, "payloads", "provenance", "artifacts")[
        "state"
    ] == "not_measured"


def test_skill_invocation_is_a_distinct_runtime_object(db_session):
    workspace, user, _capability, run, invocation = _seed(db_session)
    payloads = {
        lens: build_skill_invocation_perspective(
            db_session,
            workspace=workspace,
            user=user,
            run=run,
            invocation=invocation,
            lens=lens,
        )
        for lens in OBJECT_LENSES
    }
    _assert_four_distinct(payloads, ("overview", "io", "runtime", "governance"))
    identity = payloads["build"]["identity"]
    assert identity["skill_invocation_id"] == invocation.id
    assert identity["skill_id"] == "skill-lot7"
    assert identity["skill_version"] == "1"
    assert identity["execution_digests"]["execution_sha256"] == "c" * 64
    assert identity["object_type"] == "skill_invocation"
    assert _fact(payloads["operate"], "overview", "status", "latency")["value"] == 500.0
    assert _fact(payloads["steer"], "overview", "contribution", "value")["state"] == "not_measured"
    actions = _fact(payloads["govern"], "overview", "authorization", "actions")["value"]
    assert set(actions) == {"read"}


def test_invocation_projection_never_rebinds_history_to_mutable_skill(db_session):
    workspace, user, _capability, run, invocation = _seed(db_session)
    skill = db_session.query(Skill).filter_by(id=invocation.skill_id).one()
    skill.version = "99"
    skill.provider = "mutated-provider"
    skill.certification_level = "experimental"
    db_session.commit()

    payload = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="build",
    )

    assert payload["identity"]["skill_version"] == "1"
    assert payload["identity"]["skill_provider"] == "internal"
    assert "mutated-provider" not in str(payload)
    assert _fact(payload, "governance", "certification", "version")["value"] == "1"


def test_historical_invocation_snapshot_and_default_zero_cost_remain_unmeasured(db_session):
    workspace, user, _capability, run, invocation = _seed(db_session)
    invocation.execution_snapshot = None
    invocation.cost = 0.0
    invocation.cost_measured = None
    db_session.commit()

    payload = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="operate",
    )
    assert payload["identity"]["execution_snapshot_state"] == "not_measured"
    assert payload["header"]["skill_version"]["state"] == "not_measured"
    assert _fact(payload, "overview", "status", "cost")["state"] == "not_measured"

    invocation.cost_measured = True
    db_session.commit()
    measured = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="operate",
    )
    assert _fact(measured, "overview", "status", "cost")["state"] == "available"
    assert _fact(measured, "overview", "status", "cost")["value"] == 0.0


@pytest.mark.parametrize("invalid_cost", [-0.01, float("inf"), float("nan")])
def test_invalid_cost_can_never_be_presented_as_measured(
    db_session,
    invalid_cost: float,
):
    _workspace, _user, _capability, _run, invocation = _seed(db_session)
    invocation.cost_measured = True
    invocation.cost = invalid_cost

    assert invocation_cost_is_measured(invocation) is False


def test_historical_invocation_never_exposes_unscoped_mutable_skill_reference(
    db_session,
):
    workspace, user, _capability, run, invocation = _seed(db_session)
    foreign_workspace = Workspace(
        id="ws-lot7-foreign-skill",
        slug="lot7-foreign-skill",
        name="Foreign Skill workspace",
    )
    foreign_skill = Skill(
        id="skill-lot7-foreign-secret",
        workspace_id=foreign_workspace.id,
        slug="foreign_secret_skill_slug",
        name="Foreign Skill secret name",
        version="1",
    )
    db_session.add_all([foreign_workspace, foreign_skill])
    invocation.execution_snapshot = None
    invocation.skill_id = foreign_skill.id
    invocation.skill_slug = foreign_skill.slug
    db_session.commit()

    invocation_payload = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="build",
    )
    run_payload = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="build",
    )

    assert invocation_payload["identity"]["skill_id"] is None
    assert invocation_payload["identity"]["skill_slug"] is None
    assert invocation_payload["identity"]["execution_snapshot_state"] == "not_measured"
    rendered = str({"invocation": invocation_payload, "run": run_payload})
    for forbidden in (foreign_skill.id, foreign_skill.slug, foreign_skill.name):
        assert forbidden not in rendered


def test_owner_payload_authority_window_and_canonical_invocation_provenance(db_session):
    workspace, user, _capability, run, invocation = _seed(db_session)
    user.role = None
    membership = (
        db_session.query(WorkspaceMember)
        .filter_by(
            workspace_id=workspace.id,
            user_id=user.id,
        )
        .one()
    )
    membership.role = "member"
    membership.role_template = "workspace_contributor"
    invocation.trace = {
        "membrane_provenance": {
            "uri": "object://provenance/run-lot7.json",
            "sha256": "a" * 64,
            "size_bytes": 128,
        }
    }
    old_decision = Decision(
        id="decision-lot7-old",
        workspace_id=workspace.id,
        scope="run",
        target_id=run.id,
        kind="recommendation",
        status="proposed",
        title="Expired recommendation",
        created_at=datetime.utcnow() - timedelta(days=100),
    )
    old_audit = AuditLog(
        id="audit-lot7-old",
        workspace_id=workspace.id,
        event_type="run.old",
        actor="old@test",
        trace_id=run.id,
        timestamp=datetime.utcnow() - timedelta(days=100),
    )
    db_session.add_all([old_decision, old_audit])
    db_session.commit()

    build = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="build",
        window="7d",
    )
    assert _fact(build, "payloads", "typed-io", "input")["state"] == "available"
    govern = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="govern",
        window="7d",
    )
    assert "Expired recommendation" not in str(govern)
    assert "run.old" not in str(govern)

    invocation_govern = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="govern",
        window="7d",
    )
    provenance = _fact(
        invocation_govern,
        "governance",
        "audit",
        "provenance",
    )
    assert provenance["value"]["uri"] == "object://provenance/run-lot7.json"
    assert provenance["value"]["sha256"] == "a" * 64


def test_govern_projection_does_not_mint_shadow_evidence_for_display_only_actions(
    db_session,
):
    workspace, user, _capability, run, _invocation = _seed(db_session)
    db_session.add(
        WorkspaceIAMConfig(
            workspace_id=workspace.id,
            version=1,
            role_flags={},
            capability_overrides={
                "authorization_v2": {
                    "policy_version": 2,
                    "default_mode": "compat",
                    "modes": {
                        "system.read": "shadow",
                        "capability.read": "shadow",
                        "run.read": "shadow",
                        "run.approve": "shadow",
                        "run.admin": "shadow",
                    },
                }
            },
        )
    )
    db_session.commit()

    payload = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="govern",
    )

    actions = _fact(payload, "overview", "authorization", "actions")["value"]
    assert set(actions) == {"read", "approve", "admin"}
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="iam.shadow.evaluation",
        )
        .count()
        == 0
    )


def test_projection_flags_require_attested_gate_and_remain_per_object_type(db_session):
    workspace, _user, _capability, run, _invocation = _seed(db_session)
    assert projection_feature_enabled(db_session, workspace, "capability") is True
    assert projection_feature_enabled(db_session, workspace, "run") is True
    assert projection_feature_enabled(db_session, workspace, "skill_invocation") is True
    workspace.settings = {"features": {"capability_360_projection_v1": True}}
    assert projection_feature_enabled(db_session, workspace, "capability") is False
    workspace.settings = _projection_settings("capability")
    system = db_session.query(System).filter_by(id=run.system_id).one()
    system.settings = _canary_settings(
        db_session,
        workspace.settings,
        workspace_id=workspace.id,
    )
    db_session.flush()
    assert projection_feature_enabled(db_session, workspace, "capability") is True
    assert projection_feature_enabled(db_session, workspace, "run") is False
    assert projection_feature_enabled(db_session, workspace, "skill_invocation") is False
    drifted = copy.deepcopy(workspace.settings)
    drifted["_lot7_projection_gate_v1"]["activations"][0]["evidence_sha256"] = "f" * 64
    workspace.settings = drifted
    assert projection_feature_enabled(db_session, workspace, "capability") is False


def test_parent_objects_are_filtered_by_their_independent_read_action(
    db_session,
    monkeypatch,
):
    workspace, user, capability, run, invocation = _seed(db_session)

    def _resolve(*_args, resource_kind, action, **_kwargs):
        allowed = resource_kind != "system"
        return ActionResolution(
            resource_kind=resource_kind,
            action=action,
            mode="enforce",
            effective_allowed=allowed,
            legacy_allowed=True,
            candidate_allowed=allowed,
            mismatch=not allowed,
            reason="candidate_allowed" if allowed else "role_denied",
            policy_id=f"test:{resource_kind}.{action}",
        )

    monkeypatch.setattr("app.services.system_access.resolve_action", _resolve)

    capability_payload = build_capability_perspective(
        db_session,
        workspace=workspace,
        user=user,
        capability=capability,
        lens="build",
    )
    systems_fact = _fact(
        capability_payload,
        "systems",
        "implementations",
        "systems",
    )
    assert systems_fact["state"] == "not_configured"
    assert "Contract Risk Copilot" not in str(capability_payload)

    run_payload = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="build",
    )
    system_fact = _fact(
        run_payload,
        "overview",
        "execution-evidence",
        "system",
    )
    assert system_fact["state"] == "not_configured"
    assert "Contract Risk Copilot" not in str(run_payload)
    assert run_payload["identity"]["system_id"] is None
    assert (
        _fact(
            run_payload,
            "overview",
            "execution-evidence",
            "capability",
        )["state"]
        == "available"
    )

    invocation_payload = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="operate",
    )
    assert invocation_payload["identity"]["system_id"] is None
    lineage_system = _fact(
        invocation_payload,
        "governance",
        "lineage",
        "system",
    )
    assert lineage_system["state"] == "restricted"
    assert lineage_system["value"] is None


def test_corrupt_cross_workspace_parent_references_never_enter_projection(db_session):
    workspace, user, _capability, run, invocation = _seed(db_session)
    foreign_workspace = Workspace(
        id="ws-lot7-foreign-parent",
        slug="lot7-foreign-parent",
        name="Foreign parent workspace",
    )
    foreign_capability = Capability(
        id="cap-lot7-foreign-parent",
        workspace_id=foreign_workspace.id,
        slug="lot7_foreign_parent",
        name="Foreign capability secret name",
    )
    foreign_system = System(
        id="system-lot7-foreign-parent",
        workspace_id=foreign_workspace.id,
        name="Foreign system secret name",
        objective="Must never cross the projection boundary.",
        capability_id=foreign_capability.id,
        status="active",
    )
    db_session.add_all([foreign_workspace, foreign_capability, foreign_system])
    run.system_id = foreign_system.id
    run.capability_id = foreign_capability.id
    db_session.commit()

    run_payload = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="govern",
    )
    invocation_payload = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="operate",
    )

    assert run_payload["identity"]["system_id"] is None
    assert run_payload["identity"]["capability_id"] is None
    assert invocation_payload["identity"]["system_id"] is None
    assert invocation_payload["identity"]["capability_id"] is None
    rendered = str({"run": run_payload, "invocation": invocation_payload})
    for forbidden in (
        foreign_system.id,
        foreign_capability.id,
        foreign_system.name,
        foreign_capability.name,
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("tier", "industry", "hidden_explicitly"),
    [
        ("industry", "government", False),
        ("universal", None, True),
    ],
    ids=("different-industry-family", "explicitly-hidden-global"),
)
def test_global_parent_capability_uses_exact_workspace_catalog_visibility(
    db_session,
    tier,
    industry,
    hidden_explicitly,
):
    workspace, user, _capability, run, invocation = _seed(db_session)
    global_capability = Capability(
        id=f"cap-lot7-global-{tier}",
        workspace_id=None,
        slug=f"lot7_global_{tier}",
        name="Hidden global capability name",
        tier=tier,
        industry=industry,
    )
    catalog = (
        {"hidden_capabilities": [global_capability.slug]}
        if hidden_explicitly
        else {}
    )
    workspace.settings = {
        **dict(workspace.settings or {}),
        "family": "andritz",
        "catalog": catalog,
    }
    run.capability_id = global_capability.id
    db_session.add(global_capability)
    db_session.commit()

    run_payload = build_run_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        lens="build",
    )
    invocation_payload = build_skill_invocation_perspective(
        db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens="govern",
    )

    assert run_payload["identity"]["capability_id"] is None
    assert invocation_payload["identity"]["capability_id"] is None
    capability_fact = _fact(
        run_payload,
        "overview",
        "execution-evidence",
        "capability",
    )
    assert capability_fact["state"] == "restricted"
    assert capability_fact["value"] is None
    rendered = str({"run": run_payload, "invocation": invocation_payload})
    assert global_capability.id not in rendered
    assert global_capability.name not in rendered
