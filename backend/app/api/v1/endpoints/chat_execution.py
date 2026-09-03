"""Workspace chat execution policy: which runtime answers `/chat`, and for whom.

``GET  /workspaces/{slug}/chat-execution`` — current mode/percentage, the
agentic target and every invariant that would block a rollout.
``PUT  /workspaces/{slug}/chat-execution`` — admin-only change of mode and
percentage through ``chat_execution_rollout.set_chat_execution`` (the only
writer of this managed setting; the generic settings PATCH refuses it).
"""

from __future__ import annotations

from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user
from app.core.iam.roles import WORKSPACE_ADMIN, WORKSPACE_OWNER, normalize_role_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import chat_execution_rollout as rollout

router = APIRouter()


class ChatExecutionUpdateBody(BaseModel):
    mode: str = Field(..., description="classic | hybrid | agentic_default")
    percentage: Union[int, float] = Field(..., ge=0, le=100)
    dry_run: bool = False


def _resolve_workspace_and_role(
    db: DBSession, user: User, slug: str
) -> tuple[Workspace, WorkspaceMember]:
    workspace = (
        db.query(Workspace)
        .filter(Workspace.slug == slug, Workspace.deleted_at.is_(None))
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    return workspace, membership


def _require_admin(membership: WorkspaceMember) -> None:
    if normalize_role_template(getattr(membership, "role_template", None), membership.role) not in (
        WORKSPACE_OWNER,
        WORKSPACE_ADMIN,
    ):
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/{slug}/chat-execution")
async def get_chat_execution(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace, _ = _resolve_workspace_and_role(db, user, slug)
    return rollout.describe_chat_execution(db, workspace).as_dict()


@router.put("/{slug}/chat-execution")
async def put_chat_execution(
    slug: str,
    body: ChatExecutionUpdateBody,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)
    actor = f"user:{getattr(user, 'email', None) or user.id}"
    try:
        state = rollout.set_chat_execution(
            db,
            workspace,
            mode=body.mode,
            percentage=body.percentage,
            actor=actor,
            dry_run=body.dry_run,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except rollout.RolloutInvariantError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "CHAT_EXECUTION_ROLLOUT_BLOCKED", "message": str(exc)},
        ) from exc
    if body.dry_run:
        db.rollback()
    else:
        db.commit()
    return state.as_dict()
