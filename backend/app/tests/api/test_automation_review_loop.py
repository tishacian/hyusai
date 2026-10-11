"""F3: reservation, reread correction and comparison on a BRD System.

SPARK-089 summary is a System generated from a BRD. Its extraction, passage and
synthesis blocks are not in the automation palette, and the reread used to stop
there with ``block_refused``. The loop only reads the draft, so it now reads
every block; the palette still bounds what an automation turn may edit.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import automation_edit as endpoint
from app.models.capability import Capability
from app.models.run import Run
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.user import User
from app.models.workspace import Workspace
from app.services import automation_edit
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.tests.iam_baseline import OPEN_IAM_FEATURES

NOTE = "The proposed grade is still missing."


def _brd_flow(instruction: str) -> dict:
    """The shape of the PIH BRD System: extract, select passages, synthesize, review."""
    return {
        "nodes": [
            {"id": "src_pih", "type": "source", "kind": "source"},
            {
                "id": "t_extract",
                "type": "task",
                "kind": "task",
                "config": {"skill_slug": "@extract_facts"},
            },
            {
                "id": "t_passage",
                "type": "task",
                "kind": "task",
                "config": {"skill_slug": "@select_passages"},
            },
            {
                "id": "t_synth",
                "type": "task",
                "kind": "task",
                "config": {
                    "skill_slug": "@synthesize_summary",
                    "params": {"instruction": instruction},
                },
            },
            {"id": "h_review", "type": "hitl", "kind": "hitl"},
            {"id": "sink_out", "type": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src_pih", "to": "t_extract"},
            {"from": "t_extract", "to": "t_passage"},
            {"from": "t_passage", "to": "t_synth"},
            {"from": "t_synth", "to": "h_review"},
            {"from": "h_review", "to": "sink_out"},
        ],
    }


FIRST = _brd_flow("Summarize titles and current grades.")
CORRECTED = _brd_flow("Summarize titles, current grades and proposed grades.")


@pytest.fixture
def spark(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"f3-{uuid4().hex[:8]}",
        name="F3",
        settings={"features": dict(OPEN_IAM_FEATURES)},
    )
    capability = Capability(
        id=str(uuid4()), workspace_id=workspace.id, slug=f"f3-{uuid4().hex[:8]}", name="PIH"
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="SPARK-089 summary",
        objective="PIH summary",
        status="draft",
        flow_definition=copy.deepcopy(FIRST),
    )
    user = User(id=str(uuid4()), username=f"reviewer-{uuid4().hex[:8]}", email="r@example.test")
    draft = SystemFlowDraft(
        system_id=system.id,
        workspace_id=workspace.id,
        flow_definition=copy.deepcopy(FIRST),
        flow_sha256=canonical_flow_sha256(FIRST),
        updated_by="test",
    )
    db_session.add_all([workspace, capability, system, user])
    db_session.flush()
    db_session.add(draft)
    db_session.commit()
    return workspace, system, user, draft


def _run(db_session, workspace, system, *, flow, started_at, status="completed"):
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=system.capability_id,
        status=status,
        started_at=started_at,
        flow_sha256=canonical_flow_sha256(flow),
    )
    db_session.add(run)
    db_session.commit()
    return run


def _code(exc: pytest.ExceptionInfo) -> str:
    return exc.value.detail["code"]


@pytest.mark.asyncio
async def test_a_brd_system_goes_from_reservation_to_a_compared_correction(db_session, spark):
    workspace, system, user, draft = spark
    now = datetime.utcnow()
    earlier = _run(db_session, workspace, system, flow=FIRST, started_at=now - timedelta(hours=2))
    reserved = _run(db_session, workspace, system, flow=FIRST, started_at=now - timedelta(hours=1))
    auth = {"workspace": workspace, "user": user, "db": db_session}

    row = await endpoint.automation_review_reserve(
        system.id, endpoint.ReservationBody(run_id=reserved.id, note=NOTE), **auth
    )
    assert row["status"] == "reserved" and row["run_id"] == reserved.id

    seen = await endpoint.automation_review_reread(system.id, row["id"], **auth)
    assert [node["type"] for node in seen["nodes"]] == [
        "trigger",
        "extract_facts",
        "select_passages",
        "synthesize_summary",
        "approval",
        "output",
    ]
    assert [node["editable"] for node in seen["nodes"]] == [True, False, False, False, True, True]
    assert seen["draft_hash"] == canonical_flow_sha256(FIRST)

    # Nothing was corrected yet: the draft is the graph the reserved result ran.
    with pytest.raises(HTTPException) as unchanged:
        await endpoint.automation_review_confirm(
            system.id, row["id"], endpoint.RereadConfirmBody(draft_hash=seen["draft_hash"]), **auth
        )
    assert _code(unchanged) == "unchanged_draft"

    # The person corrects the synthesis in the Flow canvas; the draft moves.
    draft.flow_definition = copy.deepcopy(CORRECTED)
    draft.flow_sha256 = canonical_flow_sha256(CORRECTED)
    db_session.commit()
    with pytest.raises(HTTPException) as stale:
        await endpoint.automation_review_confirm(
            system.id, row["id"], endpoint.RereadConfirmBody(draft_hash=seen["draft_hash"]), **auth
        )
    assert _code(stale) == "stale_reread"

    reread = await endpoint.automation_review_reread(system.id, row["id"], **auth)
    confirmed = await endpoint.automation_review_confirm(
        system.id, row["id"], endpoint.RereadConfirmBody(draft_hash=reread["draft_hash"]), **auth
    )
    assert confirmed["status"] == "corrected"
    assert confirmed["correction_hash"] == canonical_flow_sha256(CORRECTED)

    with pytest.raises(HTTPException) as before:
        await endpoint.automation_review_compare(
            system.id, row["id"], endpoint.CompareBody(run_id=earlier.id), **auth
        )
    assert _code(before) == "not_later"

    later = _run(db_session, workspace, system, flow=CORRECTED, started_at=now)
    compared = await endpoint.automation_review_compare(
        system.id, row["id"], endpoint.CompareBody(run_id=later.id), **auth
    )
    assert compared["same_object"] is True
    assert compared["later_run_id"] == later.id and compared["later_status"] == "completed"
    assert compared["ran_correction"] is True

    state = await endpoint.automation_review_state(system.id, **auth)
    assert state["review"]["run_id"] == reserved.id
    assert state["review"]["same_object"] is True and state["review"]["ran_correction"] is True


@pytest.mark.asyncio
async def test_a_later_result_of_another_graph_is_compared_but_not_called_the_correction(
    db_session, spark
):
    workspace, system, user, draft = spark
    now = datetime.utcnow()
    reserved = _run(db_session, workspace, system, flow=FIRST, started_at=now - timedelta(hours=1))
    auth = {"workspace": workspace, "user": user, "db": db_session}
    row = await endpoint.automation_review_reserve(
        system.id, endpoint.ReservationBody(run_id=reserved.id, note=NOTE), **auth
    )
    draft.flow_definition = copy.deepcopy(CORRECTED)
    draft.flow_sha256 = canonical_flow_sha256(CORRECTED)
    db_session.commit()
    seen = await endpoint.automation_review_reread(system.id, row["id"], **auth)
    await endpoint.automation_review_confirm(
        system.id, row["id"], endpoint.RereadConfirmBody(draft_hash=seen["draft_hash"]), **auth
    )

    later = _run(db_session, workspace, system, flow=FIRST, started_at=now)
    compared = await endpoint.automation_review_compare(
        system.id, row["id"], endpoint.CompareBody(run_id=later.id), **auth
    )
    assert compared["same_object"] is True and compared["ran_correction"] is False


def test_the_palette_still_refuses_to_edit_the_brd_draft():
    with pytest.raises(automation_edit.AutomationEditRefusal) as refused:
        automation_edit.read_draft(CORRECTED)
    assert refused.value.code == "block_refused"
