"""Tests for ``services.chains.version_service`` — rolling window,
rollback semantics, and audit trail.

Uses the session-scoped SQLite fixture from ``conftest.py``. Each test
truncates through the global fixture so rows from prior tests don't
leak across the FIFO purge assertion.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.system import System
from app.models.system_version import SystemVersion
from app.services.chains import version_service


def _make_system(db_session, workspace_id: str = "ws-1", flow=None) -> System:
    sys_row = System(
        id=f"sys-{workspace_id}",
        workspace_id=workspace_id,
        name="test",
        objective="",
        flow_definition=flow if flow is not None else {"nodes": [], "edges": []},
    )
    db_session.add(sys_row)
    db_session.flush()
    return sys_row


def test_first_version_is_v1(db_session) -> None:
    s = _make_system(db_session)
    v = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition={"nodes": [{"id": "a", "kind": "task"}], "edges": []},
        created_by="alice",
    )
    assert v is not None
    assert v.version_number == 1
    assert v.created_by == "alice"
    assert v.workspace_id == "ws-1"


def test_incremental_versioning(db_session) -> None:
    s = _make_system(db_session)
    for i in range(3):
        version_service.record_new_version(
            db=db_session,
            system=s,
            flow_definition={"nodes": [{"id": f"n{i}", "kind": "task"}], "edges": []},
            created_by="alice",
        )
    rows, total = version_service.list_versions(
        db=db_session, system_id=s.id, workspace_id="ws-1"
    )
    assert total == 3
    numbers = [r.version_number for r in rows]
    # list_versions returns latest first
    assert numbers == [3, 2, 1]


def test_identical_flow_is_noop(db_session) -> None:
    s = _make_system(db_session)
    flow = {"nodes": [{"id": "a", "kind": "task"}], "edges": []}
    v1 = version_service.record_new_version(
        db=db_session, system=s, flow_definition=flow, created_by="alice"
    )
    v2 = version_service.record_new_version(
        db=db_session, system=s, flow_definition=flow, created_by="alice"
    )
    assert v1 is not None
    assert v2 is None, "Identical flow_definition should not create a new version"
    _, total = version_service.list_versions(
        db=db_session, system_id=s.id, workspace_id="ws-1"
    )
    assert total == 1


def test_identical_flow_with_different_key_order_is_noop(db_session) -> None:
    """JSON equality is structural — reordering keys doesn't fork a
    version. Otherwise every Drawflow re-export would balloon history.
    """
    s = _make_system(db_session)
    v1 = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition={"nodes": [], "edges": [], "schema_version": 2},
        created_by="alice",
    )
    v2 = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition={"schema_version": 2, "edges": [], "nodes": []},
        created_by="alice",
    )
    assert v1 is not None
    assert v2 is None


def test_rolling_window_purges_fifo(db_session, monkeypatch) -> None:
    """Shrink the window to 3 and confirm the 4th save purges v1."""
    monkeypatch.setattr(settings, "custom_chain_version_window", 3)
    s = _make_system(db_session)
    created = []
    for i in range(5):
        v = version_service.record_new_version(
            db=db_session,
            system=s,
            flow_definition={"nodes": [{"id": f"n{i}", "kind": "task"}], "edges": []},
            created_by="alice",
        )
        created.append(v)

    rows, total = version_service.list_versions(
        db=db_session, system_id=s.id, workspace_id="ws-1"
    )
    assert total == 3
    numbers = sorted([r.version_number for r in rows])
    # The 3 survivors are v3, v4, v5 (v1 and v2 purged).
    assert numbers == [3, 4, 5]

    # Audit trail captured the purge.
    purge_events = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "chain.version.purged")
        .all()
    )
    assert len(purge_events) == 2, f"Expected 2 purge events, got {len(purge_events)}"


def test_rollback_creates_new_version_with_target_flow(db_session) -> None:
    s = _make_system(db_session)
    flow_v1 = {"nodes": [{"id": "a", "kind": "task"}], "edges": []}
    flow_v2 = {"nodes": [{"id": "b", "kind": "task"}], "edges": []}
    flow_v3 = {"nodes": [{"id": "c", "kind": "task"}], "edges": []}

    version_service.record_new_version(
        db=db_session, system=s, flow_definition=flow_v1, created_by="alice"
    )
    version_service.record_new_version(
        db=db_session, system=s, flow_definition=flow_v2, created_by="bob"
    )
    version_service.record_new_version(
        db=db_session, system=s, flow_definition=flow_v3, created_by="carol"
    )

    new = version_service.rollback_to_version(
        db=db_session,
        system=s,
        version_number=1,
        created_by="dave",
        message="rollback to start",
    )

    assert new.version_number == 4
    assert new.flow_definition == flow_v1
    assert new.rolled_back_from_id is not None
    assert new.message == "rollback to start"
    # System row is updated in place so the engine sees the rollback.
    assert s.flow_definition == flow_v1

    rb_events = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "chain.rollback")
        .all()
    )
    assert len(rb_events) == 1
    details = rb_events[0].details or {}
    assert details.get("target_version_number") == 1
    assert details.get("no_op") is False


def test_rollback_to_missing_version_raises(db_session) -> None:
    s = _make_system(db_session)
    version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition={"nodes": [{"id": "a"}], "edges": []},
        created_by="alice",
    )
    with pytest.raises(version_service.ChainVersionError):
        version_service.rollback_to_version(
            db=db_session, system=s, version_number=99, created_by="alice"
        )


def test_rollback_to_current_is_noop(db_session) -> None:
    s = _make_system(db_session)
    flow = {"nodes": [{"id": "a", "kind": "task"}], "edges": []}
    version_service.record_new_version(
        db=db_session, system=s, flow_definition=flow, created_by="alice"
    )

    target = version_service.rollback_to_version(
        db=db_session, system=s, version_number=1, created_by="alice"
    )

    # No-op rollback returns the target version itself, no new row.
    assert target.version_number == 1
    _, total = version_service.list_versions(
        db=db_session, system_id=s.id, workspace_id="ws-1"
    )
    assert total == 1

    rb_events = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "chain.rollback")
        .all()
    )
    assert len(rb_events) == 1
    assert (rb_events[0].details or {}).get("no_op") is True


def test_workspace_isolation_on_list(db_session) -> None:
    s_a = _make_system(db_session, workspace_id="ws-A")
    version_service.record_new_version(
        db=db_session,
        system=s_a,
        flow_definition={"nodes": [{"id": "a"}], "edges": []},
        created_by="alice",
    )
    # Same-id query but from a different workspace must see nothing.
    rows, total = version_service.list_versions(
        db=db_session, system_id=s_a.id, workspace_id="ws-OTHER"
    )
    assert rows == []
    assert total == 0


def test_serialize_version_summary_drops_flow_definition(db_session) -> None:
    s = _make_system(db_session)
    v = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition={
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b"}],
        },
        created_by="alice",
    )
    summary = version_service.serialize_version_summary(v)
    assert "flow_definition" not in summary
    assert summary["node_count"] == 2
    assert summary["edge_count"] == 1
    full = version_service.serialize_version(v)
    assert "flow_definition" in full
