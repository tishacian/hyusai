"""The optional SDK boundary preserves identity and uncertain native outcomes."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytest.importorskip("temporalio")
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from app.core.config import settings
from app.models.execution_control import ExecutionDispatch
from app.models.run import Run
from app.services.execution.contracts import ExecutionPolicy
from app.workers import temporal_execution as bridge


def candidate(db, *, status="pending", expired=False):
    run = Run(
        id=str(uuid4()),
        status=status,
        execution_policy=ExecutionPolicy(
            engine="temporal",
            runtime_revision="qualified-old-image",
            native_profile={"composition": "agent_data_agent"},
            native_profile_digest="a" * 64,
            deadline_at=datetime.now(UTC) + timedelta(seconds=-1 if expired else 60),
        ).model_dump(mode="json"),
    )
    db.add(run)
    db.flush()
    db.add(
        ExecutionDispatch(
            entity_kind="run",
            entity_id=run.id,
            workspace_id="fixture",
            task_name="agentium.execution_temporal_start",
            task_queue="orchestration",
            task_id=str(uuid4()),
            dedupe_key=str(uuid4()),
        )
    )
    db.commit()
    return run


@pytest.mark.asyncio
async def test_ambiguous_start_reuses_workflow_identity_and_frozen_revision(
    db_session, monkeypatch
):
    run = candidate(db_session)
    monkeypatch.setattr(settings, "execution_temporal_enabled", False)
    authorized = []
    monkeypatch.setattr(bridge, "_authorize_start", lambda request: authorized.append(request))
    client = SimpleNamespace(start_workflow=AsyncMock())
    assert await bridge.start(run.id, client=client) == "started"
    client.start_workflow.side_effect = WorkflowAlreadyStartedError(
        bridge.workflow_id(run.id), "AgentiumNativeWorkflowV1"
    )
    assert await bridge.start(run.id, client=client) == "already_started"
    first, second = client.start_workflow.call_args_list
    assert first == second
    assert first.kwargs["task_queue"].endswith(":qualified-old-image")
    assert set(first.args[1]) == {"workspace_id", "run_id", "profile_digest", "runtime_revision"}
    assert first.args[1]["run_id"] == run.id
    assert len(authorized) == 2


@pytest.mark.asyncio
async def test_expired_absent_workflow_is_failed_without_start(db_session):
    run = candidate(db_session, expired=True)
    handle = SimpleNamespace(
        describe=AsyncMock(side_effect=RPCError("fixture", RPCStatusCode.NOT_FOUND, b""))
    )
    client = SimpleNamespace(get_workflow_handle=lambda _: handle, start_workflow=AsyncMock())
    assert await bridge.start(run.id, client=client) == "reconciliation_required"
    db_session.refresh(run)
    assert run.status == "failed" and run.error == "EXECUTION_TEMPORAL_START_DEADLINE"
    client.start_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_closed_workflow_does_not_invent_native_success(db_session):
    run = candidate(db_session, status="running")
    handle = SimpleNamespace(
        describe=AsyncMock(return_value=SimpleNamespace(status=WorkflowExecutionStatus.COMPLETED))
    )
    client = SimpleNamespace(get_workflow_handle=lambda _: handle)
    assert await bridge.reconcile_one(run.id, client=client) == "reconciliation_required"
    db_session.refresh(run)
    assert run.status == "failed" and "RECONCILIATION" in run.error


@pytest.mark.asyncio
async def test_unavailable_server_preserves_native_state(db_session):
    run = candidate(db_session, status="running", expired=True)
    handle = SimpleNamespace(
        describe=AsyncMock(side_effect=RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b""))
    )
    client = SimpleNamespace(get_workflow_handle=lambda _: handle)
    with pytest.raises(RPCError):
        await bridge.reconcile_one(run.id, client=client)
    db_session.refresh(run)
    assert run.status == "running" and run.error is None


@pytest.mark.asyncio
async def test_terminal_native_run_is_never_started_again(db_session):
    run = candidate(db_session, status="cancelled")
    client = SimpleNamespace(start_workflow=AsyncMock())
    assert await bridge.start(run.id, client=client) == "not_pending"
    client.start_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_credentials_require_encrypted_transport(monkeypatch):
    monkeypatch.setattr(settings, "execution_temporal_api_key", "fixture-only")
    monkeypatch.setattr(settings, "execution_temporal_tls", False)
    with pytest.raises(ValueError, match="CREDENTIALS_REQUIRE_TLS"):
        await bridge.connect()


@pytest.mark.asyncio
async def test_revocation_between_commit_and_start_refuses_execution(db_session, monkeypatch):
    from fastapi import HTTPException

    run = candidate(db_session)

    def revoked(request):
        raise HTTPException(403, "private IAM detail")

    monkeypatch.setattr(bridge, "_authorize_start", revoked)
    client = SimpleNamespace(start_workflow=AsyncMock())
    assert await bridge.start(run.id, client=client) == "refused"
    db_session.refresh(run)
    assert run.status == "failed" and run.error == "EXECUTION_NATIVE_ADMISSION_REFUSED"
    client.start_workflow.assert_not_called()


def test_explicit_candidate_never_silently_falls_back_to_legacy(db_session, monkeypatch):
    from fastapi import HTTPException

    from app.services.execution.submission import stage_run

    monkeypatch.setattr(settings, "execution_temporal_enabled", False)
    run = Run(id=str(uuid4()), workspace_id="fixture")
    system = SimpleNamespace(execution_profile={"orchestration": {"engine": "temporal"}})
    with pytest.raises(HTTPException) as refused:
        stage_run(db_session, run, system)
    assert refused.value.status_code == 409
    assert run.execution_policy is None
    assert not db_session.query(ExecutionDispatch).count()


def test_reconciliation_rotates_pending_work_and_isolates_a_slow_workflow(db_session, monkeypatch):
    runs = [candidate(db_session) for _ in range(7)]
    before = {item.entity_id: item.available_at for item in db_session.query(ExecutionDispatch)}
    visited = []
    monkeypatch.setattr(bridge, "connect", AsyncMock(return_value=object()))

    async def inspect(identifier, *, client):
        visited.append(identifier)
        if len(visited) == 1:
            raise TimeoutError("one workflow is slow")
        return "running"

    monkeypatch.setattr(bridge, "reconcile_one", inspect)
    assert bridge.reconcile_task.run() == {"inspected": 5, "available": False}
    assert len(visited) == 5
    assert bridge.reconcile_task.run()["available"]
    assert {run.id for run in runs}.issubset(visited)
    db_session.expire_all()
    assert {
        item.entity_id: item.available_at for item in db_session.query(ExecutionDispatch)
    } == before
