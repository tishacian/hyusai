"""Workspace-admin PostgreSQL explorer using the saved server-side connector."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.endpoints.connectors import _require_workspace_admin
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services import tabular_datasets
from app.services.connectors.generic import postgresql_browser as browser

router = APIRouter()


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: str = Field(alias="schema", min_length=1, max_length=63)
    table: str = Field(min_length=1, max_length=63)
    columns: list[str] = Field(min_length=1, max_length=browser.MAX_COLUMNS)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    def selection(self):
        return self.model_dump(by_alias=True)


class Preview(Selection):
    limit: int = Field(default=25, ge=1, le=browser.MAX_PREVIEW_ROWS)


class Import(Selection):
    name: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=36, max_length=36)


def _error(exc):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None


@router.get("/catalog")
def catalog(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workspace_admin(db, user, workspace)
    try:
        return browser.catalog(workspace)
    except browser.PostgresBrowseError as exc:
        _error(exc)


@router.get("/table")
def table(
    schema: str = Query(min_length=1, max_length=63),
    table: str = Query(min_length=1, max_length=63),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workspace_admin(db, user, workspace)
    try:
        return browser.describe(workspace, schema, table)
    except browser.PostgresBrowseError as exc:
        _error(exc)


@router.post("/preview")
def preview(
    body: Preview,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workspace_admin(db, user, workspace)
    try:
        result = browser.read(workspace, **body.selection())
        return {
            key: value for key, value in result.items() if key not in {"native_rows", "database"}
        }
    except browser.PostgresBrowseError as exc:
        _error(exc)


@router.post("/import")
def import_dataset(
    body: Import,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workspace_admin(db, user, workspace)
    try:
        values = body.selection()
        name, request_id = values.pop("name"), values.pop("request_id")
        dataset, replayed = browser.import_dataset(
            db, workspace, user, name=name, request_id=request_id, **values
        )
        db.commit()
        return {
            "dataset": tabular_datasets.serialize_dataset(dataset, include_preview=True),
            "replayed": replayed,
        }
    except browser.PostgresBrowseError as exc:
        db.rollback()
        _error(exc)
    except tabular_datasets.TabularError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from None
    except IntegrityError:
        # Another native producer can take the same slug/version without the
        # explorer's workspace lock. Roll back and let the caller safely retry.
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "PG_REQUEST_CONFLICT"}) from None
