"""Tabular datasets API: upload, browse, profile, retire.

Workspace-scoped. The endpoint never reads dataset bytes: an upload is staged
into the ObjectStore and handed to the ``agentium.dataset_ingest`` worker, which
folds the schema, preview and column profile back into the row. Every read here
is therefore one indexed SELECT, which is what keeps the Data pages snappy while
an ingest is still running.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.tabular import TabularDataset
from app.models.user import User
from app.models.workspace import Workspace
from app.services.tabular_datasets import (
    DATASET_INGEST_TASK,
    TabularError,
    create_upload,
    get_dataset,
    ingest_dataset,
    serialize_dataset,
    soft_delete,
)

router = APIRouter()


def _raise_tabular(exc: TabularError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _feature_payload() -> dict[str, Any]:
    return {
        "enabled": bool(settings.tabular_data_enabled),
        "upload_max_bytes": int(settings.tabular_upload_max_bytes),
    }


def _dispatch_ingest(dataset_id: str) -> bool:
    """Queue the ingest, or run it inline when the worker plane is eager."""

    if settings.worker_eager_mode:
        ingest_dataset(dataset_id)
        return False
    from app.workers.celery_app import celery_app

    celery_app.send_task(
        DATASET_INGEST_TASK,
        args=(dataset_id,),
        queue=settings.celery_task_default_queue,
    )
    return True


@router.get("")
async def list_datasets(
    source: Optional[str] = Query(default=None, max_length=16),
    status: Optional[str] = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    query = db.query(TabularDataset).filter(
        TabularDataset.workspace_id == workspace.id,
        TabularDataset.status != "deleted",
    )
    if source:
        query = query.filter(TabularDataset.source == source)
    if status:
        query = query.filter(TabularDataset.status == status)
    datasets = query.order_by(TabularDataset.created_at.desc()).limit(limit).all()
    return {
        "datasets": [serialize_dataset(row) for row in datasets],
        "feature": _feature_payload(),
    }


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    name: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Stage a file and queue its ingest; the row status is the tracker."""

    payload = await file.read()
    try:
        dataset = create_upload(
            db,
            workspace_id=workspace.id,
            name=(name or "").strip() or (file.filename or "dataset"),
            filename=file.filename or "upload.csv",
            content_type=file.content_type,
            payload=payload,
            description=(description or "").strip() or None,
            created_by=getattr(user, "id", None),
        )
    except TabularError as exc:
        _raise_tabular(exc)
    db.commit()
    dataset_id = dataset.id
    queued = _dispatch_ingest(dataset_id)
    db.expire_all()
    refreshed = (
        db.query(TabularDataset).filter(TabularDataset.id == dataset_id).first()
    )
    return {
        "dataset": serialize_dataset(refreshed or dataset),
        "queued": queued,
    }


@router.get("/{dataset_id}")
async def get_dataset_detail(
    dataset_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Full read model: schema, preview rows and the per-column profile."""

    try:
        dataset = get_dataset(db, dataset_id=dataset_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    parents = (
        db.query(TabularDataset)
        .filter(TabularDataset.id.in_(list(dataset.parent_ids or [])))
        .all()
        if dataset.parent_ids
        else []
    )
    children = (
        db.query(TabularDataset)
        .filter(
            TabularDataset.workspace_id == workspace.id,
            TabularDataset.status != "deleted",
            TabularDataset.parent_ids.isnot(None),
        )
        .order_by(TabularDataset.created_at.desc())
        .limit(200)
        .all()
    )
    descendants = [
        serialize_dataset(row)
        for row in children
        if dataset.id in list(row.parent_ids or [])
    ]
    versions = (
        db.query(TabularDataset)
        .filter(
            TabularDataset.workspace_id == workspace.id,
            TabularDataset.slug == dataset.slug,
            TabularDataset.status != "deleted",
        )
        .order_by(TabularDataset.version.desc())
        .limit(50)
        .all()
    )
    return {
        "dataset": serialize_dataset(dataset, include_preview=True),
        "lineage": {
            "parents": [serialize_dataset(row) for row in parents],
            "children": descendants,
        },
        "versions": [serialize_dataset(row) for row in versions],
        "feature": _feature_payload(),
    }


@router.post("/{dataset_id}/reingest")
async def reingest_dataset(
    dataset_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Retry a failed ingest without re-uploading the file."""

    try:
        dataset = get_dataset(db, dataset_id=dataset_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    if not dataset.upload_key:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "dataset_not_reingestable",
                "code": "DATASET_NOT_REINGESTABLE",
                "message": "Only uploaded datasets can be re-ingested.",
            },
        )
    dataset.status = "pending"
    dataset.status_detail = "Queued for ingest"
    dataset.error = None
    db.commit()
    queued = _dispatch_ingest(dataset.id)
    db.expire_all()
    refreshed = (
        db.query(TabularDataset).filter(TabularDataset.id == dataset_id).first()
    )
    return {"dataset": serialize_dataset(refreshed or dataset), "queued": queued}


@router.delete("/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Retire a dataset (soft: the production object policy is append-only)."""

    try:
        dataset = get_dataset(db, dataset_id=dataset_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    dataset = soft_delete(db, dataset)
    return {"dataset": serialize_dataset(dataset)}
