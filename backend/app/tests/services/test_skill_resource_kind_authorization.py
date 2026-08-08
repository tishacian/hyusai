"""`skill` as an authorization boundary, and the cost of declaring it.

The Skill catalog was governed only through `skill_invocation`, which is the
record of a run, not the definition. Workspace-scoped authoring needs a
resource kind of its own. Declaring one mutates the manifest registry and
therefore `candidate_config_sha256`, so the digest move is pinned here rather
than discovered by a workspace failing attestation in production.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.iam import decision_plane as plane
from app.services.iam.decision_plane import (
    build_authorization_v2_backfill,
    candidate_config_sha256,
    resolve_action,
    resolve_mode,
)
from app.services.iam.manifest import ADMIN_ROLES, ALL_CAPTURE_ROLES, get_manifest


def _subject(db_session, *, role_template: str):
    workspace = Workspace(id="ws-skill-iam", slug="skill-iam", name="Skill IAM")
    user = User(id="user-skill-iam", username="skill@test", email="skill@test")
    member = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="member",
        role_template=role_template,
    )
    db_session.add_all([workspace, user, member])
    db_session.commit()
    return workspace, user


def test_skill_read_and_admin_are_declared_on_the_object_actions_manifest():
    rules = {
        (rule.resource_kind, rule.action): rule
        for rule in get_manifest("agentium_object_actions", strict=True).permissions
    }

    assert rules[("skill", "read")].roles == ALL_CAPTURE_ROLES
    assert rules[("skill", "admin")].roles == ADMIN_ROLES
    # One admin gate, deliberately: authoring, schema edition and runtime
    # binding must not become separately weaker boundaries.
    assert {action for kind, action in rules if kind == "skill"} == {"read", "admin"}
    assert not rules[("skill", "read")].conditions
    assert not rules[("skill", "admin")].conditions


@pytest.mark.parametrize(
    ("role_template", "action", "allowed"),
    [
        ("workspace_viewer", "read", True),
        ("workspace_viewer", "admin", False),
        ("workspace_contributor", "admin", False),
        ("workspace_reviewer", "admin", False),
        ("workspace_admin", "admin", True),
    ],
)
def test_the_catalog_is_readable_by_members_and_writable_by_admins(
    db_session, role_template, action, allowed
):
    workspace, user = _subject(db_session, role_template=role_template)

    resolution = resolve_action(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="skill",
        action=action,
        legacy_allowed=True,
    )

    assert resolution.candidate_allowed is allowed


def test_a_workspace_without_a_v2_policy_keeps_the_new_kind_in_compat(db_session):
    """Declaring a resource kind must not gate anything on its own."""

    workspace, user = _subject(db_session, role_template="workspace_viewer")

    assert resolve_mode(None, resource_kind="skill", action="admin").value == "compat"

    resolution = resolve_action(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="skill",
        action="admin",
        legacy_allowed=True,
    )
    assert resolution.mode == "compat"
    assert resolution.effective_allowed is True


def test_a_wildcard_enforce_cannot_promote_the_new_kind_by_inheritance(db_session):
    config = WorkspaceIAMConfig(
        workspace_id="ws-skill-iam",
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"*.*": "enforce", "skill.*": "enforce"},
            }
        },
    )

    assert resolve_mode(config, resource_kind="skill", action="admin").value == "shadow"


def test_the_rollout_document_governs_both_skill_actions():
    """The manifest rule alone only makes the candidate evaluable. An action the
    rollout document does not own can never leave compat, because the promotion
    script refuses to promote outside the canonical key set."""

    modes = build_authorization_v2_backfill(mode="shadow")["modes"]

    assert modes["skill.read"] == "shadow"
    assert modes["skill.admin"] == "shadow"


def test_governing_the_skill_actions_leaves_the_candidate_digest_alone():
    """Stored enforcement attestations are bound to the candidate digest.

    Declaring the resource kind moved it once, deliberately (see below). Putting
    the same two actions under rollout control must not move it a second time:
    ``candidate_config_sha256`` excludes ``modes`` precisely so that promoting an
    action does not invalidate the receipt that authorised the promotion.
    """

    before = candidate_config_sha256(None)
    governed = build_authorization_v2_backfill(mode="enforce")

    assert governed["modes"]["skill.admin"] == "enforce"
    assert candidate_config_sha256(None) == before


def test_declaring_the_kind_moves_the_candidate_digest_once(monkeypatch):
    """Every stored enforce attestation is bound to the pre-change digest.

    The move is the point of the change, but it must come from the manifest
    registry alone: the memoization key stays `{policy_version, default_mode,
    role_flags}` so an aggregate still hashes once per distinct policy.
    """

    after = candidate_config_sha256(None)

    without_skill = {}
    for manifest_id, manifest in plane.MANIFESTS.items():
        kept = tuple(rule for rule in manifest.permissions if rule.resource_kind != "skill")
        without_skill[manifest_id] = (
            manifest if kept == manifest.permissions else dataclasses.replace(manifest, permissions=kept)
        )
    monkeypatch.setattr(plane, "MANIFESTS", without_skill)
    plane._candidate_config_sha256.cache_clear()
    before = candidate_config_sha256(None)
    monkeypatch.undo()
    plane._candidate_config_sha256.cache_clear()

    assert before != after
    assert candidate_config_sha256(None) == after

    baseline = plane._candidate_config_sha256.cache_info()
    for _ in range(5):
        candidate_config_sha256(None)
    hits = plane._candidate_config_sha256.cache_info().hits - baseline.hits
    assert hits == 5
