"""Mission ownership survives disconnects; retries never erase prior output."""

from datetime import datetime, timedelta

import pytest

from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.tasks.execution import (
    MissionConflict,
    checkpoint,
    claim_execution,
    queue_execution,
    recover_executions,
    resume_execution,
)


def mission(db):
    workspace = Workspace(id="mission-ws", slug="mission-ws", name="Missions")
    task = Task(
        id="mission",
        workspace_id=workspace.id,
        title="Report",
        description="Summarise evidence",
        status="pending",
    )
    user = User(id="author", username="mission-author")
    db.add_all([workspace, user, task])
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member"))
    db.commit()
    return task


def test_duplicate_dispatch_is_fenced_and_a_relaunch_keeps_previous_artifacts(db_session):
    task = mission(db_session)
    row = queue_execution(db_session, task, "author")
    db_session.commit()
    first_id = row.id
    fence = claim_execution(db_session, row.id)
    assert fence == 1
    assert claim_execution(db_session, row.id) is None
    assert checkpoint(
        db_session,
        row.id,
        fence,
        {"type": "task_complete", "steps": [], "artifacts": {"report": "first"}, "progress": 100},
    )
    with pytest.raises(MissionConflict, match="CONFIRMATION"):
        queue_execution(db_session, task, "author")
    second = queue_execution(db_session, task, "author", confirm_rerun=True)
    db_session.commit()
    assert second.id != first_id
    assert db_session.get(TaskExecution, first_id).artifacts == {"report": "first"}
    assert task.artifacts == {"report": "first"}


def test_expired_worker_cannot_write_and_resume_keeps_the_same_checkpoint(db_session):
    task = mission(db_session)
    row = queue_execution(db_session, task, "author")
    db_session.commit()
    fence = claim_execution(db_session, row.id)
    completed = {"id": "step-1", "title": "Evidence", "status": "completed", "result": "retained"}
    assert checkpoint(
        db_session, row.id, fence, {"type": "task_step_complete", "step": completed, "progress": 50}
    )
    row.lease_until = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert not checkpoint(
        db_session, row.id, fence, {"type": "task_complete", "artifacts": {"report": "late"}}
    )
    recover_executions(db_session)
    db_session.refresh(row)
    assert row.status == "interrupted"
    same = resume_execution(db_session, task, row.id)
    db_session.commit()
    assert same.id == row.id and same.steps == [completed]
    next_fence = claim_execution(db_session, row.id)
    assert next_fence > fence
    assert not checkpoint(db_session, row.id, fence, {"type": "task_error", "message": "stale"})
    assert checkpoint(
        db_session,
        row.id,
        next_fence,
        {"type": "task_complete", "steps": [completed], "artifacts": {"report": "retained"}},
    )


def test_queued_attempt_is_a_durable_outbox_and_cannot_be_duplicated(db_session):
    task = mission(db_session)
    row = queue_execution(db_session, task, "author")
    db_session.commit()
    assert recover_executions(db_session) == [row.id]
    with pytest.raises(MissionConflict, match="ALREADY_STARTED"):
        queue_execution(db_session, task, "author", confirm_rerun=True)


def test_resume_cannot_cross_workspace(db_session):
    task = mission(db_session)
    row = queue_execution(db_session, task, "author")
    db_session.commit()
    other = Workspace(id="other", slug="other", name="Other")
    other_task = Task(
        id="other-mission",
        workspace_id=other.id,
        title="Other",
        description="Other",
        status="pending",
    )
    db_session.add_all([other, other_task])
    db_session.commit()
    with pytest.raises(MissionConflict, match="NOT_INTERRUPTED"):
        resume_execution(db_session, other_task, row.id)


def test_revoked_creator_cannot_start_queued_mission(db_session):
    task = mission(db_session)
    row = queue_execution(db_session, task, "author")
    db_session.commit()
    db_session.query(WorkspaceMember).filter_by(user_id="author").delete()
    db_session.commit()
    assert claim_execution(db_session, row.id) is None
    db_session.refresh(row)
    assert row.status == "failed" and row.error == "MISSION_ACCESS_REVOKED"
    db_session.refresh(task)
    assert task.status == "failed" and task.error == "MISSION_ACCESS_REVOKED"


def test_engine_resume_skips_completed_steps_and_retains_their_evidence():
    import asyncio

    from app.services.tasks.engine import TaskEngine

    calls = []

    class Model:
        async def complete(self, **kwargs):
            calls.append(kwargs["prompt"])
            return "New report"

    engine = TaskEngine()
    engine._llm = Model()
    steps = [
        {
            "id": "done",
            "title": "Source",
            "status": "completed",
            "result": "Verified source",
            "description": "Read source",
            "step_type": "analysis",
        },
        {
            "id": "todo",
            "title": "Report",
            "status": "running",
            "result": None,
            "description": "Summarise",
            "step_type": "synthesis",
        },
    ]

    async def collect():
        return [event async for event in engine.execute_task("mission", "Goal", resume_steps=steps)]

    events = asyncio.run(collect())
    assert len(calls) == 1 and "Verified source" in calls[0]
    assert events[-1]["steps"][0]["result"] == "Verified source"
    assert events[-1]["artifacts"]["report"] == "New report"
    assert steps[1]["status"] == "running"  # no shared mutable checkpoint


def test_heartbeat_cannot_extend_an_expired_or_superseded_lease(db_session):
    from app.services.tasks.execution import renew_lease

    task = mission(db_session)
    row = queue_execution(db_session, task, "author")
    db_session.commit()
    fence = claim_execution(db_session, row.id)
    assert renew_lease(db_session, row.id, fence)
    assert not renew_lease(db_session, row.id, fence + 1)
    row.lease_until = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert not renew_lease(db_session, row.id, fence)
    recover_executions(db_session)
    db_session.refresh(row)
    assert row.status == "interrupted"


def test_revocation_during_model_call_fences_heartbeat_and_future_checkpoint(db_session):
    from app.services.tasks.execution import renew_lease

    task = mission(db_session)
    row = queue_execution(db_session, task, "author")
    db_session.commit()
    fence = claim_execution(db_session, row.id)
    assert checkpoint(
        db_session,
        row.id,
        fence,
        {
            "type": "task_step_complete",
            "step": {"id": "known", "status": "completed", "result": "retained"},
        },
    )
    member = db_session.query(WorkspaceMember).filter_by(user_id="author").one()
    member.role_template = "workspace_viewer"
    db_session.commit()
    assert not renew_lease(db_session, row.id, fence)
    assert not checkpoint(
        db_session,
        row.id,
        fence,
        {"type": "task_complete", "artifacts": {"report": "late response"}},
    )
    db_session.refresh(row)
    db_session.refresh(task)
    assert row.status == task.status == "failed"
    assert row.steps[0]["result"] == "retained" and row.artifacts == {}


def test_new_mission_formats_the_json_example_before_calling_the_model():
    import asyncio
    import json

    from app.services.tasks.engine import TaskEngine

    expected = [{"title": "Evidence", "description": "Read sources", "type": "analysis"}]
    prompts = []

    class Model:
        async def complete(self, *, prompt, **kwargs):
            prompts.append(prompt)
            return json.dumps(expected)

    engine = TaskEngine()
    engine._llm = Model()
    assert asyncio.run(engine.plan_mission("Analyse {workspace}")) == expected
    assert len(prompts) == 1
    assert '[{"title": "...", "description": "...", "type": "..."}]' in prompts[0]
    assert "Mission: Analyse {workspace}" in prompts[0]
