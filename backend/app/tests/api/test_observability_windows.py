from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import evaluation, observability
from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob


def setup(db):
    workspace = Workspace(id="window-ws", slug="window-ws", name="Windows")
    user = User(id="window-user", username="window-user", role="admin", is_active=True)
    db.add_all([workspace, user, System(id="window-a", workspace_id=workspace.id, name="A"),
                System(id="window-b", workspace_id=workspace.id, name="B")])
    db.commit()
    app = FastAPI()
    app.include_router(observability.router, prefix="/observability")
    app.include_router(evaluation.router, prefix="/evaluation")
    app.dependency_overrides[observability.get_db] = lambda: db
    app.dependency_overrides[observability.get_current_workspace] = lambda: workspace
    app.dependency_overrides[observability.get_current_user] = lambda: user
    return TestClient(app), workspace, user


def test_overview_filter_and_quality_share_fixed_anchor(db_session):
    db = db_session
    client, workspace, _ = setup(db)
    anchor = datetime(2026, 1, 10)
    for identifier, system, start in [
        ("inside", "window-a", anchor - timedelta(hours=1)),
        ("before", "window-a", anchor - timedelta(days=2)),
        ("after", "window-a", anchor + timedelta(seconds=1)),
        ("other-system", "window-b", anchor - timedelta(hours=1)),
    ]:
        db.add(Run(id=identifier, workspace_id=workspace.id, system_id=system,
                   started_at=start, completed_at=start, status="completed"))
        db.add(EvaluationScore(id="eval-"+identifier, workspace_id=workspace.id,
                               run_id=identifier, created_at=start, composite_score=75))
    db.commit()
    params = {"system_id": "window-a", "as_of": anchor.isoformat()+"Z"}
    overview = client.get("/observability/workspace-overview", params={**params, "window": "24h"})
    assert overview.status_code == 200
    assert overview.json()["summary"]["runs_total"] == 1
    assert overview.json()["as_of"] == anchor.isoformat()+"Z"
    history = client.get("/evaluation/history", params={**params, "since": "24h"})
    assert history.status_code == 200
    assert [r["run_id"] for r in history.json()["evaluations"]] == ["inside"]


def test_large_overview_explicitly_announces_sampling(db_session):
    db = db_session
    client, workspace, user = setup(db)
    now = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    db.add_all([Run(id=f"bounded-{index}", workspace_id=workspace.id, system_id="window-a",
                    started_at=now, completed_at=now, status="completed") for index in range(205)])
    db.add_all([WorkspaceJob(id=f"job-{index}", workspace_id=workspace.id,
                            created_by_user_id=user.id, created_at=now, updated_at=now,
                            kind="briefing", status="completed") for index in range(105)])
    db.add_all([EvaluationScore(id=f"eval-{index}", workspace_id=workspace.id,
                               run_id=f"bounded-{index}", created_at=now, composite_score=70) for index in range(105)])
    db.commit()
    response = client.get("/observability/workspace-overview?window=7d")
    assert response.status_code == 200
    coverage = response.json()["coverage"]
    assert coverage["mode"] == "bounded_sample"
    for kind, limit in [("runs", 200), ("jobs", 100), ("evaluations", 100)]:
        assert coverage[kind]["limit"] == limit
        assert coverage[kind]["returned"] <= limit
        assert coverage[kind]["total"] is None


def test_overview_does_not_include_work_only_updated_after_anchor(db_session):
    db = db_session
    client, workspace, user = setup(db)
    anchor = datetime(2026, 1, 10)
    before, inside, after = anchor - timedelta(days=2), anchor - timedelta(hours=1), anchor + timedelta(hours=1)
    for identifier, finish in [("finished-in-window", inside), ("finished-after", after)]:
        db.add(Run(id=identifier, workspace_id=workspace.id, started_at=before,
                   completed_at=finish, status="completed"))
        db.add(WorkspaceJob(id="job-"+identifier, workspace_id=workspace.id,
                            created_by_user_id=user.id, kind="briefing", status="completed",
                            created_at=before, updated_at=finish))
    db.commit()
    response = client.get("/observability/workspace-overview", params={"window": "24h", "as_of": anchor.isoformat()+"Z"})
    assert response.status_code == 200
    result = response.json()
    assert result["summary"]["runs_total"] == 1
    assert result["coverage"]["jobs"]["returned"] == 1
