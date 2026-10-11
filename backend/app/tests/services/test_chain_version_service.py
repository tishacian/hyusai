"""Tests for ``services.chains.version_service`` — rolling window,
rollback semantics, and audit trail.

Uses the session-scoped SQLite fixture from ``conftest.py``. Each test
truncates through the global fixture so rows from prior tests don't
leak across the FIFO purge assertion.
"""
from __future__ import annotations

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chains import version_service

POLICY_SOURCE_ID = "00000000-0000-4000-8000-000000000001"
POLICY_SHADOW_1_ID = "00000000-0000-4000-8000-000000000002"
POLICY_SHADOW_2_ID = "00000000-0000-4000-8000-000000000003"


def _configuration_snapshot(
    policy_id: str,
    *,
    previous_policy_id: str = POLICY_SOURCE_ID,
) -> dict:
    return {
        "schema_version": 1,
        "bindings": {"control_policy_id": policy_id},
        "transition": {
            "kind": "control_policy_rebind",
            "previous_control_policy_id": previous_policy_id,
            "enforcement_mode": "shadow",
            "source_contract_sha256": "a" * 64,
            "target_contract_sha256": "b" * 64,
        },
    }


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


def test_system_version_number_is_a_database_invariant() -> None:
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in version_service.SystemVersion.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert constraints["uq_system_versions_system_version_number"] == (
        "system_id",
        "version_number",
    )


def test_parent_system_lock_targets_only_system_table(db_session, monkeypatch) -> None:
    system = _make_system(db_session)
    real_query = db_session.query
    observed: dict[str, object] = {}

    class _LockQuery:
        def filter(self, *_criteria):
            return self

        def populate_existing(self):
            observed["populate_existing"] = True
            return self

        def with_for_update(self, **kwargs):
            observed.update(kwargs)
            return self

        def one_or_none(self):
            return system

    def _query(entity):
        if entity is System:
            return _LockQuery()
        return real_query(entity)

    monkeypatch.setattr(db_session, "query", _query)

    assert version_service._lock_system_for_versioning(db_session, system.id) is system
    assert observed == {"populate_existing": True, "of": System}


def test_parent_lock_compiles_to_postgresql_for_update_of_systems(db_session) -> None:
    statement = (
        db_session.query(System)
        .filter(System.id == "system-lock-contract")
        .with_for_update(of=System)
        .statement
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert sql.rstrip().endswith("FOR UPDATE OF systems")


def test_record_new_version_fails_if_parent_disappeared(db_session) -> None:
    missing = System(
        id="system-deleted-before-version-append",
        workspace_id="ws-1",
        name="gone",
        objective="",
        flow_definition={},
    )

    with pytest.raises(
        version_service.ChainVersionError,
        match="no longer exists",
    ):
        version_service.record_new_version(
            db=db_session,
            system=missing,
            flow_definition={"nodes": [], "edges": []},
            created_by="alice",
        )


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


def test_identical_flow_with_different_explicit_configuration_appends(db_session) -> None:
    s = _make_system(db_session)
    flow = {"nodes": [{"id": "a", "kind": "task"}], "edges": []}
    first_snapshot = _configuration_snapshot(POLICY_SHADOW_1_ID)
    second_snapshot = _configuration_snapshot(POLICY_SHADOW_2_ID)

    first = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition=flow,
        configuration_snapshot=first_snapshot,
        created_by="rollout",
    )
    second = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition=flow,
        configuration_snapshot=second_snapshot,
        created_by="rollout",
    )
    repeated = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition=flow,
        configuration_snapshot=second_snapshot,
        created_by="rollout",
    )

    assert first is not None
    assert second is not None
    assert second.version_number == 2
    assert second.flow_definition == first.flow_definition
    assert second.configuration_snapshot == second_snapshot
    assert repeated is None


def test_legacy_identical_flow_remains_noop_after_configuration_version(db_session) -> None:
    """Omitting the new argument preserves the pre-065 flow-only contract."""

    s = _make_system(db_session)
    flow = {"nodes": [{"id": "a", "kind": "task"}], "edges": []}
    configured = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition=flow,
        configuration_snapshot=_configuration_snapshot(POLICY_SHADOW_1_ID),
        created_by="rollout",
    )
    legacy = version_service.record_new_version(
        db=db_session,
        system=s,
        flow_definition=flow,
        created_by="editor",
    )

    assert configured is not None
    assert legacy is None
    assert db_session.query(type(configured)).filter_by(system_id=s.id).count() == 1


def test_configuration_snapshot_rejects_non_allowlisted_secret_bearing_fields(
    db_session,
) -> None:
    s = _make_system(db_session)
    snapshot = _configuration_snapshot(POLICY_SHADOW_1_ID)
    snapshot["policy_body"] = {"api_key": "must-never-be-persisted"}

    with pytest.raises(
        version_service.ConfigurationSnapshotError,
        match="unsupported configuration_snapshot fields",
    ):
        version_service.record_new_version(
            db=db_session,
            system=s,
            flow_definition={"nodes": [], "edges": []},
            configuration_snapshot=snapshot,
            created_by="rollout",
        )

    _, total = version_service.list_versions(
        db=db_session,
        system_id=s.id,
        workspace_id=s.workspace_id,
    )
    assert total == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("control_policy_id", "Bearer super-secret-token"),
        ("control_policy_id", "00000000-0000-4000-8000-000000000002 "),
        ("previous_control_policy_id", "user:password@example.test"),
    ),
)
def test_configuration_snapshot_rejects_non_canonical_or_secret_like_references(
    db_session,
    field,
    value,
) -> None:
    system = _make_system(db_session)
    snapshot = _configuration_snapshot(POLICY_SHADOW_1_ID)
    if field == "previous_control_policy_id":
        snapshot["transition"][field] = value
    else:
        snapshot["bindings"][field] = value

    with pytest.raises(
        version_service.ConfigurationSnapshotError,
        match="canonical UUID reference",
    ):
        version_service.record_new_version(
            db=db_session,
            system=system,
            flow_definition={"nodes": [], "edges": []},
            configuration_snapshot=snapshot,
            created_by="rollout",
        )


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


def test_append_only_caller_can_disable_fifo_purge(db_session, monkeypatch) -> None:
    """Backfills and staged rollouts must never delete historical versions."""
    monkeypatch.setattr(settings, "custom_chain_version_window", 1)
    system = _make_system(db_session)

    for index in range(3):
        version_service.record_new_version(
            db=db_session,
            system=system,
            flow_definition={"nodes": [{"id": f"n{index}"}], "edges": []},
            created_by="migration",
            purge=False,
        )

    rows, total = version_service.list_versions(
        db=db_session,
        system_id=system.id,
        workspace_id=system.workspace_id,
    )
    assert total == 3
    assert [row.version_number for row in rows] == [3, 2, 1]
    assert db_session.query(AuditLog).filter_by(event_type="chain.version.purged").count() == 0


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


def test_legacy_rollback_service_is_blocked_when_publication_is_enabled(
    db_session,
) -> None:
    workspace = Workspace(
        id="ws-publication-rollback-guard",
        name="Publication rollback guard",
        slug="publication-rollback-guard",
        settings={"features": {"flow_publication_v1": True}},
    )
    db_session.add(workspace)
    system = _make_system(
        db_session,
        workspace_id=workspace.id,
        flow={"nodes": [{"id": "current"}], "edges": []},
    )
    version_service.record_new_version(
        db=db_session,
        system=system,
        flow_definition={"nodes": [{"id": "target"}], "edges": []},
        created_by="alice",
    )

    with pytest.raises(
        version_service.ChainVersionError,
        match="Legacy rollback is disabled",
    ):
        version_service.rollback_to_version(
            db=db_session,
            system=system,
            version_number=1,
            created_by="alice",
        )

    assert system.flow_definition == {"nodes": [{"id": "current"}], "edges": []}
    assert (
        db_session.query(version_service.SystemVersion)
        .filter_by(system_id=system.id)
        .count()
        == 1
    )


def test_rollback_repairs_system_drift_even_when_target_is_latest(db_session) -> None:
    s = _make_system(db_session)
    flow = {"nodes": [{"id": "a", "kind": "task"}], "edges": []}
    version_service.record_new_version(
        db=db_session, system=s, flow_definition=flow, created_by="alice"
    )

    target = version_service.rollback_to_version(
        db=db_session, system=s, version_number=1, created_by="alice"
    )

    assert target.version_number == 2
    assert s.flow_definition == flow
    _, total = version_service.list_versions(
        db=db_session, system_id=s.id, workspace_id="ws-1"
    )
    assert total == 2

    rb_events = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "chain.rollback")
        .all()
    )
    assert len(rb_events) == 1
    assert (rb_events[0].details or {}).get("no_op") is False


def test_rollback_to_authoritative_current_is_noop(db_session) -> None:
    flow = {"nodes": [{"id": "a", "kind": "task"}], "edges": []}
    s = _make_system(db_session, flow=flow)
    version_service.record_new_version(
        db=db_session, system=s, flow_definition=flow, created_by="alice"
    )

    target = version_service.rollback_to_version(
        db=db_session, system=s, version_number=1, created_by="alice"
    )

    assert target.version_number == 1
    _, total = version_service.list_versions(
        db=db_session, system_id=s.id, workspace_id="ws-1"
    )
    assert total == 1
    event = db_session.query(AuditLog).filter_by(event_type="chain.rollback").one()
    assert (event.details or {}).get("no_op") is True


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
    assert "configuration_snapshot" in full
    assert full["configuration_snapshot"] is None
