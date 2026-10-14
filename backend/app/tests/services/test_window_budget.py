"""Composition uses real fenced windows and a shared durable reservation ledger."""

import copy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.run import Run
from app.models.system import System
from app.schemas.service_contract import ServiceBudget
from app.services import governed_assets as assets
from app.services import service_promises as promises
from app.services import window_budget as budget
from app.services.dataops import narration
from app.services.evaluation import typed_judge as judge
from app.services.governed_assets import GovernanceError
from app.services.model_plane.execution import ModelExecution
from app.tests.services import test_narration, test_typed_judge

setup = test_narration.setup
payload = test_typed_judge.payload
provider = test_typed_judge.provider


def service(s, **budget_overrides):
    now = datetime.utcnow()
    system = System(workspace_id=s.workspace.id, name="Composed service", status="active")
    s.db.add(system)
    s.db.flush()
    s.run.system_id = system.id
    definition = {
        "starts_on": now.date().isoformat(),
        "deadline": "23:59",
        "budget": {"max_cost": 10.0, "max_tokens": 100000, "max_seconds": 3600, **budget_overrides},
    }
    contract = promises.create_contract(
        s.db, s.workspace.id, system.id, s.user.id, definition, created_by=s.user.id
    )
    promises.publish_contract(s.db, s.workspace.id, contract.id, user_id=s.user.id, now=now)
    window = promises.tick(s.db, now, workspace_id=s.workspace.id)[0]
    attempt = promises.claim_window(
        s.db,
        s.workspace.id,
        window.id,
        worker_id="unit-test",
        run_id=s.run.id,
        lease_seconds=600,
        now=now,
    )
    s.db.commit()
    return SimpleNamespace(s=s, window=window, attempt=attempt, contract=contract, system=system)


def reserve(s, key="narration", **amounts):
    return budget.reserve(
        s.ctx,
        stage="narration" if key == "narration" else "judge",
        key=key,
        cost=amounts.get("cost", 10.0),
        tokens=amounts.get("tokens", 100),
        seconds=amounts.get("seconds", 30),
    )


def test_narration_nine_plus_judge_nine_cannot_spend_eighteen_from_ten(setup):
    s = setup
    window = service(s).window
    first = reserve(s)
    budget.settle(first, cost=9.0, tokens=50, seconds=2.0)
    with pytest.raises(GovernanceError, match="BUDGET_EXHAUSTED"):
        reserve(s, "judge", cost=9.0)
    result = budget.summary(s.db, s.workspace.id, window.id, run_id=s.run.id)
    assert result["entries"] == 1 and result["engaged_cost"] == result["measured_cost"] == 9


def test_unknown_usage_retains_envelope_but_measured_zero_releases_it(setup):
    s = setup
    window = service(s).window
    first = reserve(s)
    unknown = budget.settle(first, seconds=1.0)
    assert unknown["measured_cost"] is None and unknown["engaged_cost"] == 10
    assert unknown["cost_coverage"] == "unavailable" and unknown["measured_tokens"] is None
    with pytest.raises(GovernanceError, match="BUDGET_EXHAUSTED"):
        reserve(s, "judge", cost=0.01)
    budget.settle(first, cost=0.0, tokens=0)
    second = reserve(s, "judge", cost=9.0)
    combined = budget.settle(second, cost=9.0, tokens=20, seconds=1.0)
    assert combined["measured_cost"] == combined["engaged_cost"] == 9
    assert combined["measured_tokens"] == 20 and combined["cost_coverage"] == "measured"
    assert budget.summary(s.db, s.workspace.id, window.id)["entries"] == 2


def test_partial_measurements_do_not_release_any_remaining_remote_envelope(setup):
    s = setup
    service(s)
    first = reserve(s)
    result = budget.settle(first, cost=2.0, tokens=1, final=False)
    assert result["known_cost"] == 2 and result["measured_cost"] is None
    assert result["engaged_cost"] == 10 and result["cost_coverage"] == "partial"
    result = budget.settle(first, final=True)
    assert result["measured_cost"] is None and result["engaged_cost"] == 10
    with pytest.raises(GovernanceError, match="BUDGET_EXHAUSTED"):
        reserve(s, "judge", cost=1.0)


def test_an_increased_final_bill_is_retained_and_requires_reconciliation(setup):
    s = setup
    svc = service(s)
    first = reserve(s)
    budget.settle(first, cost=9.0, tokens=100, seconds=1.0)
    result = budget.settle(first, cost=12.0, tokens=100, seconds=2.0)
    assert result["measurement_conflict"] and result["over_budget"]
    assert result["measured_cost"] == result["engaged_cost"] == 12.0
    assert result["measured_seconds"] == 1.0  # replay did not reopen the remote interval
    with pytest.raises(GovernanceError, match="RECONCILIATION_REQUIRED"):
        reserve(s, "another", cost=0.0)
    assert budget.summary(s.db, s.workspace.id, svc.window.id)["measurement_conflict"]


def test_fence_retry_keeps_original_spend_and_allows_only_idempotent_gateway_replay(setup):
    s = setup
    svc = service(s)
    first = budget.reserve(
        s.ctx,
        stage="narration",
        key="stable-remote",
        cost=10.0,
        tokens=100,
        seconds=30,
        replayable=True,
    )
    second_run = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        system_id=svc.system.id,
        initiated_by_user_id=s.user.id,
        status="running",
    )
    s.db.add(second_run)
    svc.window.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    s.db.commit()
    promises.claim_window(
        s.db,
        s.workspace.id,
        svc.window.id,
        worker_id="retry",
        run_id=second_run.id,
        lease_seconds=600,
    )
    s.db.commit()
    with pytest.raises(GovernanceError, match="STALE_LEASE"):
        reserve(s, "stale", cost=1.0)
    retry_ctx = {**s.ctx, "run_id": second_run.id}
    replay = budget.reserve(
        retry_ctx,
        stage="narration",
        key="stable-remote",
        cost=10.0,
        tokens=100,
        seconds=30,
        replayable=True,
    )
    assert replay == first
    with pytest.raises(GovernanceError, match="BUDGET_EXHAUSTED"):
        budget.reserve(retry_ctx, stage="judge", key="new-call", cost=1.0, tokens=1, seconds=1)
    # Late spend is still recorded under the original Run; it cannot admit work.
    budget.settle(first, cost=9.0, tokens=20, seconds=2.0)
    assert (
        budget.summary(s.db, s.workspace.id, svc.window.id, run_id=s.run.id)["measured_cost"] == 9
    )
    assert (
        budget.summary(s.db, s.workspace.id, svc.window.id, run_id=second_run.id)["measured_cost"]
        is None
    )
    assert budget.summary(s.db, s.workspace.id, svc.window.id)["engaged_cost"] == 9


def test_stage_allocations_are_frozen_and_validated_as_a_sum(setup):
    s = setup
    stages = {
        "narration": {"max_cost": 6.0, "max_tokens": 600, "max_seconds": 60},
        "judge": {"max_cost": 4.0, "max_tokens": 400, "max_seconds": 40},
    }
    service(s, stages=stages)
    assert budget.limits(s.ctx, "narration")["max_cost"] == 6
    with pytest.raises(GovernanceError, match="BUDGET_EXHAUSTED"):
        reserve(s, cost=6.01)
    invalid = copy.deepcopy(stages)
    invalid["judge"]["max_cost"] = 5
    with pytest.raises(ValidationError, match="ALLOCATIONS_EXCEED_WINDOW"):
        ServiceBudget.model_validate({"max_cost": 10.0, "stages": invalid})


def test_scope_cannot_be_forged_and_nonidempotent_replays_are_refused(setup):
    s = setup
    service(s)
    with pytest.raises(GovernanceError, match="RUN_INVALID"):
        budget.reserve(
            {**s.ctx, "workspace_id": str(uuid4())},
            stage="judge",
            key="other",
            cost=1.0,
            tokens=1,
            seconds=1,
        )
    reserve(s, "model", cost=1.0)
    with pytest.raises(GovernanceError, match="RECONCILIATION_REQUIRED"):
        reserve(s, "model", cost=1.0)


async def test_real_narration_settlement_blocks_next_typed_model_before_dispatch(
    setup, monkeypatch, payload, provider
):
    s = setup
    svc = service(s)
    narration_payload = test_narration.make_payload(s, max_cost_usd=10.0, max_tokens=50000)
    calls, _ = test_narration.gateway(
        monkeypatch,
        narration_payload,
        [
            {
                "status": "completed",
                "units": [test_narration.rendered("page-0")],
                "cost_usd": 9.0,
                "tokens": 100,
            }
        ],
    )
    result = await narration.run_narration(narration_payload, s.ctx)
    assert result["technical_status"] == "completed" and len(calls) == 1
    s.db.expire_all()
    s.run.input_ref = {**s.run.input_ref, "evidence": payload["evidence"]}
    s.db.commit()
    payload["budget"].update(max_cost_usd=100.0, max_output_tokens=8192)
    payload["tariff"].update(input_per_million=1000.0, output_per_million=1000.0)
    ctx = {
        **s.ctx,
        "_model_execution": ModelExecution("openai", "judge-test", "workspace", "workspace"),
        "_model_policy_check": lambda candidate: None,
    }
    evaluation = await judge.typed_evaluate(payload, ctx)
    assert evaluation["status"] == "failed" and evaluation["reason"] == "SERVICE_BUDGET_EXHAUSTED"
    assert not provider.calls
    measured = budget.summary(s.db, s.workspace.id, svc.window.id)
    assert measured["entries"] == 1 and measured["measured_cost"] == 9.0


async def test_gateway_idempotency_survives_a_new_run_attempt(setup, monkeypatch):
    s = setup
    svc = service(s)
    narration_payload = test_narration.make_payload(s, max_cost_usd=10.0)
    import httpx

    calls, _ = test_narration.gateway(
        monkeypatch,
        narration_payload,
        [
            httpx.ConnectError("fixture"),
            {
                "status": "completed",
                "units": [test_narration.rendered("page-0")],
                "cost_usd": 9.0,
                "tokens": 100,
            },
        ],
    )
    with pytest.raises(narration.NarrationError, match="NETWORK_UNAVAILABLE"):
        await narration.run_narration(narration_payload, s.ctx)
    s.db.expire_all()
    retry = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        system_id=svc.system.id,
        initiated_by_user_id=s.user.id,
        status="running",
        input_ref=copy.deepcopy(s.run.input_ref),
    )
    s.db.add(retry)
    svc.window.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    s.db.commit()
    promises.claim_window(
        s.db, s.workspace.id, svc.window.id, worker_id="retry", run_id=retry.id, lease_seconds=600
    )
    s.db.commit()
    await narration.run_narration(narration_payload, {**s.ctx, "run_id": retry.id})
    assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]
    summary = budget.summary(s.db, s.workspace.id, svc.window.id)
    assert summary["entries"] == 1 and summary["measured_cost"] == 9.0


async def test_completed_gateway_cache_creates_a_current_run_candidate_with_no_new_spend(
    setup, monkeypatch
):
    s = setup
    svc = service(s)
    narration_payload = test_narration.make_payload(s)
    calls, _ = test_narration.gateway(
        monkeypatch,
        narration_payload,
        [
            {
                "status": "completed",
                "units": [test_narration.rendered("page-0")],
                "cost_usd": 9.0,
                "tokens": 100,
            }
        ],
    )
    original = await narration.run_narration(narration_payload, s.ctx)
    s.db.expire_all()
    retry = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        system_id=svc.system.id,
        initiated_by_user_id=s.user.id,
        status="running",
        input_ref=copy.deepcopy(s.run.input_ref),
    )
    s.db.add(retry)
    svc.window.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    s.db.commit()
    promises.claim_window(
        s.db, s.workspace.id, svc.window.id, worker_id="retry", run_id=retry.id, lease_seconds=600
    )
    s.db.commit()
    result = await narration.run_narration(narration_payload, {**s.ctx, "run_id": retry.id})
    assert len(calls) == 1 and result["cost"]["amount"] == 0.0 and result["tokens"] == 0
    assert result["original_measurement"]["cost"]["amount"] == 9.0
    derived = assets.resolve_asset_ref(s.db, s.workspace.id, result["asset_ref"])
    assert derived.run_id == retry.id and derived.parents_json == [original["asset_ref"]]
    assert derived.manifest_json["producer"]["run_id"] == retry.id
    assert (
        assets.current_qualification(s.db, s.workspace.id, derived.id).status == "review_required"
    )
    assert (
        budget.summary(s.db, s.workspace.id, svc.window.id, run_id=retry.id)["measured_cost"] == 0.0
    )
    assert budget.summary(s.db, s.workspace.id, svc.window.id)["measured_cost"] == 9.0


async def test_stale_narration_records_paid_response_but_cannot_checkpoint_or_cancel_new_attempt(
    setup, monkeypatch
):
    s = setup
    svc = service(s)
    narration_payload = test_narration.make_payload(s)
    retry_ids = []

    def replace_attempt(request):
        from app.db.base import SessionLocal
        from app.models.service_contract import ServiceWindow

        with SessionLocal() as db:
            active = db.get(ServiceWindow, svc.window.id)
            active.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
            retry = Run(
                id=str(uuid4()),
                workspace_id=s.workspace.id,
                system_id=svc.system.id,
                initiated_by_user_id=s.user.id,
                status="running",
                input_ref=copy.deepcopy(s.run.input_ref),
            )
            db.add(retry)
            db.commit()
            retry_ids.append(retry.id)
            promises.claim_window(
                db, s.workspace.id, active.id, worker_id="retry", run_id=retry.id, lease_seconds=600
            )
            db.commit()
        return {
            "status": "completed",
            "units": [test_narration.rendered("page-0")],
            "cost_usd": 9.0,
            "tokens": 100,
        }

    calls, _ = test_narration.gateway(
        monkeypatch,
        narration_payload,
        [
            replace_attempt,
            {
                "status": "completed",
                "units": [test_narration.rendered("page-0")],
                "cost_usd": 9.0,
                "tokens": 100,
            },
        ],
    )
    with pytest.raises(narration.NarrationError, match="STALE_LEASE"):
        await narration.run_narration(narration_payload, s.ctx)
    assert [request.method for request in calls] == ["POST"]
    job = test_narration.job(s)
    assert job.status == "queued" and job.result["units"] == {}
    assert budget.summary(s.db, s.workspace.id, svc.window.id)["measured_cost"] == 9.0
    result = await narration.run_narration(narration_payload, {**s.ctx, "run_id": retry_ids[0]})
    assert result["technical_status"] == "completed"
    assert [request.method for request in calls] == ["POST", "POST"]
    assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]
    assert budget.summary(s.db, s.workspace.id, svc.window.id)["measured_cost"] == 9.0


def test_concurrent_stages_cannot_both_reserve_the_same_remaining_envelope(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    s = setup
    svc = service(s)
    barrier = Barrier(2)

    def claim(key):
        barrier.wait(timeout=5)
        try:
            return budget.reserve(s.ctx, stage="judge", key=key, cost=9.0, tokens=1, seconds=1)
        except GovernanceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, key) for key in ("one", "two")]
        values = [future.result(timeout=10) for future in futures]
    assert sum(isinstance(value, budget.Reservation) for value in values) == 1
    assert next(value for value in values if isinstance(value, str)) in {
        "SERVICE_BUDGET_BUSY",
        "SERVICE_BUDGET_EXHAUSTED",
    }
    result = budget.summary(s.db, s.workspace.id, svc.window.id)
    assert result["entries"] == 1 and result["engaged_cost"] == 9.0
