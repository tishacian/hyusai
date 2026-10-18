"""Operations drill-downs must select the same authorized population as series."""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import activities as api
from app.core.config import settings
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

START, UNTIL = datetime(2026, 1, 1), datetime(2026, 1, 2)
ACTIVE = "pending,running,waiting"


@pytest.fixture
def population(db_session, monkeypatch):
    monkeypatch.setattr(settings, "activity_observability_enabled", True)
    monkeypatch.setattr(settings, "activity_series_enabled", True)
    workspace = Workspace(id="status-ws", slug="status-ws", name="Status")
    foreign = Workspace(id="status-foreign", slug="status-foreign", name="Foreign")
    user = User(id="status-user", username="status-user", role="user", is_active=True)
    other = User(id="status-other", username="status-other", role="user", is_active=True)
    db_session.add_all([workspace, foreign, user, other])
    db_session.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id, user_id=user.id,
        role="member", role_template="workspace_contributor",
    )
    db_session.add_all([
        member,
        System(id="status-system", workspace_id=workspace.id, name="Selected"),
        System(id="status-other-system", workspace_id=workspace.id, name="Other"),
    ])
    db_session.flush()
    for owner in (user, other):
        for index, status in enumerate(("pending", "running", "waiting_subflows", "completed", "failed")):
            db_session.add(Run(
                id=f"{owner.id}-{status}", workspace_id=workspace.id,
                system_id="status-system", status=status, trigger="chat_agentic",
                initiated_by_user_id=owner.id,
                started_at=START + timedelta(minutes=index),
                completed_at=START + timedelta(hours=1) if index >= 3 else None,
            ))
    db_session.add_all([
        Run(id="status-too-old", workspace_id=workspace.id, system_id="status-system",
            status="running", started_at=START - timedelta(microseconds=1)),
        Run(id="status-upper-bound", workspace_id=workspace.id, system_id="status-system",
            status="running", started_at=UNTIL),
        Run(id="status-foreign-run", workspace_id=foreign.id,
            status="running", started_at=START),
        Run(id="status-wrong-system", workspace_id=workspace.id, system_id="status-other-system",
            status="running", started_at=START),
    ])
    db_session.flush()
    db_session.add(SkillInvocation(
        id="status-wrong-kind", run_id=f"{user.id}-running", status="running", started_at=START,
    ))
    db_session.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/observability")
    app.dependency_overrides[api.get_db] = lambda: db_session
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_current_workspace] = lambda: workspace
    return TestClient(app), db_session, user, member


@pytest.mark.parametrize("role,template,multiplier", [
    ("user", "workspace_contributor", 1),
    ("user", "workspace_admin", 2),
    ("admin", "workspace_contributor", 2),
])
@pytest.mark.parametrize("status,expected", [
    (ACTIVE, {"pending", "running", "waiting"}),
    ("running", {"running"}),
    ("succeeded", {"succeeded"}),
    (" pending, running,waiting,pending ", {"pending", "running", "waiting"}),
    (None, {"pending", "running", "waiting", "succeeded", "failed"}),
])
def test_status_union_preserves_scope_pagination_and_series(population, role, template, multiplier, status, expected):
    client, db, user, member = population
    user.role, member.role_template = role, template
    db.commit()
    filters = {"kind": "run", "system_id": "status-system", "until": UNTIL.isoformat()}
    if status is not None:
        filters["status"] = status
    listed = client.get("/observability/activities", params={
        **filters, "since": START.isoformat(), "limit": 1,
    })
    assert listed.status_code == 200
    first = listed.json()
    assert first["total"] == len(expected) * multiplier
    assert len(first["items"]) == 1
    assert first["has_more"] is (first["total"] > 1)
    pages = [client.get("/observability/activities", params={
        **filters, "since": START.isoformat(), "limit": 1, "offset": offset,
    }).json() for offset in range(first["total"])]
    rows = [page["items"][0] for page in pages]
    assert all(page["total"] == first["total"] for page in pages)
    assert not pages[-1]["has_more"]
    assert len({row["id"] for row in rows}) == first["total"]
    assert {row["status"] for row in rows} == expected
    assert {row["native_id"] for row in rows} == {
        f"{owner}-{native}" for owner in ([user.id] if multiplier == 1 else [user.id, "status-other"])
        for state, native in (("pending", "pending"), ("running", "running"),
                              ("waiting", "waiting_subflows"), ("succeeded", "completed"), ("failed", "failed"))
        if state in expected
    }
    response = client.get("/observability/activities/series", params={
        **filters, "from": START.isoformat(),
    })
    assert response.status_code == 200
    series = response.json()
    assert series["totals"]["total"] == sum(bucket["total"] for bucket in series["buckets"]) == first["total"]
    assert series["totals"]["by_status"] == first["aggregates"]["by_status"] == {
        state: multiplier for state in expected
    }
    assert series["population"]["status"] == status


@pytest.mark.parametrize("status", ["", ",", "running,", ",running", "pending,,waiting", "running,invalid", "running, "])
def test_invalid_union_never_silently_broadens_list_or_series(population, status):
    client = population[0]
    for path, extra, detail in (
        ("/observability/activities", {"since": START.isoformat()}, "ACTIVITY_FILTER_INVALID"),
        ("/observability/activities/series", {"from": START.isoformat()}, "ACTIVITY_SERIES_FILTER_INVALID"),
    ):
        response = client.get(path, params={**extra, "until": UNTIL.isoformat(), "status": status})
        assert response.status_code == 422
        assert response.json()["detail"] == detail
