"""Workspace-scoped SystemBinding CRUD, resolve, and published-ingress invoke."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.run import Run
from app.models.system import System
from app.models.system_binding import (
    CONFIRMATION_POLICIES,
    ON_UNAVAILABLE_POLICIES,
    SystemBinding,
)
from app.models.system_version import SystemVersion
from app.services.audit_logger import emit_audit_event
from app.services.systems import flow_ingress, flow_publication
from app.services.workspace_features import feature_enabled, graduated_feature_enabled

FEATURE_KEY = "experience_v1"
STUDIO_FEATURE_KEY = "experience_studio_v1"
NAWA_PASSWORD_RESET_KEY = "nawa.password_reset"
BINDING_KEY_RE = re.compile(r"^[a-z][a-z0-9._-]{0,119}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ResolveStatus = Literal["ok", "unavailable", "drift"]


@dataclass(slots=True)
class BindingError(Exception):
    code: str
    message: str
    status_code: int = 409
    details: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "error": self.code.lower(),
            "code": self.code,
            "message": self.message,
            **copy.deepcopy(self.details or {}),
        }


def experience_v1_enabled(workspace: Any) -> bool:
    return feature_enabled(workspace, FEATURE_KEY)


def require_experience_v1(workspace: Any) -> None:
    if not experience_v1_enabled(workspace):
        raise BindingError(
            code="EXPERIENCE_V1_DISABLED",
            message="Experience bindings are not enabled for this workspace.",
            status_code=404,
        )


def experience_studio_v1_enabled(workspace: Any) -> bool:
    return experience_v1_enabled(workspace) and graduated_feature_enabled(
        workspace, STUDIO_FEATURE_KEY
    )


def require_experience_studio_v1(workspace: Any) -> None:
    require_experience_v1(workspace)
    if not graduated_feature_enabled(workspace, STUDIO_FEATURE_KEY):
        raise BindingError(
            code="EXPERIENCE_STUDIO_V1_DISABLED",
            message="Experience authoring is not enabled for this workspace.",
            status_code=404,
        )


def serialize_binding(row: SystemBinding) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "binding_key": row.binding_key,
        "system_id": row.system_id,
        "published_flow_version_id": row.published_flow_version_id,
        "flow_sha256": row.flow_sha256,
        "ingress_id": row.ingress_id,
        "input_schema_sha256": row.input_schema_sha256,
        "output_schema_sha256": row.output_schema_sha256,
        "confirmation_policy": row.confirmation_policy,
        "on_unavailable": row.on_unavailable,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _validate_key(binding_key: str) -> str:
    key = (binding_key or "").strip()
    if not BINDING_KEY_RE.fullmatch(key):
        raise BindingError(
            code="BINDING_KEY_INVALID",
            message="binding_key must be a lowercase dotted identifier.",
            status_code=422,
        )
    return key


def _validate_policy(value: str, allowed: tuple[str, ...], *, field: str) -> str:
    if value not in allowed:
        raise BindingError(
            code="BINDING_POLICY_INVALID",
            message=f"{field} must be one of {', '.join(allowed)}.",
            status_code=422,
            details={"field": field},
        )
    return value


def _owned_system(db: DBSession, *, workspace_id: str, system_id: str) -> System:
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace_id)
        .one_or_none()
    )
    if system is None:
        raise BindingError(code="SYSTEM_NOT_FOUND", message="System not found.", status_code=404)
    return system


def _owned_version(
    db: DBSession,
    *,
    system: System,
    version_id: str,
) -> SystemVersion:
    version = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.id == version_id,
            SystemVersion.system_id == system.id,
            SystemVersion.workspace_id == system.workspace_id,
        )
        .one_or_none()
    )
    if version is None:
        raise BindingError(
            code="PUBLISHED_FLOW_VERSION_INVALID",
            message="The published pointer does not reference an owned immutable version.",
            status_code=422,
        )
    return version


def _contract_ingress(contract: Mapping[str, Any], ingress_id: str) -> Mapping[str, Any]:
    raw = contract.get("ingresses")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping) and item.get("ingress_id") == ingress_id:
                return item
    raise BindingError(
        code="BINDING_INGRESS_NOT_PUBLISHED",
        message="The requested ingress is not part of the published Flow contract.",
        status_code=422,
        details={"ingress_id": ingress_id},
    )


def _output_schema_sha256(contract: Mapping[str, Any]) -> str | None:
    outputs = contract.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1:
        return None
    item = outputs[0]
    if not isinstance(item, Mapping):
        return None
    digest = item.get("schema_sha256")
    if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
        return digest
    return None


def _has_direct_hitl(flow: Mapping[str, Any]) -> bool:
    nodes = flow.get("nodes")
    return isinstance(nodes, list) and any(
        isinstance(node, Mapping) and node.get("kind") == "hitl" for node in nodes
    )


def _snapshot_from_published(
    db: DBSession,
    *,
    workspace: Any,
    system: System,
    published_flow_version_id: str,
    ingress_id: str,
) -> dict[str, str | None]:
    if system.published_flow_version_id != published_flow_version_id:
        raise BindingError(
            code="BINDING_NOT_CURRENT_PUBLISH",
            message="A binding can only lock the System's currently published Flow version.",
            status_code=422,
            details={
                "published_flow_version_id": published_flow_version_id,
                "current_published_flow_version_id": system.published_flow_version_id,
            },
        )
    version = _owned_version(db, system=system, version_id=published_flow_version_id)
    try:
        current, _flow, flow_sha256, contract = flow_publication.published_run_evidence(
            db,
            system=system,
            workspace=workspace,
        )
    except flow_publication.FlowPublicationError as exc:
        raise BindingError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=copy.deepcopy(exc.details),
        ) from exc
    current_id = getattr(current, "id", None) or system.published_flow_version_id
    if current_id != version.id:
        raise BindingError(
            code="BINDING_NOT_CURRENT_PUBLISH",
            message="A binding can only lock the System's currently published Flow version.",
            status_code=422,
        )
    ingress = _contract_ingress(contract, ingress_id)
    input_sha = ingress.get("input_schema_sha256")
    if not isinstance(input_sha, str) or not SHA256_RE.fullmatch(input_sha):
        raise BindingError(
            code="BINDING_INGRESS_SCHEMA_MISSING",
            message="The published ingress has no input_schema_sha256.",
            status_code=422,
        )
    return {
        "published_flow_version_id": version.id,
        "flow_sha256": flow_sha256,
        "ingress_id": str(ingress["ingress_id"]),
        "input_schema_sha256": input_sha,
        "output_schema_sha256": _output_schema_sha256(contract),
    }


def lookup_bound_system_id(
    db: DBSession,
    *,
    workspace_id: str,
    binding_key: str,
) -> str | None:
    """Return the bound system_id when the key exists. Missing keys are not errors."""
    key = (binding_key or "").strip()
    if not BINDING_KEY_RE.fullmatch(key):
        return None
    row = (
        db.query(SystemBinding)
        .filter(
            SystemBinding.workspace_id == workspace_id,
            SystemBinding.binding_key == key,
        )
        .one_or_none()
    )
    return row.system_id if row is not None else None


def get_binding(db: DBSession, *, workspace_id: str, binding_key: str) -> SystemBinding:
    key = _validate_key(binding_key)
    row = (
        db.query(SystemBinding)
        .filter(
            SystemBinding.workspace_id == workspace_id,
            SystemBinding.binding_key == key,
        )
        .one_or_none()
    )
    if row is None:
        raise BindingError(code="BINDING_NOT_FOUND", message="System binding not found.", status_code=404)
    return row


def list_bindings(db: DBSession, *, workspace_id: str) -> list[SystemBinding]:
    return (
        db.query(SystemBinding)
        .filter(SystemBinding.workspace_id == workspace_id)
        .order_by(SystemBinding.binding_key.asc())
        .all()
    )


def list_drifted_bindings(db: DBSession, *, workspace: Any) -> list[dict[str, Any]]:
    drifted: list[dict[str, Any]] = []
    for row in list_bindings(db, workspace_id=workspace.id):
        resolved = resolve_binding(db, workspace=workspace, binding_key=row.binding_key)
        if resolved["status"] in ("drift", "unavailable"):
            drifted.append(resolved)
    return drifted


def create_binding(
    db: DBSession,
    *,
    workspace: Any,
    actor: str | None,
    binding_key: str,
    system_id: str,
    published_flow_version_id: str,
    ingress_id: str,
    confirmation_policy: str,
    on_unavailable: str,
) -> SystemBinding:
    key = _validate_key(binding_key)
    policy = _validate_policy(
        confirmation_policy, CONFIRMATION_POLICIES, field="confirmation_policy"
    )
    unavailable = _validate_policy(
        on_unavailable, ON_UNAVAILABLE_POLICIES, field="on_unavailable"
    )
    existing = (
        db.query(SystemBinding)
        .filter(
            SystemBinding.workspace_id == workspace.id,
            SystemBinding.binding_key == key,
        )
        .one_or_none()
    )
    if existing is not None:
        raise BindingError(
            code="BINDING_KEY_EXISTS",
            message="A binding with this key already exists in the workspace.",
            status_code=409,
            details={"binding_key": key},
        )
    system = _owned_system(db, workspace_id=workspace.id, system_id=system_id)
    snapshot = _snapshot_from_published(
        db,
        workspace=workspace,
        system=system,
        published_flow_version_id=published_flow_version_id,
        ingress_id=ingress_id,
    )
    now = datetime.utcnow()
    row = SystemBinding(
        id=str(uuid4()),
        workspace_id=workspace.id,
        binding_key=key,
        system_id=system.id,
        published_flow_version_id=snapshot["published_flow_version_id"],
        flow_sha256=snapshot["flow_sha256"],
        ingress_id=snapshot["ingress_id"],
        input_schema_sha256=snapshot["input_schema_sha256"],
        output_schema_sha256=snapshot["output_schema_sha256"],
        confirmation_policy=policy,
        on_unavailable=unavailable,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise BindingError(
            code="BINDING_KEY_EXISTS",
            message="A binding with this key already exists in the workspace.",
            status_code=409,
            details={"binding_key": key},
        ) from exc
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.binding.created",
        actor=actor or "unknown",
        agent_id=system.id,
        details={
            "binding_key": row.binding_key,
            "system_id": row.system_id,
            "published_flow_version_id": row.published_flow_version_id,
            "ingress_id": row.ingress_id,
            "confirmation_policy": row.confirmation_policy,
            "on_unavailable": row.on_unavailable,
        },
        db=db,
    )
    return row


def update_binding(
    db: DBSession,
    *,
    workspace: Any,
    binding_key: str,
    confirmation_policy: str | None = None,
    on_unavailable: str | None = None,
    published_flow_version_id: str | None = None,
    ingress_id: str | None = None,
    actor: str | None = None,
) -> SystemBinding:
    row = get_binding(db, workspace_id=workspace.id, binding_key=binding_key)
    before = serialize_binding(row)
    if confirmation_policy is not None:
        row.confirmation_policy = _validate_policy(
            confirmation_policy, CONFIRMATION_POLICIES, field="confirmation_policy"
        )
    if on_unavailable is not None:
        row.on_unavailable = _validate_policy(
            on_unavailable, ON_UNAVAILABLE_POLICIES, field="on_unavailable"
        )
    retarget = published_flow_version_id is not None or ingress_id is not None
    if retarget:
        system = _owned_system(db, workspace_id=workspace.id, system_id=row.system_id)
        snapshot = _snapshot_from_published(
            db,
            workspace=workspace,
            system=system,
            published_flow_version_id=published_flow_version_id or row.published_flow_version_id,
            ingress_id=ingress_id or row.ingress_id,
        )
        row.published_flow_version_id = snapshot["published_flow_version_id"]
        row.flow_sha256 = snapshot["flow_sha256"]
        row.ingress_id = snapshot["ingress_id"]
        row.input_schema_sha256 = snapshot["input_schema_sha256"]
        row.output_schema_sha256 = snapshot["output_schema_sha256"]
    after = serialize_binding(row)
    changed_fields = [
        field
        for field in (
            "published_flow_version_id",
            "flow_sha256",
            "ingress_id",
            "input_schema_sha256",
            "output_schema_sha256",
            "confirmation_policy",
            "on_unavailable",
        )
        if before[field] != after[field]
    ]
    if not changed_fields:
        return row
    row.updated_at = datetime.utcnow()
    db.flush()
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.binding.updated",
        actor=actor or "unknown",
        agent_id=row.system_id,
        details={
            "binding_key": row.binding_key,
            "system_id": row.system_id,
            "changed_fields": changed_fields,
            "from": {field: before[field] for field in changed_fields},
            "to": {field: after[field] for field in changed_fields},
        },
        db=db,
    )
    return row


def retarget_binding(
    db: DBSession,
    *,
    workspace: Any,
    binding_key: str,
    actor: str,
) -> SystemBinding:
    row = get_binding(db, workspace_id=workspace.id, binding_key=binding_key)
    system = _owned_system(db, workspace_id=workspace.id, system_id=row.system_id)
    if not system.published_flow_version_id:
        raise BindingError(
            code="BINDING_NOT_CURRENT_PUBLISH",
            message="A binding can only lock the System's currently published Flow version.",
            status_code=422,
        )
    before = {
        "published_flow_version_id": row.published_flow_version_id,
        "flow_sha256": row.flow_sha256,
        "ingress_id": row.ingress_id,
        "input_schema_sha256": row.input_schema_sha256,
        "output_schema_sha256": row.output_schema_sha256,
    }
    snapshot = _snapshot_from_published(
        db,
        workspace=workspace,
        system=system,
        published_flow_version_id=system.published_flow_version_id,
        ingress_id=row.ingress_id,
    )
    row.published_flow_version_id = snapshot["published_flow_version_id"]
    row.flow_sha256 = snapshot["flow_sha256"]
    row.ingress_id = snapshot["ingress_id"]
    row.input_schema_sha256 = snapshot["input_schema_sha256"]
    row.output_schema_sha256 = snapshot["output_schema_sha256"]
    row.updated_at = datetime.utcnow()
    db.flush()
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.binding.retargeted",
        actor=actor,
        agent_id=system.id,
        details={
            "binding_key": row.binding_key,
            "system_id": system.id,
            "from": before,
            "to": snapshot,
        },
        db=db,
    )
    return row


def _is_seed_stub_contract(contract: Any) -> bool:
    if not isinstance(contract, Mapping):
        return True
    return not contract.get("contract_sha256")


def retarget_seed_stub_bindings(
    db: DBSession,
    *,
    workspace: Any,
    system: System,
    actor: str,
) -> list[SystemBinding]:
    """Retarget seed bindings locked to a stub contract after the first real publish.

    089 freezes ingress/sink hashes without the ORM compiler. The first API
    Publish compiles a full ``execution_contract`` (with ``contract_sha256``).
    Seed-created bindings that still point at that stub would otherwise drift
    until an operator retargets them. Author-created bindings stay put.
    """
    rows = (
        db.query(SystemBinding)
        .filter(
            SystemBinding.workspace_id == workspace.id,
            SystemBinding.system_id == system.id,
        )
        .all()
    )
    updated: list[SystemBinding] = []
    for row in rows:
        if not (row.created_by or "").startswith("system:"):
            continue
        locked = (
            db.query(SystemVersion)
            .filter(
                SystemVersion.id == row.published_flow_version_id,
                SystemVersion.system_id == system.id,
            )
            .one_or_none()
        )
        contract = (locked.execution_contract if locked is not None else None) or {}
        if not _is_seed_stub_contract(contract):
            continue
        try:
            updated.append(
                retarget_binding(
                    db,
                    workspace=workspace,
                    binding_key=row.binding_key,
                    actor=actor,
                )
            )
        except BindingError:
            continue
    return updated


def delete_binding(
    db: DBSession,
    *,
    workspace_id: str,
    binding_key: str,
    actor: str | None = None,
) -> None:
    row = get_binding(db, workspace_id=workspace_id, binding_key=binding_key)
    emit_audit_event(
        workspace_id=workspace_id,
        event_type="experience.binding.deleted",
        actor=actor or "unknown",
        agent_id=row.system_id,
        details={
            "binding_key": row.binding_key,
            "system_id": row.system_id,
            "published_flow_version_id": row.published_flow_version_id,
            "ingress_id": row.ingress_id,
        },
        db=db,
    )
    db.delete(row)
    db.flush()


def resolve_binding(
    db: DBSession,
    *,
    workspace: Any,
    binding_key: str,
) -> dict[str, Any]:
    row = get_binding(db, workspace_id=workspace.id, binding_key=binding_key)
    reasons: list[str] = []
    system = (
        db.query(System)
        .filter(System.id == row.system_id, System.workspace_id == workspace.id)
        .one_or_none()
    )
    if system is None:
        return _resolve_payload("unavailable", row, ["system_missing"])
    if system.status != "active":
        return _resolve_payload("unavailable", row, ["system_inactive"])
    version = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.id == row.published_flow_version_id,
            SystemVersion.system_id == system.id,
            SystemVersion.workspace_id == workspace.id,
        )
        .one_or_none()
    )
    if version is None:
        return _resolve_payload("unavailable", row, ["published_version_missing"])
    try:
        _, flow, flow_sha256, contract = flow_publication.version_run_evidence(
            db,
            system=system,
            workspace=workspace,
            version_id=row.published_flow_version_id,
        )
    except flow_publication.FlowPublicationError:
        return _resolve_payload("unavailable", row, ["locked_evidence_unavailable"])
    raw = contract.get("ingresses")
    ingress = next(
        (
            item
            for item in raw
            if isinstance(item, Mapping) and item.get("ingress_id") == row.ingress_id
        ),
        None,
    ) if isinstance(raw, list) else None
    if ingress is None:
        reasons.append("ingress_missing")
    input_sha = ingress.get("input_schema_sha256") if isinstance(ingress, Mapping) else None
    if flow_sha256 != row.flow_sha256:
        reasons.append("flow_sha256_mismatch")
    if ingress is not None and input_sha != row.input_schema_sha256:
        reasons.append("input_schema_sha256_mismatch")
    if _output_schema_sha256(contract) != row.output_schema_sha256:
        reasons.append("output_schema_sha256_mismatch")
    if system.published_flow_version_id is None:
        return _resolve_payload("unavailable", row, ["published_version_missing"])
    if system.published_flow_version_id != row.published_flow_version_id:
        reasons.append("published_flow_version_id_mismatch")
    if any(item.endswith("_mismatch") for item in reasons):
        return _resolve_payload("drift", row, reasons)
    if reasons:
        return _resolve_payload("unavailable", row, reasons)
    if row.confirmation_policy == "hitl" and not _has_direct_hitl(flow):
        return _resolve_payload("unavailable", row, ["hitl_gate_missing"])
    payload = _resolve_payload("ok", row, [])
    input_schema = ingress.get("input_schema") if isinstance(ingress, Mapping) else None
    if isinstance(input_schema, Mapping):
        payload["input_schema"] = copy.deepcopy(dict(input_schema))
    outputs = contract.get("outputs")
    if isinstance(outputs, list) and len(outputs) == 1 and isinstance(outputs[0], Mapping):
        output_schema = outputs[0].get("schema")
        if isinstance(output_schema, Mapping):
            payload["output_schema"] = copy.deepcopy(dict(output_schema))
    return payload


def resolve_binding_snapshot(
    db: DBSession,
    *,
    workspace: Any,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve immutable release evidence without reading SystemBinding."""
    required = (
        "binding_key",
        "system_id",
        "published_flow_version_id",
        "flow_sha256",
        "ingress_id",
        "input_schema_sha256",
        "confirmation_policy",
        "on_unavailable",
    )
    if any(
        not isinstance(snapshot.get(field), str)
        or not snapshot[field]
        or snapshot[field] != snapshot[field].strip()
        for field in required
    ):
        raise BindingError(
            code="RELEASE_BINDING_SNAPSHOT_INVALID",
            message="The deployed release contains an invalid binding snapshot.",
            status_code=409,
        )
    binding = copy.deepcopy(dict(snapshot))
    if (
        not BINDING_KEY_RE.fullmatch(binding["binding_key"])
        or not SHA256_RE.fullmatch(binding["flow_sha256"])
        or not SHA256_RE.fullmatch(binding["input_schema_sha256"])
        or (
            binding.get("output_schema_sha256") is not None
            and (
                not isinstance(binding["output_schema_sha256"], str)
                or not SHA256_RE.fullmatch(binding["output_schema_sha256"])
            )
        )
        or binding["confirmation_policy"] not in CONFIRMATION_POLICIES
        or binding["on_unavailable"] not in ON_UNAVAILABLE_POLICIES
    ):
        raise BindingError(
            code="RELEASE_BINDING_SNAPSHOT_INVALID",
            message="The deployed release contains an invalid binding snapshot.",
            status_code=409,
        )
    system = (
        db.query(System)
        .filter(
            System.id == binding["system_id"],
            System.workspace_id == workspace.id,
        )
        .one_or_none()
    )
    if system is None:
        return {"status": "unavailable", "binding": binding, "reasons": ["system_missing"]}
    if system.status != "active":
        return {"status": "unavailable", "binding": binding, "reasons": ["system_inactive"]}
    try:
        _version, flow, flow_sha256, contract = flow_publication.version_run_evidence(
            db,
            system=system,
            workspace=workspace,
            version_id=binding["published_flow_version_id"],
        )
    except flow_publication.FlowPublicationError as exc:
        return {
            "status": "unavailable",
            "binding": binding,
            "reasons": [exc.code.lower()],
        }
    try:
        ingress = _contract_ingress(contract, binding["ingress_id"])
    except BindingError:
        return {"status": "unavailable", "binding": binding, "reasons": ["ingress_missing"]}
    reasons: list[str] = []
    if flow_sha256 != binding["flow_sha256"]:
        reasons.append("flow_sha256_mismatch")
    if ingress.get("input_schema_sha256") != binding["input_schema_sha256"]:
        reasons.append("input_schema_sha256_mismatch")
    if _output_schema_sha256(contract) != binding.get("output_schema_sha256"):
        reasons.append("output_schema_sha256_mismatch")
    if binding["confirmation_policy"] == "hitl" and not _has_direct_hitl(flow):
        return {
            "status": "unavailable",
            "binding": binding,
            "reasons": ["hitl_gate_missing"],
        }
    return {
        "status": "drift" if reasons else "ok",
        "binding": binding,
        "reasons": reasons,
    }


def _resolve_payload(
    status: ResolveStatus,
    row: SystemBinding,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "binding": serialize_binding(row),
        "reasons": reasons,
    }


def invoke_binding(
    db: DBSession,
    *,
    workspace: Any,
    binding_key: str,
    payload: Mapping[str, Any],
    confirmed: bool | None,
    initiated_by_user_id: str | None,
    actor: str,
) -> Run:
    resolved = resolve_binding(db, workspace=workspace, binding_key=binding_key)
    if resolved["status"] != "ok":
        raise BindingError(
            code="BINDING_NOT_OK",
            message="The binding is not currently invokable.",
            status_code=409,
            details=resolved,
        )
    row = get_binding(db, workspace_id=workspace.id, binding_key=binding_key)
    if row.confirmation_policy == "confirm" and confirmed is not True:
        raise BindingError(
            code="BINDING_CONFIRMATION_REQUIRED",
            message="This binding requires confirmed=true before a Run can start.",
            status_code=409,
            details={"confirmation_policy": row.confirmation_policy, "status": "confirm_required"},
        )
    system = _owned_system(db, workspace_id=workspace.id, system_id=row.system_id)
    try:
        _version, _flow, flow_sha256, contract = flow_publication.version_run_evidence(
            db,
            system=system,
            workspace=workspace,
            version_id=row.published_flow_version_id,
        )
    except flow_publication.FlowPublicationError as exc:
        raise BindingError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=copy.deepcopy(exc.details),
        ) from exc
    ingress = _contract_ingress(contract, row.ingress_id)
    kind = str(ingress.get("kind") or "manual")
    version_id = getattr(_version, "id", None) or system.published_flow_version_id
    try:
        run = flow_ingress.create_published_ingress_run(
            db,
            system_id=system.id,
            workspace=workspace,
            ingress_id=row.ingress_id,
            kind=kind,
            payload=payload,
            initiated_by_user_id=initiated_by_user_id,
            expected_published_version_id=row.published_flow_version_id,
            expected_flow_sha256=row.flow_sha256,
            adapter_evidence={
                "surface": "experience",
                "origin": f"experience:{row.binding_key}",
            },
            trigger="manual",
            authority_version_id=row.published_flow_version_id,
        )
    except flow_ingress.FlowIngressError as exc:
        raise BindingError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=copy.deepcopy(exc.details),
        ) from exc
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.binding.invoked",
        actor=actor,
        agent_id=system.id,
        details={
            "binding_key": row.binding_key,
            "system_id": system.id,
            "run_id": run.id,
            "ingress_id": row.ingress_id,
            "published_flow_version_id": version_id,
        },
        db=db,
    )
    return run


def invoke_binding_snapshot(
    db: DBSession,
    *,
    workspace: Any,
    snapshot: Mapping[str, Any],
    payload: Mapping[str, Any],
    confirmed: bool | None,
    initiated_by_user_id: str | None,
    actor: str,
    provenance: Mapping[str, Any],
    trigger_dedup_key: str,
    experience_idempotency_key: str,
) -> Run:
    """Invoke exactly the SystemVersion captured by an ExperienceRelease."""
    resolved = resolve_binding_snapshot(db, workspace=workspace, snapshot=snapshot)
    if resolved["status"] != "ok":
        raise BindingError(
            code="BINDING_NOT_OK",
            message="The released binding is not currently invokable.",
            status_code=409,
            details=resolved,
        )
    binding = resolved["binding"]
    if binding["confirmation_policy"] == "confirm" and confirmed is not True:
        raise BindingError(
            code="BINDING_CONFIRMATION_REQUIRED",
            message="This binding requires confirmed=true before a Run can start.",
            status_code=409,
            details={"confirmation_policy": "confirm", "status": "confirm_required"},
        )
    system = _owned_system(
        db,
        workspace_id=workspace.id,
        system_id=binding["system_id"],
    )
    try:
        _version, _flow, flow_sha256, contract = flow_publication.version_run_evidence(
            db,
            system=system,
            workspace=workspace,
            version_id=binding["published_flow_version_id"],
        )
        ingress = _contract_ingress(contract, binding["ingress_id"])
        run = flow_ingress.create_published_ingress_run(
            db,
            system_id=system.id,
            workspace=workspace,
            ingress_id=binding["ingress_id"],
            kind=str(ingress.get("kind") or "manual"),
            payload=payload,
            initiated_by_user_id=initiated_by_user_id,
            expected_published_version_id=binding["published_flow_version_id"],
            expected_flow_sha256=flow_sha256,
            adapter_evidence=copy.deepcopy(dict(provenance)),
            trigger="manual",
            trigger_dedup_key=trigger_dedup_key,
            experience_idempotency_key=experience_idempotency_key,
            authority_version_id=binding["published_flow_version_id"],
        )
    except (flow_publication.FlowPublicationError, flow_ingress.FlowIngressError) as exc:
        raise BindingError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=copy.deepcopy(exc.details),
        ) from exc
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.binding.invoked",
        actor=actor,
        agent_id=system.id,
        details={
            **copy.deepcopy(dict(provenance)),
            "system_id": system.id,
            "run_id": run.id,
            "ingress_id": binding["ingress_id"],
            "published_flow_version_id": binding["published_flow_version_id"],
        },
        db=db,
    )
    return run
