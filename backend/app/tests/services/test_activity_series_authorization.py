"""Read-context optimization must remain equivalent to native read boundaries."""

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.activity import Activity
from app.models.brd_document import BrdDocument
from app.models.compute_run import ComputeRun
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.activity_observability.queries import VisibilityReadContext, filter_visible
from app.services.activity_observability.series import activity_series


@pytest.fixture
def scope(db_session, monkeypatch):
    monkeypatch.setattr(settings, "activity_observability_enabled", True)
    ws = Workspace(
        id="context-ws",
        slug="context-ws",
        name="Context",
        settings={
            "_migration_059_andritz_agentic_default_state": {
                "revision": "059_andritz_agentic_default",
                "schema": 1,
                "system_id": "managed",
            },
        },
    )
    user = User(id="context-user", username="context-user", role="user", is_active=True)
    other = User(id="context-other", username="context-other", role="user", is_active=True)
    db_session.add_all([ws, user, other])
    db_session.flush()
    member = WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="member")
    db_session.add_all([member, System(id="managed", workspace_id=ws.id, name="Managed")])
    db_session.commit()
    return db_session, ws, user, other, member


def seed_runs(scope):
    db, ws, user, other, _ = scope
    runs = [
        Run(id="public", workspace_id=ws.id),
        Run(
            id="private", workspace_id=ws.id, trigger="chat_agentic", initiated_by_user_id=other.id
        ),
        Run(
            id="own-private",
            workspace_id=ws.id,
            trigger="chat_agentic",
            initiated_by_user_id=user.id,
        ),
        Run(
            id="workbench",
            workspace_id=ws.id,
            execution_surface="builder_preview",
            initiated_by_user_id=other.id,
        ),
        Run(
            id="own-workbench",
            workspace_id=ws.id,
            execution_surface="builder_preview",
            initiated_by_user_id=user.id,
        ),
        Run(id="managed-wait", workspace_id=ws.id, system_id="managed", status="hitl_pending"),
        Run(
            id="managed-rejected",
            workspace_id=ws.id,
            system_id="managed",
            status="completed",
            output_ref={"hitl_decision": "rejected"},
        ),
        Run(id="managed-done", workspace_id=ws.id, system_id="managed", status="completed"),
    ]
    db.add_all(runs)
    db.commit()
    return runs


def ids(rows):
    return {row.native_id for row in rows}


@pytest.mark.parametrize(
    "role,template,allowed",
    [
        (
            "user",
            "workspace_contributor",
            {"public", "own-private", "own-workbench", "managed-done"},
        ),
        (
            "user",
            "workspace_reviewer",
            {"public", "private", "own-private", "own-workbench", "managed-done"},
        ),
        (
            "user",
            "workspace_admin",
            {
                "public",
                "private",
                "own-private",
                "workbench",
                "own-workbench",
                "managed-wait",
                "managed-rejected",
                "managed-done",
            },
        ),
        (
            "admin",
            "workspace_contributor",
            {
                "public",
                "private",
                "own-private",
                "workbench",
                "own-workbench",
                "managed-wait",
                "managed-rejected",
                "managed-done",
            },
        ),
    ],
)
def test_cached_native_visibility_equals_uncached_for_all_roles(scope, role, template, allowed):
    db, ws, user, _, member = scope
    user.role, member.role_template = role, template
    seed_runs(scope)
    rows = db.query(Activity).all()
    uncached = ids(filter_visible(db, rows, ws, user))
    context = VisibilityReadContext(db, ws, user)
    assert db.query(WorkspaceIAMConfig).count() == 0
    assert uncached == allowed
    assert ids(filter_visible(db, rows, ws, user, read_context=context)) == allowed
    # Hits retain the same decision without retaining Run checkpoint/prompt JSON.
    assert ids(filter_visible(db, rows, ws, user, read_context=context)) == allowed
    assert all(not hasattr(value[1], "checkpoints") for value in context.runs.values())
    assert db.query(WorkspaceIAMConfig).count() == 0


def test_context_does_not_outlive_role_revocation_or_transaction(scope):
    db, ws, user, _, member = scope
    member.role_template = "workspace_admin"
    seed_runs(scope)
    rows = db.query(Activity).all()
    context = VisibilityReadContext(db, ws, user)
    assert "private" in ids(filter_visible(db, rows, ws, user, read_context=context))
    member.role_template = "workspace_contributor"
    db.commit()
    with pytest.raises(ValueError, match="expired"):
        filter_visible(db, rows, ws, user, read_context=context)
    fresh = VisibilityReadContext(db, ws, user)
    assert "private" not in ids(filter_visible(db, rows, ws, user, read_context=fresh))
    db.delete(member)
    db.commit()
    with pytest.raises(HTTPException) as error:
        activity_series(db, ws, user, start=datetime(2026, 1, 1), until=datetime(2026, 1, 2))
    assert error.value.status_code == 403


def test_context_rejects_other_user_and_eviction_cannot_drop_visible_rows(scope, monkeypatch):
    db, ws, user, other, _ = scope
    db.add_all([Run(id=f"public-{i}", workspace_id=ws.id) for i in range(5)])
    db.commit()
    rows = db.query(Activity).order_by(Activity.native_id).all()
    context = VisibilityReadContext(db, ws, user)
    original = VisibilityReadContext.remember
    monkeypatch.setattr(
        VisibilityReadContext,
        "remember",
        staticmethod(lambda cache, key, value, limit=16384: original(cache, key, value, 2)),
    )
    filter_visible(db, rows[:2], ws, user, read_context=context)
    assert ids(filter_visible(db, rows, ws, user, read_context=context)) == ids(rows)
    assert len(context.runs) <= 2
    with pytest.raises(ValueError, match="another identity"):
        filter_visible(db, rows, ws, other, read_context=context)


def test_invocation_enforcement_remains_independent_of_cached_parent(
    scope, attest_authorization_v2
):
    db, ws, user, _, member = scope
    member.role_template = "workspace_viewer"
    db.add(Run(id="public", workspace_id=ws.id))
    db.flush()
    db.add(SkillInvocation(id="denied-invocation", run_id="public", status="completed"))
    config = WorkspaceIAMConfig(
        workspace_id=ws.id,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"skill_invocation.read": "enforce"},
            },
        },
    )
    db.add(config)
    attest_authorization_v2(config, ["skill_invocation.read"])
    db.commit()
    rows = db.query(Activity).all()
    context = VisibilityReadContext(db, ws, user)
    assert ids(filter_visible(db, rows, ws, user)) == {"public"}
    assert ids(filter_visible(db, rows, ws, user, read_context=context)) == {"public"}
    assert ids(filter_visible(db, rows, ws, user, read_context=context)) == {"public"}


def test_compute_jobs_and_brd_native_boundaries_survive_admin_preload(scope):
    db, ws, user, other, _ = scope
    db.add(Run(id="public", workspace_id=ws.id))
    db.flush()
    db.add_all(
        [
            ComputeRun(
                id="owned-compute",
                workspace_id=ws.id,
                run_id="public",
                user_id=user.id,
                kind="dataops",
                operation="prepare",
                deadline_at=datetime.now() + timedelta(hours=1),
            ),
            ComputeRun(
                id="other-compute",
                workspace_id=ws.id,
                run_id="public",
                user_id=other.id,
                kind="dataops",
                operation="prepare",
                deadline_at=datetime.now() + timedelta(hours=1),
            ),
            WorkspaceJob(
                id="owned-job",
                workspace_id=ws.id,
                run_id="public",
                created_by_user_id=user.id,
                kind="qualification",
            ),
            WorkspaceJob(
                id="other-job",
                workspace_id=ws.id,
                run_id="public",
                created_by_user_id=other.id,
                kind="qualification",
            ),
            BrdDocument(
                id="brd-doc",
                workspace_id=ws.id,
                created_by_user_id=user.id,
                sha256="0" * 64,
                size_bytes=1,
                filename="test",
                storage_key="test",
                extraction={},
            ),
            WorkspaceJob(
                id="owned-brd",
                workspace_id=ws.id,
                run_id="public",
                created_by_user_id=user.id,
                kind="brd_generation",
                input_ref={"document_id": "brd-doc"},
            ),
            WorkspaceJob(
                id="missing-brd",
                workspace_id=ws.id,
                run_id="public",
                created_by_user_id=user.id,
                kind="brd_generation",
                input_ref={"document_id": "missing"},
            ),
            WorkspaceJob(
                id="other-brd",
                workspace_id=ws.id,
                run_id="public",
                created_by_user_id=other.id,
                kind="brd_generation",
                input_ref={"document_id": "brd-doc"},
            ),
        ]
    )
    db.commit()
    for admin in (False, True):
        user.role = "admin" if admin else "user"
        db.commit()
        rows = db.query(Activity).all()
        expected = ids(filter_visible(db, rows, ws, user))
        context = VisibilityReadContext(db, ws, user)
        assert ids(filter_visible(db, rows, ws, user, read_context=context)) == expected
        assert "owned-job" in expected and "owned-compute" in expected
        assert ("owned-brd" in expected) is admin
        assert "missing-brd" not in expected and "other-brd" not in expected
        assert ("other-compute" in expected) is admin
        assert ("other-job" in expected) is admin
