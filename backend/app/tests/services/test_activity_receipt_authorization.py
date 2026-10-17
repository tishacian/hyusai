"""Service activity projections retain native membership and recursive grants."""

from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.run import Run
from app.models.user import User
from app.services import governed_assets as assets
from app.services import service_promises as services
from app.services.activity_observability import queries
from app.services.activity_observability.execution_metadata import (
    receipt_history_visible,
    receipt_metadata_visible,
)
from app.services.activity_observability.projection import activity_id
from app.services.activity_observability.series import activity_series
from app.services.execution_view import execution_view
from app.tests.services.test_service_contracts import (
    NOW,
    asset,
    review_snapshot,
    window,
)
from app.tests.services.test_service_contracts import (
    setup as service_scope,  # noqa: F401
)


@pytest.fixture
def context(service_scope, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "activity_observability_enabled", True)
    monkeypatch.setattr(settings, "execution_view_enabled", True)
    return service_scope


def publish(s, private=None):
    run = Run(
        workspace_id=s.workspace.id,
        system_id=s.system.id,
        status="completed",
        trigger="chat_agentic" if private == "direct" else "manual",
        initiated_by_user_id=s.owner.id,
        flow_snapshot={"nodes": [], "edges": []},
    )
    s.db.add(run)
    s.db.flush()
    _, w = window(s)
    a = asset(s, run_id=run.id)
    if private == "parent":
        parent_run = Run(
            workspace_id=s.workspace.id,
            system_id=s.system.id,
            status="completed",
            trigger="chat_agentic",
            initiated_by_user_id=s.owner.id,
        )
        s.db.add(parent_run)
        s.db.flush()
        parent = asset(s, name="private-parent", run_id=parent_run.id)
        a = assets.register_asset(
            s.db,
            s.workspace.id,
            "reference",
            "public-child",
            {},
            [assets.asset_ref(parent)],
            run_id=run.id,
        )
    assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(a),
        status="qualified",
        policy={"v": 1},
        evidence={"test": True},
    )
    attempt = services.claim_window(
        s.db,
        s.workspace.id,
        w.id,
        run_id=run.id,
        worker_id="test",
        now=NOW,
    )
    services.complete_attempt(
        s.db,
        s.workspace.id,
        w.id,
        fence=attempt.fence,
        lease_token=attempt.lease_token,
        candidate_ref=assets.asset_ref(a),
        now=NOW + timedelta(seconds=1),
    )
    decision = services.review_delivery(
        s.db,
        s.workspace.id,
        w.id,
        **review_snapshot(s, w),
        reviewer_user_id=s.owner.id,
        accept=True,
        now=NOW + timedelta(seconds=2),
    )
    receipt = services.publish_delivery(
        s.db,
        s.workspace.id,
        w.id,
        decision_id=decision.id,
        fence=attempt.fence,
        lease_token=attempt.lease_token,
        now=NOW + timedelta(seconds=3),
    )
    s.db.commit()
    return run, w, a, receipt


def count(s, user, kind):
    return activity_series(
        s.db,
        s.workspace,
        user,
        start=NOW - timedelta(days=1),
        until=NOW + timedelta(days=1),
        kind=kind,
    )["totals"]["total"]


@pytest.mark.parametrize("private", ["direct", "parent"])
def test_receipt_native_denial_excludes_lists_totals_events_and_flow(context, private, monkeypatch):
    s = context
    run, _, _, receipt = publish(s, private)
    with pytest.raises(assets.GovernanceError, match="ASSET_NATIVE_ACCESS_DENIED") as exc:
        services.get_receipt(s.db, s.workspace.id, receipt.id, user_id=s.member.id)
    assert exc.value.status_code == 403

    def forbidden_store():
        raise AssertionError("Recursive metadata authorization must not open the object store")

    monkeypatch.setattr(assets, "get_object_store", forbidden_store)
    assert not receipt_history_visible(s.db, s.workspace, s.member, receipt.id)
    assert not receipt_metadata_visible(s.db, s.workspace, s.member, receipt.id)
    identifier = activity_id("delivery_receipt", receipt.id)
    listed = queries.list_activities(s.db, s.workspace, s.member, kind="delivery_receipt")
    assert listed["total"] == 0 and listed["items"] == []
    assert count(s, s.member, "delivery_receipt") == 0
    assert identifier not in {
        event["activity_id"] for event in queries.event_page(s.db, s.workspace, s.member)["items"]
    }
    with pytest.raises(HTTPException) as exc:
        queries.authorized_activity(s.db, identifier, s.workspace, s.member)
    assert exc.value.status_code == 404
    assert (
        queries.list_activities(s.db, s.workspace, s.owner, kind="delivery_receipt")["total"] == 1
    )
    # Windows have a separate native policy: their metadata is workspace-readable.
    assert queries.list_activities(s.db, s.workspace, s.member, kind="service_window")["total"] == 1
    if private == "parent":
        view = execution_view(s.db, s.workspace, s.member, run.id)
        assert all(item["source"] != "delivery_receipt" for item in view["items"])
        events = queries.event_page(s.db, s.workspace, s.member, run_id=run.id, subtree=True)
        assert identifier not in {event["activity_id"] for event in events["items"]}


def test_platform_admin_without_membership_cannot_read_service_metadata(context):
    s = context
    run, w, _, receipt = publish(s)
    user = User(
        id="service-outsider-admin", username="service-outsider-admin", role="admin", is_active=True
    )
    s.db.add(user)
    s.db.commit()
    with pytest.raises(assets.GovernanceError, match="SERVICE_PERMISSION_DENIED"):
        services.require_member(s.db, s.workspace.id, user.id)
    hidden = {activity_id("service_window", w.id), activity_id("delivery_receipt", receipt.id)}
    for kind in ("service_window", "delivery_receipt"):
        assert queries.list_activities(s.db, s.workspace, user, kind=kind)["total"] == 0
        assert count(s, user, kind) == 0
    assert hidden.isdisjoint(
        event["activity_id"] for event in queries.event_page(s.db, s.workspace, user)["items"]
    )
    assert all(
        item["source"] not in {"service_window", "delivery_receipt"}
        for item in execution_view(s.db, s.workspace, user, run.id)["items"]
    )


def test_invalidated_receipt_remains_in_history_under_grants_without_object_io(
    context, monkeypatch
):
    s = context
    _, _, a, receipt = publish(s)
    assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(a),
        status="needs_requalification",
        policy={"v": 2},
        evidence={"changed": True},
    )
    s.db.commit()
    native = services.list_receipts(s.db, s.workspace.id, user_id=s.member.id)
    assert native["items"][0]["available"] is False

    def forbidden_store():
        raise AssertionError("Metadata authorization must not open the object store")

    monkeypatch.setattr(assets, "get_object_store", forbidden_store)
    assert receipt_history_visible(s.db, s.workspace, s.member, receipt.id)
    assert not receipt_metadata_visible(s.db, s.workspace, s.member, receipt.id)
    assert (
        queries.list_activities(s.db, s.workspace, s.member, kind="delivery_receipt")["total"] == 1
    )
    assert count(s, s.member, "delivery_receipt") == 1
    assert activity_id("delivery_receipt", receipt.id) in {
        event["activity_id"] for event in queries.event_page(s.db, s.workspace, s.member)["items"]
    }
