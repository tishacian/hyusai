"""Explicit Lot-9 Workspace App installation backfill contracts."""

import pytest

from app.models.audit import AuditLog
from app.models.workspace import Workspace
from app.models.workspace_app import (
    WorkspaceAppInstallation,
    WorkspaceAppLifecycleStepReceipt,
    WorkspaceAppOperation,
)
from app.services.workspace_app_lifecycle import (
    apply_workspace_app_lifecycle,
    plan_workspace_app_lifecycle,
)
from app.services.workspace_app_manifests import list_builtin_workspace_app_manifests
from scripts.backfill_workspace_app_installations import (
    ANDRITZ_APP_IDS,
    WorkspaceAppBackfillError,
    _lock_workspaces_for_apply,
    analyze,
    apply,
)


def _workspace(db, key: str, *, settings: dict, slug: str | None = None) -> Workspace:
    workspace = Workspace(
        id=f"ws-{key}",
        name=f"Workspace {key}",
        slug=slug or f"unrelated-{key}",
        settings=settings,
    )
    db.add(workspace)
    db.commit()
    return workspace


def _manifest(app_id: str, version: str = "1.0.0"):
    return next(
        item for item in list_builtin_workspace_app_manifests(app_id) if item.version == version
    )


def test_andritz_selection_uses_family_not_slug_and_dry_run_is_read_only(db_session):
    assert ANDRITZ_APP_IDS == (
        "andritz.chat",
        "andritz.client360-pdr",
        "andritz.knowledge-capture",
    )
    canonical = _workspace(
        db_session,
        "canonical",
        settings={"family": "andritz"},
        slug="customer-42",
    )
    slug_only = _workspace(
        db_session,
        "slug-only",
        settings={"family": "generic"},
        slug="andritz",
    )

    report = analyze(db_session, workspace_ids=[canonical.id, slug_only.id])

    assert report["ready"] is True
    assert report["selection"] == "explicit_workspace_ids"
    canonical_apps = {
        row["app_id"] for row in report["changes"] if row["workspace_id"] == canonical.id
    }
    assert canonical_apps == {
        "andritz.chat",
        "andritz.client360-pdr",
        "andritz.knowledge-capture",
    }
    assert not [row for row in report["changes"] if row["workspace_id"] == slug_only.id]
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0


def test_sentinel_and_octocity_are_discovered_and_isolated_structurally(db_session):
    sentinel = _workspace(
        db_session,
        "sentinel",
        settings={
            "family": "sentinel_ci",
            "assistant_profile_default": "vigie_executive",
            "mission_room": {"enabled": True, "profile": "sentinel_government_v1"},
        },
        slug="opaque-a",
    )
    octocity = _workspace(
        db_session,
        "octocity",
        settings={
            "family": "generic",
            "assistant_profile_default": "octave_executive",
            "mission_room": {"enabled": True, "profile": "octocity_institutional_v1"},
        },
        slug="opaque-b",
    )

    report = analyze(db_session, workspace_ids=[sentinel.id, octocity.id])
    by_workspace = {row["workspace_id"]: row for row in report["changes"]}

    assert report["ready"] is True
    assert by_workspace[sentinel.id]["app_id"] == "sentinel.mission-room"
    assert by_workspace[sentinel.id]["configuration"] == {
        "profile": "government_mission_room",
        "assistant_profile": "vigie_executive",
    }
    assert "octocity" not in str(by_workspace[sentinel.id]).lower()
    assert by_workspace[octocity.id]["app_id"] == "octocity.mission-room"
    assert by_workspace[octocity.id]["configuration"] == {
        "profile": "octocity_mission_room",
        "assistant_profile": "octave_executive",
    }
    assert "sentinel" not in str(by_workspace[octocity.id]).lower()


def test_new_generic_adoption_targets_provider_capable_manifest(db_session):
    workspace = _workspace(
        db_session,
        "generic-provider",
        settings={
            "family": "generic",
            "assistant_profile_default": "default",
            "mission_room": {"enabled": True, "profile": "generic"},
        },
    )

    report = analyze(db_session, workspace_ids=[workspace.id])

    assert report["ready"] is True
    assert len(report["changes"]) == 1
    change = report["changes"][0]
    assert change["app_id"] == "mission-room.extension"
    assert change["version"] == "1.2.0"
    assert change["configuration"] == {
        "profile": "generic",
        "assistant_profile": "default",
        "decision_surfaces": True,
    }


def test_known_mission_room_profile_with_crossed_assistant_blocks(db_session):
    workspace = _workspace(
        db_session,
        "crossed",
        settings={
            "family": "generic",
            "assistant_profile_default": "octave_executive",
            "mission_room": {"enabled": True, "profile": "sentinel_government_v1"},
        },
    )

    report = analyze(db_session, workspace_ids=[workspace.id])

    assert report["ready"] is False
    assert report["blockers"] == [
        {
            "code": "mission_room_profile_assistant_mismatch",
            "workspace_id": workspace.id,
            "profile": "sentinel_government_v1",
            "expected_assistant_profile": "vigie_executive",
            "actual_assistant_profile": "octave_executive",
        }
    ]


def test_apply_requires_exact_analysis_and_is_atomic(db_session):
    workspace = _workspace(
        db_session,
        "apply",
        settings={"family": "andritz", "keep": {"operator": "owned"}},
    )
    before_settings = dict(workspace.settings)
    report = analyze(db_session, workspace_ids=[workspace.id])

    with pytest.raises(WorkspaceAppBackfillError, match="analysis changed"):
        apply(
            db_session,
            workspace_ids=[workspace.id],
            expected_analysis_sha256="0" * 64,
            actor="lot9-test",
        )

    result = apply(
        db_session,
        workspace_ids=[workspace.id],
        expected_analysis_sha256=report["analysis_sha256"],
        actor="lot9-test",
    )

    assert result["applied_count"] == 3
    assert result["legacy_settings_mutated"] is False
    assert result["member_entitlements_mutated"] is False
    assert db_session.query(WorkspaceAppInstallation).count() == 3
    assert db_session.query(WorkspaceAppOperation).count() == 3
    assert {
        row.lifecycle_phase for row in db_session.query(WorkspaceAppOperation).all()
    } == {"legacy_adoption"}
    step_receipts = db_session.query(WorkspaceAppLifecycleStepReceipt).all()
    assert len(step_receipts) == 9
    assert sum(
        row.executor == "explicit_legacy_backfill_v1" for row in step_receipts
    ) == 3
    assert all(
        row.evidence_sha256 == report["analysis_sha256"]
        for row in step_receipts
        if row.executor == "explicit_legacy_backfill_v1"
    )
    assert db_session.query(AuditLog).filter(AuditLog.workspace_id == workspace.id).count() == 3
    db_session.refresh(workspace)
    assert workspace.settings == before_settings

    replay = analyze(db_session, workspace_ids=[workspace.id])
    assert replay["ready"] is True
    assert {row["operation"] for row in replay["changes"]} == {"none"}
    assert {row["reason"] for row in replay["changes"]} == {"already_exact"}


def test_apply_locks_sorted_batch_before_revalidating_acknowledged_analysis(
    db_session,
    monkeypatch,
):
    first = _workspace(
        db_session,
        "z-last",
        settings={
            "family": "generic",
            "assistant_profile_default": "vigie_executive",
            "mission_room": {"enabled": True, "profile": "sentinel_government_v1"},
        },
    )
    second = _workspace(
        db_session,
        "a-first",
        settings={
            "family": "generic",
            "assistant_profile_default": "octave_executive",
            "mission_room": {"enabled": True, "profile": "octocity_institutional_v1"},
        },
    )
    report = analyze(db_session, workspace_ids=[first.id, second.id])

    observed: dict[str, object] = {}
    original_lock = _lock_workspaces_for_apply

    def lock_then_simulate_preexisting_drift(db, *, workspace_ids):
        rows = original_lock(db, workspace_ids=workspace_ids)
        observed["requested"] = list(workspace_ids)
        observed["locked"] = [row.id for row in rows]
        # Simulate state that won the race immediately before this transaction
        # acquired its batch locks. The mandatory re-analysis must see it and
        # reject the previously acknowledged dry-run.
        first.settings = {
            **dict(first.settings),
            "assistant_profile_default": "octave_executive",
        }
        db.flush()
        return rows

    monkeypatch.setattr(
        "scripts.backfill_workspace_app_installations._lock_workspaces_for_apply",
        lock_then_simulate_preexisting_drift,
    )

    with pytest.raises(WorkspaceAppBackfillError, match="analysis changed"):
        apply(
            db_session,
            workspace_ids=[first.id, second.id, first.id],
            expected_analysis_sha256=report["analysis_sha256"],
            actor="lot9-test",
        )

    assert observed == {
        "requested": sorted([first.id, second.id]),
        "locked": sorted([first.id, second.id]),
    }
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0


def test_different_installed_state_requires_normal_lifecycle(db_session):
    workspace = _workspace(
        db_session,
        "conflict",
        settings={
            "family": "generic",
            "assistant_profile_default": "default",
            "mission_room": {"enabled": True, "profile": "generic"},
        },
    )
    v1 = _manifest("mission-room.extension", "1.0.0")
    plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=v1.app_id,
        target_version=v1.version,
        expected_manifest_digest=v1.digest,
    )
    apply_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=v1.app_id,
        target_version=v1.version,
        expected_manifest_digest=v1.digest,
        expected_plan_sha256=plan.plan_sha256,
        actor="test",
        idempotency_key="install-v1",
    )

    report = analyze(db_session, workspace_ids=[workspace.id])

    assert report["ready"] is False
    assert report["blockers"][0]["code"] == "installed_app_requires_lifecycle_transition"
    assert report["blockers"][0]["installed_version"] == "1.0.0"


def test_missing_workspace_is_a_blocker_and_no_global_selection_exists(db_session):
    report = analyze(db_session, workspace_ids=["ws-does-not-exist"])
    assert report["ready"] is False
    assert report["blockers"] == [
        {"code": "workspace_not_found", "workspace_id": "ws-does-not-exist"}
    ]
    with pytest.raises(WorkspaceAppBackfillError, match="at least one explicit"):
        analyze(db_session, workspace_ids=[])
