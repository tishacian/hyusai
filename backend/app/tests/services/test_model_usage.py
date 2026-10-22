"""Provider attempts are charged once; missing measurement is never free."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.model_usage import (
    ModelUsageCall,
    UsageBudgetBucket,
    UsageBudgetPolicy,
    UsageReservation,
)
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import model_usage as usage
from app.services import model_usage_views as views

READINESS_IMPLEMENTATION = usage.budget_readiness


@pytest.fixture
def scope(db_session, monkeypatch):
    db = db_session
    workspace = Workspace(id=str(uuid4()), slug="usage-" + uuid4().hex, name="Usage test")
    user = User(
        id=str(uuid4()),
        email=uuid4().hex + "@example.test",
        username=uuid4().hex,
        password_hash="test",
        role="admin",
        is_active=True,
    )
    system = System(id=str(uuid4()), workspace_id=workspace.id, name="Application")
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=user.id,
        status="running",
    )
    db.add_all([workspace, user, system, run])
    db.commit()
    monkeypatch.setattr(usage, "budget_readiness", lambda _ws: {"ready": True})
    tariff = usage.create_tariff(
        db,
        workspace,
        user,
        provider="openai",
        model="qualified",
        currency="USD",
        input_per_million="1000",
        output_per_million="2000",
    )
    return SimpleNamespace(
        db=db,
        workspace=workspace,
        user=user,
        system=system,
        run=run,
        tariff=tariff,
        ctx=usage.UsageContext(workspace.id, system_id=system.id, run_id=run.id),
    )


def policy(s, *, scope="workspace", tokens=1000, amount="1", revision=0, enabled=True, **kwargs):
    return usage.save_budget(
        s.db,
        s.workspace,
        s.user,
        scope=scope,
        system_id=s.system.id if scope == "system" else None,
        enabled=enabled,
        max_tokens=tokens,
        currency_limits={"USD": amount} if amount is not None else {},
        expected_revision=revision,
        **kwargs,
    )


def prepare(s, key="one", **kwargs):
    params = {
        "request_key": key,
        "provider": "openai",
        "model": "qualified",
        "input_token_bound": 100,
        "output_token_bound": 100,
        "admission_qualified": True,
        **kwargs,
    }
    return usage.prepare_call(s.ctx, **params)


def buckets(s):
    s.db.expire_all()
    return s.db.query(UsageBudgetBucket).all()


def test_shared_limits_are_atomic_and_no_parent_double_count(scope):
    s = scope
    policy(s, amount="1")
    policy(s, scope="system", amount="0.3")
    call = prepare(s)
    assert Decimal(call["reserved_amount"]) == Decimal("0.3")
    with pytest.raises(usage.UsageError, match="BUDGET_EXHAUSTED"):
        prepare(s, "two")
    assert len(s.db.query(UsageReservation).all()) == 2
    assert all(Decimal(b.reserved_amounts["USD"]) == Decimal("0.3") for b in buckets(s))
    assert usage.mark_dispatched(call["id"])
    usage.settle_call(call["id"], usage={"input_tokens": 10, "output_tokens": 20})
    assert all(Decimal(b.consumed_amounts["USD"]) == Decimal("0.05") for b in buckets(s))
    summary = views.summarize(s.db.query(ModelUsageCall).all())
    assert summary["costs"][0]["known_amount"] == "0.050000000000"
    assert summary["counts"]["dispatched"] == 1


def test_unknown_timeout_stays_engaged_then_late_zero_releases(scope):
    s = scope
    policy(s, amount="0.3")
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    result = usage.settle_call(call["id"], usage=None, status="unknown", diagnostic="TimeoutError")
    assert result["amount"] is None and result["total_tokens"] is None
    assert Decimal(buckets(s)[0].reserved_amounts["USD"]) == Decimal("0.3")
    with pytest.raises(usage.UsageError, match="BUDGET_EXHAUSTED"):
        prepare(s, "blocked")
    usage.settle_call(call["id"], usage={"input_tokens": 0, "output_tokens": 0}, status="failed")
    assert Decimal(buckets(s)[0].reserved_amounts["USD"]) == 0
    assert prepare(s, "after-late-proof")["status"] == "prepared"


def test_identity_dedup_and_dispatch_claim_are_distinct(scope):
    s = scope
    policy(s)
    call = prepare(s)
    duplicate = prepare(s)
    assert duplicate["id"] == call["id"] and duplicate["reused"]
    assert len(s.db.query(UsageReservation).all()) == 1
    assert usage.mark_dispatched(call["id"])
    assert not usage.mark_dispatched(call["id"])
    with pytest.raises(usage.UsageError, match="REQUEST_CHANGED"):
        prepare(s, input_token_bound=101)


def test_cancellation_releases_only_before_dispatch(scope):
    s = scope
    policy(s)
    first = prepare(s)
    assert usage.cancel_before_dispatch(first["id"])
    assert buckets(s)[0].reserved_tokens == 0
    second = prepare(s, "second")
    usage.mark_dispatched(second["id"])
    assert not usage.cancel_before_dispatch(second["id"])
    assert buckets(s)[0].reserved_tokens == 200


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"admission_qualified": False}, "TRANSPORT_UNQUALIFIED"),
        ({"model": "missing"}, "TARIFF_REQUIRED"),
        ({"input_token_bound": None}, "BOUND_REQUIRED"),
    ],
)
def test_unknown_routes_and_unbounded_calls_fail_before_transport(scope, changes, code):
    policy(scope)
    with pytest.raises(usage.UsageError, match=code):
        prepare(scope, **changes)
    assert not scope.db.query(UsageReservation).count()
    assert scope.db.query(ModelUsageCall).one().status == "blocked"


def test_local_admission_failure_rolls_back_all_scopes(scope):
    s = scope
    policy(s)

    def refusal(db, call):
        assert call["reserved_tokens"] == 200
        db.add(Workspace(id="rollback-child", name="rollback", slug="rollback"))
        raise ValueError("native stage exhausted")

    with pytest.raises(ValueError, match="stage exhausted"):
        prepare(s, admission_hook=refusal)
    s.db.expire_all()
    assert s.db.get(Workspace, "rollback-child") is None
    assert not s.db.query(UsageReservation).count()
    assert not s.db.query(ModelUsageCall).count()


def test_partial_tokens_do_not_release_monetary_reservation(scope):
    s = scope
    policy(s)
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    usage.settle_call(call["id"], usage={"total_tokens": 20})
    row = buckets(s)[0]
    assert row.consumed_tokens == 20 and row.reserved_tokens == 0
    assert Decimal(row.reserved_amounts["USD"]) == Decimal("0.3")
    usage.settle_call(call["id"], usage={"input_tokens": 10, "output_tokens": 10})
    row = buckets(s)[0]
    assert row.consumed_tokens == 20 and Decimal(row.reserved_amounts["USD"]) == 0
    usage.settle_call(call["id"], usage={"input_tokens": 10, "output_tokens": 10})
    assert buckets(s)[0].consumed_tokens == 20


def test_cached_and_reasoning_are_subsets_and_not_added(scope):
    s = scope
    usage.create_tariff(
        s.db,
        s.workspace,
        s.user,
        provider="openai",
        model="qualified",
        currency="USD",
        input_per_million="1000",
        output_per_million="2000",
        cached_input_per_million="500",
    )
    policy(s)
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    result = usage.settle_call(
        call["id"],
        usage={
            "input_tokens": 100,
            "output_tokens": 50,
            "cached_input_tokens": 40,
            "reasoning_tokens": 30,
        },
    )
    assert result["total_tokens"] == 150
    assert Decimal(result["amount"]) == Decimal("0.18")


def test_tariff_changes_do_not_reprice_existing_calls(scope):
    s = scope
    call = prepare(s)
    usage.create_tariff(
        s.db,
        s.workspace,
        s.user,
        provider="openai",
        model="qualified",
        currency="USD",
        input_per_million="9999",
        output_per_million="9999",
    )
    usage.mark_dispatched(call["id"])
    result = usage.settle_call(call["id"], usage={"input_tokens": 10, "output_tokens": 10})
    assert Decimal(result["amount"]) == Decimal("0.03")


def test_limit_changes_do_not_reset_month(scope):
    s = scope
    original = policy(s)
    prepare(s)
    updated = policy(s, revision=1, amount="2")
    assert original["activated_at"] == updated["activated_at"]
    assert updated["current_period"]["reserved_tokens"] == 200
    assert len(updated["history"]) == 2
    with pytest.raises(usage.UsageError, match="REVISION_CONFLICT"):
        policy(s, revision=1)


def test_period_bounds_honor_dst_without_changing_historical_allocation(scope, monkeypatch):
    p = SimpleNamespace(timezone="Europe/Paris", activated_at=None)
    assert usage.period_bounds(p, datetime(2026, 10, 22))[0] == datetime(2026, 9, 30, 22)
    assert usage.period_bounds(p, datetime(2026, 10, 22))[1] == datetime(2026, 10, 31, 23)
    s = scope
    monkeypatch.setattr(usage, "_now", lambda: datetime(2026, 10, 20, 10))
    policy(s)
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    monkeypatch.setattr(usage, "_now", lambda: datetime(2026, 11, 2, 10))
    usage.settle_call(call["id"], usage={"input_tokens": 10, "output_tokens": 20})
    assert buckets(s)[0].period_end == datetime(2026, 11, 1)
    assert buckets(s)[0].consumed_tokens == 30


def test_bound_breach_retains_spend_and_blocks_next_admission(scope):
    s = scope
    policy(s, amount="10")
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    result = usage.settle_call(call["id"], usage={"input_tokens": 1000, "output_tokens": 500})
    assert result["details"]["reservation_exceeded"]
    assert Decimal(result["amount"]) == 2
    with pytest.raises(usage.UsageError, match="RECONCILIATION_REQUIRED"):
        prepare(s, "next")


def test_readiness_cannot_be_bypassed_by_policy_save(scope, monkeypatch):
    monkeypatch.setattr(usage, "budget_readiness", lambda _: {"ready": False})
    with pytest.raises(usage.UsageError, match="ROLLOUT_UNVERIFIED"):
        policy(scope)
    assert policy(scope, enabled=False)["enabled"] is False


def test_cross_workspace_and_forged_root_fail(scope):
    s = scope
    ctx = usage.UsageContext(s.workspace.id, run_id=s.run.id, root_system_id="another")
    with pytest.raises(usage.UsageError, match="ROOT_SYSTEM_MISMATCH"):
        usage.prepare_call(ctx, request_key="bad", provider="openai", model="qualified")


def test_usd_eur_are_not_implicitly_converted(scope):
    s = scope
    policy(s)
    usage.create_tariff(
        s.db,
        s.workspace,
        s.user,
        provider="other",
        model="eur",
        currency="EUR",
        input_per_million="1",
        output_per_million="1",
    )
    with pytest.raises(usage.UsageError, match="CURRENCY_NOT_BUDGETED"):
        prepare(s, provider="other", model="eur")


def test_disabled_budget_keeps_same_period_accounting(scope):
    s = scope
    policy(s)
    first = prepare(s)
    usage.mark_dispatched(first["id"])
    usage.settle_call(first["id"], usage={"input_tokens": 10, "output_tokens": 10})
    policy(s, revision=1, enabled=False)
    second = prepare(s, "during-pause")
    usage.mark_dispatched(second["id"])
    usage.settle_call(second["id"], usage={"input_tokens": 10, "output_tokens": 10})
    resumed = policy(s, revision=2)
    assert resumed["current_period"]["consumed_tokens"] == 40


def test_reenable_cannot_ignore_unbounded_call_during_pause(scope):
    s = scope
    policy(s)
    policy(s, revision=1, enabled=False)
    call = prepare(s, input_token_bound=None, output_token_bound=None)
    usage.mark_dispatched(call["id"])
    usage.settle_call(call["id"], usage=None, status="unknown")
    with pytest.raises(usage.UsageError, match="UNRESOLVED_PRIOR_USAGE"):
        policy(s, revision=2)


def test_reader_cannot_infer_private_call_through_totals_or_groups(scope):
    s = scope
    reader = User(id=str(uuid4()), username=uuid4().hex, role="user", is_active=True)
    s.db.add(reader)
    s.db.flush()
    s.db.add(WorkspaceMember(workspace_id=s.workspace.id, user_id=reader.id, role="member"))
    s.run.trigger = "chat_agentic"
    s.db.commit()
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    usage.settle_call(call["id"], usage={"input_tokens": 50, "output_tokens": 50})
    rows, coverage = views.visible_calls(s.db, s.workspace, reader)
    assert rows == []
    assert views.summarize(rows)["counts"]["calls"] == 0
    assert views.summarize(rows)["groups"] == []


def test_scope_tree_counts_child_once_and_direct_scope_keeps_single_run(scope):
    s = scope
    parent = prepare(s)
    child = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        system_id=s.system.id,
        initiated_by_user_id=s.user.id,
        status="running",
        parent_run_id=s.run.id,
    )
    s.db.add(child)
    s.db.commit()
    usage.prepare_call(
        usage.UsageContext(s.workspace.id, run_id=child.id),
        request_key="child",
        provider="openai",
        model="qualified",
        input_token_bound=10,
        output_token_bound=10,
    )
    direct, _ = views.visible_calls(s.db, s.workspace, s.user, run_id=s.run.id)
    tree, _ = views.visible_calls(s.db, s.workspace, s.user, run_id=s.run.id, run_scope="tree")
    assert len(direct) == 1 and len(tree) == 2
    assert {row.root_run_id for row in tree} == {s.run.id}


def test_api_contract_accepts_24h_and_denies_member_budget_changes(scope):
    from fastapi import HTTPException

    from app.api.v1.endpoints import model_usage as api

    s = scope
    reader = User(id=str(uuid4()), username=uuid4().hex, role="user", is_active=True)
    s.db.add(reader)
    s.db.flush()
    s.db.add(WorkspaceMember(workspace_id=s.workspace.id, user_id=reader.id, role="member"))
    s.db.commit()
    body = api.BudgetBody(scope="workspace", expected_revision=0, max_tokens=10, enabled=True)
    with pytest.raises(HTTPException) as denied:
        api.save_budget(body, workspace=s.workspace, user=reader, db=s.db)
    assert denied.value.status_code == 403
    assert views.visible_calls(s.db, s.workspace, s.user, window="24h")[0] == []


def test_partial_reconciliation_derives_merged_total(scope):
    s = scope
    policy(s)
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    first = usage.settle_call(call["id"], usage={"input_tokens": 10})
    assert first["total_tokens"] is None
    final = usage.settle_call(call["id"], usage={"output_tokens": 20})
    assert final["total_tokens"] == 30
    assert buckets(s)[0].consumed_tokens == 30
    assert buckets(s)[0].reserved_tokens == 0


def test_missing_tariff_cache_breakdown_keeps_cost_unknown(scope):
    s = scope
    usage.create_tariff(
        s.db,
        s.workspace,
        s.user,
        provider="openai",
        model="qualified",
        currency="USD",
        input_per_million="1000",
        output_per_million="2000",
        cached_input_per_million="100",
    )
    policy(s)
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    first = usage.settle_call(call["id"], usage={"input_tokens": 10, "output_tokens": 20})
    assert first["amount"] is None
    assert Decimal(buckets(s)[0].reserved_amounts["USD"]) == Decimal("0.3")
    final = usage.settle_call(call["id"], usage={"cached_tokens": 5})
    assert Decimal(final["amount"]) == Decimal("0.0455")
    assert Decimal(buckets(s)[0].reserved_amounts["USD"]) == 0


def test_direct_sdk_records_usage_and_disables_hidden_retries(scope):
    from app.services.model_usage_sdk import openai_chat
    from app.services.model_usage_transport import usage_scope

    s = scope
    policy(s, tokens=100000, amount="100")
    sent = []
    options = []
    client = SimpleNamespace(with_options=lambda **opts: options.append(opts) or client)
    client.chat = SimpleNamespace(
        completions=SimpleNamespace(
            create=lambda **kw: (
                sent.append(kw)
                or {
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                    "model": "qualified",
                    "id": "provider-call",
                }
            )
        )
    )
    with usage_scope(s.ctx, key="sdk-sync"):
        openai_chat(
            client,
            model="qualified",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=100,
        )
    assert options == [{"max_retries": 0}] and len(sent) == 1
    row = s.db.query(ModelUsageCall).one()
    assert row.total_tokens == 30 and row.provider_request_id == "provider-call"


def test_direct_sdk_refuses_vision_or_unbounded_request_before_network(scope):
    import asyncio

    from app.services.model_usage_sdk import async_openai_chat
    from app.services.model_usage_transport import usage_scope

    s = scope
    policy(s, tokens=100000, amount="100")
    sent = []

    async def create(**kwargs):
        sent.append(kwargs)

    client = SimpleNamespace(with_options=lambda **opts: client)
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    for payload in [
        {"model": "qualified", "messages": [{"role": "user", "content": "unbounded"}]},
        {
            "model": "qualified",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": "data:fake"}}],
                }
            ],
            "max_tokens": 100,
        },
    ]:
        with usage_scope(s.ctx, key=str(uuid4())):
            with pytest.raises(usage.UsageError, match="USAGE_TRANSPORT_UNQUALIFIED"):
                asyncio.run(async_openai_chat(client, **payload))
    assert sent == []


def test_rollout_attestation_is_revision_bound_audited_and_requires_voice_drain(scope, monkeypatch):
    from app.models.audit import AuditLog

    s = scope
    monkeypatch.setattr(usage, "budget_readiness", READINESS_IMPLEMENTATION)
    revision = "a" * 40
    monkeypatch.setattr(usage.settings, "agentium_image_revision", revision)
    components = {name: revision for name in usage.ROLLOUT_COMPONENTS}
    assert not usage.budget_readiness(s.workspace)["ready"]
    with pytest.raises(usage.UsageError, match="ROLLOUT_UNVERIFIED"):
        usage.attest_rollout(
            s.db,
            s.workspace,
            s.user,
            revision=revision,
            components=components,
            all_workers_recreated=True,
        )
    result = usage.attest_rollout(
        s.db,
        s.workspace,
        s.user,
        revision=revision,
        components=components,
        all_workers_recreated=True,
        livekit_sessions_drained=True,
    )
    assert result["ready"] and result["attestation_basis"] == "operator_declaration"
    assert s.db.query(AuditLog).filter_by(event_type="model_usage.rollout_attested").count() == 1
    assert s.db.query(UsageBudgetPolicy).count() == 0
    monkeypatch.setattr(usage.settings, "agentium_image_revision", "b" * 40)
    assert not usage.budget_readiness(s.workspace)["ready"]


def test_workspace_job_scope_loads_trusted_attribution_and_restores_parent(scope):
    from app.models.workspace_job import WorkspaceJob
    from app.services.model_usage_jobs import job_usage_scope
    from app.services.model_usage_transport import current_scope, usage_scope

    s = scope
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        system_id=s.system.id,
        run_id=s.run.id,
        kind="test_generation",
        created_by_user_id=s.user.id,
    )
    s.db.add(job)
    s.db.commit()
    with usage_scope(usage.UsageContext(s.workspace.id, purpose="generation")):
        with job_usage_scope(job.id, purpose="test_generation", traffic="evaluation"):
            actual = current_scope()
            assert actual.job_id == job.id and actual.run_id == s.run.id
            assert actual.actor_user_id == s.user.id and actual.traffic == "evaluation"
        assert current_scope().job_id is None
    assert current_scope() is None
