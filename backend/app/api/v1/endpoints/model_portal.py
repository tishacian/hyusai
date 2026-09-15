"""Models & Providers portal — live plane + workspace configuration (beta).

Exposes provider health, effective routing, ledger distribution, admin-gated
serving-node lifecycle, and workspace-scoped config (routing, cloud keys,
serving-node attach).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
import copy

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.system import System
from app.models.skill import Skill
from app.models.system_flow_draft import SystemFlowDraft
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.model_plane import distribution as distribution_service
from app.services.model_plane import providers as providers_service
from app.services.model_plane import serving_nodes as serving_nodes_service
from app.services.model_plane import workspace_config as ws_config
from app.services.workspace_features import feature_enabled
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.flow_skill_binding import resolve_flow_skill_binding, FlowSkillBindingError
from app.services.systems import flow_workbench

router = APIRouter()

FEATURE_FLAG = "model_portal_beta"


def _require_enabled(workspace: Workspace) -> None:
    if not feature_enabled(workspace, FEATURE_FLAG, csv_fallback="agentium-showcase"):
        raise HTTPException(
            status_code=403,
            detail={"code": "MODEL_PORTAL_DISABLED", "message": "Model portal is not enabled for this workspace"},
        )


def _can_configure(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == getattr(user, "id", None),
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    return bool(membership and is_admin_template(
        getattr(membership, "role_template", None), membership.role,
    ))


def _require_workspace_admin(db: DBSession, *, user: User, workspace: Workspace) -> None:
    if not _can_configure(db, user=user, workspace=workspace):
        raise HTTPException(403, detail={"code": "MODEL_PORTAL_ADMIN_REQUIRED", "message": "Admin access required"})


def _test_blockers(db: DBSession, *, user: User, workspace: Workspace) -> list[dict[str, str]]:
    if not _can_configure(db, user=user, workspace=workspace):
        return [{"code": "MODEL_PORTAL_ADMIN_REQUIRED", "message": "An administrator can run a model test in a System."}]
    try:
        flow_workbench.require_flow_workbench(workspace)
    except flow_workbench.FlowWorkbenchError as exc:
        return [{"code": exc.code, "message": exc.message}]
    return []


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
    default_provider: str = Field(..., min_length=1, max_length=80)
    default_model: str = Field(..., min_length=1, max_length=256)
    fallback_chain: Optional[List[str]] = Field(default=None, max_length=10)


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
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    nodes = await serving_nodes_service.list_nodes(sync_registry=True, workspace=workspace)
    providers = await providers_service.list_providers(
        include_local_serving=True,
        workspace=workspace, node_snapshots=nodes.get("nodes", []),
    )
    return {"providers": providers, "can_configure": _can_configure(db, user=user, workspace=workspace)}


@router.get("/routing")
async def get_model_routing(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    nodes = await serving_nodes_service.list_nodes(sync_registry=True, workspace=workspace)
    local_serving = providers_service.scoped_serving_providers(nodes.get("nodes", []))
    provider_catalog = await providers_service.list_providers(include_local_serving=False, workspace=workspace)
    ws_routing = ws_config.get_routing(workspace)
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id)
        .order_by(System.name.asc())
        .all()
    )
    from app.api.v1.endpoints.systems import _enforce_system_read
    from app.services.model_plane.execution import ModelExecutionError
    readable = []
    model_usage = []
    for system in systems:
        try:
            _enforce_system_read(db, user=user, workspace=workspace, system=system)
        except HTTPException:
            continue
        readable.append(system)
        flow = _test_flow(db, system=system, workspace=workspace)
        for node in flow.get("nodes", []):
            if not isinstance(node, dict):
                continue
            skill = _test_skill(db, system=system, workspace=workspace, node=node)
            if skill is None:
                continue
            try:
                resolved = _node_model(workspace, system, skill, node, {})
            except ModelExecutionError:
                continue
            if resolved is not None:
                model_usage.append({
                    "system_id": system.id, "system_name": system.name,
                    "node_id": node.get("id"), "node_label": node.get("label") or node.get("id"),
                    "skill_slug": skill.slug, "configuration_source": "current_flow", "source": "current_flow",
                    **resolved.public(),
                })
    return {
        "model_usage": model_usage,
        "default_provider": ws_routing["default_provider"],
        "default_model": ws_routing["default_model"],
        "ollama_default_model": settings.ollama_default_model,
        "primary": {
            "provider": ws_routing["default_provider"],
            "model": ws_routing["default_model"],
        },
        "fallback_chain": ws_routing["fallback_chain"],
        "source": ws_routing["source"],
        "runtime_providers": sorted(providers_service.RUNTIME_PROVIDERS),
        "compatibility": providers_service.model_compatibility(ws_routing["default_provider"], ws_routing["default_model"]),
        "registered_clients": sorted(row["key"] for row in provider_catalog if row.get("configured") and row.get("runtime_available")),
        "registered_clients_source": "workspace_configuration",
        "local_serving": local_serving,
        "systems": [
            {
                "id": system.id,
                "name": system.name,
                "default_model": system.default_model,
                "status": system.status,
            }
            for system in readable
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
        raise HTTPException(status_code=400, detail={"code": "MODEL_PORTAL_CONFIG_INVALID", "message": str(exc)}) from exc
    return config["routing"]


@router.get("/config")
async def get_portal_config(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    blockers = _test_blockers(db, user=user, workspace=workspace)
    return {
        **ws_config.get_public_config(workspace),
        "can_configure": _can_configure(db, user=user, workspace=workspace),
        "runtime_providers": sorted(providers_service.RUNTIME_PROVIDERS),
        "can_test": not blockers,
        "test_blockers": blockers,
    }


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
        raise HTTPException(status_code=400, detail={"code": "MODEL_PORTAL_CONFIG_INVALID", "message": str(exc)}) from exc
    providers_service.clear_health_cache(workspace=workspace)
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
        raise HTTPException(status_code=400, detail={"code": "MODEL_PORTAL_CONFIG_INVALID", "message": str(exc)}) from exc
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
        raise HTTPException(status_code=400, detail={"code": "MODEL_PORTAL_CONFIG_INVALID", "message": str(exc)}) from exc
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
            window=window, workspace=workspace, user=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "MODEL_PORTAL_CONFIG_INVALID", "message": str(exc)}) from exc


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


@router.post("/providers/{provider}/test")
async def test_provider_connection(
    provider: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user=user, workspace=workspace)
    if provider not in (*ws_config.CLOUD_PROVIDERS, "ollama"):
        raise HTTPException(404, detail={"code": "MODEL_PROVIDER_NOT_FOUND", "message": "Provider not found"})
    providers_service.clear_health_cache(workspace=workspace)
    rows = await providers_service.list_providers(workspace=workspace, include_local_serving=False, provider_key=provider)
    result = next(row for row in rows if row["key"] == provider)
    return {"provider": result, "test_kind": "connection", "generation_verified": False}


@router.get("/resolve")
async def resolve_model_preview(
    provider: str = Query(min_length=1, max_length=80),
    model: str | None = Query(default=None, max_length=256),
    system_id: str | None = Query(default=None, max_length=36),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    from app.services.model_plane.execution import ModelExecutionError, resolve_skill_model_execution
    from app.api.v1.endpoints.systems import _enforce_system_read

    _require_enabled(workspace)
    system_default = None
    if system_id:
        system = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
        if system is None:
            raise HTTPException(404, detail={"code": "SYSTEM_NOT_FOUND", "message": "System not found"})
        _enforce_system_read(db, user=user, workspace=workspace, system=system)
        system_default = system.default_model
    try:
        resolution = resolve_skill_model_execution(
            workspace, executor={"kind": "prompt_template", "params": {"provider": provider, **({"model": model} if model else {})}},
            input_ref={}, system_default_model=system_default,
        )
        return resolution.public()
    except ModelExecutionError as exc:
        raise HTTPException(400, detail={"code": getattr(exc, "code", "MODEL_EXECUTION_INVALID"), "message": str(exc)}) from exc


class ModelTestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_id: str = Field(min_length=1, max_length=36)
    node_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=256)
    expected_flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_ref: dict[str, Any] = Field(default_factory=dict)
    acknowledge_real_side_effects: Literal[True]

    @field_validator("acknowledge_real_side_effects", mode="before")
    @classmethod
    def explicit_test_action(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("acknowledge_real_side_effects must be the boolean true")
        return value


def _test_flow(db: DBSession, *, system: System, workspace: Workspace) -> dict[str, Any]:
    draft = db.query(SystemFlowDraft).filter(
        SystemFlowDraft.system_id == system.id, SystemFlowDraft.workspace_id == workspace.id,
    ).first()
    return copy.deepcopy(draft.flow_definition if draft is not None else system.flow_definition or {})


def _test_skill(db: DBSession, *, system: System, workspace: Workspace, node: dict[str, Any], lock: bool = False) -> Skill | None:
    if node.get("kind", "task") != "task":
        return None
    try:
        binding = resolve_flow_skill_binding(node)
    except FlowSkillBindingError:
        return None
    clauses = []
    if binding.skill_id:
        clauses.append(Skill.id == binding.skill_id)
    if binding.skill_slug:
        clauses.append(Skill.slug == binding.skill_slug)
    if not clauses:
        return None
    query = db.query(Skill).filter(
        or_(*clauses), or_(Skill.workspace_id == workspace.id, Skill.workspace_id.is_(None)),
    )
    skill = (query.with_for_update(of=Skill) if lock else query).first()
    if skill is None or skill.id not in (system.skill_ids or []):
        return None
    if binding.skill_id and skill.id != binding.skill_id or binding.skill_slug and skill.slug != binding.skill_slug:
        return None
    return skill


def _node_model(workspace: Workspace, system: System, skill: Skill, node: dict[str, Any], inputs: dict[str, Any]):
    from app.services.model_plane.execution import resolve_skill_model_execution
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    params = config.get("params") if isinstance(config.get("params"), dict) else {}
    return resolve_skill_model_execution(
        workspace, executor=skill.executor, slug=skill.slug,
        input_ref={**params, **inputs}, system_default_model=system.default_model,
    )


@router.get("/test-targets")
async def model_test_targets(
    provider: str = Query(min_length=1, max_length=80),
    model: str = Query(min_length=1, max_length=256),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    from app.api.v1.endpoints.flow_workbench import _authorize
    from app.services.model_plane.execution import ModelExecutionError

    _require_enabled(workspace)
    blockers = _test_blockers(db, user=user, workspace=workspace)
    if blockers:
        return {"can_test": False, "blockers": blockers, "targets": []}
    targets = []
    systems = db.query(System).filter(System.workspace_id == workspace.id).order_by(System.name).limit(100).all()
    for system in systems:
        try:
            _authorize(db, system_id=system.id, workspace=workspace, user=user)
        except HTTPException:
            continue
        flow = _test_flow(db, system=system, workspace=workspace)
        for node in flow.get("nodes", []):
            if not isinstance(node, dict):
                continue
            skill = _test_skill(db, system=system, workspace=workspace, node=node)
            if skill is None:
                continue
            schema = skill.input_schema or {}
            defaults = {key: value["default"] for key, value in schema.get("properties", {}).items()
                        if isinstance(value, dict) and "default" in value}
            defaults.update((node.get("config") or {}).get("params") or {})
            if "model" in schema.get("properties", {}) or schema.get("additionalProperties") is True:
                defaults["model"] = model
            try:
                resolution = _node_model(workspace, system, skill, node, defaults)
            except ModelExecutionError:
                continue
            if resolution is None or (resolution.provider, resolution.model) != (provider, model):
                continue
            targets.append({
                "system_id": system.id, "system_name": system.name,
                "node_id": node["id"], "node_label": node.get("label") or node["id"],
                "skill_slug": skill.slug, "skill_name": skill.name,
                "provider": resolution.provider, "model": resolution.model,
                "input_schema": schema, "input_defaults": defaults,
                "expected_flow_sha256": canonical_flow_sha256(flow),
            })
            if len(targets) >= 50:
                return {"can_test": True, "blockers": [], "targets": targets, "truncated": True}
    return {"can_test": True, "blockers": [], "targets": targets, "truncated": len(systems) == 100}


@router.post("/test", status_code=201)
async def test_model_in_system(
    body: ModelTestBody,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    from app.api.v1.endpoints.flow_workbench import _authorize, WorkbenchNodeBody, create_node_preview_run
    from app.services.model_plane.execution import ModelExecutionError

    _require_enabled(workspace)
    system = _authorize(db, system_id=body.system_id, workspace=workspace, user=user)
    system = db.query(System).filter(System.id == system.id, System.workspace_id == workspace.id).populate_existing().with_for_update(of=System).one()
    flow = _test_flow(db, system=system, workspace=workspace)
    if canonical_flow_sha256(flow) != body.expected_flow_sha256:
        raise HTTPException(409, detail={"code": "MODEL_TEST_FLOW_CHANGED", "message": "Reload the test target: its Flow has changed."})
    nodes = [node for node in flow.get("nodes", []) if isinstance(node, dict) and node.get("id") == body.node_id]
    skill = _test_skill(db, system=system, workspace=workspace, node=nodes[0], lock=True) if len(nodes) == 1 else None
    if skill is None:
        raise HTTPException(404, detail={"code": "MODEL_TEST_TARGET_NOT_FOUND", "message": "Choose an authorized LLM node in this System."})
    try:
        resolution = _node_model(workspace, system, skill, nodes[0], body.input_ref)
    except ModelExecutionError as exc:
        raise HTTPException(400, detail={"code": getattr(exc, "code", "MODEL_EXECUTION_INVALID"), "message": str(exc)}) from exc
    if resolution is None or (resolution.provider, resolution.model) != (body.provider, body.model):
        raise HTTPException(409, detail={"code": "MODEL_TEST_BINDING_MISMATCH", "message": "The selected node does not resolve to this provider and model. Reload its definition."})
    payload = await create_node_preview_run(
        system_id=system.id, body=WorkbenchNodeBody(
            acknowledge_real_side_effects=body.acknowledge_real_side_effects,
            flow_definition=flow, expected_flow_sha256=body.expected_flow_sha256,
            node_id=body.node_id, input_ref=body.input_ref,
        ), background_tasks=background_tasks, workspace=workspace, user=user, db=db,
    )
    return {**payload, "run_url": f"/runs/{payload['id']}", "requested": {"provider": body.provider, "model": body.model}}
