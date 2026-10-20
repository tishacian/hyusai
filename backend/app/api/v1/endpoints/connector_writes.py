"""A reviewable immutable contract precedes every connector write."""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.endpoints.connections import _access, _call, _enabled
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.services.connectors import writes
from app.services.connectors.adapters.sql import AdapterError

router = APIRouter(dependencies=[Depends(_enabled)])


def call(db, fn):
    try:
        return _call(db, fn, mutate=True)
    except (writes.WriteError, AdapterError) as exc:
        db.rollback()
        raise HTTPException(getattr(exc, "status_code", 400), detail={"code": exc.code}) from None


@router.post("", status_code=201)
def prepare(
    body=Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    if (
        not isinstance(body, dict)
        or set(body)
        != {
            "connection_id",
            "request_key",
            "operation",
            "dataset_id",
            "parameters",
        }
        or not all(
            isinstance(body[k], str) and 0 < len(body[k]) <= 120
            for k in ("connection_id", "request_key", "operation")
        )
        or not isinstance(body["parameters"], dict)
        or (body["dataset_id"] is not None and not isinstance(body["dataset_id"], str))
    ):
        raise HTTPException(400, detail={"code": "CONNECTOR_WRITE_CONTRACT_INVALID"})
    return call(
        db, lambda: writes.view(writes.prepare(db, workspace_id=workspace.id, user=user, **body))
    )


@router.get("/{operation_id}")
def detail(
    operation_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return call(db, lambda: writes.view(writes.get_write(db, workspace.id, operation_id)))


@router.post("/{operation_id}/approve")
def approve(
    operation_id: str,
    body=Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"contract_digest"}
        or not isinstance(body["contract_digest"], str)
    ):
        raise HTTPException(400, detail={"code": "CONNECTOR_APPROVAL_MISMATCH"})
    return call(
        db,
        lambda: writes.view(
            writes.approve(
                db,
                workspace_id=workspace.id,
                user=user,
                operation_id=operation_id,
                contract_digest=body["contract_digest"],
            )
        ),
    )


@router.post("/{operation_id}/execute", status_code=202)
def execute(
    operation_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return call(
        db,
        lambda: writes.view(
            writes.dispatch(db, workspace_id=workspace.id, user=user, operation_id=operation_id)
        ),
    )


@router.post("/{operation_id}/reconcile", status_code=202)
def reconcile(
    operation_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return call(
        db,
        lambda: writes.dispatch_reconciliation(
            db, workspace_id=workspace.id, user=user, operation_id=operation_id
        ),
    )


@router.post("/{operation_id}/preview", status_code=202)
def preview(
    operation_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return call(
        db,
        lambda: writes.dispatch_preview(
            db, workspace_id=workspace.id, user=user, operation_id=operation_id
        ),
    )


@router.post("/{operation_id}/abandon")
def abandon(
    operation_id: str,
    body=Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    if not isinstance(body, dict) or set(body) != {
        "contract_digest",
        "reason",
        "acknowledge_possible_application",
    }:
        raise HTTPException(400, detail={"code": "CONNECTOR_UNKNOWN_REVIEW_REQUIRED"})
    return call(
        db,
        lambda: writes.view(
            writes.abandon_unknown(
                db, workspace_id=workspace.id, user=user, operation_id=operation_id, **body
            )
        ),
    )
