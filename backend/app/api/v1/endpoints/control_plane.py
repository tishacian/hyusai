"""Canonical /control-plane endpoints — Steering Wheel CRUD + simulate.

ControlPolicy + AdaptivePolicy are mounted here as a single concept.
`POST /simulate` returns the projected impact of a lever change without
persisting anything (used by the Steering cockpit's <300ms preview).
"""
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.capability import Capability
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chat_execution_policy import (
    migration_059_control_policy_id,
)
from app.services.capability_access import resolve_capability_read
from app.services.iam.decision_plane import (
    ActionResolution,
    emit_shadow_diff_summary,
    enforce_action,
    resolve_action,
)
from app.services.membrane.spec import MembraneSpec
from app.services.system_access import resolve_system_read

router = APIRouter()


def _policy_resource_attrs(
    *,
    policy_id: str | None,
    scope: str | None,
    target_id: str | None,
) -> dict[str, str | None]:
    normalized = "portfolio" if scope in {None, "workspace", "portfolio"} else scope
    attrs: dict[str, str | None] = {
        "policy_id": policy_id,
        "scope": normalized,
        "target_id": target_id,
    }
    if normalized in {"system", "capability"}:
        attrs[f"{normalized}_id"] = target_id
    return attrs


def _enforce_policy_action(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    resource_kind: str,
    action: str,
    policy_id: str | None = None,
    scope: str | None = None,
    target_id: str | None = None,
) -> None:
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action=action,
        legacy_allowed=True,
        resource_attrs=_policy_resource_attrs(
            policy_id=policy_id,
            scope=scope,
            target_id=target_id,
        ),
    )


def _readable_policy_rows(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    resource_kind: str,
    rows: list[ControlPolicy] | list[AdaptivePolicy],
) -> list[ControlPolicy] | list[AdaptivePolicy]:
    """Compose row-level policy authorization with target visibility.

    Policy attributes are resolved for every row so a future candidate rule can
    grant or deny one policy without a coarse, attribute-free pre-check masking
    that decision. Shadow differences are emitted once as a bounded summary.
    """

    visible: list[ControlPolicy] | list[AdaptivePolicy] = []
    resolutions: list[tuple[str, ActionResolution]] = []
    for row in rows:
        resolution = resolve_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind=resource_kind,
            action="read",
            legacy_allowed=True,
            resource_attrs=_policy_resource_attrs(
                policy_id=row.id,
                scope=row.scope,
                target_id=row.target_id,
            ),
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((row.id, resolution))
        if resolution.effective_allowed and _policy_target_is_readable(
            db,
            workspace=workspace,
            user=user,
            scope=row.scope,
            target_id=row.target_id,
        ):
            visible.append(row)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind=resource_kind,
        action="read",
        resolutions=resolutions,
    )
    return visible


def _policy_target_is_readable(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    scope: str | None,
    target_id: str | None,
) -> bool:
    normalized = "portfolio" if scope in {None, "workspace", "portfolio"} else scope
    if normalized == "portfolio":
        return target_id in {None, ""}
    if not target_id:
        return False
    if normalized == "system":
        system = (
            db.query(System)
            .filter(System.id == target_id, System.workspace_id == workspace.id)
            .one_or_none()
        )
        return bool(
            system is not None
            and resolve_system_read(
                db,
                system=system,
                user=user,
                workspace=workspace,
                audit_shadow_diff=False,
                audit_shadow_evidence=False,
            ).effective_allowed
        )
    if normalized == "capability":
        capability = (
            db.query(Capability)
            .filter(
                Capability.id == target_id,
                (
                    (Capability.workspace_id == workspace.id)
                    | (Capability.workspace_id.is_(None))
                ),
            )
            .one_or_none()
        )
        return bool(
            capability is not None
            and resolve_capability_read(
                db,
                capability=capability,
                user=user,
                workspace=workspace,
                audit_shadow_diff=False,
                audit_shadow_evidence=False,
            ).effective_allowed
        )
    return False


def _require_policy_target(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    scope: str | None,
    target_id: str | None,
) -> None:
    if not _policy_target_is_readable(
        db,
        workspace=workspace,
        user=user,
        scope=scope,
        target_id=target_id,
    ):
        raise HTTPException(status_code=404, detail="Policy target not found")


def _require_managed_policy_admin(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    policy: ControlPolicy,
) -> None:
    """Reserve the migration-owned production membrane to administrators."""

    is_managed = migration_059_control_policy_id(workspace) == policy.id
    if not is_managed or getattr(user, "role", None) == "admin":
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
            detail="Admin/owner access required for the production Agentic policy",
        )


# ---- Control policies ----
class ControlPolicyBody(BaseModel):
    name: str = "default"
    scope: Literal["portfolio", "capability", "system"] = "portfolio"
    target_id: Optional[str] = None
    max_cost_per_decision: Optional[float] = None
    max_latency_ms: Optional[float] = None
    mandatory_hitl_if_confidence_below: Optional[float] = None
    allowed_models: List[str] = []
    allowed_skills: List[str] = []
    extra: Dict[str, Any] = {}

    @field_validator("extra")
    @classmethod
    def _validate_membrane_spec(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise ``extra["membrane_spec"]`` through the typed MembraneSpec.

        ``extra`` still passes through free-form; only the reserved
        ``membrane_spec`` key is parsed/canonicalised so a malformed facet is
        rejected at the API boundary instead of silently mis-enforcing. Absent
        key → untouched (read-through path).
        """
        if not isinstance(value, dict):
            return value
        raw = value.get("membrane_spec")
        if raw is None:
            return value
        if not isinstance(raw, dict):
            raise ValueError("membrane_spec must be an object")
        value = dict(value)
        value["membrane_spec"] = MembraneSpec.from_dict(raw).to_dict()
        return value

    @model_validator(mode="after")
    def _validate_enforced_membrane_scope(self):
        if self.scope in {"capability", "system"} and not self.target_id:
            raise ValueError("target_id is required for capability or system scope")
        if self.scope == "portfolio" and self.target_id:
            raise ValueError("target_id must be absent for portfolio scope")
        raw = self.extra.get("membrane_spec") if isinstance(self.extra, dict) else None
        if not isinstance(raw, dict):
            return self
        spec = MembraneSpec.from_dict(raw)
        if spec.enforcement_active and (self.scope != "system" or not self.target_id):
            raise ValueError(
                "an enforced membrane_spec v2 must be bound to a concrete system target_id"
            )
        return self


def _serialize_cp(p: ControlPolicy) -> Dict[str, Any]:
    payload = {
        "id": p.id,
        "name": p.name,
        "scope": p.scope,
        "target_id": p.target_id,
        "max_cost_per_decision": p.max_cost_per_decision,
        "max_latency_ms": p.max_latency_ms,
        "mandatory_hitl_if_confidence_below": p.mandatory_hitl_if_confidence_below,
        "allowed_models": p.allowed_models or [],
        "allowed_skills": p.allowed_skills or [],
        "extra": p.extra or {},
    }
    try:
        from app.services.membrane.spec import resolve_membrane_spec

        spec = resolve_membrane_spec(control=p)
        payload["membrane"] = {
            "version": spec.version,
            "enforcement_mode": spec.effective_mode.value,
            "authoritative": spec.authoritative,
            "facet_states": spec.facet_states(),
        }
    except Exception:  # noqa: BLE001 - existing policy rows remain readable.
        payload["membrane"] = {
            "version": None,
            "enforcement_mode": "compat",
            "authoritative": False,
            "facet_states": {},
        }
    return payload


@router.get("/policies")
async def list_policies(
    scope: Optional[str] = None,
    target_id: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    q = db.query(ControlPolicy).filter(ControlPolicy.workspace_id == workspace.id)
    if scope:
        q = q.filter(ControlPolicy.scope == scope)
    if target_id:
        q = q.filter(ControlPolicy.target_id == target_id)
    rows = _readable_policy_rows(
        db,
        workspace=workspace,
        user=user,
        resource_kind="control_policy",
        rows=q.all(),
    )
    return {"policies": [_serialize_cp(p) for p in rows]}


@router.post("/policies")
async def create_policy(
    body: ControlPolicyBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _enforce_policy_action(
        db,
        workspace=workspace,
        user=user,
        resource_kind="control_policy",
        action="admin",
        scope=body.scope,
        target_id=body.target_id,
    )
    _require_policy_target(
        db,
        workspace=workspace,
        user=user,
        scope=body.scope,
        target_id=body.target_id,
    )
    p = ControlPolicy(id=str(uuid4()), workspace_id=workspace.id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serialize_cp(p)


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    body: ControlPolicyBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    p = (
        db.query(ControlPolicy)
        .filter(ControlPolicy.id == policy_id, ControlPolicy.workspace_id == workspace.id)
        .first()
    )
    if not p:
        raise HTTPException(404, "Policy not found")
    _require_managed_policy_admin(
        db,
        user=user,
        workspace=workspace,
        policy=p,
    )
    _require_policy_target(
        db,
        workspace=workspace,
        user=user,
        scope=p.scope,
        target_id=p.target_id,
    )
    _enforce_policy_action(
        db,
        workspace=workspace,
        user=user,
        resource_kind="control_policy",
        action="admin",
        policy_id=p.id,
        scope=p.scope,
        target_id=p.target_id,
    )
    changes = body.model_dump(exclude_unset=True)
    next_scope = changes.get("scope", p.scope)
    next_target_id = changes.get("target_id", p.target_id)
    _require_policy_target(
        db,
        workspace=workspace,
        user=user,
        scope=next_scope,
        target_id=next_target_id,
    )
    _enforce_policy_action(
        db,
        workspace=workspace,
        user=user,
        resource_kind="control_policy",
        action="admin",
        policy_id=p.id,
        scope=next_scope,
        target_id=next_target_id,
    )
    for k, v in changes.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _serialize_cp(p)


# ---- Adaptive policies ----
class AdaptivePolicyBody(BaseModel):
    name: str = "default"
    enabled: bool = False
    adaptation_level: str = "moderate"
    scope: Literal["portfolio", "capability", "system"] = "portfolio"
    target_id: Optional[str] = None
    triggers: Dict[str, Any] = {}
    allowed_actions: List[str] = []
    constraints: Dict[str, Any] = {}

    @model_validator(mode="after")
    def _validate_target(self):
        if self.scope in {"capability", "system"} and not self.target_id:
            raise ValueError("target_id is required for capability or system scope")
        if self.scope == "portfolio" and self.target_id:
            raise ValueError("target_id must be absent for portfolio scope")
        return self


class AdaptivePolicyPatch(BaseModel):
    """Partial update — every field optional."""

    name: Optional[str] = None
    enabled: Optional[bool] = None
    adaptation_level: Optional[str] = None
    scope: Optional[Literal["portfolio", "capability", "system"]] = None
    target_id: Optional[str] = None
    triggers: Optional[Dict[str, Any]] = None
    allowed_actions: Optional[List[str]] = None
    constraints: Optional[Dict[str, Any]] = None


class AdaptiveToggleBody(BaseModel):
    enabled: Optional[bool] = None


def _serialize_ap(p: AdaptivePolicy) -> Dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "enabled": bool(p.enabled),
        "adaptation_level": p.adaptation_level,
        "scope": p.scope,
        "target_id": p.target_id,
        "triggers": p.triggers or {},
        "allowed_actions": p.allowed_actions or [],
        "constraints": p.constraints or {},
    }


@router.get("/adaptive")
async def list_adaptive(
    scope: Optional[str] = None,
    target_id: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    q = db.query(AdaptivePolicy).filter(AdaptivePolicy.workspace_id == workspace.id)
    if scope:
        q = q.filter(AdaptivePolicy.scope == scope)
    if target_id:
        q = q.filter(AdaptivePolicy.target_id == target_id)
    rows = _readable_policy_rows(
        db,
        workspace=workspace,
        user=user,
        resource_kind="adaptive_policy",
        rows=q.all(),
    )
    return {"policies": [_serialize_ap(p) for p in rows]}


@router.post("/adaptive")
async def create_adaptive(
    body: AdaptivePolicyBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _enforce_policy_action(
        db,
        workspace=workspace,
        user=user,
        resource_kind="adaptive_policy",
        action="admin",
        scope=body.scope,
        target_id=body.target_id,
    )
    _require_policy_target(
        db,
        workspace=workspace,
        user=user,
        scope=body.scope,
        target_id=body.target_id,
    )
    p = AdaptivePolicy(id=str(uuid4()), workspace_id=workspace.id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serialize_ap(p)


def _find_adaptive(db: DBSession, workspace_id: str, policy_id: str) -> AdaptivePolicy:
    p = (
        db.query(AdaptivePolicy)
        .filter(AdaptivePolicy.id == policy_id, AdaptivePolicy.workspace_id == workspace_id)
        .first()
    )
    if not p:
        raise HTTPException(404, "Adaptive policy not found")
    return p


@router.patch("/adaptive/{policy_id}")
async def update_adaptive(
    policy_id: str,
    body: AdaptivePolicyPatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    p = _find_adaptive(db, workspace.id, policy_id)
    _require_policy_target(
        db,
        workspace=workspace,
        user=user,
        scope=p.scope,
        target_id=p.target_id,
    )
    _enforce_policy_action(
        db,
        workspace=workspace,
        user=user,
        resource_kind="adaptive_policy",
        action="admin",
        policy_id=p.id,
        scope=p.scope,
        target_id=p.target_id,
    )
    changes = body.model_dump(exclude_unset=True)
    next_scope = changes.get("scope", p.scope)
    next_target_id = changes.get("target_id", p.target_id)
    _require_policy_target(
        db,
        workspace=workspace,
        user=user,
        scope=next_scope,
        target_id=next_target_id,
    )
    _enforce_policy_action(
        db,
        workspace=workspace,
        user=user,
        resource_kind="adaptive_policy",
        action="admin",
        policy_id=p.id,
        scope=next_scope,
        target_id=next_target_id,
    )
    for k, v in changes.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _serialize_ap(p)


@router.post("/adaptive/{policy_id}/toggle")
async def toggle_adaptive(
    policy_id: str,
    body: Optional[AdaptiveToggleBody] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Flip the ``enabled`` flag. Explicit value wins, otherwise invert."""
    p = _find_adaptive(db, workspace.id, policy_id)
    _require_policy_target(
        db,
        workspace=workspace,
        user=user,
        scope=p.scope,
        target_id=p.target_id,
    )
    _enforce_policy_action(
        db,
        workspace=workspace,
        user=user,
        resource_kind="adaptive_policy",
        action="admin",
        policy_id=p.id,
        scope=p.scope,
        target_id=p.target_id,
    )
    target = body.enabled if (body and body.enabled is not None) else (not bool(p.enabled))
    p.enabled = bool(target)
    db.commit()
    db.refresh(p)
    return _serialize_ap(p)


@router.delete("/adaptive/{policy_id}", status_code=204)
async def delete_adaptive(
    policy_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    p = _find_adaptive(db, workspace.id, policy_id)
    _require_policy_target(
        db,
        workspace=workspace,
        user=user,
        scope=p.scope,
        target_id=p.target_id,
    )
    _enforce_policy_action(
        db,
        workspace=workspace,
        user=user,
        resource_kind="adaptive_policy",
        action="admin",
        policy_id=p.id,
        scope=p.scope,
        target_id=p.target_id,
    )
    db.delete(p)
    db.commit()
    return None


# ---- Simulate ----
class SimulateBody(BaseModel):
    scope: Literal["portfolio", "capability", "system"] = "capability"
    target_id: Optional[str] = None
    levers: Dict[str, float] = {}

    @model_validator(mode="after")
    def _require_system_target(self):
        if self.scope in {"capability", "system"} and not self.target_id:
            raise ValueError("target_id is required for capability or system scope")
        if self.scope == "portfolio" and self.target_id:
            raise ValueError("target_id must be absent for portfolio scope")
        return self


@router.post("/simulate")
async def simulate(
    body: SimulateBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="value_scenario",
        action="read",
        legacy_allowed=True,
        resource_attrs={"scope": body.scope, "target_id": body.target_id},
    )
    return {
        "kind": "simulation",
        "state": "not_configured",
        "measured": False,
        "scope": body.scope,
        "target_id": body.target_id,
        "model": None,
        "assumptions": None,
        "provenance": None,
        "confidence": None,
        "base": None,
        "projected": None,
        "reason": "authoritative_value_loop_required",
        "replacement": "/systems/{system_id}/value-loop",
    }
