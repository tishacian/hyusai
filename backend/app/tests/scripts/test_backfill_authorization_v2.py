"""Safety contract for the authorization-v2 shadow backfill."""

from uuid import uuid4

import pytest

from app.models.audit import AuditLog
from app.models.workspace import Workspace, WorkspaceIAMConfig
from scripts import backfill_authorization_v2 as backfill


def _workspace(db_session, *, family: str, active: bool = True) -> Workspace:
    row = Workspace(
        id=str(uuid4()),
        slug=f"opaque-{uuid4()}",
        name="Opaque workspace",
        is_active=active,
        settings={"family": family},
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_shadow_backfill_is_dry_run_by_default_and_family_is_canonical(db_session):
    andritz = _workspace(db_session, family="andritz")
    _workspace(db_session, family="generic")
    _workspace(db_session, family="andritz", active=False)
    unstamped = _workspace(db_session, family="generic")
    unstamped.settings = {}
    db_session.commit()

    report = backfill.run(
        workspace_ids=[],
        family="andritz",
        mode="shadow",
        apply=False,
        db=db_session,
    )

    assert report["operation"] == "dry-run"
    assert report["selected_count"] == 1
    assert report["workspaces"][0]["workspace_id"] == andritz.id
    assert report["workspaces"][0]["action"] == "would_update"
    assert db_session.get(WorkspaceIAMConfig, andritz.id) is None
    assert db_session.query(AuditLog).count() == 0

    generic = backfill.run(
        workspace_ids=[],
        family="generic",
        mode="shadow",
        apply=False,
        db=db_session,
    )
    assert generic["selected_count"] == 1
    assert generic["workspaces"][0]["workspace_id"] != unstamped.id


def test_shadow_backfill_apply_is_explicit_audited_and_idempotent(db_session):
    workspace = _workspace(db_session, family="generic")

    with pytest.raises(ValueError, match="non-empty --actor"):
        backfill.run(
            workspace_ids=[workspace.id],
            family=None,
            mode="shadow",
            apply=True,
            db=db_session,
        )

    first = backfill.run(
        workspace_ids=[workspace.id],
        family=None,
        mode="shadow",
        apply=True,
        actor="operator@example.net",
        db=db_session,
    )
    config = db_session.get(WorkspaceIAMConfig, workspace.id)
    assert config is not None
    modes = config.capability_overrides["authorization_v2"]["modes"]
    assert modes
    assert set(modes.values()) == {"shadow"}
    assert first["changed_count"] == 1
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.authorization.shadow_configured",
        )
        .count()
        == 1
    )

    version = config.version
    second = backfill.run(
        workspace_ids=[workspace.id],
        family=None,
        mode="shadow",
        apply=True,
        actor="operator@example.net",
        db=db_session,
    )
    db_session.refresh(config)
    assert second["changed_count"] == 0
    assert config.version == version
    assert db_session.query(AuditLog).count() == 1


def test_shadow_backfill_cannot_enforce_or_guess_a_workspace(db_session):
    workspace = _workspace(db_session, family="generic")

    with pytest.raises(ValueError, match="only supports shadow"):
        backfill.run(
            workspace_ids=[workspace.id],
            family=None,
            mode="enforce",
            apply=False,
            db=db_session,
        )
    with pytest.raises(ValueError, match="Select at least one"):
        backfill.run(
            workspace_ids=[],
            family=None,
            mode="shadow",
            apply=False,
            db=db_session,
        )
    with pytest.raises(ValueError, match="Unknown active workspace ids"):
        backfill.run(
            workspace_ids=[str(uuid4())],
            family=None,
            mode="shadow",
            apply=False,
            db=db_session,
        )
