"""The governed value contract of a System (ADR 0003 lot 3).

Reading needs ``system.read``. Proposing is a System administration act, the
same authority that edits the operational objective. Approving or rejecting
belongs to the owner the proposal names, and to nobody else.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.systems import (
    _enforce_operational_objective_admin,
    _enforce_system_read,
)
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.value_contract import ValueContractDecision, ValueContractProposal
from app.services import value_contracts

router = APIRouter()


def _system_or_404(db: DBSession, *, system_id: str, workspace: Workspace) -> System:
    system = (
        db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    )
    if system is None:
        raise HTTPException(404, "System not found")
    return system


def _can_propose(db: DBSession, *, user: User, workspace: Workspace, system: System) -> bool:
    try:
        _enforce_operational_objective_admin(db, user=user, workspace=workspace, system=system)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return False
    return True


def _is_automation(db: DBSession, system: System) -> bool:
    """A contract belongs to an automation: its draft, published or stored flow says so."""

    flows = [system.flow_definition]
    draft = db.query(SystemFlowDraft).filter(SystemFlowDraft.system_id == system.id).one_or_none()
    if draft is not None:
        flows.append(draft.flow_definition)
    if system.published_flow_version_id:
        version = (
            db.query(SystemVersion)
            .filter(SystemVersion.id == system.published_flow_version_id)
            .one_or_none()
        )
        if version is not None:
            flows.append(version.flow_definition)
    return any(isinstance(flow, dict) and flow.get("variant") == "automation_v1" for flow in flows)


def _refuse(db: DBSession, error: value_contracts.ValueContractError) -> None:
    db.rollback()
    raise HTTPException(
        status_code=error.status_code, detail={"code": error.code, "message": error.message}
    ) from error


def _state(db: DBSession, *, user: User, workspace: Workspace, system: System) -> dict:
    can_propose = _can_propose(db, user=user, workspace=workspace, system=system)
    current = value_contracts.approved(db, system.id)
    waiting = value_contracts.pending(db, system.id)
    history = value_contracts.revisions(db, system.id)[: value_contracts.HISTORY_LIMIT]
    convention, gap = value_contracts.card_value(db, user=user, workspace=workspace, system=system)
    return {
        "system_id": system.id,
        "automation": _is_automation(db, system),
        "latest_revision": history[0].revision if history else 0,
        "current": value_contracts.public(db, current),
        "pending": value_contracts.public(db, waiting),
        "history": [value_contracts.public(db, row) for row in history],
        "gap": gap,
        "convention": convention,
        "can_propose": can_propose,
        "can_decide": waiting is not None and waiting.owner_user_id == user.id,
        "owner_options": value_contracts.owner_options(db, workspace) if can_propose else [],
        "prefill": value_contracts.prefill(db, system) if can_propose else {},
    }


@router.get("/{system_id}/value-contract")
async def get_value_contract(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_or_404(db, system_id=system_id, workspace=workspace)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    return _state(db, user=user, workspace=workspace, system=system)


@router.post("/{system_id}/value-contract")
async def propose_value_contract(
    system_id: str,
    body: ValueContractProposal,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_or_404(db, system_id=system_id, workspace=workspace)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    _enforce_operational_objective_admin(db, user=user, workspace=workspace, system=system)
    try:
        value_contracts.propose(db, workspace=workspace, system=system, user=user, proposal=body)
    except value_contracts.ValueContractError as error:
        _refuse(db, error)
    return _state(db, user=user, workspace=workspace, system=system)


async def _decide(
    db: DBSession,
    *,
    system_id: str,
    revision: int,
    body: ValueContractDecision,
    workspace: Workspace,
    user: User,
    approve: bool,
) -> dict:
    system = _system_or_404(db, system_id=system_id, workspace=workspace)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    try:
        value_contracts.decide(
            db,
            workspace=workspace,
            system=system,
            user=user,
            revision=revision,
            content_sha=body.content_sha256,
            approve=approve,
            note=body.note,
        )
    except value_contracts.ValueContractError as error:
        _refuse(db, error)
    return _state(db, user=user, workspace=workspace, system=system)


@router.post("/{system_id}/value-contract/{revision}/approve")
async def approve_value_contract(
    system_id: str,
    revision: int,
    body: ValueContractDecision,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    return await _decide(
        db,
        system_id=system_id,
        revision=revision,
        body=body,
        workspace=workspace,
        user=user,
        approve=True,
    )


@router.post("/{system_id}/value-contract/{revision}/reject")
async def reject_value_contract(
    system_id: str,
    revision: int,
    body: ValueContractDecision,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    return await _decide(
        db,
        system_id=system_id,
        revision=revision,
        body=body,
        workspace=workspace,
        user=user,
        approve=False,
    )
