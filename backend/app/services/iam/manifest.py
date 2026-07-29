"""Default IAM capability manifests.

The first manifest covers Expert Knowledge Capture. It is intentionally
data-driven so later capability manifests can be registered without adding
endpoint-specific authorization branches.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

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
    policy_id: str | None = None

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
# These are the legacy Knowledge Capture roles. Reviewer removal must be
# introduced as an authorization-v2 candidate and compared in shadow before
# it can become authoritative; changing this manifest would bypass rollout and
# break already-authorized workspaces such as Andritz even with v2 flags off.
CAPTURE_OPERATOR_OR_ADMIN = (
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
)
CAPTURE_OWNER_SCOPED_ROLES = (WORKSPACE_CONTRIBUTOR, WORKSPACE_REVIEWER)
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
        PermissionRule("capture_session", "create", CAPTURE_OPERATOR_OR_ADMIN),
        PermissionRule("capture_session", "read", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("capture_session", "read", REVIEW_ROLES),
        PermissionRule("capture_session", "update", CAPTURE_OWNER_SCOPED_ROLES, ("owner_match",)),
        PermissionRule("capture_session", "update", ADMIN_ROLES),
        PermissionRule("capture_session", "execute", CAPTURE_OWNER_SCOPED_ROLES, ("owner_match",)),
        PermissionRule("capture_session", "execute", ADMIN_ROLES),
        PermissionRule("knowledge_proposal", "read", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("knowledge_proposal", "read", REVIEW_ROLES),
        PermissionRule("knowledge_proposal", "submit_review", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("knowledge_proposal", "submit_review", ADMIN_ROLES),
        PermissionRule("knowledge_proposal", "review_decide", REVIEW_ROLES),
        PermissionRule("knowledge_proposal", "chat_correct", REVIEW_ROLES),
        PermissionRule("knowledge_proposal", "trigger_ingestion", REVIEW_ROLES, ("second_eye_ingestion",)),
        PermissionRule("action", "execute", CAPTURE_OPERATOR_OR_ADMIN),
        PermissionRule("workspace", "manage_members", ADMIN_ROLES),
        PermissionRule("policy", "manage_policies", ADMIN_ROLES),
        PermissionRule("audit_log", "read", REVIEW_ROLES),
    ),
)


# Candidate contract for the reviewer/contributor split. The legacy manifest
# above deliberately remains unchanged until each workspace has compared this
# policy in shadow and explicitly opted into enforce.
EXPERT_KNOWLEDGE_CAPTURE_V2_MANIFEST = CapabilityIAMManifest(
    capability_id="expert_knowledge_capture_v2",
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
        PermissionRule("knowledge_proposal", "chat_correct", REVIEW_ROLES),
        PermissionRule("knowledge_proposal", "trigger_ingestion", REVIEW_ROLES, ("second_eye_ingestion",)),
        PermissionRule("action", "execute", CONTRIBUTOR_OR_ADMIN),
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
        PermissionRule("deposit_file", "operate", REVIEW_ROLES),
        PermissionRule("deposit_config", "manage", ADMIN_ROLES),
    ),
)

VOICE2VOICE_MANIFEST = CapabilityIAMManifest(
    capability_id="voice2voice_interaction",
    permissions=(
        PermissionRule("voice_runtime", "read", ALL_CAPTURE_ROLES),
        PermissionRule("action", "execute", CAPTURE_OPERATOR_OR_ADMIN),
    ),
)

AYA_VOICE_COMMAND_MANIFEST = CapabilityIAMManifest(
    capability_id="aya_voice_command",
    permissions=(
        PermissionRule("action", "execute", CAPTURE_OPERATOR_OR_ADMIN),
    ),
)

OCTAVE_VOICE_COMMAND_MANIFEST = CapabilityIAMManifest(
    capability_id="octave_voice_command",
    permissions=(
        PermissionRule("action", "execute", CAPTURE_OPERATOR_OR_ADMIN),
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

TRANSLATION_SUITE_MANIFEST = CapabilityIAMManifest(
    capability_id="showcase_translation_suite",
    permissions=(
        PermissionRule("translation_batch", "read", ALL_CAPTURE_ROLES),
        PermissionRule("translation_batch", "create", CONTRIBUTOR_OR_ADMIN),
        PermissionRule("translation_batch", "execute", CONTRIBUTOR_OR_ADMIN),
        PermissionRule("translation_batch", "replay", CONTRIBUTOR_OR_ADMIN),
        PermissionRule("translation_batch", "approve", REVIEW_ROLES),
        PermissionRule("translation_memory", "read", ALL_CAPTURE_ROLES),
        PermissionRule("agent_identity", "read", ALL_CAPTURE_ROLES),
        PermissionRule("agent_identity", "manage", ADMIN_ROLES),
        PermissionRule("model_policy", "read", REVIEW_ROLES),
        PermissionRule("model_policy", "manage", ADMIN_ROLES),
        PermissionRule("delivery_manifest", "read", REVIEW_ROLES),
        PermissionRule("delivery_manifest", "release", REVIEW_ROLES),
        PermissionRule("audit_log", "read", REVIEW_ROLES),
        PermissionRule("audit_log", "export", REVIEW_ROLES),
    ),
)

SYSTEM_ENGINE_MANIFEST = CapabilityIAMManifest(
    capability_id="system_engine",
    permissions=(
        PermissionRule("system", "read", ALL_CAPTURE_ROLES),
        # Reviewer contributor-inheritance is a Knowledge Capture policy. It
        # must not silently alter the pre-v2 System Engine contract while the
        # granular action plane is still in compat/shadow rollout.
        PermissionRule(
            "system",
            "engine.run",
            CONTRIBUTOR_OR_ADMIN + (WORKSPACE_REVIEWER,),
        ),
    ),
)


# Canonical object/action vocabulary used by the Lot 7 decision plane.  The
# legacy capability manifests above stay available while workspaces compare
# both decisions in shadow mode.
AGENTIUM_OBJECT_ACTIONS_MANIFEST = CapabilityIAMManifest(
    capability_id="agentium_object_actions",
    permissions=(
        PermissionRule("capability", "read", ALL_CAPTURE_ROLES),
        PermissionRule("capability", "admin", ADMIN_ROLES),
        PermissionRule("system", "read", ALL_CAPTURE_ROLES),
        PermissionRule(
            "system",
            "engine.run",
            CONTRIBUTOR_OR_ADMIN + (WORKSPACE_REVIEWER,),
        ),
        PermissionRule("system", "admin", ADMIN_ROLES),
        PermissionRule("run", "read", (WORKSPACE_CONTRIBUTOR,), ("owner_match",)),
        PermissionRule("run", "read", REVIEW_ROLES),
        PermissionRule("run", "approve", REVIEW_ROLES),
        PermissionRule("run", "admin", ADMIN_ROLES),
        PermissionRule(
            "skill_invocation",
            "read",
            (WORKSPACE_CONTRIBUTOR,),
            ("owner_match",),
        ),
        PermissionRule("skill_invocation", "read", REVIEW_ROLES),
        PermissionRule("skill_invocation", "admin", ADMIN_ROLES),
        PermissionRule("mail_draft", "mail.send", ADMIN_ROLES),
        PermissionRule(
            "decision",
            "read",
            (WORKSPACE_CONTRIBUTOR,),
            ("owner_match",),
        ),
        PermissionRule("decision", "read", REVIEW_ROLES),
        PermissionRule("decision", "approve", REVIEW_ROLES),
        PermissionRule("decision", "admin", ADMIN_ROLES),
        PermissionRule("audit_log", "read", REVIEW_ROLES),
        PermissionRule("control_policy", "read", ALL_CAPTURE_ROLES),
        PermissionRule("control_policy", "admin", ADMIN_ROLES),
        PermissionRule("adaptive_policy", "read", ALL_CAPTURE_ROLES),
        PermissionRule("adaptive_policy", "admin", ADMIN_ROLES),
        PermissionRule("value_scenario", "read", ALL_CAPTURE_ROLES),
        PermissionRule("value_scenario", "create", CONTRIBUTOR_OR_ADMIN),
        PermissionRule("value_scenario", "simulate", CONTRIBUTOR_OR_ADMIN),
        PermissionRule("value_scenario", "approve", REVIEW_ROLES),
        PermissionRule("value_scenario", "act", ADMIN_ROLES),
        PermissionRule(
            "value_scenario",
            "measure",
            CONTRIBUTOR_OR_ADMIN + (WORKSPACE_REVIEWER,),
        ),
        PermissionRule(
            "knowledge_proposal",
            "publish",
            REVIEW_ROLES,
            ("second_eye_ingestion",),
        ),
        PermissionRule("action", "read", ALL_CAPTURE_ROLES),
        PermissionRule(
            "action",
            "execute",
            CONTRIBUTOR_OR_ADMIN + (WORKSPACE_REVIEWER,),
        ),
        PermissionRule("action", "admin", ADMIN_ROLES),
    ),
)


MANIFESTS: dict[str, CapabilityIAMManifest] = {
    CAPTURE_MANIFEST.capability_id: CAPTURE_MANIFEST,
    EXPERT_KNOWLEDGE_CAPTURE_V2_MANIFEST.capability_id: EXPERT_KNOWLEDGE_CAPTURE_V2_MANIFEST,
    SECURE_DEPOSIT_MANIFEST.capability_id: SECURE_DEPOSIT_MANIFEST,
    VOICE2VOICE_MANIFEST.capability_id: VOICE2VOICE_MANIFEST,
    AYA_VOICE_COMMAND_MANIFEST.capability_id: AYA_VOICE_COMMAND_MANIFEST,
    OCTAVE_VOICE_COMMAND_MANIFEST.capability_id: OCTAVE_VOICE_COMMAND_MANIFEST,
    AGENTIUM_ACTIONS_MANIFEST.capability_id: AGENTIUM_ACTIONS_MANIFEST,
    TRANSLATION_SUITE_MANIFEST.capability_id: TRANSLATION_SUITE_MANIFEST,
    SYSTEM_ENGINE_MANIFEST.capability_id: SYSTEM_ENGINE_MANIFEST,
    AGENTIUM_OBJECT_ACTIONS_MANIFEST.capability_id: AGENTIUM_OBJECT_ACTIONS_MANIFEST,
}


def get_manifest(
    capability_id: str = "expert_knowledge_capture",
    *,
    strict: bool = False,
) -> CapabilityIAMManifest:
    manifest = MANIFESTS.get(capability_id)
    if manifest is not None:
        return manifest
    if strict:
        raise KeyError(f"Unknown IAM capability manifest: {capability_id}")
    return CAPTURE_MANIFEST


def iter_permissions(capability_id: str = "expert_knowledge_capture") -> Iterable[PermissionRule]:
    return get_manifest(capability_id).permissions
