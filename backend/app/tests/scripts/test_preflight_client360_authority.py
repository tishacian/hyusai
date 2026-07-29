from __future__ import annotations

from datetime import datetime

import pytest

from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.system import System
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceIAMConfig,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.services.client360_contract import (
    CLIENT360_CAPABILITY_SLUG,
    CLIENT360_SYSTEM_VARIANT,
)
from app.services.iam.app_entitlements import CLIENT360_APP
from scripts.preflight_client360_authority import (
    _parser,
    build_preflight,
    main,
    select_workspaces,
)

REVISION = "a" * 40


def _workspace(
    db_session,
    suffix: str,
    *,
    family: str = "generic",
    active: bool = True,
    deleted: bool = False,
) -> Workspace:
    row = Workspace(
        id=f"ws-c360-preflight-{suffix}",
        slug=f"c360-preflight-{suffix}",
        name=f"Mutable name {suffix}",
        is_active=active,
        deleted_at=datetime.utcnow() if deleted else None,
        settings={"family": family},
    )
    db_session.add(row)
    db_session.flush()
    return row


def _authority(
    db_session,
    workspace: Workspace,
    suffix: str,
    *,
    status: str = "active",
    slug: str = CLIENT360_CAPABILITY_SLUG,
) -> tuple[System, Capability]:
    capability = Capability(
        id=f"cap-c360-preflight-{suffix}",
        workspace_id=workspace.id,
        slug=slug,
        name=f"Capability {suffix}",
        tier="client",
    )
    system = System(
        id=f"sys-c360-preflight-{suffix}",
        workspace_id=workspace.id,
        name=f"System {suffix}",
        objective="Client360 authority preflight",
        capability_id=capability.id,
        status=status,
        settings={"system_type": CLIENT360_SYSTEM_VARIANT},
        flow_definition={"variant": CLIENT360_SYSTEM_VARIANT},
    )
    db_session.add_all([capability, system])
    db_session.flush()
    return system, capability


def _grant(db_session, workspace: Workspace, suffix: str) -> None:
    user = User(
        id=f"user-c360-preflight-{suffix}",
        username=f"c360-preflight-{suffix}",
        email=f"c360-preflight-{suffix}@example.test",
    )
    membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template="workspace_contributor",
    )
    db_session.add_all([user, membership])
    db_session.flush()
    db_session.add(
        WorkspaceMemberAppEntitlement(
            workspace_member_id=membership.id,
            app_key=CLIENT360_APP,
            grant_source="preflight-test",
        )
    )
    db_session.flush()


def test_preflight_selects_family_and_entitled_workspaces_without_slug_or_name(db_session) -> None:
    family = _workspace(db_session, "family", family="andritz")
    entitled = _workspace(db_session, "entitled")
    ignored = _workspace(db_session, "ignored")
    inactive = _workspace(db_session, "inactive", family="andritz", active=False)
    deleted = _workspace(db_session, "deleted", family="andritz", deleted=True)
    _grant(db_session, entitled, "entitled")

    selected, missing = select_workspaces(db_session, family="andritz")

    assert {row.id for row in selected} == {family.id, entitled.id}
    assert ignored.id not in {row.id for row in selected}
    assert inactive.id not in {row.id for row in selected}
    assert deleted.id not in {row.id for row in selected}
    assert missing == []


def test_preflight_is_read_only_and_binds_authority_config_and_runtime(db_session) -> None:
    workspace = _workspace(db_session, "ready", family="andritz")
    system, capability = _authority(db_session, workspace, "ready")
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=7,
        role_flags={},
        capability_overrides={},
    )
    db_session.add(config)
    db_session.flush()
    audits_before = db_session.query(AuditLog).count()

    first = build_preflight(db_session, runtime_revision=REVISION)
    second = build_preflight(db_session, runtime_revision=REVISION)

    assert first["summary"] == {"workspace_count": 1, "ready": 1, "blocked": 0}
    row = first["workspaces"][0]
    assert row["system_id"] == system.id
    assert row["capability_id"] == capability.id
    assert row["iam_config_version"] == 7
    assert row["authority_sha256"] == second["workspaces"][0]["authority_sha256"]
    assert db_session.query(AuditLog).count() == audits_before

    config.version = 8
    db_session.flush()
    drifted = build_preflight(db_session, runtime_revision=REVISION)
    assert drifted["workspaces"][0]["authority_sha256"] != row["authority_sha256"]


def test_preflight_blocks_missing_ambiguous_and_non_exact_runtime(db_session) -> None:
    missing = _workspace(db_session, "missing", family="andritz")
    ambiguous = _workspace(db_session, "ambiguous", family="andritz")
    _authority(db_session, ambiguous, "ambiguous-a")
    second_capability = Capability(
        id="cap-c360-preflight-ambiguous-b",
        workspace_id=ambiguous.id,
        slug="client360-preflight-copy",
        name="Second capability",
        tier="client",
    )
    second_system = System(
        id="sys-c360-preflight-ambiguous-b",
        workspace_id=ambiguous.id,
        name="Second active binding",
        objective="Make the authority ambiguous",
        capability_id=second_capability.id,
        status="active",
        settings={"system_type": CLIENT360_SYSTEM_VARIANT},
        flow_definition={"variant": CLIENT360_SYSTEM_VARIANT},
    )
    db_session.add_all([second_capability, second_system])
    db_session.flush()

    result = build_preflight(db_session, runtime_revision="local")

    assert result["summary"] == {"workspace_count": 2, "ready": 0, "blocked": 2}
    rows = {row["workspace_id"]: row for row in result["workspaces"]}
    assert "runtime_revision_not_exact" in {
        blocker["code"] for blocker in rows[missing.id]["blockers"]
    }
    assert any("found 0" in blocker["message"] for blocker in rows[missing.id]["blockers"])
    assert any(
        "found 2" in blocker["message"] for blocker in rows[ambiguous.id]["blockers"]
    )


def test_preflight_ignores_paused_duplicate_but_rejects_wrong_capability_contract(db_session) -> None:
    ready = _workspace(db_session, "lifecycle", family="andritz")
    active, _capability = _authority(db_session, ready, "lifecycle-active")
    paused_capability = Capability(
        id="cap-c360-preflight-lifecycle-paused",
        workspace_id=ready.id,
        slug="paused-client360-copy",
        name="Paused copy",
        tier="client",
    )
    paused = System(
        id="sys-c360-preflight-lifecycle-paused",
        workspace_id=ready.id,
        name="Paused copy",
        objective="Not an execution authority",
        capability_id=paused_capability.id,
        status="paused",
        settings={"system_type": CLIENT360_SYSTEM_VARIANT},
        flow_definition={"variant": CLIENT360_SYSTEM_VARIANT},
    )
    wrong = _workspace(db_session, "wrong", family="andritz")
    _authority(
        db_session,
        wrong,
        "wrong",
        slug="wrong-client360-contract",
    )
    db_session.add_all([paused_capability, paused])
    db_session.flush()

    result = build_preflight(db_session, runtime_revision=REVISION)
    rows = {row["workspace_id"]: row for row in result["workspaces"]}

    assert rows[ready.id]["ready"] is True
    assert rows[ready.id]["system_id"] == active.id
    assert rows[wrong.id]["ready"] is False
    assert any(
        "contract does not match" in blocker["message"]
        for blocker in rows[wrong.id]["blockers"]
    )


def test_preflight_empty_cohort_and_cli_target_sha_fail_closed(db_session) -> None:
    result = build_preflight(
        db_session,
        family="andritz",
        runtime_revision=REVISION,
    )

    assert result["workspaces"] == []
    assert result["summary"] == {"workspace_count": 0, "ready": 0, "blocked": 1}
    assert result["blockers"][0]["code"] == "no_workspace_selected"
    args = _parser().parse_args(["--runtime-revision", REVISION])
    assert args.runtime_revision == REVISION


def test_cli_requires_the_explicit_target_revision_even_if_runtime_has_an_old_sha(
    monkeypatch,
    capsys,
) -> None:
    from scripts import preflight_client360_authority as preflight

    monkeypatch.setattr(preflight.settings, "agentium_image_revision", "b" * 40)
    monkeypatch.setattr(
        preflight,
        "SessionLocal",
        lambda: pytest.fail("database must not be opened without the target SHA"),
    )

    assert main([]) == 2
    assert "target_runtime_revision_required" in capsys.readouterr().out


def test_preflight_config_content_drift_changes_authority_at_same_version(db_session) -> None:
    workspace = _workspace(db_session, "config-drift", family="andritz")
    _authority(db_session, workspace, "config-drift")
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=3,
        role_flags={},
        capability_overrides={},
    )
    db_session.add(config)
    db_session.flush()
    before = build_preflight(db_session, runtime_revision=REVISION)["workspaces"][0]

    config.role_flags = {"engine.run": False}
    db_session.flush()
    after = build_preflight(db_session, runtime_revision=REVISION)["workspaces"][0]

    assert after["iam_config_version"] == before["iam_config_version"] == 3
    assert after["candidate_config_sha256"] != before["candidate_config_sha256"]
    assert after["authority_sha256"] != before["authority_sha256"]
