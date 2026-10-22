"""Declared conversion evidence is immutable; no implicit exchange takes place."""

from copy import deepcopy
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.model_usage import TariffBody
from app.models.audit import AuditLog
from app.models.model_usage import ModelTariff, ModelUsageCall
from app.services import model_usage as usage
from app.tests.services import test_model_usage

scope = test_model_usage.scope
prepare = test_model_usage.prepare


def converted_tariff():
    # Deliberately artificial exchange rate, used only by isolated unit tests.
    return {
        "provider": "openai",
        "model": "qualified",
        "currency": "EUR",
        "input_per_million": "1",
        "output_per_million": "8",
        "cached_input_per_million": "0.1",
        "provenance": {
            "reference": "https://provider.example/pricing",
            "observed_on": "2026-10-22",
            "conversion": {
                "source_currency": "USD",
                "source_rates": {
                    "input_per_million": "1.25",
                    "output_per_million": "10",
                    "cached_input_per_million": "0.125",
                },
                "rate": "0.8",
                "reference": "https://bank.example/reference-rates",
                "observed_on": "2026-10-21",
            },
        },
    }


def test_conversion_provenance_persists_in_audit_and_frozen_call_snapshot(scope):
    s = scope
    original_usd = prepare(s, key="before-eur-tariff")
    request = converted_tariff()
    original = deepcopy(request)
    # Match the actual API's Pydantic model_dump (which contains Python dates).
    body = TariffBody.model_validate(request)
    created = usage.create_tariff(s.db, s.workspace, s.user, **body.model_dump())
    assert request == original
    assert created["provenance"]["conversion"]["rate"] == "0.800000000000"
    assert created["provenance"]["conversion"]["convention"] == "target_per_source"
    assert created["provenance"]["conversion"]["rounding"] == "half_even_12dp"
    assert created["provenance"]["observed_on"] == "2026-10-22"
    assert "provenance" not in created["rates"]
    audit = s.db.query(AuditLog).filter_by(event_type="model_usage.tariff_created").all()
    assert next(row.details for row in audit if row.details["id"] == created["id"]) == created
    call = prepare(s)
    assert call["tariff_snapshot"] == created
    saved = s.db.get(ModelUsageCall, call["id"])
    assert saved.tariff_snapshot == created
    assert Decimal(call["reserved_amount"]) == Decimal("0.0009")

    revised = converted_tariff()
    revised["provenance"]["conversion"]["rate"] = "0.9"
    revised.update(
        input_per_million="1.125", output_per_million="9", cached_input_per_million="0.1125"
    )
    usage.create_tariff(s.db, s.workspace, s.user, **revised)
    s.db.expire_all()
    assert s.db.get(ModelUsageCall, call["id"]).tariff_snapshot == created
    assert s.db.get(ModelUsageCall, original_usd["id"]).tariff_snapshot == s.tariff
    assert s.db.get(ModelUsageCall, original_usd["id"]).currency == "USD"


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda request: request.update(input_per_million="1.01"), "CONVERSION_MISMATCH"),
        (
            lambda request: request["provenance"]["conversion"].update(rate="0"),
            "CONVERSION_INVALID",
        ),
        (
            lambda request: request["provenance"]["conversion"].update(source_currency="EUR"),
            "CONVERSION_INVALID",
        ),
        (
            lambda request: request["provenance"]["conversion"]["source_rates"].pop(
                "cached_input_per_million"
            ),
            "CONVERSION_INVALID",
        ),
        (lambda request: request["provenance"]["conversion"].update(rate="NaN"), "AMOUNT_INVALID"),
        (lambda request: request["provenance"].update(reference=" "), "PROVENANCE_INVALID"),
        (
            lambda request: request["provenance"].update(observed_on="not-a-date"),
            "PROVENANCE_INVALID",
        ),
    ],
)
def test_invalid_or_inconsistent_conversion_creates_no_tariff(scope, mutation, code):
    s = scope
    request = converted_tariff()
    mutation(request)
    before = s.db.query(ModelTariff).count()
    with pytest.raises(usage.UsageError, match=code):
        usage.create_tariff(s.db, s.workspace, s.user, **request)
    s.db.rollback()
    assert s.db.query(ModelTariff).count() == before


def test_direct_declared_source_needs_no_conversion_and_old_tariffs_stay_readable(scope):
    s = scope
    assert s.tariff["provenance"] is None
    created = usage.create_tariff(
        s.db,
        s.workspace,
        s.user,
        provider="openai",
        model="qualified",
        currency="USD",
        input_per_million="1.25",
        output_per_million="10",
        provenance={"reference": "contract:pricing-v3", "observed_on": "2026-10-22"},
    )
    assert created["provenance"]["conversion"] is None
    assert usage._price(created, 1_000_000, 0) == Decimal("1.25")


def test_provenance_cannot_claim_unimplemented_verification_or_supply_only_source_prices():
    request = converted_tariff()
    request["provenance"]["verified_by_provider"] = True
    with pytest.raises(ValidationError):
        TariffBody.model_validate(request)
    request = converted_tariff()
    request.pop("input_per_million")
    with pytest.raises(ValidationError):
        TariffBody.model_validate(request)


def test_explicit_conversion_rounds_half_even_at_twelve_decimal_places(scope):
    s = scope
    request = converted_tariff()
    request.pop("cached_input_per_million")
    request.update(input_per_million="0", output_per_million="0.000000000002")
    request["provenance"]["conversion"].update(
        rate="0.5",
        source_rates={
            "input_per_million": "0.000000000001",
            "output_per_million": "0.000000000003",
        },
    )
    created = usage.create_tariff(s.db, s.workspace, s.user, **request)
    assert created["rates"] == {"input_per_million": "0E-12", "output_per_million": "2E-12"}


@pytest.mark.parametrize("rounding", [ROUND_UP, ROUND_DOWN])
def test_conversion_normalization_is_independent_of_callers_rounding_context(scope, rounding):
    request = converted_tariff()
    request.pop("cached_input_per_million")
    request.update(input_per_million="1", output_per_million="1.000000000002")
    request["provenance"]["conversion"].update(
        rate="1.0000000000005",
        source_rates={
            "input_per_million": "1.0000000000005",
            "output_per_million": "1.0000000000015",
        },
    )
    with localcontext() as context:
        context.rounding = rounding
        created = usage.create_tariff(scope.db, scope.workspace, scope.user, **request)
    assert created["rates"] == {
        "input_per_million": "1.000000000000",
        "output_per_million": "1.000000000002",
    }
    assert created["provenance"]["conversion"]["rate"] == "1.000000000000"
