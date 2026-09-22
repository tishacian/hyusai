"""Canonical /systems endpoints — supersede /agents.

A System is the deployable composition (Objective + Capability + Context +
Skills + Policies). `POST /systems/{id}/runs` enqueues a Run; the actual
execution loop lives in `app.services.run_engine`.

Vague E / E3.1 — versioning + DAG validation:

- ``PATCH /systems/{id}`` is now validated before it touches the DB.
  Structural errors (cycle, orphan, unreachable node, decision without
  branches, …) are returned as HTTP 400 with the same shape the editor
  displays (``FlowValidationIssue``). Warnings (task without skill,
  fork/join imbalance, …) pass through but are echoed in the response.
- Every change to ``flow_definition`` spawns a new ``SystemVersion``
  row. Rolling window of 500 per system (see
  ``services.chains.version_service``).
- New routes ``/systems/{id}/versions`` + ``/rollback`` expose the
  history and restore flow.
"""

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.iam.dependencies import evaluate_permission
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.capability import Capability
from app.models.context import Context
from app.models.policy import ControlPolicy
from app.models.run import Run
from app.models.run_schedule import RunSchedule
from app.models.system import System
from app.models.user import User
from app.models.webhook_hook import WebhookHook
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.canonical import ExecutionMode, SystemStatus
from app.services.actions.contracts import normalize_system_action_pack_settings
from app.services.audit_logger import emit_audit_event
from app.services.chains import dag_validator, export_service, version_service
from app.services.chat_execution_policy import (
    migration_059_system_id,
)
from app.services.context_bindings import ContextBindingError, validate_context_id
from app.services.iam.config_service import is_iam_enforced_for_workspace
from app.services.iam.decision_plane import enforce_action
from app.services.iam.legacy_authority import legacy_object_action_allowed
from app.services.membrane.enforcement import evaluate_capability
from app.services.membrane.spec import resolve_membrane_spec
from app.services.run_access import readable_run_page
from app.services.run_engine import schedule_run, triggers
from app.services.run_engine import scheduler as run_scheduler
from app.services.run_engine.debug_contract import (
    DebugContractError,
    normalize_input_debug,
)
from app.services.run_engine.execution_contract import (
    canonical_flow,
    canonical_flow_sha256,
    resolve_flow_execution,
)
from app.services.run_engine.webhooks import generate_hook_secret, serialize_hook
from app.services.system_catalog_bindings import (
    ResolvedSystemCatalogBindings,
    SystemCatalogBindingError,
    resolve_persisted_system_catalog_bindings,
    resolve_system_catalog_bindings,
)
from app.services.system_perspective import PublishedMandateUnavailable, build_system_perspective
from app.services.systems import dispatch_readiness, flow_ingress, flow_publication
from app.services.systems.flow_manifest import serialize_flow_manifest

router = APIRouter()

_MANAGED_SYSTEM_SETTING_FIELDS = {
    "_lot6_system360_rollout_v1": "LOT6_SYSTEM360_ROLLOUT_STATE_MANAGED",
    "_lot7_projection_rollout_v1": "LOT7_PROJECTION_ROLLOUT_STATE_MANAGED",
    "_lot8_value_loop_rollout_v1": "LOT8_VALUE_LOOP_ROLLOUT_STATE_MANAGED",
}
_MANAGED_SYSTEM_EXPERIENCE_FIELDS = {
    "system_360_canary": "LOT6_SYSTEM360_ROLLOUT_STATE_MANAGED",
    "value_loop_canary": "LOT8_VALUE_LOOP_ROLLOUT_STATE_MANAGED",
}


def _managed_system_settings_error(*, code: str, path: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": code,
            "message": f"{path} is managed internally",
        },
    )


def _settings_with_managed_system_fields_preserved(
    current: object,
    requested: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep rollout markers and evidence outside generic System writes.

    ``System.settings`` remains a replacement payload for ordinary product
    configuration. Rollout state and canary selection are different: only the
    seed/rollout services may create, change, or remove them. Omitting one from
    a generic replacement therefore preserves the current server-owned value.
    """

    current_settings = (
        copy.deepcopy(dict(current)) if isinstance(current, Mapping) else {}
    )
    next_settings = copy.deepcopy(dict(requested))

    for field, code in _MANAGED_SYSTEM_SETTING_FIELDS.items():
        current_has_field = field in current_settings
        requested_has_field = field in next_settings
        if requested_has_field and (
            not current_has_field
            or next_settings[field] != current_settings[field]
        ):
            raise _managed_system_settings_error(
                code=code,
                path=f"system.settings.{field}",
            )
        if current_has_field:
            next_settings[field] = copy.deepcopy(current_settings[field])

    current_experience_raw = current_settings.get("experience")
    current_experience = (
        dict(current_experience_raw)
        if isinstance(current_experience_raw, Mapping)
        else {}
    )
    requested_has_experience = "experience" in next_settings
    requested_experience_raw = next_settings.get("experience")
    requested_experience = (
        copy.deepcopy(dict(requested_experience_raw))
        if isinstance(requested_experience_raw, Mapping)
        else {}
    )
    current_has_managed_experience = any(
        field in current_experience for field in _MANAGED_SYSTEM_EXPERIENCE_FIELDS
    )
    if (
        requested_has_experience
        and not isinstance(requested_experience_raw, Mapping)
        and current_has_managed_experience
    ):
        raise _managed_system_settings_error(
            code="SYSTEM_EXPERIENCE_ROLLOUT_STATE_MANAGED",
            path="system.settings.experience",
        )
    for field, code in _MANAGED_SYSTEM_EXPERIENCE_FIELDS.items():
        current_has_field = field in current_experience
        requested_has_field = field in requested_experience
        if requested_has_field and (
            not current_has_field
            or requested_experience[field] != current_experience[field]
        ):
            raise _managed_system_settings_error(
                code=code,
                path=f"system.settings.experience.{field}",
            )
        if current_has_field:
            requested_experience[field] = copy.deepcopy(current_experience[field])

    if requested_has_experience or current_has_managed_experience:
        next_settings["experience"] = requested_experience
    return next_settings


def _is_migration_managed_agentic_system(
    workspace: Workspace,
    system: System,
) -> bool:
    return migration_059_system_id(workspace) == system.id


def _require_managed_system_admin(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    system: System,
) -> None:
    if not _is_migration_managed_agentic_system(workspace, system):
        return
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
        membership.role_template,
        membership.role,
    ):
        raise HTTPException(
            status_code=403,
            detail="Admin/owner access required for the production Agentic System",
        )


def _enforce_system_read(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    system: System,
) -> None:
    """Apply the additive v2 read decision after tenant-scoped lookup."""

    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="read",
        legacy_allowed=True,
        resource_attrs={
            "system_id": system.id,
            "capability_id": system.capability_id,
        },
    )


def _enforce_system_collection_read(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> None:
    """Resolve the role-scoped collection boundary before returning counts."""

    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="read",
        legacy_allowed=True,
        resource_attrs={"scope": "collection"},
    )


def _enforce_system_admin(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    system: System,
    **resource_attrs: Any,
) -> None:
    """Preserve the managed-System guard, then resolve granular admin.

    Ordinary Systems historically allowed the mutation once workspace access
    had succeeded. That remains the legacy decision in compat/shadow. The
    candidate admin policy becomes authoritative only for an explicit v2
    enforce rollout.
    """

    _require_managed_system_admin(
        db,
        user=user,
        workspace=workspace,
        system=system,
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="admin",
        legacy_allowed=legacy_object_action_allowed(
            db,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="admin",
        ),
        resource_attrs={
            "system_id": system.id,
            "capability_id": system.capability_id,
            **resource_attrs,
        },
    )


def _require_reserved_agentic_identity_admin(
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
        membership.role_template,
        membership.role,
    ):
        raise HTTPException(
            status_code=403,
            detail="Admin/owner access required for the reserved Agentic identity",
        )


def _is_reserved_agentic_identity(settings_blob: Any, flow: Any) -> bool:
    settings_payload = settings_blob if isinstance(settings_blob, dict) else {}
    flow_payload = flow if isinstance(flow, dict) else {}
    return bool(
        settings_payload.get("system_type") == "chat_agentic"
        and flow_payload.get("variant") == "chat_agentic_thinking_v1"
    )


def _validate_control_policy_tenant(
    db: DBSession,
    *,
    workspace_id: str,
    policy_id: Optional[str],
) -> None:
    if not policy_id:
        return
    exists_in_workspace = (
        db.query(ControlPolicy.id)
        .filter(
            ControlPolicy.id == policy_id,
            ControlPolicy.workspace_id == workspace_id,
        )
        .first()
    )
    if exists_in_workspace is None:
        raise HTTPException(400, "ControlPolicy must belong to the current workspace")


def _validate_context_tenant(
    db: DBSession,
    *,
    workspace_id: str,
    context_id: Optional[str],
) -> Optional[Context]:
    try:
        return validate_context_id(
            db,
            workspace_id=workspace_id,
            context_id=context_id,
        )
    except ContextBindingError as exc:
        raise HTTPException(400, str(exc)) from exc


def _resolve_catalog_bindings_http(
    db: DBSession,
    *,
    workspace: Workspace,
    system_id: Optional[str],
    capability_id: Optional[str],
    skill_ids: list[str] | None,
    adaptive_policy_id: Optional[str],
) -> ResolvedSystemCatalogBindings:
    """Translate the shared tenant/catalog contract into a safe API error."""

    try:
        return resolve_system_catalog_bindings(
            db,
            workspace=workspace,
            system_id=system_id,
            capability_id=capability_id,
            skill_ids=skill_ids,
            adaptive_policy_id=adaptive_policy_id,
        )
    except SystemCatalogBindingError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_system_catalog_binding",
                "code": exc.code,
                "field": exc.field,
                "message": str(exc),
            },
        ) from exc


def _resolve_persisted_catalog_bindings_http(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
) -> ResolvedSystemCatalogBindings:
    """Translate the persisted runtime contract into a safe API error."""

    try:
        return resolve_persisted_system_catalog_bindings(
            db,
            workspace=workspace,
            system=system,
        )
    except SystemCatalogBindingError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_system_catalog_binding",
                "code": exc.code,
                "field": exc.field,
                "message": str(exc),
            },
        ) from exc


def _enforce_system_run_authority(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    system: System,
    execution_source: str,
    execution_contract: dict[str, Any] | None = None,
) -> None:
    """Apply the complete operator Run boundary shared by every HTTP surface."""

    _require_managed_system_admin(
        db,
        user=user,
        workspace=workspace,
        system=system,
    )
    catalog_bindings = _resolve_persisted_catalog_bindings_http(
        db,
        workspace=workspace,
        system=system,
    )
    capability = catalog_bindings.capability
    legacy_decision = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="engine.run",
        resource_attrs={
            "iam_manifest": "system_engine",
            "system_id": system.id,
            "capability_id": system.capability_id,
            "capability": capability.slug if capability else None,
            "execution_source": execution_source,
        },
        audit_prefix="system",
        audit_denials=False,
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="engine.run",
        legacy_allowed=(
            legacy_decision.allowed
            if is_iam_enforced_for_workspace(workspace)
            else True
        ),
        resource_attrs={
            "system_id": system.id,
            "capability_id": system.capability_id,
            "capability": capability.slug if capability else None,
            "execution_source": execution_source,
        },
    )

    # New Runs use the published policy; replay/debug use the exact stored
    # contract passed by their server handler. An explicit {} denotes a legacy
    # Run, whose live policy checks must remain intact.
    if execution_contract is None and flow_publication.flow_publication_enabled(workspace):
        locked = (
            db.query(System)
            .filter(System.id == system.id, System.workspace_id == workspace.id)
            .populate_existing()
            .with_for_update(of=System)
            .first()
        )
        if locked is None:
            raise HTTPException(404, "System not found")
        system = locked
        try:
            _, _, _, execution_contract = flow_publication.published_run_evidence(
                db, system=system, workspace=workspace,
            )
        except flow_publication.FlowPublicationError as exc:
            raise HTTPException(exc.status_code, detail=exc.payload()) from exc

    if isinstance(execution_contract, dict) and "control_policy_snapshot" in execution_contract:
        from app.services.control_policy_snapshot import thaw_control_policy
        from app.services.flow_contracts import FlowContractError, validate_execution_contract

        try:
            validate_execution_contract(execution_contract)
            control = thaw_control_policy(
                execution_contract["control_policy_snapshot"],
                workspace_id=workspace.id, system_id=system.id,
            )
        except (ValueError, FlowContractError) as exc:
            raise HTTPException(409, detail={
                "code": "CONTROL_POLICY_SNAPSHOT_INVALID",
                "message": "The frozen execution policy is invalid; execution was not started.",
            }) from exc
    else:
        control = None
        if system.control_policy_id:
            control = (
                db.query(ControlPolicy)
                .filter(
                    ControlPolicy.id == system.control_policy_id,
                    ControlPolicy.workspace_id == workspace.id,
                    ControlPolicy.scope == "system",
                    ControlPolicy.target_id == system.id,
                )
                .first()
            )
        if control is None:
            control = (
                db.query(ControlPolicy)
                .filter(
                    ControlPolicy.workspace_id == workspace.id,
                    ControlPolicy.scope == "system",
                    ControlPolicy.target_id == system.id,
                )
                .order_by(ControlPolicy.updated_at.desc())
                .first()
            )
    spec = resolve_membrane_spec(control=control)
    membrane_decision = evaluate_capability(
        spec,
        model=system.default_model,
        action="system.engine.run",
    )
    if not membrane_decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "MEMBRANE_CAPABILITY_DENIED",
                "message": "System execution denied by its enforced membrane",
                "system_id": system.id,
                "capability_id": system.capability_id,
                "violations": list(membrane_decision.violations),
            },
        )


# ---------------- Pydantic ----------------
from app.schemas.operational_objective import OperationalObjective, validate_objective_settings


class SystemCreate(BaseModel):
    name: str
    objective: str = ""
    capability_id: Optional[str] = None
    skill_ids: list[str] = []
    flow_definition: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = {}
    execution_mode: ExecutionMode = ExecutionMode.real_time_decision
    execution_profile: Optional[dict[str, Any]] = None
    coordination_pattern: str = "single_agent"
    control_policy_id: Optional[str] = None
    adaptive_policy_id: Optional[str] = None
    context_id: Optional[str] = None
    status: SystemStatus = SystemStatus.draft
    default_prompt_type: Optional[str] = None
    default_model: Optional[str] = None
    retrieval_mode_default: Optional[str] = None

    @field_validator("settings")
    @classmethod
    def _validate_settings_action_packs(cls, value: dict[str, Any]) -> dict[str, Any]:
        normalized, _ = normalize_system_action_pack_settings(
            settings=value,
            execution_profile=None,
        )
        return validate_objective_settings(normalized) or {}

    @field_validator("execution_profile")
    @classmethod
    def _validate_profile_action_packs(
        cls,
        value: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        _, normalized = normalize_system_action_pack_settings(
            settings=None,
            execution_profile=value,
        )
        return normalized


class SystemUpdate(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    capability_id: Optional[str] = None
    skill_ids: Optional[list[str]] = None
    # Non-nullable in OpenAPI and at runtime. ``exclude_unset=True`` below
    # still distinguishes an omitted PATCH field from an explicit object.
    flow_definition: dict[str, Any] = Field(default_factory=dict)
    settings: Optional[dict[str, Any]] = None
    execution_mode: Optional[ExecutionMode] = None
    execution_profile: Optional[dict[str, Any]] = None
    coordination_pattern: Optional[str] = None
    control_policy_id: Optional[str] = None
    adaptive_policy_id: Optional[str] = None
    context_id: Optional[str] = None
    status: Optional[SystemStatus] = None
    default_prompt_type: Optional[str] = None
    default_model: Optional[str] = None
    retrieval_mode_default: Optional[str] = None

    @field_validator("settings")
    @classmethod
    def _validate_settings_action_packs(
        cls,
        value: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        normalized, _ = normalize_system_action_pack_settings(
            settings=value,
            execution_profile=None,
        )
        return validate_objective_settings(normalized)

    @field_validator("execution_profile")
    @classmethod
    def _validate_profile_action_packs(
        cls,
        value: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        _, normalized = normalize_system_action_pack_settings(
            settings=None,
            execution_profile=value,
        )
        return normalized


class RunCreate(BaseModel):
    """Truthful public Run envelope.

    The accepted Flow identity is mandatory and debugger controls live inside
    ``input_ref`` so the HTTP payload has one shape for normal and debug runs.
    """

    model_config = ConfigDict(extra="forbid")

    input_ref: dict[str, Any] = Field(default_factory=dict)
    trigger: str = "manual"
    expected_flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_debug_config(self) -> "RunCreate":
        try:
            self.input_ref = normalize_input_debug(self.input_ref)
        except DebugContractError as exc:
            raise ValueError(exc.message) from exc
        return self


class FlowValidationRequest(BaseModel):
    """Ephemeral Flow body analysed without mutating the persisted System."""

    model_config = ConfigDict(extra="forbid")

    flow_definition: dict[str, Any] = Field(default_factory=dict)


class EventTriggerUpdate(BaseModel):
    """Per-System event-trigger piloting knobs (Flow Builder sources DAG,
    Phase 3). ``mode`` flips ``dry_run`` ⇄ ``live``; ``disabled`` re-arms
    (``False``) or manually opens (``True``) the circuit breaker. Both merge
    into ``System.settings['event_trigger']`` — no schema change, no migration.

    This ONLY sets mode / breaker state; it never touches the code-enforced
    governance allowlist (``triggers._GOVERNANCE``) which stays authoritative.
    """

    mode: Optional[str] = None
    disabled: Optional[bool] = None


class RunScheduleCreate(BaseModel):
    name: str = Field(default="Schedule", max_length=255)
    cron_expr: str = Field(..., min_length=1, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class RunScheduleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    cron_expr: Optional[str] = Field(default=None, min_length=1, max_length=120)
    timezone: Optional[str] = Field(default=None, max_length=64)
    input_payload: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None


class WebhookHookCreate(BaseModel):
    name: str = Field(default="Webhook", max_length=255)
    event_type: str = Field(default="webhook.received", max_length=120)
    enabled: bool = True
    secret: Optional[str] = Field(default=None, min_length=8, max_length=256)


class WebhookHookUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    event_type: Optional[str] = Field(default=None, max_length=120)
    enabled: Optional[bool] = None
    rotate_secret: bool = False


class ActiveFlowWriteOptions(BaseModel):
    expected_flow_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "Canonical SHA-256 returned by the last System read. Required for "
            "every flow write that touches a currently or prospectively active System."
        ),
    )
    flow_write_intent: Literal["replace_active_flow"] | None = Field(
        default=None,
        description=(
            "One-shot explicit intent required for destructive active-flow replacements."
        ),
    )


class SystemCreateOptions(BaseModel):
    flow_write_intent: Literal["replace_active_flow"] | None = None


class SystemUpdateOptions(ActiveFlowWriteOptions):
    """Optional controls piggy-backing on the PATCH body.

    Kept separate from :class:`SystemUpdate` so clients that don't care
    about versioning can keep their existing payload shape. The editor
    sends ``version_message`` to attach a changelog note; tests and
    background jobs can set ``skip_validation`` to bypass the DAG gate
    when they know the payload is already trusted.
    """

    expected_published_version_id: str | None = Field(
        default=None, min_length=1, max_length=36,
        description="Published Flow reviewed before activating this System.",
    )
    version_message: Optional[str] = Field(
        default=None,
        description="Optional changelog note saved alongside the new version.",
        max_length=2000,
    )
    skip_validation: bool = False


class RollbackOptions(ActiveFlowWriteOptions):
    expected_draft_revision: int | None = Field(default=None, ge=1)


class RollbackBody(BaseModel):
    message: Optional[str] = Field(
        default=None,
        description="Optional note attached to the rollback version.",
        max_length=2000,
    )


def _actor_display_name(user: User) -> str:
    """Pick a stable, human-readable actor label for audit/version rows.

    Prefer ``email`` then ``username`` then ``keycloak_sub``, falling
    back to the DB id so the field is never empty. Matches the spirit
    of ``emit_audit_event.actor`` in the SharePoint endpoints.
    """
    return (
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or getattr(user, "keycloak_sub", None)
        or getattr(user, "id", "demo-user")
    )


# ---------------- Helpers ----------------
def _canonical_flow(flow: Any) -> dict[str, Any]:
    # Historical NULL is intentionally represented as an empty object. Any
    # other persisted JSON shape is corruption, not another spelling of empty:
    # masking it would create hash collisions and let the editor overwrite it.
    return canonical_flow(flow)


def _flow_sha256(flow: Any) -> str:
    """Hash the semantic JSON tree while preserving array ordering.

    Dict key ordering is deliberately non-semantic, matching SystemVersion
    equality and the hash frozen into a Run at execution start.
    """

    return canonical_flow_sha256(flow)


def _flow_items(flow: Any, key: str) -> list[Any]:
    canonical = _canonical_flow(flow)
    items = canonical.get(key)
    return list(items) if isinstance(items, list) else []


def _flow_node_ids(flow: Any) -> set[str]:
    return {
        node_id
        for node in _flow_items(flow, "nodes")
        if isinstance(node, Mapping)
        and isinstance((node_id := node.get("id")), str)
        and bool(node_id)
    }


def _flow_uses_dag(flow: Any, workspace: Workspace) -> bool:
    """Resolve the same DAG/legacy boundary as the production dispatcher."""

    return resolve_flow_execution(flow, workspace).uses_dag


def _flow_write_summary(flow: Any) -> dict[str, Any]:
    return {
        "sha256": _flow_sha256(flow),
        "node_count": len(_flow_items(flow, "nodes")),
        "edge_count": len(_flow_items(flow, "edges")),
    }


def _active_flow_replacement_reasons(
    *,
    current_flow: Any,
    prospective_flow: Any,
    workspace: Workspace,
) -> list[str]:
    """Return stable, payload-free reasons requiring explicit operator intent."""

    reasons: list[str] = []
    current_ids = _flow_node_ids(current_flow)
    prospective_ids = _flow_node_ids(prospective_flow)
    if not prospective_ids:
        reasons.append("active_flow_empty")
    if _flow_uses_dag(current_flow, workspace) and not _flow_uses_dag(
        prospective_flow,
        workspace,
    ):
        reasons.append("active_dag_runtime_downgrade")
    if current_ids and prospective_ids and current_ids.isdisjoint(prospective_ids):
        reasons.append("active_flow_node_identity_replacement")
    return reasons


def _flow_write_conflict(
    *,
    error: Literal["flow_precondition_missing", "flow_precondition_stale"],
    code: str,
    system_id: str,
    current_flow_sha256: str,
    expected_flow_sha256: str | None,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": error,
            "code": code,
            "message": (
                "Reload the System before saving its active flow."
                if expected_flow_sha256 is not None
                else "The current flow hash is required before saving an active System."
            ),
            "system_id": system_id,
            "current_flow_sha256": current_flow_sha256,
            "expected_flow_sha256": expected_flow_sha256,
        },
    )


def _serialize(s: System) -> dict[str, Any]:
    try:
        flow = _canonical_flow(s.flow_definition)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "persisted_flow_invalid",
                "message": "The persisted flow is not a JSON object.",
                "system_id": s.id,
            },
        ) from exc
    return {
        "id": s.id,
        "workspace_id": s.workspace_id,
        "name": s.name,
        "objective": s.objective,
        "capability_id": s.capability_id,
        "skill_ids": s.skill_ids or [],
        "flow_definition": flow,
        "flow_sha256": _flow_sha256(flow),
        "settings": getattr(s, "settings", None) or {},
        # Publication authority pointer. Optional and additive: rows created
        # before migration 077, and workspaces without flow publication, keep
        # answering ``None`` here rather than changing shape.
        "published_flow_version_id": getattr(s, "published_flow_version_id", None),
        "published_at": (
            s.published_at.isoformat()
            if getattr(s, "published_at", None)
            else None
        ),
        "published_by": getattr(s, "published_by", None),
        "execution_mode": s.execution_mode,
        "execution_profile": getattr(s, "execution_profile", None) or {},
        "coordination_pattern": s.coordination_pattern,
        "control_policy_id": s.control_policy_id,
        "adaptive_policy_id": s.adaptive_policy_id,
        "context_id": s.context_id,
        "status": s.status,
        "default_prompt_type": getattr(s, "default_prompt_type", None),
        "default_model": getattr(s, "default_model", None),
        "retrieval_mode_default": getattr(s, "retrieval_mode_default", None),
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _event_trigger_state(s: System, db: Optional[DBSession] = None) -> dict[str, Any]:
    """Read-only projection of a System's event-trigger piloting state.

    Combines the GLOBAL master switch / workspace opt-in
    (``triggers.is_event_triggers_enabled``) with the per-System mode +
    circuit-breaker fields stored under ``System.settings['event_trigger']``.
    ``mode`` is resolved through the same ``triggers.trigger_mode`` the run
    engine uses, so the UI never drifts from the executor's own reading
    (anything but the literal ``live`` is ``dry_run``).
    """
    blob = getattr(s, "settings", None) or {}
    et = blob.get("event_trigger") if isinstance(blob, dict) else {}
    et = et if isinstance(et, dict) else {}
    return {
        "system_id": s.id,
        "master_enabled": triggers.is_event_triggers_enabled(s.workspace_id, db=db),
        "global_enabled": bool(settings.enable_event_triggers),
        "mode": triggers.trigger_mode(s),
        "disabled": bool(et.get("disabled")),
        "disabled_reason": et.get("disabled_reason"),
        "disabled_at": et.get("disabled_at"),
    }


# ---------------- CRUD ----------------
@router.get("")
async def list_systems(
    capability_id: Optional[str] = None,
    status: Optional[SystemStatus] = None,
    include_retired: bool = False,
    limit: int = 100,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _enforce_system_collection_read(db, user=user, workspace=workspace)
    q = db.query(System).filter(System.workspace_id == workspace.id)
    if capability_id:
        # A malformed FK must not turn a capability id from another tenant
        # into a valid scope. Universal capabilities remain intentionally
        # visible through their NULL workspace ownership.
        visible_capability = exists().where(
            and_(
                Capability.id == capability_id,
                or_(
                    Capability.workspace_id == workspace.id,
                    Capability.workspace_id.is_(None),
                ),
            )
        )
        q = q.filter(
            System.capability_id == capability_id,
            visible_capability,
        )
    if status:
        q = q.filter(System.status == status.value)
    elif not include_retired:
        # ``retired`` is the archive state: hide it from the grid unless asked,
        # so de-duplicating seeded systems stays reversible (status flip, no
        # row/run deletion).
        q = q.filter(System.status != "retired")
    rows = q.order_by(System.updated_at.desc()).limit(limit).all()
    return {"systems": [_serialize(s) for s in rows]}


@router.get("/dispatch-readiness")
async def list_dispatch_readiness(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Which Systems would be refused at the published-ingress boundary.

    Declared ahead of ``GET /{system_id}`` so the static path is not captured
    as a System id.
    """
    _enforce_system_collection_read(db, user=user, workspace=workspace)
    return dispatch_readiness.workspace_dispatch_readiness(db, workspace=workspace)


@router.post("")
async def create_system(
    body: SystemCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
    options: SystemCreateOptions = Depends(),
):
    payload = _create_system_record(body, workspace=workspace, user=user, db=db, options=options)
    db.commit()
    return payload


def _create_system_record(body: SystemCreate, *, workspace, user, db, options=None):
    """Canonical creation, leaving transaction ownership with the caller."""
    # Unit/service callers invoke the endpoint function directly and therefore
    # see FastAPI's ``Depends`` sentinel instead of dependency injection.
    if not isinstance(options, SystemCreateOptions):
        options = SystemCreateOptions()
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="admin",
        legacy_allowed=legacy_object_action_allowed(
            db,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="admin",
        ),
        resource_attrs={"capability_id": body.capability_id},
    )
    system_settings = _settings_with_managed_system_fields_preserved(
        {},
        body.settings or {},
    )
    if migration_059_system_id(workspace) is not None and _is_reserved_agentic_identity(
        system_settings, body.flow_definition
    ):
        _require_reserved_agentic_identity_admin(
            db,
            user=user,
            workspace=workspace,
        )
    if (
        body.status == SystemStatus.active
        and not _flow_node_ids(body.flow_definition)
        and options.flow_write_intent != "replace_active_flow"
    ):
        after = _flow_write_summary(body.flow_definition)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "active_flow_replace_intent_required",
                "code": "ACTIVE_FLOW_CREATION_REQUIRES_INTENT",
                "message": "Creating an active empty flow requires explicit operator intent.",
                "required_intent": "replace_active_flow",
                "reasons": ["active_flow_empty"],
                "after": after,
            },
        )
    _validate_control_policy_tenant(
        db,
        workspace_id=workspace.id,
        policy_id=body.control_policy_id,
    )
    _validate_context_tenant(
        db,
        workspace_id=workspace.id,
        context_id=body.context_id,
    )
    system_id = str(uuid4())
    _resolve_catalog_bindings_http(
        db,
        workspace=workspace,
        system_id=system_id,
        capability_id=body.capability_id,
        skill_ids=body.skill_ids,
        adaptive_policy_id=body.adaptive_policy_id,
    )
    # Validate the initial flow_definition the same way PATCH does so
    # a chain can't be born invalid. Empty flow_definition is valid
    # (draft) — the validator treats no-nodes as zero issues.
    issues = dag_validator.validate_flow(body.flow_definition or {})
    if dag_validator.has_errors(issues):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "flow_invalid",
                "message": "Flow definition has structural errors.",
                "issues": dag_validator.issues_to_payload(issues),
            },
        )

    actor = _actor_display_name(user)
    s = System(
        id=system_id,
        workspace_id=workspace.id,
        name=body.name,
        objective=body.objective,
        capability_id=body.capability_id,
        skill_ids=body.skill_ids,
        flow_definition=body.flow_definition,
        settings=system_settings,
        execution_mode=body.execution_mode.value,
        execution_profile=body.execution_profile or None,
        coordination_pattern=body.coordination_pattern,
        control_policy_id=body.control_policy_id,
        adaptive_policy_id=body.adaptive_policy_id,
        context_id=body.context_id,
        status=body.status.value,
        created_by=actor,
        default_prompt_type=body.default_prompt_type,
        default_model=body.default_model,
        retrieval_mode_default=body.retrieval_mode_default or "auto",
    )
    if system_settings.get("operational_objective") is not None:
        _enforce_operational_objective_admin(db, user=user, workspace=workspace, system=s)
    db.add(s)
    db.flush()

    # Seed v1 for every new chain so the history is never empty — the
    # UI's "Versions" panel always has at least the starting point to
    # compare against or roll back to.
    try:
        publication_state = (
            flow_publication.initialize_new_system_publication_if_enabled(
                db,
                system=s,
                workspace=workspace,
                actor=actor,
            )
        )
    except flow_publication.FlowPublicationError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, detail=exc.payload()) from exc
    if publication_state is None:
        version_service.record_new_version(
            db=db,
            system=s,
            flow_definition=body.flow_definition or {},
            created_by=actor,
            message="Initial version",
        )

    db.flush()
    db.refresh(s)
    payload = _serialize(s)
    payload["validation_warnings"] = dag_validator.issues_to_payload(
        [i for i in issues if i.level == "warn"]
    )
    return payload


@router.get("/{system_id}")
async def get_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=s)
    return _serialize(s)


def _system_360_enabled(workspace: Workspace, system: System) -> bool:
    """Literal-boolean, marker-based gate for the Showcase vertical slice."""

    from app.services.workspace_features import graduated_feature_enabled

    system_settings = system.settings if isinstance(system.settings, dict) else {}
    experience = system_settings.get("experience")
    experience = experience if isinstance(experience, dict) else {}
    return bool(
        graduated_feature_enabled(workspace, "cockpit_router_axes_v4")
        and graduated_feature_enabled(workspace, "system_360_projection_v1")
        and experience.get("system_360_canary") == "v1"
    )


@router.get("/{system_id}/perspective")
async def get_system_perspective(
    system_id: str,
    lens: Literal["build", "operate", "steer", "govern"],
    window: Literal["7d", "30d", "90d"] = "30d",
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return one lens projection without changing the canonical System.

    Both lookup and every aggregate in the read model are workspace-scoped.
    The feature/experience gate intentionally returns 404 so an unmarked
    System does not advertise a partially enabled product surface.
    """

    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .first()
    )
    if system is None or not _system_360_enabled(workspace, system):
        raise HTTPException(404, "System perspective not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    try:
        return build_system_perspective(
            db,
            workspace=workspace,
            user=user,
            system=system,
            lens=lens,
            window=window,
        )
    except PublishedMandateUnavailable as exc:
        raise HTTPException(409, detail={
            "code": "published_mandate_unavailable",
            "message": "The published mandate could not be verified. Review the System publication before relying on its access preview.",
        }) from exc


@router.get("/{system_id}/flow-manifest")
async def get_system_flow_manifest(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Runtime manifest consumed by the no-code Flow Builder.

    The response is derived from the real ``System.flow_definition`` and the
    live Skill registry, so the UI can distinguish decorative graph structure
    from nodes that actually drive /chat or run_engine execution.
    """
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=s)
    return serialize_flow_manifest(db, s)


@router.post("/{system_id}/validate-flow")
async def validate_system_flow(
    system_id: str,
    body: FlowValidationRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return hash-bound diagnostics for the exact submitted graph.

    The endpoint is intentionally non-mutating. The client may validate a
    dirty graph, but Save/Execute/Publish must bind the returned diagnostics to
    this server-computed hash and must discard them immediately after an edit.
    """

    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .first()
    )
    if system is None:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=system)

    flow = _canonical_flow(body.flow_definition)
    issues = dag_validator.validate_flow(flow)
    issues = sorted(
        issues,
        key=lambda issue: (
            0 if issue.level == "error" else 1,
            issue.node_id or "",
            issue.edge_index if issue.edge_index is not None else -1,
            issue.code,
            issue.message,
        ),
    )
    resolution = resolve_flow_execution(flow, workspace)
    return {
        "flow_sha256": _flow_sha256(flow),
        "analyzer_version": "flow-analyzer/1",
        "runtime_mode": resolution.runtime_mode,
        "valid": not dag_validator.has_errors(issues),
        "issues": dag_validator.issues_to_payload(issues),
    }


def _connected_asset_collection_slugs(flow: Optional[dict[str, Any]]) -> list[str]:
    """Collection slugs declared by ``asset`` nodes that are WIRED into the graph.

    An asset node counts only when it has at least one outbound edge (it actually
    feeds a retrieval lane); a dropped-but-unwired asset is authoring scaffolding
    and never contributes to the retrieval policy. Returns a stable, de-duped,
    sorted list (``[]`` when there are no connected asset nodes → neutral).
    """
    if not isinstance(flow, dict):
        return []
    nodes = flow.get("nodes") or []
    edges = flow.get("edges") or []
    connected_sources = {str(e.get("from")) for e in edges if isinstance(e, dict) and e.get("from")}
    slugs: list[str] = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("kind") != "asset":
            continue
        nid = str(node.get("id") or "")
        if nid and nid not in connected_sources:
            continue
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        slug = cfg.get("collection_slug")
        if isinstance(slug, str) and slug.strip() and slug.strip() not in slugs:
            slugs.append(slug.strip())
    return sorted(slugs)


def _sync_membrane_collection_allowlist(
    db: DBSession, system: System, flow: Optional[dict[str, Any]]
) -> None:
    """Phase 2 (``p2-membrane``, flag-gated): mirror the graph's connected asset
    collections into the membrane inbound allowlist on the bound ControlPolicy.

    The GRAPH becomes the retrieval policy: on flow save (flag ON) the inbound
    ``collection_allowlist`` is set to the connected ``asset`` collection slugs
    (``[]`` when there are none — neutral, never over-restrictive).

    This writes declarative metadata only. The DAG retrieval path
    (``retrieve_rag_context``) currently resolves its allowlist from the
    Workspace ``source_policy``, not this ControlPolicy. Where an authoritative
    v2 ControlPolicy is consumed, an empty intersection intentionally blocks in
    ``enforce`` and only observes in ``shadow``; it never broadens to every
    collection. We only UPDATE an EXISTING ``membrane_spec`` (never fabricate
    one) so a System with a derived spec is not silently promoted to an
    authoritative contract for the capability/outbound facets.
    """
    policy_id = getattr(system, "control_policy_id", None)
    if not policy_id:
        return
    policy = (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.id == policy_id,
            ControlPolicy.workspace_id == system.workspace_id,
            ControlPolicy.scope == "system",
            ControlPolicy.target_id == system.id,
        )
        .first()
    )
    if policy is None:
        return
    extra = dict(policy.extra) if isinstance(policy.extra, dict) else {}
    spec = extra.get("membrane_spec")
    if not isinstance(spec, dict):
        return  # no authoritative spec to sync into — leave derived behaviour intact
    spec = dict(spec)
    inbound = dict(spec.get("inbound")) if isinstance(spec.get("inbound"), dict) else {}
    slugs = _connected_asset_collection_slugs(flow)
    if list(inbound.get("collection_allowlist") or []) == slugs:
        return  # already coherent — avoid a needless write / version churn
    inbound["collection_allowlist"] = slugs
    spec["inbound"] = inbound
    extra["membrane_spec"] = spec
    # Reassign so SQLAlchemy detects the JSON column mutation.
    policy.extra = extra


@router.patch("/{system_id}")
async def update_system(
    system_id: str,
    body: SystemUpdate,
    options: SystemUpdateOptions = Depends(),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    # The same row carries server-owned rollout receipts. Lock and refresh it
    # before merging a generic settings replacement so a concurrent rollout
    # cannot be reverted by a stale, otherwise legitimate System update.
    s = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .populate_existing()
        .with_for_update(of=System)
        .first()
    )
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_admin(db, user=user, workspace=workspace, system=s)

    updates = body.model_dump(exclude_unset=True, mode="json")
    if (
        options.expected_published_version_id is not None
        and options.expected_published_version_id != s.published_flow_version_id
    ):
        raise HTTPException(409, detail={
            "code": "SYSTEM_PUBLISHED_VERSION_MISMATCH",
            "message": "The published Flow changed. Reload and review it before activating the System.",
            "system_id": s.id,
            "expected_published_version_id": options.expected_published_version_id,
            "current_published_version_id": s.published_flow_version_id,
        })
    if "settings" in updates:
        incoming = updates["settings"] or {}
        current_objective = (s.settings or {}).get("operational_objective")
        if "operational_objective" not in incoming and current_objective is not None:
            incoming = {**incoming, "operational_objective": current_objective}
        elif incoming.get("operational_objective") != current_objective:
            _enforce_operational_objective_admin(db, user=user, workspace=workspace, system=s)
        updates["settings"] = _settings_with_managed_system_fields_preserved(
            s.settings,
            incoming,
        )
    flow_touched = "flow_definition" in updates
    if flow_touched and flow_publication.flow_publication_enabled(workspace):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "flow_draft_endpoint_required",
                "code": "FLOW_DRAFT_ENDPOINT_REQUIRED",
                "message": (
                    "This workspace stores editor changes through PUT /flow-draft; "
                    "the published compatibility mirror is read-only."
                ),
                "system_id": s.id,
            },
        )
    current_flow = _canonical_flow(s.flow_definition)
    prospective_flow = updates.get("flow_definition", current_flow)
    prospective_status = updates.get("status", s.status)
    activating_empty_flow = bool(
        s.status != SystemStatus.active.value
        and prospective_status == SystemStatus.active.value
        and not _flow_node_ids(prospective_flow)
    )
    active_flow_boundary = bool(
        (
            flow_touched
            and (
                s.status == SystemStatus.active.value
                or prospective_status == SystemStatus.active.value
            )
        )
        or activating_empty_flow
    )
    flow_write_reasons: list[str] = []
    flow_write_audit: dict[str, Any] | None = None
    if flow_touched or activating_empty_flow:
        before = _flow_write_summary(current_flow)
        after = _flow_write_summary(prospective_flow)
        if active_flow_boundary:
            if options.expected_flow_sha256 is None:
                raise _flow_write_conflict(
                    error="flow_precondition_missing",
                    code="ACTIVE_FLOW_SHA256_REQUIRED",
                    system_id=s.id,
                    current_flow_sha256=before["sha256"],
                    expected_flow_sha256=None,
                )
            if options.expected_flow_sha256 != before["sha256"]:
                raise _flow_write_conflict(
                    error="flow_precondition_stale",
                    code="ACTIVE_FLOW_SHA256_MISMATCH",
                    system_id=s.id,
                    current_flow_sha256=before["sha256"],
                    expected_flow_sha256=options.expected_flow_sha256,
                )
            flow_write_reasons = _active_flow_replacement_reasons(
                current_flow=current_flow,
                prospective_flow=prospective_flow,
                workspace=workspace,
            )
            if (
                flow_write_reasons
                and options.flow_write_intent != "replace_active_flow"
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "active_flow_replace_intent_required",
                        "code": "ACTIVE_FLOW_REPLACEMENT_REQUIRES_INTENT",
                        "message": (
                            "This active flow replacement requires explicit operator intent."
                        ),
                        "system_id": s.id,
                        "required_intent": "replace_active_flow",
                        "reasons": flow_write_reasons,
                        "before": before,
                        "after": after,
                    },
                )
        flow_write_audit = {
            "before_sha256": before["sha256"],
            "after_sha256": after["sha256"],
            "before_node_count": before["node_count"],
            "after_node_count": after["node_count"],
            "before_edge_count": before["edge_count"],
            "after_edge_count": after["edge_count"],
            "intent": options.flow_write_intent,
            "reasons": flow_write_reasons,
            "active_boundary": active_flow_boundary,
        }
    changed_fields = sorted(
        key for key, value in updates.items() if getattr(s, key, None) != value
    )
    prospective_settings = updates.get("settings", s.settings)
    if migration_059_system_id(workspace) is not None and _is_reserved_agentic_identity(
        prospective_settings, prospective_flow
    ):
        _require_reserved_agentic_identity_admin(
            db,
            user=user,
            workspace=workspace,
        )
    if "control_policy_id" in updates:
        _validate_control_policy_tenant(
            db,
            workspace_id=workspace.id,
            policy_id=updates["control_policy_id"],
        )
    if "context_id" in updates:
        _validate_context_tenant(
            db,
            workspace_id=workspace.id,
            context_id=updates["context_id"],
        )
    _resolve_catalog_bindings_http(
        db,
        workspace=workspace,
        system_id=s.id,
        capability_id=updates.get("capability_id", s.capability_id),
        skill_ids=updates.get("skill_ids", s.skill_ids),
        adaptive_policy_id=updates.get("adaptive_policy_id", s.adaptive_policy_id),
    )
    new_flow = updates.get("flow_definition") if flow_touched else None

    issues: list = []
    if new_flow is not None and not options.skip_validation:
        issues = dag_validator.validate_flow(new_flow)
        if dag_validator.has_errors(issues):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "flow_invalid",
                    "message": "Flow definition has structural errors.",
                    "issues": dag_validator.issues_to_payload(issues),
                },
            )

    for k, v in updates.items():
        setattr(s, k, v)

    created_version = None
    if new_flow is not None:
        # SessionLocal deliberately disables autoflush.  Persist the pending
        # System mutation inside this transaction before ``record_new_version``
        # refreshes/locks the parent row with ``populate_existing()``; otherwise
        # that refresh would restore the old flow while appending a version of
        # the new one.
        db.flush()
        created_version = version_service.record_new_version(
            db=db,
            system=s,
            flow_definition=new_flow,
            created_by=_actor_display_name(user),
            message=options.version_message,
        )

    # Phase 2 (p2-membrane, flag-gated): when a new flow is saved, sync the
    # membrane inbound collection_allowlist from the graph's connected asset
    # nodes. Flag OFF (default) = Phase 1 behaviour (allowlist untouched).
    if new_flow is not None and settings.flow_asset_binding_authoritative:
        _sync_membrane_collection_allowlist(db, s, new_flow)

    if changed_fields:
        audit_details: dict[str, Any] = {
            "system_id": s.id,
            "fields": changed_fields,
        }
        if flow_write_audit is not None:
            audit_details["flow_write"] = flow_write_audit
        emit_audit_event(
            workspace_id=workspace.id,
            event_type="system.updated",
            actor=_actor_display_name(user),
            agent_id=s.id,
            details=audit_details,
            db=db,
        )

    db.commit()
    db.refresh(s)
    payload = _serialize(s)
    if issues:
        payload["validation_warnings"] = dag_validator.issues_to_payload(
            [i for i in issues if i.level == "warn"]
        )
    if created_version is not None:
        payload["new_version"] = version_service.serialize_version_summary(created_version)
    return payload


@router.get("/{system_id}/event-trigger")
async def get_system_event_trigger(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Current event-trigger piloting state for a System (Phase 3).

    Read-only: master switch + per-System mode + circuit-breaker status. The
    Flow Builder inspector reads this when an SFTP trigger node is selected.
    """
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=s)
    return _event_trigger_state(s, db=db)


@router.patch("/{system_id}/event-trigger")
async def update_system_event_trigger(
    system_id: str,
    body: EventTriggerUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Set a System's event-trigger ``mode`` and/or re-arm its circuit breaker.

    Merges the given fields into ``System.settings['event_trigger']`` (a plain
    JSON setting — no migration). Setting ``disabled=False`` re-arms the breaker
    and clears its provenance (``disabled_reason`` / ``disabled_at``). Governance
    stays code-enforced and is never relaxed here.
    """
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_admin(
        db,
        user=user,
        workspace=workspace,
        system=s,
        mutation="event_trigger",
    )

    updates: dict[str, Any] = {}
    if body.mode is not None:
        mode = str(body.mode).lower()
        if mode not in (triggers.TRIGGER_MODE_DRY_RUN, triggers.TRIGGER_MODE_LIVE):
            raise HTTPException(400, "mode must be 'dry_run' or 'live'")
        updates["mode"] = mode
    if body.disabled is not None:
        updates["disabled"] = bool(body.disabled)
        if not body.disabled:
            # Re-arm: clear the circuit-breaker provenance and stamp the reset.
            updates["disabled_reason"] = None
            updates["disabled_at"] = None
            updates["rearmed_at"] = datetime.utcnow().isoformat()
    if not updates:
        raise HTTPException(400, "no event-trigger fields to update")

    # Reassign a NEW dict so SQLAlchemy flags the JSON column dirty (in-place
    # mutation of a plain JSON dict is not tracked) — same pattern the run
    # engine's own writer uses.
    blob = dict(s.settings) if isinstance(s.settings, dict) else {}
    et = dict(blob.get("event_trigger") or {})
    et.update(updates)
    blob["event_trigger"] = et
    s.settings = blob
    db.commit()
    db.refresh(s)

    emit_audit_event(
        workspace_id=workspace.id,
        event_type="system.event_trigger.update",
        actor=_actor_display_name(user),
        details={"system_id": s.id, "updates": updates},
        db=db,
    )
    return _event_trigger_state(s, db=db)


@router.delete("/{system_id}", status_code=204)
async def delete_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_admin(db, user=user, workspace=workspace, system=s)
    references = version_service.experience_release_references(
        db, system_id=s.id
    )
    if references:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SYSTEM_REFERENCED_BY_EXPERIENCE_RELEASE",
                "message": "This System is referenced by an immutable Experience release.",
                "references": references,
            },
        )
    db.delete(s)
    db.commit()
    return None


# ---------------- Runs ----------------
@router.post("/{system_id}/runs")
async def trigger_run(
    system_id: str,
    body: RunCreate,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    if body.trigger == "chat_agentic":
        raise HTTPException(
            status_code=400,
            detail="The chat_agentic trigger is reserved to the server-owned chat adapter",
        )
    _enforce_system_run_authority(
        db,
        user=user,
        workspace=workspace,
        system=s,
        execution_source="systems_run_api",
    )

    # The Flow boundary is accepted under a row lock.  This closes the gap
    # where a successful POST could otherwise execute a graph saved between
    # request validation and the worker's first read.
    s = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .populate_existing()
        .with_for_update(of=System)
        .first()
    )
    if s is None:
        raise HTTPException(404, "System not found")
    try:
        published_version, flow, flow_sha256, execution_contract = (
            flow_publication.published_run_evidence(
                db,
                system=s,
                workspace=workspace,
            )
        )
    except flow_publication.FlowPublicationError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, detail=exc.payload()) from exc
    if body.expected_flow_sha256 != flow_sha256:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "run_flow_precondition_stale",
                "code": "RUN_FLOW_SHA256_MISMATCH",
                "message": "Reload the System before executing its Flow.",
                "system_id": s.id,
                "current_flow_sha256": flow_sha256,
                "expected_flow_sha256": body.expected_flow_sha256,
            },
        )
    execution_resolution = resolve_flow_execution(
        flow,
        workspace,
        pinned_runtime_mode=execution_contract.get("runtime_mode"),
    )
    if "_debug" in body.input_ref and not execution_resolution.debug_supported:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "debug_runtime_unsupported",
                "code": "RUN_DEBUG_REQUIRES_DAG",
                "message": "Flow debugging is unavailable for the sequential legacy runtime.",
                "runtime_mode": execution_resolution.runtime_mode,
            },
        )

    if flow_publication.flow_publication_enabled(workspace):
        try:
            run = flow_ingress.create_published_ingress_run(
                db,
                system_id=s.id,
                workspace=workspace,
                ingress_id=None,
                kind="manual",
                payload=body.input_ref,
                initiated_by_user_id=getattr(user, "id", None),
                expected_published_version_id=(
                    published_version.id if published_version is not None else None
                ),
                expected_flow_sha256=body.expected_flow_sha256,
                adapter_evidence={"surface": "systems_run_api"},
                trigger=body.trigger,
                allow_debug=True,
            )
        except flow_ingress.FlowIngressError as exc:
            db.rollback()
            raise HTTPException(exc.status_code, detail=exc.payload()) from exc
    else:
        input_ref = copy.deepcopy(body.input_ref)
        input_ref.pop("_ingress", None)
        raw_execution = input_ref.get("execution")
        execution = dict(raw_execution) if isinstance(raw_execution, Mapping) else {}
        for key in (
            "ingress_id",
            "ingress_selection_version",
            "published_flow_version_id",
            "execution_surface",
        ):
            execution.pop(key, None)
        # These fields are server-owned even if the caller supplied lookalikes.
        execution["flow_sha256"] = flow_sha256
        execution["runtime_mode"] = execution_resolution.runtime_mode
        execution["runtime_mode_reason"] = execution_resolution.reason
        input_ref["execution"] = execution

        run = Run(
            id=str(uuid4()),
            workspace_id=workspace.id,
            system_id=s.id,
            capability_id=s.capability_id,
            initiated_by_user_id=getattr(user, "id", None),
            input_ref=input_ref,
            flow_snapshot=copy.deepcopy(flow),
            flow_version_id=published_version.id if published_version is not None else None,
            published_flow_version_id=(
                published_version.id if published_version is not None else None
            ),
            flow_sha256=flow_sha256,
            execution_contract=copy.deepcopy(execution_contract),
            execution_surface="published_manual",
            status="pending",
            started_at=datetime.utcnow(),
            trigger=body.trigger,
        )
        db.add(run)
    db.commit()
    db.refresh(run)

    # Hand the actual execution to the canonical run_engine (Phase 6).
    background_tasks.add_task(schedule_run, run.id)
    return {
        "id": run.id,
        "status": run.status,
        "system_id": s.id,
        "trigger": body.trigger,
        "flow_sha256": flow_sha256,
        "runtime_mode": execution_resolution.runtime_mode,
    }


@router.get("/{system_id}/versions")
async def list_system_versions(
    system_id: str,
    limit: int = 100,
    offset: int = 0,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Paginated history of ``flow_definition`` snapshots for a system.

    Returns summaries (no full ``flow_definition`` payload) so the
    panel can stay responsive even at the 500-row window ceiling.
    Fetch the full body with ``GET /systems/{id}/versions/{n}``.
    """
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=s)
    rows, total = version_service.list_versions(
        db=db,
        system_id=system_id,
        workspace_id=workspace.id,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "window": None,  # filled by the client from the config endpoint if needed
        "versions": [version_service.serialize_version_summary(v) for v in rows],
    }


@router.get("/{system_id}/versions/{version_number}")
async def get_system_version(
    system_id: str,
    version_number: int,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Full version payload including ``flow_definition``. Used by the
    editor when hovering a row to preview, or when starting a
    rollback to confirm the target.
    """
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=s)
    v = version_service.get_version(
        db=db,
        system_id=system_id,
        workspace_id=workspace.id,
        version_number=version_number,
    )
    if v is None:
        raise HTTPException(404, "Version not found (may have been purged by the rolling window).")
    return version_service.serialize_version(v)


@router.post("/{system_id}/versions/{version_number}/rollback")
async def rollback_system_version(
    system_id: str,
    version_number: int,
    body: RollbackBody = RollbackBody(),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
    options: RollbackOptions = Depends(),
):
    """Roll the system back to a specific version.

    Implemented as "append a new version whose ``flow_definition``
    equals the target"; we never rewrite history. Returns the
    newly created version (or the target itself if the rollback is
    a no-op because the target is already the current flow).
    """
    if not isinstance(options, RollbackOptions):
        options = RollbackOptions()
    s = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .populate_existing()
        .with_for_update(of=System)
        .first()
    )
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_admin(
        db,
        user=user,
        workspace=workspace,
        system=s,
        mutation="version_rollback",
    )
    target = version_service.get_version(
        db=db,
        system_id=system_id,
        workspace_id=workspace.id,
        version_number=version_number,
    )
    if target is None:
        raise HTTPException(
            404,
            "Version not found (may have been purged by the rolling window).",
        )

    if flow_publication.flow_publication_enabled(workspace):
        if options.expected_draft_revision is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "flow_draft_precondition_missing",
                    "code": "FLOW_DRAFT_REVISION_REQUIRED",
                    "message": "Reload the server draft before restoring a version.",
                    "system_id": s.id,
                },
            )
        try:
            draft, no_op = flow_publication.restore_draft(
                db,
                system_id=s.id,
                workspace=workspace,
                version_id=target.id,
                expected_revision=options.expected_draft_revision,
                actor=_actor_display_name(user),
            )
        except flow_publication.FlowPublicationError as exc:
            db.rollback()
            raise HTTPException(exc.status_code, detail=exc.payload()) from exc
        db.commit()
        db.refresh(s)
        db.refresh(draft)
        return {
            "system": _serialize(s),
            "draft": {
                "revision": draft.revision,
                "flow_sha256": draft.flow_sha256,
                "flow_definition": copy.deepcopy(draft.flow_definition),
                "base_published_version_id": draft.base_published_version_id,
                "no_op": no_op,
            },
            "published_unchanged": True,
        }

    flow_write_audit: dict[str, Any] | None = None
    if s.status == SystemStatus.active.value:
        current_flow = _canonical_flow(s.flow_definition)
        target_flow = _canonical_flow(target.flow_definition)
        before = _flow_write_summary(current_flow)
        after = _flow_write_summary(target_flow)
        if options.expected_flow_sha256 is None:
            raise _flow_write_conflict(
                error="flow_precondition_missing",
                code="ACTIVE_FLOW_SHA256_REQUIRED",
                system_id=s.id,
                current_flow_sha256=before["sha256"],
                expected_flow_sha256=None,
            )
        if options.expected_flow_sha256 != before["sha256"]:
            raise _flow_write_conflict(
                error="flow_precondition_stale",
                code="ACTIVE_FLOW_SHA256_MISMATCH",
                system_id=s.id,
                current_flow_sha256=before["sha256"],
                expected_flow_sha256=options.expected_flow_sha256,
            )
        reasons = _active_flow_replacement_reasons(
            current_flow=current_flow,
            prospective_flow=target_flow,
            workspace=workspace,
        )
        if reasons and options.flow_write_intent != "replace_active_flow":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "active_flow_replace_intent_required",
                    "code": "ACTIVE_FLOW_ROLLBACK_REQUIRES_INTENT",
                    "message": "This active flow rollback requires explicit operator intent.",
                    "system_id": s.id,
                    "required_intent": "replace_active_flow",
                    "reasons": reasons,
                    "before": before,
                    "after": after,
                },
            )
        flow_write_audit = {
            "before_sha256": before["sha256"],
            "after_sha256": after["sha256"],
            "before_node_count": before["node_count"],
            "after_node_count": after["node_count"],
            "before_edge_count": before["edge_count"],
            "after_edge_count": after["edge_count"],
            "intent": options.flow_write_intent,
            "reasons": reasons,
            "active_boundary": True,
        }
    try:
        new_version = version_service.rollback_to_version(
            db=db,
            system=s,
            version_number=version_number,
            created_by=_actor_display_name(user),
            message=body.message,
            flow_write_audit=flow_write_audit,
        )
    except version_service.ChainVersionError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.commit()
    db.refresh(s)
    return {
        "system": _serialize(s),
        "new_version": version_service.serialize_version(new_version),
    }


# ---------------- Export / Import (Vague E / E3.4) ----------------


class SystemImportBody(BaseModel):
    """Import payload — the envelope produced by ``GET /{id}/export``.

    ``target_name`` lets the caller override the system name at import
    time (useful for cloning: "Chain X (copy)"). Validation and version
    seeding mirror ``POST /systems``.
    """

    envelope: dict[str, Any]
    target_name: Optional[str] = None


@router.get("/{system_id}/export")
async def export_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Serialize ``system_id`` into a portable JSON envelope.

    The payload strips DB-scoped identifiers (``id``, ``workspace_id``,
    audit metadata) and replaces per-node ``skill_id`` with ``skill_slug``
    so the receiver can rebind against its own catalog.
    """
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=s)
    actor = _actor_display_name(user)
    payload = export_service.serialize_for_export(db=db, system=s, exported_by=actor)
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="chain.export",
        actor=actor,
        details={"system_id": s.id, "system_name": s.name},
        db=db,
    )
    return payload


@router.post("/import")
async def import_system(
    body: SystemImportBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a new System from an exported envelope.

    The flow is validated through the same DAG validator as PATCH, so
    a malformed envelope cannot sneak a broken chain into the
    workspace. Skill slugs that don't resolve in the target workspace
    are reported under ``unresolved_skills`` in the response — the
    import still succeeds, the operator rebinds manually afterwards.
    """
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="admin",
        legacy_allowed=legacy_object_action_allowed(
            db,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="admin",
        ),
        resource_attrs={"mutation": "import"},
    )
    try:
        create_kwargs, report = export_service.prepare_import(
            db=db,
            envelope=body.envelope,
            workspace_id=workspace.id,
            target_name=body.target_name,
        )
    except export_service.ChainExportError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_envelope", "message": str(exc)},
        ) from exc

    flow = create_kwargs.get("flow_definition") or {}
    issues = dag_validator.validate_flow(flow)
    if dag_validator.has_errors(issues):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "flow_invalid",
                "message": "Imported flow has structural errors.",
                "issues": dag_validator.issues_to_payload(issues),
            },
        )

    imported_system_id = str(uuid4())
    _resolve_catalog_bindings_http(
        db,
        workspace=workspace,
        system_id=imported_system_id,
        capability_id=None,
        skill_ids=create_kwargs.get("skill_ids"),
        adaptive_policy_id=None,
    )
    actor = _actor_display_name(user)
    s = System(
        id=imported_system_id,
        workspace_id=workspace.id,
        name=create_kwargs["name"],
        objective=create_kwargs["objective"],
        skill_ids=create_kwargs["skill_ids"],
        flow_definition=flow,
        execution_mode=create_kwargs["execution_mode"],
        execution_profile=create_kwargs["execution_profile"] or None,
        coordination_pattern=create_kwargs["coordination_pattern"],
        status="draft",
        created_by=actor,
        default_prompt_type=create_kwargs["default_prompt_type"],
        default_model=create_kwargs["default_model"],
        retrieval_mode_default=create_kwargs["retrieval_mode_default"] or "auto",
    )
    db.add(s)
    db.flush()
    try:
        publication_state = (
            flow_publication.initialize_new_system_publication_if_enabled(
                db,
                system=s,
                workspace=workspace,
                actor=actor,
            )
        )
    except flow_publication.FlowPublicationError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, detail=exc.payload()) from exc
    if publication_state is None:
        version_service.record_new_version(
            db=db,
            system=s,
            flow_definition=flow,
            created_by=actor,
            message="Imported from envelope",
        )
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="chain.import",
        actor=actor,
        details={
            "system_id": s.id,
            "source": report.get("source", {}),
            "unresolved_skills": report.get("unresolved_skills", []),
            "task_rebind_count": len(report.get("task_node_rebinds", [])),
        },
        db=db,
    )
    db.commit()
    db.refresh(s)
    payload = _serialize(s)
    payload["import_report"] = report
    payload["validation_warnings"] = dag_validator.issues_to_payload(
        [i for i in issues if i.level == "warn"]
    )
    return payload


@router.get("/{system_id}/runs")
async def list_system_runs(
    system_id: str,
    limit: int = 50,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _get_system_or_404(
        db, system_id=system_id, workspace_id=workspace.id
    )
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    rows = readable_run_page(
        db,
        query=(
            db.query(Run)
            .filter(Run.workspace_id == workspace.id, Run.system_id == system_id)
            .order_by(Run.started_at.desc())
        ),
        limit=limit,
        user=user,
        workspace=workspace,
    )
    return {
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": r.duration_ms,
                "decision": r.decision,
                "confidence": r.confidence,
                "value_estimated": r.value_estimated,
                "cost_internal": r.cost_internal,
                "efficiency": r.efficiency,
                "trigger": r.trigger,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Run schedules (cron) + webhook hooks — orchestration Phase 3
# ---------------------------------------------------------------------------
def _get_system_or_404(db: DBSession, *, system_id: str, workspace_id: str) -> System:
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace_id).first()
    if not s:
        raise HTTPException(404, "System not found")
    return s


@router.get("/{system_id}/schedules")
async def list_system_schedules(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _get_system_or_404(
        db, system_id=system_id, workspace_id=workspace.id
    )
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    rows = (
        db.query(RunSchedule)
        .filter(RunSchedule.workspace_id == workspace.id, RunSchedule.system_id == system_id)
        .order_by(RunSchedule.created_at.desc())
        .all()
    )
    return {"schedules": [run_scheduler.serialize_schedule(r) for r in rows]}


@router.post("/{system_id}/schedules", status_code=201)
async def create_system_schedule(
    system_id: str,
    body: RunScheduleCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = _get_system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_admin(
        db, user=user, workspace=workspace, system=s, mutation="schedule_create"
    )
    try:
        next_fire = run_scheduler.validate_cron_expr(body.cron_expr, body.timezone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    row = RunSchedule(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system_id,
        name=(body.name or "Schedule").strip() or "Schedule",
        cron_expr=body.cron_expr.strip(),
        timezone=(body.timezone or "UTC").strip() or "UTC",
        input_payload=body.input_payload or {},
        enabled=bool(body.enabled),
        next_fire_at=next_fire if body.enabled else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="system.schedule.create",
        actor=_actor_display_name(user),
        details={"system_id": system_id, "schedule_id": row.id, "cron_expr": row.cron_expr},
        db=db,
    )
    return run_scheduler.serialize_schedule(row)


@router.patch("/{system_id}/schedules/{schedule_id}")
async def update_system_schedule(
    system_id: str,
    schedule_id: str,
    body: RunScheduleUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = _get_system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_admin(
        db, user=user, workspace=workspace, system=s, mutation="schedule_update"
    )
    row = (
        db.query(RunSchedule)
        .filter(
            RunSchedule.id == schedule_id,
            RunSchedule.system_id == system_id,
            RunSchedule.workspace_id == workspace.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Schedule not found")

    if body.name is not None:
        row.name = body.name.strip() or row.name
    if body.input_payload is not None:
        row.input_payload = body.input_payload
    if body.cron_expr is not None:
        row.cron_expr = body.cron_expr.strip()
    if body.timezone is not None:
        row.timezone = body.timezone.strip() or "UTC"
    if body.enabled is not None:
        row.enabled = bool(body.enabled)

    try:
        next_fire = run_scheduler.validate_cron_expr(row.cron_expr, row.timezone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    row.next_fire_at = next_fire if row.enabled else None
    db.commit()
    db.refresh(row)
    return run_scheduler.serialize_schedule(row)


@router.delete("/{system_id}/schedules/{schedule_id}", status_code=204)
async def delete_system_schedule(
    system_id: str,
    schedule_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = _get_system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_admin(
        db, user=user, workspace=workspace, system=s, mutation="schedule_delete"
    )
    row = (
        db.query(RunSchedule)
        .filter(
            RunSchedule.id == schedule_id,
            RunSchedule.system_id == system_id,
            RunSchedule.workspace_id == workspace.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Schedule not found")
    db.delete(row)
    db.commit()
    return None


@router.get("/{system_id}/hooks")
async def list_system_hooks(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _get_system_or_404(
        db, system_id=system_id, workspace_id=workspace.id
    )
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    rows = (
        db.query(WebhookHook)
        .filter(WebhookHook.workspace_id == workspace.id, WebhookHook.system_id == system_id)
        .order_by(WebhookHook.created_at.desc())
        .all()
    )
    return {"hooks": [serialize_hook(r) for r in rows]}


@router.post("/{system_id}/hooks", status_code=201)
async def create_system_hook(
    system_id: str,
    body: WebhookHookCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = _get_system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_admin(
        db, user=user, workspace=workspace, system=s, mutation="hook_create"
    )
    secret = (body.secret or "").strip() or generate_hook_secret()
    event_type = (
        (body.event_type or triggers.EVENT_WEBHOOK_RECEIVED).strip()
        or triggers.EVENT_WEBHOOK_RECEIVED
    )
    row = WebhookHook(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system_id,
        name=(body.name or "Webhook").strip() or "Webhook",
        event_type=event_type,
        secret=secret,
        enabled=bool(body.enabled),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="system.hook.create",
        actor=_actor_display_name(user),
        details={"system_id": system_id, "hook_id": row.id, "event_type": row.event_type},
        db=db,
    )
    # Secret is returned once at creation so the operator can copy it.
    return serialize_hook(row, include_secret=True)


@router.patch("/{system_id}/hooks/{hook_id}")
async def update_system_hook(
    system_id: str,
    hook_id: str,
    body: WebhookHookUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = _get_system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_admin(
        db, user=user, workspace=workspace, system=s, mutation="hook_update"
    )
    row = (
        db.query(WebhookHook)
        .filter(
            WebhookHook.id == hook_id,
            WebhookHook.system_id == system_id,
            WebhookHook.workspace_id == workspace.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Hook not found")

    if body.name is not None:
        row.name = body.name.strip() or row.name
    if body.event_type is not None:
        row.event_type = body.event_type.strip() or triggers.EVENT_WEBHOOK_RECEIVED
    if body.enabled is not None:
        row.enabled = bool(body.enabled)
    include_secret = False
    if body.rotate_secret:
        row.secret = generate_hook_secret()
        include_secret = True
    db.commit()
    db.refresh(row)
    return serialize_hook(row, include_secret=include_secret)


@router.delete("/{system_id}/hooks/{hook_id}", status_code=204)
async def delete_system_hook(
    system_id: str,
    hook_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    s = _get_system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_admin(
        db, user=user, workspace=workspace, system=s, mutation="hook_delete"
    )
    row = (
        db.query(WebhookHook)
        .filter(
            WebhookHook.id == hook_id,
            WebhookHook.system_id == system_id,
            WebhookHook.workspace_id == workspace.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Hook not found")
    db.delete(row)
    db.commit()
    return None


@router.get("/{system_id}/operational-metrics")
async def get_operational_metrics(system_id: str, workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    system = db.query(System).filter_by(id=system_id, workspace_id=workspace.id).first()
    if not system:
        raise HTTPException(404, "System not found")
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    from app.services.operational_metrics import operational_metrics
    try:
        _enforce_operational_objective_admin(db, user=user, workspace=workspace, system=system)
        can_edit = True
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        can_edit = False
    return {**operational_metrics(db, user=user, workspace=workspace, system=system), "can_edit": can_edit}


@router.put("/{system_id}/operational-objective")
async def put_operational_objective(system_id: str, body: OperationalObjective,
    workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    system = db.query(System).filter_by(id=system_id, workspace_id=workspace.id).populate_existing().with_for_update().first()
    if not system:
        raise HTTPException(404, "System not found")
    _enforce_operational_objective_admin(db, user=user, workspace=workspace, system=system)
    system.settings = {**(system.settings or {}), "operational_objective": body.model_dump(mode="json")}
    from app.services.audit_logger import emit_audit_event
    emit_audit_event(db=db, workspace_id=workspace.id, event_type="system.objective.updated", actor=user.id,
        details={"system_id": system.id, "metric": body.metric})
    db.commit()
    return body.model_dump(mode="json")


def _enforce_operational_objective_admin(db, *, user, workspace, system):
    from app.services.iam.legacy_authority import legacy_workspace_admin
    _require_managed_system_admin(db, user=user, workspace=workspace, system=system)
    enforce_action(
        db, user=user, workspace=workspace, resource_kind="system", action="admin",
        legacy_allowed=legacy_workspace_admin(db, user=user, workspace=workspace),
        resource_attrs={"system_id": system.id, "capability_id": system.capability_id,
                        "mutation": "operational_objective"},
    )
