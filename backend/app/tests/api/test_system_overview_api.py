"""Canonical System Overview contract: scoped facts and honest empty states."""

from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems
from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import system_overview


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session):
    workspace = Workspace(id="ws-overview", slug="overview", name="Overview", settings={})
    other = Workspace(id="ws-overview-other", slug="overview-other", name="Other", settings={})
    user = User(
        id="user-overview",
        username="overview@test",
        email="overview@test",
        role="admin",
    )
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="owner",
        role_template="workspace_owner",
    )
    system = System(
        id="system-overview",
        workspace_id=workspace.id,
        name="Decision assistant",
        objective="Answer from governed evidence.",
        status="active",
    )
    foreign = System(
        id="system-overview-foreign",
        workspace_id=other.id,
        name="Foreign",
        status="active",
    )
    db_session.add_all([workspace, other, user, membership, system, foreign])
    db_session.commit()
    return workspace, other, user, system, foreign


def test_overview_is_available_without_legacy_system_360_canary(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)

    response = _client(db_session, workspace, user).get(f"/systems/{system.id}/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["system"] == {
        "id": system.id,
        "name": "Decision assistant",
        "objective": "Answer from governed evidence.",
        "status": "active",
    }
    assert payload["readiness"]["state"] == "needs_setup"
    assert payload["readiness"]["can_run"] is False
    assert payload["readiness"]["blockers"][0]["code"] == "flow_not_published"
    assert payload["runs"]["total"] == 0
    assert payload["runs"]["success_rate"] is None
    assert payload["runs"]["avg_latency_ms"] is None
    assert payload["quality"] == {
        "state": "not_measured",
        "score": None,
        "hallucination_rate": None,
        "measured_at": None,
        "sample_count": 0,
    }


def test_overview_uses_only_system_scoped_runs_and_measurements(db_session, monkeypatch):
    workspace, _other, user, system, _foreign = _seed(db_session)
    version = SystemVersion(
        id="published-overview",
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=3,
        flow_definition={"nodes": [], "edges": []},
        flow_sha256="a" * 64,
        release_kind="publish",
        execution_contract={"ingresses": []},
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    system.published_at = datetime(2026, 9, 14, 12, 0, 0)
    completed = Run(
        id="run-overview-completed",
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        duration_ms=120,
        started_at=datetime.utcnow(),
    )
    failed = Run(
        id="run-overview-failed",
        workspace_id=workspace.id,
        system_id=system.id,
        status="failed",
        duration_ms=50,
        started_at=datetime.utcnow(),
    )
    unrelated = Run(
        id="run-overview-unrelated",
        workspace_id=workspace.id,
        system_id=None,
        status="completed",
        duration_ms=999,
        started_at=datetime.utcnow(),
    )
    evaluation = EvaluationScore(
        id="evaluation-overview",
        workspace_id=workspace.id,
        run_id=completed.id,
        agent_id=system.id,
        composite_score=88.0,
        hallucination_rate=0.04,
        created_at=datetime.utcnow(),
    )
    db_session.add_all([completed, failed, unrelated, evaluation])
    db_session.commit()
    monkeypatch.setattr(
        system_overview.flow_ingress,
        "assert_dispatchable",
        lambda *_args, **_kwargs: {
            "published_flow_version_id": version.id,
            "flow_sha256": "a" * 64,
        },
    )

    payload = (
        _client(db_session, workspace, user)
        .get(
            f"/systems/{system.id}/overview",
            params={"window": "7d"},
        )
        .json()
    )

    assert payload["readiness"]["state"] == "ready"
    assert payload["publication"]["version_number"] == 3
    assert payload["runs"]["total"] == 2
    assert payload["runs"]["completed"] == 1
    assert payload["runs"]["failed"] == 1
    assert payload["runs"]["success_rate"] == 50.0
    assert payload["runs"]["avg_latency_ms"] == 120.0
    assert payload["quality"]["state"] == "available"
    assert payload["quality"]["score"] == 88.0


def test_overview_fails_closed_across_workspaces(db_session):
    workspace, _other, user, _system, foreign = _seed(db_session)

    response = _client(db_session, workspace, user).get(f"/systems/{foreign.id}/overview")

    assert response.status_code == 404


def test_overview_validates_window(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)

    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/overview",
        params={"window": "365d"},
    )

    assert response.status_code == 422
