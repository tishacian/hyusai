"""Administrative Workspace App lifecycle governance API.

This router is intentionally separate from the legacy workspace ``apps``
settings endpoint. Every mutation selects a precompiled manifest by exact
version and digest, applies a previously returned plan, and records the
authenticated server-side actor.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_app import (
    WorkspaceAppInstallation,
    WorkspaceAppLifecycleStepReceipt,
)
from app.services.workspace_app_lifecycle import (
    WorkspaceAppLifecycleConflict,
    WorkspaceAppLifecycleError,
    WorkspaceAppLifecycleNotFound,
    WorkspaceAppLifecycleValidationError,
    apply_workspace_app_lifecycle,
    plan_workspace_app_lifecycle,
    workspace_app_is_compatible,
)
from app.services.workspace_app_manifests import (
    WorkspaceAppManifestError,
    get_builtin_workspace_app_manifest,
    list_builtin_workspace_app_manifests,
    validate_manifest_configuration,
)

router = APIRouter()


class WorkspaceAppLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["install", "upgrade", "rollback", "uninstall"]
    app_id: str = Field(min_length=3, max_length=120)
    target_version: str | None = Field(default=None, min_length=5, max_length=40)
    expected_manifest_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    configuration: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("config", "configuration"),
        serialization_alias="config",
    )


class WorkspaceAppLifecycleApplyRequest(WorkspaceAppLifecycleRequest):
    expected_plan_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


def _require_workspace_admin(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    refresh: bool = False,
) -> WorkspaceMember:
    query = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
    )
    if refresh:
        query = query.populate_existing()
    membership = query.one_or_none()
    if membership is None or not is_admin_template(
        getattr(membership, "role_template", None),
        membership.role,
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "WORKSPACE_APP_ADMIN_REQUIRED"},
        )
    return membership


def _raise_lifecycle_http(exc: WorkspaceAppLifecycleError) -> None:
    if isinstance(exc, WorkspaceAppLifecycleNotFound):
        status_code = 404
    elif isinstance(exc, WorkspaceAppLifecycleConflict):
        status_code = 409
    elif isinstance(exc, WorkspaceAppLifecycleValidationError):
        status_code = 422
    else:
        status_code = 400
    raise HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _installation_payload(installation: WorkspaceAppInstallation) -> dict[str, Any]:
    configuration = deepcopy(installation.configuration or {})
    if installation.state == "installed":
        try:
            manifest = get_builtin_workspace_app_manifest(
                installation.app_id,
                str(installation.version or ""),
                expected_digest=str(installation.manifest_digest or ""),
            )
            canonical = validate_manifest_configuration(manifest, configuration)
        except WorkspaceAppManifestError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "WORKSPACE_APP_STATE_INVALID",
                    "message": str(exc),
                    "app_id": installation.app_id,
                },
            ) from exc
        if canonical != configuration:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "WORKSPACE_APP_STATE_INVALID",
                    "message": "installation configuration is not canonical",
                    "app_id": installation.app_id,
                },
            )
    elif configuration:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKSPACE_APP_STATE_INVALID",
                "message": "uninstalled application retains opaque configuration",
                "app_id": installation.app_id,
            },
        )
    return {
        "app_id": installation.app_id,
        "state": installation.state,
        "version": installation.version,
        "manifest_digest": installation.manifest_digest,
        "configuration": configuration,
        "revision": int(installation.revision or 0),
        "installed_at": (
            installation.installed_at.isoformat() + "Z"
            if installation.installed_at is not None
            else None
        ),
        "updated_at": (
            installation.updated_at.isoformat() + "Z"
            if installation.updated_at is not None
            else None
        ),
        "updated_by": installation.updated_by,
    }


def _step_receipt_payload(
    receipt: WorkspaceAppLifecycleStepReceipt,
) -> dict[str, Any]:
    """Expose lifecycle proof without internal row or installation identifiers."""

    return {
        "position": int(receipt.position),
        "manifest_role": receipt.manifest_role,
        "manifest_digest": receipt.manifest_digest,
        "step_id": receipt.step_id,
        "step_sha256": receipt.step_sha256,
        "phase": receipt.phase,
        "executor": receipt.executor,
        "outcome": receipt.outcome,
        "reversibility": receipt.reversibility,
        "evidence_sha256": receipt.evidence_sha256,
    }


@router.get("/manifests")
async def list_workspace_app_manifests(
    app_id: str | None = Query(default=None, min_length=3, max_length=120),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    _require_workspace_admin(db, user=user, workspace=workspace)
    manifests = tuple(
        manifest
        for manifest in list_builtin_workspace_app_manifests(app_id)
        if workspace_app_is_compatible(workspace, manifest)
    )
    return {
        "workspace_id": workspace.id,
        "manifests": [
            {
                "app_id": manifest.app_id,
                "version": manifest.version,
                "manifest_digest": manifest.digest,
                "manifest": manifest.as_dict(),
            }
            for manifest in manifests
        ],
    }


@router.get("/installations")
async def list_workspace_app_installations(
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    _require_workspace_admin(db, user=user, workspace=workspace)
    rows = (
        db.query(WorkspaceAppInstallation)
        .filter(WorkspaceAppInstallation.workspace_id == workspace.id)
        .order_by(WorkspaceAppInstallation.app_id.asc())
        .all()
    )
    return {
        "workspace_id": workspace.id,
        "installations": [_installation_payload(row) for row in rows],
    }


@router.post("/plan")
async def plan_workspace_app_operation(
    body: WorkspaceAppLifecycleRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    _require_workspace_admin(db, user=user, workspace=workspace)
    try:
        plan = plan_workspace_app_lifecycle(
            db,
            workspace_id=workspace.id,
            operation=body.operation,
            app_id=body.app_id,
            target_version=body.target_version,
            expected_manifest_digest=body.expected_manifest_digest,
            configuration=body.configuration,
        )
        return plan.as_dict()
    except WorkspaceAppLifecycleError as exc:
        db.rollback()
        _raise_lifecycle_http(exc)


@router.post("/apply")
async def apply_workspace_app_operation(
    body: WorkspaceAppLifecycleApplyRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=160,
    ),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        # Re-check membership only after taking the tenant mutation lock. A
        # role revoked between plan and apply therefore cannot race the write.
        locked_workspace = (
            db.query(Workspace)
            .filter(Workspace.id == workspace.id)
            .with_for_update(of=Workspace)
            .populate_existing()
            .one_or_none()
        )
        if locked_workspace is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "WORKSPACE_NOT_FOUND"},
            )
        _require_workspace_admin(
            db,
            user=user,
            workspace=locked_workspace,
            refresh=True,
        )
        result = apply_workspace_app_lifecycle(
            db,
            workspace_id=locked_workspace.id,
            operation=body.operation,
            app_id=body.app_id,
            target_version=body.target_version,
            expected_manifest_digest=body.expected_manifest_digest,
            expected_plan_sha256=body.expected_plan_sha256,
            configuration=body.configuration,
            actor=user.id,
            idempotency_key=idempotency_key,
        )
        return {
            "workspace_id": locked_workspace.id,
            "operation_id": result.operation.id,
            "operation": result.operation.operation,
            "app_id": result.operation.app_id,
            "plan_sha256": result.operation.plan_sha256,
            "manifest_digest": result.operation.manifest_digest,
            "lifecycle_phase": result.operation.lifecycle_phase,
            "steps_sha256": result.operation.steps_sha256,
            "step_receipts": [
                _step_receipt_payload(receipt)
                for receipt in result.step_receipts
            ],
            "idempotent_replay": result.idempotent_replay,
            "installation": deepcopy(result.result_snapshot),
        }
    except WorkspaceAppLifecycleError as exc:
        db.rollback()
        _raise_lifecycle_http(exc)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
