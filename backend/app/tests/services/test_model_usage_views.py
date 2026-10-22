"""Usage views disclose only the caller's calls and authorised lineage."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.model_usage import ModelUsageCall
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.services import model_usage as usage
from app.services import model_usage_views as views
from app.tests.services.test_model_usage import prepare
from app.tests.services.test_model_usage import scope as scope


def reader(s):
    user = User(id=str(uuid4()), username=uuid4().hex, role="user", is_active=True)
    s.db.add(user)
    s.db.flush()
    s.db.add(WorkspaceMember(workspace_id=s.workspace.id, user_id=user.id, role="member"))
    s.db.commit()
    return user


def child_call(s, parent, actor, *, private=False):
    system = System(id=str(uuid4()), workspace_id=s.workspace.id, name="Delegated application")
    run = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        system_id=system.id,
        initiated_by_user_id=actor.id,
        status="running",
        parent_run_id=parent.id,
        trigger="chat_agentic" if private else "manual",
    )
    s.db.add_all([system, run])
    s.db.commit()
    result = usage.prepare_call(
        usage.UsageContext(s.workspace.id, run_id=run.id),
        request_key=run.id,
        provider="openai",
        model="qualified",
        input_token_bound=10,
        output_token_bound=10,
    )
    return run, s.db.get(ModelUsageCall, result["id"])


def test_readable_child_does_not_disclose_private_parent_or_change_its_ledger(scope):
    s, user = scope, reader(scope)
    s.run.trigger = "chat_agentic"
    s.db.commit()
    prepare(s)
    child, call = child_call(s, s.run, user)
    call.details = {
        "scope": "system:" + s.system.id,
        "policy_id": "private-budget",
        "reason": "cap",
    }
    s.db.commit()
    rows, coverage = views.visible_calls(s.db, s.workspace, user)
    assert [row.id for row in rows] == [call.id]
    assert coverage["complete"] and views.summarize(rows)["counts"]["calls"] == 1
    payload = views.visible_call_payloads(s.db, s.workspace, user, rows)[0]
    assert payload["run_id"] == child.id and payload["system_id"] == child.system_id
    assert payload["root_run_id"] is None and payload["root_system_id"] is None
    assert payload["details"] == {"reason": "cap"}
    assert call.root_run_id == s.run.id and call.root_system_id == s.system.id
    assert call.details["policy_id"] == "private-budget"
    # A root-system filter must not reveal the hidden relationship by counting
    # a visible child whose own system is different.
    filtered, _ = views.visible_calls(s.db, s.workspace, user, system_id=s.system.id)
    assert filtered == []
    with pytest.raises(HTTPException) as denied:
        views.visible_calls(s.db, s.workspace, user, run_id=s.run.id, run_scope="tree")
    assert denied.value.status_code == 404


def test_unreadable_system_filter_is_denied_and_root_identity_is_masked(scope, monkeypatch):
    s, user = scope, reader(scope)
    _, call = child_call(s, s.run, user)
    real = views.readable_systems
    monkeypatch.setattr(
        views,
        "readable_systems",
        lambda db, **kw: [system for system in real(db, **kw) if system.id != s.system.id],
    )
    with pytest.raises(HTTPException) as denied:
        views.visible_calls(s.db, s.workspace, user, system_id=s.system.id)
    assert denied.value.status_code == 404
    rows, _ = views.visible_calls(s.db, s.workspace, user)
    assert [row.id for row in rows] == [call.id]
    assert views.visible_call_payloads(s.db, s.workspace, user, rows)[0]["root_system_id"] is None


def test_private_volume_does_not_change_authorised_limit_or_coverage(scope, monkeypatch):
    s, user = scope, reader(scope)
    visible_id = prepare(s)["id"]
    child_call(s, s.run, s.user, private=True)
    child_call(s, s.run, s.user, private=True)
    s.db.get(ModelUsageCall, visible_id).started_at = datetime.utcnow() - timedelta(hours=1)
    s.db.commit()
    monkeypatch.setattr(views, "SCAN_LIMIT", 1)
    rows, coverage = views.visible_calls(s.db, s.workspace, user)
    assert [row.id for row in rows] == [visible_id]
    assert coverage["complete"] and coverage["scanned"] == 1
    assert views.summarize(rows)["counts"]["calls"] == 1
    # Only additional readable calls may make the authorised result bounded.
    prepare(s, key="visible-second")
    _, coverage = views.visible_calls(s.db, s.workspace, user)
    assert coverage["complete"] is False


def test_unknown_currency_cost_is_null_until_a_real_zero_is_measured(scope):
    s = scope
    call = prepare(s)
    usage.mark_dispatched(call["id"])
    usage.settle_call(call["id"], usage=None, status="unknown")
    rows, _ = views.visible_calls(s.db, s.workspace, s.user)
    cost = views.summarize(rows)["costs"][0]
    assert cost["known_amount"] is None and cost["known_calls"] == 0 and cost["unknown_calls"] == 1
    assert views.series(rows)[0]["costs"][0]["known_amount"] is None
    usage.settle_call(call["id"], usage={"input_tokens": 0, "output_tokens": 0}, status="failed")
    s.db.expire_all()
    rows, _ = views.visible_calls(s.db, s.workspace, s.user)
    cost = views.summarize(rows)["costs"][0]
    assert (
        Decimal(cost["known_amount"]) == 0
        and cost["known_calls"] == 1
        and cost["unknown_calls"] == 0
    )


def test_intermediate_delegation_tree_counts_descendants_once_with_their_acl(scope):
    s, user = scope, reader(scope)
    parent = prepare(s)
    child, child_cost = child_call(s, s.run, user)
    grandchild, grandchild_cost = child_call(s, child, user)
    _, hidden_cost = child_call(s, child, s.user, private=True)
    sibling, sibling_cost = child_call(s, s.run, user)
    direct, _ = views.visible_calls(s.db, s.workspace, user, run_id=child.id)
    assert {row.id for row in direct} == {child_cost.id}
    subtree, _ = views.visible_calls(s.db, s.workspace, user, run_id=child.id, run_scope="tree")
    assert {row.id for row in subtree} == {child_cost.id, grandchild_cost.id}
    root, _ = views.visible_calls(s.db, s.workspace, user, run_id=s.run.id, run_scope="tree")
    assert len(root) == 4
    assert {row.id for row in root} == {
        parent["id"],
        child_cost.id,
        grandchild_cost.id,
        sibling_cost.id,
    }
    assert hidden_cost.id not in {row.id for row in root}
