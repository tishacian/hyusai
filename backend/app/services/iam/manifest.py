"""Default IAM capability manifests.

The first manifest covers Expert Knowledge Capture. It is intentionally
data-driven so later capability manifests can be registered without adding
endpoint-specific authorization branches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_OWNER,
    WORKSPACE_REVIEWER,
    WORKSPACE_VIEWER,
)


@dataclass(frozen=True)
class PermissionRule:
    resource_kind: str
    action: str
    roles: tuple[str, ...]
    conditions: tuple[str, ...] = ()
    policy_id: Optional[str] = None

    def resolved_policy_id(self, manifest_id: str) -> str:
        return self.policy_id or f"{manifest_id}:{self.resource_kind}.{self.action}"


@dataclass(frozen=True)
class CapabilityIAMManifest:
    capability_id: str
    permissions: tuple[PermissionRule, ...] = field(default_factory=tuple)


ALL_CAPTURE_ROLES = (
    WORKSPACE_VIEWER,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
)
REVIEW_ROLES = (WORKSPACE_REVIEWER, WORKSPACE_ADMIN, WORKSPACE_OWNER)
ADMIN_ROLES = (WORKSPACE_ADMIN, WORKSPACE_OWNER)
CONTRIBUTOR_OR_ADMIN = (WORKSPACE_CONTRIBUTOR, WORKSPACE_ADMIN, WORKSPACE_OWNER)
SECURE_DEPOSIT_ALL_MEMBERS = (
    WORKSPACE_VIEWER,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
)


CAPTURE_MANIFEST = CapabilityIAMManifest(
    capability_id="expert_knowledge_capture",
    permissions=(
        PermissionRule("voice_runtime", "read", ALL_CAPTURE_ROLES),
        PermissionRule("capture_session", "create", CONTRIBUTOR_OR_ADMIN),
        PermissionRule("capture_session", "read", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("capture_session", "read", REVIEW_ROLES),
        PermissionRule("capture_session", "update", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("capture_session", "update", ADMIN_ROLES),
        PermissionRule("capture_session", "execute", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("capture_session", "execute", ADMIN_ROLES),
        PermissionRule("knowledge_proposal", "read", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("knowledge_proposal", "read", REVIEW_ROLES),
        PermissionRule("knowledge_proposal", "submit_review", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("knowledge_proposal", "submit_review", ADMIN_ROLES),
        PermissionRule("knowledge_proposal", "review_decide", REVIEW_ROLES),
        PermissionRule("knowledge_proposal", "trigger_ingestion", REVIEW_ROLES, ("second_eye_ingestion",)),
        PermissionRule("workspace", "manage_members", ADMIN_ROLES),
        PermissionRule("policy", "manage_policies", ADMIN_ROLES),
        PermissionRule("audit_log", "read", REVIEW_ROLES),
    ),
)

SECURE_DEPOSIT_MANIFEST = CapabilityIAMManifest(
    capability_id="secure_deposit",
    permissions=(
        PermissionRule("deposit_link", "create", SECURE_DEPOSIT_ALL_MEMBERS),
        PermissionRule("deposit_link", "read", SECURE_DEPOSIT_ALL_MEMBERS, ("owner_match",)),
        PermissionRule("deposit_link", "read_all", REVIEW_ROLES),
        PermissionRule("deposit_link", "update", SECURE_DEPOSIT_ALL_MEMBERS, ("owner_match",)),
        PermissionRule("deposit_link", "update", ADMIN_ROLES),
        PermissionRule("deposit_link", "revoke", SECURE_DEPOSIT_ALL_MEMBERS, ("owner_match",)),
        PermissionRule("deposit_link", "revoke", ADMIN_ROLES),
        PermissionRule("deposit_file", "read", SECURE_DEPOSIT_ALL_MEMBERS, ("owner_match",)),
        PermissionRule("deposit_file", "read_all", REVIEW_ROLES),
        PermissionRule("deposit_file", "promote", REVIEW_ROLES),
        PermissionRule("deposit_file", "download_archive", REVIEW_ROLES),
        PermissionRule("deposit_config", "manage", ADMIN_ROLES),
    ),
)

VOICE2VOICE_MANIFEST = CapabilityIAMManifest(
    capability_id="voice2voice_interaction",
    permissions=(
        PermissionRule("voice_runtime", "read", ALL_CAPTURE_ROLES),
    ),
)

AGENTIUM_ACTIONS_MANIFEST = CapabilityIAMManifest(
    capability_id="agentium_actions",
    permissions=(
        PermissionRule("action", "read", ALL_CAPTURE_ROLES),
        PermissionRule("action", "resolve", ALL_CAPTURE_ROLES),
        PermissionRule("action", "execute", CONTRIBUTOR_OR_ADMIN + (WORKSPACE_REVIEWER,)),
        PermissionRule("action", "manage", ADMIN_ROLES),
    ),
)


MANIFESTS: Dict[str, CapabilityIAMManifest] = {
    CAPTURE_MANIFEST.capability_id: CAPTURE_MANIFEST,
    SECURE_DEPOSIT_MANIFEST.capability_id: SECURE_DEPOSIT_MANIFEST,
    VOICE2VOICE_MANIFEST.capability_id: VOICE2VOICE_MANIFEST,
    AGENTIUM_ACTIONS_MANIFEST.capability_id: AGENTIUM_ACTIONS_MANIFEST,
}


def get_manifest(capability_id: str = "expert_knowledge_capture") -> CapabilityIAMManifest:
    return MANIFESTS.get(capability_id, CAPTURE_MANIFEST)


def iter_permissions(capability_id: str = "expert_knowledge_capture") -> Iterable[PermissionRule]:
    return get_manifest(capability_id).permissions
