"""Identifier-only dispatch for durable mission attempts."""

import asyncio

from app.workers.celery_app import celery_app


@celery_app.task(name="agentium.run_mission", acks_late=True, reject_on_worker_lost=True)
def run_mission(execution_id):
    from app.db.base import SessionLocal
    from app.services.tasks.engine import get_task_engine
    from app.services.tasks.execution import execute_mission

    return asyncio.run(execute_mission(execution_id, SessionLocal, get_task_engine()))


@celery_app.task(name="agentium.recover_missions")
def recover_missions():
    from app.db.base import SessionLocal
    from app.services.tasks.execution import dispatch_execution, recover_executions

    with SessionLocal() as db:
        queued = recover_executions(db)
    return {
        "queued": len(queued),
        "dispatched": sum(dispatch_execution(execution_id) for execution_id in queued),
    }
