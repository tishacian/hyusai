"""Workspace-scoped compilation and durable preparation API."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.recipe import RecipeExecution
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.data_prep import DataPrepSpec, PrepOutput, bind_spec
from app.services.dataops.compiler import catalog, expression
from app.services.dataops.preparation import preview_preparation, submit_preparation
from app.services.governed_assets import GovernanceError
from app.services.recipe_executions import request_cancel, serialize_execution
from app.services.tabular_datasets import TabularError


def require_dataops(
    workspace: Workspace = Depends(get_current_workspace), db: Session = Depends(get_db)
):
    from app.services.dataops.rollout import enabled

    if not enabled(db, workspace.id, "dataops_enabled"):
        raise HTTPException(404, detail={"code": "DATAPREP_DISABLED"})


router = APIRouter(dependencies=[Depends(require_dataops)])


class PrepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: DataPrepSpec
    inputs: dict[str, dict[str, Any]]
    request_key: str | None = Field(default=None, max_length=160)
    outputs: list[PrepOutput] | None = None
    step_id: str | None = Field(default=None, max_length=64)
    output_port: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,30}$")
    limit: int = Field(default=50, ge=1, le=200)
    placement: str = "auto"
    timeout_s: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def bind_outputs(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            value["spec"] = bind_spec(value.get("spec"), value.get("outputs"))
        return value


def refuse(exc):
    if isinstance(exc, GovernanceError):
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc
    if isinstance(exc, TabularError):
        raise HTTPException(exc.status_code, detail=exc.payload()) from exc
    raise HTTPException(
        429 if str(exc) == "DATAPREP_PREVIEW_BUSY" else 422,
        detail={
            "code": str(exc).split(":", 1)[0],
            "message": str(exc)[:400],
            "step_id": getattr(exc, "step_id", None),
            "position": getattr(exc, "position", None),
        },
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
        from app.services.dataops.preview_graph import compile_preview_graph, sql_export

        compiled, datasets = compile_preview_graph(
            db, workspace.id, body.spec, body.inputs, step_id=body.step_id
        )
        return {
            "sql": compiled.sql,
            "fingerprint": compiled.fingerprint,
            "ports": list(compiled.port_inputs),
            "columns": list(compiled.columns),
            "schema": list(compiled.output_schema),
            "output_schema": list(compiled.output_schema),
            "step_schemas": list(compiled.step_schemas),
            "warnings": list(compiled.warnings),
            "sources": [
                {"port": "input" if port == "in" else port, "dataset_id": dataset.id}
                for port, dataset in datasets.items()
            ],
            **sql_export(compiled, body.spec),
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
            db,
            workspace_id=workspace.id,
            spec=body.spec,
            inputs=body.inputs,
            step_id=body.step_id,
            limit=body.limit,
            output_port=body.output_port,
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
        if (
            body.step_id
            or body.output_port
            or any("upstream" in ref for ref in body.inputs.values())
        ):
            raise ValueError("DATAPREP_PREVIEW_ONLY_INPUT")
        return serialize_execution(
            submit_preparation(
                db,
                workspace_id=workspace.id,
                spec=body.spec,
                inputs=body.inputs,
                request_key=body.request_key,
                placement=body.placement,
                timeout_s=body.timeout_s,
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
    expression: str = Field(max_length=4000)
    columns: list[str] = Field(default_factory=list, max_length=500)
    schema_fields: list[dict[str, Any]] = Field(
        default_factory=list, alias="schema", max_length=500
    )


@router.post("/validate-expression")
def validate_expression(
    body: ExpressionRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    try:
        from app.services.dataops.compiler import compile_prep

        columns = [f["name"] for f in body.schema_fields] if body.schema_fields else body.columns
        sql = expression(body.expression, columns)
        result = {"valid": True, "sql": sql, "dtype": None}
        if body.schema_fields:
            spec = DataPrepSpec(
                operation="prepare",
                steps=[
                    {
                        "action": "formula",
                        "params": {"output": "__expression_result", "expression": body.expression},
                    }
                ],
                outputs=[{"name": "Validation"}],
            )
            compiled = compile_prep(spec, {"in": body.schema_fields})
            field = next(f for f in compiled.output_schema if f["name"] == "__expression_result")
            result.update(dtype=field["dtype"], schema=field)
        return result
    except ValueError as exc:
        refuse(exc)


class PivotValuesRequest(PrepRequest):
    column: str = Field(min_length=1, max_length=255)


@router.post("/pivot-values")
def pivot_values(
    body: PivotValuesRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        spec = DataPrepSpec(
            operation="aggregate",
            params={
                "group_by": [body.column],
                "aggregations": [{"op": "count_rows", "output": "__dp_pivot_count"}],
            },
            outputs=[{"name": "Pivot proposals"}],
        )
        result = preview_preparation(
            db, workspace_id=workspace.id, spec=spec, inputs=body.inputs, limit=body.limit
        )
        return {
            "values": [row[body.column] for row in result["rows"]],
            "truncated": result["counters"]["outputs"]["out"] > body.limit,
            "sample": True,
            "sample_info": result["sample_info"],
        }
    except (ValueError, TabularError, GovernanceError) as exc:
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
