"""The governed value contract of an automation (ADR 0003 lot 3).

A System administrator proposes; the owner the contract names approves, even
when they proposed it. Only an approved contract reaches the cards, and the
gap is measured from the automation's own runs, never typed in.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.endpoints import value_contracts as endpoint
from app.models.capability import Capability
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.value_contract import APPROVED, PROPOSED, REJECTED, SUPERSEDED, WITHDRAWN
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.value_contract import ValueContractDecision, ValueContractProposal
from app.services import value_contracts
from app.services.automation_portfolio import list_job_explanations
from app.services.automation_proof import proof_identity
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.tests.iam_baseline import OPEN_IAM_FEATURES

FLOW = {"variant": "automation_v1", "nodes": [], "edges": []}
PERIOD_START = date(2026, 9, 1)
PERIOD_END = date(2026, 10, 1)


@pytest.fixture
def estate(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"value-{uuid4().hex[:8]}",
        name="Value",
        settings={"features": dict(OPEN_IAM_FEATURES)},
    )
    capability = Capability(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=f"po-{uuid4().hex[:8]}",
        name="PR to PO",
        output_unit="PO",
        value_basis={"status": "declared", "unit": "PO", "value_per_unit": 6, "currency": "EUR"},
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="PR to PO automation",
        objective="Turn approved requisitions into orders",
        status="active",
        flow_definition=dict(FLOW),
        settings={
            "operational_objective": {
                "metric": "completed_volume",
                "target": 50,
                "period_start": "2026-09-01",
                "period_end": "2026-10-01",
                "owner": "Purchasing lead",
                "comparison_reference": "Purchasing plan 2026",
            }
        },
    )
    admin = User(id=str(uuid4()), username=f"admin-{uuid4().hex[:6]}", email=f"admin-{uuid4().hex[:6]}@example.test")
    owner = User(id=str(uuid4()), username=f"owner-{uuid4().hex[:6]}", email=f"owner-{uuid4().hex[:6]}@example.test")
    outsider = User(id=str(uuid4()), username=f"out-{uuid4().hex[:6]}", email=f"out-{uuid4().hex[:6]}@example.test")
    db_session.add_all([workspace, capability, admin, owner, outsider])
    db_session.flush()
    db_session.add(system)
    db_session.flush()
    version = SystemVersion(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=dict(FLOW),
        flow_sha256=canonical_flow_sha256(FLOW),
        release_kind="publish",
        draft_revision=1,
        execution_contract={},
        message="v1",
        created_by="test",
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    db_session.add_all(
        [
            WorkspaceMember(workspace_id=workspace.id, user_id=admin.id, role="admin"),
            WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="viewer"),
        ]
    )
    db_session.commit()
    return {"workspace": workspace, "system": system, "admin": admin, "owner": owner, "outsider": outsider, "version": version}


def _proposal(owner_id: str, **overrides) -> ValueContractProposal:
    body = {
        "owner_user_id": owner_id,
        "indicator": "completed_volume",
        "target": 50,
        "period_start": PERIOD_START.isoformat(),
        "period_end": PERIOD_END.isoformat(),
        "convention": {"value_per_unit": 6, "currency": "EUR", "unit": "PO"},
        "source": {"kind": "agreement", "reference": "Purchasing plan 2026, section 3"},
        "expected_revision": 0,
    }
    body.update(overrides)
    return ValueContractProposal.model_validate(body)


def _runs(db_session, estate, count, *, status="completed", day=date(2026, 9, 10)):
    for index in range(count):
        db_session.add(
            Run(
                id=str(uuid4()),
                workspace_id=estate["workspace"].id,
                system_id=estate["system"].id,
                capability_id=estate["system"].capability_id,
                status=status,
                started_at=datetime.combine(day, datetime.min.time()) + timedelta(minutes=index),
                flow_sha256=estate["version"].flow_sha256,
                execution_surface="published_manual",
            )
        )
    db_session.commit()


def _propose(db_session, estate, **overrides):
    return value_contracts.propose(
        db_session,
        workspace=estate["workspace"],
        system=estate["system"],
        user=estate["admin"],
        proposal=_proposal(estate["owner"].id, **overrides),
    )


def _decide(db_session, estate, contract, *, user=None, approve=True, sha=None):
    return value_contracts.decide(
        db_session,
        workspace=estate["workspace"],
        system=estate["system"],
        user=user or estate["owner"],
        revision=contract.revision,
        content_sha=sha or contract.content_sha256,
        approve=approve,
    )


def _card(db_session, estate, user=None):
    cards = list_job_explanations(db_session, estate["workspace"], user or estate["admin"])
    return next(card for card in cards if card["job"]["system_id"] == estate["system"].id)


# --- the terms --------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"indicator": "human_waits"},
        {"period_end": (PERIOD_START + timedelta(days=91)).isoformat()},
        {"period_end": PERIOD_START.isoformat()},
        {"indicator": "human_validation_rate", "target": 120},
        {"convention": {"value_per_unit": -1, "currency": "EUR", "unit": "PO"}},
        {"convention": {"value_per_unit": 6, "currency": "euro", "unit": "PO"}},
        {"source": {"kind": "rumour", "reference": "x"}},
    ],
    ids=["queue-snapshot", "period-too-long", "empty-period", "percent-over-100", "negative-value", "currency", "source-kind"],
)
def test_terms_that_cannot_be_measured_or_trusted_are_refused(overrides):
    with pytest.raises(ValidationError):
        _proposal("user-1", **overrides)


# --- proposal and approval ----------------------------------------------------


def test_a_proposal_is_not_on_the_card_until_its_owner_approves_it(db_session, estate):
    contract = _propose(db_session, estate)
    assert contract.status == PROPOSED and contract.revision == 1
    assert _card(db_session, estate)["convention"] == {"status": "absent"}

    approved = _decide(db_session, estate, contract)
    assert approved.status == APPROVED
    convention = _card(db_session, estate)["convention"]
    assert convention["status"] == "approved"
    assert convention["value_per_unit"] == 6 and convention["currency"] == "EUR"
    assert convention["contract"]["revision"] == 1
    assert convention["contract"]["owner"] == estate["owner"].email
    assert convention["contract"]["source"]["reference"] == "Purchasing plan 2026, section 3"


def test_only_the_named_owner_decides(db_session, estate):
    contract = _propose(db_session, estate)
    for other in (estate["admin"], estate["outsider"]):
        with pytest.raises(value_contracts.ValueContractError) as refused:
            _decide(db_session, estate, contract, user=other)
        assert refused.value.code == "value_contract_owner_only"


def test_an_owner_may_approve_what_they_proposed(db_session, estate):
    contract = value_contracts.propose(
        db_session,
        workspace=estate["workspace"],
        system=estate["system"],
        user=estate["admin"],
        proposal=_proposal(estate["admin"].id),
    )
    assert _decide(db_session, estate, contract, user=estate["admin"]).status == APPROVED


def test_the_owner_decides_on_the_terms_they_read(db_session, estate):
    contract = _propose(db_session, estate)
    with pytest.raises(value_contracts.ValueContractError) as refused:
        _decide(db_session, estate, contract, sha="0" * 64)
    assert refused.value.code == "value_contract_changed"


def test_a_proposal_is_written_against_the_latest_revision(db_session, estate):
    _propose(db_session, estate)
    with pytest.raises(value_contracts.ValueContractError) as refused:
        _propose(db_session, estate)
    assert refused.value.code == "value_contract_stale"


def test_the_owner_must_be_an_active_member(db_session, estate):
    with pytest.raises(value_contracts.ValueContractError) as refused:
        value_contracts.propose(
            db_session,
            workspace=estate["workspace"],
            system=estate["system"],
            user=estate["admin"],
            proposal=_proposal(estate["outsider"].id),
        )
    assert refused.value.code == "value_contract_owner_not_member"


def test_revisions_keep_their_history(db_session, estate):
    first = _decide(db_session, estate, _propose(db_session, estate))
    waiting = _propose(db_session, estate, target=60, expected_revision=1)
    replaced = _propose(db_session, estate, target=70, expected_revision=2)
    rejected = _decide(db_session, estate, replaced, approve=False)
    last = _decide(db_session, estate, _propose(db_session, estate, target=80, expected_revision=3))

    statuses = {row.revision: row.status for row in value_contracts.revisions(db_session, estate["system"].id)}
    assert statuses == {1: SUPERSEDED, 2: WITHDRAWN, 3: REJECTED, 4: APPROVED}
    assert first.revision == 1 and waiting.revision == 2 and rejected.revision == 3 and last.revision == 4
    assert value_contracts.approved(db_session, estate["system"].id).target == 80


def test_a_capability_value_basis_alone_no_longer_reaches_the_card(db_session, estate):
    """The card reads the approved contract only (lot 3)."""
    card = _card(db_session, estate)
    assert card["convention"] == {"status": "absent"} and card["gap"] == {"status": "absent"}


# --- the measured gap ---------------------------------------------------------------


def _approved(db_session, estate, **overrides):
    return _decide(db_session, estate, _propose(db_session, estate, **overrides))


def test_during_the_period_the_card_shows_progress_not_a_gap(db_session, estate):
    contract = _approved(db_session, estate)
    _runs(db_session, estate, 3)
    gap = value_contracts.measured_gap(
        db_session, user=estate["admin"], workspace=estate["workspace"], system=estate["system"],
        contract=contract, now=datetime(2026, 9, 15),
    )
    assert gap["status"] == "in_progress" and gap["value"] == 3 and gap["target"] == 50
    assert "delta" not in gap


def test_after_the_period_the_gap_is_measured_against_the_target(db_session, estate):
    contract = _approved(db_session, estate, target=5)
    _runs(db_session, estate, 3)
    _runs(db_session, estate, 1, status="failed")
    gap = value_contracts.measured_gap(
        db_session, user=estate["admin"], workspace=estate["workspace"], system=estate["system"],
        contract=contract, now=datetime(2026, 10, 2),
    )
    assert gap["status"] == "measured"
    assert gap["value"] == 3 and gap["delta"] == -2 and gap["unit"] == "runs"


def test_before_the_period_nothing_is_measured(db_session, estate):
    contract = _approved(db_session, estate)
    gap = value_contracts.measured_gap(
        db_session, user=estate["admin"], workspace=estate["workspace"], system=estate["system"],
        contract=contract, now=datetime(2026, 8, 20),
    )
    assert gap["status"] == "not_started"


def test_a_period_without_evidence_is_not_comparable(db_session, estate):
    contract = _approved(db_session, estate, indicator="human_validation_rate", target=90)
    gap = value_contracts.measured_gap(
        db_session, user=estate["admin"], workspace=estate["workspace"], system=estate["system"],
        contract=contract, now=datetime(2026, 10, 2),
    )
    assert gap["status"] == "not_comparable" and gap["reason"] == "not_measured"


def test_the_gap_is_never_turned_into_money(db_session, estate):
    contract = _approved(db_session, estate, target=5)
    _runs(db_session, estate, 3)
    gap = value_contracts.measured_gap(
        db_session, user=estate["admin"], workspace=estate["workspace"], system=estate["system"],
        contract=contract, now=datetime(2026, 10, 2),
    )
    assert not {"value_estimated", "currency", "saving", "amount"} & set(gap)


def test_the_proof_names_the_contract_it_shows(db_session, estate):
    contract = _approved(db_session, estate)
    identity = proof_identity(_card(db_session, estate))
    assert identity["convention"] == "approved"
    assert identity["contract"] == contract.content_sha256


# --- endpoints -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_panel_state_offers_a_prefilled_proposal_to_an_administrator(db_session, estate):
    auth = {"workspace": estate["workspace"], "db": db_session}
    state = await endpoint.get_value_contract(estate["system"].id, user=estate["admin"], **auth)
    assert state["can_propose"] is True and state["latest_revision"] == 0
    assert {row["user_id"] for row in state["owner_options"]} == {estate["admin"].id, estate["owner"].id}
    assert state["prefill"]["indicator"] == "completed_volume" and state["prefill"]["target"] == 50
    assert state["prefill"]["convention"] == {"value_per_unit": 6, "currency": "EUR", "unit": "PO"}
    assert state["prefill"]["source"] == {"kind": "document", "reference": "Purchasing plan 2026"}

    viewer = await endpoint.get_value_contract(estate["system"].id, user=estate["owner"], **auth)
    assert viewer["can_propose"] is False and viewer["owner_options"] == [] and viewer["prefill"] == {}


@pytest.mark.asyncio
async def test_a_member_who_is_not_administrator_cannot_propose(db_session, estate):
    with pytest.raises(HTTPException) as refused:
        await endpoint.propose_value_contract(
            estate["system"].id,
            _proposal(estate["owner"].id),
            workspace=estate["workspace"],
            user=estate["owner"],
            db=db_session,
        )
    assert refused.value.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_approves_through_the_endpoint(db_session, estate):
    auth = {"workspace": estate["workspace"], "db": db_session}
    proposed = await endpoint.propose_value_contract(
        estate["system"].id, _proposal(estate["owner"].id), user=estate["admin"], **auth
    )
    pending = proposed["pending"]
    assert pending["revision"] == 1 and proposed["can_decide"] is False

    as_owner = await endpoint.get_value_contract(estate["system"].id, user=estate["owner"], **auth)
    assert as_owner["can_decide"] is True
    with pytest.raises(HTTPException) as refused:
        await endpoint.approve_value_contract(
            estate["system"].id, 1, ValueContractDecision(content_sha256=pending["content_sha256"]),
            user=estate["admin"], **auth,
        )
    assert refused.value.status_code == 403
    assert refused.value.detail["code"] == "value_contract_owner_only"

    done = await endpoint.approve_value_contract(
        estate["system"].id, 1, ValueContractDecision(content_sha256=pending["content_sha256"]),
        user=estate["owner"], **auth,
    )
    assert done["current"]["revision"] == 1 and done["current"]["status"] == APPROVED
    assert done["pending"] is None and done["convention"]["status"] == "approved"
