"""Celery task definitions for Agentium."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable, TypeVar

from app.services.rag.context import run_rag_retrieve_context
from app.services.secure_deposit_operations import run_sftp_reconciliation_job
from app.services.visual_intelligence import run_visual_capture_job
from app.services.worker_bm25 import run_bm25_rebuild
from app.services.worker_deep_retrieval import run_deep_retrieval, run_workspace_deep_retrieval
from app.services.worker_ingest import run_document_ingest_index
from app.services.worker_offline_retrieval_artifacts import run_offline_retrieval_artifact_job
from app.workers.celery_app import celery_app

_T = TypeVar("_T")


def _call_with_deadline(callback: Callable[[], _T], remaining_seconds: float | None) -> _T:
    """Enforce the persisted absolute deadline from actual worker start."""

    if remaining_seconds is None:
        return callback()
    if remaining_seconds <= 0:
        raise TimeoutError("delegated subflow deadline expired")

    import signal

    def deadline_exceeded(_signum, _frame):
        raise TimeoutError("delegated subflow deadline expired")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, deadline_exceeded)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, remaining_seconds)
    try:
        return callback()
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def _enqueue_parent_resume_dispatch(parent_run_id: str, *, source_id: str) -> str:
    """Persist a parent wake-up before attempting its best-effort fast path."""

    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.services.run_engine.dispatch_outbox import (
        SUBFLOW_PARENT_RESUME,
        enqueue_dispatch,
        reconcile_dispatch_outbox,
    )
    from app.services.run_engine.subflow_orchestration import _wave_ids_equal

    with SessionLocal() as db:
        parent = db.query(Run).filter(Run.id == parent_run_id).first()
        if parent is None or not parent.workspace_id:
            raise RuntimeError(f"subflow parent {parent_run_id} is missing")
        waiting = parent.waiting_subflows if isinstance(parent.waiting_subflows, dict) else {}
        meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
        raw_wave_id = meta.get("wave_id")
        if raw_wave_id is not None and not _wave_ids_equal(
            raw_wave_id,
            raw_wave_id,
        ):
            raise RuntimeError("subflow parent has a noncanonical wave_id")
        event = enqueue_dispatch(
            db,
            event_type=SUBFLOW_PARENT_RESUME,
            workspace_id=str(parent.workspace_id),
            run_id=parent.id,
            source_id=str(source_id),
            wave_id=raw_wave_id,
        )
        db.commit()
        task_id = event.task_id

    # The maintenance service is the crash-recovery owner. This immediate pass
    # keeps normal latency identical when RabbitMQ is healthy.
    reconcile_dispatch_outbox(
        batch_size=50,
        lease_seconds=settings.p4_maintenance_lease_seconds,
    )
    return str(task_id)


@celery_app.task(name="agentium.document_ingest_index")
def document_ingest_index(job_id: str) -> dict:
    return run_document_ingest_index(job_id)


@celery_app.task(name="agentium.bm25_rebuild")
def bm25_rebuild(job_id: str) -> dict:
    return run_bm25_rebuild(job_id)


@celery_app.task(name="agentium.rag_deep_retrieval")
def rag_deep_retrieval(job_id: str) -> dict:
    return run_deep_retrieval(job_id)


@celery_app.task(name="agentium.workspace_rag_deep_retrieval")
def workspace_rag_deep_retrieval(job_id: str) -> dict:
    return run_workspace_deep_retrieval(job_id)


@celery_app.task(name="agentium.sftp_reconciliation")
def sftp_reconciliation(job_id: str) -> dict:
    return run_sftp_reconciliation_job(job_id)


@celery_app.task(name="agentium.offline_retrieval_artifact")
def offline_retrieval_artifact(job_id: str) -> dict:
    return run_offline_retrieval_artifact_job(job_id)


@celery_app.task(name="agentium.rag_retrieve_context")
def rag_retrieve_context(payload: dict) -> dict:
    return run_rag_retrieve_context(payload)


@celery_app.task(
    name="agentium.subflow_run",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def subflow_run(self, child_run_id: str) -> dict:
    """Execute a delegated child run (P4 multi-agent fan-out).

    Thin wrapper over ``run_engine.engine.run_subflow_child`` so the heavy
    engine import stays lazy (keeps worker boot light and avoids import cycles).
    """
    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.models.system import System
    from app.services.run_engine.dag import subflow_celery_enabled
    from app.services.run_engine.engine import (
        _subflow_deadline_remaining,
        run_subflow_child,
    )
    from app.services.run_engine.subflow_orchestration import (
        _wave_ids_equal,
        postgres_coordination_lease,
    )

    with SessionLocal() as db:
        child = db.query(Run).filter(Run.id == child_run_id).first()
        parent = (
            db.query(Run)
            .filter(
                Run.id == child.parent_run_id,
                Run.workspace_id == child.workspace_id,
            )
            .first()
            if child is not None and child.parent_run_id
            else None
        )
        parent_system = (
            db.query(System)
            .filter(
                System.id == parent.system_id,
                System.workspace_id == parent.workspace_id,
            )
            .first()
            if parent is not None and parent.system_id
            else None
        )
        delegation = (
            ((child.input_ref or {}).get("_delegation") or {})
            if child is not None and isinstance(child.input_ref, dict)
            else {}
        )
        celery_dispatch_snapshot = delegation.get("execution_plane") == "celery"
        waiting = parent.waiting_subflows if parent is not None and isinstance(parent.waiting_subflows, dict) else {}
        entry = waiting.get(child.delegation_key) if child is not None else None
        meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
        envelope_valid = bool(
            child is not None
            and parent is not None
            and child.delegation_key
            and isinstance(entry, dict)
            and entry.get("child_run_id") == child.id
            and (
                meta.get("wave_id") is None
                or _wave_ids_equal(entry.get("wave_id"), meta.get("wave_id"))
            )
        )
        if not envelope_valid:
            return {"id": child_run_id, "status": "delegation_envelope_invalid"}
        if (
            not celery_dispatch_snapshot
            and (
                not settings.enable_subflow_celery
                or parent_system is None
                or not subflow_celery_enabled(parent_system)
            )
        ):
            return {"id": child_run_id, "status": "subflow_celery_disabled"}

    if not settings.database_url.startswith("postgresql"):
        return {"id": child_run_id, "status": "unsupported_coordination_database"}

    with postgres_coordination_lease("subflow-child", child_run_id) as lease_acquired:
        if not lease_acquired:
            raise self.retry(countdown=1, max_retries=120)

        with SessionLocal() as db:
            child = db.query(Run).filter(Run.id == child_run_id).first()
            if child is None:
                return {"id": child_run_id, "status": "missing", "error": "run_not_found"}
            parent_run_id = child.parent_run_id
            if child.status in {"hitl_pending", "waiting_subflows", "debug_pending"}:
                # Durable pauses are resumed only by their dedicated
                # coordinator/API path. A duplicate initial delivery is ACKed
                # without replaying nodes that ran before the pause.
                return {"id": child_run_id, "status": child.status}
            # Acquiring the lease proves no previous worker is alive. A
            # persisted running state therefore represents a lost claimant;
            # fail closed instead of replaying unknown external side-effects.
            if child.status == "running":
                child.status = "failed"
                child.error = child.error or "subflow_worker_lost_after_claim"
                child.completed_at = datetime.utcnow()
                db.commit()
            terminal = child.status in {"completed", "failed", "cancelled"}
            if terminal:
                checkpoints = list(child.checkpoints or [])
                task_id = str(self.request.id)
                if not any(
                    cp.get("kind") == "subflow_terminal_redelivery" and cp.get("task_id") == task_id
                    for cp in checkpoints
                    if isinstance(cp, dict)
                ):
                    checkpoints.append(
                        {
                            "kind": "subflow_terminal_redelivery",
                            "task_id": task_id,
                            "redelivered": bool((self.request.delivery_info or {}).get("redelivered")),
                        }
                    )
                    child.checkpoints = checkpoints
                    db.commit()
            terminal_result = {
                "id": child_run_id,
                "status": child.status,
                "error": child.error,
            }

        execution_error = None
        try:
            remaining = _subflow_deadline_remaining(child_run_id)
            result = (
                terminal_result
                if terminal
                else _call_with_deadline(lambda: run_subflow_child(child_run_id), remaining)
            )
        except asyncio.CancelledError as exc:
            remaining_after_cancel = _subflow_deadline_remaining(child_run_id)
            deadline_expired = (
                remaining_after_cancel is not None and remaining_after_cancel <= 0.25
            )
            execution_error = (
                "delegated subflow deadline expired"
                if deadline_expired
                else "delegated subflow execution cancelled"
            )
            with SessionLocal() as db:
                failed = db.query(Run).filter(Run.id == child_run_id).first()
                if failed is not None and failed.status != "completed":
                    if deadline_expired:
                        failed.status = "failed"
                        failed.error = "subflow_deadline_expired"
                    elif failed.status not in {"failed", "cancelled"}:
                        failed.status = "cancelled"
                        failed.error = failed.error or "execution_cancelled"
                    failed.completed_at = failed.completed_at or datetime.utcnow()
                    db.commit()
            result = {
                "id": child_run_id,
                "status": "failed" if deadline_expired else "cancelled",
                "error": execution_error,
            }
        except Exception as exc:  # includes Celery soft time limits
            execution_error = str(exc)[:400]
            deadline_expired = "deadline" in execution_error.lower()
            with SessionLocal() as db:
                failed = db.query(Run).filter(Run.id == child_run_id).first()
                if failed is not None and failed.status != "completed" and (
                    deadline_expired or failed.status not in {"failed", "cancelled"}
                ):
                    failed.status = "failed"
                    failed.error = (
                        "subflow_deadline_expired"
                        if deadline_expired
                        else failed.error or f"subflow_worker_failed:{execution_error}"
                    )
                    failed.completed_at = datetime.utcnow()
                    db.commit()
            result = {"id": child_run_id, "status": "failed", "error": execution_error}

        with SessionLocal() as db:
            persisted = db.query(Run).filter(Run.id == child_run_id).first()
            persisted_status = persisted.status if persisted is not None else "missing"
            parent_run_id = persisted.parent_run_id if persisted is not None else parent_run_id
        coordination = {"status": "no_parent"}
        if parent_run_id and persisted_status in {"completed", "failed", "cancelled"}:
            try:
                resume_task_id = _enqueue_parent_resume_dispatch(
                    parent_run_id,
                    source_id=child_run_id,
                )
                coordination = {"status": "dispatched", "task_id": resume_task_id}
            except RuntimeError as exc:
                raise self.retry(exc=exc, countdown=1, max_retries=20)
        if execution_error is not None:
            raise RuntimeError(execution_error)
        return {**result, "parent_coordination": coordination}


@celery_app.task(
    name="agentium.subflow_parent_resume",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=1800,
    time_limit=1830,
)
def subflow_parent_resume(self, parent_run_id: str) -> dict:
    """Resume one ready parent while PostgreSQL owns the crash-safe lease."""

    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.models.system import System
    from app.services.run_engine.dag import subflow_celery_enabled
    from app.services.run_engine.engine import (
        _subflow_deadline_remaining,
    )
    from app.services.run_engine.subflow_orchestration import (
        cancel_waiting_children,
        delegated_celery_context,
        resume_subflow_parent_sync,
    )

    with SessionLocal() as db:
        parent = db.query(Run).filter(Run.id == parent_run_id).first()
        system = (
            db.query(System)
            .filter(
                System.id == parent.system_id,
                System.workspace_id == parent.workspace_id,
            )
            .first()
            if parent is not None and parent.system_id
            else None
        )
        waiting_meta = (
            ((parent.waiting_subflows or {}).get("_meta") or {})
            if parent is not None and isinstance(parent.waiting_subflows, dict)
            else {}
        )
        celery_dispatch_snapshot = waiting_meta.get("execution_plane") == "celery"
        if not celery_dispatch_snapshot and (
            not settings.enable_subflow_celery
            or system is None
            or not subflow_celery_enabled(system)
        ):
            return {"status": "subflow_celery_disabled", "parent_run_id": parent_run_id}
    try:
        remaining = _subflow_deadline_remaining(parent_run_id)
        result = _call_with_deadline(
            lambda: resume_subflow_parent_sync(
                parent_run_id,
                resume_owner=str(self.request.id),
                redelivered=bool((self.request.delivery_info or {}).get("redelivered")),
            ),
            remaining,
        )
    except TimeoutError as exc:
        with SessionLocal() as db:
            parent = (
                db.query(Run)
                .filter(Run.id == parent_run_id)
                .with_for_update()
                .first()
            )
            if parent is not None and parent.status not in {"completed", "failed", "cancelled"}:
                parent.status = "failed"
                parent.error = parent.error or f"subflow_deadline_expired:{str(exc)[:300]}"
                parent.completed_at = datetime.utcnow()
                db.commit()
            result = {
                "id": parent_run_id,
                "status": parent.status if parent is not None else "missing",
                "error": str(exc)[:400],
            }
        cancel_waiting_children(parent_run_id, reason="subflow_deadline_expired")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=1, max_retries=20)
    if result.get("status") in {"checkpoint_pending", "resume_busy"}:
        raise self.retry(countdown=1, max_retries=120)

    # A delegated child may itself be a parent. Once its grandchildren have
    # settled, completion must wake the next ancestor in the same durable
    # chain; otherwise the root remains waiting forever.
    with SessionLocal() as db:
        resumed = db.query(Run).filter(Run.id == parent_run_id).first()
        resumed_status = resumed.status if resumed is not None else "missing"
        ancestor_context = (
            delegated_celery_context(
                db,
                child=resumed,
                workspace_id=resumed.workspace_id,
            )
            if resumed is not None and resumed.delegation_key
            else None
        )
        ancestor_id = ancestor_context[0].id if ancestor_context is not None else None
    if ancestor_id and resumed_status in {"completed", "failed", "cancelled"}:
        try:
            _enqueue_parent_resume_dispatch(ancestor_id, source_id=parent_run_id)
        except RuntimeError as exc:
            raise self.retry(exc=exc, countdown=1, max_retries=20)
    return result


@celery_app.task(
    name="agentium.subflow_hitl_resume",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def subflow_hitl_resume(
    self,
    child_run_id: str,
    expected_decision_id: str | None = None,
) -> dict:
    """Durably continue a delegated child after its Decision is resolved."""

    from celery.exceptions import Retry
    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.models.system import System
    from app.services.run_engine.dag import (
        resolve_hitl_decision_for_run,
        resume_run_dag,
        subflow_celery_enabled,
    )
    from app.services.run_engine.engine import (
        _subflow_deadline_remaining,
    )
    from app.services.run_engine.subflow_orchestration import (
        _wave_ids_equal,
        postgres_coordination_lease,
    )

    with SessionLocal() as db:
        child = db.query(Run).filter(Run.id == child_run_id).first()
        parent = (
            db.query(Run)
            .filter(
                Run.id == child.parent_run_id,
                Run.workspace_id == child.workspace_id,
            )
            .first()
            if child is not None and child.parent_run_id
            else None
        )
        parent_system = (
            db.query(System)
            .filter(
                System.id == parent.system_id,
                System.workspace_id == parent.workspace_id,
            )
            .first()
            if parent is not None and parent.system_id
            else None
        )
        delegation = (
            ((child.input_ref or {}).get("_delegation") or {})
            if child is not None and isinstance(child.input_ref, dict)
            else {}
        )
        celery_dispatch_snapshot = delegation.get("execution_plane") == "celery"
        if (
            not celery_dispatch_snapshot
            and (
                not settings.enable_subflow_celery
                or parent_system is None
                or not subflow_celery_enabled(parent_system)
            )
        ):
            return {"status": "subflow_celery_disabled", "child_run_id": child_run_id}
        waiting = (
            parent.waiting_subflows
            if parent is not None and isinstance(parent.waiting_subflows, dict)
            else {}
        )
        entry = waiting.get(child.delegation_key) if child is not None else None
        meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
        if (
            child is None
            or parent is None
            or not isinstance(entry, dict)
            or entry.get("child_run_id") != child.id
            or child.parent_run_id != parent.id
            or (
                meta.get("wave_id") is not None
                and not _wave_ids_equal(
                    entry.get("wave_id"),
                    meta.get("wave_id"),
                )
            )
        ):
            return {"status": "delegation_envelope_invalid", "child_run_id": child_run_id}

    if not settings.database_url.startswith("postgresql"):
        return {"status": "unsupported_coordination_database", "child_run_id": child_run_id}

    # Initial execution and every durable continuation share one lease.  A
    # late redelivery of the initial task must never race a HITL continuation.
    try:
        with postgres_coordination_lease("subflow-child", child_run_id) as lease_acquired:
            if not lease_acquired:
                raise self.retry(countdown=1, max_retries=120)
            with SessionLocal() as db:
                child = db.query(Run).filter(Run.id == child_run_id).first()
                if child is None:
                    return {"status": "missing", "child_run_id": child_run_id}
                parent_run_id = child.parent_run_id
                decision_id = None
                if child.status == "hitl_pending":
                    pause_cp = next(
                        (
                            checkpoint
                            for checkpoint in reversed(list(child.checkpoints or []))
                            if isinstance(checkpoint, dict) and checkpoint.get("kind") == "hitl_pause"
                        ),
                        None,
                    )
                    decision_id = pause_cp.get("decision_id") if pause_cp else None
                    if expected_decision_id and decision_id != expected_decision_id:
                        return {
                            "status": "stale_decision",
                            "child_run_id": child_run_id,
                            "decision_id": decision_id,
                        }
                    decision = (
                        resolve_hitl_decision_for_run(
                            db,
                            run=child,
                            decision_id=decision_id,
                            lock=True,
                        )
                        if decision_id
                        else None
                    )
                    if decision is None or decision.status not in {"accepted", "applied", "rejected"}:
                        return {"status": "waiting_decision", "child_run_id": child_run_id}
                if child.status == "running":
                    child.status = "failed"
                    child.error = child.error or "subflow_hitl_worker_lost_after_claim"
                    child.completed_at = datetime.utcnow()
                    db.commit()
                status = child.status

            if status == "hitl_pending":
                remaining = _subflow_deadline_remaining(child_run_id)
                try:
                    summary = _call_with_deadline(
                        lambda: asyncio.run(resume_run_dag(child_run_id, decision_id=decision_id)),
                        remaining,
                    )
                except Exception as exc:
                    with SessionLocal() as db:
                        failed = db.query(Run).filter(Run.id == child_run_id).first()
                        if failed is not None and failed.status not in {"completed", "failed", "cancelled"}:
                            failed.status = "failed"
                            failed.error = failed.error or f"subflow_hitl_resume_failed:{str(exc)[:400]}"
                            failed.completed_at = datetime.utcnow()
                            db.commit()
                    summary = {"id": child_run_id, "status": "failed", "error": str(exc)[:400]}
            else:
                summary = {"id": child_run_id, "status": status}

            with SessionLocal() as db:
                child = db.query(Run).filter(Run.id == child_run_id).first()
                parent_run_id = child.parent_run_id if child is not None else parent_run_id
                status = child.status if child is not None else "missing"
            if parent_run_id and status in {"completed", "failed", "cancelled"}:
                _enqueue_parent_resume_dispatch(
                    parent_run_id,
                    source_id=child_run_id,
                )
            return summary
    except Retry:
        raise
    except Exception as exc:
        raise self.retry(exc=exc, countdown=1, max_retries=20)


@celery_app.task(
    name="agentium.run_hitl_resume",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_hitl_resume(
    self,
    run_id: str,
    expected_decision_id: str,
) -> dict:
    """Durably resume a non-Celery HITL Run exactly once per live owner."""

    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.models.system import System
    from app.services.run_engine.dag import resolve_hitl_decision_for_run, resume_run_dag
    from app.services.run_engine.subflow_orchestration import (
        delegated_celery_claimed,
        postgres_coordination_lease,
        resume_parent_for_child_sync,
    )

    if not settings.database_url.startswith("postgresql"):
        return {"id": run_id, "status": "unsupported_coordination_database"}

    # Parent and child endpoints can expose the same in-process subflow
    # Decision. The Decision id is therefore the canonical mutex key: both
    # routes serialize onto one owner even though their Run ids differ.
    with postgres_coordination_lease(
        "run-hitl-decision",
        expected_decision_id,
    ) as lease_acquired:
        if not lease_acquired:
            raise self.retry(countdown=1, max_retries=120)

        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            if run is None:
                return {"id": run_id, "status": "missing", "error": "run_not_found"}
            if delegated_celery_claimed(db, child=run, workspace_id=run.workspace_id):
                return {"id": run_id, "status": "delegated_hitl_requires_subflow_task"}
            pause_cp = next(
                (
                    checkpoint
                    for checkpoint in reversed(list(run.checkpoints or []))
                    if isinstance(checkpoint, dict) and checkpoint.get("kind") == "hitl_pause"
                ),
                None,
            )
            decision_id = pause_cp.get("decision_id") if pause_cp else None
            if decision_id != expected_decision_id:
                return {
                    "id": run_id,
                    "status": "stale_decision",
                    "decision_id": decision_id,
                }
            dispatch_cp = next(
                (
                    checkpoint
                    for checkpoint in reversed(list(run.checkpoints or []))
                    if isinstance(checkpoint, dict)
                    and checkpoint.get("kind") == "hitl_resume_dispatch"
                    and str(checkpoint.get("decision_id") or "")
                    == str(expected_decision_id)
                ),
                None,
            )
            if dispatch_cp is None or dispatch_cp.get("plane") != "run_celery":
                return {"id": run_id, "status": "run_hitl_celery_not_authorized"}
            decision = resolve_hitl_decision_for_run(
                db,
                run=run,
                decision_id=decision_id,
            )
            if decision is None or decision.status not in {"accepted", "applied", "rejected"}:
                return {"id": run_id, "status": "waiting_decision"}
            if run.status in {"completed", "failed", "cancelled"}:
                summary = {"id": run.id, "status": run.status, "error": run.error}
            else:
                scoped_system = (
                    db.query(System)
                    .filter(
                        System.id == run.system_id,
                        System.workspace_id == run.workspace_id,
                    )
                    .first()
                )
                if scoped_system is None:
                    run.status = "failed"
                    run.error = run.error or "hitl_system_scope_mismatch"
                    run.completed_at = datetime.utcnow()
                    db.commit()
                    summary = {"id": run.id, "status": "failed", "error": run.error}
                else:
                    summary = None
            if summary is None and run.status == "running":
                # Owning the crash-released lease proves the former claimant
                # is gone. Fail closed instead of replaying unknown effects.
                run.status = "failed"
                run.error = run.error or "hitl_worker_lost_after_claim"
                run.completed_at = datetime.utcnow()
                db.commit()
                summary = {"id": run.id, "status": "failed", "error": run.error}
            elif summary is None and run.status != "hitl_pending":
                return {"id": run.id, "status": run.status, "error": run.error}

        if summary is None:
            try:
                summary = asyncio.run(resume_run_dag(run_id, decision_id=expected_decision_id))
            except Exception as exc:
                raise self.retry(exc=exc, countdown=1, max_retries=20)

        # Preserve the historical post-resume hooks, now after a durable task.
        # Terminal redelivery intentionally reaches these hooks: the worker may
        # have died after the Run commit but before parent/chat finalization.
        try:
            resume_parent_for_child_sync(
                run_id,
                resume_owner=str(self.request.id),
                redelivered=bool((self.request.delivery_info or {}).get("redelivered")),
            )
            if summary.get("status") in {"completed", "failed"}:
                from app.services.chat_agentic_runtime import finalize_resumed_agentic_chat

                finalize_resumed_agentic_chat(run_id)
        except Exception as exc:
            raise self.retry(exc=exc, countdown=1, max_retries=20)
        return summary


@celery_app.task(
    name="agentium.subflow_crash_probe",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def subflow_crash_probe(self, token: str) -> dict:
    """Protected integration probe proving RabbitMQ worker-loss redelivery.

    It is inert outside the explicit protected-test environment. A dedicated
    solo worker dies on first delivery; a second worker receives the same task
    and writes the redelivery marker. This must never be routed to production.
    """
    import os
    from pathlib import Path
    from uuid import UUID

    if os.getenv("RUN_RABBITMQ_INTEGRATION") != "1":
        raise RuntimeError("subflow crash probe is disabled")
    safe_token = str(UUID(str(token)))
    root = Path(os.getenv("SUBFLOW_CRASH_PROBE_DIR", "/tmp"))
    first = root / f"agentium-p4-crash-{safe_token}.first"
    redelivered = root / f"agentium-p4-crash-{safe_token}.redelivered"
    if not first.exists():
        first.write_text(str(self.request.id), encoding="utf-8")
        os._exit(91)  # dedicated integration worker only
    redelivered.write_text(str(self.request.id), encoding="utf-8")
    return {"status": "redelivered", "task_id": str(self.request.id)}


@celery_app.task(name="agentium.visual_snapshot_capture")
def visual_snapshot_capture(job_id: str) -> dict:
    return run_visual_capture_job(job_id)


@celery_app.task(name="agentium.refresh_macro_indicators")
def refresh_macro_indicators_task(workspace_slug: str = "sentinel-ci", force: bool = False) -> dict:
    """Periodic refresh (24h) of the macro indicators cache.

    Defaults to the SENTINEL-CI workspace so the demo cockpit always has
    fresh data; can be parameterised by Celery beat for other workspaces.
    """
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace
    from app.services.macro_indicators import fetch_civ_indicators

    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == workspace_slug).first()
        if not workspace:
            return {"status": "skipped", "reason": "workspace_not_found", "workspace_slug": workspace_slug}
        result = fetch_civ_indicators(db, workspace, force=bool(force))
    return {"status": "ok", **result}


@celery_app.task(name="agentium.scheduler_tick")
def scheduler_tick_task() -> dict:
    """Celery beat entrypoint: fire due schedules + sweep expired HITL gates."""
    from app.services.run_engine.scheduler import scheduler_tick

    return scheduler_tick()
