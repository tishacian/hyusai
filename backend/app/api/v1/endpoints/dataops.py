"""Workspace-scoped compilation and durable preparation API."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.recipe import RecipeExecution
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.data_prep import DataPrepSpec
from app.services.dataops.compiler import catalog, expression
from app.services.dataops.preparation import compile_inputs, preview_preparation, submit_preparation
from app.services.governed_assets import GovernanceError
from app.services.recipe_executions import request_cancel, serialize_execution
from app.services.tabular_datasets import TabularError

router = APIRouter()


class PrepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: DataPrepSpec
    inputs: dict[str, dict[str, Any]]
    request_key: str | None = Field(default=None, max_length=160)


def refuse(exc):
    if isinstance(exc, GovernanceError):
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc
    if isinstance(exc, TabularError):
        raise HTTPException(exc.status_code, detail=exc.payload()) from exc
    raise HTTPException(
        429 if str(exc) == "DATAPREP_PREVIEW_BUSY" else 422,
        detail={"code": str(exc).split(":", 1)[0], "message": str(exc)[:400]},
    ) from exc


@router.get("/catalog")
def get_catalog(
    workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user)
):
    return catalog()


@router.post("/compile")
def compile_request(
    body: PrepRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        compiled, datasets = compile_inputs(db, workspace.id, body.spec, body.inputs)
        return {
            "sql": compiled.sql,
            "fingerprint": compiled.fingerprint,
            "ports": list(compiled.port_inputs),
            "columns": list(compiled.columns),
            "schema": __import__(
                "app.services.dataops.preview", fromlist=["infer_schema"]
            ).infer_schema(compiled, datasets, body.spec),
        }
    except (ValueError, TabularError, GovernanceError) as exc:
        refuse(exc)


@router.post("/preview")
def preview(
    body: PrepRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return preview_preparation(
            db, workspace_id=workspace.id, spec=body.spec, inputs=body.inputs
        )
    except (ValueError, TabularError, GovernanceError) as exc:
        refuse(exc)


@router.post("/executions")
def execute(
    body: PrepRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return serialize_execution(
            submit_preparation(
                db,
                workspace_id=workspace.id,
                spec=body.spec,
                inputs=body.inputs,
                request_key=body.request_key,
            )
        )
    except (ValueError, TabularError, GovernanceError) as exc:
        db.rollback()
        refuse(exc)


@router.get("/executions/{execution_id}")
def read_execution(
    execution_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(RecipeExecution).filter_by(id=execution_id, workspace_id=workspace.id).first()
    if not row:
        raise HTTPException(404, "Execution not found")
    return serialize_execution(row)


@router.post("/executions/{execution_id}/cancel")
def cancel(
    execution_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(RecipeExecution).filter_by(id=execution_id, workspace_id=workspace.id).first()
    if not row:
        raise HTTPException(404, "Execution not found")
    return serialize_execution(request_cancel(db, row))


class ExpressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = Field(max_length=4096)
    columns: list[str] = Field(max_length=500)


@router.post("/validate-expression")
def validate_expression(
    body: ExpressionRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    try:
        return {"valid": True, "sql": expression(body.expression, body.columns)}
    except ValueError as exc:
        refuse(exc)


class HashSaltCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,119}$")


@router.post("/hash-salts")
def create_hash_salt(
    body: HashSaltCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import secrets

    from app.services.governed_assets import GovernanceError
    from app.services.secrets import registry
    from app.services.secrets.values import SecretRegistryError
    from app.services.service_promises import require_member

    try:
        require_member(db, workspace.id, user.id, admin=True)
        return registry.create(
            db,
            scope="workspace",
            workspace_id=workspace.id,
            name=body.name,
            value=secrets.token_urlsafe(32),
            actor=user.id,
            kind="generic",
            metadata={"purpose": "dataops_hash_salt"},
            description="Versioned workspace hash salt",
        )
    except (GovernanceError, SecretRegistryError) as exc:
        raise HTTPException(getattr(exc, "status_code", 422), detail={"code": exc.code}) from None
