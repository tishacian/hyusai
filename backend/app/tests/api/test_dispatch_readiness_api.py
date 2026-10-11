"""Estate view an operator opens after a partial contract backfill."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems
from app.models.run_schedule import RunSchedule
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.tests.publication_baseline import baseline_flow_publication


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def _flow() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.cron", "kind": "source", "type": "source.schedule"},
            {"id": "snk", "kind": "sink"},
        ],
        "edges": [{"from": "src.cron", "to": "snk", "kind": "control"}],
    }


def _seed(db_session) -> tuple[Workspace, User, System, System]:
    workspace = Workspace(
        id=str(uuid.uuid4()),
        slug=f"readiness-api-{uuid.uuid4().hex[:6]}",
        name="Readiness API",
    )
    identity = f"readiness-{uuid.uuid4().hex[:8]}@test"
    user = User(
        id=str(uuid.uuid4()),
        username=identity,
        email=identity,
        role="admin",
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    db_session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    db_session.commit()

    made: list[System] = []
    for name, published in (("A repaired", True), ("B unrepaired", False)):
        system = System(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            name=name,
            objective="dispatch",
            status="active",
            flow_definition=_flow(),
        )
        db_session.add(system)
        db_session.commit()
        if published:
            baseline_flow_publication(db_session, system)
        db_session.add(
            RunSchedule(
                id=str(uuid.uuid4()),
                workspace_id=workspace.id,
                system_id=system.id,
                name=f"{name} cron",
                cron_expr="0 8 * * 1",
                timezone="UTC",
                enabled=True,
                next_fire_at=datetime.utcnow() + timedelta(days=1),
            )
        )
        db_session.commit()
        made.append(system)
    return workspace, user, made[0], made[1]


def test_readiness_names_the_systems_a_partial_backfill_left_inert(db_session):
    workspace, user, repaired, unrepaired = _seed(db_session)

    response = _client(db_session, workspace, user).get("/systems/dispatch-readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"dispatching_systems": 2, "ready": 1, "blocked": 1}
    by_id = {item["system_id"]: item for item in body["systems"]}
    assert by_id[repaired.id]["ready"] is True
    inert = by_id[unrepaired.id]
    assert inert["ready"] is False
    assert inert["blocked"]["code"] == "PUBLISHED_FLOW_VERSION_INVALID"
    assert inert["surfaces"][0]["name"] == "B unrepaired cron"
    assert inert["surfaces"][0]["next_fire_at"] is not None


def test_readiness_is_scoped_to_the_calling_workspace(db_session):
    workspace, user, _repaired, _unrepaired = _seed(db_session)
    other, _other_user, _a, _b = _seed(db_session)

    response = _client(db_session, workspace, user).get("/systems/dispatch-readiness")

    body = response.json()
    assert body["workspace_id"] == workspace.id
    assert body["summary"]["dispatching_systems"] == 2
    assert other.id != workspace.id
