"""Generic Impact activity and saved view/scenario contracts."""

from datetime import datetime, timedelta

import pytest

from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services import impact_activity
from app.tests.api.test_hypervisor_v2_semantics import _hypervisor_client, _seed


def _activity_seed(db):
    seeded = _seed(db)
    run = seeded["run"]
    now = datetime.utcnow()
    other = System(
        id="other-local-system",
        workspace_id=seeded["workspace"].id,
        name="Inventory",
        status="active",
    )
    foreign_ws = Workspace(id="other-tenant", slug="other-tenant", name="Other tenant")
    foreign = System(
        id="foreign-system", workspace_id=foreign_ws.id, name="Foreign secret", status="active"
    )
    db.add_all([other, foreign_ws, foreign])
    db.flush()
    for id_, status, system_id, age, surface in [
        ("retry", "failed", run.system_id, 1, None),
        ("waiting", "hitl_pending", run.system_id, 1, None),
        ("preview", "completed", run.system_id, 1, "builder_preview"),
        ("draft", "completed", run.system_id, 1, "draft_test"),
        ("older", "completed", run.system_id, 8, None),
        ("inventory", "completed", other.id, 1, None),
        ("bad-parent", "completed", foreign.id, 1, None),
    ]:
        db.add(
            Run(
                id=id_,
                workspace_id=run.workspace_id,
                system_id=system_id,
                status=status,
                started_at=now - timedelta(days=age),
                execution_surface=surface,
            )
        )
    db.flush()
    db.add_all(
        [
            SkillInvocation(
                id="priced-call",
                run_id=run.id,
                status="completed",
                cost=0.25,
                cost_measured=True,
                latency_ms=1000,
                metrics={"cost_evidence": {"state": "calculated", "currency": "USD"}},
            ),
            SkillInvocation(
                id="zero-call",
                run_id="retry",
                status="failed",
                cost=0,
                cost_measured=True,
                latency_ms=2000,
                metrics={"cost_evidence": {"state": "measured", "currency": "EUR"}},
            ),
            SkillInvocation(
                id="unknown-call",
                run_id="retry",
                status="failed",
                cost=0,
                cost_measured=None,
                latency_ms=500,
                metrics={},
            ),
        ]
    )
    db.commit()
    seeded["other"] = other
    seeded["foreign"] = foreign
    return seeded


def test_activity_counts_all_attempts_separates_costs_and_excludes_previews(db_session):
    seeded = _activity_seed(db_session)
    client = _hypervisor_client(db_session, seeded["workspace"], seeded["user"])
    response = client.get(
        "/hypervisor/activity", params={"window": "7d", "system_id": seeded["system"].id}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {
        "attempts": 3,
        "completed": 1,
        "failed": 1,
        "cancelled": 0,
        "pending": 1,
        "invocations": 3,
    }
    assert sum(bucket["attempts"] for bucket in body["buckets"]) == 3
    assert body["costs"]["by_currency"] == {"USD": "0.25", "EUR": "0.0"}
    assert body["costs"]["state"] == "partial"
    assert body["costs"]["unpriced_invocations"] == 1
    assert body["median_technical_seconds"] == 1.75
    assert "output_ref" not in response.text
    assert "preview" not in response.text
    assert "business_volume" not in body
    assert "roi" not in body
    assert body["authorization_scope"]["counts_include_only_readable_runs"] is True
    all_systems = client.get("/hypervisor/activity").json()
    assert all_systems["counts"]["attempts"] == 4


def test_activity_scope_window_and_catalog_never_accept_a_foreign_parent(db_session):
    seeded = _activity_seed(db_session)
    client = _hypervisor_client(db_session, seeded["workspace"], seeded["user"])
    catalog = client.get("/hypervisor/activity/systems").json()["systems"]
    assert {system["id"] for system in catalog} == {seeded["system"].id, seeded["other"].id}
    assert (
        client.get(
            "/hypervisor/activity", params={"window": "30d", "system_id": seeded["system"].id}
        ).json()["counts"]["attempts"]
        == 4
    )
    denied = client.get("/hypervisor/activity", params={"system_id": seeded["foreign"].id})
    missing = client.get("/hypervisor/activity", params={"system_id": "missing"})
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()
    assert client.get("/hypervisor/activity", params={"window": "all"}).status_code == 422


@pytest.mark.parametrize("mode", ["run.read", "skill_invocation.read", "system.read"])
def test_activity_honors_independent_authorization_planes(
    db_session, attest_authorization_v2, mode
):
    seeded = _activity_seed(db_session)
    member = (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=seeded["workspace"].id, user_id=seeded["user"].id)
        .one()
    )
    member.role = "member"
    member.role_template = "workspace_viewer"
    if mode == "system.read":
        db_session.delete(member)
    config = WorkspaceIAMConfig(
        workspace_id=seeded["workspace"].id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {mode: "enforce"},
            }
        },
    )
    db_session.add(config)
    attest_authorization_v2(config, [mode])
    db_session.commit()
    body = (
        _hypervisor_client(db_session, seeded["workspace"], seeded["user"])
        .get("/hypervisor/activity")
        .json()
    )
    if mode == "skill_invocation.read":
        assert body["counts"]["attempts"] == 4
        assert body["counts"]["invocations"] == 0
        assert body["costs"]["by_currency"] == {}
        assert body["median_technical_seconds"] is None
    else:
        assert body["counts"]["attempts"] == 0
        assert body["runs"] == []


def test_activity_limit_is_applied_after_visibility_and_is_disclosed(db_session, monkeypatch):
    seeded = _activity_seed(db_session)
    monkeypatch.setattr(impact_activity, "ACTIVITY_LIMIT", 2)
    body = (
        _hypervisor_client(db_session, seeded["workspace"], seeded["user"])
        .get("/hypervisor/activity")
        .json()
    )
    assert body["limited"] is True
    assert body["limit"] == body["counts"]["attempts"] == 2


def _view(system_id):
    return {
        "id": "customer-support",
        "label": "Customer support",
        "denominator": "runs",
        "period": "7d",
        "system_id": system_id,
        "strata": {
            "comprendre": [
                {
                    "type": "financial_scenario",
                    "title": "Declared support scenario",
                    "settings": {
                        "manual_minutes": 12,
                        "assisted_minutes": 3,
                        "hourly_cost": 30,
                        "unit_budget": 1,
                        "currency": "GBP",
                    },
                },
                {"type": "activity", "settings": {"metrics": ["costs", "statuses"]}},
            ],
            "detailler": [],
            "decider": [],
        },
    }


def test_generic_configuration_round_trip_default_order_and_no_demo_defaults(db_session):
    seeded = _seed(db_session)
    client = _hypervisor_client(db_session, seeded["workspace"], seeded["user"])
    saved = client.put(
        "/hypervisor/views",
        json={"views": [_view(seeded["system"].id)], "default_view_id": "customer-support"},
    )
    assert saved.status_code == 200
    reread = client.get("/hypervisor/views").json()
    assert reread == saved.json()
    assert reread["default_view_id"] == "customer-support"
    view = reread["views"][0]
    assert view["system_id"] == seeded["system"].id
    assert [block["type"] for block in view["strata"]["comprendre"]] == [
        "financial_scenario",
        "activity",
    ]
    assert view["strata"]["comprendre"][0]["settings"]["monthly_volume"] is None
    view["strata"]["comprendre"][0]["settings"] = {}
    empty = client.put("/hypervisor/views", json={"views": [view]}).json()
    assert all(
        value is None for value in empty["views"][0]["strata"]["comprendre"][0]["settings"].values()
    )


def test_configuration_rejects_invalid_scope_assumptions_and_non_admin_writes(db_session):
    seeded = _activity_seed(db_session)
    client = _hypervisor_client(db_session, seeded["workspace"], seeded["user"])
    view = _view(seeded["system"].id)
    for invalid in [-1, "NaN", 1441]:
        view["strata"]["comprendre"][0]["settings"]["manual_minutes"] = invalid
        assert client.put("/hypervisor/views", json={"views": [view]}).status_code == 422
    view = _view(seeded["foreign"].id)
    assert client.put("/hypervisor/views", json={"views": [view]}).status_code == 404
    view = _view(seeded["system"].id)
    assert (
        client.put(
            "/hypervisor/views", json={"views": [view], "default_view_id": "missing"}
        ).status_code
        == 422
    )
    view = _view(seeded["system"].id)
    view["strata"]["comprendre"].append({"type": "activity", "settings": {}})
    assert client.put("/hypervisor/views", json={"views": [view]}).status_code == 422
    view = _view(seeded["system"].id)
    view["strata"]["comprendre"][0]["settings"]["monthly_volume"] = 1.5
    assert client.put("/hypervisor/views", json={"views": [view]}).status_code == 422
    view = _view(seeded["system"].id)
    member = (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=seeded["workspace"].id, user_id=seeded["user"].id)
        .one()
    )
    member.role = "member"
    member.role_template = "workspace_viewer"
    db_session.commit()
    assert client.put("/hypervisor/views", json={"views": [view]}).status_code == 403
    assert seeded["workspace"].settings == {}
