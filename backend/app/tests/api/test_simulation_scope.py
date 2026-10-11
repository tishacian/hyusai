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
    monkeypatch.setattr(module, "enforce_action", lambda *_args, **_kwargs: None)
    db = object()
    payload = await endpoint(
        body_type(scope="system", target_id="system-123", levers={}),
        workspace=SimpleNamespace(id="workspace-123"),
        user=SimpleNamespace(id="user-123"),
        db=db,
    )

    assert payload["kind"] == "simulation"
    assert payload["state"] == "not_configured"
    assert payload["measured"] is False
    assert payload["scope"] == "system"
    assert payload["target_id"] == "system-123"
    assert payload["model"] is None
    assert payload["provenance"] is None
    assert payload["confidence"] is None
    assert payload["reason"] == "authoritative_value_loop_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "body_type", "endpoint"),
    [
        (control_plane, control_plane.SimulateBody, control_plane.simulate),
        (hypervisor, hypervisor.WhatIfRequest, hypervisor.simulate_what_if),
    ],
)
async def test_simulation_routes_preserve_missing_measurements(
    monkeypatch,
    module,
    body_type,
    endpoint,
):
    monkeypatch.setattr(module, "enforce_action", lambda *_args, **_kwargs: None)

    payload = await endpoint(
        body_type(scope="portfolio", levers={}),
        workspace=SimpleNamespace(id="workspace-empty"),
        user=SimpleNamespace(id="user-empty"),
        db=object(),
    )

    assert payload["state"] == "not_configured"
    assert payload["base"] is None
    assert payload["projected"] is None


@pytest.mark.parametrize("body_type", [control_plane.SimulateBody, hypervisor.WhatIfRequest])
def test_system_simulation_requires_a_target(body_type):
    with pytest.raises(ValidationError, match="target_id is required"):
        body_type(scope="system")
