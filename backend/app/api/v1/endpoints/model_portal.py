"""Models & Providers portal — live plane + workspace configuration (beta).

Exposes provider health, effective routing, ledger distribution, admin-gated
serving-node lifecycle, and workspace-scoped config (routing, cloud keys,
serving-node attach).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.model_plane import distribution as distribution_service
from app.services.model_plane import providers as providers_service
from app.services.model_plane import serving_nodes as serving_nodes_service
from app.services.model_plane import workspace_config as ws_config
from app.services.model_plane.registration import list_routable_providers
from app.services.model_router import ModelRouter
from app.services.workspace_features import feature_enabled

router = APIRouter()

FEATURE_FLAG = "model_portal_beta"


def _require_enabled(workspace: Workspace) -> None:
    if not feature_enabled(workspace, FEATURE_FLAG, csv_fallback="agentium-showcase"):
        raise HTTPException(
            status_code=403,
            detail="Model portal is not enabled for this workspace",
        )


def _require_workspace_admin(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> None:
    if getattr(user, "role", None) == "admin":
        return
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == getattr(user, "id", None),
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    if not membership or not is_admin_template(
        getattr(membership, "role_template", None),
        membership.role,
    ):
        raise HTTPException(status_code=403, detail="Admin access required")


class CreateInstanceBody(BaseModel):
    provider: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("provider", "engine"),
    )
    model: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    name: Optional[str] = None
    image: Optional[str] = None
    gpu_devices: Optional[List[str]] = None
    environment: Optional[Dict[str, str]] = None
    memory_limit: Optional[str] = "16g"
    shm_size: Optional[str] = "16g"
    auto_start: Optional[bool] = True
    quantization: Optional[str] = None


class RoutingUpdateBody(BaseModel):
    default_provider: str = Field(..., min_length=1)
    default_model: str = Field(..., min_length=1)
    fallback_chain: Optional[List[str]] = None


class CredentialUpdateBody(BaseModel):
    api_key: Optional[str] = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    endpoint: Optional[str] = Field(default=None, max_length=512)
    api_version: Optional[str] = Field(default=None, max_length=64)
    deployment: Optional[str] = Field(default=None, max_length=256)


class ServingNodeUpsertBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=512)
    token: Optional[str] = Field(default=None, max_length=512)


@router.get("/providers")
async def list_model_providers(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    await serving_nodes_service.list_nodes(sync_registry=True, workspace=workspace)
    providers = await providers_service.list_providers(
        include_local_serving=True,
        workspace=workspace,
    )
    return {"providers": providers}


@router.get("/routing")
async def get_model_routing(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    await serving_nodes_service.list_nodes(sync_registry=True, workspace=workspace)
    router_runtime = ModelRouter()
    ws_routing = ws_config.get_routing(workspace)
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id)
        .order_by(System.name.asc())
        .all()
    )
    return {
        "default_provider": ws_routing["default_provider"],
        "default_model": ws_routing["default_model"],
        "ollama_default_model": settings.ollama_default_model,
        "primary": {
            "provider": ws_routing["default_provider"],
            "model": ws_routing["default_model"],
        },
        "fallback_chain": ws_routing["fallback_chain"],
        "source": ws_routing["source"],
        "registered_clients": sorted(router_runtime.clients.keys()),
        "local_serving": list_routable_providers(),
        "systems": [
            {
                "id": system.id,
                "name": system.name,
                "default_model": system.default_model,
                "status": system.status,
            }
            for system in systems
        ],
    }


@router.put("/routing")
async def put_model_routing(
    body: RoutingUpdateBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        config = ws_config.set_routing(
            db,
            workspace,
            default_provider=body.default_provider,
            default_model=body.default_model,
            fallback_chain=body.fallback_chain,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return config["routing"]


@router.get("/config")
async def get_portal_config(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    return ws_config.get_public_config(workspace)


@router.put("/credentials/{provider}")
async def put_provider_credential(
    provider: str,
    body: CredentialUpdateBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        config = ws_config.set_cloud_credential(
            db,
            workspace,
            provider,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
            endpoint=body.endpoint,
            api_version=body.api_version,
            deployment=body.deployment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    providers_service.clear_health_cache()
    return {
        "cloud_credentials": config["cloud_credentials"],
        "provider": next(
            (c for c in config["cloud_credentials"] if c["key"] == provider),
            {"key": provider, "api_key_set": False},
        ),
    }


@router.put("/nodes")
async def upsert_serving_node(
    body: ServingNodeUpsertBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        config = ws_config.upsert_serving_node(
            db,
            workspace,
            name=body.name,
            base_url=body.base_url,
            token=body.token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"serving_nodes": config["serving_nodes"]}


@router.delete("/nodes/{node_name}")
async def detach_serving_node(
    node_name: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        config = ws_config.delete_serving_node(db, workspace, node_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"serving_nodes": config["serving_nodes"]}


@router.get("/distribution")
async def get_model_distribution(
    window: str = Query(default="7d", pattern="^(7d|30d)$"),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    try:
        return distribution_service.get_distribution(
            db,
            workspace_id=workspace.id,
            window=window,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/nodes")
async def list_serving_nodes(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    return await serving_nodes_service.list_nodes(
        sync_registry=True, workspace=workspace
    )


@router.post("/nodes/{node_name}/instances")
async def create_serving_instance(
    node_name: str,
    body: CreateInstanceBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        instance = await serving_nodes_service.create_instance(
            node_name,
            body.model_dump(exclude_none=True),
            workspace=workspace,
        )
    except serving_nodes_service.PortalClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"instance": instance}


@router.post("/nodes/{node_name}/instances/{instance_id}/start")
async def start_serving_instance(
    node_name: str,
    instance_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        result = await serving_nodes_service.start_instance(
            node_name, instance_id, workspace=workspace
        )
    except serving_nodes_service.PortalClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return result if isinstance(result, dict) else {"result": result}


@router.post("/nodes/{node_name}/instances/{instance_id}/stop")
async def stop_serving_instance(
    node_name: str,
    instance_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        result = await serving_nodes_service.stop_instance(
            node_name, instance_id, workspace=workspace
        )
    except serving_nodes_service.PortalClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return result if isinstance(result, dict) else {"result": result}


@router.delete("/nodes/{node_name}/instances/{instance_id}")
async def delete_serving_instance(
    node_name: str,
    instance_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        result = await serving_nodes_service.delete_instance(
            node_name, instance_id, workspace=workspace
        )
    except serving_nodes_service.PortalClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return result if isinstance(result, dict) else {"result": result}
