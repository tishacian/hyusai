from datetime import datetime, timedelta

from app.services.automation_review import (
    AutomationReviewRefusal,
    compare,
    confirm_correction,
    ran_correction,
    reread,
    reserve,
)


def _flow():
    return {
        "nodes": [
            {"id": "trigger", "kind": "source", "type": "trigger"},
            {"id": "agent", "kind": "task", "type": "agent", "config": {"skill_slug": "workspace_llm_v1"}},
            {"id": "output", "kind": "sink", "type": "output"},
        ],
        "edges": [],
    }


def test_a_result_from_another_automation_cannot_be_reserved():
    try:
        reserve("system-a", {"id": "run-1", "system_id": "system-b"}, "TVA unclear")
    except AutomationReviewRefusal as refusal:
        assert refusal.code == "object_lost"
    else:
        raise AssertionError("expected object_lost")


def test_reread_keeps_the_system_and_the_result():
    reserved = reserve("system-a", {"id": "run-1", "system_id": "system-a"}, "TVA unclear")
    seen = reread(reserved, _flow())
    assert seen["system_id"] == "system-a"
    assert seen["run_id"] == "run-1"
    assert seen["note"] == "TVA unclear"
    assert seen["status"] == "reread"
    assert seen["draft_hash"]
    assert [node["type"] for node in seen["nodes"]] == ["trigger", "agent", "output"]


def test_correction_is_refused_until_the_draft_is_reread_and_still_matches():
    reserved = reserve("system-a", {"id": "run-1", "system_id": "system-a"}, "TVA unclear")
    try:
        confirm_correction(reserved, _flow(), "not-the-hash")
    except AutomationReviewRefusal as refusal:
        assert refusal.code == "stale_reread"
    else:
        raise AssertionError("expected stale_reread")
    seen = reread(reserved, _flow())
    confirmed = confirm_correction(seen, _flow(), seen["draft_hash"])
    assert confirmed["status"] == "corrected"
    assert confirmed["correction_hash"] == seen["draft_hash"]
    assert confirmed["system_id"] == "system-a"
    assert confirmed["run_id"] == "run-1"


def test_a_moved_draft_cannot_confirm_the_old_reread():
    reserved = reserve("system-a", {"id": "run-1", "system_id": "system-a"}, "TVA unclear")
    seen = reread(reserved, _flow())
    moved = _flow()
    moved["nodes"].append({"id": "gate", "kind": "decision"})
    try:
        confirm_correction(seen, moved, seen["draft_hash"])
    except AutomationReviewRefusal as refusal:
        assert refusal.code == "stale_reread"
    else:
        raise AssertionError("expected stale_reread")


def test_comparison_refuses_another_automation_and_the_same_result():
    reserved = reserve("system-a", {"id": "run-1", "system_id": "system-a"}, "TVA unclear")
    try:
        compare(reserved, {"id": "run-2", "system_id": "system-a", "status": "completed"})
    except AutomationReviewRefusal as refusal:
        assert refusal.code == "not_corrected"
    else:
        raise AssertionError("expected not_corrected")
    corrected = {**reserved, "correction_hash": "abc", "status": "corrected"}
    try:
        compare(corrected, {"id": "run-2", "system_id": "system-b", "status": "completed"})
    except AutomationReviewRefusal as refusal:
        assert refusal.code == "object_lost"
    else:
        raise AssertionError("expected object_lost")
    try:
        compare(corrected, {"id": "run-1", "system_id": "system-a", "status": "completed"})
    except AutomationReviewRefusal as refusal:
        assert refusal.code == "same_result"
    else:
        raise AssertionError("expected same_result")
    later = compare(corrected, {"id": "run-2", "system_id": "system-a", "status": "completed"})
    assert later["same_object"] is True
    assert later["system_id"] == "system-a"
    assert later["run_id"] == "run-1"
    assert later["later_run_id"] == "run-2"


def test_a_draft_outside_the_catalog_is_reread_and_says_what_an_edit_may_change():
    reserved = reserve("system-a", {"id": "run-1", "system_id": "system-a"}, "TVA unclear")
    flow = {
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "x", "kind": "task", "config": {"skill_slug": "@extract_facts"}},
            {"id": "f", "type": "function"},
        ],
        "edges": [],
    }
    seen = reread(reserved, flow)
    assert [(node["type"], node["editable"]) for node in seen["nodes"]] == [
        ("trigger", True),
        ("extract_facts", False),
        ("function", False),
    ]
    confirmed = confirm_correction(seen, flow, seen["draft_hash"])
    assert confirmed["status"] == "corrected"


def test_the_graph_the_reserved_result_ran_is_not_a_correction():
    reserved = reserve("system-a", {"id": "run-1", "system_id": "system-a"}, "TVA unclear")
    seen = reread(reserved, _flow())
    try:
        confirm_correction(seen, _flow(), seen["draft_hash"], reserved_flow_sha256=seen["draft_hash"])
    except AutomationReviewRefusal as refusal:
        assert refusal.code == "unchanged_draft"
    else:
        raise AssertionError("expected unchanged_draft")


def test_a_result_older_than_the_reservation_is_not_a_later_result():
    corrected = {
        **reserve("system-a", {"id": "run-1", "system_id": "system-a"}, "TVA unclear"),
        "correction_hash": "abc",
    }
    reserved_at = datetime(2026, 9, 23, 12, 0)
    try:
        compare(
            corrected,
            {"id": "run-0", "system_id": "system-a", "started_at": reserved_at - timedelta(hours=1)},
            reserved_started_at=reserved_at,
        )
    except AutomationReviewRefusal as refusal:
        assert refusal.code == "not_later"
    else:
        raise AssertionError("expected not_later")
    later = compare(
        corrected,
        {
            "id": "run-2",
            "system_id": "system-a",
            "status": "completed",
            "started_at": reserved_at + timedelta(hours=1),
            "flow_sha256": "abc",
        },
        reserved_started_at=reserved_at,
    )
    assert later["ran_correction"] is True


def test_ran_correction_is_unknown_without_a_flow_hash():
    assert ran_correction("abc", None) is None
    assert ran_correction("abc", "abd") is False
    assert ran_correction("abc", "abc") is True
