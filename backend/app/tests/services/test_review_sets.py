"""Review sets: queue policy, claims, decisions, taxonomy rules, export, completion."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.review_set import ReviewDecision
from app.models.workspace import Workspace
from app.services import review_sets as rs

TAXONOMY = {
    "categories": [
        {"key": "WT", "label": "Wrong term", "severities": ["minor", "major"]},
        {"key": "OM", "label": "Omission", "severities": ["minor", "major"]},
    ],
    "comment_required_for": ["major"],
    "severity_weights": {"minor": 2, "major": 5},
    "severity_order": ["minor", "major"],
}
POLICY = {
    "tiers": [
        {"key": "P0"},
        {"key": "P1"},
        {"key": "P3", "unlock_after": {"tiers": ["P0", "P1"], "threshold": 1.0}},
    ],
    "package_weight": 10,
}


def _items():
    return [
        {
            "item_ref": "a",
            "tier": "P0",
            "weight": 6,
            "subject": {"source": "Bonjour", "candidate": "Hello"},
        },
        {
            "item_ref": "b",
            "tier": "P0",
            "weight": 6,
            "subject": {"source": "Frein", "candidate": "Brake"},
        },
        {
            "item_ref": "c",
            "tier": "P1",
            "weight": 3,
            "subject": {
                "source": "<b>Danger</b>",
                "candidate": "<b>Danger</b>",
                "protected_spans": ["<b>", "</b>"],
            },
        },
        {
            "item_ref": "d",
            "tier": "P3",
            "weight": 1,
            "subject": {"source": "=SUM(A1)", "candidate": "x"},
        },
    ]


@pytest.fixture
def opened(db_session):
    ws = Workspace(id=str(uuid4()), name="review", slug=str(uuid4()), settings={})
    db_session.add(ws)
    db_session.commit()
    row = rs.open_set(
        db_session,
        workspace_id=ws.id,
        namespace="translation.segment",
        group_key="lot-1:de",
        title="Lot 1 German",
        items=_items(),
        taxonomy=TAXONOMY,
        policy=POLICY,
        user_id="u0",
    )
    db_session.commit()
    return ws, row


def _item(db, review_set, ref):
    return next(
        i for i in rs.list_items(db, review_set, limit=200)["items"] if i["item_ref"] == ref
    )


def _decide(db, review_set, ref, user="u1", **kwargs):
    item_id = _item(db, review_set, ref)["id"]
    _set, item = rs.get_item(db, review_set.workspace_id, item_id)
    kwargs.setdefault("revision", item.revision)
    out = rs.decide(db, review_set, item, user_id=user, **kwargs)
    db.commit()
    return out


def test_packages_split_by_weight_and_lock_later_tiers(db_session, opened):
    _ws, review_set = opened
    packs = rs.packages(db_session, review_set)
    assert [(p["key"], p["items"], p["locked"]) for p in packs] == [
        ("P0-1", 1, False),
        ("P0-2", 1, False),
        ("P1-1", 1, False),
        ("P3-1", 1, True),
    ]
    item = rs.get_item(
        db_session, review_set.workspace_id, _item(db_session, review_set, "d")["id"]
    )[1]
    with pytest.raises(rs.ReviewError) as locked:
        rs.claim(db_session, review_set, item, user_id="u1")
    assert locked.value.code == "REVIEW_TIER_LOCKED"
    for ref in ("a", "b", "c"):
        _decide(db_session, review_set, ref, decision="approve")
    assert rs.packages(db_session, review_set)[-1]["locked"] is False


def test_claims_are_exclusive_until_expiry(db_session, opened, monkeypatch):
    _ws, review_set = opened
    item = rs.get_item(
        db_session, review_set.workspace_id, _item(db_session, review_set, "a")["id"]
    )[1]
    rs.claim(db_session, review_set, item, user_id="u1")
    with pytest.raises(rs.ReviewError) as taken:
        rs.claim(db_session, review_set, item, user_id="u2")
    assert taken.value.code == "REVIEW_ITEM_CLAIMED"
    with pytest.raises(rs.ReviewError):
        rs.decide(db_session, review_set, item, user_id="u2", revision=0, decision="approve")
    from datetime import timedelta

    item.claim_expires_at = rs.utcnow() - timedelta(seconds=1)
    db_session.commit()
    rs.claim(db_session, review_set, item, user_id="u2")


def test_decision_rules(db_session, opened):
    _ws, review_set = opened
    with pytest.raises(rs.ReviewError) as comment:
        _decide(
            db_session,
            review_set,
            "a",
            decision="correct",
            value="Good morning",
            annotations=[{"category": "WT", "severity": "major"}],
        )
    assert comment.value.code == "REVIEW_COMMENT_REQUIRED"
    with pytest.raises(rs.ReviewError) as unknown:
        _decide(
            db_session,
            review_set,
            "a",
            decision="correct",
            value="Good morning",
            annotations=[{"category": "XX", "severity": "minor"}],
        )
    assert unknown.value.code == "REVIEW_ANNOTATION_UNKNOWN"
    with pytest.raises(rs.ReviewError) as protected:
        _decide(db_session, review_set, "c", decision="correct", value="Danger!")
    assert (protected.value.code, str(protected.value)) == ("REVIEW_PROTECTED_SPAN_LOST", "<b>")
    item = _decide(
        db_session,
        review_set,
        "a",
        decision="correct",
        value="Good morning",
        annotations=[{"category": "WT", "severity": "major"}],
        comment="register",
        duration_ms=4000,
    )
    assert (item.status, item.worst_severity, item.revision, item.duration_ms) == (
        "correct",
        "major",
        1,
        4000,
    )
    with pytest.raises(rs.ReviewError) as stale:
        _decide(db_session, review_set, "a", decision="approve", revision=0)
    assert stale.value.code == "REVIEW_REVISION_STALE"
    auto = _decide(db_session, review_set, "b", decision="auto", value="Brake")
    assert auto.status == "approve"
    assert review_set.decided_count == 2
    assert db_session.query(ReviewDecision).count() == 2


def test_bulk_approve_skips_claimed_items(db_session, opened):
    _ws, review_set = opened
    a = _item(db_session, review_set, "a")["id"]
    b = _item(db_session, review_set, "b")["id"]
    rs.claim(
        db_session, review_set, rs.get_item(db_session, review_set.workspace_id, b)[1], user_id="u9"
    )
    out = rs.bulk_approve(db_session, review_set, [a, b, "missing"], user_id="u1")
    assert out["approved"] == [a]
    assert {s["code"] for s in out["skipped"]} == {"REVIEW_ITEM_CLAIMED", "REVIEW_ITEM_NOT_FOUND"}


def test_filters_stats_export_and_completion(db_session, opened, monkeypatch):
    _ws, review_set = opened
    _decide(
        db_session,
        review_set,
        "a",
        decision="correct",
        value="Good morning",
        annotations=[{"category": "WT", "severity": "minor"}],
    )
    assert [
        i["item_ref"] for i in rs.list_items(db_session, review_set, status="pending")["items"]
    ] == ["b", "c", "d"]
    assert rs.list_items(db_session, review_set, category="WT")["total"] == 1
    assert rs.list_items(db_session, review_set, query="frein")["total"] == 1
    stats = rs.stats(db_session, review_set)
    assert (stats["penalty"], stats["by_category"]) == (2.0, {"WT": {"minor": 1}})
    csv_text = rs.export_csv(db_session, review_set)
    assert "Good morning" in csv_text and "WT:minor" in csv_text
    assert "'=SUM(A1)" in csv_text
    for ref in ("b", "c"):
        _decide(db_session, review_set, ref, decision="approve")
    _decide(db_session, review_set, "d", decision="reject", comment="unusable")
    assert review_set.completed_at is not None
    from app.services.run_engine import triggers

    seen = []
    monkeypatch.setattr(
        triggers,
        "emit_event",
        lambda kind, ws, payload, **kw: seen.append((kind, payload["set_id"])) or [],
    )
    assert rs.announce_completed(db_session) == 1
    assert rs.announce_completed(db_session) == 0
    assert seen == [("review_set.completed", review_set.id)]


def test_open_validation(db_session):
    ws = Workspace(id=str(uuid4()), name="v", slug=str(uuid4()), settings={})
    db_session.add(ws)
    db_session.commit()
    base = dict(
        workspace_id=ws.id,
        namespace="ns.x",
        group_key="g",
        title="t",
        taxonomy=TAXONOMY,
        policy=POLICY,
    )
    for items, code in [
        ([], "REVIEW_SET_EMPTY"),
        ([{"item_ref": "a"}, {"item_ref": "a"}], "REVIEW_ITEM_REF_INVALID"),
        ([{"item_ref": "a", "tier": "P9"}], "REVIEW_ITEM_TIER_UNKNOWN"),
    ]:
        with pytest.raises(rs.ReviewError) as exc:
            rs.open_set(db_session, items=items, **base)
        db_session.rollback()
        assert exc.value.code == code
    with pytest.raises(rs.ReviewError) as bad_policy:
        rs.open_set(
            db_session,
            items=[{"item_ref": "a"}],
            **{
                **base,
                "policy": {
                    "tiers": [{"key": "A", "unlock_after": {"tiers": ["B"], "threshold": 1}}]
                },
            },
        )
    assert bad_policy.value.code == "REVIEW_POLICY_INVALID"


def test_skills_open_from_runner_artifact_and_read(db_session, monkeypatch, tmp_path):
    import asyncio
    import json

    from app.core.config import settings
    from app.models.remote_runner import RemoteRunner, RemoteRunnerJob
    from app.services.object_store import get_object_store
    from app.services.skills_registry.wrappers.skills import (
        _review_set_open_v1,
        _review_set_read_v1,
    )

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    ws = Workspace(id=str(uuid4()), name="skills", slug=str(uuid4()), settings={})
    db_session.add(ws)
    db_session.flush()
    runner = RemoteRunner(
        workspace_id=ws.id,
        slug="r",
        name="r",
        transport="local",
        host="h",
        username="u",
        host_key="k",
        key_secret_ref="secret://workspace/k",
        work_root="/tmp/r",
        allowed_commands=[],
        labels={},
    )
    db_session.add(runner)
    db_session.flush()
    key = get_object_store().key("remote-runners", ws.id, "job", "review.jsonl")
    get_object_store().write_bytes(key, "\n".join(json.dumps(item) for item in _items()).encode())
    job = RemoteRunnerJob(
        workspace_id=ws.id,
        runner_id=runner.id,
        command="x",
        params={},
        status="succeeded",
        inputs=[],
        deadline_at=rs.utcnow(),
        artifacts=[{"path": "review.jsonl", "present": True, "key": key}],
    )
    db_session.add(job)
    db_session.commit()
    opened = asyncio.run(
        _review_set_open_v1(
            {
                "namespace": "translation.segment",
                "group_key": "lot:de",
                "title": "t",
                "job_id": job.id,
                "artifact": "review.jsonl",
                "taxonomy": TAXONOMY,
                "policy": POLICY,
            },
            {"workspace_id": ws.id, "run_id": "run-9"},
        )
    )
    assert opened["items"] == 4
    review_set = rs.get_set(db_session, ws.id, opened["set_id"])
    assert review_set.source["correlation_key"] == "run-9"
    _decide(db_session, review_set, "a", decision="correct", value="Good morning")
    read = asyncio.run(
        _review_set_read_v1(
            {"set_id": opened["set_id"], "decisions": ["correct"]}, {"workspace_id": ws.id}
        )
    )
    assert [(d["item_ref"], d["value"]) for d in read["decisions"]] == [("a", "Good morning")]
    with pytest.raises(ValueError, match="REVIEW_SET_NOT_FOUND"):
        asyncio.run(
            _review_set_read_v1({"set_id": opened["set_id"]}, {"workspace_id": str(uuid4())})
        )
