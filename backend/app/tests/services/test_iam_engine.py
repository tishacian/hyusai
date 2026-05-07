from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_VIEWER,
    normalize_role_template,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceIAMConfig
from app.services.iam.engine import AuthorizationEngine


def _subject(db_session, role_template: str, *, legacy_role: str = "member", labels=None):
    workspace = Workspace(id=f"ws-{role_template}", name=role_template, slug=f"slug-{role_template}")
    user = User(id=f"user-{role_template}", username=f"{role_template}@demo", email=f"{role_template}@demo.test")
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role=legacy_role,
        role_template=role_template,
        custom_labels=labels or [],
    )
    db_session.add_all([workspace, user, membership])
    db_session.commit()
    return workspace, user, membership


def test_legacy_roles_normalize_to_templates():
    assert normalize_role_template(None, "member") == WORKSPACE_CONTRIBUTOR
    assert normalize_role_template(None, "admin") == WORKSPACE_ADMIN
    assert normalize_role_template("workspace_reviewer", "member") == WORKSPACE_REVIEWER


def test_capture_contributor_can_execute_only_owned_session(db_session):
    workspace, user, membership = _subject(db_session, WORKSPACE_CONTRIBUTOR)
    engine = AuthorizationEngine()

    own = engine.evaluate(
        db_session,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="capture_session",
        action="execute",
        resource_attrs={"owner_user_id": user.id},
        audit_denials=False,
    )
    other = engine.evaluate(
        db_session,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="capture_session",
        action="execute",
        resource_attrs={"owner_user_id": "someone-else"},
        audit_denials=False,
    )

    assert own.allowed is True
    assert other.allowed is False
    assert other.reason == "WORKSPACE_PERMISSION_DENIED"


def test_reviewer_can_decide_proposals_but_viewer_is_deny_by_default(db_session):
    reviewer_ws, reviewer, reviewer_membership = _subject(db_session, WORKSPACE_REVIEWER)
    viewer_ws, viewer, viewer_membership = _subject(db_session, WORKSPACE_VIEWER)
    engine = AuthorizationEngine()

    review = engine.evaluate(
        db_session,
        user=reviewer,
        workspace=reviewer_ws,
        membership=reviewer_membership,
        resource_kind="knowledge_proposal",
        action="review_decide",
        resource_attrs={"owner_user_id": "author"},
        audit_denials=False,
    )
    denied = engine.evaluate(
        db_session,
        user=viewer,
        workspace=viewer_ws,
        membership=viewer_membership,
        resource_kind="capture_session",
        action="read",
        resource_attrs={"owner_user_id": viewer.id},
        audit_denials=False,
    )
    voice = engine.evaluate(
        db_session,
        user=viewer,
        workspace=viewer_ws,
        membership=viewer_membership,
        resource_kind="voice_runtime",
        action="read",
        resource_attrs={},
        audit_denials=False,
    )

    assert review.allowed is True
    assert denied.allowed is False
    assert voice.allowed is True


def test_second_eye_flag_blocks_author_ingestion(db_session):
    workspace, user, membership = _subject(db_session, WORKSPACE_REVIEWER)
    db_session.add(
        WorkspaceIAMConfig(
            workspace_id=workspace.id,
            role_flags={"require_second_eye_for_ingestion": True},
            capability_overrides={},
        )
    )
    db_session.commit()

    decision = AuthorizationEngine().evaluate(
        db_session,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="knowledge_proposal",
        action="trigger_ingestion",
        resource_attrs={"owner_user_id": user.id},
        audit_denials=False,
    )

    assert decision.allowed is False
