"""Cancellation is a durable request; a running invocation acknowledges it."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.db.base import SessionLocal
from app.models.run import Run

TERMINAL = {"completed", "failed", "cancelled"}


def _lock_cancel_tree(db, run):
    """Lock every native target before an observer can lock its journal cursor.

    Source workers lock native then cursor. Autoflushing the parent before
    locking a child would reverse that order and deadlock with a finishing
    child. Compute precedes Recipe for the historical linked controller.
    """
    from sqlalchemy import or_

    from app.models.compute_run import ComputeRun
    from app.models.recipe import RecipeExecution
    from app.models.tabular import MLModel

    with db.no_autoflush:
        descendants, frontier, visited = [], [run], {run.id}
        while frontier:
            parent = frontier.pop()
            children = (
                db.query(Run)
                .filter_by(parent_run_id=parent.id, workspace_id=run.workspace_id)
                .filter(
                    Run.delegation_key.isnot(None),
                    Run.status.notin_(TERMINAL),
                    Run.id.notin_(visited),
                )
                .order_by(Run.id)
                .with_for_update()
                .populate_existing()
                .all()
            )
            visited.update(child.id for child in children)
            descendants.extend(children)
            frontier.extend(children)
        recipe_ids = [
            row[0]
            for row in db.query(RecipeExecution.id).filter(
                RecipeExecution.workspace_id == run.workspace_id,
                RecipeExecution.run_id.in_(visited),
            )
        ]
        db.query(ComputeRun).filter(
            ComputeRun.workspace_id == run.workspace_id,
            or_(ComputeRun.run_id.in_(visited), ComputeRun.recipe_execution_id.in_(recipe_ids)),
        ).order_by(ComputeRun.id).with_for_update().populate_existing().all()
        db.query(RecipeExecution).filter(
            RecipeExecution.workspace_id == run.workspace_id, RecipeExecution.run_id.in_(visited)
        ).order_by(RecipeExecution.id).with_for_update().populate_existing().all()
        db.query(MLModel).filter(
            MLModel.workspace_id == run.workspace_id, MLModel.run_id.in_(visited)
        ).order_by(MLModel.id).with_for_update().populate_existing().all()
    return descendants


def parent_cancelled(db, run_id, workspace_id):
    """Serialize a late child claim with its parent's cancellation request."""
    if not run_id:
        return False
    parent = (
        db.query(Run)
        .filter_by(id=run_id, workspace_id=workspace_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    return bool(parent and (parent.cancel_requested or parent.status == "cancelled"))


def request_run_cancel(db, run: Run, *, commit: bool = True, _tree_locked: bool = False):
    run = (
        db.query(Run)
        .filter_by(id=run.id, workspace_id=run.workspace_id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if run.status in TERMINAL:
        return run
    if not _tree_locked:
        _lock_cancel_tree(db, run)
    run.cancel_requested = True
    # Paused/pending work has no active invocation to interrupt. Children are
    # requested cooperatively below and keep their own truthful terminal state.
    if run.status in {"pending", "hitl_pending", "debug_pending", "waiting_subflows"}:
        run.status = "cancelled"
        run.error = "execution_cancelled"
        run.completed_at = datetime.utcnow()
    from app.models.compute_run import ComputeRun
    from app.models.recipe import RecipeExecution
    from app.models.tabular import MLModel
    from app.services.compute_runs import request_cancel as cancel_compute
    from app.services.recipe_executions import request_cancel as cancel_recipe
    from app.services.tabular_ml import request_cancel as cancel_model

    for row in (
        db.query(RecipeExecution)
        .filter_by(run_id=run.id, workspace_id=run.workspace_id)
        .order_by(RecipeExecution.id)
    ):
        cancel_recipe(db, row, commit=False)
    for row in (
        db.query(ComputeRun)
        .filter_by(run_id=run.id, workspace_id=run.workspace_id)
        .filter(ComputeRun.recipe_execution_id.is_(None))
        .order_by(ComputeRun.id)
    ):
        cancel_compute(db, row, commit=False)
    for row in (
        db.query(MLModel)
        .filter_by(run_id=run.id, workspace_id=run.workspace_id)
        .order_by(MLModel.id)
    ):
        cancel_model(db, row, commit=False)
    for child in (
        db.query(Run)
        .filter_by(parent_run_id=run.id, workspace_id=run.workspace_id)
        .filter(Run.delegation_key.isnot(None), Run.status.notin_(TERMINAL))
        .order_by(Run.id)
    ):
        request_run_cancel(db, child, commit=False, _tree_locked=True)
    db.commit() if commit else db.flush()
    return run


def cancellation_requested(run_id: str) -> bool:
    with SessionLocal() as db:
        state = db.query(Run.cancel_requested, Run.status).filter_by(id=run_id).first()
        return state is None or state.cancel_requested or state.status == "cancelled"


async def invoke_controlled(run_id: str, invoke):
    """A separate short DB session observes cancellation while an async Skill runs.

    Do not cancel another task's shared ORM session. Blocking CPU Skills must
    already use isolated runners; this does not claim to preempt synchronous
    native code on the event loop.
    """
    if cancellation_requested(run_id):
        raise asyncio.CancelledError("execution_cancelled")
    task = asyncio.create_task(invoke())
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.5)
            if cancellation_requested(run_id):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise asyncio.CancelledError("execution_cancelled")
            if done:
                return task.result()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
