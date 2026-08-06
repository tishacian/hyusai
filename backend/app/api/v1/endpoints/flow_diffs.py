"""Secret-free semantic diff between published, draft and immutable versions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.systems import _enforce_system_read
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services.flow_contracts import canonical_sha256
from app.services.flow_diff import semantic_flow_diff
from app.services.run_engine.execution_contract import canonical_flow
from app.services.systems import flow_publication

router = APIRouter()


def _diff_contract(version: SystemVersion) -> dict[str, Any] | None:
    """Return secret-free evidence that distinguishes absent from corrupt.

    Execution always uses the strictly validated pinned contract.  A semantic
    diff additionally needs to know whether a non-null frozen payload existed:
    otherwise corruption would look like a harmless legacy baseline.  Only a
    digest and an invalid-state marker leave this boundary.
    """

    pinned = flow_publication._pinned_execution_contract(version)
    if pinned is not None:
        return pinned
    raw = version.execution_contract
    if raw is None:
        return None
    return {
        "contract_state": "invalid",
        "contract_sha256": canonical_sha256(raw),
    }


def _resolve_ref(
    db: DBSession,
    *,
    system: System,
    workspace: Workspace,
    ref: str,
) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    if ref == "published":
        version = (
            db.query(SystemVersion)
            .filter(
                SystemVersion.id == system.published_flow_version_id,
                SystemVersion.system_id == system.id,
                SystemVersion.workspace_id == system.workspace_id,
            )
            .one_or_none()
        )
        if version is None:
            raise HTTPException(409, detail={"code": "PUBLISHED_FLOW_VERSION_INVALID"})
        return (
            canonical_flow(version.flow_definition),
            f"published:{version.version_number}",
            _diff_contract(version),
        )
    if ref == "draft":
        draft = (
            db.query(SystemFlowDraft)
            .filter(
                SystemFlowDraft.system_id == system.id,
                SystemFlowDraft.workspace_id == system.workspace_id,
            )
            .one_or_none()
        )
        if draft is None:
            raise HTTPException(409, detail={"code": "FLOW_DRAFT_STATE_MISSING"})
        flow = canonical_flow(draft.flow_definition)
        return (
            flow,
            f"draft:{draft.revision}",
            flow_publication.compile_execution_contract(
                db,
                flow,
                workspace,
                system=system,
            ),
        )
    if ref.startswith("version:"):
        try:
            number = int(ref.removeprefix("version:"))
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "FLOW_DIFF_REF_INVALID"}) from exc
        version = (
            db.query(SystemVersion)
            .filter(
                SystemVersion.system_id == system.id,
                SystemVersion.workspace_id == system.workspace_id,
                SystemVersion.version_number == number,
            )
            .one_or_none()
        )
        if version is None:
            raise HTTPException(404, detail={"code": "FLOW_VERSION_NOT_FOUND"})
        return (
            canonical_flow(version.flow_definition),
            f"version:{number}",
            _diff_contract(version),
        )
    raise HTTPException(422, detail={"code": "FLOW_DIFF_REF_INVALID"})


@router.get("/{system_id}/flow-diff")
async def get_flow_diff(
    system_id: str,
    base: str = Query(default="published", max_length=80),
    target: str = Query(default="draft", max_length=80),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .one_or_none()
    )
    if system is None:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    try:
        flow_publication.require_flow_publication(workspace)
    except flow_publication.FlowPublicationError as exc:
        raise HTTPException(exc.status_code, detail=exc.payload()) from exc
    try:
        base_flow, base_identity, base_contract = _resolve_ref(
            db,
            system=system,
            workspace=workspace,
            ref=base,
        )
        target_flow, target_identity, target_contract = _resolve_ref(
            db,
            system=system,
            workspace=workspace,
            ref=target,
        )
    except flow_publication.FlowPublicationError as exc:
        raise HTTPException(exc.status_code, detail=exc.payload()) from exc
    return semantic_flow_diff(
        base_flow,
        target_flow,
        base_identity=base_identity,
        target_identity=target_identity,
        base_contract=base_contract,
        target_contract=target_contract,
    )
