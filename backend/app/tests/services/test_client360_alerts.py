from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from app.models.client360 import Client360MailDraft, Client360Opportunity
from app.models.workspace import Workspace
from app.services.client360_alerts import (
    DEFAULT_ALERT_THRESHOLDS,
    alert_thresholds,
    alerts_payload,
    compute_alerts,
)
from app.services.client360_pdr import summary_payload


NOW = datetime(2026, 7, 8, 12, 0, 0)


def _seed_workspace(db_session, *, slug: str = "andritz", settings: dict | None = None) -> Workspace:
    workspace = Workspace(id=str(uuid4()), name=slug.title(), slug=slug, settings=settings or {})
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _seed_opportunity(db_session, workspace: Workspace, **overrides) -> Client360Opportunity:
    payload = {
        "id": str(uuid4()),
        "workspace_id": workspace.id,
        "customer_key": "septona",
        "customer_name": "Septona",
        "country": "Greece",
        "hub": "EMEA",
        "technology": "JETLACE",
        "part_family": "wear belts",
        "part_reference": "PDR-001",
        "installed_quantity": 10,
        "recommended_quantity": 2,
        "periodicity_weeks": 4,
        "delivery_time_weeks": 6,
        "sales_known_qty": 8,
        "sales_known_value": 1200,
        "confidence_label": "medium",
        "status": "detected",
        "data_gaps": [],
    }
    payload.update(overrides)
    opportunity = Client360Opportunity(**payload)
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def _alerts_by_type(alerts: list[dict]) -> dict[str, dict]:
    return {alert["type"]: alert for alert in alerts}


def test_due_soon_alert_fires_within_delivery_window(db_session) -> None:
    workspace = _seed_workspace(db_session)
    # delivery 6 weeks + default margin 2 weeks -> 8 week (56 day) window.
    opportunity = _seed_opportunity(
        db_session,
        workspace,
        next_due_at=NOW + timedelta(days=30),
    )

    alerts = compute_alerts(db_session, workspace, now=NOW)
    by_type = _alerts_by_type(alerts)

    assert "due_soon" in by_type
    alert = by_type["due_soon"]
    assert alert["opportunity_id"] == opportunity.id
    assert alert["opportunity_label"] == "Septona - wear belts"
    assert alert["severity"] == "medium"
    assert alert["metrics"]["days_until_due"] == 30
    assert alert["metrics"]["overdue"] is False


def test_due_soon_alert_escalates_when_overdue(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, next_due_at=NOW - timedelta(days=5))

    by_type = _alerts_by_type(compute_alerts(db_session, workspace, now=NOW))

    assert by_type["due_soon"]["severity"] == "high"
    assert by_type["due_soon"]["title"] == "Echeance depassee"
    assert by_type["due_soon"]["metrics"]["overdue"] is True


def test_due_soon_ignores_far_dates_and_closed_status(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, next_due_at=NOW + timedelta(days=200))
    _seed_opportunity(
        db_session,
        workspace,
        customer_key="closed",
        status="won",
        next_due_at=NOW + timedelta(days=10),
    )

    types = {alert["type"] for alert in compute_alerts(db_session, workspace, now=NOW)}
    assert "due_soon" not in types


def test_long_delivery_alert_uses_threshold(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, delivery_time_weeks=20, next_due_at=None)

    by_type = _alerts_by_type(compute_alerts(db_session, workspace, now=NOW))

    assert "long_delivery" in by_type
    assert by_type["long_delivery"]["metrics"]["delivery_time_weeks"] == 20
    assert by_type["long_delivery"]["metrics"]["threshold_weeks"] == 12


def test_incomplete_data_alert_only_on_high_confidence(db_session) -> None:
    workspace = _seed_workspace(db_session)
    # High confidence but missing periodicity + recommended qty -> blocking gaps.
    _seed_opportunity(
        db_session,
        workspace,
        confidence_label="high",
        periodicity_weeks=None,
        recommended_quantity=None,
        next_due_at=None,
    )
    # Same gaps on a medium confidence opportunity must not raise the blocking alert.
    _seed_opportunity(
        db_session,
        workspace,
        customer_key="medium",
        confidence_label="medium",
        periodicity_weeks=None,
        recommended_quantity=None,
        next_due_at=None,
    )

    alerts = compute_alerts(db_session, workspace, now=NOW)
    incomplete = [alert for alert in alerts if alert["type"] == "incomplete_data"]

    assert len(incomplete) == 1
    assert incomplete[0]["metrics"]["confidence_label"] == "high"
    assert "periodicity_missing" in incomplete[0]["metrics"]["data_gaps"]


def test_draft_no_response_alert_references_draft(db_session) -> None:
    workspace = _seed_workspace(db_session)
    opportunity = _seed_opportunity(db_session, workspace, next_due_at=None, status="sent")
    draft = Client360MailDraft(
        id=str(uuid4()),
        workspace_id=workspace.id,
        opportunity_id=opportunity.id,
        subject="Maintenance preventive - wear belts",
        generated_body="Bonjour,",
        status="sent",
        sent_at=NOW - timedelta(days=20),
    )
    db_session.add(draft)
    db_session.flush()

    by_type = _alerts_by_type(compute_alerts(db_session, workspace, now=NOW))

    assert "draft_no_response" in by_type
    alert = by_type["draft_no_response"]
    assert alert["mail_draft_id"] == draft.id
    assert alert["mail_draft_label"] == "Maintenance preventive - wear belts"
    assert alert["metrics"]["days_since_sent"] == 20


def test_draft_no_response_skipped_when_opportunity_responded(db_session) -> None:
    workspace = _seed_workspace(db_session)
    opportunity = _seed_opportunity(db_session, workspace, next_due_at=None, status="quote_requested")
    db_session.add(
        Client360MailDraft(
            id=str(uuid4()),
            workspace_id=workspace.id,
            opportunity_id=opportunity.id,
            subject="Relance",
            generated_body="Bonjour,",
            status="sent",
            sent_at=NOW - timedelta(days=30),
        )
    )
    db_session.flush()

    types = {alert["type"] for alert in compute_alerts(db_session, workspace, now=NOW)}
    assert "draft_no_response" not in types


def test_thresholds_are_workspace_configurable(db_session) -> None:
    workspace = _seed_workspace(
        db_session,
        settings={
            "client360_pdr_scope": {
                "alert_thresholds": {
                    "long_delivery_weeks": 4,
                    "no_response_days": 3,
                    "data_gap_confidence_labels": ["high", "medium"],
                }
            }
        },
    )
    resolved = alert_thresholds(workspace)
    assert resolved["long_delivery_weeks"] == 4
    assert resolved["no_response_days"] == 3
    assert resolved["data_gap_confidence_labels"] == ["high", "medium"]
    # Untouched thresholds keep their defaults.
    assert resolved["due_soon_margin_weeks"] == DEFAULT_ALERT_THRESHOLDS["due_soon_margin_weeks"]

    # A 8-week delivery now trips the lowered long-delivery threshold.
    _seed_opportunity(db_session, workspace, delivery_time_weeks=8, next_due_at=None)
    by_type = _alerts_by_type(compute_alerts(db_session, workspace, now=NOW))
    assert "long_delivery" in by_type


def test_alerts_payload_shape_and_summary_integration(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, next_due_at=NOW - timedelta(days=2))

    payload = alerts_payload(db_session, workspace, now=NOW)
    assert set(payload.keys()) == {"alerts", "counts", "thresholds", "generated_at"}
    assert payload["counts"]["total"] == len(payload["alerts"])
    assert payload["counts"]["by_type"]["due_soon"] == 1
    assert payload["counts"]["by_severity"]["high"] >= 1

    summary = summary_payload(db_session, workspace, include_mail_ai=False)
    assert "alerts" in summary
    assert summary["alerts"]["total"] >= 1
    assert "counts" in summary["alerts"]
    assert isinstance(summary["alerts"]["items"], list)
