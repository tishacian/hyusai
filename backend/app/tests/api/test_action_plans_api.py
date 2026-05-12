from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import action_plans
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.services.action_plans import handle_action_plan_chat_action, list_action_items


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(action_plans.router, prefix="/api/v1/action-plans")
    app.dependency_overrides[action_plans.get_current_workspace] = lambda: workspace
    app.dependency_overrides[action_plans.get_current_user] = lambda: user
    app.dependency_overrides[action_plans.get_db] = lambda: db_session
    return TestClient(app)


def test_action_plans_are_workspace_scoped_and_audited(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    other = Workspace(id="workspace-andritz", slug="andritz", name="Andritz", mode="standard")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, other, user])
    db_session.commit()

    other_client = _client(db_session, other, user)
    other_created = other_client.post("/api/v1/action-plans/", json={"title": "Andritz private action"})
    assert other_created.status_code == 200

    client = _client(db_session, workspace, user)
    created = client.post(
        "/api/v1/action-plans/",
        json={
            "title": "Arbitrer message presse Nord",
            "description": "Valider une ligne sobre et sourcee.",
            "target_kind": "zone",
            "target_id": "zone-nord",
            "priority": "critical",
            "due_at": "2026-04-15T10:30:00",
        },
    )
    assert created.status_code == 200
    item_id = created.json()["id"]

    listed = client.get("/api/v1/action-plans/")
    assert listed.status_code == 200
    assert [item["title"] for item in listed.json()["items"]] == ["Arbitrer message presse Nord"]
    assert "Andritz private action" not in str(listed.json())

    completed = client.post(f"/api/v1/action-plans/{item_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert {"action_plan.item.created", "action_plan.item.completed"} <= event_types


def test_vigie_action_plan_create_writes_when_policy_is_direct(db_session):
    workspace = Workspace(
        id="workspace-sentinel",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={"action_planner": {"write_policy": "direct"}},
    )
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()

    result = handle_action_plan_chat_action(
        db_session,
        workspace,
        user,
        query="Ajoute une action cabinet prioritaire pour preparer les elements de langage a 10h30",
        assistant_profile="vigie_executive",
    )

    assert result is not None
    assert result["action"] == "action_plan_create"
    assert result["applied"] is True
    assert len(list_action_items(db_session, workspace)) == 1
    assert list_action_items(db_session, workspace)[0].workspace_id == workspace.id
