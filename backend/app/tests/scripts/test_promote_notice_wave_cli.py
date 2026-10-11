from __future__ import annotations

import sys

import pytest

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from scripts import promote_notice_wave


def _membership(
    db_session,
    *,
    role: str,
    role_template: str | None = None,
) -> tuple[Workspace, User]:
    identity = role_template or role
    workspace = Workspace(id=f"ws-{identity}", name="Andritz", slug=f"andritz-{identity}")
    user = User(
        id=f"user-{identity}",
        username=f"operator-{identity}",
        email=f"operator-{identity}@example.test",
    )
    db_session.add_all([workspace, user])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=role,
            role_template=role_template,
        )
    )
    db_session.commit()
    return workspace, user


@pytest.mark.parametrize(
    ("role", "role_template"),
    [
        ("admin", None),
        ("owner", None),
        ("member", "workspace_reviewer"),
        ("admin", "workspace_admin"),
        ("owner", "workspace_owner"),
    ],
)
def test_resolve_actor_requires_review_membership(db_session, role, role_template):
    workspace, user = _membership(
        db_session,
        role=role,
        role_template=role_template,
    )

    resolved = promote_notice_wave._resolve_actor(
        db_session,
        workspace=workspace,
        email=user.email,
    )

    assert resolved.id == user.id


def test_resolve_actor_rejects_non_admin_or_cross_workspace(db_session):
    workspace, user = _membership(db_session, role="member")

    with pytest.raises(SystemExit, match="reviewer, admin, or owner"):
        promote_notice_wave._resolve_actor(
            db_session,
            workspace=workspace,
            email=user.email,
        )

    other = Workspace(id="ws-other", name="Other", slug="other")
    db_session.add(other)
    db_session.commit()
    with pytest.raises(SystemExit, match="not a member"):
        promote_notice_wave._resolve_actor(
            db_session,
            workspace=other,
            email=user.email,
        )


def test_resolve_actor_rejects_inactive_user(db_session):
    workspace, user = _membership(db_session, role="admin")
    user.is_active = False
    db_session.commit()

    with pytest.raises(SystemExit, match="inactive"):
        promote_notice_wave._resolve_actor(
            db_session,
            workspace=workspace,
            email=user.email,
        )


def test_planner_cli_rejects_direct_execute_before_opening_database(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "promote_notice_wave",
            "--workspace",
            "andritz",
            "--project",
            "61035",
            "--execute",
            "--plan-hash",
            "a" * 64,
        ],
    )
    monkeypatch.setattr(
        promote_notice_wave,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
    )

    with pytest.raises(SystemExit) as exc_info:
        promote_notice_wave.main()

    assert exc_info.value.code == 2
