"""Feature-gated server draft and atomic Flow publication endpoints."""

from __future__ import annotations

import copy
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.systems import (
    _actor_display_name,
    _enforce_system_admin,
    _enforce_system_read,
)
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_engine import schedule_run
from app.services.run_engine.debug_contract import (
    DebugContractError,
    normalize_input_debug,
)
from app.services.systems import flow_publication as publication

router = APIRouter()


class DraftSaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_definition: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int = Field(ge=1)


class DraftRestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class DraftTestRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_ref: dict[str, Any] = Field(default_factory=dict)
    expected_draft_revision: int = Field(ge=1)
    expected_flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingress_id: str | None = Field(default=None, min_length=1, max_length=160)
    kind: Literal["manual", "chat", "http", "schedule", "event"] | None = None

    @model_validator(mode="after")
    def validate_controls(self) -> DraftTestRunBody:
        if (self.ingress_id is None) != (self.kind is None):
            raise ValueError("ingress_id and kind must be provided together")
        try:
            self.input_ref = normalize_input_debug(self.input_ref)
        except DebugContractError as exc:
            raise ValueError(exc.message) from exc
        return self


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_revision: int = Field(ge=1)
    # Required even though the expand/backfill interval permits NULL. Requiring
    # an explicit null prevents an omitted stale-client precondition.
    expected_published_version_id: str | None = Field(..., max_length=36)
    message: str = Field(min_length=1, max_length=2000)
    breaking_change_intent: Literal["acknowledged"] | None = None
    expected_execution_contract_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("message")
    @classmethod
    def validate_release_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("release message must contain non-whitespace characters")
        return stripped


def _system_or_404(
    db: DBSession,
    *,
    system_id: str,
    workspace_id: str,
) -> System:
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace_id)
        .one_or_none()
    )
    if system is None:
        raise HTTPException(404, "System not found")
    return system


def _raise_http(db: DBSession, exc: publication.FlowPublicationError) -> None:
    # Request-scoped sessions roll back when closed, but tests and CLI adapters
    # may reuse one. Release every row lock before exposing the rejection.
    db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _draft_payload(draft: Any, *, no_op: bool, db: DBSession, system: System) -> dict[str, Any]:
    return {
        "system_id": draft.system_id,
        "revision": draft.revision,
        "flow_sha256": draft.flow_sha256,
        "control_policy_snapshot_sha256": publication.resolved_control_policy_snapshot(db, system=system, draft=draft)["sha256"],
        "flow_definition": copy.deepcopy(draft.flow_definition),
        "base_published_version_id": draft.base_published_version_id,
        "updated_by": draft.updated_by,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        "no_op": no_op,
    }


@router.get("/{system_id}/flow-state")
async def get_flow_state(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    try:
        return publication.flow_state(db, system=system, workspace=workspace)
    except publication.FlowPublicationError as exc:
        _raise_http(db, exc)


@router.put("/{system_id}/flow-draft")
async def put_flow_draft(
    system_id: str,
    body: DraftSaveBody,
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
        mutation="flow_draft_save",
    )
    try:
        draft, no_op = publication.save_draft(
            db,
            system_id=system.id,
            workspace=workspace,
            flow_definition=body.flow_definition,
            expected_revision=body.expected_revision,
            actor=_actor_display_name(user),
        )
        db.commit()
        db.refresh(draft)
        return _draft_payload(draft, no_op=no_op, db=db, system=system)
    except publication.FlowPublicationError as exc:
        _raise_http(db, exc)


@router.post("/{system_id}/flow-draft/restore/{version_id}")
async def restore_flow_draft(
    system_id: str,
    version_id: str,
    body: DraftRestoreBody,
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
        mutation="flow_draft_restore",
    )
    try:
        draft, no_op = publication.restore_draft(
            db,
            system_id=system.id,
            workspace=workspace,
            version_id=version_id,
            expected_revision=body.expected_revision,
            actor=_actor_display_name(user),
        )
        db.commit()
        db.refresh(draft)
        return _draft_payload(draft, no_op=no_op, db=db, system=system)
    except publication.FlowPublicationError as exc:
        _raise_http(db, exc)


@router.post("/{system_id}/flow-draft/test-runs", status_code=201)
async def create_flow_draft_test_run(
    system_id: str,
    body: DraftTestRunBody,
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
        mutation="flow_draft_test_run",
    )
    try:
        run = publication.create_draft_test_run(
            db,
            system_id=system.id,
            workspace=workspace,
            user_id=getattr(user, "id", None),
            input_ref=body.input_ref,
            expected_draft_revision=body.expected_draft_revision,
            expected_flow_sha256=body.expected_flow_sha256,
            ingress_id=body.ingress_id,
            ingress_kind=body.kind,
        )
        db.commit()
        db.refresh(run)
    except publication.FlowPublicationError as exc:
        _raise_http(db, exc)
    background_tasks.add_task(schedule_run, run.id)
    return {
        "id": run.id,
        "status": run.status,
        "system_id": run.system_id,
        "execution_surface": run.execution_surface,
        "flow_sha256": run.flow_sha256,
        "draft_revision": body.expected_draft_revision,
        "runtime_mode": (run.execution_contract or {}).get("runtime_mode"),
    }


@router.post("/{system_id}/flow/publish")
async def publish_flow(
    system_id: str,
    body: PublishBody,
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
        mutation="flow_publish",
    )
    try:
        version, draft, no_op = publication.publish_draft(
            db,
            system_id=system.id,
            workspace=workspace,
            expected_draft_revision=body.expected_draft_revision,
            expected_published_version_id=body.expected_published_version_id,
            message=body.message,
            breaking_change_intent=body.breaking_change_intent,
            expected_execution_contract_sha256=body.expected_execution_contract_sha256,
            require_review=True,
            actor=_actor_display_name(user),
        )
        db.commit()
        db.refresh(version)
        db.refresh(draft)
        db.refresh(system)
        return {
            "no_op": no_op,
            "system_id": system.id,
            "status": system.status,
            "published": {
                "version_id": version.id,
                "version_number": version.version_number,
                "flow_sha256": version.flow_sha256
                or publication.canonical_flow_sha256(version.flow_definition),
                "release_kind": version.release_kind or "legacy_snapshot",
                "published_by": system.published_by,
                "published_at": (
                    system.published_at.isoformat() if system.published_at else None
                ),
                "execution_contract": copy.deepcopy(version.execution_contract),
                "control_policy_snapshot_sha256": (version.execution_contract or {}).get("control_policy_snapshot", {}).get("sha256"),
                "execution_contract_ready": True,
            },
            "draft": _draft_payload(draft, no_op=no_op, db=db, system=system),
        }
    except publication.FlowPublicationError as exc:
        _raise_http(db, exc)
