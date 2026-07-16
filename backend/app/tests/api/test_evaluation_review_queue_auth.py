"""Authorization boundary for review-queue Run evidence."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import evaluation
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_REVIEWER
from app.models.canonical_answer import CanonicalAnswer
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.evaluation.canonical_answer_service import create_canonical_answer


def _subject(db_session, *, role_template: str) -> tuple[Workspace, User]:
    token = uuid4().hex[:8]
    workspace = Workspace(
        id=str(uuid4()),
        name="Review queue auth",
        slug=f"review-queue-{token}",
        settings={},
    )
    user = User(
        id=str(uuid4()),
        username=f"review-queue-{token}",
        email=f"review-queue-{token}@example.invalid",
        role="user",
    )
    membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template=role_template,
    )
    db_session.add_all([workspace, user, membership])
    db_session.commit()
    return workspace, user


@pytest.mark.asyncio
async def test_review_queue_rejects_ordinary_member(db_session):
    workspace, member = _subject(
        db_session,
        role_template=WORKSPACE_CONTRIBUTOR,
    )

    with pytest.raises(HTTPException) as exc_info:
        await evaluation.review_queue(
            status="proposed",
            component=None,
            limit=50,
            workspace=workspace,
            user=member,
            db=db_session,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_review_queue_allows_workspace_reviewer(db_session):
    workspace, reviewer = _subject(
        db_session,
        role_template=WORKSPACE_REVIEWER,
    )

    result = await evaluation.review_queue(
        status="proposed",
        component=None,
        limit=50,
        workspace=workspace,
        user=reviewer,
        db=db_session,
    )

    assert result == {"items": [], "count": 0}


@pytest.mark.asyncio
async def test_canonical_answer_create_and_delete_reject_ordinary_member(db_session):
    workspace, member = _subject(
        db_session,
        role_template=WORKSPACE_CONTRIBUTOR,
    )
    existing = create_canonical_answer(
        db_session,
        workspace_id=workspace.id,
        question="Question governed",
        answer="Answer governed",
        actor="trusted-seed",
    )
    db_session.commit()

    with pytest.raises(HTTPException) as create_error:
        await evaluation.create_canonical_answer_endpoint(
            evaluation.CanonicalAnswerIn(
                question="Poisoned question",
                answer="Poisoned answer",
                actor="spoofed-admin@example.invalid",
            ),
            workspace,
            member,
            db_session,
        )
    with pytest.raises(HTTPException) as delete_error:
        await evaluation.delete_canonical_answer_endpoint(
            existing.id,
            workspace,
            member,
            db_session,
        )

    assert create_error.value.status_code == 403
    assert delete_error.value.status_code == 403
    assert db_session.get(CanonicalAnswer, existing.id) is not None


@pytest.mark.asyncio
async def test_reviewer_canonical_answer_uses_authenticated_actor(db_session):
    workspace, reviewer = _subject(
        db_session,
        role_template=WORKSPACE_REVIEWER,
    )

    result = await evaluation.create_canonical_answer_endpoint(
        evaluation.CanonicalAnswerIn(
            question="Trusted question",
            answer="Trusted answer",
            actor="spoofed-admin@example.invalid",
        ),
        workspace,
        reviewer,
        db_session,
    )

    assert result["created_by"] == reviewer.email
    assert result["created_by"] != "spoofed-admin@example.invalid"
