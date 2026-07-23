"""Unit tests for Client360 deterministic forecasts (Phase 4)."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.client360_contract import CLIENT360_ADDRESSABLE_WEIGHTS
from app.services.client360_forecast import (
    CONFIDENCE_CONSTRUCTION_YEAR,
    CONFIDENCE_LAST_PURCHASE,
    FORECAST_DISCLAIMER,
    apply_next_due_to_record,
    campaign_expected_value,
    compute_next_due,
    mail_follow_up_due_at,
    mail_follow_up_reminder,
    next_due_items_for_records,
    opportunity_addressable_value,
    parse_construction_year,
    parse_forecast_date,
    resolve_conversion_proxy,
)


NOW = datetime(2026, 7, 8, 12, 0, 0)


def test_parse_forecast_date_formats() -> None:
    assert parse_forecast_date("2024-03-15") == datetime(2024, 3, 15)
    assert parse_forecast_date("15/03/2024") == datetime(2024, 3, 15)
    assert parse_forecast_date(datetime(2024, 3, 15, 9, 0, 0)) == datetime(2024, 3, 15, 9, 0, 0)
    # VA05 aggregation payload format (``Document Date`` cell via _safe_text).
    assert parse_forecast_date("2024-04-03 00:00:00") == datetime(2024, 4, 3)
    assert parse_forecast_date(None) is None
    assert parse_forecast_date("") is None


def test_parse_construction_year() -> None:
    assert parse_construction_year(2019) == 2019
    assert parse_construction_year("2019") == 2019
    assert parse_construction_year("Built 2019 Q2") == 2019
    assert parse_construction_year("2019-01-01T00:00:00") == 2019
    assert parse_construction_year("n/a") is None


def test_compute_next_due_from_last_purchase() -> None:
    result = compute_next_due(
        last_purchase_date="2026-01-01",
        periodicity_weeks=26,
        recommended_quantity=4,
        now=NOW,
    )
    assert result is not None
    assert result["next_due_at"] == datetime(2026, 7, 2)
    assert result["recommended_qty"] == 4.0
    assert result["anchor_source"] == "last_purchase"
    assert result["confidence"] == CONFIDENCE_LAST_PURCHASE
    assert result["disclaimer"] == FORECAST_DISCLAIMER


def test_compute_next_due_rolls_forward_overdue_cycles() -> None:
    # Anchor far in the past: roll forward until within one cycle of *now*.
    result = compute_next_due(
        last_purchase_date="2024-01-01",
        periodicity_weeks=26,
        now=NOW,
    )
    assert result is not None
    assert result["next_due_at"] >= NOW - timedelta(weeks=26)
    assert result["next_due_at"] <= NOW + timedelta(weeks=26)


def test_compute_next_due_falls_back_to_construction_year() -> None:
    result = compute_next_due(
        periodicity_weeks=52,
        recommended_quantity=2,
        construction_year=2024,
        now=NOW,
    )
    assert result is not None
    assert result["anchor_source"] == "construction_year"
    assert result["confidence"] == CONFIDENCE_CONSTRUCTION_YEAR
    assert result["anchor_date"] == datetime(2024, 1, 1)
    # 2024-01-01 + 52w ≈ 2024-12-30; rolled forward past NOW → ~2025-12-29
    assert result["next_due_at"].year >= 2025


def test_compute_next_due_requires_periodicity() -> None:
    assert compute_next_due(last_purchase_date="2026-01-01", now=NOW) is None
    assert compute_next_due(construction_year=2020, now=NOW) is None


def test_apply_next_due_to_record_attaches_meta() -> None:
    record = apply_next_due_to_record(
        {
            "customer_key": "mogul",
            "part_family": "injector strip",
            "periodicity_weeks": 13,
            "recommended_quantity": 1,
            "last_document_date": "2026-04-01",
        },
        now=NOW,
    )
    assert record["next_due_at"] == datetime(2026, 7, 1)
    assert record["meta_data"]["forecast"]["anchor_source"] == "last_purchase"
    assert record["meta_data"]["forecast"]["confidence"] == CONFIDENCE_LAST_PURCHASE


def test_next_due_items_sorted_and_persisted_fallback() -> None:
    items = next_due_items_for_records(
        [
            {
                "customer_key": "a",
                "part_family": "belts",
                "next_due_at": "2026-09-01",
            },
            {
                "customer_key": "b",
                "part_family": "strips",
                "periodicity_weeks": 4,
                "last_purchase_date": "2026-06-10",
                "recommended_quantity": 3,
            },
        ],
        now=NOW,
    )
    assert len(items) == 2
    assert items[0]["next_due_at"] <= items[1]["next_due_at"]
    assert items[0]["part_family"] == "strips"
    assert items[1]["anchor_source"] == "persisted"


def test_resolve_conversion_proxy_prefers_observed_impacts() -> None:
    observed = resolve_conversion_proxy(
        impact_counts={"order": 2, "lost": 2, "response": 0, "quote": 0, "no_response": 0}
    )
    assert observed["conversion_proxy"] == 0.5
    assert observed["conversion_proxy_source"] == "observed_impacts"

    fallback = resolve_conversion_proxy(impact_counts={})
    assert fallback["conversion_proxy"] == CLIENT360_ADDRESSABLE_WEIGHTS["observed_conversion"]
    assert fallback["conversion_proxy_source"] == "contract_observed_conversion_weight"


def test_opportunity_addressable_value_uses_factor() -> None:
    value = opportunity_addressable_value(
        {
            "potential_gap_value": 10000,
            "metadata": {"addressable_factors": {"factor": 0.8}},
        }
    )
    assert value == 8000.0


def test_campaign_expected_value_sum_product() -> None:
    result = campaign_expected_value(
        [
            {
                "potential_gap_value": 10000,
                "metadata": {"addressable_factors": {"factor": 0.5}},
            },
            {"potential_gap_value": 4000},
        ],
        impact_counts={},  # contract weight 0.15
    )
    # (10000*0.5 + 4000) * 0.15 = 1350
    assert result["expected_value"] == 1350.0
    assert result["conversion_proxy"] == 0.15
    assert result["disclaimer"] == FORECAST_DISCLAIMER

    with_impacts = campaign_expected_value(
        [{"potential_gap_value": 10000}],
        impact_counts={"order": 1, "lost": 1},
    )
    assert with_impacts["conversion_proxy"] == 0.5
    assert with_impacts["expected_value"] == 5000.0


def test_mail_follow_up_reminder_date_math() -> None:
    sent_at = NOW - timedelta(days=20)
    assert mail_follow_up_due_at(sent_at, delay_days=14) == sent_at + timedelta(days=14)

    due = mail_follow_up_reminder(
        sent_at=sent_at,
        delay_days=14,
        now=NOW,
        opportunity_id="opp-1",
        opportunity_label="Septona - wear belts",
        customer_key="septona",
        mail_draft_id="draft-1",
        mail_draft_label="Relance PDR",
    )
    assert due is not None
    assert due["type"] == "draft_no_response"
    assert due["metrics"]["days_since_sent"] == 20
    assert due["metrics"]["open_tracking"] is False
    assert due["metrics"]["follow_up_mode"] == "suivi manuel"

    too_soon = mail_follow_up_reminder(
        sent_at=NOW - timedelta(days=3),
        delay_days=14,
        now=NOW,
        opportunity_id="opp-1",
    )
    assert too_soon is None

    responded = mail_follow_up_reminder(
        sent_at=sent_at,
        delay_days=14,
        now=NOW,
        opportunity_id="opp-1",
        responded=True,
    )
    assert responded is None
