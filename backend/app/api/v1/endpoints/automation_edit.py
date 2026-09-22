"""One automation edit turn: read, optional verified patch, optional draft test."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.capabilities import serialize_value_basis
from app.api.v1.endpoints.systems import (
    _actor_display_name,
    _enforce_system_admin,
    _enforce_system_read,
    _enforce_system_run_authority,
)
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services import automation_edit, automation_portfolio
from app.services.model_plane.workspace_config import get_routing
from app.services.systems.preparation_diagnostic import (
    caller_run_right,
    preparation_diagnostic,
    provider_name,
)
from app.services.model_plane.execution import (
    ModelExecutionError,
    complete_model,
    resolve_model_execution,
)
from app.services.run_engine import schedule_run
from app.services.systems import flow_publication as publication

router = APIRouter()


class AutomationTurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


def _system_or_404(db: DBSession, *, system_id: str, workspace_id: str) -> System:
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace_id)
        .one_or_none()
    )
    if system is None:
        raise HTTPException(404, "System not found")
    return system


def _refuse(db: DBSession, refusal: automation_edit.AutomationEditRefusal) -> None:
    db.rollback()
    raise HTTPException(
        status_code=422,
        detail={"code": refusal.code, "message": refusal.message},
    ) from refusal


def _bind_skills(db: DBSession, system: System, flow: dict[str, Any]) -> None:
    slugs = automation_edit.required_skill_slugs(flow)
    if not slugs:
        return
    rows = db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    found = {row.slug: row.id for row in rows}
    missing = [slug for slug in slugs if slug not in found]
    if missing:
        raise automation_edit.AutomationEditRefusal(
            "block_refused",
            f"Skill {missing[0]} is not available",
        )
    ids = [item for item in (system.skill_ids or []) if isinstance(item, str)]
    if any(found[slug] not in ids for slug in slugs):
        system.skill_ids = [*ids, *[found[slug] for slug in slugs if found[slug] not in ids]]
        db.flush()


@router.post("/{system_id}/automation-turn")
async def automation_turn(
    system_id: str,
    body: AutomationTurnBody,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_admin(
        db,
        user=user,
        workspace=workspace,
        system=system,
        mutation="automation_turn",
    )
    draft = (
        db.query(SystemFlowDraft)
        .filter(SystemFlowDraft.system_id == system.id)
        .one_or_none()
    )
    if draft is None or not isinstance(draft.flow_definition, dict):
        raise HTTPException(404, "Automation draft not found")
    if draft.flow_definition.get("variant") != "automation_v1":
        _refuse(
            db,
            automation_edit.AutomationEditRefusal(
                "intent_refused",
                "This turn only edits an automation draft",
            ),
        )
    try:
        seen = automation_edit.read_draft(draft.flow_definition)
    except automation_edit.AutomationEditRefusal as refusal:
        _refuse(db, refusal)
    try:
        execution = resolve_model_execution(workspace, provider="workspace")
        options: dict[str, Any] = {"max_tokens": 2000}
        if execution.provider in {"openai", "azure_openai"}:
            options["response_format"] = {"type": "json_object"}
        output = await asyncio.wait_for(
            complete_model(
                execution,
                automation_edit.edit_prompt(body.message, seen),
                {"_model_workspace": workspace},
                generation_options=options,
                stream=False,
            ),
            timeout=60,
        )
    except (ModelExecutionError, asyncio.TimeoutError):
        _refuse(
            db,
            automation_edit.AutomationEditRefusal(
                "plan_invalid",
                "The edit plan could not be produced",
            ),
        )
    completion = output.get("completion") if isinstance(output, dict) else None
    if not isinstance(completion, str) or not completion.strip():
        _refuse(
            db,
            automation_edit.AutomationEditRefusal("plan_invalid", "The edit plan is empty"),
        )
    try:
        plan = automation_edit.plan_from_completion(completion)
    except automation_edit.AutomationEditRefusal as refusal:
        _refuse(db, refusal)

    current = (
        db.query(SystemFlowDraft)
        .filter(SystemFlowDraft.system_id == system.id)
        .one()
    )
    try:
        if automation_edit.read_draft(current.flow_definition)["hash"] != seen["hash"]:
            raise automation_edit.AutomationEditRefusal(
                "stale_draft",
                "The draft changed after it was read; read it again before writing",
            )
    except automation_edit.AutomationEditRefusal as refusal:
        _refuse(db, refusal)

    holder: dict[str, Any] = {"draft": current}

    def save(proposed: dict[str, Any]) -> dict[str, Any]:
        saved, _no_op = publication.save_draft(
            db,
            system_id=system.id,
            workspace=workspace,
            flow_definition=proposed,
            expected_revision=current.revision,
            actor=_actor_display_name(user),
        )
        _bind_skills(db, system, saved.flow_definition)
        holder["draft"] = saved
        return saved.flow_definition

    def start_test(snapshot: dict[str, Any]) -> dict[str, Any]:
        row = holder["draft"]
        run = publication.create_draft_test_run(
            db,
            system_id=system.id,
            workspace=workspace,
            user_id=getattr(user, "id", None),
            input_ref={"transcript": body.message},
            expected_draft_revision=row.revision,
            expected_flow_sha256=snapshot["hash"],
            ingress_id=None,
            ingress_kind=None,
        )
        holder["run"] = run
        return {"id": run.id, "status": run.status}

    try:
        result = automation_edit.execute_turn(
            copy.deepcopy(current.flow_definition),
            intent=plan["intent"],
            patch=plan["patch"] or None,
            save=save,
            start_test=start_test,
        )
        db.commit()
    except automation_edit.AutomationEditRefusal as refusal:
        _refuse(db, refusal)
    except publication.FlowPublicationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc

    run = holder.get("run")
    if run is not None:
        background_tasks.add_task(schedule_run, run.id)
    return {
        "intent": plan["intent"],
        "read": result["read"],
        "verified": result["verified"],
        "run": result["run"],
    }


def _portfolio_refusal(refusal: automation_portfolio.AutomationPortfolioRefusal) -> None:
    raise HTTPException(
        status_code=422,
        detail={"code": refusal.code, "message": refusal.message},
    ) from refusal


def _published_automation(db: DBSession, system: System) -> tuple[dict[str, Any], dict[str, Any] | None]:
    version = (
        db.query(SystemVersion)
        .filter(SystemVersion.id == system.published_flow_version_id, SystemVersion.system_id == system.id)
        .one_or_none()
        if system.published_flow_version_id
        else None
    )
    flow = version.flow_definition if version is not None and isinstance(version.flow_definition, dict) else {}
    try:
        job = automation_portfolio.work_job(
            {"id": system.id, "name": system.name, "status": system.status, "objective": system.objective},
            variant=flow.get("variant") if isinstance(flow, dict) else None,
            published_version_id=version.id if version is not None else None,
            flow_sha256=version.flow_sha256 if version is not None else None,
        )
    except automation_portfolio.AutomationPortfolioRefusal as refusal:
        _portfolio_refusal(refusal)
    capability = (
        db.query(Capability).filter(Capability.id == system.capability_id).one_or_none()
        if system.capability_id
        else None
    )
    convention = serialize_value_basis(
        capability.value_basis if capability is not None else None,
        default_unit=capability.output_unit if capability is not None else None,
    )
    return job, convention


@router.get("/{system_id}/automation-work-job")
async def automation_work_job(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    for card in automation_portfolio.list_job_explanations(db, workspace):
        if card["job"].get("system_id") == system.id:
            return card
    _published_automation(db, system)


@router.get("/{system_id}/automation-package")
async def automation_package(
    system_id: str,
    run_id: str = Query(min_length=1, max_length=36),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    job, convention = _published_automation(db, system)
    run = (
        db.query(Run)
        .filter(Run.id == run_id, Run.system_id == system.id, Run.workspace_id == workspace.id)
        .one_or_none()
    )
    if run is None:
        raise HTTPException(404, "Run not found")
    sap = None
    citations = []
    for item in db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all():
        output = item.output_ref if isinstance(item.output_ref, dict) else {}
        if item.skill_slug == "sap_create_po_v1":
            sap = {"sealed": output.get("sealed") is True, "called": output.get("called") is True}
        source = output.get("source") if item.skill_slug == "semantic_search_v1" else None
        if isinstance(source, str) and source:
            citations.append({"source": source})
    try:
        return automation_portfolio.run_package(
            job,
            {
                "id": run.id,
                "system_id": run.system_id,
                "status": run.status,
                "flow_sha256": run.flow_sha256,
                "execution_surface": run.execution_surface,
            },
            convention=convention,
            proof={"sap": sap, "citations": citations},
        )
    except automation_portfolio.AutomationPortfolioRefusal as refusal:
        _portfolio_refusal(refusal)


@router.get("/{system_id}/preparation")
async def automation_preparation(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Six preparation checks. A skipped check is not ready."""

    system = _system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    draft = (
        db.query(SystemFlowDraft)
        .filter(SystemFlowDraft.system_id == system.id)
        .one_or_none()
    )
    flow = draft.flow_definition if draft is not None and isinstance(draft.flow_definition, dict) else system.flow_definition
    routing = get_routing(workspace)
    try:
        _enforce_system_run_authority(
            db,
            user=user,
            workspace=workspace,
            system=system,
            execution_source="systems_run_api",
            # Same live policy as a run. An empty contract skips the publication
            # row lock, which a preparation read must not take.
            execution_contract={},
        )
        authority_status = None
    except HTTPException as exc:
        authority_status = exc.status_code
    return preparation_diagnostic(
        flow if isinstance(flow, dict) else None,
        provider=provider_name(routing),
        caller_can_run=caller_run_right(authority_status),
    )
