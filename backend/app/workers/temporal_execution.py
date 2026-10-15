"""Optional native Temporal worker and short, identifier-only Celery bridge.

The SDK is imported only in this isolated image. Start a Celery consumer for
``app`` and, separately, ``python -m app.workers.temporal_execution worker``.
Existing intents drain when admission is disabled. No development server is
started implicitly and no legacy Flow is wrapped in an Activity.
"""

import asyncio
from datetime import datetime, timedelta

from celery import Celery
from sqlalchemy import text

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.execution_control import ExecutionDispatch
from app.models.run import Run
from app.services.execution.contracts import ExecutionPolicy
from app.workers.celery_app import configure

app = configure(Celery("agentium-orchestration", broker=settings.celery_broker_url))
app.conf.update(
    task_default_queue=settings.celery_orchestration_queue,
    task_reject_on_worker_lost=True,
    task_ignore_result=True,
    task_routes={
        "agentium.execution_temporal_start": {"queue": settings.celery_orchestration_queue},
        "agentium.execution_temporal_reconcile": {"queue": settings.celery_orchestration_queue},
    },
)


def task_queue(revision):
    # A new image never silently takes ownership of an old workflow's code.
    return f"{settings.execution_temporal_task_queue}:{revision}"


async def connect():
    from temporalio.client import Client

    if settings.execution_temporal_api_key and not settings.execution_temporal_tls:
        raise ValueError("EXECUTION_TEMPORAL_CREDENTIALS_REQUIRE_TLS")
    return await Client.connect(
        settings.execution_temporal_address,
        namespace=settings.execution_temporal_namespace,
        tls=settings.execution_temporal_tls,
        api_key=settings.execution_temporal_api_key or None,
    )


def workflow_id(run_id):
    return f"agentium-native:{run_id}"


def _bound_database(db):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '250ms'"))
        db.execute(text("SET LOCAL statement_timeout = '1s'"))


def _request(run_id):
    """No DB lock/session survives the network call; only references escape."""
    with SessionLocal() as db:
        _bound_database(db)
        run = db.get(Run, run_id)
        if run is None:
            return None
        intent = db.query(ExecutionDispatch).filter_by(entity_kind="run", entity_id=run_id).first()
        if not intent or (run.execution_policy or {}).get("engine") != "temporal":
            return None
        if run.status not in {"pending", "running", "hitl_pending"}:
            return None
        policy = ExecutionPolicy.model_validate(run.execution_policy)
        return {
            "workspace_id": run.workspace_id,
            "run_id": run.id,
            "profile_digest": policy.native_profile_digest,
            "runtime_revision": policy.runtime_revision,
        }, policy


def _authorize_start(request):
    from app.services.execution.runtimes.native_port import authorize

    with SessionLocal() as db:
        _bound_database(db)
        # Only the Activity worker executes the frozen revision's code. This
        # transport bridge still rechecks current IAM before every start.
        authorize(db, request, enforce_revision=False)


async def start(run_id, *, client=None):
    from fastapi import HTTPException
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    request = await asyncio.to_thread(_request, run_id)
    if request is None:
        return "not_pending"
    payload, policy = request
    remaining = policy.remaining_seconds()
    if remaining <= 0:
        # Reconciliation describes an ambiguous earlier start before deciding
        # whether its absence is authoritative. Never replay a different ID.
        return await reconcile_one(run_id, client=client)
    try:
        await asyncio.to_thread(_authorize_start, payload)
    except (ValueError, HTTPException):
        await asyncio.to_thread(_reconcile_terminal, run_id, "EXECUTION_NATIVE_ADMISSION_REFUSED")
        return "refused"
    client = client or await connect()
    try:
        await client.start_workflow(
            "AgentiumNativeWorkflowV1",
            payload,
            id=workflow_id(run_id),
            task_queue=task_queue(policy.runtime_revision),
            execution_timeout=timedelta(seconds=remaining),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        return "already_started"
    return "started"


@app.task(name="agentium.execution_temporal_start", bind=True, max_retries=None)
def start_task(self, run_id):
    try:
        return asyncio.run(asyncio.wait_for(start(run_id), timeout=15))
    except Exception:
        # SDK exception messages may contain endpoint credentials. The stable
        # workflow ID makes retry safe even after an ambiguous start response.
        raise self.retry(
            exc=RuntimeError("EXECUTION_TEMPORAL_UNAVAILABLE"),
            countdown=min(60, 2 ** min(self.request.retries + 1, 6)),
        ) from None


async def reconcile_one(run_id, *, client=None):
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.service import RPCError, RPCStatusCode

    request = await asyncio.to_thread(_request, run_id)
    if request is None:
        return "terminal"
    _, policy = request
    client = client or await connect()
    try:
        description = await client.get_workflow_handle(workflow_id(run_id)).describe()
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
        if policy.remaining_seconds() > 0:
            return await start(run_id, client=client)
        code = "EXECUTION_TEMPORAL_START_DEADLINE"
    else:
        if description.status == WorkflowExecutionStatus.RUNNING:
            return "running"
        # Normal completion must have committed the native Run first. A closed
        # Workflow with nonterminal native state is never inferred successful.
        code = "EXECUTION_TEMPORAL_OUTCOME_REQUIRES_RECONCILIATION"
    await asyncio.to_thread(_reconcile_terminal, run_id, code)
    return "reconciliation_required"


def _reconcile_terminal(run_id, code):
    from app.services.execution.runtimes.native_port import settle_failed_run

    with SessionLocal() as db:
        _bound_database(db)
        run = db.query(Run).filter_by(id=run_id).with_for_update().populate_existing().first()
        if run and run.status in {"pending", "running", "hitl_pending"}:
            settle_failed_run(db, run, error_code=code)
            db.commit()


@app.task(name="agentium.execution_temporal_reconcile")
def reconcile_task():
    with SessionLocal() as db:
        _bound_database(db)
        # No JSON dialect dependency; a bounded scan advances through all
        # candidate intents, including those published before a flag closed.
        candidates = (
            db.query(Run.id)
            .join(
                ExecutionDispatch,
                (ExecutionDispatch.entity_kind == "run") & (ExecutionDispatch.entity_id == Run.id),
            )
            .filter(
                ExecutionDispatch.task_name == "agentium.execution_temporal_start",
                Run.status.in_(["pending", "running", "hitl_pending"]),
            )
            .order_by(ExecutionDispatch.reconciled_at.asc().nullsfirst(), Run.id)
            .limit(5)
            .all()
        )
        identifiers = [row[0] for row in candidates]
        # Rotate the scan; a long-lived first Run must not starve other tenants.
        if identifiers:
            db.query(ExecutionDispatch).filter(
                ExecutionDispatch.entity_kind == "run",
                ExecutionDispatch.entity_id.in_(identifiers),
            ).update(
                {ExecutionDispatch.reconciled_at: datetime.utcnow()}, synchronize_session=False
            )
            db.commit()

    async def reconcile():
        client = await connect()
        failed = 0
        for identifier in identifiers:
            try:
                await asyncio.wait_for(reconcile_one(identifier, client=client), timeout=10)
            except Exception:
                failed += 1
        return failed

    if identifiers:
        try:
            failed = asyncio.run(asyncio.wait_for(reconcile(), timeout=55))
        except Exception:
            # Next scheduled pass retries; no unknown SDK error is persisted.
            return {"inspected": len(identifiers), "available": False}
        return {"inspected": len(identifiers), "available": failed == 0}
    return {"inspected": len(identifiers), "available": True}


async def run_worker():
    from temporalio.worker import Worker

    from app.services.execution.runtimes.native_temporal import NativeActivities, NativeWorkflow

    activities = NativeActivities(session_factory=SessionLocal)
    client = await connect()
    async with Worker(
        client,
        task_queue=task_queue(settings.agentium_image_revision),
        workflows=[NativeWorkflow],
        activities=activities.registered(),
        max_concurrent_activities=2,
    ):
        await asyncio.Event().wait()


if __name__ == "__main__":
    import sys

    if sys.argv[1:] != ["worker"]:
        raise SystemExit("usage: python -m app.workers.temporal_execution worker")
    asyncio.run(run_worker())
