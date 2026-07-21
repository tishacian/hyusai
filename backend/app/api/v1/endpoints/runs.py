"""Canonical /runs endpoints — supersede /traces.

A Run carries the Outcome block. Detail view exposes the SkillInvocation
ledger so the cockpit can drill from the Run timeline down to individual
skill calls.
"""
import asyncio
import json
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.iam.roles import WORKSPACE_REVIEWER, is_admin_template, normalize_role_template
from app.core.logging import get_logger
from app.db.base import SessionLocal, get_db
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chat_execution_policy import (
    migration_059_system_id,
)
from app.services.decisions import (
    InvalidTransition,
)
from app.services.decisions import (
    accept as accept_decision,
)
from app.services.decisions import (
    reject as reject_decision,
)
from app.services.outcome.derive import apply_operator_override
from app.services.run_engine import schedule_run
from app.services.run_engine.dag import resume_run_dag, resume_run_dag_debug
from app.services.run_engine.events import bus as event_bus

logger = get_logger(__name__)
router = APIRouter()

_PRIVATE_CHAT_TRIGGER = "chat_agentic"


def _postgres_hitl_coordination_supported() -> bool:
    """Durable HITL coordination requires PostgreSQL advisory leases."""

    return settings.database_url.startswith("postgresql")


def _durable_run_hitl_enabled(system: Optional[System]) -> bool:
    """Gate ordinary HITL Celery without changing the default experience."""

    raw_settings = system.settings if system is not None else None
    features = raw_settings.get("features") if isinstance(raw_settings, dict) else None
    return bool(
        _postgres_hitl_coordination_supported()
        and settings.enable_run_hitl_celery
        and isinstance(features, dict)
        and features.get("run_hitl_celery") is True
    )


def _has_private_chat_admin_access(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    return bool(membership and is_admin_template(membership.role_template, membership.role))


def _can_view_private_chat_runs(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> bool:
    """Reviewers and workspace/org admins may inspect every Agentic chat Run."""
    if _has_private_chat_admin_access(db, user=user, workspace=workspace):
        return True
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    if membership is None:
        return False
    return bool(
        normalize_role_template(membership.role_template, membership.role) == WORKSPACE_REVIEWER
    )


def _managed_agentic_run_requires_admin(
    db: DBSession,
    *,
    run: Run,
    workspace: Workspace,
) -> bool:
    """Keep in-flight and rejected migration-059 Runs admin-only.

    This closes both sides of the HITL race: an initiator cannot attach an SSE
    stream while the gated draft is still being produced, and a rejected draft
    does not become readable merely because finalisation made the Run terminal.
    """
    managed_system_id = migration_059_system_id(workspace)
    if managed_system_id is None:
        return False
    managed = run.system_id == managed_system_id

    # A parent subflow can surface a Decision owned by a managed child Run.
    # Preserve the same boundary for that parent without trusting checkpoint
    # payload beyond the server-persisted Decision -> Run relationship.
    if not managed:
        decision_ids = [
            checkpoint.get("decision_id")
            for checkpoint in list(run.checkpoints or [])
            if isinstance(checkpoint, dict) and checkpoint.get("kind") == "hitl_pause"
        ]
        decision_ids = [decision_id for decision_id in decision_ids if decision_id]
        if decision_ids:
            managed = (
                db.query(Run.id)
                .join(Decision, Decision.target_id == Run.id)
                .filter(
                    Decision.id.in_(decision_ids),
                    Decision.scope == "run",
                    or_(
                        Decision.workspace_id == workspace.id,
                        Decision.workspace_id.is_(None),
                    ),
                    Run.workspace_id == workspace.id,
                    Run.system_id == managed_system_id,
                )
                .first()
                is not None
            )
    if not managed:
        return False

    if run.status not in {"completed", "failed", "cancelled"}:
        return True

    output = run.output_ref if isinstance(run.output_ref, dict) else {}
    if str(output.get("hitl_decision") or "").strip().lower() == "rejected":
        return True
    return any(
        isinstance(checkpoint, dict)
        and checkpoint.get("kind") == "hitl_resume"
        and str(checkpoint.get("decision_status") or "").strip().lower() == "rejected"
        for checkpoint in list(run.checkpoints or [])
    )


def _run_is_visible(
    db: DBSession,
    *,
    run: Run,
    user: User,
    workspace: Workspace,
    allow_managed_hitl_for_resolution: bool = False,
) -> bool:
    requires_admin = _managed_agentic_run_requires_admin(
        db,
        run=run,
        workspace=workspace,
    )
    resolution_may_authorize = allow_managed_hitl_for_resolution and run.status == "hitl_pending"
    if requires_admin and not resolution_may_authorize:
        return _has_private_chat_admin_access(db, user=user, workspace=workspace)
    if run.trigger != _PRIVATE_CHAT_TRIGGER:
        return True
    if run.initiated_by_user_id == user.id:
        return True
    return _can_view_private_chat_runs(db, user=user, workspace=workspace)


def _visible_run_or_404(
    db: DBSession,
    *,
    run_id: str,
    user: User,
    workspace: Workspace,
    allow_managed_hitl_for_resolution: bool = False,
) -> Run:
    """Resolve one Run without disclosing private Agentic Run existence."""
    run = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace.id).first()
    if run is None or not _run_is_visible(
        db,
        run=run,
        user=user,
        workspace=workspace,
        allow_managed_hitl_for_resolution=allow_managed_hitl_for_resolution,
    ):
        raise HTTPException(404, "Run not found")
    return run


def _row(r: Run) -> Dict[str, Any]:
    membrane_held = _membrane_egress_held(r)
    checkpoints = []
    for checkpoint in list(r.checkpoints or []):
        if (
            membrane_held
            and isinstance(checkpoint, dict)
            and checkpoint.get("kind") == "hitl_pause"
            and checkpoint.get("membrane_egress")
        ):
            public = {key: value for key, value in checkpoint.items() if key != "state"}
            public["result_held"] = True
            checkpoints.append(public)
        else:
            checkpoints.append(checkpoint)
    return {
        "id": r.id,
        "system_id": r.system_id,
        "capability_id": r.capability_id,
        "status": r.status,
        "trigger": r.trigger,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "duration_ms": r.duration_ms,
        "input_ref": r.input_ref or {},
        "output_ref": r.output_ref or {},
        "outcome": {
            "decision": r.decision,
            "confidence": r.confidence,
            "value_estimated": r.value_estimated,
            "cost_internal": r.cost_internal,
            "revenue_allocated": r.revenue_allocated,
            "efficiency": r.efficiency,
            "value_source": getattr(r, "value_source", None) or "unset",
            "operator_value_note": getattr(r, "operator_value_note", None),
        },
        "retries": r.retries,
        "error": r.error,
        "checkpoints": checkpoints,
        "waiting_subflows": r.waiting_subflows or {},
        "result_held": membrane_held,
    }


def _membrane_egress_held(r: Run) -> bool:
    if (r.status or "") != "hitl_pending":
        return False
    return any(
        isinstance(checkpoint, dict)
        and checkpoint.get("kind") == "hitl_pause"
        and checkpoint.get("membrane_egress") is True
        for checkpoint in reversed(list(r.checkpoints or []))
    )


def _pending_hitl_checkpoint(r: Run) -> Optional[Dict[str, Any]]:
    """Return the last ``hitl_pause`` checkpoint when the Run is awaiting
    operator input, ``None`` otherwise."""
    if (r.status or "") != "hitl_pending":
        return None
    for cp in reversed(list(r.checkpoints or [])):
        if isinstance(cp, dict) and cp.get("kind") == "hitl_pause":
            return cp
    return None


def _pending_debug_checkpoint(r: Run) -> Optional[Dict[str, Any]]:
    """Return the last ``debug_pause`` checkpoint when the Run is paused
    in the step debugger."""
    if (r.status or "") != "debug_pending":
        return None
    for cp in reversed(list(r.checkpoints or [])):
        if isinstance(cp, dict) and cp.get("kind") == "debug_pause":
            return cp
    return None


def _invocation(i: SkillInvocation, *, redact_io: bool = False) -> Dict[str, Any]:
    return {
        "id": i.id,
        "skill_slug": i.skill_slug,
        "status": i.status,
        "started_at": i.started_at.isoformat() if i.started_at else None,
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        "latency_ms": i.latency_ms,
        "cost": i.cost,
        "input_ref": {} if redact_io else i.input_ref or {},
        "output_ref": {} if redact_io else i.output_ref or {},
        "metrics": i.metrics or {},
        "trace": i.trace or {},
        "error": i.error,
    }


@router.get("")
async def list_runs(
    system_id: Optional[str] = None,
    capability_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    q = db.query(Run).filter(Run.workspace_id == workspace.id)
    if not _can_view_private_chat_runs(db, user=user, workspace=workspace):
        q = q.filter(
            or_(
                Run.trigger.is_(None),
                Run.trigger != _PRIVATE_CHAT_TRIGGER,
                Run.initiated_by_user_id == user.id,
            )
        )
    if system_id:
        # Do not accept an orphaned or cross-tenant parent edge even when a
        # corrupted Run row itself belongs to the current workspace.
        current_parent_system = exists().where(
            and_(
                System.id == Run.system_id,
                System.workspace_id == workspace.id,
            )
        )
        q = q.filter(Run.system_id == system_id, current_parent_system)
    if capability_id:
        visible_capability = exists().where(
            and_(
                Capability.id == capability_id,
                or_(
                    Capability.workspace_id == workspace.id,
                    Capability.workspace_id.is_(None),
                ),
            )
        )
        parent_system_matches = exists().where(
            and_(
                System.id == Run.system_id,
                System.workspace_id == workspace.id,
                System.capability_id == capability_id,
            )
        )
        q = q.filter(
            visible_capability,
            or_(
                parent_system_matches,
                and_(Run.system_id.is_(None), Run.capability_id == capability_id),
            ),
        )
    if status:
        q = q.filter(Run.status == status)
    rows = q.order_by(Run.started_at.desc()).limit(limit).all()
    rows = [row for row in rows if _run_is_visible(db, run=row, user=user, workspace=workspace)]
    return {"runs": [_row(r) for r in rows]}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    r = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == r.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    payload: Dict[str, Any] = {
        **_row(r),
        "invocations": [
            _invocation(i, redact_io=_membrane_egress_held(r)) for i in invocations
        ],
    }
    pending_cp = _pending_hitl_checkpoint(r)
    if pending_cp:
        decision_id = pending_cp.get("decision_id")
        decision: Optional[Decision] = None
        if decision_id:
            candidate = db.query(Decision).filter(Decision.id == decision_id).first()
            if candidate and _decision_target_run(
                db,
                decision=candidate,
                paused_run=r,
                workspace_id=workspace.id,
            ):
                decision = candidate
        payload["hitl"] = {
            "node_id": pending_cp.get("node_id"),
            "prompt": pending_cp.get("prompt"),
            "decision_id": decision_id,
            "decision_status": decision.status if decision else None,
            "decision_title": decision.title if decision else None,
        }
    debug_cp = _pending_debug_checkpoint(r)
    if debug_cp:
        payload["debug"] = {
            "node_id": debug_cp.get("node_id"),
            "debug_mode": debug_cp.get("debug_mode"),
            "breakpoints": debug_cp.get("breakpoints") or [],
            "ctx_snapshot": debug_cp.get("ctx_snapshot") or {},
            "last_output": debug_cp.get("last_output") or {},
        }
    return payload


class HitlResolve(BaseModel):
    action: Literal["accept", "reject"]
    actor: Optional[str] = Field(
        default=None,
        description="Deprecated compatibility field; the authenticated server identity is used.",
    )
    note: Optional[str] = Field(default=None, description="Audit trail note.")


def _actor_label(user: User) -> str:
    """Return the authenticated identity written to the Decision audit trail."""
    return (
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or getattr(user, "keycloak_sub", None)
        or str(user.id)
    )


def _is_migration_managed_agentic_system(
    workspace: Workspace,
    system: System,
) -> bool:
    return migration_059_system_id(workspace) == system.id


def _run_lineage(
    db: DBSession,
    *,
    run: Run,
    workspace_id: str,
) -> Optional[List[Run]]:
    """Return ``run`` and its ancestors, failing closed on corrupt edges."""
    lineage: List[Run] = []
    current: Optional[Run] = run
    visited: set[str] = set()
    while current is not None:
        if current.id in visited or current.workspace_id != workspace_id:
            return None
        visited.add(current.id)
        lineage.append(current)
        if not current.parent_run_id:
            break
        current = (
            db.query(Run)
            .filter(
                Run.id == current.parent_run_id,
                Run.workspace_id == workspace_id,
            )
            .first()
        )
        if current is None:
            return None
    return lineage


def _decision_target_run(
    db: DBSession,
    *,
    decision: Decision,
    paused_run: Run,
    workspace_id: str,
) -> Optional[Run]:
    """Resolve a HITL Decision only when it belongs to the paused run tree."""
    if decision.scope != "run" or not decision.target_id:
        return None
    if decision.workspace_id not in (None, workspace_id):
        return None
    target = (
        db.query(Run).filter(Run.id == decision.target_id, Run.workspace_id == workspace_id).first()
    )
    if target is None:
        return None
    lineage = _run_lineage(db, run=target, workspace_id=workspace_id)
    if lineage is None or paused_run.id not in {row.id for row in lineage}:
        return None
    return target


def _canonical_in_process_hitl_run(
    db: DBSession,
    *,
    decision_target: Run,
    decision_id: str,
    workspace_id: str,
) -> Run:
    """Return the outermost paused ancestor carrying the same Decision.

    An in-process subflow copies its child's HITL pause through every parent.
    Resuming the deepest child alone leaves those parents paused, so all API
    routes converge on the outermost matching checkpoint instead.
    """

    lineage = _run_lineage(db, run=decision_target, workspace_id=workspace_id) or []
    matching = []
    for candidate in lineage:
        checkpoint = _pending_hitl_checkpoint(candidate)
        if checkpoint is not None and str(checkpoint.get("decision_id") or "") == str(decision_id):
            matching.append(candidate)
    return matching[-1] if matching else decision_target


def _persisted_hitl_dispatch_plane(run: Run, decision_id: str) -> Optional[str]:
    for checkpoint in reversed(list(run.checkpoints or [])):
        if not isinstance(checkpoint, dict) or checkpoint.get("kind") != "hitl_resume_dispatch":
            continue
        if str(checkpoint.get("decision_id") or "") != str(decision_id):
            continue
        plane = str(checkpoint.get("plane") or "")
        if plane in {"inline", "run_celery", "subflow_celery"}:
            return plane
        return "invalid"
    return None


def _record_hitl_dispatch_plane(run: Run, *, decision_id: str, plane: str) -> None:
    """Snapshot the execution plane in the Decision transition transaction."""

    if _persisted_hitl_dispatch_plane(run, decision_id) is not None:
        return
    run.checkpoints = [
        *(run.checkpoints or []),
        {
            "kind": "hitl_resume_dispatch",
            "t": datetime.utcnow().isoformat(),
            "decision_id": decision_id,
            "plane": plane,
        },
    ]


def _require_hitl_authorization(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    paused_run: Run,
    decision_target: Run,
) -> None:
    """Allow workspace admins, or the initiating user for ordinary Systems.

    Migration-059's production Agentic System is deliberately stricter: only
    organization admins and workspace admin/owner roles may resolve its HITL
    gates, even when they initiated the Run themselves.
    """
    is_admin = getattr(user, "role", None) == "admin"
    if not is_admin:
        membership = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.workspace_id == workspace.id,
            )
            .first()
        )
        if membership is None:
            raise HTTPException(403, "Workspace membership required to resolve HITL")
        is_admin = is_admin_template(membership.role_template, membership.role)

    affected_runs: Dict[str, Run] = {}
    for candidate in (paused_run, decision_target):
        lineage = _run_lineage(db, run=candidate, workspace_id=workspace.id)
        if lineage is None:
            raise HTTPException(403, "Run lineage is outside the current workspace")
        affected_runs.update({row.id: row for row in lineage})

    for candidate in affected_runs.values():
        if not candidate.system_id:
            continue
        system = (
            db.query(System)
            .filter(
                System.id == candidate.system_id,
                System.workspace_id == workspace.id,
            )
            .first()
        )
        if system is None:
            raise HTTPException(403, "Run System is outside the current workspace")
        if _is_migration_managed_agentic_system(workspace, system) and not is_admin:
            raise HTTPException(
                403,
                "Admin/owner access required for the production Agentic System",
            )

    if is_admin:
        return
    if any(row.initiated_by_user_id == user.id for row in affected_runs.values()):
        return
    raise HTTPException(403, "Only the Run initiator or a workspace admin may resolve HITL")


@router.post("/{run_id}/hitl")
async def resolve_run_hitl(
    run_id: str,
    body: HitlResolve,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Operator accepts or rejects the pending HITL Decision and the DAG
    walker resumes in the background. The call is idempotent: a second
    request on a Run no longer paused returns 409.
    """
    r = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
        allow_managed_hitl_for_resolution=True,
    )
    pending_cp = _pending_hitl_checkpoint(r)
    if not pending_cp:
        raise HTTPException(409, f"Run is not awaiting HITL (status={r.status!r})")
    decision_id = pending_cp.get("decision_id")
    if not decision_id:
        raise HTTPException(500, "HITL checkpoint is missing its decision_id")
    # Serialize accept/reject on the canonical Decision row. ``populate_existing``
    # is required because the identity map may already hold the unlocked object
    # loaded while rendering the Run.
    decision = (
        db.query(Decision)
        .filter(
            Decision.id == decision_id,
            or_(
                Decision.workspace_id == workspace.id,
                Decision.workspace_id.is_(None),
            ),
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not decision:
        raise HTTPException(404, "HITL decision not found")
    # The Decision and paused Run are the same authority boundary. Lock and
    # revalidate the Run after acquiring the Decision lock so an any/race
    # coordinator that cancelled the child first wins cleanly.
    locked_run = (
        db.query(Run)
        .filter(
            Run.id == r.id,
            Run.workspace_id == workspace.id,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    locked_checkpoint = _pending_hitl_checkpoint(locked_run) if locked_run is not None else None
    if (
        locked_run is None
        or locked_checkpoint is None
        or str(locked_checkpoint.get("decision_id") or "") != str(decision.id)
    ):
        db.rollback()
        raise HTTPException(409, "Run is no longer awaiting this HITL decision")
    r = locked_run
    requested_run_id = r.id
    requested_run_status = r.status
    decision_target = _decision_target_run(
        db,
        decision=decision,
        paused_run=r,
        workspace_id=workspace.id,
    )
    if decision_target is None:
        raise HTTPException(404, "HITL decision not found")

    # A child Decision can be surfaced by every in-process ancestor. All such
    # routes converge on the outermost live pause, then lock and revalidate it
    # while the canonical Decision row is still held.
    canonical_candidate = _canonical_in_process_hitl_run(
        db,
        decision_target=decision_target,
        decision_id=decision.id,
        workspace_id=workspace.id,
    )
    canonical_run = (
        db.query(Run)
        .filter(
            Run.id == canonical_candidate.id,
            Run.workspace_id == workspace.id,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    canonical_checkpoint = (
        _pending_hitl_checkpoint(canonical_run) if canonical_run is not None else None
    )
    if (
        canonical_run is None
        or canonical_checkpoint is None
        or str(canonical_checkpoint.get("decision_id") or "") != str(decision.id)
    ):
        db.rollback()
        raise HTTPException(409, "Canonical Run is no longer awaiting this HITL decision")
    r = canonical_run
    decision_target = _decision_target_run(
        db,
        decision=decision,
        paused_run=r,
        workspace_id=workspace.id,
    )
    if decision_target is None:
        db.rollback()
        raise HTTPException(404, "HITL decision not found")
    _require_hitl_authorization(
        db,
        user=user,
        workspace=workspace,
        paused_run=r,
        decision_target=decision_target,
    )

    actor = _actor_label(user)
    from app.services.run_engine.subflow_orchestration import (
        delegated_celery_claimed,
        delegated_celery_context,
    )

    celery_owned = delegated_celery_claimed(
        db,
        child=r,
        workspace_id=workspace.id,
    )
    delegated_context = delegated_celery_context(
        db,
        child=r,
        workspace_id=workspace.id,
    )
    if celery_owned and delegated_context is None:
        db.rollback()
        raise HTTPException(409, "Delegated HITL context is no longer active")
    delegated_celery_child = delegated_context is not None
    run_system = (
        db.query(System)
        .filter(
            System.id == r.system_id,
            System.workspace_id == workspace.id,
        )
        .first()
        if r.system_id
        else None
    )
    if r.system_id and run_system is None:
        db.rollback()
        raise HTTPException(403, "Run System is outside the current workspace")

    # The first resolution snapshots its execution plane in the same commit as
    # the Decision transition. A retry therefore cannot switch from inline to
    # Celery (or vice versa) after a flag change or ambiguous broker ACK.
    dispatch_plane = _persisted_hitl_dispatch_plane(r, decision.id)
    if dispatch_plane == "invalid":
        db.rollback()
        raise HTTPException(409, "Persisted HITL execution plane is invalid")
    if dispatch_plane is None:
        if delegated_celery_child:
            if not _postgres_hitl_coordination_supported():
                db.rollback()
                raise HTTPException(503, "Durable delegated HITL requires PostgreSQL")
            dispatch_plane = "subflow_celery"
        elif _durable_run_hitl_enabled(run_system):
            dispatch_plane = "run_celery"
        else:
            dispatch_plane = "inline"
        _record_hitl_dispatch_plane(r, decision_id=decision.id, plane=dispatch_plane)
    elif delegated_celery_child and dispatch_plane != "subflow_celery":
        db.rollback()
        raise HTTPException(409, "Persisted HITL execution plane conflicts with delegation")
    elif not delegated_celery_child and dispatch_plane == "subflow_celery":
        db.rollback()
        raise HTTPException(409, "Persisted delegated HITL context is no longer active")
    elif dispatch_plane == "run_celery" and not _postgres_hitl_coordination_supported():
        db.rollback()
        raise HTTPException(503, "Durable Run HITL requires PostgreSQL")

    expected_final = "accepted" if body.action == "accept" else "rejected"
    already_resolved = decision.status == expected_final
    if not already_resolved:
        try:
            if body.action == "accept":
                accept_decision(db, decision, actor=actor, note=body.note)
            else:
                reject_decision(db, decision, actor=actor, note=body.note)
        except InvalidTransition as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc
    else:
        # Release locks and persist any newly introduced dispatch snapshot
        # before deterministic republish on an idempotent retry.
        db.commit()

    resume_task_id: Optional[str] = None
    if dispatch_plane == "subflow_celery":
        # A delegated HITL continuation must survive API process loss. The
        # message carries only the persisted child id; the worker reloads the
        # accepted Decision from the child's checkpoint.
        from app.services.run_engine.engine import schedule_subflow_hitl_resume

        try:
            resume_task_id = schedule_subflow_hitl_resume(r.id, decision_id=decision.id)
        except RuntimeError as exc:
            # The Decision is already durable. Returning 503 lets the caller
            # retry the same action, which republishes the deterministic task
            # id instead of falling back to an in-process continuation.
            raise HTTPException(503, "Delegated HITL resume dispatch is ambiguous") from exc
    elif dispatch_plane == "run_celery":
        # Ordinary HITL uses a durable deterministic Celery task as well. An
        # idempotent HTTP retry republishes safely after an ambiguous ACK; the
        # worker's PostgreSQL lease prevents two messages from running two
        # walkers concurrently.
        from app.services.run_engine.engine import schedule_run_hitl_resume

        try:
            resume_task_id = schedule_run_hitl_resume(r.id, decision_id=decision.id)
        except RuntimeError as exc:
            raise HTTPException(503, "Run HITL resume dispatch is ambiguous") from exc
    elif not already_resolved:
        # Preserve the historical in-process path unless the explicit double
        # opt-in selected durable Celery before the Decision commit.
        background_tasks.add_task(_resume_wrapper, r.id, decision.id)
    logger.info(
        "runs.hitl: dispatched resume",
        run_id=r.id,
        decision_id=decision.id,
        action=body.action,
        canonical_run_id=r.id,
        dispatch_plane=dispatch_plane,
        celery_task_id=resume_task_id,
    )
    return {
        "id": requested_run_id,
        "status": requested_run_status,
        "decision": {
            "id": decision.id,
            "status": decision.status,
        },
        "resume_task_id": resume_task_id,
    }


# ---------------------------------------------------------------------------
# Step debugger — /runs/{id}/step
# ---------------------------------------------------------------------------
class DebugStep(BaseModel):
    action: Literal["step", "continue", "stop"]
    breakpoints: Optional[List[str]] = Field(
        default=None,
        description="Optional replacement breakpoint set applied before resume.",
    )


@router.post("/{run_id}/step")
async def step_run(
    run_id: str,
    body: DebugStep,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Advance a Run paused by the step debugger.

    Action semantics:
        * ``step``     — run until the next non-source/sink node settles.
        * ``continue`` — run until a breakpoint fires or the DAG ends.
        * ``stop``     — cancel the Run here; outcome = ``debugger_stopped``.

    Returns 409 when the Run is not currently in ``debug_pending``.
    """
    r = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    if r.status != "debug_pending":
        raise HTTPException(409, f"Run is not in debugger pause (status={r.status!r})")
    background_tasks.add_task(_step_wrapper, r.id, body.action, body.breakpoints or None)
    logger.info("runs.debug: dispatched step", run_id=r.id, action=body.action)
    return {"id": r.id, "status": r.status, "action": body.action}


def _step_wrapper(run_id: str, action: str, breakpoints: Optional[List[str]]) -> None:
    """Background shim mirroring :func:`_resume_wrapper` for step resume."""
    import asyncio

    try:
        asyncio.run(resume_run_dag_debug(run_id, action=action, breakpoints=breakpoints))
        if action == "stop":
            from app.services.run_engine.subflow_orchestration import cancel_waiting_children

            cancel_waiting_children(run_id, reason="parent_debugger_stopped")
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(resume_run_dag_debug(run_id, action=action, breakpoints=breakpoints))
    except Exception as exc:  # noqa: BLE001
        logger.exception("runs.debug: step failed", run_id=run_id, action=action, error=str(exc))


# ---------------------------------------------------------------------------
# Live SSE stream — /runs/{id}/stream
# ---------------------------------------------------------------------------
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _sse_format(event: str, payload: Dict[str, Any]) -> str:
    """Serialize one payload as a single SSE frame."""
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


async def _run_event_stream(
    run_id: str, request: Request, workspace_id: Optional[str]
) -> AsyncIterator[str]:
    """Yield SSE frames for a single Run.

    1. Subscribe to the live bus *before* touching the DB so any event
       emitted by the walker during the replay phase lands in our queue.
    2. Replay every checkpoint already persisted, remembering their
       timestamps so we can dedupe them against the buffered live events.
    3. Emit a ``snapshot`` meta event carrying the current outcome so
       the UI can rebuild state without a second HTTP round-trip.
    4. Forward live events until the bus closes, the Run reaches a
       terminal state, or the HTTP client disconnects.
    """
    subscriber = event_bus.subscribe(run_id)
    replayed_ts: set[str] = set()
    try:
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.id == run_id).first()
            if not run or (workspace_id and run.workspace_id != workspace_id):
                yield _sse_format("error", {"code": "not_found", "run_id": run_id})
                return

            checkpoints = list(run.checkpoints or [])
            for cp in checkpoints:
                ts = cp.get("t")
                if isinstance(ts, str):
                    replayed_ts.add(ts)
                public_cp = cp
                if (
                    run.status == "hitl_pending"
                    and cp.get("kind") == "hitl_pause"
                    and cp.get("membrane_egress") is True
                ):
                    public_cp = {key: value for key, value in cp.items() if key != "state"}
                    public_cp["result_held"] = True
                yield _sse_format(public_cp.get("kind", "checkpoint"), public_cp)

            yield _sse_format(
                "snapshot",
                {
                    "status": run.status,
                    "outcome": {
                        "decision": run.decision,
                        "confidence": run.confidence,
                        "value_estimated": run.value_estimated,
                        "cost_internal": run.cost_internal,
                        "efficiency": run.efficiency,
                    },
                    "checkpoints_emitted": len(checkpoints),
                },
            )

            if run.status in _TERMINAL_STATUSES or run.status in (
                "hitl_pending",
                "debug_pending",
                "waiting_subflows",
            ):
                yield _sse_format("close", {"reason": "run_not_live", "status": run.status})
                return
        finally:
            db.close()

        consumer_task: Optional[asyncio.Task[Optional[Dict[str, Any]]]] = None
        while True:
            if await request.is_disconnected():
                return
            if consumer_task is None:
                consumer_task = asyncio.create_task(subscriber.next_event())
            done, _ = await asyncio.wait(
                {consumer_task}, timeout=15.0, return_when=asyncio.FIRST_COMPLETED
            )
            if consumer_task in done:
                event = consumer_task.result()
                consumer_task = None
                if event is None:
                    # Bus closed cleanly.
                    break
                ts = event.get("t")
                if isinstance(ts, str) and ts in replayed_ts:
                    # This event landed during replay and is already on
                    # the wire via the checkpoint replay loop.
                    continue
                yield _sse_format(event.get("kind", "event"), event)
                if event.get("kind") in ("run_end", "hitl_pause", "debug_pause", "subflow_wait"):
                    break
            else:
                # 15s tick with no events. Two responsibilities here:
                #   1. Keep the connection warm so proxies (Nginx) don't
                #      close idle streams.
                #   2. Short-circuit when the Run finished through a
                #      path that bypasses the live bus (e.g. sequential
                #      walker that doesn't publish events).
                db = SessionLocal()
                try:
                    status = db.query(Run.status).filter(Run.id == run_id).scalar()
                finally:
                    db.close()
                if status in _TERMINAL_STATUSES or status in (
                    "hitl_pending",
                    "debug_pending",
                    "waiting_subflows",
                ):
                    yield _sse_format("close", {"reason": "polled_terminal", "status": status})
                    break
                yield ": keep-alive\n\n"
        if consumer_task is not None:
            consumer_task.cancel()
    finally:
        await subscriber.aclose()
        yield _sse_format("close", {"reason": "stream_closed"})


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Server-Sent Events stream of a Run's lifecycle.

    Each frame is shaped as::

        event: <kind>
        data: <json>

    Known ``kind`` values mirror the walker checkpoints: ``run_start``,
    ``node_start``, ``node_end``, ``hitl_pause``, ``hitl_resume``,
    ``run_end``, plus two meta events the HTTP layer injects:
    ``snapshot`` (initial state dump on connect) and ``close`` (terminal
    signal so the client can unsubscribe without inspecting ``status``).
    """
    _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    return StreamingResponse(
        _run_event_stream(run_id, request, workspace.id if workspace else None),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable buffering on Nginx
        },
    )


def _resume_wrapper(run_id: str, decision_id: str) -> None:
    """Background shim so the FastAPI request returns immediately; the
    walker owns its own event loop via ``resume_run_dag``.
    """
    import asyncio

    async def _resume_and_finalize() -> None:
        summary = await resume_run_dag(run_id, decision_id=decision_id)
        # If this is a delegated child, its terminal transition atomically
        # releases (or keeps waiting) the parent fan-out. The helper is a no-op
        # for ordinary top-level Runs.
        from app.services.run_engine.subflow_orchestration import resume_parent_for_child

        await resume_parent_for_child(run_id)
        if summary.get("status") in {"completed", "failed"}:
            from app.services.chat_agentic_runtime import finalize_resumed_agentic_chat

            finalize_resumed_agentic_chat(run_id)

    try:
        asyncio.run(_resume_and_finalize())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(_resume_and_finalize())
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "runs.hitl: resume failed", run_id=run_id, decision_id=decision_id, error=str(exc)
        )


class OutcomeOverride(BaseModel):
    value: float = Field(..., description="Operator-declared business value.")
    note: Optional[str] = Field(
        default=None,
        description="Audit trail — why the auto-derivation was overridden.",
    )


@router.patch("/{run_id}/outcome")
async def override_run_outcome(
    run_id: str,
    body: OutcomeOverride,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Operator override for the Outcome's `value`. Cost, confidence and
    efficiency are re-computed against the new value; `value_source` flips
    to `operator`. The previous value is preserved in `operator_value_note`
    so the audit is lossless.
    """
    r = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    if r.status not in ("completed", "failed"):
        raise HTTPException(
            409,
            f"Run is still {r.status!r}; operator overrides require a settled run.",
        )
    apply_operator_override(r, value=body.value, note=body.note)
    db.commit()
    return _row(r)


# ---------------------------------------------------------------------------
# E1.5.2 — Replay with override
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    overrides: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Override fields for the replay. Recognised keys: "
            "`query`, `rag_pipeline_mode`, `model`, `provider`, "
            "`system_prompt`, `temperature`, `max_tokens`, `top_k`, "
            "`similarity_threshold`, `prompt_type`. Unknown keys are "
            "forwarded into `agent_preferences.custom_overrides` so the "
            "API stays stable as the orchestrator gains options."
        ),
    )
    actor: Optional[str] = Field(
        default=None,
        description="Deprecated compatibility field; the authenticated server identity is used.",
    )
    source_decision_id: Optional[str] = Field(
        default=None,
        description=(
            "When the replay was triggered from a review-queue Decision, "
            "the Decision id — captured in the audit trail so we can "
            "answer 'how many replays did the queue actually drive?'"
        ),
    )
    source_feedback_id: Optional[str] = Field(
        default=None,
        description=(
            "When the replay followed a feedback row (E1.5.1), the "
            "feedback id. Lets us correlate corrected_output against "
            "what a replay produced for the same parent."
        ),
    )


@router.post("/{run_id}/replay")
async def replay_run(
    run_id: str,
    body: ReplayRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Re-run a settled chat-style Run with operator overrides applied.

    Returns the new Run id (status is whatever the synchronous
    orchestrator pass produced — typically ``completed``). The
    front-end can then poll ``/evaluation/by-run/{new_run_id}`` to
    surface the eval delta against the parent.

    System-engine runs (DAG executions) are NOT yet supported and
    return 400 with a clear message — see ``replay_service`` docs.
    """
    from app.services.runs.replay_service import (
        ReplayError,
        replay_run_async,
    )

    parent = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )

    try:
        new_run, response_text = await replay_run_async(
            db=db,
            parent=parent,
            workspace_slug=workspace.slug,
            overrides=body.overrides or {},
            actor=_actor_label(user),
            source_decision_id=body.source_decision_id,
            source_feedback_id=body.source_feedback_id,
        )
    except ReplayError as exc:
        raise HTTPException(400, str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("runs.replay: unhandled error", run_id=run_id)
        raise HTTPException(500, f"replay failed: {exc!r}")

    new_run.initiated_by_user_id = user.id
    db.commit()

    return {
        "run_id": new_run.id,
        "parent_run_id": parent.id,
        "status": new_run.status,
        "trigger": new_run.trigger,
        "started_at": new_run.started_at.isoformat() if new_run.started_at else None,
        "completed_at": (new_run.completed_at.isoformat() if new_run.completed_at else None),
        "duration_ms": new_run.duration_ms,
        "replay_overrides": new_run.replay_overrides or {},
        "response_preview": (response_text[:500] if response_text else ""),
        "eval_pending": True,
    }


@router.get("/{run_id}/replays")
async def list_run_replays(
    run_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List runs that were replayed from this run as parent.

    Newest first. Used by the run-detail view to render a "Replays"
    sub-list and by the review queue to indicate when a Decision's
    breached run already has follow-up replays the reviewer can
    compare against.
    """
    _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )

    children = (
        db.query(Run)
        .filter(
            Run.parent_run_id == run_id,
            Run.workspace_id == workspace.id,
            Run.delegation_key.is_(None),
            Run.trigger.in_(("replay", "rerun")),
        )
        .order_by(Run.started_at.desc())
        .all()
    )
    children = [
        child
        for child in children
        if _run_is_visible(db, run=child, user=user, workspace=workspace)
    ]
    return {
        "parent_run_id": run_id,
        "items": [
            {
                **_row(r),
                "replay_overrides": r.replay_overrides or {},
                "evaluation_scores": r.evaluation_scores,
            }
            for r in children
        ],
    }


@router.post("/{run_id}/rerun")
async def rerun_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Re-execute a Run's DAG with the same input (demo-grade re-run).

    Creates a fresh Run pointing at the parent via ``parent_run_id``,
    copying the parent's ``input_ref`` and ``flow_snapshot``, then hands
    execution to the canonical run engine in the background.
    """
    parent = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )

    new_run = Run(
        id=str(uuid4()),
        workspace_id=parent.workspace_id,
        system_id=parent.system_id,
        capability_id=parent.capability_id,
        initiated_by_user_id=getattr(user, "id", None),
        input_ref=parent.input_ref or {},
        status="pending",
        started_at=datetime.utcnow(),
        trigger="rerun",
        parent_run_id=parent.id,
        flow_snapshot=parent.flow_snapshot,
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    background_tasks.add_task(schedule_run, new_run.id)
    return {
        "id": new_run.id,
        "status": new_run.status,
        "system_id": new_run.system_id,
        "trigger": new_run.trigger,
        "parent_run_id": parent.id,
    }
