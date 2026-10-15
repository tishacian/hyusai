import json
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.api.v1.endpoints import activities as api
from app.core.config import settings
from app.models.activity import Activity, ActivityCommand, ActivityEvent, ActivityWorkspaceCursor
from app.models.compute_run import ComputeRun
from app.models.recipe import RecipeExecution
from app.models.run import Run, SkillInvocation
from app.models.service_contract import DeliveryReceipt, ServiceAttempt, ServiceWindow
from app.models.system import System
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.activity_observability import commands, queries
from app.services.activity_observability.projection import activity_id, backfill


@pytest.fixture
def context(db_session, monkeypatch):
    for model in (ActivityCommand, ActivityEvent, Activity, ActivityWorkspaceCursor):
        db_session.query(model).delete(synchronize_session=False)
    workspace = Workspace(id="activity-ws", slug="activity-ws", name="Activity")
    user = User(id="activity-user", username="activity-user", role="admin", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    monkeypatch.setattr(settings, "activity_observability_enabled", True)
    monkeypatch.setattr(settings, "execution_control_enabled", True)
    monkeypatch.setattr(settings, "execution_canary_workspaces", "*")
    return db_session, workspace, user


def seed_run(db, workspace, identifier="run-one", **kwargs):
    row = Run(id=identifier, workspace_id=workspace.id, status="pending", **kwargs)
    db.add(row)
    db.commit()
    return row


def client(context):
    db, workspace, user = context
    app = FastAPI()
    app.include_router(api.router, prefix="/observability")
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_current_workspace] = lambda: workspace
    return TestClient(app)


def test_journal_is_atomic_with_native_rollback(context):
    db, workspace, user = context
    seed_run(db, workspace)
    before = queries.highwater(db, workspace.id)
    db.query(Run).filter_by(id="run-one").update({"status": "running"}, synchronize_session=False)
    assert db.query(Activity).one().status == "running"
    assert db.query(ActivityEvent).count() == 2
    db.rollback()
    db.expire_all()
    assert db.get(Run, "run-one").status == "pending"
    assert db.query(Activity).one().status == "pending"
    assert db.query(ActivityEvent).count() == 1
    assert queries.highwater(db, workspace.id) == before


def test_orm_and_bulk_core_transitions_do_not_record_secrets_or_tokens(context):
    db, workspace, _ = context
    row = seed_run(db, workspace, input_ref={"password": "DO_NOT_JOURNAL"}, error="DO_NOT_JOURNAL")
    row.status = "running"
    db.commit()
    db.execute(update(Run).where(Run.id == row.id).values(status="completed", duration_ms=12.5))
    db.commit()
    events = db.query(ActivityEvent).order_by(ActivityEvent.sequence).all()
    assert [event.payload["status"] for event in events] == ["pending", "running", "succeeded"]
    db.execute(update(Run).where(Run.id == row.id).values(output_ref={"token": "DO_NOT_JOURNAL"}))
    db.commit()
    assert db.query(ActivityEvent).count() == 3
    assert "DO_NOT_JOURNAL" not in json.dumps(db.query(Activity).one().snapshot)
    assert "DO_NOT_JOURNAL" not in json.dumps([event.payload for event in events])


def test_eight_native_sources_and_compute_heartbeat(context):
    db, workspace, user = context
    run = seed_run(db, workspace)
    now = datetime.utcnow()
    db.add_all([
        SkillInvocation(id="inv-one", run_id=run.id, status="running", input_ref={"secret": "HIDDEN"}),
        RecipeExecution(id="recipe-one", workspace_id=workspace.id, run_id=run.id, status="queued"),
        ComputeRun(id="compute-one", workspace_id=workspace.id, run_id=run.id, kind="connector_read", operation="read", deadline_at=now+timedelta(minutes=1), cpu_cores=1, memory_mb=128, reserved_core_hours=0.1),
        MLModel(id="ml-one", workspace_id=workspace.id, run_id=run.id, slug="model", name="Model", version=1, task="classification", algo="logistic", target="target", status="pending"),
        WorkspaceJob(id="job-one", workspace_id=workspace.id, run_id=run.id, kind="briefing", title="HIDDEN"),
        ServiceWindow(id="window-one", workspace_id=workspace.id, contract_id="contract", system_id="system", logical_key="key", period_start=now, period_end=now+timedelta(days=1), deadline_at=now+timedelta(days=1)),
        DeliveryReceipt(id="receipt-one", workspace_id=workspace.id, window_id="window-one", asset_id="asset", asset_digest="a"*64, qualification_id="qualification", qualification_digest="b"*64, destination="HIDDEN", decision_id="decision", binding_digest="c"*64),
    ])
    db.commit()
    assert set(row.kind for row in db.query(Activity).all()) == set(queries.KINDS)
    before = db.query(ActivityEvent).count()
    db.query(ComputeRun).filter_by(id="compute-one").update({"lease_expires_at": now+timedelta(seconds=30), "lease_token": "HIDDEN"}, synchronize_session=False)
    db.commit()
    assert db.query(ActivityEvent).count() == before
    assert "HIDDEN" not in json.dumps([row.snapshot for row in db.query(Activity).all()])


def test_snapshot_backfill_never_invents_historical_events(context, monkeypatch):
    db, workspace, user = context
    monkeypatch.setattr(settings, "activity_observability_enabled", False)
    row = Run(id="historical", workspace_id=workspace.id, status="completed")
    db.add(row)
    db.commit()
    assert db.query(Activity).count() == 0
    backfill(db, kind="run")
    db.commit()
    assert db.query(Activity).one().origin == "snapshot_only"
    assert db.query(ActivityEvent).one().event_type == "activity.snapshot"
    backfill(db, kind="run")
    db.commit()
    assert db.query(ActivityEvent).count() == 1


def test_cursor_bound_to_workspace_and_not_ahead(context):
    db, workspace, user = context
    seed_run(db, workspace)
    with pytest.raises(HTTPException, match="ACTIVITY_CURSOR_INVALID"):
        queries.event_page(db, workspace, user, cursor=queries.encode_cursor("another-workspace", 0))
    with pytest.raises(HTTPException, match="ACTIVITY_CURSOR_AHEAD"):
        queries.event_page(db, workspace, user, cursor=queries.encode_cursor(workspace.id, 99))
    first = queries.event_page(db, workspace, user, limit=1)
    assert len(first["items"]) == 1
    event = first["items"][0]
    assert event["specversion"] == "1.0" and event["type"] == "activity.updated"
    assert event["data"] == {"activity_id": event["activity_id"], "version": 1, "kind": "run", "status": "pending", "native_status": "pending"}
    assert queries.event_page(db, workspace, user, cursor=first["next_cursor"])["items"] == []


def test_aggregates_exhaustive_and_private_runs_not_in_page_or_events(context):
    db, workspace, user = context
    db.add_all([Run(id=f"many-{index:04}", workspace_id=workspace.id, status="completed") for index in range(205)])
    db.commit()
    result = queries.list_activities(db, workspace, user, limit=3, offset=200)
    assert result["total"] == 205 and result["aggregates"]["by_status"] == {"succeeded": 205}
    assert len(result["items"]) == 3 and result["has_more"]
    other = User(id="ordinary", username="ordinary", role="user", is_active=True)
    db.add(other)
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=other.id, role="member"))
    db.commit()
    private = seed_run(db, workspace, "private", trigger="chat_agentic", initiated_by_user_id=user.id)
    identifier = activity_id("run", private.id)
    visible = queries.list_activities(db, workspace, other, limit=100)
    assert visible["total"] == 205
    with pytest.raises(HTTPException):
        queries.authorized_activity(db, identifier, workspace, other)
    assert identifier not in {event["activity_id"] for event in queries.event_page(db, workspace, other, limit=500)["items"]}


def test_commands_are_idempotent_versioned_and_atomically_applied(context):
    db, workspace, user = context
    row = RecipeExecution(id="recipe-cancel", workspace_id=workspace.id, status="running")
    db.add(row)
    db.commit()
    activity = db.query(Activity).one()
    command = commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=1, idempotency_key="cancel-one")
    db.commit()
    assert commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=1, idempotency_key="cancel-one").id == command.id
    assert commands.process_commands(db) == 1
    db.rollback()
    db.expire_all()
    assert db.get(ActivityCommand, command.id).status == "requested"
    assert not db.get(RecipeExecution, row.id).cancel_requested
    commands.process_commands(db)
    db.commit()
    db.expire_all()
    assert db.get(ActivityCommand, command.id).status == "applied"
    assert db.get(RecipeExecution, row.id).cancel_requested
    assert db.get(RecipeExecution, row.id).status == "running"  # applied != stopped
    assert commands.process_commands(db) == 0


def test_commands_reject_stale_version_and_unsupported_action(context):
    db, workspace, user = context
    db.add(RecipeExecution(id="recipe-cancel", workspace_id=workspace.id, status="running"))
    db.commit()
    activity = db.query(Activity).one()
    with pytest.raises(HTTPException, match="ACTIVITY_VERSION_CONFLICT"):
        commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=42, idempotency_key="stale-one")
    with pytest.raises(HTTPException, match="ACTIVITY_COMMAND_UNSUPPORTED"):
        commands.enqueue(db, row=activity, workspace=workspace, user=user, action="retry", expected_version=1, idempotency_key="retry-one")


def test_feature_discovery_and_platform_gate(context, monkeypatch):
    db, workspace, user = context
    http = client(context)
    assert http.get("/observability/activities/features").json()["enabled"] is True
    assert http.get("/observability/platform-overview").status_code == 200
    user.role = "user"
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin"))
    db.commit()
    assert http.get("/observability/platform-overview").status_code == 403
    assert "platform" not in http.get("/observability/activities/features").json()["scopes"]
    monkeypatch.setattr(settings, "activity_observability_enabled", False)
    assert http.get("/observability/activities/features").json()["enabled"] is False
    assert http.get("/observability/activities").status_code == 404


@pytest.mark.asyncio
async def test_sse_rechecks_auth_without_any_source_traffic(monkeypatch):
    class Request:
        headers = {}
        async def is_disconnected(self):
            return False
    calls = []
    def poll(*args):
        calls.append(args)
        if len(calls) == 2:
            raise HTTPException(403)
        return {"items": [], "next_cursor": "cursor", "has_more": False}
    monkeypatch.setattr(api, "_stream_page", poll)
    frames = [frame async for frame in api.stream_events(Request(), "w", "u", "cursor", None, poll_s=0, lifetime_s=1)]
    assert len(calls) == 2
    assert "event: snapshot" in frames[0] and "id: cursor" in frames[0]
    assert "ACTIVITY_ACCESS_REVOKED" in frames[-1]


def test_commands_recheck_revoked_membership_at_execution(context):
    db, workspace, user = context
    user.role = "user"
    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin")
    db.add(member)
    db.add(RecipeExecution(id="revoked-cancel", workspace_id=workspace.id, status="running"))
    db.commit()
    activity = db.query(Activity).one()
    command = commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=1, idempotency_key="revoked-command")
    db.commit()
    db.delete(member)
    db.commit()
    commands.process_commands(db)
    db.commit()
    assert command.status == "rejected"
    assert not db.get(RecipeExecution, "revoked-cancel").cancel_requested


def test_native_connector_ownership_and_private_jobs_are_not_broadened(context):
    db, workspace, admin = context
    ordinary = User(id="connector-observer", username="connector-observer", role="user", is_active=True)
    db.add(ordinary)
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=ordinary.id, role="member"))
    run = seed_run(db, workspace)
    db.add(ComputeRun(id="private-compute", workspace_id=workspace.id, run_id=run.id, user_id=admin.id,
                      kind="connector_read", operation="read", deadline_at=datetime.utcnow()+timedelta(minutes=1), cpu_cores=1, memory_mb=128, reserved_core_hours=0.1))
    db.add(WorkspaceJob(id="private-job", workspace_id=workspace.id, run_id=run.id, kind="briefing", created_by_user_id=admin.id))
    db.commit()
    assert {row["kind"] for row in queries.list_activities(db, workspace, ordinary)["items"]} == {"run"}
    assert {row["kind"] for row in queries.event_page(db, workspace, ordinary)["items"]} == {"run"}


@pytest.mark.parametrize("kind", ["run", "ml_training", "compute_run", "recipe_execution"])
def test_native_cancel_adapters_record_request_without_claiming_running_job_stopped(context, monkeypatch, kind):
    db, workspace, user = context
    if kind == "run":
        native = Run(id="native-cancel", workspace_id=workspace.id, status="running")
    elif kind == "ml_training":
        native = MLModel(id="native-cancel", workspace_id=workspace.id, slug="cancel-model", name="Cancel", version=1, task="classification", algo="logistic", target="target", status="training")
    elif kind == "recipe_execution":
        native = RecipeExecution(id="native-cancel", workspace_id=workspace.id, status="running")
    else:
        native = ComputeRun(id="native-cancel", workspace_id=workspace.id, kind="connector_read", operation="read", status="running", deadline_at=datetime.utcnow()+timedelta(minutes=1), cpu_cores=1, memory_mb=128, reserved_core_hours=0.1)
    db.add(native)
    db.commit()
    activity = db.query(Activity).one()
    monkeypatch.setattr(settings, "execution_canary_workspaces", "different-workspace")
    assert queries.serialize_activity(db, activity, workspace, user)["capabilities"]["cancel"] is False
    with pytest.raises(HTTPException, match="ACTIVITY_COMMAND_UNSUPPORTED"):
        commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=1, idempotency_key="outside-canary")
    monkeypatch.setattr(settings, "execution_canary_workspaces", workspace.slug)
    command = commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=1, idempotency_key="cancel-native")
    db.commit()
    # Closing the rollout blocks new commands without abandoning the request
    # that was already durably accepted for this native execution.
    monkeypatch.setattr(settings, "execution_control_enabled", False)
    monkeypatch.setattr(settings, "execution_canary_workspaces", "different-workspace")
    assert not queries.can_cancel(db, activity, workspace, user)
    commands.process_commands(db)
    db.commit()
    db.expire_all()
    assert command.status == "applied" and native.cancel_requested
    assert db.query(Activity).one().status == "running"


def test_window_attempts_link_native_runs_not_receipts_or_other_children(context):
    db, workspace, user = context
    run = seed_run(db, workspace)
    now = datetime.utcnow()
    db.add(ServiceWindow(id="window-attempt", workspace_id=workspace.id, contract_id="contract", system_id="system", logical_key="daily", period_start=now, period_end=now+timedelta(days=1), deadline_at=now+timedelta(days=1)))
    db.add(ServiceAttempt(id="actual-attempt", workspace_id=workspace.id, window_id="window-attempt", run_id=run.id, fence=1, lease_token="MUST_NOT_LEAK"))
    db.add(DeliveryReceipt(id="actual-receipt", workspace_id=workspace.id, window_id="window-attempt", asset_id="asset", asset_digest="a"*64, qualification_id="qual", qualification_digest="b"*64, destination="opaque", decision_id="decision", binding_digest="c"*64))
    db.commit()
    # A real System is normally required by the native service foreign key.
    # Read via its system-authorized metadata boundary in this isolated fixture.
    from app.models.system import System
    db.add(System(id="system", workspace_id=workspace.id, name="Service", objective="Daily"))
    db.commit()
    row = db.get(Activity, activity_id("service_window", "window-attempt"))
    detail = queries.detail(db, row, workspace, user)
    assert [item["native_id"] for item in detail["attempts"]] == [run.id]
    assert [item["kind"] for item in detail["related_activities"]] == ["delivery_receipt"]
    assert "MUST_NOT_LEAK" not in json.dumps(detail)


def test_http_cancel_duplicate_and_version_conflict(context):
    db, workspace, user = context
    db.add(RecipeExecution(id="http-cancel", workspace_id=workspace.id, status="running"))
    db.commit()
    identifier = activity_id("recipe_execution", "http-cancel")
    http = client(context)
    payload = {"action": "cancel", "expected_version": 1, "idempotency_key": "request-once"}
    first = http.post(f"/observability/activities/{identifier}/commands", json=payload)
    second = http.post(f"/observability/activities/{identifier}/commands", json=payload)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "requested"
    assert http.post(f"/observability/activities/{identifier}/commands", json={**payload, "expected_version": 9, "idempotency_key": "request-stale"}).status_code == 409
    assert http.post(f"/observability/activities/{identifier}/commands", json={**payload, "expected_version": True}).status_code == 422


@pytest.mark.parametrize("kind", ["run", "recipe_execution", "compute_run", "ml_training"])
def test_run_and_native_child_controls_keep_system_operator_authority(context, monkeypatch, kind):
    from app.api.v1.endpoints import systems

    db, workspace, user = context
    db.add(System(id="controlled-system", workspace_id=workspace.id, name="Controlled"))
    run = seed_run(db, workspace, system_id="controlled-system", execution_contract={"test_frozen_policy": "preserved"})
    if kind == "run":
        native = run
    elif kind == "recipe_execution":
        native = RecipeExecution(id="controlled-child", workspace_id=workspace.id, run_id=run.id, status="running")
    elif kind == "compute_run":
        native = ComputeRun(id="controlled-child", workspace_id=workspace.id, run_id=run.id, kind="connector_read", operation="read", status="running", deadline_at=datetime.utcnow()+timedelta(minutes=1), cpu_cores=1, memory_mb=128, reserved_core_hours=0.1)
    else:
        native = MLModel(id="controlled-child", workspace_id=workspace.id, run_id=run.id, slug="controlled-model", name="Controlled", version=1, task="classification", algo="logistic", target="target", status="training")
    db.add(native)
    db.commit()
    activity = db.get(Activity, activity_id(kind, native.id))
    allowed = False
    calls = []

    def guard(db, **kwargs):
        calls.append(kwargs)
        assert kwargs["system"].id == "controlled-system"
        assert kwargs["execution_contract"] == run.execution_contract
        if not allowed:
            raise HTTPException(403, detail={"policy": "NEVER_EXPOSE_POLICY_TEXT"})

    monkeypatch.setattr(systems, "_enforce_system_run_authority", guard)
    assert queries.serialize_activity(db, activity, workspace, user)["capabilities"]["cancel"] is False
    with pytest.raises(HTTPException, match="ACTIVITY_COMMAND_UNSUPPORTED"):
        commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=activity.version, idempotency_key="blocked")
    assert db.query(ActivityCommand).count() == 0
    allowed = True
    assert queries.serialize_activity(db, activity, workspace, user)["capabilities"]["cancel"] is True
    command = commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=activity.version, idempotency_key="accepted")
    db.commit()
    allowed = False  # authority revoked after durable enqueue
    commands.process_commands(db)
    db.commit()
    assert command.status == "rejected" and command.error_code == "ACTIVITY_COMMAND_NO_LONGER_ALLOWED"
    assert not native.cancel_requested
    assert "NEVER_EXPOSE_POLICY_TEXT" not in json.dumps(queries.serialize_command(command))
    assert len(calls) >= 5


def test_dispatch_revalidates_system_authority_after_native_lock(context, monkeypatch):
    from app.api.v1.endpoints import systems

    db, workspace, user = context
    db.add(System(id="controlled-system", workspace_id=workspace.id, name="Controlled"))
    run = seed_run(db, workspace, system_id="controlled-system")
    activity = db.get(Activity, activity_id("run", run.id))
    calls = []
    def guard(db, **kwargs):
        calls.append(kwargs)
        if len(calls) >= 3:  # enqueue, dispatcher precheck, post-lock check
            raise HTTPException(403, detail="NEVER_EXPOSE_POLICY_TEXT")
    monkeypatch.setattr(systems, "_enforce_system_run_authority", guard)
    command = commands.enqueue(db, row=activity, workspace=workspace, user=user, action="cancel", expected_version=activity.version, idempotency_key="race")
    db.commit()
    commands.process_commands(db)
    db.commit()
    assert len(calls) == 3 and command.status == "rejected"
    assert command.error_code == "ACTIVITY_COMMAND_NO_LONGER_ALLOWED"
    assert not run.cancel_requested and run.status == "pending"
