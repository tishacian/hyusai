"""Authorized mandate drafts, published configuration and Run proof links."""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.v1.endpoints.runs import _decision_target_run, _pending_hitl_checkpoint, _visible_run_or_404
from app.api.v1.endpoints.skills import _visible_skill_rows
from app.api.v1.endpoints.systems import _actor_display_name, _enforce_system_admin, _enforce_system_read
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.decision import Decision
from app.models.knowledge_collection import KnowledgeCollection
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services import mandate_projection
from app.services.decision_access import readable_decisions
from app.services.iam.decision_plane import enforce_action, resolve_action
from app.services.run_access import (
    readable_run_page, readable_runs, readable_skill_invocations, run_read_attrs,
)
from app.services.run_engine.engine import _load_control_policy
from app.services.system_access import readable_systems
from app.services.systems import flow_publication as publication, mandate_draft

router = APIRouter()


class MandateSaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    expected_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    spec: dict[str, Any]


class MandateValidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    expected_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def _system(db, *, system_id, workspace, user, write=False):
    system = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).one_or_none()
    if system is None:
        raise HTTPException(404, "System not found")
    if write:
        _enforce_system_admin(db, system=system, workspace=workspace, user=user, mutation="mandate_draft")
    else:
        _enforce_system_read(db, system=system, workspace=workspace, user=user)
    return system


def _can_edit(db, *, system, workspace, user):
    if not publication.flow_publication_enabled(workspace):
        return False
    try:
        _enforce_system_admin(db, system=system, workspace=workspace, user=user, mutation="mandate_draft")
        return True
    except HTTPException as exc:
        if exc.status_code == 403:
            return False
        raise


def _options(db, *, system, snapshot, workspace, user, flow=None):
    spec = mandate_draft.editable_spec(snapshot)
    labels = _reference_labels(db, configuration={"spec": spec}, workspace=workspace, user=user)
    bound_ids = set(system.skill_ids or []) | set(getattr(system.capability, "skill_ids", None) or [])
    skill_options = {}
    if resolve_action(db, user=user, workspace=workspace, resource_kind="skill", action="read",
                      legacy_allowed=True, resource_attrs={"scope": "collection"}).effective_allowed:
        skill_options.update({row.slug: row.name for row in _visible_skill_rows(db, workspace) if row.id in bound_ids})
    # Collection catalog has the same workspace membership boundary as the
    # canonical documents/collections endpoint; no private ACL exists here.
    collections = {row.slug: row.name for row in db.query(KnowledgeCollection)
                   .filter(KnowledgeCollection.workspace_id == workspace.id).all()}
    models = mandate_draft.configured_models(system, workspace, flow=flow)
    return {"skills": [{"id": key, "label": value} for key, value in sorted(skill_options.items())],
            "collections": [{"id": key, "label": value} for key, value in sorted(collections.items())],
            "models": [{"id": value, "label": value} for value in sorted(models)],
            "delegations": [{**deepcopy(rule), "label": labels["delegations"][rule["system_id"]]}
                            for rule in spec["capabilities"]["allowed_delegations"]
                            if isinstance(rule, dict) and rule.get("system_id") in labels["delegations"]]}


def _draft_state(db, *, system, workspace, user):
    publication.require_flow_publication(workspace)
    draft = db.query(SystemFlowDraft).filter_by(system_id=system.id, workspace_id=workspace.id).one_or_none()
    if draft is None:
        raise publication.FlowPublicationError("FLOW_DRAFT_STATE_MISSING", "The System has no initialized Flow draft.")
    published = publication._owned_version(db, system=system, version_id=system.published_flow_version_id)
    snapshot = publication.resolved_control_policy_snapshot(db, system=system, draft=draft)
    published_contract = published.execution_contract if isinstance(published.execution_contract, dict) else {}
    raw_published = published_contract.get("control_policy_snapshot")
    configuration = mandate_projection.published_configuration(system=system, version=published,
                                                                 legacy_policy=_load_control_policy(db, system))
    if configuration.get("policy_binding") == "invalid":
        raise publication.FlowPublicationError("FLOW_POLICY_SNAPSHOT_INVALID", "The published mandate is invalid.")
    return {"system_id": system.id, "permissions": {"can_edit": _can_edit(db, system=system, workspace=workspace, user=user)},
            "draft": {"revision": draft.revision, "flow_sha256": draft.flow_sha256,
                      "spec": mandate_draft.editable_spec(snapshot), "base_published_version_id": draft.base_published_version_id,
                      "spec_is_seed": mandate_draft.spec_is_seed(snapshot),
                      "snapshot_sha256": snapshot["sha256"],
                      "policy_binding": "frozen" if draft.control_policy_snapshot is not None or raw_published is not None
                      else "not_configured" if snapshot["state"] == "not_configured" else "legacy_current"},
            "published": {"version_id": published.id, "version_number": published.version_number,
                          "spec": configuration["spec"], "policy_revision": configuration["policy_revision"],
                          "snapshot_sha256": configuration.get("policy_snapshot_sha256"),
                          "policy_binding": "frozen" if raw_published is not None else "legacy"},
            "options": _options(db, system=system, snapshot=snapshot, workspace=workspace, user=user, flow=draft.flow_definition),
            "validation": {"valid": False, "checks": [{"code": code, "status": "not_run"} for code in mandate_draft.CHECKS]}}


def _raise(db, exc):
    db.rollback()
    raise HTTPException(exc.status_code, exc.payload()) from exc


@router.get("/systems/{system_id}/mandate/draft")
async def get_mandate_draft(system_id: str, workspace: Workspace = Depends(get_current_workspace),
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    system = _system(db, system_id=system_id, workspace=workspace, user=user)
    try:
        return _draft_state(db, system=system, workspace=workspace, user=user)
    except publication.FlowPublicationError as exc:
        _raise(db, exc)


@router.put("/systems/{system_id}/mandate/draft")
async def put_mandate_draft(system_id: str, body: MandateSaveBody, workspace: Workspace = Depends(get_current_workspace),
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    system = _system(db, system_id=system_id, workspace=workspace, user=user, write=True)
    try:
        state = _draft_state(db, system=system, workspace=workspace, user=user)
        _, no_op = mandate_draft.save(db, system=system, workspace=workspace, actor=_actor_display_name(user),
                                     options=state["options"], **body.model_dump())
        db.commit()
        return {**_draft_state(db, system=system, workspace=workspace, user=user), "no_op": no_op}
    except publication.FlowPublicationError as exc:
        _raise(db, exc)


@router.post("/systems/{system_id}/mandate/draft/validate")
async def validate_mandate_draft(system_id: str, body: MandateValidateBody, workspace: Workspace = Depends(get_current_workspace),
                                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    system = _system(db, system_id=system_id, workspace=workspace, user=user, write=True)
    try:
        publication.require_flow_publication(workspace)
        return mandate_draft.validate(db, system=system, workspace=workspace, **body.model_dump())
    except publication.FlowPublicationError as exc:
        _raise(db, exc)


def _reference_labels(db: Session, *, configuration: dict, workspace: Workspace, user: User) -> dict:
    """Optional current catalog names; never widen access to resolve an ID."""
    spec = configuration.get("spec") or {}
    capabilities = spec.get("capabilities") or {}
    skills = {}
    refs = set(capabilities.get("allowed_skills") or [])
    if refs and resolve_action(
        db, user=user, workspace=workspace, resource_kind="skill", action="read",
        legacy_allowed=True, resource_attrs={"scope": "collection"},
    ).effective_allowed:
        for row in _visible_skill_rows(db, workspace):
            for ref in (row.slug, row.id):
                if ref in refs:
                    skills[ref] = row.name
    delegation_refs = [rule.get("system_id") if isinstance(rule, dict) else rule
                       for rule in capabilities.get("allowed_delegations") or []]
    delegation_ids = {ref for ref in delegation_refs if isinstance(ref, str) and ref}
    targets = (db.query(System).filter(System.workspace_id == workspace.id, System.id.in_(delegation_ids)).all()
               if delegation_ids else [])
    delegations = {row.id: row.name for row in readable_systems(
        db, systems=targets, user=user, workspace=workspace,
    )}
    return {"skills": skills, "delegations": delegations}


def _evidence(db: Session, *, run: Run, workspace: Workspace, user: User) -> dict:
    invocations = readable_skill_invocations(
        db, invocations=db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all(),
        run=run, workspace=workspace, user=user,
    )
    candidates = db.query(Decision).filter(
            Decision.workspace_id == workspace.id,
            or_(and_(Decision.scope == "run", Decision.target_id == run.id),
                and_(Decision.scope == "system", Decision.target_id == run.system_id,
                     Decision.rationale["run_id"].as_string() == run.id)),
        ).all()
    authorized_targets = [run]
    forwarded_decisions = {}
    gate = _pending_hitl_checkpoint(run)
    if gate and gate.get("decision_id"):
        candidate = db.query(Decision).filter(
            Decision.id == gate["decision_id"], Decision.workspace_id == workspace.id,
        ).one_or_none()
        target = (_decision_target_run(db, decision=candidate, paused_run=run, workspace_id=workspace.id)
                  if candidate else None)
        if target is not None and target.id != run.id and readable_runs(
            db, runs=[target], user=user, workspace=workspace,
        ):
            authorized_targets.append(target)
            candidates.append(candidate)
            forwarded_decisions[candidate.id] = target.id
    decisions = readable_decisions(
        db, decisions=candidates, workspace=workspace, user=user, visible_runs=authorized_targets,
    )
    children = readable_run_page(
        db, query=db.query(Run).filter(
            Run.workspace_id == workspace.id, Run.parent_run_id == run.id,
            Run.trigger == "subflow", Run.delegation_key.is_not(None),
            Run.delegation_node_id.is_not(None),
        ).order_by(Run.started_at, Run.id), limit=20, user=user, workspace=workspace,
    )
    return mandate_projection.run_mandate(
        run, decisions=decisions, invocations=invocations, children=children,
        forwarded_decision_run_ids=forwarded_decisions,
    )


@router.get("/systems/{system_id}/mandate")
async def get_system_mandate(
    system_id: str, workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    system = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).one_or_none()
    if system is None:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    runs = readable_run_page(
        db, query=db.query(Run).filter(Run.system_id == system.id, Run.workspace_id == workspace.id)
        .order_by(Run.started_at.desc(), Run.id.desc()),
        limit=8, user=user, workspace=workspace,
    )
    recent = []
    for run in runs:
        evidence = _evidence(db, run=run, workspace=workspace, user=user)
        recent.append({"run_id": run.id, "status": run.status,
                       "started_at": run.started_at.isoformat() if run.started_at else None,
                       "evidence_state": "recorded" if evidence["events"] else "not_recorded",
                       "event_count": len(evidence["events"]), "facets": evidence["facets"],
                       "recorded_mode": evidence["applied"]["mode"],
                       "recorded_version": evidence["applied"]["version"]})
    published = db.query(SystemVersion).filter_by(id=system.published_flow_version_id,
                    system_id=system.id, workspace_id=workspace.id).one_or_none() if system.published_flow_version_id else None
    configuration = mandate_projection.published_configuration(system=system, version=published,
                                                                 legacy_policy=_load_control_policy(db, system))
    limitations = ["configuration_is_not_execution_proof", "visible_recent_runs_only",
                   "mandate_editing_requires_versioned_publication"]
    if configuration["state"] == "derived":
        limitations.append("legacy_derived_defaults_are_not_controls")
    return {"system_id": system.id, "system_name": system.name,
            "configuration": configuration,
            "reference_labels": _reference_labels(db, configuration=configuration, workspace=workspace, user=user),
            "permissions": {"can_edit": _can_edit(db, system=system, workspace=workspace, user=user)},
            "editing_supported": publication.flow_publication_enabled(workspace),
            "recent_runs": recent, "recent_runs_limit": 8,
            "limitations": limitations}


@router.get("/runs/{run_id}/mandate")
async def get_run_mandate(
    run_id: str, workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    run = _visible_run_or_404(db, run_id=run_id, user=user, workspace=workspace)
    enforce_action(db, user=user, workspace=workspace, resource_kind="run", action="read",
                   legacy_allowed=True, resource_attrs=run_read_attrs(run))
    return _evidence(db, run=run, workspace=workspace, user=user)
