"""Optional real Temporal test: real Agentium authorities, provider doubles only.

ACTIVITY_TEMPORAL_ADDRESS must point to an explicitly disposable local server.
No production server or infrastructure is started by this test.
"""

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest

from app.db.base import SessionLocal
from app.models.run import Run, SkillInvocation
from app.models.service_contract import DeliveryReceipt
from app.services import service_promises as promises
from app.tests.services.test_native_temporal_port import candidate as candidate
from app.tests.services.test_service_contracts import review_snapshot


@pytest.fixture
def temporal_server(tmp_path):
    """A CLI opt-in owns its own localhost server and persistent test database."""
    import socket
    import subprocess
    import time
    from types import SimpleNamespace

    binary = os.getenv("ACTIVITY_TEMPORAL_CLI")
    if not binary:
        address = os.getenv("ACTIVITY_TEMPORAL_ADDRESS")
        if not address:
            pytest.skip("ACTIVITY_TEMPORAL_ADDRESS or ACTIVITY_TEMPORAL_CLI required")
        yield SimpleNamespace(address=address, restart=None)
        return
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        ui_port = sock.getsockname()[1]
    process = None
    log = (tmp_path / "temporal-server.log").open("w")

    def start():
        nonlocal process
        process = subprocess.Popen(
            [
                binary,
                "server",
                "start-dev",
                "--ip",
                "127.0.0.1",
                "--port",
                str(port),
                "--ui-port",
                str(ui_port),
                "--db-filename",
                str(tmp_path / "temporal.db"),
                "--log-level",
                "error",
            ],
            env={
                **os.environ,
                "USER": os.getenv("USER") or "agent",
                "NO_PROXY": "localhost,127.0.0.1",
            },
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            assert process.poll() is None, "Disposable Temporal server exited"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.1)
        raise AssertionError("Disposable Temporal server did not start")

    def stop():
        if process and process.poll() is None:
            process.kill()  # Deliberate crash, persistence must recover.
            process.wait(timeout=10)

    def restart():
        stop()
        start()

    try:
        start()
        yield SimpleNamespace(address=f"127.0.0.1:{port}", restart=restart)
    finally:
        stop()
        log.close()


@pytest.mark.parametrize("candidate", ["agent_data_agent", "data_agent_delivery"], indirect=True)
async def test_real_temporal_restart_keeps_no_activity_while_review_and_one_receipt(
    candidate, monkeypatch, temporal_server
):
    from temporalio.client import Client
    from temporalio.worker import Worker

    from app.core.config import settings
    from app.models.execution_control import ExecutionDispatch
    from app.models.recipe import RecipeExecution
    from app.services.dataops.preparation import run_preparation
    from app.services.execution.runtimes.native_temporal import NativeActivities, NativeWorkflow

    s = candidate
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(settings, "execution_control_enabled", True)
    monkeypatch.setattr(settings, "execution_durable_dispatch_enabled", True)
    monkeypatch.setattr(settings, "execution_canary_workspaces", s.workspace.id)
    private_marker = "private-input-must-not-enter-temporal-" + uuid4().hex
    s.run.input_ref = {**s.run.input_ref, "private_marker": private_marker}
    s.db.commit()
    queue = "native-port-test-" + uuid4().hex
    client = await Client.connect(temporal_server.address)
    activities = NativeActivities(SessionLocal)
    async with Worker(
        client, task_queue=queue, workflows=[NativeWorkflow], activities=activities.registered()
    ):
        handle = await client.start_workflow(
            NativeWorkflow.run,
            s.request,
            id="native-qualification-" + s.run.id,
            task_queue=queue,
            execution_timeout=timedelta(minutes=3),
        )
        for _ in range(200):
            s.db.expire_all()
            child = s.db.query(RecipeExecution).filter_by(run_id=s.run.id).first()
            description = await handle.describe()
            if (
                child
                and child.status == "queued"
                and not description.raw_description.pending_activities
            ):
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("The native compute was not waiting independently of Temporal Activities")
        assert (
            s.db.query(ExecutionDispatch)
            .filter_by(entity_kind="recipe_execution", entity_id=child.id)
            .count()
            == 1
        )
        from app.services.execution.contracts import ExecutionPolicy

        parent_deadline = ExecutionPolicy.model_validate(
            s.run.execution_policy
        ).deadline_at.replace(tzinfo=None)
        assert child.deadline_at <= parent_deadline
        # This is the real native worker entry, outside every Temporal Activity.
        # RabbitMQ publication is qualified separately by the outbox tests.
        await asyncio.to_thread(run_preparation, child.id)
        for _ in range(200):
            s.db.expire_all()
            if s.db.get(Run, s.run.id).status == "hitl_pending":
                break
            await asyncio.sleep(0.1)
        else:
            description = await handle.describe()
            pytest.fail(
                f"Native Run did not reach service review: {s.db.get(Run, s.run.id).status}; workflow={description.status}"
            )
        await handle.signal(NativeWorkflow.native_change)
        await asyncio.sleep(0.2)
        s.db.expire_all()
        assert s.run.status == "hitl_pending"  # Signal alone is not approval.
        description = await handle.describe()
        assert not description.raw_description.pending_activities
    # No Worker is alive while a real authorized human reviews the exact asset.
    if temporal_server.restart:
        await asyncio.to_thread(temporal_server.restart)
        client = await Client.connect(temporal_server.address)
        handle = client.get_workflow_handle("native-qualification-" + s.run.id)
    s.db.expire_all()
    decision = promises.review_delivery(
        s.db,
        s.workspace.id,
        s.window.id,
        reviewer_user_id=s.owner.id,
        accept=True,
        qualify_candidate=True,
        note="Local qualification: inspected the actual generated dataset",
        **review_snapshot(s, s.window),
    )
    s.db.commit()
    async with Worker(
        client, task_queue=queue, workflows=[NativeWorkflow], activities=activities.registered()
    ):
        result = await asyncio.wait_for(handle.result(), 30)
    assert result["status"] == "succeeded"
    s.db.expire_all()
    receipt = s.db.get(DeliveryReceipt, result["reference"]["id"])
    assert receipt.decision_id == decision.id and receipt.window_id == s.window.id
    assert s.db.query(SkillInvocation).filter_by(run_id=s.run.id).count() == 3
    assert s.db.query(DeliveryReceipt).filter_by(window_id=s.window.id).count() == 1
    history = await handle.fetch_history()
    assert private_marker not in history.to_json()
    assert not any("agentium.legacy" in str(event) for event in history.events)
