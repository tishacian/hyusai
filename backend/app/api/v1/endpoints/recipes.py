"""Python recipe plane API: managed venvs + execution status/cancel.

Two workspace-scoped routers mounted at ``/python-envs`` and
``/recipe-executions``. Errors follow the canonical ``{code, message}``
payload carried by :class:`app.services.recipe_envs.RecipeError`.

Requirements files are deliberately NOT uploaded here: the Flow Builder reads
``requirements.txt`` client-side (FileReader) and fills the spec text, so the
graph stays the single versioned source of truth for the environment.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.recipe import PythonEnv, RecipeExecution
from app.models.user import User
from app.models.workspace import Workspace
from app.services.recipe_envs import (
    RecipeError,
    build_env,
    build_env_spec,
    evict_env,
    resolve_env,
    serialize_env,
)
from app.services.recipe_executions import (
    RECIPE_ENV_BUILD_TASK,
    request_cancel,
    serialize_execution,
)

envs_router = APIRouter()
executions_router = APIRouter()


def _raise_recipe(exc: RecipeError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _feature_payload() -> dict[str, Any]:
    return {"enabled": bool(settings.recipe_execution_enabled)}


class EnvResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements_text: str = Field(default="", max_length=60_000)
    index_url: Optional[str] = Field(default=None, max_length=500)
    extra_index_urls: list[str] = Field(default_factory=list, max_length=8)


def _get_env_or_404(
    db: DBSession, *, env_id: str, workspace_id: str
) -> PythonEnv:
    env = (
        db.query(PythonEnv)
        .filter(PythonEnv.id == env_id, PythonEnv.workspace_id == workspace_id)
        .first()
    )
    if env is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "recipe_env_not_found",
                "code": "RECIPE_ENV_NOT_FOUND",
                "message": "The Python environment does not exist in this workspace.",
            },
        )
    return env


@envs_router.post("/resolve")
async def resolve_python_env(
    body: EnvResolveBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Normalize a spec and return its (existing or newly pending) env row."""

    try:
        spec = build_env_spec(
            requirements_text=body.requirements_text,
            index_url=body.index_url,
            extra_index_urls=body.extra_index_urls,
        )
        env = resolve_env(db, workspace_id=workspace.id, spec=spec)
    except RecipeError as exc:
        _raise_recipe(exc)
    db.commit()
    return {"env": serialize_env(env), "feature": _feature_payload()}


@envs_router.get("")
async def list_python_envs(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    envs = (
        db.query(PythonEnv)
        .filter(PythonEnv.workspace_id == workspace.id)
        .order_by(PythonEnv.created_at.desc())
        .limit(200)
        .all()
    )
    return {"envs": [serialize_env(env) for env in envs], "feature": _feature_payload()}


@envs_router.get("/{env_id}")
async def get_python_env(
    env_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    env = _get_env_or_404(db, env_id=env_id, workspace_id=workspace.id)
    return {"env": serialize_env(env), "feature": _feature_payload()}


@envs_router.post("/{env_id}/build")
async def build_python_env(
    env_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Kick an async prebuild ('prepare now'); the row status is the tracker."""

    env = _get_env_or_404(db, env_id=env_id, workspace_id=workspace.id)
    if not settings.recipe_execution_enabled:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "recipe_execution_disabled",
                "code": "RECIPE_EXECUTION_DISABLED",
                "message": "Recipe execution is not enabled on this deployment.",
            },
        )
    if env.status in {"ready", "building"}:
        return {"env": serialize_env(env), "dispatched": False}
    if settings.worker_eager_mode:
        try:
            env = build_env(db, env.id)
        except RecipeError as exc:
            _raise_recipe(exc)
        return {"env": serialize_env(env), "dispatched": True}
    from app.workers.celery_app import celery_app

    celery_app.send_task(
        RECIPE_ENV_BUILD_TASK,
        args=(env.id,),
        queue=settings.celery_task_default_queue,
    )
    return {"env": serialize_env(env), "dispatched": True}


@envs_router.delete("/{env_id}")
async def evict_python_env(
    env_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Manual eviction: frees the disk bytes, keeps the row + lock for rebuilds."""

    env = _get_env_or_404(db, env_id=env_id, workspace_id=workspace.id)
    active = (
        db.query(RecipeExecution)
        .filter(
            RecipeExecution.env_id == env.id,
            RecipeExecution.status.in_(("queued", "env_building", "running")),
        )
        .count()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "recipe_env_in_use",
                "code": "RECIPE_ENV_IN_USE",
                "message": "The environment is referenced by an active execution.",
            },
        )
    if env.status == "building":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "recipe_env_building",
                "code": "RECIPE_ENV_BUILDING",
                "message": "The environment is being prepared; retry once settled.",
            },
        )
    evict_env(db, env, reason="manual")
    return {"env": serialize_env(env)}


def _get_execution_or_404(
    db: DBSession, *, execution_id: str, workspace_id: str
) -> RecipeExecution:
    execution = (
        db.query(RecipeExecution)
        .filter(
            RecipeExecution.id == execution_id,
            RecipeExecution.workspace_id == workspace_id,
        )
        .first()
    )
    if execution is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "recipe_execution_not_found",
                "code": "RECIPE_EXECUTION_NOT_FOUND",
                "message": "The execution does not exist in this workspace.",
            },
        )
    return execution


@executions_router.get("")
async def list_recipe_executions(
    run_id: Optional[str] = Query(default=None, max_length=36),
    node_id: Optional[str] = Query(default=None, max_length=160),
    limit: int = Query(default=20, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    query = db.query(RecipeExecution).filter(
        RecipeExecution.workspace_id == workspace.id
    )
    if run_id:
        query = query.filter(RecipeExecution.run_id == run_id)
    if node_id:
        query = query.filter(RecipeExecution.node_id == node_id)
    executions = query.order_by(RecipeExecution.created_at.desc()).limit(limit).all()
    return {"executions": [serialize_execution(item) for item in executions]}


@executions_router.get("/{execution_id}")
async def get_recipe_execution(
    execution_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    execution = _get_execution_or_404(
        db, execution_id=execution_id, workspace_id=workspace.id
    )
    return {"execution": serialize_execution(execution)}


@executions_router.post("/{execution_id}/cancel")
async def cancel_recipe_execution(
    execution_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    execution = _get_execution_or_404(
        db, execution_id=execution_id, workspace_id=workspace.id
    )
    execution = request_cancel(db, execution)
    return {"execution": serialize_execution(execution)}
