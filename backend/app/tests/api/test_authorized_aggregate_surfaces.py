"""Indirect aggregates must never reintroduce denied runtime objects."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import impact, skills
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember


def _seed(db, attest_authorization_v2):
    workspace = Workspace(
        id="workspace-authorized-aggregates",
        slug="authorized-aggregates",
        name="Authorized aggregates",
    )
    user = User(id="aggregate-owner", username="aggregate-owner")
    other = User(id="aggregate-other", username="aggregate-other")
    skill = Skill(
        id="skill-authorized-aggregate",
        slug="authorized_aggregate_v1",
        name="Authorized aggregate",
    )
    capability = Capability(
        id="capability-authorized-aggregate",
        workspace_id=workspace.id,
        slug="authorized_aggregate",
        name="Authorized aggregate",
        skill_ids=[skill.id],
    )
    system = System(
        id="system-authorized-aggregate",
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Authorized aggregate",
        status="active",
    )
    now = datetime.utcnow()
    own_run = Run(
        id="run-authorized-aggregate-own",
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        trigger="manual",
        started_at=now - timedelta(minutes=2),
        completed_at=now - timedelta(minutes=1),
        cost_internal=1.0,
        value_estimated=4.0,
        value_source="auto",
    )
    hidden_run = Run(
        id="run-authorized-aggregate-hidden",
        workspace_id=workspace.id,
        initiated_by_user_id=other.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        trigger="manual",
        started_at=now - timedelta(minutes=2),
        completed_at=now - timedelta(minutes=1),
        cost_internal=999.0,
        value_estimated=4_999.0,
        value_source="auto",
    )
    invocations = [
        SkillInvocation(
            id="invocation-authorized-aggregate-own",
            run_id=own_run.id,
            skill_id=skill.id,
            skill_slug=skill.slug,
            status="completed",
            latency_ms=10.0,
            cost=0.25,
            cost_measured=True,
        ),
        SkillInvocation(
            id="invocation-authorized-aggregate-unmeasured",
            run_id=own_run.id,
            skill_id=skill.id,
            skill_slug=skill.slug,
            status="completed",
            latency_ms=20.0,
            cost=777.0,
            cost_measured=False,
        ),
        SkillInvocation(
            id="invocation-authorized-aggregate-hidden",
            run_id=hidden_run.id,
            skill_id=skill.id,
            skill_slug=skill.slug,
            status="completed",
            latency_ms=9_999.0,
            cost=1_000.0,
            cost_measured=True,
        ),
    ]
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template="workspace_contributor",
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {
                    "capability.read": "enforce",
                    "system.read": "enforce",
                    "run.read": "enforce",
                    "skill_invocation.read": "enforce",
                },
            }
        },
    )
    db.add_all(
        [
            workspace,
            user,
            other,
            member,
            skill,
            capability,
            system,
            own_run,
            hidden_run,
            *invocations,
            config,
        ]
    )
    db.flush()
    attest_authorization_v2(
        config,
        [
            "capability.read",
            "system.read",
            "run.read",
            "skill_invocation.read",
        ],
    )
    db.commit()
    return workspace, user, capability, system, skill


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(impact.router, prefix="/impact")
    app.include_router(skills.router, prefix="/skills")
    for module in (impact, skills):
        app.dependency_overrides[module.get_current_workspace] = lambda: workspace
        app.dependency_overrides[module.get_current_user] = lambda: user
        app.dependency_overrides[module.get_db] = lambda: db
    return TestClient(app)


def test_impact_aggregates_only_runs_allowed_to_the_subject(
    db_session,
    attest_authorization_v2,
):
    workspace, user, capability, system, _skill = _seed(
        db_session,
        attest_authorization_v2,
    )
    client = _client(db_session, workspace, user)

    portfolio = client.get("/impact/portfolio", params={"period": "rolling_30d"})
    by_capability = client.get(
        "/impact/by-capability",
        params={"period": "rolling_30d"},
    )
    by_system = client.get("/impact/by-system", params={"period": "rolling_30d"})

    assert portfolio.status_code == by_capability.status_code == by_system.status_code == 200
    assert portfolio.json()["runs_count"] == 1
    assert portfolio.json()["total_cost"] == 1.0
    assert by_capability.json()["items"] == [
        {
            **by_capability.json()["items"][0],
            "capability_id": capability.id,
            "runs_count": 1,
            "total_cost": 1.0,
        }
    ]
    assert by_system.json()["items"][0]["system_id"] == system.id
    assert by_system.json()["items"][0]["runs_count"] == 1
    assert by_system.json()["items"][0]["total_cost"] == 1.0
    assert "999" not in portfolio.text


def test_skill_catalog_runtime_metrics_compose_run_and_invocation_read(
    db_session,
    attest_authorization_v2,
):
    workspace, user, _capability, _system, skill = _seed(
        db_session,
        attest_authorization_v2,
    )
    response = _client(db_session, workspace, user).get("/skills")

    assert response.status_code == 200
    row = next(item for item in response.json()["skills"] if item["slug"] == skill.slug)
    assert row["metrics"] == {
        "calls": 2,
        "avg_latency_ms": 15.0,
        "total_cost": 0.25,
        "cost_state": "available",
        "cost_sample_count": 1,
        "success_rate": 1.0,
    }
    assert "9999" not in response.text
    assert "1000" not in response.text
    assert "777" not in response.text
