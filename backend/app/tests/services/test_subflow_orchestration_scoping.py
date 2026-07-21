"""Workspace, delegation-key and wave isolation for durable subflows."""

from uuid import uuid4

from app.models.run import Run
from app.services.run_engine.subflow_orchestration import (
    _refresh_entries,
    cancel_waiting_children,
)


def _entry(child: Run, *, wave_id: int, status: str = "running") -> dict:
    return {
        "child_run_id": child.id,
        "node_id": child.delegation_node_id,
        "branch": child.delegation_branch,
        "status": status,
        "wave_id": wave_id,
    }


def test_refresh_is_scoped_and_leaves_historical_wave_untouched(db_session):
    workspace_id = str(uuid4())
    parent = Run(
        id=str(uuid4()), workspace_id=workspace_id, status="waiting_subflows"
    )
    active = Run(
        id=str(uuid4()), workspace_id=workspace_id, parent_run_id=parent.id,
        delegation_key="a" * 64, delegation_node_id="active", delegation_branch="main",
        status="completed",
    )
    historical = Run(
        id=str(uuid4()), workspace_id=workspace_id, parent_run_id=parent.id,
        delegation_key="b" * 64, delegation_node_id="old", delegation_branch="main",
        status="completed",
    )
    foreign = Run(
        id=str(uuid4()), workspace_id=str(uuid4()), parent_run_id=parent.id,
        delegation_key="c" * 64, delegation_node_id="foreign", delegation_branch="main",
        status="completed",
    )
    db_session.add_all([parent, active, historical, foreign])
    db_session.commit()
    waiting = {
        "_meta": {"strategy": "all", "wave_id": 2},
        active.delegation_key: _entry(active, wave_id=2),
        historical.delegation_key: _entry(historical, wave_id=1),
        foreign.delegation_key: _entry(foreign, wave_id=2),
    }

    refreshed = _refresh_entries(db_session, parent, waiting)

    assert refreshed[active.delegation_key]["status"] == "completed"
    assert refreshed[historical.delegation_key]["status"] == "running"
    assert refreshed[foreign.delegation_key]["status"] == "failed"
    assert refreshed[foreign.delegation_key]["error"] == "delegated_child_missing"
    db_session.refresh(foreign)
    assert foreign.status == "completed"


def test_parent_cancellation_recurses_three_levels_in_active_waves(db_session):
    workspace_id = str(uuid4())
    root = Run(id=str(uuid4()), workspace_id=workspace_id, status="cancelled")
    child = Run(
        id=str(uuid4()), workspace_id=workspace_id, parent_run_id=root.id,
        delegation_key="1" * 64, delegation_node_id="level-1", delegation_branch="main",
        status="running",
    )
    grandchild = Run(
        id=str(uuid4()), workspace_id=workspace_id, parent_run_id=child.id,
        delegation_key="2" * 64, delegation_node_id="level-2", delegation_branch="main",
        status="running",
    )
    leaf = Run(
        id=str(uuid4()), workspace_id=workspace_id, parent_run_id=grandchild.id,
        delegation_key="3" * 64, delegation_node_id="level-3", delegation_branch="main",
        status="running",
    )
    historical = Run(
        id=str(uuid4()), workspace_id=workspace_id, parent_run_id=root.id,
        delegation_key="4" * 64, delegation_node_id="historical", delegation_branch="main",
        status="running",
    )
    root.waiting_subflows = {
        "_meta": {"strategy": "all", "wave_id": 2},
        child.delegation_key: _entry(child, wave_id=2),
        historical.delegation_key: _entry(historical, wave_id=1),
    }
    child.waiting_subflows = {
        "_meta": {"strategy": "all", "wave_id": 7},
        grandchild.delegation_key: _entry(grandchild, wave_id=7),
    }
    grandchild.waiting_subflows = {
        "_meta": {"strategy": "all", "wave_id": 9},
        leaf.delegation_key: _entry(leaf, wave_id=9),
    }
    db_session.add_all([root, child, grandchild, leaf, historical])
    db_session.commit()

    assert cancel_waiting_children(root.id, reason="root_cancelled") == 3

    db_session.expire_all()
    for delegated in (child, grandchild, leaf):
        refreshed = db_session.query(Run).filter(Run.id == delegated.id).one()
        assert refreshed.status == "cancelled"
        assert refreshed.error == "root_cancelled"
    untouched = db_session.query(Run).filter(Run.id == historical.id).one()
    assert untouched.status == "running"
    refreshed_root = db_session.query(Run).filter(Run.id == root.id).one()
    assert refreshed_root.waiting_subflows[child.delegation_key]["status"] == "cancelled"
    refreshed_child = db_session.query(Run).filter(Run.id == child.id).one()
    assert refreshed_child.waiting_subflows[grandchild.delegation_key]["status"] == "cancelled"
    refreshed_grandchild = db_session.query(Run).filter(Run.id == grandchild.id).one()
    assert refreshed_grandchild.waiting_subflows[leaf.delegation_key]["status"] == "cancelled"
