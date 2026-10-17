from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import activities as api
from app.core.config import settings
from app.models.activity import Activity
from app.models.run import Run, SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.activity_observability.queries import list_activities
from app.services.activity_observability.series import activity_series


@pytest.fixture
def scope(db_session, monkeypatch):
    workspace = Workspace(id="series-ws", slug="series-ws", name="Series")
    user = User(id="series-admin", username="series-admin", role="admin", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    monkeypatch.setattr(settings, "activity_observability_enabled", True)
    monkeypatch.setattr(settings, "activity_series_enabled", True)
    until = datetime(2026, 1, 10)
    return db_session, workspace, user, until - timedelta(days=1), until


def aggregate(scope, **kwargs):
    db, workspace, user, start, until = scope
    return activity_series(db, workspace, user, start=start, until=until, **kwargs)


def seed(scope, *, identifier="run", start=None, finish=None, **kwargs):
    db, workspace, _, default_start, until = scope
    run = Run(id=identifier, workspace_id=workspace.id,
              started_at=start or default_start, completed_at=finish or until - timedelta(hours=1),
              status=kwargs.pop("status", "completed"), **kwargs)
    db.add(run)
    db.commit()
    return run


def test_counts_not_truncated_and_exact_quantiles_ignore_missing(scope):
    db, workspace, _, start, until = scope
    db.add_all([Run(id=f"run-{index:04}", workspace_id=workspace.id, status="completed",
                    started_at=start, completed_at=until - timedelta(hours=1),
                    duration_ms=index if index < 100 else None) for index in range(301)])
    db.commit()
    result = aggregate(scope, kind="run")
    assert result["totals"]["total"] == sum(b["total"] for b in result["buckets"]) == 301
    assert result["totals"]["durations"]["run"] == {
        "eligible_count": 301, "measured_count": 100, "p50_ms": 49, "p95_ms": 94,
    }


def test_finished_population_includes_old_work_and_preserves_creation_semantics(scope):
    seed(scope, start=scope[3] - timedelta(days=3), duration_ms=50)
    assert aggregate(scope)["totals"]["total"] == 0
    assert aggregate(scope, time_basis="finished")["totals"]["total"] == 1


def test_half_open_microsecond_boundaries(scope):
    start, until = scope[3:]
    for index, finish in enumerate([start - timedelta(microseconds=1), start,
                                   start + timedelta(microseconds=1), until - timedelta(microseconds=1), until]):
        seed(scope, identifier=f"r{index}", start=start - timedelta(days=1), finish=finish)
    result = aggregate(scope, time_basis="finished")
    assert result["totals"]["total"] == 3


def test_activity_list_and_created_series_share_anchored_population(scope):
    db, workspace, user, start, until = scope
    for index, created in enumerate([start - timedelta(microseconds=1), start,
                                    until - timedelta(microseconds=1), until]):
        seed(scope, identifier=f"cohort-{index}", start=created)
    listed = list_activities(db, workspace, user, since=start, until=until)
    result = aggregate(scope)
    assert listed["total"] == result["totals"]["total"] == 2


def test_parent_cost_never_added_to_invocation_and_unknown_stays_unknown(scope):
    db = scope[0]
    run = seed(scope, provider_cost_usd=.1)
    for identifier, amount, evidence in [
        ("measured", .1, {"state": "measured", "currency": "USD"}),
        ("calculated", .2, {"state": "calculated", "currency": "EUR"}),
        ("zero", 0, {"state": "calculated", "currency": "USD"}),
        ("historical", 0, {}),
    ]:
        db.add(SkillInvocation(id=identifier, run_id=run.id, status="completed",
                               started_at=run.started_at, completed_at=run.completed_at,
                               cost=amount, provider_cost_usd=amount, cost_measured=True,
                               metrics={"cost_evidence": evidence}))
    db.commit()
    result = aggregate(scope, metric="cost", kind="skill_invocation", time_basis="finished")
    assert result["totals"]["costs"] == [
        {"basis": "catalogue_calculated", "currency": "EUR", "known_amount": .2, "known_count": 1},
        {"basis": "catalogue_calculated", "currency": "USD", "known_amount": 0, "known_count": 1},
        {"basis": "provider_measured", "currency": "USD", "known_amount": .1, "known_count": 1},
    ]
    assert result["totals"]["cost_unknown_count"] == 1
    assert result["totals"]["cost_complete"] is False


def test_hidden_run_never_affects_count_quantile_or_cost(scope):
    db, workspace, _, start, until = scope
    user = User(id="series-member", username="series-member", role="user", is_active=True)
    db.add_all([user, WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member")])
    db.commit()
    run = seed(scope, trigger="chat_agentic", initiated_by_user_id="series-admin", duration_ms=999999)
    db.add(SkillInvocation(run_id=run.id, status="completed", started_at=start, completed_at=until - timedelta(hours=1),
                           cost=.1, provider_cost_usd=.1, cost_measured=True,
                           metrics={"cost_evidence": {"state": "measured", "currency": "USD"}}))
    db.commit()
    member_scope = (db, workspace, user, start, until)
    assert aggregate(member_scope)["totals"]["total"] == 0
    assert aggregate(member_scope, metric="cost", kind="skill_invocation", time_basis="finished")["totals"]["costs"] == []


def test_missing_finish_date_and_snapshot_coverage_are_explicit(scope):
    db, _, _, start, _ = scope
    run = seed(scope)
    run.completed_at = None
    db.commit()
    row = db.query(Activity).one()
    row.origin = "snapshot_only"
    db.commit()
    assert aggregate(scope)["totals"]["snapshot_only_count"] == 1
    result = aggregate(scope, time_basis="finished")
    assert result["totals"]["total"] == 0
    assert result["coverage"]["missing_finished_at"] == 1


@pytest.mark.parametrize("kwargs", [
    {"metric": "cost"}, {"metric": "cost", "kind": "run", "time_basis": "finished"},
    {"kind": "imaginary"}, {"bucket": "minute"}, {"time_basis": "current"},
])
def test_invalid_population_rejected(scope, kwargs):
    with pytest.raises(HTTPException) as error:
        aggregate(scope, **kwargs)
    assert error.value.status_code == 422


def test_series_static_route_precedes_activity_id_and_flag_does_not_disable_journal(scope, monkeypatch):
    db, workspace, user, start, until = scope
    app = FastAPI()
    app.include_router(api.router, prefix="/observability")
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_current_workspace] = lambda: workspace
    client = TestClient(app)
    params = {"from": start.isoformat(), "until": until.isoformat()}
    assert client.get("/observability/activities/series", params=params).status_code == 200
    monkeypatch.setattr(settings, "activity_series_enabled", False)
    assert client.get("/observability/activities/series", params=params).json()["detail"] == "ACTIVITY_SERIES_DISABLED"
    seed(scope)
    assert db.query(Activity).count() == 1
    assert client.get("/observability/activities").status_code == 200


def test_native_flow_read_capability_can_remain_open_without_live_journal(scope, monkeypatch):
    db, workspace, user, _, _ = scope
    monkeypatch.setattr(settings, "activity_observability_enabled", False)
    monkeypatch.setattr(settings, "execution_view_enabled", True)
    features = api.features(workspace=workspace, user=user, db=db)
    assert features["enabled"] is False
    assert features["execution_view_enabled"] is True
    assert features["activity_series_enabled"] is False
