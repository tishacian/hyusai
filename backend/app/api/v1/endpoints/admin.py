"""Workspace-scoped administrative endpoints used by the demo runbook.

These endpoints are intentionally minimal and only intended to be invoked by
workspace owners (or admins) to reseed demo data without requiring direct
database / shell access to the production deployment. All operations are
audit-logged and scoped to the active workspace identified by the
``X-Workspace-Slug`` header.

Routes:

- ``POST /api/v1/admin/calendar/reseed`` — wipe and re-seed the SENTINEL-CI
  calendar (``WorkspaceCalendarEvent``) from
  ``app.services.workspace_calendar.SENTINEL_CALENDAR_SEED``. Useful when the
  deployed seed is stale (e.g. pre-Phase A dates) and ``ensure_calendar_seed``
  refuses to re-run because the table is non-empty.

- ``POST /api/v1/admin/reports/rebuild`` — rebuild the Prefet Nawa 70-page PDF
  and warm a strategic cacao report into the workspace object store. Mirrors
  the ``poetry run python -m app.cli.build_sentinel_reports --force`` CLI but
  is accessible over HTTP for runtime patching of the prod deployment.

- ``POST /api/v1/admin/workspace/reset-actions`` — clear ``actions.last_focus``,
  ``actions.awaiting``, ``actions.current_meeting`` and
  ``actions.pending_agenda_patch`` so the next demo run starts from a clean
  state.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
    normalize_role_template,
)
from app.db.base import get_db
from app.models.calendar import WorkspaceCalendarEvent
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.workspace_calendar import (
    SENTINEL_CALENDAR_SEED,
    ensure_calendar_seed,
)


router = APIRouter()


def _actor(user: User) -> str:
    return user.email or user.username or user.id


def _require_workspace_admin(
    db: DBSession, user: User, workspace: Workspace
) -> WorkspaceMember:
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
    role = normalize_role_template(getattr(membership, "role_template", None), membership.role)
    if role not in (WORKSPACE_OWNER, WORKSPACE_ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Admin/owner access required for admin operations",
        )
    return membership


class ResetActionsRequest(BaseModel):
    clear_last_focus: bool = True
    clear_awaiting: bool = True
    clear_current_meeting: bool = True
    clear_pending_agenda_patch: bool = True
    enabled_packs: Optional[list[str]] = None


@router.post("/calendar/reseed")
def calendar_reseed(
    confirm: bool = Query(default=False, description="Must be true to actually wipe & reseed."),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Wipe and reseed the workspace calendar from ``SENTINEL_CALENDAR_SEED``.

    This is destructive: every ``WorkspaceCalendarEvent`` row attached to the
    current workspace is deleted. Pass ``?confirm=true`` to acknowledge.
    """
    _require_workspace_admin(db, user, workspace)
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to acknowledge the destructive reseed.",
        )
    if "sentinel" not in (workspace.slug or "").lower():
        raise HTTPException(
            status_code=400,
            detail="calendar reseed is only valid for SENTINEL-CI demo workspaces.",
        )

    deleted = (
        db.query(WorkspaceCalendarEvent)
        .filter(WorkspaceCalendarEvent.workspace_id == workspace.id)
        .delete(synchronize_session=False)
    )
    db.flush()
    added = ensure_calendar_seed(db, workspace)
    db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="admin.calendar.reseed",
        actor=_actor(user),
        details={"deleted": int(deleted or 0), "added": int(added or 0)},
    )
    return {
        "status": "ok",
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "deleted": int(deleted or 0),
        "added": int(added or 0),
        "expected": len(SENTINEL_CALENDAR_SEED),
        "reseeded_at": datetime.utcnow().isoformat(),
    }


@router.post("/reports/rebuild")
def reports_rebuild(
    rebuild_prefet: bool = Query(default=True),
    rebuild_strategic_cacao: bool = Query(default=True),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Rebuild the Prefet PDF + warm a strategic cacao report into the store.

    Equivalent to ``python -m app.cli.build_sentinel_reports --force`` but
    invokable over HTTP, scoped to the active workspace only.
    """
    _require_workspace_admin(db, user, workspace)
    if "sentinel" not in (workspace.slug or "").lower():
        raise HTTPException(
            status_code=400,
            detail="reports rebuild is only valid for SENTINEL-CI demo workspaces.",
        )

    from app.services.sentinel_ci_reports import (
        build_prefet_report_pdf,
        ensure_prefet_report_in_object_store,
        generate_strategic_report,
    )

    output: dict[str, Any] = {
        "status": "ok",
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "rebuilt_at": datetime.utcnow().isoformat(),
        "prefet": None,
        "strategic_cacao": None,
    }
    if rebuild_prefet:
        try:
            build_info = build_prefet_report_pdf(force=True)
            store_info = ensure_prefet_report_in_object_store(db, workspace)
            output["prefet"] = {**build_info, **store_info}
        except Exception as exc:  # noqa: BLE001 - report failure inline for ops visibility
            output["prefet"] = {"status": "error", "error": str(exc)}
    if rebuild_strategic_cacao:
        try:
            report = generate_strategic_report(
                db,
                workspace,
                user,
                topic="cacao_diversification",
                context_refs=[
                    "report-prefet-nawa-2026-05-10",
                    "proj-cacao-transformation-nawa",
                ],
                target_id="package-cacao-diversification",
                length="long",
            )
            db.commit()
            output["strategic_cacao"] = report
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            output["strategic_cacao"] = {"status": "error", "error": str(exc)}
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="admin.reports.rebuild",
        actor=_actor(user),
        details={
            "prefet_status": (output["prefet"] or {}).get("status") if isinstance(output["prefet"], dict) else None,
            "strategic_status": (output["strategic_cacao"] or {}).get("topic") if isinstance(output["strategic_cacao"], dict) else None,
        },
    )
    return output


@router.post("/workspace/reset-actions")
def workspace_reset_actions(
    body: ResetActionsRequest = Body(default_factory=ResetActionsRequest),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Reset polluted ``workspace.settings.actions`` keys to clean state."""
    _require_workspace_admin(db, user, workspace)

    settings = dict(workspace.settings or {})
    actions = dict(settings.get("actions") or {})
    cleared: list[str] = []
    if body.clear_last_focus and "last_focus" in actions:
        actions.pop("last_focus", None)
        cleared.append("last_focus")
    if body.clear_awaiting and "awaiting" in actions:
        actions["awaiting"] = {}
        cleared.append("awaiting")
    if body.clear_current_meeting and "current_meeting" in actions:
        actions.pop("current_meeting", None)
        cleared.append("current_meeting")
    if body.clear_pending_agenda_patch and "pending_agenda_patch" in actions:
        actions.pop("pending_agenda_patch", None)
        cleared.append("pending_agenda_patch")
    if body.enabled_packs is not None:
        actions["enabled_packs"] = list(body.enabled_packs)
        cleared.append("enabled_packs=updated")
    settings["actions"] = actions
    workspace.settings = settings
    db.add(workspace)
    db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="admin.workspace.reset_actions",
        actor=_actor(user),
        details={"cleared": cleared},
    )
    return {
        "status": "ok",
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "cleared": cleared,
        "actions": actions,
    }


@router.delete("/calendar/events/{event_id}")
def calendar_event_delete(
    event_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Hard-delete a calendar event (admin only).

    Useful to remove QA pollution like ``agenda QA wiring VIGIE …`` rows that
    accumulated during testing of the workspace calendar API.
    """
    _require_workspace_admin(db, user, workspace)
    event = (
        db.query(WorkspaceCalendarEvent)
        .filter(
            WorkspaceCalendarEvent.id == event_id,
            WorkspaceCalendarEvent.workspace_id == workspace.id,
        )
        .first()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="calendar_event_not_found")
    title = event.title
    db.delete(event)
    db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="admin.calendar.event.deleted",
        actor=_actor(user),
        details={"event_id": event_id, "title": title},
    )
    return {
        "status": "ok",
        "deleted_event_id": event_id,
        "title": title,
    }
