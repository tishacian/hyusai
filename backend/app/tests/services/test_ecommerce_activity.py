"""Activity measures executions; declared scenarios cannot fabricate human ROI."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.models.run import Run, SkillInvocation
from app.services import ecommerce_activity as activity


def config():
    return {
        "allowed_claim_ids": ["RC-5002", "RC-5004"],
        "allowed_collection_slugs": ["luma-maison-benchmark"],
        "policy_sha256": "policy-sha",
        "benchmark": {
            "pairs": [
                {
                    "manual_claim_id": "RC-5001",
                    "assisted_claim_id": "RC-5002",
                    "manual_expected": {
                        "action": "refund",
                        "amount": "49.90",
                        "references": ["refund-policy-v2", "loss-lm5001"],
                    },
                    "assisted_expected": {
                        "action": "refund",
                        "amount": "49.90",
                        "references": ["refund-policy-v2", "loss-lm5002"],
                    },
                }
            ],
        },
    }


def call(slug, output, *, cost=0, currency="EUR", measured=True, latency=100):
    return SimpleNamespace(
        skill_slug=slug,
        status="completed",
        output_ref=output,
        cost=cost,
        cost_measured=measured,
        latency_ms=latency,
        metrics={
            "cost_evidence": {
                "state": "calculated" if measured else "not_measured",
                "currency": currency,
            }
        },
    )


def run(run_id="attempt-1", **kwargs):
    snapshot = {
        "data": {
            "documents": [
                {"document_key": reference} for reference in ("refund-policy-v2", "loss-lm5002")
            ]
        },
        "provenance": {"snapshot_sha256": "snapshot"},
    }
    proposal = {
        "evidence_kind": "synthetic_demo",
        "claim_id": "RC-5002",
        "snapshot_sha256": "snapshot",
        "action": "refund",
        "amount": "49.90",
        "citations": [{"document_id": "policy"}, {"document_id": "loss"}],
    }
    now = datetime.utcnow()
    values = dict(
        id=run_id,
        input_ref={"claim_id": "RC-5002"},
        status="completed",
        started_at=now,
        completed_at=now + timedelta(seconds=1000),
        published_flow_version_id="published-v3",
        flow_sha256="flow-sha",
        invocations=[
            call("postgresql_claim_snapshot_v1", snapshot),
            call(
                "ecommerce_policy_evidence_v1",
                {
                    "results": [
                        {"reference": "refund-policy-v2", "metadata": {"document_id": "policy"}}
                    ]
                },
                measured=False,
            ),
            call(
                "ecommerce_delivery_evidence_v1",
                {"results": [{"reference": "loss-lm5002", "metadata": {"document_id": "loss"}}]},
                measured=False,
            ),
            call("decide_next_v1", {}, cost=0.003, currency="USD"),
            call("ecommerce_resolution_propose_v1", proposal),
        ],
    )
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_currency_and_coverage_preserve_unpriced_calls_and_zero_tariffs():
    result = activity.summarize_runs([run()], config())
    assert result["catalog_costs"]["by_currency"] == {"EUR": "0", "USD": "0.003"}
    assert result["catalog_costs"]["priced_invocations"] == 3
    assert result["catalog_costs"]["unpriced_invocations"] == 2
    assert result["catalog_costs"]["state"] == "partial"
    assert result["catalog_costs"]["includes_infrastructure_licence_integration"] is False
    assert "roi" not in result and "active_human_seconds" not in result
    assert result["assumptions"] == activity.ASSUMPTIONS
    assert result["production_baseline_eligible"] is False


def test_all_retries_count_in_costs_but_distinct_cases_and_latest_quality_do_not_inflate():
    first = run()
    second = run("attempt-2", started_at=first.started_at + timedelta(seconds=1), status="failed")
    result = activity.summarize_runs([second, first], config())
    assert result["counts"] == {
        "attempts": 2,
        "completed": 1,
        "failed": 1,
        "duplicate_blocked": 0,
        "pending": 0,
        "unique_cases": 1,
        "rule_matched_cases": 1,
        "simulated_receipts": 0,
        "waiting_information_cases": 0,
        "invocations": 10,
    }
    assert result["catalog_costs"]["by_currency"]["USD"] == "0.006"
    second.invocations[-1].output_ref["amount"] = "1000"
    assert activity.summarize_runs([second, first], config())["counts"]["rule_matched_cases"] == 0


def test_reused_simulated_receipt_and_information_requests_do_not_create_resolved_volume():
    first, replay, missing = run(), run("replay"), run("missing")
    receipt = {
        "receipt_id": "original-receipt",
        "status": "simulated",
        "evidence_kind": "synthetic_demo",
        "external_payment_called": False,
    }
    for r in (first, replay):
        r.invocations.append(call("ecommerce_resolution_simulate_v1", dict(receipt)))
    missing.input_ref = {"claim_id": "RC-5004"}
    missing.invocations[-1].output_ref["action"] = "request_information"
    result = activity.summarize_runs([first, replay, missing], config())
    assert result["counts"]["unique_cases"] == 2
    assert result["counts"]["simulated_receipts"] == 1
    assert result["counts"]["waiting_information_cases"] == 1
    first.invocations[-1].output_ref["external_payment_called"] = True
    replay.invocations[-1].status = "failed"
    assert activity.summarize_runs([first, replay], config())["counts"]["simulated_receipts"] == 0


def test_technical_call_time_never_includes_queue_or_approval_wait():
    r = run()
    result = activity.summarize_runs([r], config())
    assert result["median_technical_seconds"] == 0.5
    assert result["runs"][0]["elapsed_seconds"] == 1000
    r.invocations[0].latency_ms = None
    assert activity.summarize_runs([r], config())["median_technical_seconds"] is None


def test_rubric_checks_actual_citations_action_amount_and_snapshot():
    r = run()
    assert activity._rule_match(r, config()) is True
    proposal = r.invocations[-1].output_ref
    for key, value in (
        ("action", "close_duplicate"),
        ("amount", "NaN"),
        ("snapshot_sha256", "changed"),
        ("citations", [{"document_id": "policy"}]),
    ):
        saved = proposal[key]
        proposal[key] = value
        assert activity._rule_match(r, config()) is False
        proposal[key] = saved
    r.invocations[2].output_ref["results"] = []
    assert activity._rule_match(r, config()) is False


def test_unknown_case_and_empty_ledger_never_manufacture_quality_or_cost():
    r = run(input_ref={"claim_id": "RC-1042"})
    assert activity._rule_match(r, config()) is None
    result = activity.summarize_runs([], config())
    assert result["catalog_costs"]["by_currency"] == {}
    assert result["median_technical_seconds"] is None
    assert result["counts"]["attempts"] == 0


def test_pending_and_invalid_costs_cannot_be_treated_as_measured_zero():
    r = run(status="running", completed_at=None)
    for c in r.invocations:
        c.cost_measured = True
        c.cost = float("nan")
    r.invocations[-1].cost = 0
    r.invocations[-1].status = "running"
    result = activity.summarize_runs([r], config())
    assert result["counts"]["pending"] == 1
    assert result["counts"]["rule_matched_cases"] == 0
    assert result["catalog_costs"]["priced_invocations"] == 0
    assert result["catalog_costs"]["by_currency"] == {}


def test_database_scope_and_canonical_read_permission_are_applied(db_session, monkeypatch):
    now = datetime.utcnow()
    workspace = SimpleNamespace(
        id="ws-luma-activity",
        settings={"features": {"ecommerce_claims_v1": True}, "ecommerce_claims": config()},
    )
    valid = dict(
        workspace_id=workspace.id,
        system_id=None,
        status="completed",
        started_at=now,
        input_ref={
            "claim_id": "RC-5002",
            "_ingress": {
                "adapter": {"experience_id": "work-luma", "binding_key": activity.BINDING}
            },
        },
    )
    for run_id, changed in [
        ("visible", {}),
        ("hidden", {}),
        ("other-workspace", {"workspace_id": "ws-other"}),
        (
            "other-app",
            {
                "input_ref": {
                    "claim_id": "RC-5002",
                    "_ingress": {
                        "adapter": {"experience_id": "other-app", "binding_key": activity.BINDING}
                    },
                }
            },
        ),
        (
            "outside-cohort",
            {
                "input_ref": {
                    "claim_id": "RC-9999",
                    "_ingress": {
                        "adapter": {"experience_id": "work-luma", "binding_key": activity.BINDING}
                    },
                }
            },
        ),
        ("old", {"started_at": now - timedelta(days=8)}),
    ]:
        db_session.add(Run(id=run_id, **{**valid, **changed}))
    db_session.add(
        SkillInvocation(
            id="priced-call",
            run_id="visible",
            skill_slug="decide_next_v1",
            status="failed",
            cost=0.003,
            cost_measured=True,
            metrics={"cost_evidence": {"state": "calculated", "currency": "USD"}},
        )
    )
    db_session.flush()

    def readable(db, *, runs, user, workspace):
        assert {r.id for r in runs} == {"visible", "hidden"}
        return [r for r in runs if r.id == "visible"]

    monkeypatch.setattr(activity, "readable_runs", readable)
    result = activity.activity(
        db_session,
        workspace,
        SimpleNamespace(id="viewer"),
        experience_id="work-luma",
        system_id=None,
    )
    assert [r["run_id"] for r in result["runs"]] == ["visible"]
    assert result["counts"]["attempts"] == 1
    assert result["catalog_costs"]["by_currency"] == {"USD": "0.003"}
