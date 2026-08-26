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
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
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
    read_page,
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


class TransformSourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view: Optional[str] = Field(default=None, max_length=64)
    dataset_id: Optional[str] = Field(default=None, max_length=36)
    dataset_slug: Optional[str] = Field(default=None, max_length=200)


class SqlPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(default="", max_length=60_000)
    sources: list[TransformSourceBody] = Field(default_factory=list, max_length=8)
    row_limit: int = Field(default=50, ge=1, le=500)


@router.post("/sql-preview")
async def preview_sql_transform(
    body: SqlPreviewBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Run a transform without persisting it — the SQL workshop's Test button.

    Returns the same profile shape the dataset pages render (schema, preview
    rows, per-column stats) plus the source catalog the editor autocompletes
    from, so the workshop needs exactly one call to be useful.
    """

    from app.services.tabular_transforms import preview_sql, resolve_sources, source_catalog

    declared = [
        entry.model_dump(exclude_none=True) for entry in body.sources
    ]
    try:
        if not str(body.sql or "").strip():
            # No statement yet: the editor still needs the catalog to
            # autocomplete against, so answer with sources only.
            sources = resolve_sources(
                db, workspace_id=workspace.id, declared=declared, payload=None
            )
            return {"preview": None, "sources": source_catalog(sources)}
        result = preview_sql(
            db,
            workspace_id=workspace.id,
            sql=body.sql,
            declared=declared,
            row_limit=body.row_limit,
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {"preview": result, "sources": result["sources"]}


class PolarsPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(default="", max_length=200_000)
    requirements_text: str = Field(default="", max_length=60_000)
    sources: list[TransformSourceBody] = Field(default_factory=list, max_length=8)
    row_limit: int = Field(default=50, ge=1, le=500)
    timeout_s: Optional[float] = Field(default=None, ge=1, le=600)


@router.post("/polars-preview")
async def preview_polars_transform(
    body: PolarsPreviewBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Dispatch a Polars transform preview — the Python workshop's Test button.

    Unlike the SQL preview this one cannot answer inline: author-written Python
    only ever runs on a managed venv interpreter, in the worker container that
    mounts the venv store. So the call stages a ``RecipeExecution``, dispatches
    it and answers with the row; the workshop follows it through
    ``/recipe-executions/{id}`` and reads the profile off ``output_json``.

    The source catalog is resolved synchronously either way, because the editor
    needs it to autocomplete before any run has settled.
    """

    from app.services.recipe_executions import serialize_execution
    from app.services.tabular_polars import submit_polars_run
    from app.services.tabular_transforms import resolve_sources, source_catalog

    declared = [entry.model_dump(exclude_none=True) for entry in body.sources]
    try:
        if not body.code.strip():
            # No script yet: the editor still needs the catalog of frames the
            # `inputs` dict will carry, so answer with sources only.
            sources = resolve_sources(
                db, workspace_id=workspace.id, declared=declared, payload=None
            )
            return {"execution": None, "sources": source_catalog(sources)}
        execution, sources = submit_polars_run(
            db,
            workspace_id=workspace.id,
            code=body.code,
            requirements_text=body.requirements_text,
            declared=declared,
            persist=False,
            row_limit=body.row_limit,
            timeout_s=body.timeout_s,
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {
        "execution": serialize_execution(execution),
        "sources": source_catalog(sources),
    }


class DbtModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=64)
    sql: str = Field(default="", max_length=60_000)


class DbtPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[DbtModelBody] = Field(default_factory=list, max_length=32)
    tests_yml: str = Field(default="", max_length=60_000)
    output_model: str = Field(default="", max_length=64)
    requirements_text: str = Field(default="", max_length=60_000)
    sources: list[TransformSourceBody] = Field(default_factory=list, max_length=8)
    row_limit: int = Field(default=50, ge=1, le=500)
    timeout_s: Optional[float] = Field(default=None, ge=1, le=600)


@router.post("/dbt-preview")
async def preview_dbt_transform(
    body: DbtPreviewBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Dispatch a dbt build over the node's inputs — the dbt workshop's Test button.

    Same transport as the Polars preview and for the same reason: a dbt project
    compiles Jinja and runs adapter macros, so it only ever executes on a
    managed venv interpreter in the worker container. The call stages a
    ``RecipeExecution``, dispatches it and answers with the row; the workshop
    follows it and reads the profile — and the test verdicts — off
    ``output_json``.
    """

    from app.services.recipe_executions import serialize_execution
    from app.services.tabular_dbt import submit_dbt_run
    from app.services.tabular_transforms import resolve_sources, source_catalog

    declared = [entry.model_dump(exclude_none=True) for entry in body.sources]
    models = [entry.model_dump() for entry in body.models]
    try:
        if not any(str(entry.get("sql") or "").strip() for entry in models):
            # No project yet: the editor still needs the catalog of relations
            # its `source()` calls can address, so answer with sources only.
            sources = resolve_sources(
                db, workspace_id=workspace.id, declared=declared, payload=None
            )
            return {"execution": None, "sources": source_catalog(sources)}
        execution, sources = submit_dbt_run(
            db,
            workspace_id=workspace.id,
            models=models,
            tests_yml=body.tests_yml,
            output_model=body.output_model,
            requirements_text=body.requirements_text,
            declared=declared,
            persist=False,
            row_limit=body.row_limit,
            timeout_s=body.timeout_s,
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {
        "execution": serialize_execution(execution),
        "sources": source_catalog(sources),
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


@router.get("/{dataset_id}/preview")
async def get_dataset_preview(
    dataset_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """A window of a dataset's rows, read from the Parquet.

    The detail route already carries the fifty rows cached at ingest, which is
    what opens the page without a second request. This route exists for the
    question that cache cannot answer: every dataset here is immutable, so row
    8 400 of an 8 412-row dataset is a fact that exists and simply is not in the
    cache. A reader who scrolls past the fiftieth row asks for it, and asking is
    cheap — the slice is pushed into the Parquet reader, which skips whole row
    groups rather than loading the file.

    Offloaded to a thread because it touches the ObjectStore and a file: on the
    event loop it would stall every other request for the length of the read.
    """

    try:
        dataset = get_dataset(db, dataset_id=dataset_id, workspace_id=workspace.id)
        if dataset.status != "ready":
            raise TabularError(
                code="DATASET_NOT_READY",
                message="The dataset is still being prepared.",
                status_code=409,
            )
        page = await run_in_threadpool(
            read_page, dataset, offset=offset, limit=limit
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {
        "dataset_id": dataset.id,
        "schema": list(dataset.schema_json or []),
        **page,
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
