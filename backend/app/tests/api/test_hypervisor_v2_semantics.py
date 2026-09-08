"""Measurement and write contracts for Hypervisor V2 series and value bases."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import capabilities, hypervisor
from app.models.capability import Capability
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from scripts import seed_showcase_workspace as showcase_seed


def _seed(db_session, *, with_basis: bool = False, with_cost: bool = True):
    workspace = Workspace(
        id="ws-hypervisor-v2",
        slug="hypervisor-v2",
        name="Hypervisor V2",
        settings={},
    )
    user = User(
        id="user-hypervisor-v2",
        username="hypervisor-v2",
        email="hypervisor-v2@example.test",
    )
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="admin",
        role_template="workspace_admin",
    )
    capability = Capability(
        id="cap-hypervisor-v2",
        workspace_id=workspace.id,
        slug="hypervisor_v2",
        name="Hypervisor V2",
        tier="client",
        output_unit="brief",
        pricing={"unit": "per_outcome", "unit_price": 1.0, "currency": "EUR"},
        value_per_outcome=10.0,
        value_basis=(
            {
                "unit": "brief",
                "hours_per_unit": 0.5,
                "value_per_unit": 10.0,
                "currency": "EUR",
                "declared_by": "seed",
                "declared_at": "2026-07-01T00:00:00",
                "status": "declared",
            }
            if with_basis
            else None
        ),
    )
    system = System(
        id="system-hypervisor-v2",
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Hypervisor V2 System",
        status="active",
    )
    now = datetime.utcnow()
    run = Run(
        id="run-hypervisor-v2",
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        system_id=system.id,
        capability_id=capability.id,
        trigger="manual",
        status="completed",
        decision="approved",
        started_at=now - timedelta(hours=2),
        completed_at=now - timedelta(hours=1),
        cost_internal=2.5 if with_cost else None,
        value_estimated=10.0,
        value_source="auto",
    )
    db_session.add_all([workspace, user, member, capability, system, run])
    db_session.commit()
    return {
        "workspace": workspace,
        "user": user,
        "capability": capability,
        "system": system,
        "run": run,
    }


def _hypervisor_client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(hypervisor.router, prefix="/hypervisor")
    app.dependency_overrides[hypervisor.get_current_workspace] = lambda: workspace
    app.dependency_overrides[hypervisor.get_current_user] = lambda: user
    app.dependency_overrides[hypervisor.get_db] = lambda: db_session
    return TestClient(app)


def _capability_client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(capabilities.router, prefix="/capabilities")
    app.dependency_overrides[capabilities.get_current_workspace] = lambda: workspace
    app.dependency_overrides[capabilities.get_current_user] = lambda: user
    app.dependency_overrides[capabilities.get_db] = lambda: db_session
    return TestClient(app)


def _bucket(response) -> dict:
    systems = response.json()["systems"]
    assert len(systems) == 1
    assert len(systems[0]["buckets"]) == 1
    return systems[0]["buckets"][0]


def test_series_marks_absent_cost_not_measured_and_does_not_emit_zero(db_session):
    seeded = _seed(db_session, with_basis=True, with_cost=False)
    response = _hypervisor_client(
        db_session, seeded["workspace"], seeded["user"]
    ).get("/hypervisor/series", params={"window": "30d"})

    assert response.status_code == 200
    bucket = _bucket(response)
    assert bucket["cost"] == {"state": "not_measured", "value": None}
    assert bucket["runs"]["value"] == 1
    assert bucket["outcomes"] == {"state": "available", "value": 1, "unit": "brief"}
    assert bucket["hours"] == {"state": "available", "value": 0.5}


def test_series_marks_absent_value_basis_not_configured(db_session):
    seeded = _seed(db_session, with_basis=False, with_cost=True)
    response = _hypervisor_client(
        db_session, seeded["workspace"], seeded["user"]
    ).get("/hypervisor/series", params={"window": "30d"})

    assert response.status_code == 200
    system = response.json()["systems"][0]
    bucket = system["buckets"][0]
    assert system["value_basis"] is None
    assert bucket["hours"] == {"state": "not_configured", "value": None}
    assert bucket["value_declared"] == {"state": "not_configured", "value": None}
    assert bucket["cost"] == {"state": "available", "value": 2.5}


def test_series_converts_outcomes_when_value_basis_is_declared(db_session):
    seeded = _seed(db_session, with_basis=True, with_cost=True)
    response = _hypervisor_client(
        db_session, seeded["workspace"], seeded["user"]
    ).get("/hypervisor/series", params={"window": "90d"})

    assert response.status_code == 200
    bucket = _bucket(response)
    assert bucket["hours"] == {"state": "available", "value": 0.5}
    assert bucket["value_declared"] == {"state": "available", "value": 10.0}
    assert bucket["cost"] == {"state": "available", "value": 2.5}


def test_series_omits_days_without_visible_runs(db_session):
    seeded = _seed(db_session, with_basis=True, with_cost=True)
    payload = _hypervisor_client(
        db_session, seeded["workspace"], seeded["user"]
    ).get("/hypervisor/series", params={"window": "30d"}).json()

    dates = [bucket["date"] for bucket in payload["systems"][0]["buckets"]]
    assert dates == [seeded["run"].completed_at.date().isoformat()]


def test_put_value_basis_mirrors_value_per_outcome(db_session):
    seeded = _seed(db_session, with_basis=False, with_cost=True)
    client = _capability_client(db_session, seeded["workspace"], seeded["user"])

    written = client.put(
        f"/capabilities/{seeded['capability'].id}/value-basis",
        json={
            "unit": "brief",
            "hours_per_unit": 1.25,
            "value_per_unit": 40.0,
            "currency": "EUR",
            "status": "declared",
            "note": "operator declaration",
        },
    )
    assert written.status_code == 200
    body = written.json()
    assert body["value_per_outcome"] == 40.0
    assert body["value_basis"]["value_per_unit"] == 40.0
    assert body["value_basis"]["hours_per_unit"] == 1.25
    assert body["value_basis"]["declared_by"] == seeded["user"].email
    assert body["value_basis"]["status"] == "declared"

    db_session.refresh(seeded["capability"])
    assert seeded["capability"].value_per_outcome == 40.0
    assert seeded["capability"].value_basis["value_per_unit"] == 40.0

    reread = client.get(f"/capabilities/{seeded['capability'].id}/value-basis")
    assert reread.status_code == 200
    assert reread.json()["value_basis"]["value_per_unit"] == 40.0

    listed = _hypervisor_client(
        db_session, seeded["workspace"], seeded["user"]
    ).get("/hypervisor/value-bases")
    item = next(
        row
        for row in listed.json()["items"]
        if row["capability_id"] == seeded["capability"].id
    )
    assert item["value_per_outcome"] == 40.0
    assert item["value_basis"]["value_per_unit"] == 40.0
    assert item["systems"] == [
        {"system_id": seeded["system"].id, "name": seeded["system"].name}
    ]


def test_showcase_value_bases_cover_three_existing_systems_only():
    by_slug = {entry["slug"]: entry for entry in showcase_seed.CAPABILITIES}
    assert by_slug["showcase_tender_response"]["value_basis"]["hours_per_unit"] == 0.75
    assert by_slug["showcase_hana_maintenance"]["value_basis"]["value_per_unit"] == 18.0
    for slug in (
        "video_contract_risk",
        "showcase_compliance_loop",
        "showcase_translation_suite",
    ):
        assert "value_basis" not in by_slug[slug]
    assert showcase_seed.CAPTURE_VALUE_BASIS["unit"] == "knowledge_update_proposal"
    assert showcase_seed.CAPTURE_VALUE_BASIS["status"] == "declared"
    assert showcase_seed.CAPTURE_VALUE_BASIS["currency"] == "EUR"
