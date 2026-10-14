"""Administrative subscriptions to object changes, disabled with the framework."""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.endpoints.connections import _access, _enabled
from app.api.v1.endpoints.connector_writes import call
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.connector_sync import ConnectorWatch
from app.services.connectors import watches

router = APIRouter(dependencies=[Depends(_enabled)])


@router.get("")
def index(
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return [
        watches.view(row)
        for row in db.query(ConnectorWatch)
        .filter_by(workspace_id=workspace.id)
        .order_by(ConnectorWatch.created_at)
        .limit(1000)
        .all()
    ]


@router.post("", status_code=201)
def create(
    body=Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"connection_id", "system_id", "prefix", "interval_s"}
        or not all(isinstance(body[key], str) for key in ("connection_id", "system_id", "prefix"))
    ):
        raise HTTPException(400, detail={"code": "CONNECTOR_WATCH_INVALID"})
    return call(
        db, lambda: watches.view(watches.create(db, workspace_id=workspace.id, user=user, **body))
    )


@router.delete("/{watch_id}")
def disable(
    watch_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return call(
        db,
        lambda: watches.view(
            watches.disable(db, workspace_id=workspace.id, user=user, watch_id=watch_id)
        ),
    )
