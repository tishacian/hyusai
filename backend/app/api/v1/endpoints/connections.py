"""Connection metadata and asynchronous execution handles; no database driver imports."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.connection import ConnectionCreate, ConnectionUpdate
from app.services.compute_runs import ComputeRunError
from app.services.connectors import connections as service
from app.services.connectors.profiles import ProfileError, list_profiles
from app.services.huggingface.access import can_import_dataset, is_workspace_admin
from app.services.secrets import SecretRegistryError


def _enabled():
    if not settings.connector_framework_enabled:
        raise HTTPException(status_code=404, detail={"code": "CONNECTOR_FRAMEWORK_DISABLED"})


router = APIRouter(dependencies=[Depends(_enabled)])


def _access(db, workspace, user, *, admin=False):
    if not user.is_active or not workspace.is_active or workspace.deleted_at:
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})
    if is_workspace_admin(db, user, workspace):
        return
    member = (
        db.query(WorkspaceMember.id).filter_by(workspace_id=workspace.id, user_id=user.id).first()
    )
    if admin or not member:
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})


def _call(db, fn, *, mutate=False):
    try:
        value = fn()
        if mutate:
            db.commit()
        return value
    except (
        service.ConnectionError,
        ComputeRunError,
        ProfileError,
        SecretRegistryError,
        ValidationError,
        IntegrityError,
    ) as exc:
        if mutate:
            db.rollback()
        code = getattr(
            exc,
            "code",
            "CONNECTOR_CONFLICT" if isinstance(exc, IntegrityError) else "CONNECTOR_INVALID",
        )
        status = getattr(exc, "status_code", 409 if isinstance(exc, IntegrityError) else 400)
        # Never return exception text or validation input: it may contain credentials.
        raise HTTPException(status_code=status, detail={"code": code}) from exc


@router.get("/tool-catalog")
def tool_catalog(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import yaml

    from app.services.connectors.profiles import PROFILE_DIRECTORY

    _access(db, workspace, user)
    catalog = yaml.safe_load((PROFILE_DIRECTORY.parent / "mcp_catalog.yaml").read_text())
    return {"servers": [entry | {"certification": "third_party"} for entry in catalog["servers"]]}


@router.get("/profiles")
def profiles(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return {
        "profiles": [
            p.model_dump(mode="json")
            | {
                "digest": p.digest,
                "certification": "third_party" if p.family in {"mcp", "openapi"} else "unverified",
                "driver_status": "runner_unchecked",
            }
            for p in list_profiles()
        ]
    }


@router.get("")
def listing(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return {
        "connections": [
            service.serialize_connection(c) for c in service.list_connections(db, workspace.id)
        ],
        "can_configure": is_workspace_admin(db, user, workspace),
        "can_import": can_import_dataset(db, user, workspace),
    }


@router.post("", status_code=201)
def create(
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return _call(
        db,
        lambda: service.serialize_connection(
            service.create_connection(
                db,
                workspace_id=workspace.id,
                actor=user.id,
                data=ConnectionCreate.model_validate(body),
            )
        ),
        mutate=True,
    )


@router.get("/{connection_id}")
def detail(
    connection_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return _call(
        db,
        lambda: service.serialize_connection(
            service.get_connection(db, workspace.id, connection_id)
        ),
    )


@router.put("/{connection_id}")
def update(
    connection_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return _call(
        db,
        lambda: service.serialize_connection(
            service.update_connection(
                db,
                service.get_connection(db, workspace.id, connection_id),
                actor=user.id,
                data=ConnectionUpdate.model_validate(body),
            )
        ),
        mutate=True,
    )


@router.delete("/{connection_id}")
def delete(
    connection_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)

    def remove():
        service.delete_connection(
            db, service.get_connection(db, workspace.id, connection_id), actor=user.id
        )
        return {"status": "deleted"}

    return _call(db, remove, mutate=True)


def _submit(connection_id, operation, body, workspace, user, db):
    from app.services import compute_runs
    from app.services.connectors.profiles import get_profile
    from app.services.huggingface.access import can_import_dataset

    _access(db, workspace, user, admin=operation == "test")
    if operation == "import" and not can_import_dataset(db, user, workspace):
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"code": "CONNECTOR_PARAMETERS_INVALID"})

    def submit():
        connection = service.get_connection(db, workspace.id, connection_id)
        profile = get_profile(connection.profile_key)
        if not profile.capabilities.read or (
            operation == "watch" and not profile.capabilities.watch
        ):
            raise service.ConnectionError("CONNECTOR_OPERATION_UNSUPPORTED", 409)
        from app.services.connectors.skill_reads import validate_parameters

        parameters = validate_parameters(profile, body, operation=operation)
        row = compute_runs.create_run(
            db,
            workspace_id=workspace.id,
            user_id=user.id,
            connection_id=connection.id,
            operation=operation,
            parameters=parameters,
        )
        compute_runs.dispatch_run(db, row)
        return compute_runs.serialize_run(row)

    return _call(db, submit, mutate=True)


@router.post("/{connection_id}/list", status_code=202)
def list_source(
    connection_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _submit(connection_id, "catalog", body, workspace, user, db)


@router.post("/{connection_id}/watch", status_code=202)
def watch(
    connection_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _submit(connection_id, "watch", body, workspace, user, db)


@router.post("/{connection_id}/test", status_code=202)
def test(
    connection_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _submit(connection_id, "test", {}, workspace, user, db)


@router.get("/{connection_id}/catalog", status_code=202)
def catalog(
    connection_id: str,
    schema: str | None = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _submit(
        connection_id,
        "catalog",
        {"schema": schema} if schema is not None else {},
        workspace,
        user,
        db,
    )


@router.get("/{connection_id}/table", status_code=202)
def table(
    connection_id: str,
    schema: str,
    table: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _submit(connection_id, "table", {"schema": schema, "table": table}, workspace, user, db)


@router.post("/{connection_id}/preview", status_code=202)
def preview(
    connection_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _submit(connection_id, "preview", body, workspace, user, db)


@router.post("/{connection_id}/import", status_code=202)
def import_data(
    connection_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _submit(connection_id, "import", body, workspace, user, db)


def _owned_run(db, workspace, user, connection_id, run_id):
    from app.services.compute_runs import get_run

    _access(db, workspace, user)
    row = get_run(db, workspace.id, run_id)
    if row.connection_id != connection_id:
        raise service.ConnectionError("CONNECTOR_RUN_NOT_FOUND", 404)
    if row.user_id != user.id and not is_workspace_admin(db, user, workspace):
        raise service.ConnectionError("CONNECTOR_RUN_NOT_FOUND", 404)
    return row


@router.get("/{connection_id}/runs/{run_id}")
def run_detail(
    connection_id: str,
    run_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.compute_runs import serialize_run

    return _call(db, lambda: serialize_run(_owned_run(db, workspace, user, connection_id, run_id)))


@router.post("/{connection_id}/runs/{run_id}/cancel")
def cancel_run(
    connection_id: str,
    run_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.compute_runs import request_cancel, serialize_run

    return _call(
        db,
        lambda: serialize_run(
            request_cancel(db, _owned_run(db, workspace, user, connection_id, run_id))
        ),
        mutate=True,
    )


def _grant(db, connection_id, grant_id, workspace, user):
    from app.models.connector_connection import ConnectorGrant

    _access(db, workspace, user)
    row = (
        db.query(ConnectorGrant)
        .filter_by(id=grant_id, connection_id=connection_id, workspace_id=workspace.id)
        .one_or_none()
    )
    if row is None or (
        row.owner_user_id != user.id and not is_workspace_admin(db, user, workspace)
    ):
        raise service.ConnectionError("CONNECTOR_GRANT_NOT_FOUND", 404)
    return row


def _grant_metadata(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "connection_id",
            "owner_user_id",
            "scopes",
            "granted_at",
            "expires_at",
            "revoked_at",
        )
    }


@router.get("/{connection_id}/grants")
def grants(
    connection_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.connector_connection import ConnectorGrant

    _access(db, workspace, user)

    def load():
        service.get_connection(db, workspace.id, connection_id)
        query = db.query(ConnectorGrant).filter_by(
            workspace_id=workspace.id, connection_id=connection_id
        )
        if not is_workspace_admin(db, user, workspace):
            query = query.filter_by(owner_user_id=user.id)
        return {"grants": [_grant_metadata(row) for row in query.all()]}

    return _call(db, load)


@router.delete("/{connection_id}/grants/{grant_id}")
def revoke_grant(
    connection_id: str,
    grant_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    def revoke():
        service.revoke_grant(
            db, _grant(db, connection_id, grant_id, workspace, user), actor=user.id
        )
        return {"status": "revoked"}

    return _call(db, revoke, mutate=True)


def _delegation_metadata(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "grant_id",
            "system_id",
            "system_version_id",
            "created_by",
            "approved_by",
            "approved_at",
            "expires_at",
            "revoked_at",
        )
    }


@router.post("/{connection_id}/grants/{grant_id}/delegations", status_code=201)
def delegate(
    connection_id: str,
    grant_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import UTC, datetime

    if (
        not isinstance(body, dict)
        or set(body) != {"system_version_id", "expires_at"}
        or not isinstance(body["system_version_id"], str)
    ):
        raise HTTPException(status_code=400, detail={"code": "CONNECTOR_DELEGATION_INVALID"})
    try:
        expiry = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError()
        expiry = expiry.astimezone(UTC).replace(tzinfo=None)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=400, detail={"code": "CONNECTOR_DELEGATION_INVALID"}
        ) from None
    return _call(
        db,
        lambda: _delegation_metadata(
            service.create_delegation(
                db,
                _grant(db, connection_id, grant_id, workspace, user),
                actor=user.id,
                system_version_id=body["system_version_id"],
                expires_at=expiry,
            )
        ),
        mutate=True,
    )


def _delegation(db, connection_id, delegation_id, workspace, user):
    from app.models.connector_connection import ConnectorDelegation

    row = (
        db.query(ConnectorDelegation)
        .filter_by(id=delegation_id, workspace_id=workspace.id)
        .one_or_none()
    )
    if row is None:
        raise service.ConnectionError("CONNECTOR_DELEGATION_NOT_FOUND", 404)
    _grant(db, connection_id, row.grant_id, workspace, user)
    return row


@router.get("/{connection_id}/grants/{grant_id}/delegations")
def delegations(
    connection_id: str,
    grant_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.connector_connection import ConnectorDelegation

    def load():
        grant = _grant(db, connection_id, grant_id, workspace, user)
        return {
            "delegations": [
                _delegation_metadata(row)
                for row in db.query(ConnectorDelegation)
                .filter_by(workspace_id=workspace.id, grant_id=grant.id)
                .all()
            ]
        }

    return _call(db, load)


@router.post("/{connection_id}/delegations/{delegation_id}/approve")
def approve(
    connection_id: str,
    delegation_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)

    def allow():
        row = _delegation(db, connection_id, delegation_id, workspace, user)
        service.approve_delegation(db, row, actor=user)
        return _delegation_metadata(row)

    return _call(db, allow, mutate=True)


@router.delete("/{connection_id}/delegations/{delegation_id}")
def revoke_delegation(
    connection_id: str,
    delegation_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime

    def revoke():
        row = _delegation(db, connection_id, delegation_id, workspace, user)
        row.revoked_at, row.revoked_by = datetime.utcnow(), user.id
        service.audit(
            db,
            service.get_connection(db, workspace.id, connection_id),
            "connection.delegation.revoked",
            user.id,
            delegation_id=row.id,
        )
        return _delegation_metadata(row)

    return _call(db, revoke, mutate=True)


@router.post("/{connection_id}/oauth/start")
def oauth_start(
    connection_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.connectors import oauth

    _access(db, workspace, user)
    return _call(
        db,
        lambda: oauth.start(
            db, service.get_connection(db, workspace.id, connection_id), user_id=user.id
        ),
        mutate=True,
    )


@router.post("/{connection_id}/oauth/callback")
def oauth_callback(
    connection_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.connectors import oauth

    _access(db, workspace, user)
    if not isinstance(body, dict) or set(body) != {"state", "code"}:
        raise HTTPException(status_code=400, detail={"code": "CONNECTOR_OAUTH_CALLBACK_INVALID"})
    return _call(
        db,
        lambda: oauth.callback(
            db,
            service.get_connection(db, workspace.id, connection_id),
            user_id=user.id,
            state=body["state"],
            code=body["code"],
        ),
        mutate=True,
    )


@router.post("/{connection_id}/oauth/register-client")
def oauth_register_client(
    connection_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.connectors import oauth

    _access(db, workspace, user, admin=True)
    return _call(
        db,
        lambda: oauth.register_client(
            db, service.get_connection(db, workspace.id, connection_id), actor=user.id
        ),
        mutate=True,
    )


@router.post("/{connection_id}/oauth/refresh")
def oauth_refresh(
    connection_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.connectors import oauth

    _access(db, workspace, user)
    return _call(
        db,
        lambda: oauth.refresh(
            db, service.get_connection(db, workspace.id, connection_id), user_id=user.id
        ),
        mutate=True,
    )


@router.post("/{connection_id}/openapi/import")
def openapi_import(
    connection_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import UTC, datetime, timedelta

    from app.services.connectors.adapters.http import json_request
    from app.services.connectors.adapters.sql import AdapterError
    from app.services.connectors.network_policy import ConnectorNetworkError
    from app.services.connectors.tool_contracts import MAX_SPEC_BYTES, allowed_url, compile_openapi

    _access(db, workspace, user, admin=True)
    if not isinstance(body, dict) or set(body) not in ({"spec"}, {"url"}):
        raise HTTPException(status_code=400, detail={"code": "CONNECTOR_OPENAPI_INVALID"})

    def install():
        row = service.get_connection(db, workspace.id, connection_id)
        if row.profile_key != "openapi":
            raise service.ConnectionError("CONNECTOR_OPERATION_UNSUPPORTED", 409)
        spec = body.get("spec")
        if "url" in body:
            try:
                url = allowed_url(row.values, body["url"])
                _, spec = json_request(
                    "GET",
                    url,
                    deadline_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                    max_bytes=MAX_SPEC_BYTES,
                )
            except (AdapterError, ConnectorNetworkError) as exc:
                raise service.ConnectionError(exc.code, 502) from None
        contract = compile_openapi(spec, row.values)
        service.update_connection(
            db,
            row,
            actor=user.id,
            data=ConnectionUpdate(
                revision=row.revision, values={**row.values, "openapi_spec": spec}
            ),
        )
        service.audit(
            db,
            row,
            "connection.openapi.imported",
            user.id,
            digest=contract["digest"],
            operations=len(contract["operations"]),
        )
        return contract

    return _call(db, install, mutate=True)


@router.post("/{connection_id}/tools/import")
def import_tool_catalog(
    connection_id: str,
    body: Any = Body(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Freeze an actual successful MCP catalogue before a separate write approval."""
    _access(db, workspace, user, admin=True)

    def apply():
        from app.services import compute_runs
        from app.services.connectors.tool_contracts import tool_digest

        if (
            not isinstance(body, dict)
            or set(body) != {"run_id"}
            or not isinstance(body["run_id"], str)
        ):
            raise service.ConnectionError("CONNECTOR_PARAMETERS_INVALID")
        connection = service.get_connection(db, workspace.id, connection_id)
        row = compute_runs.get_run(db, workspace.id, body["run_id"])
        if (
            connection.profile_key != "mcp"
            or row.connection_id != connection.id
            or row.operation != "catalog"
            or row.status != "succeeded"
            or row.connection_revision != connection.revision
        ):
            raise service.ConnectionError("CONNECTOR_TOOL_CATALOG_REQUIRED", 409)
        listing = (row.output_json or {}).get("tools")
        if not isinstance(listing, list) or len(listing) > 1000:
            raise service.ConnectionError("CONNECTOR_TOOL_CATALOG_REQUIRED", 409)
        contracts = {
            item["id"]: item
            for item in listing
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"] in connection.values.get("tool_allowlist", [])
        }
        if len(contracts) != len(listing):
            raise service.ConnectionError("CONNECTOR_TOOL_CATALOG_REQUIRED", 409)
        tool_digest(contracts)
        updated = service.update_connection(
            db,
            connection,
            actor=user.id,
            data=ConnectionUpdate(
                revision=connection.revision,
                values={**connection.values, "tool_contracts": contracts},
            ),
            trusted_tool_catalog=True,
        )
        return service.serialize_connection(updated)

    return _call(db, apply, mutate=True)
