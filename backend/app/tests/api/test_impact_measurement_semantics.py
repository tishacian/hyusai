"""Measurement boundaries for Impact and the transient Hypervisor preview."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

from app.api.v1.endpoints import hypervisor
from app.api.v1.endpoints.hypervisor import WhatIfRequest, simulate_what_if
from app.api.v1.endpoints.impact import _aggregate
from app.models.run import Run


def _completed_run(
    *,
    run_id: str,
    workspace_id: str,
    cost: float | None,
    value: float | None,
    value_source: str,
) -> Run:
    now = datetime.utcnow()
    return Run(
        id=run_id,
        workspace_id=workspace_id,
        status="completed",
        started_at=now,
        completed_at=now,
        cost_internal=cost,
        value_estimated=value,
        value_source=value_source,
    )


def test_impact_excludes_unset_value_from_the_evidenced_aggregate(db_session):
    workspace_id = "ws-impact-value-source"
    db_session.add_all(
        [
            _completed_run(
                run_id="run-impact-auto",
                workspace_id=workspace_id,
                cost=2.0,
                value=25.0,
                value_source="auto",
            ),
            _completed_run(
                run_id="run-impact-unset",
                workspace_id=workspace_id,
                cost=3.0,
                value=999.0,
                value_source="unset",
            ),
        ]
    )
    db_session.commit()

    impact = _aggregate(db_session, workspace_id, period="all")

    assert impact["runs_count"] == 2
    assert impact["total_cost"] == 5.0
    assert impact["estimated_value"] == 25.0
    assert impact["roi"] == 4.0
    assert impact["measurement_states"]["estimated_value"] == "available"


def test_impact_keeps_absent_metrics_null_and_legacy_what_if_is_retired(
    db_session,
    monkeypatch,
):
    workspace_id = "ws-impact-unmeasured"
    db_session.add(
        _completed_run(
            run_id="run-impact-cost-only",
            workspace_id=workspace_id,
            cost=10.0,
            value=500.0,
            value_source="unset",
        )
    )
    db_session.commit()

    impact = _aggregate(db_session, workspace_id, period="all")
    assert impact["total_cost"] == 10.0
    assert impact["estimated_value"] is None
    assert impact["total_revenue"] is None
    assert impact["roi"] is None
    assert impact["measurement_states"] == {
        "total_cost": "available",
        "estimated_value": "not_measured",
        "total_revenue": "not_measured",
    }

    monkeypatch.setattr(hypervisor, "enforce_action", lambda *_args, **_kwargs: None)
    preview = asyncio.run(
        simulate_what_if(
            WhatIfRequest(
                scope="portfolio",
                target_id=None,
                levers={"cost_factor": 1.2, "value_factor": 1.5},
            ),
            workspace=SimpleNamespace(id=workspace_id),
            user=SimpleNamespace(id="impact-user"),
            db=db_session,
        )
    )
    assert preview["state"] == "not_configured"
    assert preview["measured"] is False
    assert preview["base"] is None
    assert preview["projected"] is None
    assert preview["reason"] == "authoritative_value_loop_required"

    empty_preview = asyncio.run(
        simulate_what_if(
            WhatIfRequest(scope="portfolio", target_id=None, levers={}),
            workspace=SimpleNamespace(id="ws-impact-empty"),
            user=SimpleNamespace(id="impact-user"),
            db=db_session,
        )
    )
    assert empty_preview["state"] == "not_configured"
    assert empty_preview["base"] is None
    assert empty_preview["projected"] is None
