"""Regressions for making publication the default Flow authority."""

from __future__ import annotations

import contextlib
import uuid

import pytest

from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.workspace import Workspace
from app.services.systems import flow_publication

FLOW = {
    "schema_version": 3,
    "nodes": [
        {"id": "src", "kind": "source", "type": "source.schedule"},
        {"id": "snk", "kind": "sink"},
    ],
    "edges": [{"from": "src", "to": "snk", "kind": "control"}],
}


def _workspace(db) -> Workspace:
    row = Workspace(
        id=str(uuid.uuid4()),
        name="Posture",
        slug=f"posture-{uuid.uuid4().hex[:8]}",
    )
    db.add(row)
    db.commit()
    return row


def _system_without_draft(db, workspace: Workspace) -> System:
    """A row shaped like one created while the workspace had publication off."""

    row = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Legacy row",
        objective="test",
        flow_definition=FLOW,
        status="active",
    )
    db.add(row)
    db.commit()
    return row


def test_publication_error_survives_a_context_manager():
    # ``__exit__`` assigns ``__traceback__`` as the exception propagates, which a
    # frozen dataclass turned into an unrelated TypeError that hid the real code.
    @contextlib.contextmanager
    def scope():
        yield

    with pytest.raises(flow_publication.FlowPublicationError) as caught:
        with scope():
            raise flow_publication.FlowPublicationError(code="X", message="m")

    assert caught.value.code == "X"


def test_reconcile_initializes_a_system_that_never_had_a_draft(db_session):
    workspace = _workspace(db_session)
    system = _system_without_draft(db_session, workspace)
    assert flow_publication.flow_publication_enabled(workspace)

    result = flow_publication.reconcile_system_flow(
        db_session,
        system=system,
        workspace=workspace,
        flow_definition=FLOW,
        actor="test:reconcile",
    )
    db_session.commit()

    assert result.status != "legacy_no_op"
    draft = (
        db_session.query(SystemFlowDraft)
        .filter(SystemFlowDraft.system_id == system.id)
        .one()
    )
    assert draft.revision >= 1
    db_session.refresh(system)
    assert system.published_flow_version_id


def test_initializing_publication_state_is_idempotent(db_session):
    workspace = _workspace(db_session)
    system = _system_without_draft(db_session, workspace)

    first_draft, first_version = flow_publication.initialize_publication_state(
        db_session, system=system, workspace=workspace, actor="test:init"
    )
    db_session.commit()
    second_draft, second_version = flow_publication.initialize_publication_state(
        db_session, system=system, workspace=workspace, actor="test:init"
    )
    db_session.commit()

    assert second_draft.system_id == first_draft.system_id
    assert second_version.id == first_version.id
    assert second_draft.revision == first_draft.revision
