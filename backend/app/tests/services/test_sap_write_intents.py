"""One PR item becomes at most one purchase order.

The scheduler opens a new approval gate every tick while an earlier one is
still pending, so two approvals of the same PR item used to send two
BAPI_PO_CREATE1 calls. Each create now claims a ``sap_write_intents`` row keyed
on the item, and only a known failure lets a second approval call SAP.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.models.decision import Decision
from app.models.run import SkillInvocation
from app.models.sap_write_intent import COMMITTED, FAILED, PENDING, UNKNOWN, SapWriteIntent
from app.models.skill import Skill
from app.models.workspace import Workspace
from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp import intents
from app.services.connectors.mcp import read as mcp_read
from app.services.connectors.mcp import service as mcp_service
from app.services.connectors.mcp import write as mcp_write
from app.services.connectors.mcp.errors import McpUnreachable
from app.services.skills_registry import wrappers

PR = "2000276449"
CREATED = {
    "export": {"EXPHEADER": {"PO_NUMBER": "4500999001"}},
    "tables": {"RETURN": [{"TYPE": "S", "MESSAGE": "created"}]},
}
REFUSED = {"tables": {"RETURN": [{"TYPE": "E", "MESSAGE": "Please enter net price"}]}}
CREATE = {
    "pr_id": PR,
    "supplier": "1000000018",
    "pr_type": "ZNPR",
    "pr": {
        "PurchaseRequisition": PR,
        "PurchaseRequisitionItem": "10",
        "Plant": "1000",
        "PurchaseRequisitionPrice": "4.50",
    },
}


@pytest.fixture
def estate(db_session, monkeypatch):
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"nawa-{uuid4().hex[:6]}",
        name="NAWA",
        settings={"features": {"mcp_connector": True, "sap_write_unsealed": True}},
    )
    db_session.add(workspace)
    db_session.commit()
    monkeypatch.setattr(mcp_service, "is_workspace_enabled", lambda _ws: True)
    monkeypatch.setattr(
        mcp_service,
        "resolve_server",
        lambda _ws, server_id: {"id": server_id, "url": "http://mock"},
    )
    events: list[dict] = []
    import app.services.audit_logger as audit_logger

    monkeypatch.setattr(audit_logger, "emit_audit_event", lambda **kwargs: events.append(kwargs))
    return workspace, events


def _transport(monkeypatch, replies):
    calls: list[tuple[str, dict]] = []

    def call_tool(server, *, contract_tool, arguments, timeout_s=None):
        calls.append((contract_tool, arguments))
        reply = replies.get(contract_tool, {"tables": {"RETURN": []}})
        if isinstance(reply, list):
            reply = reply.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"ok": True, "result": reply, "server_id": server["id"], "tool": contract_tool}

    monkeypatch.setattr(mcp_client, "call_tool", call_tool)
    return calls


def _approved_run(db_session, workspace, run_id):
    db_session.add(
        Decision(
            id=str(uuid4()),
            workspace_id=workspace.id,
            scope="run",
            target_id=run_id,
            kind="hitl_approval",
            status="accepted",
            title="Approve PO",
            approved_by="buyer@nawa.test",
            approved_at=datetime.utcnow(),
            human_confirmed_by="user-buyer",
        )
    )
    db_session.commit()
    return {"db": db_session, "workspace_id": workspace.id, "run_id": run_id}


async def _create(db_session, workspace, run_id):
    ctx = _approved_run(db_session, workspace, run_id)
    return await wrappers._sap_create_po_v1({**CREATE, "decided_by": "buyer@nawa.test"}, ctx)


def _intent(db_session, workspace):
    return (
        db_session.query(SapWriteIntent).filter(SapWriteIntent.workspace_id == workspace.id).one()
    )


def _creates(calls):
    return [tool for tool, _args in calls if tool == mcp_write.BAPI_CREATE]


# --- one PR item, one PO ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_approval_of_the_same_item_does_not_create_a_second_po(
    db_session, monkeypatch, estate
):
    workspace, events = estate
    calls = _transport(monkeypatch, {mcp_write.BAPI_CREATE: CREATED})
    first = await _create(db_session, workspace, "run-1")
    assert first["committed"] is True and first["po_number"] == "4500999001"

    second = await _create(db_session, workspace, "run-2")
    assert second["called"] is False and second["reason"] == intents.ALREADY_ORDERED
    assert second["po_number"] == "4500999001"
    assert _creates(calls) == [mcp_write.BAPI_CREATE]
    intent = _intent(db_session, workspace)
    assert intent.status == COMMITTED and intent.run_id == "run-1"
    assert any(event["event_type"] == "mcp.write.refused" for event in events)


@pytest.mark.asyncio
async def test_a_known_failure_lets_the_next_approval_try_again(db_session, monkeypatch, estate):
    workspace, _events = estate
    calls = _transport(monkeypatch, {mcp_write.BAPI_CREATE: [REFUSED, CREATED]})
    failed = await _create(db_session, workspace, "run-1")
    assert failed["sap_ok"] is False and _intent(db_session, workspace).status == FAILED

    retried = await _create(db_session, workspace, "run-2")
    assert retried["committed"] is True
    intent = _intent(db_session, workspace)
    assert intent.status == COMMITTED and intent.attempts == 2 and intent.run_id == "run-2"
    assert _creates(calls) == [mcp_write.BAPI_CREATE, mcp_write.BAPI_CREATE]


@pytest.mark.asyncio
async def test_an_unknown_outcome_blocks_every_later_approval(db_session, monkeypatch, estate):
    workspace, _events = estate
    calls = _transport(
        monkeypatch,
        {mcp_write.BAPI_CREATE: CREATED, mcp_write.BAPI_COMMIT: McpUnreachable("timed out")},
    )
    unsure = await _create(db_session, workspace, "run-1")
    assert unsure["outcome"] == "unknown" and unsure["needs_reconciliation"] is True
    intent = _intent(db_session, workspace)
    assert intent.status == UNKNOWN and intent.po_number == "4500999001"

    blocked = await _create(db_session, workspace, "run-2")
    assert blocked["reason"] == intents.NEEDS_RECONCILIATION and blocked["called"] is False
    assert _creates(calls) == [mcp_write.BAPI_CREATE]


@pytest.mark.asyncio
async def test_a_claim_in_flight_refuses_and_a_stale_one_becomes_unknown(
    db_session, monkeypatch, estate
):
    workspace, _events = estate
    calls = _transport(monkeypatch, {mcp_write.BAPI_CREATE: CREATED})
    db_session.add(
        SapWriteIntent(
            workspace_id=workspace.id,
            pr_id=PR,
            pr_item="10",
            status=PENDING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    db_session.commit()
    in_flight = await _create(db_session, workspace, "run-2")
    assert in_flight["reason"] == intents.WRITE_IN_PROGRESS

    intent = _intent(db_session, workspace)
    intent.updated_at = datetime.utcnow() - timedelta(hours=1)
    db_session.commit()
    stale = await _create(db_session, workspace, "run-3")
    assert stale["reason"] == intents.NEEDS_RECONCILIATION
    assert _intent(db_session, workspace).status == UNKNOWN
    assert _creates(calls) == []


def test_pr_items_are_one_key_however_sap_pads_them():
    assert intents.normalize_item("10") == intents.normalize_item("00010") == "10"


# --- the operator resolves what SAP left unknown -------------------------------


@pytest.mark.asyncio
async def test_an_operator_resolution_decides_what_happens_next(db_session, monkeypatch, estate):
    workspace, _events = estate
    _transport(monkeypatch, {mcp_write.BAPI_CREATE: McpUnreachable("timed out")})
    await _create(db_session, workspace, "run-1")
    intent = _intent(db_session, workspace)
    assert intent.status == UNKNOWN

    with pytest.raises(ValueError):
        intents.resolve(db_session, intent, status=COMMITTED, actor="ops@example.test")
    intents.resolve(db_session, intent, status=FAILED, actor="ops@example.test")
    _transport(monkeypatch, {mcp_write.BAPI_CREATE: CREATED})
    retried = await _create(db_session, workspace, "run-2")
    assert retried["committed"] is True


# --- with the reconciliation flag: SAP is read first -----------------------------


def _reconciling(db_session, workspace):
    workspace.settings = {
        "features": {
            "mcp_connector": True,
            "sap_write_unsealed": True,
            "sap_po_reconciliation": True,
        }
    }
    db_session.commit()


def _pr_item(purchasing_document="", item="10"):
    """What SAP answers to a keyed read of the PR item."""
    return {
        "d": {
            "PurchaseRequisition": PR,
            "PurchaseRequisitionItem": item,
            "PurchasingDocument": purchasing_document,
        }
    }


def _reads(calls):
    return [args for tool, args in calls if tool == mcp_read.LIVE_PR_ITEM_BY_KEY]


@pytest.mark.asyncio
async def test_with_the_flag_an_existing_sap_po_is_recorded_and_refused(
    db_session, monkeypatch, estate
):
    workspace, _events = estate
    _reconciling(db_session, workspace)
    calls = _transport(
        monkeypatch,
        {mcp_read.LIVE_PR_ITEM_BY_KEY: _pr_item("4500111222"), mcp_write.BAPI_CREATE: CREATED},
    )
    refused = await _create(db_session, workspace, "run-1")
    assert refused["reason"] == intents.ALREADY_ORDERED and refused["po_number"] == "4500111222"
    assert _reads(calls) == [{"PurchaseRequisition": PR, "PurchaseRequisitionItem": "10"}]
    intent = _intent(db_session, workspace)
    assert intent.status == COMMITTED and intent.resolved_by == "sap_read"
    assert _creates(calls) == []


@pytest.mark.asyncio
async def test_with_the_flag_an_unreadable_sap_refuses_the_write(db_session, monkeypatch, estate):
    workspace, _events = estate
    _reconciling(db_session, workspace)
    calls = _transport(
        monkeypatch, {mcp_read.LIVE_PR_ITEM_BY_KEY: McpUnreachable("sap read down")}
    )
    refused = await _create(db_session, workspace, "run-1")
    assert refused["reason"] == intents.RECONCILIATION_UNAVAILABLE
    assert _creates(calls) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        {"d": {"PurchaseRequisition": PR, "PurchaseRequisitionItem": "10"}},
        _pr_item("", item="20"),
        {"d": {"PurchaseRequisition": "2000000001", "PurchasingDocument": ""}},
        {"d": {}},
    ],
    ids=["no-purchasing-document", "another-item", "another-pr", "empty"],
)
async def test_with_the_flag_a_reply_that_does_not_show_the_item_refuses(
    db_session, monkeypatch, estate, reply
):
    workspace, _events = estate
    _reconciling(db_session, workspace)
    calls = _transport(
        monkeypatch, {mcp_read.LIVE_PR_ITEM_BY_KEY: reply, mcp_write.BAPI_CREATE: CREATED}
    )
    refused = await _create(db_session, workspace, "run-1")
    assert refused["reason"] == intents.RECONCILIATION_UNAVAILABLE
    assert _creates(calls) == []


@pytest.mark.asyncio
async def test_with_the_flag_an_unknown_sap_does_not_show_is_retried_with_a_reference(
    db_session, monkeypatch, estate
):
    workspace, _events = estate
    _transport(monkeypatch, {mcp_write.BAPI_CREATE: McpUnreachable("timed out")})
    await _create(db_session, workspace, "run-1")
    assert _intent(db_session, workspace).status == UNKNOWN

    _reconciling(db_session, workspace)
    calls = _transport(
        monkeypatch,
        {mcp_read.LIVE_PR_ITEM_BY_KEY: _pr_item("", item="00010"), mcp_write.BAPI_CREATE: CREATED},
    )
    retried = await _create(db_session, workspace, "run-2")
    assert retried["committed"] is True
    intent = _intent(db_session, workspace)
    header = next(args for tool, args in calls if tool == mcp_write.BAPI_CREATE)["import"]
    assert (
        header["POHEADER"]["COLLECT_NO"] == intent.reference
        and header["POHEADERX"]["COLLECT_NO"] == "X"
    )


@pytest.mark.asyncio
async def test_without_the_flag_the_create_carries_no_reference(db_session, monkeypatch, estate):
    workspace, _events = estate
    calls = _transport(monkeypatch, {mcp_write.BAPI_CREATE: CREATED})
    await _create(db_session, workspace, "run-1")
    assert "COLLECT_NO" not in calls[0][1]["import"]["POHEADER"]


# --- the run and the retry node ------------------------------------------------------


def test_a_run_with_an_unknown_write_does_not_complete(db_session, monkeypatch):
    from app.services.run_engine.engine import _finalize_run
    from app.tests.services.test_run_outcome_provenance import _running_engine_run

    system, capability, _policy, run = _running_engine_run(db_session)
    monkeypatch.setattr("app.services.evaluation.auto_eval.schedule_eval", lambda _run_id: None)
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="sap_create_po_v1",
        status="completed",
        output_ref={
            "sap_ok": False,
            "outcome": "unknown",
            "needs_reconciliation": True,
            "intent_id": "int-1",
        },
    )
    db_session.add(invocation)
    db_session.commit()
    _finalize_run(
        db_session,
        run,
        system=system,
        capability=capability,
        control=None,
        invocations=[invocation],
        duration_ms=1.0,
        last_output={"audited": True},
    )
    assert run.status == "failed"
    assert run.error.startswith("external_write_outcome_unknown")
    assert "int-1" in run.error


def test_the_retry_node_does_not_repeat_an_external_write(db_session):
    from app.services.run_engine.dag import _skill_is_retryable

    db_session.add_all(
        [
            Skill(
                id=str(uuid4()),
                slug="t_external_write",
                name="w",
                execution={"retryable": False, "idempotent": False},
            ),
            Skill(
                id=str(uuid4()),
                slug="t_llm_answer",
                name="a",
                execution={"retryable": True, "idempotent": False},
            ),
        ]
    )
    db_session.commit()
    assert _skill_is_retryable(db_session, "t_external_write") is False
    assert _skill_is_retryable(db_session, "t_llm_answer") is True
    assert _skill_is_retryable(db_session, "t_unknown_skill") is True
