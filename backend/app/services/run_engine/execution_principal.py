"""Explicit, revocable self-delegation for webhook and cron executions.

The automation is the initiator. A delegated user supplies only the current
authorization context, never ownership or a fabricated human Run initiation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException

from app.models.capability import Capability
from app.models.run_schedule import RunSchedule
from app.models.system import System
from app.models.user import User
from app.models.webhook_hook import WebhookHook
from app.models.workspace import Workspace, WorkspaceMember


class ExecutionPrincipalError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _authorized_user(db, *, user_id, workspace_id, system_id):
    from app.core.iam.dependencies import evaluate_permission
    from app.services.chat_execution_policy import migration_059_system_id
    from app.services.iam.decision_plane import enforce_action
    from app.services.run_access import has_private_chat_admin_access

    user = db.get(User, user_id, populate_existing=True) if user_id else None
    workspace = db.get(Workspace, workspace_id, populate_existing=True)
    system = db.get(System, system_id, populate_existing=True)
    member = (
        db.query(WorkspaceMember)
        .populate_existing()
        .filter_by(workspace_id=workspace_id, user_id=user_id)
        .first()
    )
    if (
        user is None
        or not user.is_active
        or member is None
        or workspace is None
        or not workspace.is_active
        or workspace.deleted_at
        or system is None
        or system.workspace_id != workspace_id
    ):
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_REVOKED")
    if migration_059_system_id(workspace) == system.id and not has_private_chat_admin_access(
        db, user=user, workspace=workspace, membership=member
    ):
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_FORBIDDEN")
    capability = db.get(Capability, system.capability_id) if system.capability_id else None
    attrs = {
        "iam_manifest": "system_engine",
        "system_id": system.id,
        "capability_id": system.capability_id,
        "capability": capability.slug if capability else None,
        "execution_source": "delegated_trigger",
    }
    legacy = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="engine.run",
        resource_attrs=attrs,
        audit_prefix="system",
        audit_denials=False,
    )
    try:
        # Delegating authority is a new opt-in: report-only legacy IAM does not
        # grant an identity that its current policy explicitly denies.
        enforce_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="engine.run",
            legacy_allowed=legacy.allowed,
            resource_attrs=attrs,
        )
    except HTTPException:
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_FORBIDDEN") from None
    return user


def configure_identity(db, *, source, command, user, workspace, system):
    """The authenticated caller can delegate only their own current rights."""
    if command is None:
        return
    before = getattr(source, "execution_identity", None)
    if command == "none":
        source.execution_identity = None
        if before is not None:
            _audit_identity(db, source=source, actor=user, command=command, before=before)
        return
    if command != "current_user":
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_INVALID")
    actor = _authorized_user(
        db,
        user_id=user.id,
        workspace_id=workspace.id,
        system_id=system.id,
    )
    authority = _published_authority(db, workspace=workspace, system_id=system.id)
    current = source.execution_identity
    if (
        isinstance(current, dict)
        and current.get("user_id") == actor.id
        and current.get("grant_id")
        and current.get("authority") == authority
    ):
        return
    source.execution_identity = {
        "schema_version": 1,
        "kind": "delegated_user",
        "user_id": actor.id,
        "display_name": actor.username or actor.email or actor.id,
        "grant_id": str(uuid4()),
        "granted_at": datetime.now(UTC).isoformat(),
        "authority": authority,
    }
    _audit_identity(db, source=source, actor=user, command=command, before=before)


def _audit_identity(db, *, source, actor, command, before):
    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        db=db,
        workspace_id=source.workspace_id,
        actor=actor.id,
        event_type="system.trigger.execution_identity",
        details={
            "system_id": source.system_id,
            "source_id": source.id,
            "source_type": "webhook" if isinstance(source, WebhookHook) else "schedule",
            "command": command,
            "previous_user_id": (before or {}).get("user_id"),
            "user_id": (source.execution_identity or {}).get("user_id"),
        },
    )


def public_identity(source):
    value = getattr(source, "execution_identity", None)
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in ("kind", "user_id", "display_name", "granted_at")}


def public_run_principal(run):
    value = getattr(run, "execution_principal", None)
    if not isinstance(value, dict):
        return None
    return {
        key: value.get(key) for key in ("kind", "user_id", "source_type", "source_id", "authority")
    }


def authorize_source_mutation(db, *, source, user, workspace):
    """Legacy source editing cannot borrow another person's delegated rights."""
    from app.core.iam.roles import is_admin_template

    value = getattr(source, "execution_identity", None)
    if value is None:
        return
    member = (
        db.query(WorkspaceMember)
        .populate_existing()
        .filter_by(workspace_id=workspace.id, user_id=user.id)
        .first()
    )
    actor = db.get(User, user.id, populate_existing=True)
    if (
        actor is None
        or not actor.is_active
        or member is None
        or source.workspace_id != workspace.id
        or not (
            (isinstance(value, dict) and value.get("user_id") == actor.id)
            or actor.role == "admin"
            or is_admin_template(member.role_template, member.role)
        )
    ):
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_SOURCE_FORBIDDEN")


def _published_authority(db, *, workspace, system_id):
    from app.services.flow_contracts import canonical_sha256
    from app.services.systems import flow_publication

    if not flow_publication.flow_publication_enabled(workspace):
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_PUBLICATION_REQUIRED")
    system = (
        db.query(System)
        .filter_by(id=system_id, workspace_id=workspace.id)
        .populate_existing()
        # System eagerly joins its optional Capability. PostgreSQL cannot lock
        # the nullable side of that join; only the publication owner needs
        # locking while consent is bound to its immutable version.
        .with_for_update(of=System)
        .first()
    )
    if system is None:
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_REVOKED")
    try:
        version, _flow, flow_hash, contract = flow_publication.published_run_evidence(
            db,
            system=system,
            workspace=workspace,
        )
    except flow_publication.FlowPublicationError:
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_PUBLICATION_REQUIRED") from None
    return {
        "published_flow_version_id": version.id,
        "flow_sha256": flow_hash,
        "execution_contract_sha256": canonical_sha256(contract),
    }


def _grant(source):
    value = getattr(source, "execution_identity", None)
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("kind") != "delegated_user"
        or not value.get("grant_id")
        or not isinstance(value.get("authority"), dict)
    ):
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_INVALID")
    return value


def _principal(source, source_type, value):
    return {
        "schema_version": 1,
        "kind": "delegated_user",
        "user_id": value["user_id"],
        "grant_id": value["grant_id"],
        "source_type": source_type,
        "source_id": source.id,
        "authority": dict(value["authority"]),
    }


def principal_for_source(db, *, source, source_type):
    value = getattr(source, "execution_identity", None)
    if value is None:
        return None
    value = _grant(source)
    if source_type not in {"webhook", "schedule"}:
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_INVALID")
    _authorized_user(
        db,
        user_id=value.get("user_id"),
        workspace_id=source.workspace_id,
        system_id=source.system_id,
    )
    workspace = db.get(Workspace, source.workspace_id, populate_existing=True)
    if value["authority"] != _published_authority(
        db, workspace=workspace, system_id=source.system_id
    ):
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_PUBLICATION_CHANGED")
    return _principal(source, source_type, value)


def validate_run_authority(principal, *, version_id, flow_sha256, execution_contract):
    from app.services.flow_contracts import canonical_sha256

    if principal is None:
        return
    expected = {
        "published_flow_version_id": version_id,
        "flow_sha256": flow_sha256,
        "execution_contract_sha256": canonical_sha256(execution_contract),
    }
    if not isinstance(principal, dict) or principal.get("authority") != expected:
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_PUBLICATION_CHANGED")


def execution_user_id(db, run):
    principal = getattr(run, "execution_principal", None)
    if principal is None:
        return run.initiated_by_user_id
    if not isinstance(principal, dict) or set(principal) != {
        "schema_version",
        "kind",
        "user_id",
        "grant_id",
        "source_type",
        "source_id",
        "authority",
    }:
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_INVALID")
    source_class = {"webhook": WebhookHook, "schedule": RunSchedule}.get(
        principal.get("source_type")
    )
    source = (
        db.get(source_class, principal["source_id"], populate_existing=True)
        if source_class
        else None
    )
    if (
        source is None
        or source.workspace_id != run.workspace_id
        or source.system_id != run.system_id
    ):
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_REVOKED")
    if source.execution_identity is None:
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_REVOKED")
    current = _principal(source, principal["source_type"], _grant(source))
    if current != principal:
        raise ExecutionPrincipalError("EXECUTION_PRINCIPAL_REVOKED")
    validate_run_authority(
        principal,
        version_id=run.published_flow_version_id,
        flow_sha256=run.flow_sha256,
        execution_contract=run.execution_contract,
    )
    _authorized_user(
        db, user_id=principal["user_id"], workspace_id=run.workspace_id, system_id=run.system_id
    )
    return principal["user_id"]
