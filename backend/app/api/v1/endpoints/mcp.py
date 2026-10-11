"""MCP connector API (workspace-gated, multi-server)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp import preview as mcp_preview
from app.services.connectors.mcp import read as mcp_read
from app.services.connectors.mcp import service as mcp_service
from app.services.connectors.mcp import write as mcp_write
from app.services.connectors.mcp.errors import McpError

router = APIRouter()


def _is_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> bool:
    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
        .first()
    )
    return bool(membership) and is_admin_template(getattr(membership, "role_template", None), membership.role)


def _require_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> None:
    """Server definitions carry the endpoint and the token URL the shared secret goes to."""
    if not _is_workspace_admin(db, user, workspace):
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})


class McpSharedAuthUpsert(BaseModel):
    oauth_token_url: Optional[str] = Field(default="", max_length=1024)
    oauth_client_id: Optional[str] = Field(default="", max_length=512)
    oauth_client_secret: Optional[str] = Field(default=None, max_length=4096)
    oauth_scope: Optional[str] = Field(default="", max_length=1024)


class McpServerUpsert(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    label: Optional[str] = Field(default=None, max_length=256)
    transport: str = Field(default="http_sse", max_length=32)
    url: Optional[str] = Field(default="", max_length=1024)
    token: Optional[str] = Field(default=None, max_length=4096)
    enabled: bool = True
    tool_aliases: Optional[dict[str, str]] = None
    auth_mode: Optional[str] = Field(default="bearer", max_length=64)
    oauth_token_url: Optional[str] = Field(default="", max_length=1024)
    oauth_client_id: Optional[str] = Field(default="", max_length=512)
    oauth_client_secret: Optional[str] = Field(default=None, max_length=4096)
    oauth_scope: Optional[str] = Field(default="", max_length=1024)


class McpServersReplace(BaseModel):
    servers: list[McpServerUpsert]
    shared_auth: Optional[McpSharedAuthUpsert] = None


class McpReadRequest(BaseModel):
    tool: str = Field(..., min_length=1, max_length=256)
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpInvokeRequest(BaseModel):
    tool: str = Field(..., min_length=1, max_length=256)
    arguments: dict[str, Any] = Field(default_factory=dict)
    #: ``BAPI_PO_CREATE1`` only — run the commit in the same gate call so the
    #: caller never holds a created-but-uncommitted PO.
    commit: bool = False
    #: Guardrail names the human switched off; the gate answers ``blocked``.
    disabled_tools: list[str] = Field(default_factory=list)


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
        if exc.code == "mcp_preview_unavailable":
            status = 409
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
    _require_workspace_admin(db, user, workspace)
    try:
        payload: dict = {
            "servers": [item.model_dump(exclude_unset=True) for item in body.servers],
        }
        if body.shared_auth is not None:
            payload["shared_auth"] = body.shared_auth.model_dump(exclude_unset=True)
        return mcp_service.replace_servers(db, workspace, payload)
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
    _require_workspace_admin(db, user, workspace)
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


@router.get("/servers/{server_id}/preview")
async def preview_mcp_server(
    server_id: str,
    tool: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    """One read-only sample call. Never invokes write tools."""
    _require_enabled(workspace)
    try:
        server = mcp_service.resolve_server(workspace, server_id)
        return mcp_preview.preview_server(server, tool_name=tool)
    except Exception as exc:  # noqa: BLE001
        _raise_mcp(exc)
        raise  # pragma: no cover


@router.post("/servers/{server_id}/read")
async def read_mcp_server(
    server_id: str,
    body: McpReadRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    """Keyed read-only ``tools/call``. Write tools never run. Preview stays keyless."""
    _require_enabled(workspace)
    try:
        server = mcp_service.resolve_server(workspace, server_id)
        return mcp_read.read_tool(server, tool=body.tool, arguments=body.arguments)
    except Exception as exc:  # noqa: BLE001
        _raise_mcp(exc)
        raise  # pragma: no cover


@router.post("/servers/{server_id}/invoke")
async def invoke_mcp_server(
    server_id: str,
    body: McpInvokeRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """One allow-listed write ``tools/call``, live only with ``sap_write_unsealed``.

    With the flag off the response is the sealed envelope — same shape the
    approval gate shows — and no connection is opened, so the server does not
    even need to be attached. Every unsealed call lands in the audit ledger.
    Only a workspace administrator's call is attended: this route has no
    approval gate, so for anyone else the write stays sealed.
    """
    _require_enabled(workspace)
    unsealed = mcp_write.workspace_write_unsealed(workspace)
    attended = _is_workspace_admin(db, user, workspace)
    try:
        server = mcp_service.resolve_server(workspace, server_id) if unsealed and attended else None
        if body.commit and body.tool.strip() == mcp_write.BAPI_CREATE:
            out = mcp_write.create_and_commit_po(
                server,
                server_id=server_id,
                arguments=body.arguments,
                unsealed=unsealed,
                blocked_tools=body.disabled_tools,
                attended=attended,
            )
        else:
            out = mcp_write.invoke_write_tool(
                server,
                server_id=server_id,
                tool=body.tool,
                arguments=body.arguments,
                unsealed=unsealed,
                blocked_tools=body.disabled_tools,
                attended=attended,
            )
    except Exception as exc:  # noqa: BLE001
        _raise_mcp(exc)
        raise  # pragma: no cover
    mcp_write.audit_write(
        str(workspace.id),
        actor=str(getattr(user, "email", "") or getattr(user, "id", "") or "system"),
        server_id=server_id,
        out=out,
    )
    return out
