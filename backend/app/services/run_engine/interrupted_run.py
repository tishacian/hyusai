"""Operator reconciliation of a lost inline executor after human approval.

This is terminalisation, never resumption. Legacy inline execution has no
owner lease that proves liveness: a process-stop attestation is mandatory.
NOWAIT locks detect conflicting database writers but cannot replace that proof.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from app.models.audit import AuditLog
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.workspace import Workspace

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL = {"completed", "failed", "cancelled"}


class InterruptedRunError(ValueError):
    """A precondition changed or this execution has a different recovery owner."""


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _inspect(db, *, workspace_id, run_id, decision_id, invocation_id, lock=False):
    def query(model):
        value = db.query(model).populate_existing()
        return value.with_for_update(nowait=True) if lock else value

    workspace_query = db.query(Workspace).filter_by(id=workspace_id).populate_existing()
    if lock:
        workspace_query = workspace_query.with_for_update(key_share=True, nowait=True)
    if workspace_query.one_or_none() is None:
        raise InterruptedRunError("INTERRUPTED_WORKSPACE_NOT_FOUND")
    run = query(Run).filter_by(id=run_id, workspace_id=workspace_id).one_or_none()
    if run is None:
        raise InterruptedRunError("INTERRUPTED_RUN_NOT_FOUND")
    if run.status != "running" or run.completed_at is not None:
        raise InterruptedRunError("INTERRUPTED_RUN_NOT_RUNNING")
    if (
        run.parent_run_id
        or run.delegation_key
        or run.waiting_subflows
        or (run.execution_policy or {}).get("engine") == "temporal"
        or db.query(Run).filter(Run.parent_run_id == run.id, ~Run.status.in_(_TERMINAL)).first()
    ):
        raise InterruptedRunError("INTERRUPTED_DIFFERENT_RECOVERY_OWNER")
    checkpoints = list(run.checkpoints or [])
    if any(not isinstance(cp, dict) for cp in checkpoints):
        raise InterruptedRunError("INTERRUPTED_INLINE_CHECKPOINT_MISMATCH")
    pause = next((cp for cp in reversed(checkpoints) if cp.get("kind") == "hitl_pause"), {})
    dispatch = next(
        (cp for cp in reversed(checkpoints) if cp.get("kind") == "hitl_resume_dispatch"), {}
    )
    resume = next((cp for cp in reversed(checkpoints) if cp.get("kind") == "hitl_resume"), {})
    if (
        pause.get("decision_id") != decision_id
        or dispatch.get("decision_id") != decision_id
        or dispatch.get("plane") != "inline"
        or resume.get("node_id") != pause.get("node_id")
        or resume.get("decision_status") not in {"accepted", "applied"}
        or not pause.get("node_id")
        or not checkpoints.index(pause) < checkpoints.index(dispatch) < checkpoints.index(resume)
    ):
        raise InterruptedRunError("INTERRUPTED_INLINE_CHECKPOINT_MISMATCH")
    decision = (
        query(Decision)
        .filter_by(
            id=decision_id,
            workspace_id=workspace_id,
            scope="run",
            target_id=run.id,
            kind="hitl_approval",
        )
        .one_or_none()
    )
    if (
        decision is None
        or decision.status not in {"accepted", "applied"}
        or not decision.human_confirmed_by
        or not decision.human_confirmed_at
    ):
        raise InterruptedRunError("INTERRUPTED_HUMAN_APPROVAL_REQUIRED")
    invocations = query(SkillInvocation).filter_by(run_id=run.id).order_by(SkillInvocation.id).all()
    active = [row for row in invocations if row.status in {"pending", "running"}]
    if len(active) != 1 or active[0].id != invocation_id or active[0].status != "running":
        raise InterruptedRunError("INTERRUPTED_ACTIVE_INVOCATION_MISMATCH")
    invocation = active[0]
    if invocation.completed_at is not None:
        raise InterruptedRunError("INTERRUPTED_INVOCATION_ALREADY_SETTLED")
    # The token covers the immutable authority, checkpoints, decision and full
    # invocation ledger. Only a digest is returned; inputs may contain secrets.
    state = {
        "run": {column.name: getattr(run, column.name) for column in Run.__table__.columns},
        "decision": {
            column.name: getattr(decision, column.name) for column in Decision.__table__.columns
        },
        "invocations": [
            {column.name: getattr(row, column.name) for column in SkillInvocation.__table__.columns}
            for row in invocations
        ],
    }
    report = {
        "workspace_id": workspace_id,
        "run_id": run.id,
        "decision_id": decision.id,
        "invocation_id": invocation.id,
        "skill_slug": invocation.skill_slug,
        "run_status": run.status,
        "decision_status": decision.status,
        "invocation_status": invocation.status,
        "dispatch_plane": "inline",
        "dispatch_at": dispatch.get("t"),
        "state_sha256": _digest(state),
        "proposed_run_status": "failed",
        "proposed_invocation_status": "failed",
        "external_effect_status": "unknown",
        "reexecuted": False,
        "applied": False,
        "requires_process_stop_attestation": True,
    }
    return run, invocation, report


def preview(db, *, workspace_id, run_id, decision_id, invocation_id):
    """Read and fingerprint the candidate without locking or changing it."""
    return _inspect(
        db,
        workspace_id=workspace_id,
        run_id=run_id,
        decision_id=decision_id,
        invocation_id=invocation_id,
    )[2]


def reconcile(
    db,
    *,
    workspace_id,
    run_id,
    decision_id,
    invocation_id,
    expected_state_sha256,
    operator,
    evidence_sha256,
    evidence_ref,
    confirm_process_stopped=False,
):
    """Stage an audited terminal failure; caller commits the single transaction.

    Restricted to PostgreSQL operator tooling. No provider, queue or execution
    callback is invoked, and accepted decisions and recorded outputs are kept.
    """
    if db.get_bind().dialect.name != "postgresql":
        raise InterruptedRunError("INTERRUPTED_POSTGRESQL_REQUIRED")
    if confirm_process_stopped is not True:
        raise InterruptedRunError("INTERRUPTED_PROCESS_STOP_ATTESTATION_REQUIRED")
    if not all(_DIGEST.fullmatch(str(value)) for value in (expected_state_sha256, evidence_sha256)):
        raise InterruptedRunError("INTERRUPTED_INVALID_DIGEST")
    if any(
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
        for value, maximum in ((operator, 128), (evidence_ref, 255))
    ):
        raise InterruptedRunError("INTERRUPTED_INVALID_ATTESTATION")
    try:
        run, invocation, report = _inspect(
            db,
            workspace_id=workspace_id,
            run_id=run_id,
            decision_id=decision_id,
            invocation_id=invocation_id,
            lock=True,
        )
    except OperationalError as exc:
        if getattr(exc.orig, "pgcode", None) == "55P03":
            raise InterruptedRunError("INTERRUPTED_CONCURRENT_WRITER") from exc
        raise
    if report["state_sha256"] != expected_state_sha256:
        raise InterruptedRunError("INTERRUPTED_STATE_CHANGED")
    now = datetime.utcnow()
    evidence = {
        "kind": "inline_execution_interruption_reconciled",
        "t": now.isoformat(),
        "run_id": run.id,
        "decision_id": decision_id,
        "invocation_id": invocation.id,
        "operator": operator,
        "evidence_ref": evidence_ref,
        "evidence_sha256": evidence_sha256,
        "physical_stop_attested": True,
        "previous_state_sha256": expected_state_sha256,
        "previous_run_error": run.error,
        "previous_invocation_error": invocation.error,
        "external_effect_status": "unknown",
        "reexecuted": False,
        "duration_measured": False,
    }
    run.checkpoints = [*(run.checkpoints or []), evidence]
    run.status = "failed"
    run.error = run.error or "inline_executor_lost_after_approval"
    run.completed_at = now
    run.cancel_requested = True  # additional stop signal, never a liveness proof
    invocation.status = "failed"
    invocation.error = invocation.error or "execution_interrupted_outcome_unknown"
    invocation.completed_at = now
    invocation.trace = {**(invocation.trace or {}), "interruption_reconciliation": evidence}
    # Do not turn wall time, an unknown effect, or an unfinished cost into a
    # measured duration, successful receipt or zero. Existing evidence is kept.
    audit = AuditLog(
        id=str(uuid4()),
        workspace_id=workspace_id,
        event_type="run.execution.interruption_reconciled",
        actor=f"operator:{operator}",
        trace_id=run.id,
        severity="warning",
        details=evidence,
    )
    db.add(audit)
    db.flush()  # audit failure aborts the same transaction, unlike best-effort audit
    return {
        **report,
        "applied": True,
        "run_status": "failed",
        "invocation_status": "failed",
        "audit_id": audit.id,
    }
