"""Metadata-only activity journal; no new execution or delivery authority."""

import asyncio
import json
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import SessionLocal, get_db
from app.models.activity import Activity
from app.models.user import User
from app.models.workspace import Workspace
from app.services.activity_observability import commands, queries
from app.services.activity_observability.projection import KINDS, STATUSES
from app.services.huggingface.access import is_platform_admin

router = APIRouter()


def _access(db, workspace, user):
    queries.require_enabled()
    queries.require_membership(db, workspace, user)


@router.get("/activities/features")
def features(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    queries.require_membership(db, workspace, user)
    return {
        "enabled": queries.enabled(),
        "scopes": ["workspace", "system"] + (["platform"] if is_platform_admin(user) else []),
        "kinds": KINDS,
        "statuses": STATUSES,
    }


@router.get("/activities")
def activities(
    system_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    if since and since.tzinfo:
        since = since.astimezone(UTC).replace(tzinfo=None)
    return queries.list_activities(
        db,
        workspace,
        user,
        system_id=system_id,
        kind=kind,
        status=status,
        since=since,
        limit=limit,
        offset=offset,
    )


@router.get("/activities/{activity_id}")
def activity_detail(
    activity_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    row = queries.authorized_activity(db, activity_id, workspace, user)
    return queries.detail(db, row, workspace, user)


@router.get("/activities/{activity_id}/wait")
async def wait_activity(
    activity_id: str,
    wait_s: float = Query(2, ge=0, le=10),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    queries.authorized_activity(db, activity_id, workspace, user)
    from app.services.execution.contracts import wait_for_result

    workspace_id, user_id = workspace.id, user.id

    def read():
        with SessionLocal() as current:
            member, scope = current.get(User, user_id), current.get(Workspace, workspace_id)
            _access(current, scope, member)
            row = queries.authorized_activity(current, activity_id, scope, member)
            return queries.serialize_activity(current, row, scope, member)

    async def read_state():
        return await asyncio.to_thread(read)

    status, payload = await wait_for_result(read_state, wait_s=wait_s)
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1, max_length=24)
    expected_version: int = Field(strict=True, ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


@router.post("/activities/{activity_id}/commands", status_code=202)
def issue_command(
    activity_id: str,
    body: CommandRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    row = queries.authorized_activity(db, activity_id, workspace, user)
    command = commands.enqueue(db, row=row, workspace=workspace, user=user, **body.model_dump())
    db.commit()
    return queries.serialize_command(command)


@router.get("/activity-events")
def activity_events(
    cursor: str | None = Query(None, max_length=256),
    activity_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return queries.event_page(
        db, workspace, user, cursor=cursor, activity_id=activity_id, limit=limit
    )


def _frame(event, payload, cursor=None):
    prefix = f"id: {cursor}\n" if cursor else ""
    return (
        prefix
        + "event: "
        + event
        + "\ndata: "
        + json.dumps(payload, separators=(",", ":"))
        + "\n\n"
    )


def _stream_page(workspace_id, user_id, cursor, activity_id, authorization):
    # Called independently of traffic on every poll, with a fresh DB session.
    # Long-lived sessions cannot preserve withdrawn membership, role or token.
    if authorization:
        from app.core.auth import decode_token

        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(401, detail="ACTIVITY_ACCESS_DENIED")
        decode_token(token)
    with SessionLocal() as db:
        workspace = db.get(Workspace, workspace_id)
        user = db.get(User, user_id)
        _access(db, workspace, user)
        return queries.event_page(
            db, workspace, user, cursor=cursor, activity_id=activity_id, limit=100
        )


async def stream_events(
    request, workspace_id, user_id, cursor, activity_id, *, poll_s=1.0, lifetime_s=300
):
    started, last_heartbeat = time.monotonic(), 0.0
    yield _frame("snapshot", {"cursor": cursor}, cursor)
    while time.monotonic() - started < lifetime_s:
        if await request.is_disconnected():
            return
        try:
            page = await asyncio.to_thread(
                _stream_page,
                workspace_id,
                user_id,
                cursor,
                activity_id,
                request.headers.get("authorization"),
            )
        except HTTPException:
            yield _frame("error", {"code": "ACTIVITY_ACCESS_REVOKED"})
            return
        for item in page["items"]:
            yield _frame(item["event_type"], item, item["cursor"])
        cursor = page["next_cursor"]
        if time.monotonic() - last_heartbeat >= 5:
            yield _frame("heartbeat", {"cursor": cursor}, cursor)
            last_heartbeat = time.monotonic()
        if not page["has_more"]:
            await asyncio.sleep(poll_s)
    yield _frame("reconnect", {"cursor": cursor}, cursor)


@router.get("/activity-events/stream")
def event_stream(
    request: Request,
    cursor: str | None = Query(None, max_length=256),
    activity_id: str | None = None,
    last_event_id: str | None = Header(None, alias="Last-Event-ID", max_length=256),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    if cursor and last_event_id and cursor != last_event_id:
        raise HTTPException(400, detail="ACTIVITY_CURSOR_CONFLICT")
    cursor = (
        last_event_id
        or cursor
        or queries.encode_cursor(workspace.id, queries.highwater(db, workspace.id))
    )
    queries.event_page(db, workspace, user, cursor=cursor, activity_id=activity_id, limit=1)
    return StreamingResponse(
        stream_events(request, workspace.id, user.id, cursor, activity_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/platform-overview")
def platform_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    queries.require_enabled()
    if not is_platform_admin(user):
        raise HTTPException(403, detail="PLATFORM_PERMISSION_DENIED")
    from app.services.execution.admission import snapshot

    rows = (
        db.query(Activity.workspace_id, Activity.status, Activity.kind, func.count(Activity.id))
        .group_by(Activity.workspace_id, Activity.status, Activity.kind)
        .all()
    )
    total = {"total": 0, "by_status": {}, "by_kind": {}}
    workspaces = {}
    for workspace_id, status, kind, count in rows:
        local = workspaces.setdefault(workspace_id, {"total": 0, "by_status": {}, "by_kind": {}})
        for target in (total, local):
            target["total"] += count
            target["by_status"][status] = target["by_status"].get(status, 0) + count
            target["by_kind"][kind] = target["by_kind"].get(kind, 0) + count
    return {
        "generated_at": queries.iso(datetime.utcnow()),
        "aggregates": total,
        "resources": snapshot(db),
        "workspaces": [
            {"workspace_id": identifier, "aggregates": value}
            for identifier, value in sorted(workspaces.items())
        ],
    }
