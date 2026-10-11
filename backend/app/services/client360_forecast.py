"""Client360 deterministic forecasts (no ML, no mail open tracking).

Three explainable surfaces:

1. Part due dates — ``last_purchase_date + periodicity_weeks`` (fallback:
   machine ``construction_year`` with lower confidence).
2. Campaign expected value — ``Σ addressable_value × conversion_proxy``.
3. Mail follow-up reminders — ``sent_at + configurable delay`` → alert-shaped
   items (manual follow-up; no open/click tracking).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional

from app.services.client360_contract import CLIENT360_ADDRESSABLE_WEIGHTS

FORECAST_DISCLAIMER = (
    "estimation deterministe, a recaler des les premiers retours"
)
FOLLOW_UP_MANUAL_BADGE = "suivi manuel"
DEFAULT_FOLLOW_UP_DELAY_DAYS = 14

# Confidence when anchored on last purchase vs construction year only.
CONFIDENCE_LAST_PURCHASE = 0.75
CONFIDENCE_CONSTRUCTION_YEAR = 0.4


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_non_negative_float(value: Any) -> Optional[float]:
    number = _as_float(value)
    if number is None or number < 0:
        return None
    return number


def parse_forecast_date(value: Any) -> Optional[datetime]:
    """Parse a date/datetime used as a forecast anchor."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        try:
            return datetime(int(value.year), int(value.month), int(value.day))
        except (TypeError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    # Common spreadsheet forms: YYYY-MM-DD, DD/MM/YYYY, YYYY/MM/DD
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_construction_year(value: Any) -> Optional[int]:
    """Extract a 19xx/20xx construction year from Machine ConstructYear fields."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value if 1900 <= value <= 2100 else None
    if isinstance(value, float):
        year = int(value)
        return year if 1900 <= year <= 2100 else None
    if hasattr(value, "year"):
        try:
            year = int(value.year)
            return year if 1900 <= year <= 2100 else None
        except (TypeError, ValueError):
            return None
    match = re.search(r"(19|20)\d{2}", str(value))
    if not match:
        return None
    year = int(match.group(0))
    return year if 1900 <= year <= 2100 else None


def last_purchase_date_from_record(record: dict[str, Any]) -> Optional[datetime]:
    """Resolve last purchase date from sales_orders / opportunity record fields."""
    for key in (
        "last_purchase_date",
        "last_document_date",
        "document_date",
    ):
        parsed = parse_forecast_date(record.get(key))
        if parsed is not None:
            return parsed
    return None


def compute_next_due(
    *,
    last_purchase_date: Any = None,
    periodicity_weeks: Any = None,
    recommended_quantity: Any = None,
    construction_year: Any = None,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Compute deterministic next due date + recommended qty for a part family.

    Prefer ``last_purchase_date + periodicity_weeks``. When no purchase history
    exists, fall back to ``construction_year-01-01 + periodicity_weeks`` with
    lower confidence.
    """
    weeks = _as_float(periodicity_weeks)
    if weeks is None or weeks <= 0:
        return None

    anchor = parse_forecast_date(last_purchase_date)
    anchor_source = "last_purchase"
    confidence = CONFIDENCE_LAST_PURCHASE
    if anchor is None:
        year = parse_construction_year(construction_year)
        if year is None:
            return None
        anchor = datetime(year, 1, 1)
        anchor_source = "construction_year"
        confidence = CONFIDENCE_CONSTRUCTION_YEAR

    delta = timedelta(weeks=float(weeks))
    next_due = anchor + delta
    # Roll forward until the due date is not far in the past relative to *now*
    # (keep one overdue cycle so due_soon/overdue alerts still fire).
    reference = now or datetime.utcnow()
    while next_due < reference - delta:
        next_due = next_due + delta

    qty = _as_non_negative_float(recommended_quantity)
    return {
        "next_due_at": next_due,
        "next_due_at_iso": next_due.isoformat(),
        "recommended_qty": qty,
        "periodicity_weeks": weeks,
        "anchor_date": anchor,
        "anchor_date_iso": anchor.isoformat(),
        "anchor_source": anchor_source,
        "confidence": confidence,
        "disclaimer": FORECAST_DISCLAIMER,
    }


def apply_next_due_to_record(
    record: dict[str, Any],
    *,
    now: Optional[datetime] = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Attach computed ``next_due_at`` (+ forecast meta) onto an engine record."""
    updated = dict(record)
    if updated.get("next_due_at") and not overwrite:
        return updated
    forecast = compute_next_due(
        last_purchase_date=last_purchase_date_from_record(updated),
        periodicity_weeks=updated.get("periodicity_weeks"),
        recommended_quantity=updated.get("recommended_quantity"),
        construction_year=updated.get("construction_year") or updated.get("ConstructYear"),
        now=now,
    )
    if forecast is None:
        return updated
    updated["next_due_at"] = forecast["next_due_at"]
    meta = _as_dict(updated.get("meta_data") or updated.get("metadata"))
    meta["forecast"] = {
        "anchor_source": forecast["anchor_source"],
        "anchor_date": forecast["anchor_date_iso"],
        "confidence": forecast["confidence"],
        "recommended_qty": forecast["recommended_qty"],
        "disclaimer": FORECAST_DISCLAIMER,
    }
    updated["meta_data"] = meta
    return updated


def next_due_items_for_records(
    records: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Build a sorted 'À prévoir' list for customer_payload / chat helpers."""
    items: list[dict[str, Any]] = []
    for record in records:
        forecast = compute_next_due(
            last_purchase_date=last_purchase_date_from_record(record),
            periodicity_weeks=record.get("periodicity_weeks"),
            recommended_quantity=record.get("recommended_quantity"),
            construction_year=record.get("construction_year") or record.get("ConstructYear"),
            now=now,
        )
        if forecast is None:
            # Already-persisted next_due_at on opportunities still surfaces.
            existing = parse_forecast_date(record.get("next_due_at"))
            if existing is None:
                continue
            forecast = {
                "next_due_at": existing,
                "next_due_at_iso": existing.isoformat(),
                "recommended_qty": _as_non_negative_float(record.get("recommended_quantity")),
                "periodicity_weeks": _as_float(record.get("periodicity_weeks")),
                "anchor_date": None,
                "anchor_date_iso": None,
                "anchor_source": "persisted",
                "confidence": None,
                "disclaimer": FORECAST_DISCLAIMER,
            }
        items.append(
            {
                "customer_key": record.get("customer_key"),
                "customer_name": record.get("customer_name"),
                "part_family": record.get("part_family") or record.get("pdr_family"),
                "part_reference": record.get("part_reference"),
                "next_due_at": forecast["next_due_at_iso"],
                "recommended_qty": forecast["recommended_qty"],
                "periodicity_weeks": forecast["periodicity_weeks"],
                "anchor_source": forecast["anchor_source"],
                "confidence": forecast["confidence"],
                "disclaimer": FORECAST_DISCLAIMER,
            }
        )
    items.sort(key=lambda item: item.get("next_due_at") or "")
    return items


def resolve_conversion_proxy(
    *,
    impact_counts: Optional[dict[str, Any]] = None,
    observed_rate: Optional[float] = None,
    contract_weight: Optional[float] = None,
) -> dict[str, Any]:
    """Pick conversion_proxy: observed impacts rate if any, else contract weight."""
    weight = _as_non_negative_float(contract_weight)
    if weight is None:
        weight = float(CLIENT360_ADDRESSABLE_WEIGHTS["observed_conversion"])

    counts = {str(k): int(v or 0) for k, v in _as_dict(impact_counts).items()}
    orders = counts.get("order", 0)
    signals = (
        orders
        + counts.get("lost", 0)
        + counts.get("response", 0)
        + counts.get("quote", 0)
        + counts.get("no_response", 0)
    )
    if signals > 0:
        rate = round(orders / signals, 4) if observed_rate is None else round(
            max(0.0, min(1.0, float(observed_rate))), 4
        )
        return {
            "conversion_proxy": rate,
            "conversion_proxy_source": "observed_impacts",
            "impact_signals": signals,
            "impact_orders": orders,
        }

    if observed_rate is not None:
        rate = round(max(0.0, min(1.0, float(observed_rate))), 4)
        return {
            "conversion_proxy": rate,
            "conversion_proxy_source": "observed_impacts",
            "impact_signals": 0,
            "impact_orders": 0,
        }

    return {
        "conversion_proxy": round(max(0.0, min(1.0, weight)), 4),
        "conversion_proxy_source": "contract_observed_conversion_weight",
        "impact_signals": 0,
        "impact_orders": 0,
    }


def opportunity_addressable_value(item: dict[str, Any]) -> Optional[float]:
    """Monetary addressable value for expected-value summation (EUR)."""
    gap_value = _as_non_negative_float(item.get("potential_gap_value"))
    meta = _as_dict(item.get("metadata") or item.get("meta_data"))
    factors = _as_dict(meta.get("addressable_factors"))
    factor = _as_non_negative_float(factors.get("factor"))
    if gap_value is not None and factor is not None:
        return round(gap_value * factor, 2)

    addressable_qty = _as_non_negative_float(item.get("potential_addressable"))
    gap_qty = _as_non_negative_float(item.get("potential_gap_qty"))
    if gap_value is not None and addressable_qty is not None and gap_qty and gap_qty > 0:
        return round(gap_value * (addressable_qty / gap_qty), 2)

    if gap_value is not None:
        return round(gap_value, 2)
    return None


def campaign_expected_value(
    opportunities: list[dict[str, Any]],
    *,
    impact_counts: Optional[dict[str, Any]] = None,
    observed_rate: Optional[float] = None,
    contract_weight: Optional[float] = None,
    conversion_proxy: Optional[float] = None,
) -> dict[str, Any]:
    """``expected_value = Σ addressable_value × conversion_proxy``."""
    if conversion_proxy is None:
        resolved = resolve_conversion_proxy(
            impact_counts=impact_counts,
            observed_rate=observed_rate,
            contract_weight=contract_weight,
        )
    else:
        resolved = {
            "conversion_proxy": round(max(0.0, min(1.0, float(conversion_proxy))), 4),
            "conversion_proxy_source": "explicit",
            "impact_signals": 0,
            "impact_orders": 0,
        }

    proxy = float(resolved["conversion_proxy"])
    total = 0.0
    counted = 0
    for item in opportunities:
        addressable = opportunity_addressable_value(item)
        if addressable is None:
            continue
        total += addressable * proxy
        counted += 1

    return {
        "expected_value": round(total, 2),
        "conversion_proxy": proxy,
        "conversion_proxy_source": resolved["conversion_proxy_source"],
        "addressable_opportunities": counted,
        "disclaimer": FORECAST_DISCLAIMER,
    }


def mail_follow_up_due_at(sent_at: Any, *, delay_days: int = DEFAULT_FOLLOW_UP_DELAY_DAYS) -> Optional[datetime]:
    """Return the datetime when a manual follow-up reminder should fire."""
    sent = parse_forecast_date(sent_at)
    if sent is None:
        return None
    days = max(0, int(delay_days))
    return sent + timedelta(days=days)


def _token(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _customer_matches(row_key: Any, row_name: Any, *, customer_key: str, customer_name: str | None) -> bool:
    key_norm = _token(customer_key)
    name_norm = _token(customer_name)
    row_key_n = _token(row_key)
    row_name_n = _token(row_name)
    if key_norm and (key_norm == row_key_n or key_norm == row_name_n or key_norm in row_name_n):
        return True
    if name_norm and (name_norm == row_key_n or name_norm == row_name_n or name_norm in row_name_n):
        return True
    return False


def customer_next_due(
    db: Any,
    workspace: Any,
    *,
    customer_key: str,
    customer_name: str | None = None,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Due items for a customer (used by ``customer_payload`` Phase-2 hook)."""
    from app.models.client360 import Client360Opportunity

    rows = (
        db.query(Client360Opportunity)
        .filter(Client360Opportunity.workspace_id == workspace.id)
        .all()
    )
    matched: list[dict[str, Any]] = []
    for row in rows:
        if not _customer_matches(
            row.customer_key,
            row.customer_name,
            customer_key=customer_key,
            customer_name=customer_name,
        ):
            continue
        meta = _as_dict(row.meta_data)
        forecast_meta = _as_dict(meta.get("forecast"))
        anchor_source = forecast_meta.get("anchor_source")
        matched.append(
            {
                "customer_key": row.customer_key,
                "customer_name": row.customer_name,
                "part_family": row.part_family,
                "part_reference": row.part_reference,
                "periodicity_weeks": row.periodicity_weeks,
                "recommended_quantity": row.recommended_quantity,
                "next_due_at": row.next_due_at,
                "last_purchase_date": (
                    forecast_meta.get("anchor_date") if anchor_source == "last_purchase" else None
                ),
                "construction_year": (
                    forecast_meta.get("anchor_date")
                    if anchor_source == "construction_year"
                    else meta.get("construction_year")
                ),
            }
        )
    return next_due_items_for_records(matched, now=now)


def mail_follow_up_reminder(
    *,
    sent_at: Any,
    delay_days: int = DEFAULT_FOLLOW_UP_DELAY_DAYS,
    now: Optional[datetime] = None,
    opportunity_id: Optional[str] = None,
    opportunity_label: Optional[str] = None,
    customer_key: Optional[str] = None,
    mail_draft_id: Optional[str] = None,
    mail_draft_label: Optional[str] = None,
    responded: bool = False,
) -> Optional[dict[str, Any]]:
    """Alert-shaped follow-up reminder (no open tracking — manual follow-up)."""
    if responded:
        return None
    sent = parse_forecast_date(sent_at)
    if sent is None:
        return None
    reference = now or datetime.utcnow()
    days = max(0, int(delay_days))
    due_at = sent + timedelta(days=days)
    if reference < due_at:
        return None
    days_since = (reference - sent).days
    label = opportunity_label or customer_key or mail_draft_label or "opportunite"
    return {
        "id": f"draft_no_response:{mail_draft_id or opportunity_id or sent.isoformat()}",
        "type": "draft_no_response",
        "severity": "medium",
        "title": "Relance a prevoir",
        "message": (
            f"{label} : mail envoye le {sent.strftime('%d/%m/%Y')}, "
            f"sans reponse depuis {days_since} j."
        ),
        "opportunity_id": opportunity_id,
        "opportunity_label": opportunity_label,
        "customer_key": customer_key,
        "mail_draft_id": mail_draft_id,
        "mail_draft_label": mail_draft_label,
        "due_at": due_at.isoformat(),
        "metrics": {
            "days_since_sent": days_since,
            "threshold_days": days,
            "sent_at": sent.isoformat(),
            "follow_up_mode": FOLLOW_UP_MANUAL_BADGE,
            "open_tracking": False,
        },
    }
