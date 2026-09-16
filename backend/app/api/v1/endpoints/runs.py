"""Canonical /runs endpoints — supersede /traces.

A Run carries the Outcome block. Detail view exposes the SkillInvocation
ledger so the cockpit can drill from the Run timeline down to individual
skill calls.
"""
import asyncio
import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal, get_db
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.decisions import (
    InvalidTransition,
)
from app.services.decisions import (
    accept as accept_decision,
)
from app.services.decisions import (
    reject as reject_decision,
)
from app.services.iam.decision_plane import enforce_action
from app.services.iam.legacy_authority import (
    legacy_object_action_allowed,
    legacy_run_approval_allowed,
)
from app.services.object_perspective import (
    build_run_perspective,
    build_skill_invocation_perspective,
    projection_feature_enabled,
)
from app.services.outcome.derive import apply_operator_override
from app.services.run_access import (
    PRIVATE_CHAT_TRIGGER as _PRIVATE_CHAT_TRIGGER,
)
from app.services.run_access import (
    can_view_private_chat_runs as _can_view_private_chat_runs,
)
from app.services.run_access import (
    has_private_chat_admin_access as _has_private_chat_admin_access,
)
from app.services.run_access import is_workbench_run as _is_workbench_run
from app.services.run_access import (
    managed_agentic_run_requires_admin as _managed_agentic_run_requires_admin,
)
from app.services.run_access import (
    readable_run_page,
    readable_runs,
    readable_skill_invocations,
    skill_invocation_read_attrs,
)
from app.services.run_access import (
    run_is_visible as _run_is_visible,
)
from app.services.run_access import (
    run_read_attrs as _run_read_attrs,
)
from app.services.run_engine import schedule_run
from app.services.run_engine.dag import resume_run_dag, resume_run_dag_debug
from app.services.run_engine.debug_contract import (
    DebugContractError,
    normalize_debug_config,
)
from app.services.run_engine.events import bus as event_bus
from app.services.run_outcome_provenance import (
    baseline_run_exclusion_reason,
    record_operator_outcome_override,
    run_measurement_provenance,
)

logger = get_logger(__name__)
router = APIRouter()


def _reject_generic_workbench_reexecution(run: Run, *, operation: str) -> None:
    """Keep authoring executions on their explicit, acknowledged surfaces."""

    if not _is_workbench_run(run):
        return
    code = (
        "WORKBENCH_RUN_REPLAY_FORBIDDEN"
        if operation == "replay"
        else "WORKBENCH_RUN_RERUN_FORBIDDEN"
    )
    raise HTTPException(
        status_code=409,
        detail={
            "code": code,
            "message": (
                "Flow Workbench Runs cannot be re-executed through the generic "
                f"{operation} endpoint. Start a new acknowledged Workbench run."
            ),
            "execution_surface": run.execution_surface or run.trigger,
        },
    )


def _projection_evidence_sha256(value: Any) -> Optional[str]:
    """Return a content address without exposing the underlying runtime payload."""

    if not isinstance(value, dict | list) or not value:
        return None
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def _utc_naive_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _delegated_hitl_deadline(run: Run) -> Optional[datetime]:
    """Return the immutable delegation deadline as naïve UTC, if configured."""

    value: Any = run.delegation_deadline_at
    if value is None and isinstance(run.input_ref, dict):
        delegation = (run.input_ref.get("_delegation") or {})
        value = delegation.get("deadline_at") if isinstance(delegation, dict) else None
    return _utc_naive_datetime(value)


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


def _row(r: Run, *, db: DBSession) -> Dict[str, Any]:
    membrane_held = _membrane_egress_held(r)
    measurement_provenance = run_measurement_provenance(r, db=db)
    baseline_exclusion = baseline_run_exclusion_reason(r)
    baseline_eligible = bool(
        isinstance(measurement_provenance, dict)
        and measurement_provenance.get("source") == "runtime_auto"
        and baseline_exclusion is None
    )
    from app.services.evaluation.campaigns import suite_run_result
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
        "output_ref": r.output_ref if r.output_ref is not None else {},
        "outcome": {
            "decision": r.decision,
            "confidence": r.confidence,
            "value_estimated": r.value_estimated,
            "cost_internal": r.cost_internal,
            "revenue_allocated": r.revenue_allocated,
            "efficiency": r.efficiency,
            "value_source": getattr(r, "value_source", None) or "unset",
            "operator_value_note": getattr(r, "operator_value_note", None),
            "measurement_provenance": measurement_provenance,
            "baseline_eligible": baseline_eligible,
            "baseline_ineligible_reason": (
                baseline_exclusion
                or (
                    "baseline_runtime_provenance_unavailable"
                    if not baseline_eligible
                    else None
                )
            ),
        },
        "retries": r.retries,
        "error": r.error,
        "checkpoints": checkpoints,
        "test_result": suite_run_result(r),
        "waiting_subflows": r.waiting_subflows or {},
        "result_held": membrane_held,
        # Additive, secret-free integrity evidence used by the protected Lot 7
        # canary. The raw flow stays in the projection service's allowlisted
        # view; this endpoint exposes only its exact content address.
        "flow_evidence": {
            "flow_version_id": r.flow_version_id,
            "flow_snapshot_sha256": _projection_evidence_sha256(r.flow_snapshot),
            "execution_snapshot_at": (
                r.input_ref.get("execution", {}).get("snapshot_at")
                if isinstance(r.input_ref, dict)
                and isinstance(r.input_ref.get("execution"), dict)
                else None
            ),
            "runtime_revision": (
                r.input_ref.get("execution", {}).get("runtime_revision")
                if isinstance(r.input_ref, dict)
                and isinstance(r.input_ref.get("execution"), dict)
                else None
            ),
        },
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


def _invocation(
    i: SkillInvocation,
    *,
    redact_io: bool = False,
    include_projection_evidence: bool = False,
) -> Dict[str, Any]:
    payload = {
        "id": i.id,
        "skill_slug": i.skill_slug,
        "status": i.status,
        "started_at": i.started_at.isoformat() if i.started_at else None,
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        "latency_ms": i.latency_ms,
        "cost": i.cost,
        "input_ref": {} if redact_io else i.input_ref or {},
        "output_ref": (
            {}
            if redact_io
            else (i.output_ref if i.output_ref is not None else {})
        ),
        "metrics": i.metrics or {},
        "trace": i.trace or {},
        "error": i.error,
        "execution_evidence": {
            "resolution": (
                i.execution_snapshot.get("resolution")
                if isinstance(i.execution_snapshot, dict)
                else None
            ),
            "execution_snapshot_sha256": _projection_evidence_sha256(
                i.execution_snapshot
            ),
        },
    }
    if include_projection_evidence:
        payload.update(
            {
                "cost_measured": i.cost_measured,
                "execution_snapshot": i.execution_snapshot or {},
            }
        )
    return payload


@router.get("")
async def list_runs(
    golden_batch_id: Optional[str] = None,
    system_id: Optional[str] = None,
    capability_id: Optional[str] = None,
    status: Optional[str] = None,
    origin: Optional[list[str]] = Query(None),
    limit: int = 100,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    q = db.query(Run).filter(Run.workspace_id == workspace.id)
    if golden_batch_id:
        q = q.filter(Run.execution_surface == "golden_preview",
            Run.input_ref["execution"]["golden_batch_id"].as_string() == golden_batch_id)
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
    if origin:
        # Binding invoke tags input_ref._ingress.adapter.origin. No JSON index.
        origins = [item for item in origin if item]
        origin_col = Run.input_ref["_ingress"]["adapter"]["origin"].as_string()
        if len(origins) == 1:
            q = q.filter(origin_col == origins[0])
        elif origins:
            q = q.filter(origin_col.in_(origins))
    rows = readable_run_page(
        db,
        query=q.order_by(Run.started_at.desc()),
        limit=limit,
        user=user,
        workspace=workspace,
    )
    return {"runs": [_row(r, db=db) for r in rows]}


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
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="read",
        legacy_allowed=True,
        resource_attrs=_run_read_attrs(r),
    )
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == r.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    invocations = readable_skill_invocations(
        db,
        invocations=invocations,
        run=r,
        user=user,
        workspace=workspace,
    )
    include_invocation_evidence = projection_feature_enabled(
        db,
        workspace,
        "skill_invocation",
    )
    payload: Dict[str, Any] = {
        **_row(r, db=db),
        "invocations": [
            _invocation(
                i,
                redact_io=_membrane_egress_held(r),
                include_projection_evidence=include_invocation_evidence,
            )
            for i in invocations
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
        expires_at = None
        expiry_action = None
        if decision is not None:
            expires_at = decision.expires_at.isoformat() if decision.expires_at else None
            expiry_action = decision.expiry_action
        if expires_at is None:
            expires_at = pending_cp.get("expires_at")
        if expiry_action is None:
            expiry_action = pending_cp.get("expiry_action")

        seconds_remaining = None
        if expires_at:
            try:
                from datetime import datetime as _dt

                exp = _dt.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if exp.tzinfo is not None:
                    exp = exp.replace(tzinfo=None)
                seconds_remaining = max(0, int((exp - _dt.utcnow()).total_seconds()))
            except (TypeError, ValueError):
                seconds_remaining = None

        inbox_count = 0
        memory_hint = None
        try:
            from app.services.run_engine.inbox import (  # noqa: WPS433
                inbox_count_for_run,
                load_memory_for_run,
                memory_pool_payload,
            )

            inbox_count = inbox_count_for_run(db, r.id)
            mem = load_memory_for_run(db, r)
            mem_payload = memory_pool_payload(mem)
            if mem_payload:
                memory_hint = {
                    "correlation_key": mem_payload.get("correlation_key"),
                    "version": mem_payload.get("version"),
                    "event_count": mem_payload.get("event_count"),
                    "last_event_kind": mem_payload.get("last_event_kind"),
                    "updated_at": mem_payload.get("updated_at"),
                }
        except Exception:  # noqa: BLE001 — cockpit enrichment must not break get_run
            pass

        rationale = decision.rationale if decision and isinstance(decision.rationale, dict) else {}
        payload["hitl"] = {
            "node_id": pending_cp.get("node_id"),
            "prompt": pending_cp.get("prompt") or rationale.get("prompt"),
            "prompt_kind": rationale.get("prompt_kind"),
            "decision_id": decision_id,
            "decision_status": decision.status if decision else None,
            "decision_title": decision.title if decision else None,
            "expires_at": expires_at,
            "expiry_action": expiry_action,
            "seconds_remaining": seconds_remaining,
            "inbox_count": inbox_count,
            "memory": memory_hint,
            "upstream": rationale.get("upstream"),
            "correlation_key": pending_cp.get("correlation_key")
            or rationale.get("correlation_key"),
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


@router.get("/{run_id}/perspective")
async def get_run_perspective(
    run_id: str,
    lens: Literal["build", "operate", "steer", "govern"],
    window: Literal["7d", "30d", "90d"] = "30d",
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if not projection_feature_enabled(db, workspace, "run"):
        raise HTTPException(
            410,
            {"code": "OBJECT_PROJECTION_REVOKED", "object_type": "run"},
        )
    run = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="read",
        # ``_visible_run_or_404`` is the legacy authority and already hides
        # cross-workspace/private Runs. The v2 plane only takes authority for
        # an explicit enforce rollout.
        legacy_allowed=True,
        resource_attrs=_run_read_attrs(run),
    )
    return build_run_perspective(
        db,
        workspace=workspace,
        user=user,
        run=run,
        lens=lens,
        window=window,
    )


@router.get("/{run_id}/invocations/{invocation_id}")
async def get_skill_invocation(
    run_id: str,
    invocation_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Resolve the runtime invocation, never the catalog Skill."""

    if not projection_feature_enabled(db, workspace, "skill_invocation"):
        raise HTTPException(404, "Skill invocation not found")
    run = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="read",
        legacy_allowed=True,
        resource_attrs=_run_read_attrs(run),
    )
    invocation = db.query(SkillInvocation).filter(
        SkillInvocation.id == invocation_id,
        SkillInvocation.run_id == run.id,
    ).first()
    if invocation is None:
        raise HTTPException(404, "Skill invocation not found")
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="skill_invocation",
        action="read",
        legacy_allowed=True,
        resource_attrs=skill_invocation_read_attrs(invocation, run),
    )
    return {
        **_invocation(
            invocation,
            redact_io=_membrane_egress_held(run),
            include_projection_evidence=True,
        ),
        "run_id": run.id,
        "system_id": run.system_id,
        "capability_id": run.capability_id,
    }


@router.get("/{run_id}/invocations/{invocation_id}/perspective")
async def get_skill_invocation_perspective(
    run_id: str,
    invocation_id: str,
    lens: Literal["build", "operate", "steer", "govern"],
    window: Literal["7d", "30d", "90d"] = "30d",
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if not projection_feature_enabled(db, workspace, "skill_invocation"):
        raise HTTPException(
            410,
            {
                "code": "OBJECT_PROJECTION_REVOKED",
                "object_type": "skill_invocation",
            },
        )
    run = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="read",
        legacy_allowed=True,
        resource_attrs=_run_read_attrs(run),
    )
    invocation = db.query(SkillInvocation).filter(
        SkillInvocation.id == invocation_id,
        SkillInvocation.run_id == run.id,
    ).first()
    if invocation is None:
        raise HTTPException(404, "Skill invocation perspective not found")
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="skill_invocation",
        action="read",
        # The parent Run has already passed the complete legacy visibility
        # boundary above; an invocation can never broaden that visibility.
        legacy_allowed=True,
        resource_attrs=skill_invocation_read_attrs(invocation, run),
    )
    return build_skill_invocation_perspective(
        db,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        lens=lens,
        window=window,
    )


class HitlResolve(BaseModel):
    action: Literal["accept", "reject"]
    actor: Optional[str] = Field(
        default=None,
        description="Deprecated compatibility field; the authenticated server identity is used.",
    )
    note: Optional[str] = Field(default=None, description="Audit trail note.")


class SteerBody(BaseModel):
    op: Literal["set_tier", "set_allowlist", "inject_note", "escalate"]
    privilege_tier: Optional[str] = None
    skill_allowlist: Optional[List[str]] = None
    note: Optional[str] = None
    escalate_to: Optional[str] = None


def _actor_label(user: User) -> str:
    """Return the authenticated identity written to the Decision audit trail."""
    return (
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or getattr(user, "keycloak_sub", None)
        or str(user.id)
    )


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


def _legacy_hitl_authorized(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    paused_run: Run,
    decision_target: Run,
) -> bool:
    """Return the pre-v2 initiator/admin authorization decision.

    Migration-059's production Agentic System is deliberately stricter: only
    organization admins and workspace admin/owner roles may resolve its HITL
    gates, even when they initiated the Run themselves.

    Corrupt or cross-workspace lineage remains a hard structural failure. The
    managed-System admin floor is enforced separately at the endpoint before
    Authorization v2; this legacy result is therefore only the role/action
    decision inside that structural boundary.
    """
    affected_runs: Dict[str, Run] = {}
    for candidate in (paused_run, decision_target):
        lineage = _run_lineage(db, run=candidate, workspace_id=workspace.id)
        if lineage is None:
            raise HTTPException(403, "Run lineage is outside the current workspace")
        affected_runs.update({row.id: row for row in lineage})

    return legacy_run_approval_allowed(
        db,
        user=user,
        workspace=workspace,
        runs=affected_runs.values(),
    )


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

    # Migration-059's managed Agentic System keeps an admin-only structural
    # boundary. Authorization v2 may further restrict this action, but an
    # ``enforce`` policy must never widen the managed HITL gate to reviewers.
    # Check both the surfaced pause and the canonical Decision target so a
    # parent subflow cannot hide a managed child.
    managed_requires_admin = any(
        _managed_agentic_run_requires_admin(
            db,
            run=candidate,
            workspace=workspace,
        )
        for candidate in (r, decision_target)
    )
    if managed_requires_admin and not _has_private_chat_admin_access(
        db,
        user=user,
        workspace=workspace,
    ):
        db.rollback()
        raise HTTPException(403, "Managed Run HITL requires workspace admin")

    legacy_allowed = _legacy_hitl_authorized(
        db,
        user=user,
        workspace=workspace,
        paused_run=r,
        decision_target=decision_target,
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="approve",
        legacy_allowed=legacy_allowed,
        resource_attrs={
            "run_id": r.id,
            "system_id": r.system_id,
            "capability_id": r.capability_id,
            "decision_id": decision.id,
            "owner_user_id": decision_target.initiated_by_user_id,
        },
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
    if delegated_celery_child:
        deadline = _delegated_hitl_deadline(r)
        resolved_before_deadline = bool(
            deadline is not None
            and decision.status in {"accepted", "applied", "rejected"}
            and _utc_naive_datetime(decision.approved_at) is not None
            and _utc_naive_datetime(decision.approved_at) <= deadline
        )
        if deadline is not None and datetime.utcnow() > deadline and not resolved_before_deadline:
            db.rollback()
            raise HTTPException(409, "Delegated HITL deadline has expired")
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
    dispatch_event = None
    if not already_resolved:
        try:
            if body.action == "accept":
                accept_decision(db, decision, actor=actor, note=body.note, commit=False)
            else:
                reject_decision(db, decision, actor=actor, note=body.note, commit=False)
        except InvalidTransition as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc
        decision.human_confirmed_by = user.id
        decision.human_confirmed_at = decision.approved_at
        if delegated_celery_child and deadline is not None:
            approved_at = _utc_naive_datetime(decision.approved_at)
            if approved_at is None or approved_at > deadline:
                # The state machine timestamps the durable transition. Check
                # that value as well as the pre-transition clock so a request
                # waiting on locks cannot cross the deadline unnoticed.
                db.rollback()
                raise HTTPException(409, "Delegated HITL deadline has expired")

    if dispatch_plane in {"subflow_celery", "run_celery"}:
        from app.services.run_engine.dispatch_outbox import (
            RUN_HITL_RESUME,
            SUBFLOW_HITL_RESUME,
            enqueue_dispatch,
        )

        dispatch_event = enqueue_dispatch(
            db,
            event_type=(
                SUBFLOW_HITL_RESUME
                if dispatch_plane == "subflow_celery"
                else RUN_HITL_RESUME
            ),
            workspace_id=str(workspace.id),
            run_id=r.id,
            decision_id=decision.id,
        )
    # Decision, immutable dispatch-plane checkpoint and outbox event form one
    # transaction. A lost API process can therefore never leave a durable
    # approval without a durable continuation request.
    db.commit()

    resume_task_id: Optional[str] = dispatch_event.task_id if dispatch_event else None
    if dispatch_event is not None:
        from app.services.run_engine.dispatch_outbox import reconcile_dispatch_outbox

        try:
            reconcile_dispatch_outbox(
                batch_size=50,
                lease_seconds=settings.p4_maintenance_lease_seconds,
            )
        except Exception as exc:  # persisted outbox remains authoritative
            logger.warning(
                "runs.hitl: immediate outbox reconciliation deferred",
                run_id=r.id,
                decision_id=decision.id,
                error_type=type(exc).__name__,
            )
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
    model_config = ConfigDict(extra="forbid")

    action: Literal["step", "continue", "stop"]
    breakpoints: Optional[List[str]] = Field(
        default=None,
        description="Optional replacement breakpoint set applied before resume.",
    )

    @field_validator("breakpoints")
    @classmethod
    def _validate_breakpoints(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        try:
            normalized = normalize_debug_config(
                {"mode": "step", "breakpoints": value}
            )
        except DebugContractError as exc:
            raise ValueError(exc.message) from exc
        return list(normalized["breakpoints"])


@router.post("/{run_id}/steer")
def steer_run(
    run_id: str,
    body: SteerBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Redirect an in-flight AgentLoop without starting a new Run."""

    from app.services.run_engine.agent_loop import (
        flow_has_agent_loop,
        persist_steer,
    )

    run = _visible_run_or_404(db, run_id=run_id, user=user, workspace=workspace)
    if run.status not in {"running", "hitl_pending"}:
        raise HTTPException(409, f"Run cannot be steered (status={run.status!r})")
    flow = run.flow_snapshot if isinstance(run.flow_snapshot, dict) else {}
    if not flow:
        system = db.query(System).filter(System.id == run.system_id).first()
        flow = (system.flow_definition if system else {}) or {}
    if not flow_has_agent_loop(flow):
        raise HTTPException(409, "Run has no agent_loop to steer")
    updated = persist_steer(
        run,
        op=body.op,
        privilege_tier=body.privilege_tier,
        skill_allowlist=body.skill_allowlist,
        note=body.note,
        escalate_to=body.escalate_to,
    )
    checkpoints = list(run.checkpoints or [])
    checkpoints.append(
        {
            "kind": "steer",
            "t": datetime.utcnow().isoformat(),
            "op": body.op,
            "steer": updated,
        }
    )
    run.checkpoints = checkpoints
    db.commit()
    return {"id": run.id, "status": run.status, "steer": updated}


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
    system = (
        db.query(System)
        .filter(
            System.id == r.system_id,
            System.workspace_id == workspace.id,
        )
        .one_or_none()
    )
    if system is None:
        raise HTTPException(409, detail={"code": "DEBUG_SYSTEM_UNAVAILABLE"})
    from app.api.v1.endpoints.systems import _enforce_system_run_authority

    _enforce_system_run_authority(
        db,
        user=user,
        workspace=workspace,
        system=system,
        execution_source="run_debug_resume_api",
    )
    if r.status != "debug_pending":
        raise HTTPException(409, f"Run is not in debugger pause (status={r.status!r})")
    background_tasks.add_task(_step_wrapper, r.id, body.action, body.breakpoints)
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
    run_id: str, request: Request, workspace_id: Optional[str], user_id: Optional[str] = None
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
    persisted_cursor = 0
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

            persisted_cursor = len(checkpoints)
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
                {consumer_task}, timeout=1.0, return_when=asyncio.FIRST_COMPLETED
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
                if isinstance(ts, str):
                    replayed_ts.add(ts)
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
                    current = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace_id).first()
                    if current is None:
                        return
                    if user_id:
                        current_user = db.query(User).filter(User.id == user_id).first()
                        current_workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
                        if current_user is None or current_workspace is None or not readable_runs(db, runs=[current], user=current_user, workspace=current_workspace):
                            yield _sse_format("close", {"reason": "access_unavailable"})
                            return
                    status = current.status
                    checkpoints = list(current.checkpoints or [])
                    for cp in checkpoints[persisted_cursor:]:
                        ts = cp.get("t")
                        if isinstance(ts, str) and ts in replayed_ts:
                            continue
                        if isinstance(ts, str):
                            replayed_ts.add(ts)
                        public_cp = cp
                        if status == "hitl_pending" and cp.get("kind") == "hitl_pause" and cp.get("membrane_egress") is True:
                            public_cp = {key: value for key, value in cp.items() if key != "state"}
                            public_cp["result_held"] = True
                        yield _sse_format(public_cp.get("kind", "checkpoint"), public_cp)
                    persisted_cursor = len(checkpoints)
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
    run = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="read",
        legacy_allowed=True,
        resource_attrs=_run_read_attrs(run),
    )
    return StreamingResponse(
        _run_event_stream(run_id, request, workspace.id if workspace else None, user.id),
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
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="admin",
        legacy_allowed=legacy_object_action_allowed(
            db,
            user=user,
            workspace=workspace,
            resource_kind="run",
            action="admin",
        ),
        resource_attrs=_run_read_attrs(r),
    )
    # Serialize override histories and replace any stale identity-map state
    # before deriving the value and its mandatory audit receipt.
    r = (
        db.query(Run)
        .filter(Run.id == run_id, Run.workspace_id == workspace.id)
        .populate_existing()
        .with_for_update(of=Run)
        .one_or_none()
    )
    if r is None:
        raise HTTPException(404, "Run not found")
    if r.status not in ("completed", "failed"):
        raise HTTPException(
            409,
            f"Run is still {r.status!r}; operator overrides require a settled run.",
        )
    try:
        previous_value = r.value_estimated
        apply_operator_override(r, value=body.value, note=body.note)
        record_operator_outcome_override(
            r,
            db=db,
            actor=_actor_label(user),
            previous_value=previous_value,
            note=body.note,
        )
        db.commit()
    except Exception:
        # Outcome, embedded receipt and exact AuditLog are one atomic write.
        db.rollback()
        raise
    db.refresh(r)
    return _row(r, db=db)


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
    _reject_generic_workbench_reexecution(parent, operation="replay")
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="engine.run",
        legacy_allowed=True,
        resource_attrs={
            "system_id": parent.system_id,
            "capability_id": parent.capability_id,
            "run_id": parent.id,
            "owner_user_id": parent.initiated_by_user_id,
        },
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
    parent = _visible_run_or_404(
        db,
        run_id=run_id,
        user=user,
        workspace=workspace,
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="read",
        legacy_allowed=True,
        resource_attrs=_run_read_attrs(parent),
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
    children = readable_runs(
        db,
        runs=children,
        user=user,
        workspace=workspace,
    )
    return {
        "parent_run_id": run_id,
        "items": [
            {
                **_row(r, db=db),
                "replay_overrides": r.replay_overrides or {},
                "evaluation_scores": {k: v for k, v in (r.evaluation_scores or {}).items() if k not in {"metadata", "claim_audit"}},
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
    _reject_generic_workbench_reexecution(parent, operation="rerun")
    system = (
        db.query(System)
        .filter(
            System.id == parent.system_id,
            System.workspace_id == workspace.id,
        )
        .one_or_none()
    )
    if system is None:
        raise HTTPException(409, detail={"code": "RERUN_SYSTEM_UNAVAILABLE"})
    # Reuse the canonical System run boundary so the managed-Agentic admin
    # floor, IAM decision and membrane authority cannot be bypassed through a
    # historical Run URL.
    from app.api.v1.endpoints.systems import _enforce_system_run_authority

    _enforce_system_run_authority(
        db,
        user=user,
        workspace=workspace,
        system=system,
        execution_source="run_rerun_api",
    )

    new_run = Run(
        id=str(uuid4()),
        workspace_id=parent.workspace_id,
        system_id=parent.system_id,
        capability_id=parent.capability_id,
        initiated_by_user_id=getattr(user, "id", None),
        input_ref=copy.deepcopy(parent.input_ref or {}),
        status="pending",
        started_at=datetime.utcnow(),
        trigger="rerun",
        parent_run_id=parent.id,
        flow_snapshot=copy.deepcopy(parent.flow_snapshot),
        flow_version_id=parent.flow_version_id,
        published_flow_version_id=parent.published_flow_version_id,
        flow_sha256=parent.flow_sha256,
        execution_contract=copy.deepcopy(parent.execution_contract),
        execution_surface=parent.execution_surface,
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
