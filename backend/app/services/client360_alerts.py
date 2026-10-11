"""Client360 PDR alert engine.

Alerts are computed on the fly from the existing opportunities and mail drafts.
There is no dedicated table in v1: the raw material (``next_due_at``,
``delivery_time_weeks``, opportunity ``status``, draft ``status`` / ``sent_at``,
``data_gaps``) already lives on the persisted rows.

Four alert families are surfaced:

1. ``due_soon``       -- ``next_due_at`` falls within ``delivery_time_weeks`` plus a
                          configurable margin (or a fallback window when the lead
                          time is unknown); overdue opportunities are escalated.
2. ``long_delivery``  -- ``delivery_time_weeks`` above a configurable threshold.
3. ``draft_no_response`` -- a mail draft was sent (``status == 'sent'``) more than
                          ``no_response_days`` ago while the opportunity never moved
                          to ``responded`` / ``quote_requested`` / ``won``.
4. ``incomplete_data`` -- blocking ``data_gaps`` on high-confidence opportunities.

Thresholds are configurable via
``workspace.settings.client360_pdr_scope.alert_thresholds`` with sensible
defaults defined in :data:`DEFAULT_ALERT_THRESHOLDS`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.client360 import Client360MailDraft, Client360Opportunity
from app.models.workspace import Workspace
from app.services.client360_forecast import mail_follow_up_reminder
from app.services.client360_pdr import opportunity_data_gaps


DEFAULT_ALERT_THRESHOLDS: dict[str, Any] = {
    # Extra weeks added on top of the lead time before an approaching due date fires.
    "due_soon_margin_weeks": 2.0,
    # Window used when the opportunity has no known delivery lead time.
    "due_soon_fallback_weeks": 8.0,
    # Delivery lead time (weeks) above which delivery is considered long.
    "long_delivery_weeks": 12.0,
    # Days after a draft was sent without any commercial response before we relance.
    "no_response_days": 14,
    # Confidence labels for which non-empty data gaps are treated as blocking.
    "data_gap_confidence_labels": ["high"],
}

ALERT_TYPES = ("due_soon", "long_delivery", "draft_no_response", "incomplete_data")
ALERT_SEVERITIES = ("high", "medium", "low")
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Opportunity statuses that are commercially closed: no due/delivery alert needed.
_CLOSED_STATUSES = {"won", "lost", "dismissed"}
# Statuses that indicate a draft already got a reaction: no relance needed.
_RESPONDED_STATUSES = {"responded", "quote_requested", "won", "lost", "dismissed"}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fmt_date(value: Optional[datetime]) -> str:
    return value.strftime("%d/%m/%Y") if value else "?"


def alert_thresholds(workspace: Workspace) -> dict[str, Any]:
    """Resolve alert thresholds from the workspace scope settings with defaults."""
    scope_settings = _as_dict(_as_dict(getattr(workspace, "settings", None)).get("client360_pdr_scope"))
    configured = _as_dict(scope_settings.get("alert_thresholds"))
    resolved = dict(DEFAULT_ALERT_THRESHOLDS)
    for key in ("due_soon_margin_weeks", "due_soon_fallback_weeks", "long_delivery_weeks"):
        value = _as_float(configured.get(key))
        if value is not None and value >= 0:
            resolved[key] = value
    days = _as_int(configured.get("no_response_days"))
    if days is not None and days >= 0:
        resolved["no_response_days"] = days
    labels = configured.get("data_gap_confidence_labels")
    if isinstance(labels, list) and labels:
        resolved["data_gap_confidence_labels"] = [str(item) for item in labels if item]
    return resolved


def _opportunity_label(opportunity: Client360Opportunity) -> str:
    parts = [opportunity.customer_name or opportunity.customer_key, opportunity.part_family]
    return " - ".join(str(part) for part in parts if part) or (opportunity.customer_key or opportunity.id)


def _base_alert(
    *,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    opportunity: Client360Opportunity,
    marker: str,
    due_at: Optional[datetime] = None,
    mail_draft_id: Optional[str] = None,
    mail_draft_label: Optional[str] = None,
    metrics: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "id": f"{alert_type}:{marker}",
        "type": alert_type,
        "severity": severity,
        "title": title,
        "message": message,
        "opportunity_id": opportunity.id,
        "opportunity_label": _opportunity_label(opportunity),
        "customer_key": opportunity.customer_key,
        "mail_draft_id": mail_draft_id,
        "mail_draft_label": mail_draft_label,
        "due_at": due_at.isoformat() if due_at else None,
        "metrics": metrics or {},
    }


def _due_soon_alert(
    opportunity: Client360Opportunity,
    now: datetime,
    thresholds: dict[str, Any],
) -> Optional[dict[str, Any]]:
    due_at = opportunity.next_due_at
    if due_at is None or opportunity.status in _CLOSED_STATUSES:
        return None
    delivery = _as_float(opportunity.delivery_time_weeks)
    lead_weeks = delivery if delivery is not None else float(thresholds["due_soon_fallback_weeks"])
    window_weeks = lead_weeks + float(thresholds["due_soon_margin_weeks"])
    horizon = now + timedelta(weeks=window_weeks)
    if due_at > horizon:
        return None
    days_until = (due_at - now).days
    overdue = days_until < 0
    if overdue:
        title = "Echeance depassee"
        message = f"{_opportunity_label(opportunity)} : echeance depassee depuis {abs(days_until)} j (prevue le {_fmt_date(due_at)})."
        severity = "high"
    else:
        title = "Echeance proche"
        message = f"{_opportunity_label(opportunity)} : echeance dans {days_until} j (le {_fmt_date(due_at)})."
        severity = "high" if days_until <= 14 else "medium"
    return _base_alert(
        alert_type="due_soon",
        severity=severity,
        title=title,
        message=message,
        opportunity=opportunity,
        marker=opportunity.id,
        due_at=due_at,
        metrics={
            "days_until_due": days_until,
            "overdue": overdue,
            "delivery_time_weeks": delivery,
            "window_weeks": round(window_weeks, 2),
        },
    )


def _long_delivery_alert(
    opportunity: Client360Opportunity,
    thresholds: dict[str, Any],
) -> Optional[dict[str, Any]]:
    delivery = _as_float(opportunity.delivery_time_weeks)
    threshold = float(thresholds["long_delivery_weeks"])
    if delivery is None or delivery <= threshold or opportunity.status in _CLOSED_STATUSES:
        return None
    return _base_alert(
        alert_type="long_delivery",
        severity="medium",
        title="Delai de livraison long",
        message=(
            f"{_opportunity_label(opportunity)} : delai de livraison de {delivery:g} semaines "
            f"(seuil {threshold:g})."
        ),
        opportunity=opportunity,
        marker=opportunity.id,
        due_at=opportunity.next_due_at,
        metrics={"delivery_time_weeks": delivery, "threshold_weeks": threshold},
    )


def _incomplete_data_alert(
    opportunity: Client360Opportunity,
    thresholds: dict[str, Any],
) -> Optional[dict[str, Any]]:
    blocking_labels = {str(label) for label in thresholds["data_gap_confidence_labels"]}
    if (opportunity.confidence_label or "") not in blocking_labels:
        return None
    if opportunity.status in _CLOSED_STATUSES:
        return None
    gaps = opportunity_data_gaps(opportunity)
    if not gaps:
        return None
    return _base_alert(
        alert_type="incomplete_data",
        severity="medium",
        title="Donnees incompletes bloquantes",
        message=(
            f"{_opportunity_label(opportunity)} : donnees manquantes ({', '.join(gaps)}) "
            f"sur opportunite haute confiance."
        ),
        opportunity=opportunity,
        marker=opportunity.id,
        metrics={"data_gaps": gaps, "confidence_label": opportunity.confidence_label},
    )


def _draft_no_response_alert(
    draft: Client360MailDraft,
    opportunity: Optional[Client360Opportunity],
    now: datetime,
    thresholds: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if draft.status != "sent" or draft.sent_at is None:
        return None
    if opportunity is None:
        return None
    reminder = mail_follow_up_reminder(
        sent_at=draft.sent_at,
        delay_days=int(thresholds["no_response_days"]),
        now=now,
        opportunity_id=opportunity.id,
        opportunity_label=_opportunity_label(opportunity),
        customer_key=opportunity.customer_key,
        mail_draft_id=draft.id,
        mail_draft_label=draft.subject,
        responded=opportunity.status in _RESPONDED_STATUSES,
    )
    if reminder is None:
        return None
    # Preserve the stable alert id / marker contract used by the UI.
    reminder["id"] = f"draft_no_response:{draft.id}"
    return reminder


def _sort_key(alert: dict[str, Any]) -> tuple[int, float]:
    severity = _SEVERITY_ORDER.get(alert["severity"], 9)
    due_at = alert.get("due_at")
    if due_at:
        try:
            due_ts = datetime.fromisoformat(str(due_at)).timestamp()
        except ValueError:
            due_ts = float("inf")
    else:
        due_ts = float("inf")
    return (severity, due_ts)


def compute_alerts(
    db: DBSession,
    workspace: Workspace,
    *,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Compute the full list of Client360 PDR alerts for a workspace."""
    now = now or datetime.utcnow()
    thresholds = alert_thresholds(workspace)
    opportunities = (
        db.query(Client360Opportunity)
        .filter(Client360Opportunity.workspace_id == workspace.id)
        .all()
    )
    opp_by_id = {opp.id: opp for opp in opportunities}

    alerts: list[dict[str, Any]] = []
    for opportunity in opportunities:
        for alert in (
            _due_soon_alert(opportunity, now, thresholds),
            _long_delivery_alert(opportunity, thresholds),
            _incomplete_data_alert(opportunity, thresholds),
        ):
            if alert:
                alerts.append(alert)

    drafts = (
        db.query(Client360MailDraft)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.status == "sent",
        )
        .all()
    )
    for draft in drafts:
        alert = _draft_no_response_alert(draft, opp_by_id.get(draft.opportunity_id), now, thresholds)
        if alert:
            alerts.append(alert)

    alerts.sort(key=_sort_key)
    return alerts


def alert_counts(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for alert in alerts:
        by_type[alert["type"]] = by_type.get(alert["type"], 0) + 1
        by_severity[alert["severity"]] = by_severity.get(alert["severity"], 0) + 1
    return {"total": len(alerts), "by_type": by_type, "by_severity": by_severity}


def alerts_payload(
    db: DBSession,
    workspace: Workspace,
    *,
    now: Optional[datetime] = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Full alert payload for the ``GET /alerts`` endpoint."""
    generated_at = now or datetime.utcnow()
    alerts = compute_alerts(db, workspace, now=generated_at)
    capped = alerts[: max(1, min(limit, 500))]
    return {
        "alerts": capped,
        "counts": alert_counts(alerts),
        "thresholds": alert_thresholds(workspace),
        "generated_at": generated_at.isoformat(),
    }


def alerts_summary_block(
    db: DBSession,
    workspace: Workspace,
    *,
    now: Optional[datetime] = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Compact alert block embedded in the Client360 summary payload."""
    generated_at = now or datetime.utcnow()
    alerts = compute_alerts(db, workspace, now=generated_at)
    return {
        "total": len(alerts),
        "counts": alert_counts(alerts),
        "items": alerts[: max(1, min(limit, 100))],
        "generated_at": generated_at.isoformat(),
    }
