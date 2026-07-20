from __future__ import annotations

from datetime import datetime, timedelta

from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.system_perspective import OBJECT_LENSES, build_system_perspective


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
        sla={"latency_ms": 5000, "success_rate": 0.95},
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
                "cost_multiplier": 0.9,
                "value_multiplier": 1.1,
                "confidence": 0.7,
                "assumptions": ["same evidence mix"],
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
            output_ref={"answer": "ok"},
        )
        invocation = SkillInvocation(
            id="invocation-contract",
            run_id=run.id,
            skill_id="skill-search",
            skill_slug="semantic_search_v1",
            status="completed",
            latency_ms=300,
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
    assert _fact(payloads["steer"], "overview", "outcomes", "roi")["value"] == 300.0
    simulation = _fact(payloads["steer"], "design", "simulation", "preview")["value"]
    assert simulation["measured"] is False
    assert simulation["provenance"]["scope"] == "system"
    assert simulation["provenance"]["system_id"] == system.id
    assert _fact(payloads["govern"], "design", "versions", "history")["state"] == "available"
    assert _fact(payloads["govern"], "design", "change-history", "sensitive_values")["state"] == "restricted"


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


def test_govern_redacts_audit_and_versions_for_non_privileged_member(db_session):
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
    assert history["state"] == "restricted"
    assert history["value"] is None
    assert events["state"] == "restricted"
    assert events["value"] is None
