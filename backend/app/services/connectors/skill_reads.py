"""Read-only canonical Skill gateway to the durable connector registry.

The payload selects a resource; authority comes from the authenticated context
and, for Flow calls, the persisted Run. Drivers and credentials stay in workers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.connectors.connections import ConnectionError


class Partitions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    column: str = Field(min_length=1, max_length=127)
    count: int = Field(ge=1, le=32)


class Incremental(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    watermark_column: str = Field(min_length=1, max_length=127)
    key_column: str = Field(min_length=1, max_length=127)
    type: Literal["integer", "timestamp"]
    overlap: int = Field(default=0, ge=0, le=31_536_000)


class ReadParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_name: str | None = Field(default=None, alias="schema", max_length=255)
    table: str | None = Field(default=None, max_length=255)
    columns: list[str] | None = Field(default=None, max_length=2000)
    limit: int | None = Field(default=None, ge=1, le=1000)
    max_rows: int | None = Field(default=None, ge=1)
    max_bytes: int | None = Field(default=None, ge=1)
    prefix: str | None = Field(default=None, max_length=2048)
    key: str | None = Field(default=None, max_length=2048)
    cursor: str | None = Field(default=None, max_length=8192)
    max_objects: int | None = Field(default=None, ge=1, le=10000)
    filter: dict[str, Any] | None = None
    token_start: int | None = None
    token_end: int | None = None
    operation_id: str | None = Field(default=None, max_length=255)
    arguments: dict[str, Any] | None = None
    partitions: Partitions | None = None
    incremental: Incremental | None = None
    require_consistency: Literal["snapshot", "per_partition", "none"] | None = None
    previous_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ConnectorReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection_id: str = Field(min_length=1, max_length=36)
    operation: Literal["catalog", "table", "preview", "import", "status"]
    parameters: ReadParameters = Field(default_factory=ReadParameters)
    compute_run_id: str | None = Field(default=None, min_length=1, max_length=36)
    delegation_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def status_reference(self):
        if (self.operation == "status") != bool(self.compute_run_id):
            raise ValueError("status requires a compute_run_id; dispatch forbids it")
        if self.operation == "status" and self.parameters.model_fields_set:
            raise ValueError("status does not accept query parameters")
        return self


def validate_parameters(profile, parameters, *, operation=None):
    accepted = {"schema", "table", "columns", "limit", "max_rows", "max_bytes"}
    if profile.family in {"mcp", "openapi"}:
        accepted = {"operation_id", "arguments"}
    elif profile.family in {"uc_rest", "delta_sharing", "iceberg_rest"}:
        accepted = {"schema", "table", "limit", "max_rows", "max_bytes"}
    elif profile.family == "object_store":
        accepted = {
            "prefix",
            "key",
            "cursor",
            "limit",
            "max_rows",
            "max_bytes",
            "max_objects",
            "previous_fingerprint",
        }
    elif profile.family in {"document", "search", "wide_column"}:
        accepted = {
            "schema",
            "table",
            "filter",
            "limit",
            "max_rows",
            "max_bytes",
            "token_start",
            "token_end",
        }
    # Advanced reads use generated SQL only, never caller-supplied bounds.
    if profile.family in {"dbapi", "sqlalchemy", "adbc"}:
        accepted.update({"partitions", "incremental"})
    if profile.family not in {"mcp", "openapi"}:
        accepted.add("require_consistency")
    if not isinstance(parameters, dict) or set(parameters) - accepted:
        raise ConnectionError("CONNECTOR_PARAMETERS_INVALID")
    try:
        parsed = ReadParameters.model_validate(parameters)
    except ValidationError:
        raise ConnectionError("CONNECTOR_PARAMETERS_INVALID") from None
    for name, capability in (
        ("partitions", "read_partitioned"),
        ("incremental", "read_incremental"),
    ):
        if getattr(parsed, name) is not None and (
            not getattr(profile.capabilities, capability) or operation not in (None, "import")
        ):
            raise ConnectionError("CONNECTOR_OPERATION_UNSUPPORTED", 409)
    if parsed.require_consistency is not None and operation not in (None, "import", "preview"):
        raise ConnectionError("CONNECTOR_CONSISTENCY_UNAVAILABLE", 409)
    return parsed.model_dump(by_alias=True, exclude_none=True)


def read(db, payload, ctx):
    from app.core.config import settings
    from app.models.connector_connection import ConnectorDelegation, ConnectorGrant
    from app.models.run import Run
    from app.models.system import System
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services import compute_runs
    from app.services.connectors import connections
    from app.services.connectors.profiles import get_profile
    from app.services.huggingface.access import can_import_dataset

    if not settings.connector_framework_enabled:
        raise ConnectionError("CONNECTOR_FRAMEWORK_DISABLED", 404)
    request = ConnectorReadInput.model_validate(payload)
    workspace_id = ctx.get("workspace_id")
    if not workspace_id:
        raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
    run_id, user_id = ctx.get("run_id"), ctx.get("user_id")
    system_id = version_id = None
    if run_id:
        run = db.get(Run, run_id, populate_existing=True)
        if (
            run is None
            or run.workspace_id != workspace_id
            or run.status in {"failed", "cancelled"}
            or (user_id and run.initiated_by_user_id != user_id)
            or (ctx.get("system_id") and ctx["system_id"] != run.system_id)
        ):
            raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
        user_id, system_id = run.initiated_by_user_id, run.system_id
        version_id = run.published_flow_version_id
    elif ctx.get("system_id"):
        # A System id alone is not an execution/delegation envelope.
        raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
    connection = connections.get_connection(db, workspace_id, request.connection_id)
    actor_id = user_id
    if not user_id:
        system = db.get(System, system_id, populate_existing=True) if system_id else None
        delegation = (
            db.get(ConnectorDelegation, request.delegation_id, populate_existing=True)
            if request.delegation_id
            else None
        )
        if (
            not run_id
            or not version_id
            or not system
            or system.workspace_id != workspace_id
            or system.published_flow_version_id != version_id
            or not delegation
            or connection.values.get("auth_mode") != "oauth_user"
        ):
            raise ConnectionError("CONNECTOR_GRANT_REQUIRED", 403)
        grant = db.get(ConnectorGrant, delegation.grant_id, populate_existing=True)
        actor_id = grant.owner_user_id if grant else None
    elif request.delegation_id:
        # An interactive user cannot substitute somebody else's delegation.
        raise ConnectionError("CONNECTOR_GRANT_REQUIRED", 403)
    identity = {
        "user_id": user_id,
        "system_id": system_id,
        "system_version_id": version_id,
        "delegation_id": request.delegation_id,
        "run_id": run_id,
    }
    connections.authorization_snapshot(db, connection, **identity)
    actor = db.get(User, actor_id, populate_existing=True) if actor_id else None
    workspace = db.get(Workspace, workspace_id, populate_existing=True)
    if actor is None or not actor.is_active:
        raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
    profile = get_profile(connection.profile_key)
    if not profile.capabilities.read:
        raise ConnectionError("CONNECTOR_OPERATION_UNSUPPORTED", 409)
    if request.operation == "status":
        row = compute_runs.get_run(db, workspace_id, request.compute_run_id)
        if (
            row.connection_id != connection.id
            or row.user_id != user_id
            or row.run_id != run_id
            or row.system_id != system_id
            or row.system_version_id != version_id
            or row.delegation_id != request.delegation_id
            or row.kind != "connector_read"
            or (ctx.get("_skill_node_id") and row.node_id != ctx["_skill_node_id"])
        ):
            raise ConnectionError("CONNECTOR_RUN_NOT_FOUND", 404)
        if row.connection_revision != connection.revision:
            raise ConnectionError("CONNECTOR_CONNECTION_CHANGED", 409)
        if row.operation == "import" and not can_import_dataset(db, actor, workspace):
            raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
    else:
        if request.operation == "import" and not can_import_dataset(db, actor, workspace):
            raise ConnectionError("CONNECTOR_ACTOR_FORBIDDEN", 403)
        if request.operation == "import" and profile.family in {"mcp", "openapi"}:
            raise ConnectionError("CONNECTOR_OPERATION_UNSUPPORTED", 409)
        parameters = request.parameters.model_dump(by_alias=True, exclude_none=True)
        parameters = validate_parameters(profile, parameters, operation=request.operation)
        deadline_at = None
        if run_id and ctx.get("_skill_node_id"):
            import math
            import time
            from datetime import datetime, timedelta

            flow_deadline = ctx.get("_run_deadline_monotonic")
            if isinstance(flow_deadline, (int, float)) and math.isfinite(flow_deadline):
                remaining = flow_deadline - time.monotonic()
                if remaining <= 0:
                    raise ConnectionError("CONNECTOR_TIMEOUT", 408)
                deadline_at = datetime.utcnow() + timedelta(seconds=min(remaining, 86_400))
        row = compute_runs.create_run(
            db,
            workspace_id=workspace_id,
            connection_id=connection.id,
            operation=request.operation,
            parameters=parameters,
            node_id=ctx.get("_skill_node_id"),
            deadline_at=deadline_at,
            **identity,
        )
        compute_runs.dispatch_run(db, row)
    result = compute_runs.serialize_run(row)
    db.commit()
    return {
        "compute_run_id": row.id,
        "connection_id": row.connection_id,
        "operation": row.operation,
        "status": row.status,
        "result": result["output"],
        "error_code": row.error_code,
    }


async def wait_for_result(initial, payload, ctx):
    """Flow nodes expose completed results; every poll rechecks current authority.

    Each database session ends before yielding to the event loop. Cancellation
    only addresses this already-authorized node's run, including after the
    actor's permission is revoked (cleanup must not require that permission).
    """
    import asyncio
    import math
    import time
    from datetime import datetime

    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.compute_run import TERMINAL_STATUSES, ComputeRun
    from app.services import compute_runs

    context = {key: value for key, value in ctx.items() if key != "db"}
    query = {
        "connection_id": initial["connection_id"],
        "compute_run_id": initial["compute_run_id"],
        "operation": "status",
        "parameters": {},
        "delegation_id": payload.get("delegation_id"),
    }
    deadline = time.monotonic() + min(settings.connector_max_timeout_s, 86_400)
    flow_deadline = context.get("_run_deadline_monotonic")
    if isinstance(flow_deadline, (int, float)) and math.isfinite(flow_deadline):
        deadline = min(deadline, flow_deadline)

    def cancel():
        with SessionLocal() as db:
            row = (
                db.query(ComputeRun)
                .filter_by(
                    id=initial["compute_run_id"],
                    workspace_id=context["workspace_id"],
                    connection_id=initial["connection_id"],
                    run_id=context["run_id"],
                    node_id=context["_skill_node_id"],
                    kind="connector_read",
                )
                .one_or_none()
            )
            if row is not None:
                compute_runs.request_cancel(db, row)

    try:
        while True:
            if time.monotonic() >= deadline:
                raise ConnectionError("CONNECTOR_TIMEOUT", 408)
            with SessionLocal() as db:
                result = read(db, query, context)
                row = db.get(ComputeRun, result["compute_run_id"])
                remaining = (row.deadline_at - datetime.utcnow()).total_seconds()
                deadline = min(deadline, time.monotonic() + remaining)
            if result["status"] == "succeeded":
                if not isinstance(result["result"], dict) or (
                    result["operation"] == "import"
                    and (
                        not isinstance(result["result"].get("dataset"), dict)
                        or not isinstance(result["result"]["dataset"].get("dataset_id"), str)
                    )
                ):
                    raise ConnectionError("CONNECTOR_RESULT_INVALID", 409)
                return result
            if result["status"] in TERMINAL_STATUSES:
                raise ConnectionError(result["error_code"] or "CONNECTOR_EXECUTION_FAILED", 409)
            if time.monotonic() >= deadline:
                raise ConnectionError("CONNECTOR_TIMEOUT", 408)
            await asyncio.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    except asyncio.CancelledError:
        try:
            cancel()
        finally:
            raise
    except Exception:
        cancel()
        raise
