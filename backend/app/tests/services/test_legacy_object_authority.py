from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.legacy_authority import legacy_object_action_allowed


def _subject(db_session, *, role_template="workspace_viewer"):
    workspace = Workspace(id="legacy-authority-ws", slug="legacy-authority", name="Legacy")
    user = User(id="legacy-authority-user", username="legacy@test", email="legacy@test")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template=role_template,
    )
    db_session.add_all([workspace, user, member])
    db_session.commit()
    return workspace, user


def test_legacy_admin_matches_existing_mutation_routes(db_session):
    workspace, user = _subject(db_session)

    for resource_kind in ("capability", "system", "run"):
        assert legacy_object_action_allowed(
            db_session,
            user=user,
            workspace=workspace,
            resource_kind=resource_kind,
            action="admin",
        )
    assert not legacy_object_action_allowed(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="skill_invocation",
        action="admin",
    )


def test_legacy_run_approval_is_owner_or_admin_and_managed_system_is_stricter(
    db_session,
):
    workspace, user = _subject(db_session)
    system = System(
        id="legacy-system",
        workspace_id=workspace.id,
        name="Legacy system",
        capability_id="capability",
    )
    own_run = Run(
        id="legacy-own-run",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=user.id,
        status="hitl_pending",
    )
    other_run = Run(
        id="legacy-other-run",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id="somebody-else",
        status="hitl_pending",
    )
    db_session.add_all([system, own_run, other_run])
    db_session.commit()

    assert legacy_object_action_allowed(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="approve",
        runs=[own_run],
    )
    assert not legacy_object_action_allowed(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="approve",
        runs=[other_run],
    )
