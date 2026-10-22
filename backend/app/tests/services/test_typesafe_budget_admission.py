"""Pinned native decisions can reserve money without inventing output tokens."""

import json
from decimal import Decimal

import httpx
import pytest

from app.models.model_usage import ModelUsageCall, UsageBudgetPolicy, UsageReservation
from app.services import model_usage as usage
from app.services.model_usage_transport import (
    ProviderCall,
    native_typesafe_input_bound,
    usage_scope,
)
from app.tests.services import test_model_usage as fixtures
from app.tests.services import test_model_usage_transport as transport_fixtures

scope = fixtures.scope
capture = transport_fixtures.capture
MODEL = "jev-1.13.0"
RESERVATION = Decimal("0.002752512")


def payload(model=MODEL):
    return {
        "model": model,
        "state": "Synthetic invoice: paid twice; one duplicate charge is confirmed.",
        "questions": {"duplicate": {"type": "noul", "instructions": "Was it paid twice?"}},
    }


def configure(s, *, output_price="0", amount=str(RESERVATION), tokens=None):
    usage.create_tariff(
        s.db,
        s.workspace,
        s.user,
        provider="typesafe",
        model=MODEL,
        currency="USD",
        input_per_million="0.042",
        output_per_million=output_price,
    )
    return fixtures.policy(s, amount=amount, tokens=tokens)


def call():
    # A caller's local output provision must not become a native bound.
    return ProviderCall(
        "typesafe", MODEL, payload(), operation="typed_decisions", output_token_bound=4096
    )


@pytest.mark.parametrize("model", [MODEL, "jev-1.14.0"])
def test_native_pin_reserves_full_request_context_and_no_output_counter(capture, model):
    with usage_scope(usage.UsageContext(workspace_id="ws")):
        with ProviderCall(
            "typesafe", model, payload(model), operation="typed_decisions", output_token_bound=0
        ):
            pass
    recorded = capture[0][2]
    assert recorded["input_token_bound"] == 65_536
    assert recorded["output_token_bound"] is None
    assert recorded["admission_qualified"] is True
    assert capture[-1][2]["usage"] is None
    assert "Synthetic invoice" not in str(capture)


@pytest.mark.parametrize("model", ["jev-latest", "jev-preview", "jev-1.13", "jev-9.0.0"])
def test_moving_aliases_and_unknown_versions_are_not_qualified(model):
    assert native_typesafe_input_bound(model, payload(model)) is None


@pytest.mark.parametrize(
    "change",
    [
        {"assets": {"image": "opaque"}},
        {"headers": {"TypeSafe-Danger-Zone-Long-Context": "true"}},
        {"qualified": True},
        {"model": "jev-latest"},
        {"questions": {}},
        {"questions": {"unsafe": {"type": "choice", "criteria": {}}}},
        {"questions": {"unsafe": {"type": "box"}}},
        {"state": {"type": "image_url", "url": "https://example.test/image"}},
        {"state": float("nan")},
    ],
)
def test_native_qualification_rejects_invalid_or_expanded_wire_contract(change):
    assert native_typesafe_input_bound(MODEL, {**payload(), **change}) is None


def test_prompt_wrapper_and_wrong_operation_cannot_claim_native_qualification(capture):
    assert native_typesafe_input_bound(MODEL, {"prompt": "text", "options": {}}) is None
    with usage_scope(usage.UsageContext(workspace_id="ws")):
        with ProviderCall(
            "typesafe", MODEL, payload(), operation="completion", output_token_bound=1
        ):
            pass
    assert capture[0][2]["admission_qualified"] is False


def test_full_monetary_reservation_then_exact_settlement_and_idempotence(scope):
    s = scope
    configure(s)
    with usage_scope(s.ctx, key="native-first"):
        with call() as owner:
            row = s.db.query(ModelUsageCall).one()
            assert row.reserved_tokens is None
            assert row.output_tokens is None and row.total_tokens is None
            assert row.reserved_amount == RESERVATION
            with usage_scope(s.ctx, key="native-second"):
                # Simultaneously outstanding requests cannot spend the same room.
                # The actual parallel database race is covered on PostgreSQL.
                with pytest.raises(usage.UsageError, match="BUDGET_EXHAUSTED"):
                    usage.prepare_call(
                        s.ctx,
                        request_key="second",
                        provider="typesafe",
                        model=MODEL,
                        input_token_bound=65_536,
                        output_token_bound=None,
                        admission_qualified=True,
                    )
            owner.observe({"model": MODEL, "usage": {"input_tokens": 100, "output_tokens": 12}})
    result = usage.settle_call(owner.id, usage={"input_tokens": 100, "output_tokens": 12})
    assert result["total_tokens"] == 112
    assert Decimal(result["amount"]) == Decimal("0.0000042")
    assert result["reserved_tokens"] is None
    assert "reservation_exceeded" not in result["details"]
    bucket = fixtures.buckets(s)[0]
    assert bucket.reserved_tokens == 0 and bucket.consumed_tokens == 112
    assert Decimal(bucket.reserved_amounts["USD"]) == 0
    assert Decimal(bucket.consumed_amounts["USD"]) == Decimal("0.0000042")
    assert s.db.query(UsageBudgetPolicy).one().reconciliation_required is False


@pytest.mark.parametrize("output_price,tokens", [("0.001", None), ("0", 100_000)])
def test_positive_output_tariff_and_token_ceiling_refuse_before_dispatch(
    scope, output_price, tokens
):
    configure(scope, output_price=output_price, tokens=tokens)
    with usage_scope(scope.ctx), pytest.raises(usage.UsageError, match="BOUND_REQUIRED"):
        with call():
            pytest.fail("An unbounded priced dimension must not reach the provider")
    assert scope.db.query(ModelUsageCall).one().status == "blocked"
    assert scope.db.query(UsageReservation).count() == 0


def test_unknown_billable_input_keeps_full_reservation(scope):
    configure(scope)
    with usage_scope(scope.ctx), pytest.raises(TimeoutError):
        with call():
            raise TimeoutError
    scope.db.expire_all()
    row = scope.db.query(ModelUsageCall).one()
    assert row.input_tokens is row.output_tokens is row.total_tokens is row.amount is None
    assert Decimal(fixtures.buckets(scope)[0].reserved_amounts["USD"]) == RESERVATION


def test_unknown_free_output_stays_unknown_while_measured_input_can_be_priced(scope):
    configure(scope)
    with usage_scope(scope.ctx):
        with call() as owner:
            owner.observe({"model": MODEL, "usage": {"input_tokens": 100}})
    scope.db.expire_all()
    row = scope.db.query(ModelUsageCall).one()
    assert row.input_tokens == 100
    assert row.output_tokens is row.total_tokens is row.reserved_tokens is None
    assert row.usage_coverage == "partial"
    assert row.amount == Decimal("0.0000042")
    assert Decimal(fixtures.buckets(scope)[0].reserved_amounts["USD"]) == 0
    usage.settle_call(owner.id, usage={"input_tokens": 100, "output_tokens": 8})
    assert fixtures.buckets(scope)[0].consumed_tokens == 108


def test_provider_bill_beyond_reserved_context_stops_later_admission(scope):
    configure(scope, amount="1")
    with usage_scope(scope.ctx, key="broken-provider-contract"):
        with call() as owner:
            owner.observe({"model": MODEL, "usage": {"input_tokens": 65_537, "output_tokens": 1}})
    scope.db.expire_all()
    assert scope.db.query(ModelUsageCall).one().details["reservation_exceeded"] is True
    assert scope.db.query(UsageBudgetPolicy).one().reconciliation_required is True
    with (
        usage_scope(scope.ctx, key="after-breach"),
        pytest.raises(usage.UsageError, match="RECONCILIATION_REQUIRED"),
    ):
        with call():
            pytest.fail("Reservation breach needs reconciliation")


@pytest.mark.parametrize("returned_model", ["jev-1.14.0", "jev-unknown", "jev-latest"])
def test_model_mismatch_keeps_observed_usage_but_holds_money_and_blocks_later_calls(
    scope, returned_model
):
    configure(scope, amount="1")
    with usage_scope(scope.ctx, key="mismatched-version"):
        with call() as owner:
            owner.observe(
                {"model": returned_model, "usage": {"input_tokens": 100, "output_tokens": 12}}
            )
    scope.db.expire_all()
    row = scope.db.query(ModelUsageCall).one()
    assert row.returned_model == returned_model
    assert row.input_tokens == 100 and row.output_tokens == 12 and row.total_tokens == 112
    assert row.usage_coverage == "complete"
    assert row.amount is None and row.reserved_amount == RESERVATION
    assert row.status == "failed" and row.diagnostic == "TYPESAFE_RETURNED_MODEL_MISMATCH"
    assert row.details["tariff_model_mismatch"] is True
    bucket = fixtures.buckets(scope)[0]
    assert Decimal(bucket.reserved_amounts["USD"]) == RESERVATION
    assert Decimal(bucket.consumed_amounts.get("USD", "0")) == 0
    assert bucket.consumed_tokens == 112
    assert scope.db.query(UsageBudgetPolicy).one().reconciliation_required is True
    with (
        usage_scope(scope.ctx, key="next-call"),
        pytest.raises(usage.UsageError, match="RECONCILIATION_REQUIRED"),
    ):
        with call():
            pytest.fail("The provider's pricing mismatch needs reconciliation")
    # Repeating observations cannot double charge, release the reservation or
    # rewrite the mismatching model to the requested one.
    repeated = usage.settle_call(
        owner.id, usage={"input_tokens": 100, "output_tokens": 12}, returned_model=returned_model
    )
    assert repeated["amount"] is None
    with pytest.raises(usage.UsageError, match="MEASUREMENT_CHANGED"):
        usage.settle_call(
            owner.id, usage={"input_tokens": 100, "output_tokens": 12}, returned_model=MODEL
        )
    assert Decimal(fixtures.buckets(scope)[0].reserved_amounts["USD"]) == RESERVATION


def test_native_counters_without_model_identity_are_not_priced_as_the_requested_pin(scope):
    configure(scope)
    with usage_scope(scope.ctx):
        with call() as owner:
            owner.observe({"usage": {"input_tokens": 100, "output_tokens": 12}})
    scope.db.expire_all()
    row = scope.db.query(ModelUsageCall).one()
    assert row.returned_model is None and row.amount is None
    assert row.total_tokens == 112
    assert row.diagnostic == "TYPESAFE_RETURNED_MODEL_UNVERIFIED"
    assert row.details["tariff_model_unverified"] is True
    assert scope.db.query(UsageBudgetPolicy).one().reconciliation_required is True
    assert Decimal(fixtures.buckets(scope)[0].reserved_amounts["USD"]) == RESERVATION
    assert usage.settle_call(owner.id, usage=None)["amount"] is None
    assert Decimal(fixtures.buckets(scope)[0].reserved_amounts["USD"]) == RESERVATION


def test_generic_free_dimensions_never_replace_unknown_usage_with_zero():
    tariff = {"rates": {"input_per_million": "0", "output_per_million": "2"}}
    assert usage._price(tariff, None, 5, reserve=True) == Decimal("0.000010")
    assert usage._price(tariff, None, 5) == Decimal("0.000010")
    assert usage._price(tariff, 5, None, reserve=True) is None
    assert usage._price(tariff, None, None, reserve=True) is None
    tariff["rates"]["cache_write_per_million"] = "1"
    assert usage._price(tariff, None, 5, reserve=True) is None
    assert usage._price(tariff, None, 5) is None


@pytest.mark.asyncio
async def test_owned_native_transport_sends_no_long_context_or_image_opt_in(monkeypatch):
    from app.services.model_plane import typesafe

    real_client = httpx.AsyncClient
    observed = []

    def respond(request):
        observed.append(request)
        assert json.loads(request.content) == payload()
        assert "typesafe-danger-zone-long-context" not in request.headers
        assert "typesafe-danger-zone-images" not in request.headers
        assert native_typesafe_input_bound(MODEL, json.loads(request.content)) == 65_536
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "answers": {"duplicate": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 25, "output_tokens": 4},
            },
        )

    monkeypatch.setattr(
        typesafe.httpx,
        "AsyncClient",
        lambda **options: real_client(
            transport=httpx.MockTransport(respond),
            **options,
        ),
    )
    result = await typesafe.evaluate(
        api_key="synthetic-only",
        model=MODEL,
        state=payload()["state"],
        questions=payload()["questions"],
    )
    assert len(observed) == 1 and result["model"] == MODEL
