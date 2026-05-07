"""Transverse workspace authorization engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.iam.roles import (
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    normalize_role_template,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.iam.config_service import effective_role_flags, load_iam_config
from app.services.iam.manifest import PermissionRule, get_manifest


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    policy_id: str


class AuthorizationEngine:
    """Evaluate RBAC + ABAC rules for the current workspace."""

    def evaluate(
        self,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        resource_kind: str,
        action: str,
        resource_attrs: Optional[Dict[str, Any]] = None,
        membership: Optional[WorkspaceMember] = None,
        audit_prefix: str = "iam",
        audit_denials: bool = True,
    ) -> Decision:
        attrs = resource_attrs or {}
        membership = membership or self._membership(db, user.id, workspace.id)
        if not membership:
            decision = Decision(False, "WORKSPACE_ACCESS_DENIED", "workspace.membership")
            if audit_denials:
                self._audit_deny(db, user, workspace, resource_kind, action, attrs, decision, audit_prefix)
            return decision

        config = load_iam_config(db, workspace.id, create=False)
        flags = effective_role_flags(config)
        role_template = normalize_role_template(
            getattr(membership, "role_template", None),
            getattr(membership, "role", None),
        )
        role_templates = self._effective_roles(role_template, flags)
        manifest = get_manifest(str(attrs.get("capability") or "expert_knowledge_capture"))
        candidates = [
            rule
            for rule in manifest.permissions
            if rule.resource_kind == resource_kind and rule.action == action and set(rule.roles).intersection(role_templates)
        ]
        for rule in candidates:
            if self._conditions_pass(rule, user=user, membership=membership, attrs=attrs, flags=flags):
                return Decision(True, "allowed", self._policy_id(manifest.capability_id, rule, role_template))

        reason = "WORKSPACE_PERMISSION_DENIED" if candidates else "IAM_DENY_BY_DEFAULT"
        policy_id = f"{manifest.capability_id}:{resource_kind}.{action}:deny"
        decision = Decision(False, reason, policy_id)
        if audit_denials:
            self._audit_deny(db, user, workspace, resource_kind, action, attrs, decision, audit_prefix)
        return decision

    def _membership(self, db: DBSession, user_id: str, workspace_id: str) -> Optional[WorkspaceMember]:
        return (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == workspace_id)
            .first()
        )

    def _effective_roles(self, role_template: str, flags: Dict[str, Any]) -> set[str]:
        roles = {role_template}
        if role_template == WORKSPACE_REVIEWER and flags.get("reviewers_inherit_contributor"):
            roles.add(WORKSPACE_CONTRIBUTOR)
        return roles

    def _conditions_pass(
        self,
        rule: PermissionRule,
        *,
        user: User,
        membership: WorkspaceMember,
        attrs: Dict[str, Any],
        flags: Dict[str, Any],
    ) -> bool:
        for condition in rule.conditions:
            if condition == "owner_match":
                owner = attrs.get("owner_user_id") or attrs.get("created_by_user_id")
                if not owner or str(owner) != user.id:
                    return False
            elif condition == "label_intersect":
                labels = set(getattr(membership, "custom_labels", None) or [])
                required = set(attrs.get("labels") or [])
                domain = attrs.get("domain")
                if domain:
                    required.add(f"domain:{domain}")
                if required and not labels.intersection(required):
                    return False
            elif condition == "second_eye_ingestion":
                if not flags.get("require_second_eye_for_ingestion", True):
                    continue
                owner = attrs.get("owner_user_id") or attrs.get("created_by_user_id")
                if owner and str(owner) == user.id:
                    return False
            elif condition.startswith("workspace_flag:"):
                flag_name = condition.split(":", 1)[1]
                if not flags.get(flag_name):
                    return False
            else:
                return False
        return True

    def _policy_id(self, manifest_id: str, rule: PermissionRule, role_template: str) -> str:
        suffix = ":".join(rule.conditions) if rule.conditions else "rbac"
        return f"{rule.resolved_policy_id(manifest_id)}:{role_template}:{suffix}"

    def _audit_deny(
        self,
        db: DBSession,
        user: User,
        workspace: Workspace,
        resource_kind: str,
        action: str,
        attrs: Dict[str, Any],
        decision: Decision,
        audit_prefix: str,
    ) -> None:
        event_type = "kc.iam.deny" if audit_prefix == "kc" else "iam.deny"
        actor = user.email or user.username or user.id
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type=event_type,
            actor=actor,
            severity="warning",
            details={
                "subject": {"user_id": user.id, "email": user.email, "username": user.username},
                "resource": {"kind": resource_kind, **attrs},
                "action": action,
                "policy_id": decision.policy_id,
                "outcome": "deny",
                "reason": decision.reason,
            },
        )

