"""Bounds on the context-signature thread reuse of ``_ensure_chat_session``.

A client that sends no ``session_id`` is handed the latest thread carrying the
same context signature. That fallback had no end: in production one thread had
glued 72 messages together from 28 July onwards, and no interaction could open
a fresh one. It is now bounded by idle age and by length — a platform fix, every
surface and every workspace, not a tenant one.

An explicitly supplied ``session_id`` is never rotated: the caller chose that
thread, so neither bound applies to it.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.chat import (
    CHAT_SESSION_REUSE_MAX_IDLE,
    CHAT_SESSION_REUSE_MAX_MESSAGES,
    _chat_context_signature,
    _ensure_chat_session,
)
from app.models.user import Message, User
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace


@pytest.fixture()
def actors(db_session):
    workspace = Workspace(id="ws-chat-thread", name="Chat Thread", slug="chat-thread")
    user = User(id="user-chat-thread", username="ada@datategy.local", email="ada@datategy.local")
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def _seed_thread(
    db_session,
    workspace: Workspace,
    user: User,
    *,
    session_id: str,
    idle: timedelta = timedelta(minutes=1),
    messages: int = 2,
) -> ChatSession:
    """An existing thread with the signature produced by an empty payload."""
    last_activity = datetime.utcnow() - idle
    session = ChatSession(
        id=session_id,
        user_id=user.id,
        workspace_id=workspace.id,
        title="Existing",
        status="active",
        # The signature an empty payload produces: the default workspace context.
        context_signature=_chat_context_signature({}),
        created_at=last_activity,
        last_activity=last_activity,
        meta_data={},
    )
    db_session.add(session)
    db_session.flush()
    db_session.add_all(
        [
            Message(
                id=f"{session_id}-message-{index}",
                session_id=session_id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"message {index}",
                timestamp=last_activity,
                meta_data={},
            )
            for index in range(messages)
        ]
    )
    db_session.commit()
    return session


def test_recent_short_thread_is_still_reused(db_session, actors):
    workspace, user = actors
    existing = _seed_thread(db_session, workspace, user, session_id="thread-recent")

    payload: dict = {}
    resolved = _ensure_chat_session(db_session, workspace=workspace, user=user, request_payload=payload)

    assert resolved.id == existing.id
    assert payload["session_id"] == existing.id


def test_thread_idle_past_the_bound_opens_a_new_one(db_session, actors):
    workspace, user = actors
    existing = _seed_thread(
        db_session,
        workspace,
        user,
        session_id="thread-idle",
        idle=CHAT_SESSION_REUSE_MAX_IDLE + timedelta(minutes=1),
    )

    resolved = _ensure_chat_session(db_session, workspace=workspace, user=user, request_payload={})

    assert resolved.id != existing.id
    assert resolved.context_signature == existing.context_signature
    # The old thread is left intact and readable, it simply stops growing.
    assert db_session.get(ChatSession, existing.id).status == "active"


def test_thread_longer_than_the_bound_opens_a_new_one(db_session, actors):
    workspace, user = actors
    existing = _seed_thread(
        db_session,
        workspace,
        user,
        session_id="thread-long",
        messages=CHAT_SESSION_REUSE_MAX_MESSAGES,
    )

    resolved = _ensure_chat_session(db_session, workspace=workspace, user=user, request_payload={})

    assert resolved.id != existing.id


def test_the_production_runaway_thread_is_no_longer_extended(db_session, actors):
    """The exact shape observed in production: 72 messages, two weeks old."""
    workspace, user = actors
    existing = _seed_thread(
        db_session,
        workspace,
        user,
        session_id="thread-runaway",
        idle=timedelta(days=14),
        messages=72,
    )

    first = _ensure_chat_session(db_session, workspace=workspace, user=user, request_payload={})
    second = _ensure_chat_session(db_session, workspace=workspace, user=user, request_payload={})

    assert first.id != existing.id
    # The fresh thread is short and recent, so the next turn continues it rather
    # than opening yet another one on every message.
    assert second.id == first.id


def test_the_new_thread_is_the_one_reused_next(db_session, actors):
    workspace, user = actors
    _seed_thread(
        db_session,
        workspace,
        user,
        session_id="thread-exhausted",
        messages=CHAT_SESSION_REUSE_MAX_MESSAGES + 10,
    )

    opened = _ensure_chat_session(db_session, workspace=workspace, user=user, request_payload={})
    db_session.add(
        Message(
            id="follow-up",
            session_id=opened.id,
            role="user",
            content="suite",
            timestamp=datetime.utcnow(),
            meta_data={},
        )
    )
    db_session.commit()

    assert _ensure_chat_session(db_session, workspace=workspace, user=user, request_payload={}).id == opened.id


def test_an_explicit_session_id_is_never_rotated(db_session, actors):
    """The caller chose this thread; neither bound applies to an explicit id."""
    workspace, user = actors
    existing = _seed_thread(
        db_session,
        workspace,
        user,
        session_id="thread-explicit",
        idle=timedelta(days=30),
        messages=CHAT_SESSION_REUSE_MAX_MESSAGES + 50,
    )

    resolved = _ensure_chat_session(
        db_session,
        workspace=workspace,
        user=user,
        request_payload={"session_id": existing.id},
    )

    assert resolved.id == existing.id


def test_an_unknown_session_id_is_still_a_404(db_session, actors):
    workspace, user = actors

    with pytest.raises(HTTPException) as excinfo:
        _ensure_chat_session(
            db_session,
            workspace=workspace,
            user=user,
            request_payload={"session_id": "thread-unknown"},
        )

    assert excinfo.value.status_code == 404


def test_reuse_latest_session_false_still_forces_a_new_thread(db_session, actors):
    workspace, user = actors
    existing = _seed_thread(db_session, workspace, user, session_id="thread-optout")

    resolved = _ensure_chat_session(
        db_session,
        workspace=workspace,
        user=user,
        request_payload={"reuse_latest_session": False},
    )

    assert resolved.id != existing.id
