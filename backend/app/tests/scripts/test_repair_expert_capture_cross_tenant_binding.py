from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.expert_capture import ExpertCaptureEvent, ExpertCaptureSession
from app.models.system import System
from app.models.workspace import Workspace
from scripts.repair_expert_capture_cross_tenant_binding import (
    RepairRefused,
    repair_cross_tenant_binding,
)


def _workspace(db, slug: str) -> Workspace:
    row = Workspace(id=str(uuid4()), name=slug, slug=slug, settings={})
    db.add(row)
    db.flush()
    return row


def _drifting_session(db) -> tuple[ExpertCaptureSession, System, Workspace]:
    test_workspace = _workspace(db, "test")
    andritz = _workspace(db, "andritz")
    system = System(
        id=str(uuid4()),
        workspace_id=andritz.id,
        name="Andritz system",
        status="active",
    )
    session = ExpertCaptureSession(
        id=str(uuid4()),
        workspace_id=test_workspace.id,
        capability_id=str(uuid4()),
        system_id=system.id,
        run_id=str(uuid4()),
        context_id=str(uuid4()),
        objective="objective",
        status="planned",
    )
    db.add_all([system, session])
    db.flush()
    for sequence in range(5):
        db.add(
            ExpertCaptureEvent(
                id=str(uuid4()),
                workspace_id=test_workspace.id,
                session_id=session.id,
                event_type="note",
                sequence=sequence,
            )
        )
    db.commit()
    return session, system, test_workspace


def test_plan_reports_drift_without_mutating(db_session) -> None:
    session, system, _ = _drifting_session(db_session)

    receipt = repair_cross_tenant_binding(
        db_session,
        session_id=session.id,
        expected_workspace_slug="test",
        expected_system_id=system.id,
        expected_capability_id=session.capability_id,
        apply=False,
    )

    assert receipt["result"] == "planned"
    assert receipt["cross_tenant_mismatch_count_before"] == 1
    assert receipt["event_count"] == 5
    assert receipt["proposal_count"] == 0
    reloaded = db_session.get(ExpertCaptureSession, session.id)
    assert reloaded.system_id == system.id
    assert reloaded.capability_id is not None


def test_apply_clears_exactly_the_two_bindings(db_session) -> None:
    session, system, _ = _drifting_session(db_session)
    run_id, context_id = session.run_id, session.context_id

    receipt = repair_cross_tenant_binding(
        db_session,
        session_id=session.id,
        expected_workspace_slug="test",
        expected_system_id=system.id,
        expected_capability_id=session.capability_id,
        apply=True,
    )

    assert receipt["result"] == "applied"
    assert receipt["cross_tenant_mismatch_count_after"] == 0
    reloaded = db_session.get(ExpertCaptureSession, session.id)
    assert reloaded.system_id is None
    assert reloaded.capability_id is None
    assert reloaded.run_id == run_id
    assert reloaded.context_id == context_id
    assert reloaded.status == "planned"
    assert len(reloaded.events) == 5
    assert db_session.get(System, system.id) is not None


@pytest.mark.parametrize(
    "override",
    [
        {"expected_workspace_slug": "andritz"},
        {"expected_system_id": "other-system"},
        {"expected_capability_id": "other-capability"},
        {"session_id": "missing-session"},
    ],
)
def test_identity_mismatch_refuses_without_mutation(db_session, override) -> None:
    session, system, _ = _drifting_session(db_session)
    arguments = {
        "session_id": session.id,
        "expected_workspace_slug": "test",
        "expected_system_id": system.id,
        "expected_capability_id": session.capability_id,
    }
    arguments.update(override)

    with pytest.raises(RepairRefused):
        repair_cross_tenant_binding(db_session, apply=True, **arguments)

    db_session.rollback()
    reloaded = db_session.get(ExpertCaptureSession, session.id)
    assert reloaded.system_id == system.id
    assert reloaded.capability_id is not None


def test_same_workspace_binding_is_refused(db_session) -> None:
    workspace = _workspace(db_session, "test")
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Local system",
        status="active",
    )
    session = ExpertCaptureSession(
        id=str(uuid4()),
        workspace_id=workspace.id,
        capability_id=str(uuid4()),
        system_id=system.id,
        objective="objective",
        status="planned",
    )
    db_session.add_all([system, session])
    db_session.commit()

    with pytest.raises(RepairRefused, match="not cross-tenant"):
        repair_cross_tenant_binding(
            db_session,
            session_id=session.id,
            expected_workspace_slug="test",
            expected_system_id=system.id,
            expected_capability_id=session.capability_id,
            apply=True,
        )
