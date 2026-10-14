"""A Flow/agent may request a reviewed write; this Skill never sends it."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.connectors.connections import ConnectionError


class ConnectorWriteRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection_id: str = Field(min_length=1, max_length=36)
    dataset_id: str | None = Field(default=None, min_length=1, max_length=36)
    operation: Literal["write_append", "write_overwrite", "write_upsert", "export", "tool_write"]
    request_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")
    parameters: dict[str, Any]


def request_write(db, payload, ctx):
    from app.core.config import settings
    from app.models.run import Run
    from app.models.user import User
    from app.services.connectors import writes

    if not settings.connector_framework_enabled:
        raise ConnectionError("CONNECTOR_FRAMEWORK_DISABLED", 404)
    request = ConnectorWriteRequestInput.model_validate(payload)
    workspace_id, user_id, run_id = ctx.get("workspace_id"), ctx.get("user_id"), ctx.get("run_id")
    if not workspace_id:
        raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
    if run_id:
        run = db.get(Run, run_id, populate_existing=True)
        if (
            run is None
            or run.workspace_id != workspace_id
            or run.status in {"failed", "cancelled"}
            or (user_id and user_id != run.initiated_by_user_id)
            or (ctx.get("system_id") and ctx["system_id"] != run.system_id)
        ):
            raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
        user_id = run.initiated_by_user_id
    elif ctx.get("system_id"):
        raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
    user = db.get(User, user_id, populate_existing=True) if user_id else None
    if not user or not user.is_active:
        # Personal System delegations authorize reads only, never source writes.
        raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
    identity = [workspace_id, user.id, run_id, ctx.get("_skill_node_id"), request.request_key]
    key = (
        "skill:" + hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    )
    row = writes.prepare(
        db,
        workspace_id=workspace_id,
        user=user,
        connection_id=request.connection_id,
        operation=request.operation,
        dataset_id=request.dataset_id,
        parameters=request.parameters,
        request_key=key,
        origin={"run_id": run_id, "node_id": ctx.get("_skill_node_id")} if run_id else None,
    )
    preview_id = None
    if row.state in {"prepared", "approved"}:
        preview_id = writes.dispatch_preview(
            db, workspace_id=workspace_id, user=user, operation_id=row.id
        )["id"]
    result = {
        "write_operation_id": row.id,
        "contract_digest": row.contract_digest,
        "state": row.state,
        "preview_compute_run_id": preview_id,
        "approval_required": row.state not in {"applied", "abandoned", "failed"},
        "contract": row.contract,
    }
    db.commit()
    return result
