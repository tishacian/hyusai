"""Financial authority, actual proofs, bounded reads and benchmark honesty."""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app.models.claim_trial import ClaimTrial
from app.services import claims_benchmark as bench
from app.services import ecommerce_claims as claims
from app.services.connectors.generic import postgresql_claims as pg

FIXTURES = Path(__file__).resolve().parents[4] / "docs/demo-runs/showcase-ecommerce/fixtures"
SPEC = json.loads((FIXTURES / "fixture_spec.json").read_text())
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())


def case(n):
    order = copy.deepcopy(next(r for r in SPEC["orders"] if r["order_id"] == f"LM-{n}"))
    claim = next(r for r in SPEC["claims"] if r["order_id"] == order["order_id"])
    docs = [
        {
            "document_key": d["reference"],
            "document_type": d["type"],
            "order_id": d["order_id"],
            "sha256": d["sha256"],
            "version": d["version"],
            "effective_from": d["effective_from"],
        }
        for d in MANIFEST["documents"]
        if d["current"] and d["order_id"] in {None, order["order_id"]}
    ]
    snap = {
        "data": {
            "context": [{**order, **claim}],
            "documents": docs,
            "shipments": [r for r in SPEC["shipments"] if r["order_id"] == order["order_id"]],
            "refunds": [r for r in SPEC["refunds"] if r["order_id"] == order["order_id"]],
        },
        "provenance": {"snapshot_sha256": "snap"},
    }
    passages = [
        {"reference": d["reference"], "content": " ".join(d["paragraphs"])}
        for d in SPEC["documents"]
        if d["current"] and d["order_id"] in {None, order["order_id"]}
    ]
    evidence = [{"snapshot_sha256": "snap", "results": passages, "citations": []}]
    config = {
        "policy_sha256": next(d["sha256"] for d in docs if d["document_key"] == "refund-policy-v2")
    }
    return snap, evidence, config


@pytest.mark.parametrize(
    "n,action,amount",
    [
        (1042, "carrier_investigation", "0"),
        (1043, "refund", "49.90"),
        (1044, "close_duplicate", "0"),
    ],
)
def test_three_distinct_evidence_paths(n, action, amount):
    result = claims.propose(*case(n))
    assert (result["action"], result["amount"]) == (action, amount)
    assert result["requires_human"] is True
    assert result["summary"] == "resolution_ready"
    assert result["financial_execution"] == "simulated"


def test_missing_loss_proof_cannot_authorize_refund():
    snap, evidence, config = case(1043)
    evidence[0]["results"] = [
        p for p in evidence[0]["results"] if not p["reference"].startswith("loss-")
    ]
    result = claims.propose(snap, evidence, config)
    assert result["action"] == "request_information" and result["amount"] == "0"


def test_missing_policy_or_wrong_tracking_does_not_authorize_refund():
    snap, evidence, config = case(1043)
    evidence[0]["results"] = [
        p for p in evidence[0]["results"] if p["reference"] != "refund-policy-v2"
    ]
    assert claims.propose(snap, evidence, config)["action"] == "request_information"
    snap, evidence, config = case(1043)
    for p in evidence[0]["results"]:
        p["content"] = p["content"].replace("CA-1043", "CA-9999")
    assert claims.propose(snap, evidence, config)["action"] == "request_information"


@pytest.mark.parametrize("field", ["revision", "snapshot", "currency", "amount"])
def test_stale_or_invalid_authority_rejected(field):
    snap, evidence, config = case(1043)
    if field == "revision":
        config["policy_sha256"] = "stale"
    if field == "snapshot":
        evidence[0]["snapshot_sha256"] = "stale"
    if field == "currency":
        snap["data"]["context"][0]["currency"] = "USD"
    if field == "amount":
        snap["data"]["context"][0]["paid_amount"] = "NaN"
    with pytest.raises(ValueError):
        claims.propose(snap, evidence, config)


def test_delivered_status_alone_does_not_prove_receipt():
    snap, evidence, config = case(1042)
    evidence[0]["results"] = [
        p for p in evidence[0]["results"] if not p["reference"].startswith("delivery-")
    ]
    assert claims.propose(snap, evidence, config)["action"] == "request_information"


@pytest.mark.parametrize("value", ["RC-1042;DROP TABLE", "RC-1042'", "other", None])
def test_claim_validation_precedes_connection(monkeypatch, value):
    reader = Mock()
    monkeypatch.setattr(pg, "_read", reader)
    with pytest.raises(pg.ClaimReadError):
        pg.snapshot(None, value)
    reader.assert_not_called()


def test_reader_is_readonly_bounded_and_does_not_leak_driver_errors(monkeypatch):
    import psycopg2

    monkeypatch.setattr(
        pg,
        "get_config",
        lambda *a, **kw: {
            "values": {"host": "localhost", "database": "test", "username": "reader"},
            "secrets": {"password": "test-value"},
        },
    )
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [{"claim_id": "RC-1042"}]
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: connection)
    result = pg.queue(None, ["RC-1042"])
    connection.set_session.assert_called_once_with(
        isolation_level="REPEATABLE READ", readonly=True, autocommit=False
    )
    assert result["provenance"]["snapshot_sha256"] == pg.digest(result["data"])
    assert cursor.execute.call_args.args[1] == {"claim_ids": ["RC-1042"]}
    cursor.fetchall.return_value = [{}] * 101
    with pytest.raises(pg.ClaimReadError, match="POSTGRESQL_RESULT_LIMIT"):
        pg.queue(None, ["RC-1042"])
    cursor.execute.side_effect = Exception("DO NOT ECHO DRIVER DETAILS")
    connection.rollback.side_effect = Exception("DO NOT ECHO ROLLBACK")
    with pytest.raises(pg.ClaimReadError, match="POSTGRESQL_READ_UNAVAILABLE"):
        pg.snapshot(None, "RC-1042")
    assert connection.close.called


def test_missing_information_never_creates_action():
    with pytest.raises(ValueError, match="CLAIM_RESOLUTION_NOT_READY"):
        claims._simulate(Mock(), None, None, {}, "RC-1043", {"action": "request_information"})


def trial(condition, seconds, passed=True):
    started = datetime(2026, 10, 2)
    return SimpleNamespace(
        pair_id="P01",
        condition=condition,
        state="finished",
        review={"passed": passed},
        id=condition,
        events=[
            {"action": "start", "at": started.isoformat()},
            {"action": "finish", "at": (started + timedelta(seconds=seconds)).isoformat()},
        ],
    )


def test_active_human_clock_excludes_pauses():
    row = trial("manual", 90)
    row.events.insert(1, {"action": "pause", "at": "2026-10-02T00:00:10"})
    row.events.insert(2, {"action": "resume", "at": "2026-10-02T00:01:00"})
    assert bench.seconds(row) == 40


def test_incomplete_or_bad_quality_cannot_create_roi(monkeypatch):
    db = Mock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        trial("manual", 600),
        trial("assisted", 20, False),
    ]
    monkeypatch.setattr(
        bench,
        "protocol",
        lambda _: {"version": "v1", "hourly_eur": "40.00", "pairs": [{"pair_id": "P01"}]},
    )
    monkeypatch.setattr(bench, "serialize", lambda row: {"id": row.id})
    monkeypatch.setattr(bench, "ledger_sha", lambda *a: "ledger")
    result = bench.summary(db, SimpleNamespace(id="ws"))
    assert result["capacity_value_eur"] is None and result["roi"] is None and not result["complete"]


def test_install_uses_native_immutable_publication(db_session, monkeypatch):
    from app.models.experience import ExperienceRelease
    from app.models.system_version import SystemVersion
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember
    from app.services.ecommerce_install import install

    workspace = Workspace(id="claims-install", name="Claims", slug="claims-install", settings={})
    user = User(id="claims-owner", username="claims-owner", email="claims-owner@example.invalid")
    db_session.add_all([workspace, user])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        pg,
        "snapshot",
        lambda w, c: {"data": {"documents": []}, "provenance": {"snapshot_sha256": "snapshot"}},
    )
    monkeypatch.setattr(claims, "_sources", lambda *a: [])
    benchmark = json.loads((FIXTURES / "benchmark/protocol.json").read_text())
    try:
        result = install(
            db_session,
            workspace,
            user,
            policy_sha256="a" * 64,
            source_collections=["luma-maison-regles"],
            benchmark=benchmark,
        )
    except Exception as exc:
        pytest.fail(str(getattr(exc, "details", None) or exc))
    assert result["channel"] == "pilot"
    version = db_session.get(SystemVersion, result["published_flow_version_id"])
    assert version.execution_contract["nodes"]["loop.investigate"]["tool_contract"]
    release = db_session.get(ExperienceRelease, result["release_id"])
    assert release.theme["live_href"] == "/work/reclamations/studio"
    assert release.pages["pages"][0]["components"][1]["id"] == "investigation"
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        install(
            db_session,
            workspace,
            user,
            policy_sha256="a" * 64,
            source_collections=[],
            benchmark=benchmark,
        )


def test_human_approval_cannot_be_automatic_or_another_run(db_session):
    from app.models.decision import Decision
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember

    ws = Workspace(id="claims-approval", slug="claims-approval", name="Claims")
    user = User(id="claims-reviewer", username="claims-reviewer", email="reviewer@example.invalid")
    db_session.add_all([ws, user])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=ws.id, user_id=user.id, role_template="workspace_reviewer", role="member"
        )
    )
    decision = Decision(
        id="claims-decision",
        workspace_id=ws.id,
        scope="run",
        target_id="claims-run",
        kind="hitl_approval",
        status="accepted",
        title="Review",
        rationale={"node_id": "hitl.review"},
        approved_by="system:expiry",
    )
    db_session.add(decision)
    db_session.commit()
    run = SimpleNamespace(id="claims-run")
    with pytest.raises(ValueError, match="HUMAN_APPROVAL_REQUIRED"):
        claims._approved_human(db_session, ws, run, {"requires_sav_manager": False})
    decision.human_confirmed_by = user.id
    decision.human_confirmed_at = datetime.utcnow()
    db_session.flush()
    assert (
        claims._approved_human(db_session, ws, run, {"requires_sav_manager": False}).id
        == decision.id
    )
    with pytest.raises(ValueError, match="MANAGER_APPROVAL_REQUIRED"):
        claims._approved_human(db_session, ws, run, {"requires_sav_manager": True})
    with pytest.raises(ValueError, match="HUMAN_APPROVAL_REQUIRED"):
        claims._approved_human(
            db_session, ws, SimpleNamespace(id="other-run"), {"requires_sav_manager": False}
        )


def test_negative_gain_is_preserved_and_incomplete_cost_stays_unknown(monkeypatch):
    rows = []
    for n in range(10):
        for condition, duration in (("manual", 100), ("assisted", 200)):
            row = trial(condition, duration)
            row.pair_id = f"P{n}"
            row.id = f"{condition}-{n}"
            rows.append(row)
    db = Mock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
    monkeypatch.setattr(
        bench,
        "protocol",
        lambda _: {
            "version": "v1",
            "hourly_eur": "40.00",
            "pairs": [{"pair_id": f"P{n}"} for n in range(10)],
        },
    )
    monkeypatch.setattr(bench, "serialize", lambda row: {"id": row.id})
    monkeypatch.setattr(bench, "ledger_sha", lambda *a: "ledger")
    monkeypatch.setattr(bench, "approved_costs", lambda *a: None)
    monkeypatch.setattr(bench, "cost_eur", lambda *a: None)
    result = bench.summary(db, SimpleNamespace(id="ws"))
    assert (
        float(result["capacity_value_eur"]) < 0
        and result["net_benefit_eur"] is None
        and result["roi"] is None
    )
    monkeypatch.setattr(bench, "cost_eur", lambda *a: __import__("decimal").Decimal("10"))
    result = bench.summary(db, SimpleNamespace(id="ws"))
    assert float(result["roi"]) < -1
    monkeypatch.setattr(bench, "cost_eur", lambda *a: __import__("decimal").Decimal(0))
    assert bench.summary(db, SimpleNamespace(id="ws"))["roi"] is None


@pytest.mark.asyncio
async def test_caller_cannot_replace_persisted_claim_or_cross_workspace(db_session, monkeypatch):
    from app.models.run import Run
    from app.models.user import User
    from app.models.workspace import Workspace

    ws = Workspace(
        id="claims-identity",
        slug="claims-identity",
        name="Claims",
        settings={
            "features": {"ecommerce_claims_v1": True},
            "ecommerce_claims": {
                "allowed_claim_ids": ["RC-1042"],
                "allowed_collection_slugs": ["rules"],
                "policy_sha256": "a" * 64,
            },
        },
    )
    user = User(id="claims-operator", username="operator", email="operator@example.invalid")
    db_session.add_all([ws, user])
    db_session.flush()
    run = Run(
        id="claims-run-identity",
        workspace_id=ws.id,
        initiated_by_user_id=user.id,
        input_ref={"claim_id": "RC-1042"},
    )
    db_session.add(run)
    db_session.commit()
    reader = Mock(return_value={"data": {"context": [{"claim_id": "RC-1042"}]}})
    monkeypatch.setattr(pg, "snapshot", reader)
    result = await claims.invoke(
        "snapshot",
        {"claim_id": "RC-1043", "observations": [{"action": "refund"}]},
        {"db": db_session, "workspace_id": ws.id, "run_id": run.id},
    )
    assert result["data"]["context"][0]["claim_id"] == "RC-1042"
    assert reader.call_args.args[1] == "RC-1042"
    with pytest.raises(ValueError, match="CLAIM_RUN_REQUIRED"):
        await claims.invoke(
            "snapshot", {}, {"db": db_session, "workspace_id": "other", "run_id": run.id}
        )


def test_missing_cost_or_foreign_currency_never_becomes_free(monkeypatch):
    row = SimpleNamespace(condition="assisted")
    monkeypatch.setattr(bench, "session_runs", lambda *a: [SimpleNamespace(id="run")])
    call = SimpleNamespace(
        cost_measured=False, cost=0, metrics={"cost_evidence": {"currency": "EUR"}}
    )
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = [call]
    assert (
        bench.cost_eur(
            db,
            [row],
            {
                "allocation": {
                    "coverage": "complete",
                    "total_eur": "0",
                    "evidence_ref": "real-invoice",
                }
            },
        )
        is None
    )
    call.cost_measured = True
    call.metrics["cost_evidence"]["currency"] = "USD"
    assert bench.cost_eur(db, [row], {}) is None


def test_simulated_receipt_is_idempotent_and_rechecks_live_snapshot(db_session, monkeypatch):
    from app.models.claim_action import ClaimAction
    from app.models.decision import Decision
    from app.models.run import Run
    from app.models.user import User
    from app.models.workspace import Workspace

    ws = Workspace(id="receipt-ws", slug="receipt-ws", name="Receipt")
    user = User(id="receipt-user", username="receipt-user", email="receipt@example.invalid")
    db_session.add_all([ws, user])
    db_session.flush()
    run = Run(id="receipt-run", workspace_id=ws.id, initiated_by_user_id=user.id)
    decision = Decision(
        id="receipt-decision",
        workspace_id=ws.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        title="Approve",
        status="accepted",
        human_confirmed_by=user.id,
        human_confirmed_at=datetime.utcnow(),
    )
    db_session.add_all([run, decision])
    db_session.commit()
    proposal = claims.propose(*case(1043))
    monkeypatch.setattr(claims, "_approved_human", lambda *a: decision)
    monkeypatch.setattr(pg, "snapshot", lambda *a: {"provenance": {"snapshot_sha256": "stale"}})
    with pytest.raises(ValueError, match="EVIDENCE_STALE"):
        claims._simulate(db_session, ws, run, {}, "RC-1043", proposal)
    assert db_session.query(ClaimAction).count() == 0
    monkeypatch.setattr(pg, "snapshot", lambda *a: {"provenance": {"snapshot_sha256": "snap"}})
    monkeypatch.setattr(claims, "_sources", lambda *a: [])
    receipt = claims._simulate(db_session, ws, run, {}, "RC-1043", proposal)
    db_session.commit()
    assert receipt["status"] == "simulated" and receipt["external_payment_called"] is False
    assert (
        claims._simulate(db_session, ws, run, {}, "RC-1043", proposal)["receipt_id"]
        == receipt["receipt_id"]
    )
    second = Run(id="receipt-second", workspace_id=ws.id, initiated_by_user_id=user.id)
    db_session.add(second)
    db_session.flush()
    approval = Mock(return_value=SimpleNamespace(id="current-approval"))
    monkeypatch.setattr(claims, "_approved_human", approval)
    replay = claims._simulate(db_session, ws, second, {}, "RC-1043", proposal)
    assert replay["receipt_id"] == receipt["receipt_id"]
    assert replay["run_id"] == run.id and replay["reused_for_run_id"] == second.id
    assert (
        replay["decision_id"] == decision.id
        and replay["reused_for_decision_id"] == "current-approval"
    )
    assert replay["idempotent_replay"] is True
    assert db_session.query(ClaimAction).count() == 1
    approval.assert_called_once_with(db_session, ws, second, proposal)
    assert "reused_for_run_id" not in db_session.query(ClaimAction).one().receipt
    for field, changed in (("amount", "50"), ("currency", "USD"), ("claim_id", "RC-1042")):
        previous = proposal[field]
        proposal[field] = changed
        with pytest.raises(ValueError, match="ALREADY_RECORDED"):
            claims._simulate(db_session, ws, second, {}, "RC-1043", proposal)
        proposal[field] = previous
    monkeypatch.setattr(
        claims, "_approved_human", Mock(side_effect=ValueError("CLAIM_HUMAN_APPROVAL_REQUIRED"))
    )
    with pytest.raises(ValueError, match="HUMAN_APPROVAL_REQUIRED"):
        claims._simulate(db_session, ws, second, {}, "RC-1043", proposal)


def test_trial_clock_is_owned_versioned_and_reviewed_independently(db_session, monkeypatch):
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember

    ws = Workspace(id="trial-ws", name="Trials", slug="trial-ws")
    owner = User(id="trial-human", username="trial-human", email="trial@example.invalid")
    reviewer = User(id="trial-reviewer", username="trial-reviewer", email="review@example.invalid")
    db_session.add_all([ws, owner, reviewer])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=ws.id,
            user_id=reviewer.id,
            role="member",
            role_template="workspace_reviewer",
        )
    )
    snapshot = {
        "data": {"documents": [{"document_key": "policy"}]},
        "provenance": {"snapshot_sha256": "original"},
    }
    row = ClaimTrial(
        id="trial-session",
        workspace_id=ws.id,
        operator_id=owner.id,
        protocol_sha256="a" * 64,
        pair_id="P01",
        condition="manual",
        claim_id="RC-1042",
        state="active",
        started_at=datetime.utcnow(),
        evidence={
            "snapshot": snapshot,
            "expected": {
                "action": "carrier_investigation",
                "amount": "0",
                "references": ["policy"],
            },
        },
        events=[
            {
                "action": "start",
                "sequence": 1,
                "at": datetime.utcnow().isoformat(),
                "actor_id": owner.id,
            }
        ],
    )
    db_session.add(row)
    db_session.commit()
    with pytest.raises(ValueError, match="NOT_FOUND"):
        bench.event(db_session, ws, reviewer, row.id, "pause", 1)
    bench.event(db_session, ws, owner, row.id, "pause", 1)
    with pytest.raises(ValueError, match="EVENT_CONFLICT"):
        bench.event(db_session, ws, owner, row.id, "resume", 1)
    bench.event(db_session, ws, owner, row.id, "resume", 2)
    monkeypatch.setattr(bench, "session_runs", lambda *a: [])
    monkeypatch.setattr(pg, "snapshot", lambda *a: snapshot)
    bench.event(
        db_session,
        ws,
        owner,
        row.id,
        "finish",
        3,
        {"action": "refund", "amount": "420", "references": ["policy"], "note": "wrong decision"},
    )
    # A positive human verdict cannot override an incorrect expected resolution.
    bench.review(db_session, ws, reviewer, row.id, True, "Reviewed against the original evidence")
    assert row.review["passed"] is False
    bench.event(db_session, ws, owner, row.id, "resume", 4)
    assert row.review is None and any(e["action"] == "quality_review" for e in row.events)
    assert row.state == "active"
