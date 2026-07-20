"""Scope contracts for deterministic impact previews."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints import control_plane, hypervisor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "body_type", "endpoint", "period"),
    [
        (control_plane, control_plane.SimulateBody, control_plane.simulate, "rolling_30d"),
        (hypervisor, hypervisor.WhatIfRequest, hypervisor.simulate_what_if, "qtd"),
    ],
)
async def test_system_simulation_routes_target_to_system_scope(
    monkeypatch, module, body_type, endpoint, period
):
    observed = {}

    def fake_aggregate(db, workspace_id, *, scope, target_id, period):
        observed.update(
            db=db,
            workspace_id=workspace_id,
            scope=scope,
            target_id=target_id,
            period=period,
        )
        return {"total_cost": 10.0, "estimated_value": 25.0}

    monkeypatch.setattr(module, "_aggregate_for_scope", fake_aggregate)
    db = object()
    payload = await endpoint(
        body_type(scope="system", target_id="system-123", levers={}),
        workspace=SimpleNamespace(id="workspace-123"),
        db=db,
    )

    assert observed == {
        "db": db,
        "workspace_id": "workspace-123",
        "scope": "system",
        "target_id": "system-123",
        "period": period,
    }
    assert payload["kind"] == "simulation"
    assert payload["measured"] is False
    assert payload["provenance"]["scope"] == "system"
    assert payload["provenance"]["target_id"] == "system-123"
    assert payload["model"]["version"] == 1
    assert payload["confidence"] is None


@pytest.mark.parametrize("body_type", [control_plane.SimulateBody, hypervisor.WhatIfRequest])
def test_system_simulation_requires_a_target(body_type):
    with pytest.raises(ValidationError, match="target_id is required"):
        body_type(scope="system")
