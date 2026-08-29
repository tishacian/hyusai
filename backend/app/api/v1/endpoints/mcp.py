"""MCP connector API (workspace-gated, multi-server)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp import service as mcp_service
from app.services.connectors.mcp.errors import McpError

router = APIRouter()


class McpServerUpsert(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    label: Optional[str] = Field(default=None, max_length=256)
    transport: str = Field(default="http_sse", max_length=32)
    url: Optional[str] = Field(default="", max_length=1024)
    token: Optional[str] = Field(default=None, max_length=4096)
    enabled: bool = True
    tool_aliases: Optional[dict[str, str]] = None


class McpServersReplace(BaseModel):
    servers: list[McpServerUpsert]


def _require_enabled(workspace: Workspace) -> None:
    if not mcp_service.is_workspace_enabled(workspace):
        raise HTTPException(
            status_code=403,
            detail="MCP connector is not enabled for this workspace",
        )


def _raise_mcp(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, mcp_service.EncryptionNotConfigured):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if isinstance(exc, McpError):
        status = 400 if exc.code == "mcp_unconfigured" else 502
        if exc.code == "mcp_tool_unknown":
            status = 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=f"MCP call failed: {exc}") from exc


@router.get("/servers")
async def list_mcp_servers(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    return mcp_service.get_servers(workspace)


@router.put("/servers")
async def put_mcp_servers(
    body: McpServersReplace,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    try:
        return mcp_service.replace_servers(
            db,
            workspace,
            {"servers": [item.model_dump(exclude_unset=True) for item in body.servers]},
        )
    except Exception as exc:  # noqa: BLE001
        _raise_mcp(exc)
        raise  # pragma: no cover


@router.put("/servers/{server_id}")
async def put_mcp_server(
    server_id: str,
    body: McpServerUpsert,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    payload = body.model_dump(exclude_unset=True)
    payload["id"] = server_id
    try:
        return mcp_service.upsert_server(db, workspace, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_mcp(exc)
        raise  # pragma: no cover


@router.post("/servers/{server_id}/test")
async def test_mcp_server(
    server_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    try:
        server = mcp_service.resolve_server(workspace, server_id)
        return mcp_client.test_connection(server)
    except Exception as exc:  # noqa: BLE001
        _raise_mcp(exc)
        raise  # pragma: no cover


@router.get("/servers/{server_id}/tools")
async def list_mcp_server_tools(
    server_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    """Capped ``tools/list``. Names the contract gap. Does not create skills."""
    _require_enabled(workspace)
    try:
        server = mcp_service.resolve_server(workspace, server_id)
        return mcp_client.list_tools(server)
    except Exception as exc:  # noqa: BLE001
        _raise_mcp(exc)
        raise  # pragma: no cover
