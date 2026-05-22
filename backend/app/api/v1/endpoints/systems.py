"""Canonical /systems endpoints — supersede /agents.

A System is the deployable composition (Objective + Capability + Context +
Skills + Policies). `POST /systems/{id}/runs` enqueues a Run; the actual
execution loop lives in `app.services.run_engine`.

Vague E / E3.1 — versioning + DAG validation:

- ``PATCH /systems/{id}`` is now validated before it touches the DB.
  Structural errors (cycle, orphan, unreachable node, decision without
  branches, …) are returned as HTTP 400 with the same shape the editor
  displays (``FlowValidationIssue``). Warnings (task without skill,
  fork/join imbalance, …) pass through but are echoed in the response.
- Every change to ``flow_definition`` spawns a new ``SystemVersion``
  row. Rolling window of 500 per system (see
  ``services.chains.version_service``).
- New routes ``/systems/{id}/versions`` + ``/rollback`` expose the
  history and restore flow.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.chains import dag_validator, export_service, version_service
from app.services.run_engine import schedule_run

router = APIRouter()


# ---------------- Pydantic ----------------
class SystemCreate(BaseModel):
    name: str
    objective: str = ""
    capability_id: Optional[str] = None
    skill_ids: List[str] = []
    flow_definition: Dict[str, Any] = {}
    settings: Dict[str, Any] = {}
    execution_mode: str = "real_time_decision"
    execution_profile: Optional[Dict[str, Any]] = None
    coordination_pattern: str = "single_agent"
    control_policy_id: Optional[str] = None
    adaptive_policy_id: Optional[str] = None
    context_id: Optional[str] = None
    status: str = "draft"
    default_prompt_type: Optional[str] = None
    default_model: Optional[str] = None
    retrieval_mode_default: Optional[str] = None


class SystemUpdate(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    capability_id: Optional[str] = None
    skill_ids: Optional[List[str]] = None
    flow_definition: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None
    execution_mode: Optional[str] = None
    execution_profile: Optional[Dict[str, Any]] = None
    coordination_pattern: Optional[str] = None
    control_policy_id: Optional[str] = None
    adaptive_policy_id: Optional[str] = None
    context_id: Optional[str] = None
    status: Optional[str] = None
    default_prompt_type: Optional[str] = None
    default_model: Optional[str] = None
    retrieval_mode_default: Optional[str] = None


class RunCreate(BaseModel):
    input_ref: Dict[str, Any] = {}
    trigger: str = "manual"


class SystemUpdateOptions(BaseModel):
    """Optional controls piggy-backing on the PATCH body.

    Kept separate from :class:`SystemUpdate` so clients that don't care
    about versioning can keep their existing payload shape. The editor
    sends ``version_message`` to attach a changelog note; tests and
    background jobs can set ``skip_validation`` to bypass the DAG gate
    when they know the payload is already trusted.
    """

    version_message: Optional[str] = Field(
        default=None,
        description="Optional changelog note saved alongside the new version.",
        max_length=2000,
    )
    skip_validation: bool = False


class RollbackBody(BaseModel):
    message: Optional[str] = Field(
        default=None,
        description="Optional note attached to the rollback version.",
        max_length=2000,
    )


def _actor_display_name(user: User) -> str:
    """Pick a stable, human-readable actor label for audit/version rows.

    Prefer ``email`` then ``username`` then ``keycloak_sub``, falling
    back to the DB id so the field is never empty. Matches the spirit
    of ``emit_audit_event.actor`` in the SharePoint endpoints.
    """
    return (
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or getattr(user, "keycloak_sub", None)
        or getattr(user, "id", "demo-user")
    )


# ---------------- Helpers ----------------
def _serialize(s: System) -> Dict[str, Any]:
    return {
        "id": s.id,
        "workspace_id": s.workspace_id,
        "name": s.name,
        "objective": s.objective,
        "capability_id": s.capability_id,
        "skill_ids": s.skill_ids or [],
        "flow_definition": s.flow_definition or {},
        "settings": getattr(s, "settings", None) or {},
        "execution_mode": s.execution_mode,
        "execution_profile": getattr(s, "execution_profile", None) or {},
        "coordination_pattern": s.coordination_pattern,
        "control_policy_id": s.control_policy_id,
        "adaptive_policy_id": s.adaptive_policy_id,
        "context_id": s.context_id,
        "status": s.status,
        "default_prompt_type": getattr(s, "default_prompt_type", None),
        "default_model": getattr(s, "default_model", None),
        "retrieval_mode_default": getattr(s, "retrieval_mode_default", None),
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


# ---------------- CRUD ----------------
@router.get("")
async def list_systems(
    status: Optional[str] = None,
    limit: int = 100,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    q = db.query(System).filter(System.workspace_id == workspace.id)
    if status:
        q = q.filter(System.status == status)
    rows = q.order_by(System.updated_at.desc()).limit(limit).all()
    return {"systems": [_serialize(s) for s in rows]}


@router.post("")
async def create_system(
    body: SystemCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    # Validate the initial flow_definition the same way PATCH does so
    # a chain can't be born invalid. Empty flow_definition is valid
    # (draft) — the validator treats no-nodes as zero issues.
    issues = dag_validator.validate_flow(body.flow_definition or {})
    if dag_validator.has_errors(issues):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "flow_invalid",
                "message": "Flow definition has structural errors.",
                "issues": dag_validator.issues_to_payload(issues),
            },
        )

    actor = _actor_display_name(user)
    s = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=body.name,
        objective=body.objective,
        capability_id=body.capability_id,
        skill_ids=body.skill_ids,
        flow_definition=body.flow_definition,
        settings=body.settings or {},
        execution_mode=body.execution_mode,
        execution_profile=body.execution_profile or None,
        coordination_pattern=body.coordination_pattern,
        control_policy_id=body.control_policy_id,
        adaptive_policy_id=body.adaptive_policy_id,
        context_id=body.context_id,
        status=body.status,
        created_by=actor,
        default_prompt_type=body.default_prompt_type,
        default_model=body.default_model,
        retrieval_mode_default=body.retrieval_mode_default or "auto",
    )
    db.add(s)
    db.flush()

    # Seed v1 for every new chain so the history is never empty — the
    # UI's "Versions" panel always has at least the starting point to
    # compare against or roll back to.
    version_service.record_new_version(
        db=db,
        system=s,
        flow_definition=body.flow_definition or {},
        created_by=actor,
        message="Initial version",
    )

    db.commit()
    db.refresh(s)
    payload = _serialize(s)
    payload["validation_warnings"] = dag_validator.issues_to_payload(
        [i for i in issues if i.level == "warn"]
    )
    return payload


@router.get("/{system_id}")
async def get_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    return _serialize(s)


@router.patch("/{system_id}")
async def update_system(
    system_id: str,
    body: SystemUpdate,
    options: SystemUpdateOptions = Depends(),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .first()
    )
    if not s:
        raise HTTPException(404, "System not found")

    updates = body.model_dump(exclude_unset=True)
    new_flow = updates.get("flow_definition") if "flow_definition" in updates else None

    issues: list = []
    if new_flow is not None and not options.skip_validation:
        issues = dag_validator.validate_flow(new_flow)
        if dag_validator.has_errors(issues):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "flow_invalid",
                    "message": "Flow definition has structural errors.",
                    "issues": dag_validator.issues_to_payload(issues),
                },
            )

    for k, v in updates.items():
        setattr(s, k, v)

    created_version = None
    if new_flow is not None:
        created_version = version_service.record_new_version(
            db=db,
            system=s,
            flow_definition=new_flow,
            created_by=_actor_display_name(user),
            message=options.version_message,
        )

    db.commit()
    db.refresh(s)
    payload = _serialize(s)
    if issues:
        payload["validation_warnings"] = dag_validator.issues_to_payload(
            [i for i in issues if i.level == "warn"]
        )
    if created_version is not None:
        payload["new_version"] = version_service.serialize_version_summary(created_version)
    return payload


@router.delete("/{system_id}", status_code=204)
async def delete_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    db.delete(s)
    db.commit()
    return None


# ---------------- Runs ----------------
@router.post("/{system_id}/runs")
async def trigger_run(
    system_id: str,
    body: RunCreate,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")

    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=s.id,
        capability_id=s.capability_id,
        input_ref=body.input_ref,
        status="pending",
        started_at=datetime.utcnow(),
        trigger=body.trigger,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Hand the actual execution to the canonical run_engine (Phase 6).
    background_tasks.add_task(schedule_run, run.id)
    return {"id": run.id, "status": run.status, "system_id": s.id, "trigger": body.trigger}


@router.get("/{system_id}/versions")
async def list_system_versions(
    system_id: str,
    limit: int = 100,
    offset: int = 0,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Paginated history of ``flow_definition`` snapshots for a system.

    Returns summaries (no full ``flow_definition`` payload) so the
    panel can stay responsive even at the 500-row window ceiling.
    Fetch the full body with ``GET /systems/{id}/versions/{n}``.
    """
    s = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .first()
    )
    if not s:
        raise HTTPException(404, "System not found")
    rows, total = version_service.list_versions(
        db=db,
        system_id=system_id,
        workspace_id=workspace.id,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "window": None,  # filled by the client from the config endpoint if needed
        "versions": [version_service.serialize_version_summary(v) for v in rows],
    }


@router.get("/{system_id}/versions/{version_number}")
async def get_system_version(
    system_id: str,
    version_number: int,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Full version payload including ``flow_definition``. Used by the
    editor when hovering a row to preview, or when starting a
    rollback to confirm the target.
    """
    s = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .first()
    )
    if not s:
        raise HTTPException(404, "System not found")
    v = version_service.get_version(
        db=db,
        system_id=system_id,
        workspace_id=workspace.id,
        version_number=version_number,
    )
    if v is None:
        raise HTTPException(404, "Version not found (may have been purged by the rolling window).")
    return version_service.serialize_version(v)


@router.post("/{system_id}/versions/{version_number}/rollback")
async def rollback_system_version(
    system_id: str,
    version_number: int,
    body: RollbackBody = RollbackBody(),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Roll the system back to a specific version.

    Implemented as "append a new version whose ``flow_definition``
    equals the target"; we never rewrite history. Returns the
    newly created version (or the target itself if the rollback is
    a no-op because the target is already the current flow).
    """
    s = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .first()
    )
    if not s:
        raise HTTPException(404, "System not found")
    try:
        new_version = version_service.rollback_to_version(
            db=db,
            system=s,
            version_number=version_number,
            created_by=_actor_display_name(user),
            message=body.message,
        )
    except version_service.ChainVersionError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.commit()
    db.refresh(s)
    return {
        "system": _serialize(s),
        "new_version": version_service.serialize_version(new_version),
    }


# ---------------- Export / Import (Vague E / E3.4) ----------------


class SystemImportBody(BaseModel):
    """Import payload — the envelope produced by ``GET /{id}/export``.

    ``target_name`` lets the caller override the system name at import
    time (useful for cloning: "Chain X (copy)"). Validation and version
    seeding mirror ``POST /systems``.
    """

    envelope: Dict[str, Any]
    target_name: Optional[str] = None


@router.get("/{system_id}/export")
async def export_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Serialize ``system_id`` into a portable JSON envelope.

    The payload strips DB-scoped identifiers (``id``, ``workspace_id``,
    audit metadata) and replaces per-node ``skill_id`` with ``skill_slug``
    so the receiver can rebind against its own catalog.
    """
    s = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .first()
    )
    if not s:
        raise HTTPException(404, "System not found")
    actor = _actor_display_name(user)
    payload = export_service.serialize_for_export(
        db=db, system=s, exported_by=actor
    )
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="chain.export",
        actor=actor,
        details={"system_id": s.id, "system_name": s.name},
        db=db,
    )
    return payload


@router.post("/import")
async def import_system(
    body: SystemImportBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a new System from an exported envelope.

    The flow is validated through the same DAG validator as PATCH, so
    a malformed envelope cannot sneak a broken chain into the
    workspace. Skill slugs that don't resolve in the target workspace
    are reported under ``unresolved_skills`` in the response — the
    import still succeeds, the operator rebinds manually afterwards.
    """
    try:
        create_kwargs, report = export_service.prepare_import(
            db=db,
            envelope=body.envelope,
            workspace_id=workspace.id,
            target_name=body.target_name,
        )
    except export_service.ChainExportError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_envelope", "message": str(exc)},
        ) from exc

    flow = create_kwargs.get("flow_definition") or {}
    issues = dag_validator.validate_flow(flow)
    if dag_validator.has_errors(issues):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "flow_invalid",
                "message": "Imported flow has structural errors.",
                "issues": dag_validator.issues_to_payload(issues),
            },
        )

    actor = _actor_display_name(user)
    s = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=create_kwargs["name"],
        objective=create_kwargs["objective"],
        skill_ids=create_kwargs["skill_ids"],
        flow_definition=flow,
        execution_mode=create_kwargs["execution_mode"],
        execution_profile=create_kwargs["execution_profile"] or None,
        coordination_pattern=create_kwargs["coordination_pattern"],
        status="draft",
        created_by=actor,
        default_prompt_type=create_kwargs["default_prompt_type"],
        default_model=create_kwargs["default_model"],
        retrieval_mode_default=create_kwargs["retrieval_mode_default"] or "auto",
    )
    db.add(s)
    db.flush()
    version_service.record_new_version(
        db=db,
        system=s,
        flow_definition=flow,
        created_by=actor,
        message="Imported from envelope",
    )
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="chain.import",
        actor=actor,
        details={
            "system_id": s.id,
            "source": report.get("source", {}),
            "unresolved_skills": report.get("unresolved_skills", []),
            "task_rebind_count": len(report.get("task_node_rebinds", [])),
        },
        db=db,
    )
    db.commit()
    db.refresh(s)
    payload = _serialize(s)
    payload["import_report"] = report
    payload["validation_warnings"] = dag_validator.issues_to_payload(
        [i for i in issues if i.level == "warn"]
    )
    return payload


@router.get("/{system_id}/runs")
async def list_system_runs(
    system_id: str,
    limit: int = 50,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = (
        db.query(Run)
        .filter(Run.workspace_id == workspace.id, Run.system_id == system_id)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": r.duration_ms,
                "decision": r.decision,
                "confidence": r.confidence,
                "value_estimated": r.value_estimated,
                "cost_internal": r.cost_internal,
                "efficiency": r.efficiency,
                "trigger": r.trigger,
            }
            for r in rows
        ]
    }
