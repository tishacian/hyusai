"""``audit_log_v1`` must actually record what it says it recorded.

The skill used to log a line, mint a uuid and answer ``recorded`` without
persisting anything: ``GET /api/v1/audit`` returned nothing for events it had
"written", and the ids it handed back referenced no row. These tests pin the
two halves of the fix — the event lands where the governance screens read it,
and the skill never claims success it did not achieve.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.audit import AuditLog
from app.models.workspace import Workspace
from app.services.skills_registry import wrappers

pytestmark = pytest.mark.asyncio


EVENT = "itsd.password_reset.withheld"


def _mk_workspace(db, slug: str) -> Workspace:
    row = Workspace(id=str(uuid.uuid4()), name=slug, slug=slug)
    db.add(row)
    db.commit()
    return row


def _governance_query(db, workspace_id: str, event_type: str | None = None):
    """The exact read the audit endpoint performs, tenant filter included."""
    query = (
        db.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.timestamp.desc())
    )
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    return query.all()


async def test_the_event_is_readable_through_the_governance_read_path(db_session):
    workspace = _mk_workspace(db_session, "nawa-audit-read")
    ctx = {
        "workspace_id": workspace.id,
        "system_id": "system-password-reset",
        "run_id": "run-1234",
        "user_id": "user-owner",
    }
    details = {"action": "reset_user_password", "disposition": "withheld"}

    result = await wrappers._audit_log_v1(
        {"event_type": EVENT, "details": details}, ctx
    )
    assert result["status"] == "recorded"

    db_session.expire_all()
    rows = _governance_query(db_session, workspace.id, EVENT)
    assert len(rows) == 1
    row = rows[0]
    # The id the skill handed back must reference the row it wrote — the old
    # stub returned an orphan uuid.
    assert row.id == result["id"]
    assert row.details == details
    assert row.workspace_id == workspace.id
    assert row.trace_id == "run-1234"
    assert row.agent_id == "system-password-reset"
    assert row.actor == "user-owner"
    assert row.severity == "info"


async def test_the_event_is_scoped_to_its_own_workspace(db_session):
    """The read path filters on workspace_id and nothing else, so a bad
    attribution is indistinguishable from a missing entry."""
    mine = _mk_workspace(db_session, "nawa-scope-mine")
    other = _mk_workspace(db_session, "nawa-scope-other")

    await wrappers._audit_log_v1(
        {"event_type": EVENT, "details": {}}, {"workspace_id": mine.id}
    )

    db_session.expire_all()
    assert len(_governance_query(db_session, mine.id)) == 1
    assert _governance_query(db_session, other.id) == []


async def test_an_explicit_actor_from_the_flow_wins_over_the_run_initiator(db_session):
    workspace = _mk_workspace(db_session, "nawa-audit-actor")
    await wrappers._audit_log_v1(
        {"event_type": EVENT, "details": {}, "actor": "NAWA WE (automated)"},
        {"workspace_id": workspace.id, "user_id": "user-owner"},
    )

    db_session.expire_all()
    assert _governance_query(db_session, workspace.id)[0].actor == "NAWA WE (automated)"


async def test_a_failed_write_is_never_reported_as_recorded(db_session, monkeypatch):
    """The defect in one line: the shared writer swallows its errors and
    returns None. Returning `recorded` on that is how a compliance ledger
    silently loses events."""
    workspace = _mk_workspace(db_session, "nawa-audit-fail")
    monkeypatch.setattr(
        "app.services.audit_logger.emit_audit_event", lambda **_kwargs: None
    )

    with pytest.raises(RuntimeError, match="audit ledger write failed"):
        await wrappers._audit_log_v1(
            {"event_type": EVENT, "details": {}}, {"workspace_id": workspace.id}
        )

    db_session.expire_all()
    assert _governance_query(db_session, workspace.id) == []


async def test_an_unattributable_event_is_refused_rather_than_written_invisibly(
    db_session,
):
    """A row with no workspace is unreadable by every governance screen. It is
    the same lie as not writing it, so the skill refuses instead."""
    with pytest.raises(ValueError, match="no workspace"):
        await wrappers._audit_log_v1({"event_type": EVENT, "details": {}}, {})

    assert db_session.query(AuditLog).count() == 0


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"details": {}}, "requires an event_type"),
        ({"event_type": "  ", "details": {}}, "requires an event_type"),
        ({"event_type": EVENT, "details": "not-an-object"}, "must be an object"),
    ],
)
async def test_a_malformed_event_is_refused(db_session, payload, expected):
    workspace = _mk_workspace(db_session, "nawa-audit-malformed")
    with pytest.raises(ValueError, match=expected):
        await wrappers._audit_log_v1(payload, {"workspace_id": workspace.id})
    assert db_session.query(AuditLog).count() == 0
