"""An idempotency key makes a lost replay response recoverable, never re-run."""

from datetime import datetime
from uuid import uuid4

import pytest

from app.models.run import Run
from app.models.workspace import Workspace
from app.services.runs import replay_service
from app.tests.api.test_runs_summary import _client


@pytest.fixture()
def setup(db_session, monkeypatch):
    workspace = Workspace(id="ws-replay-idem", slug="replay-idem", name="Replay idempotency")
    parent = Run(id="replay-parent", workspace_id=workspace.id, status="completed", trigger="manual",
                 started_at=datetime(2026, 10, 22, 10, 0))
    db_session.add_all([workspace, parent])
    db_session.commit()
    calls = []

    async def fake_replay(*, db, parent, workspace_slug, overrides, actor=None, source_decision_id=None,
                          source_feedback_id=None, dedup_key=None):
        calls.append(dedup_key)
        run = Run(id=str(uuid4()), workspace_id=parent.workspace_id, status="completed", trigger="replay",
                  parent_run_id=parent.id, replay_overrides=overrides, trigger_dedup_key=dedup_key,
                  started_at=datetime.utcnow())
        db.add(run)
        db.commit()
        return run, "answer"

    monkeypatch.setattr(replay_service, "replay_run_async", fake_replay)
    return _client(db_session, workspace), parent, calls


KEY = "replay-key-0000000001"


def test_same_key_returns_the_first_replay_without_running_again(setup):
    client, parent, calls = setup
    first = client.post(f"/runs/{parent.id}/replay", json={"overrides": {"top_k": 3}}, headers={"Idempotency-Key": KEY})
    again = client.post(f"/runs/{parent.id}/replay", json={"overrides": {"top_k": 3}}, headers={"Idempotency-Key": KEY})
    assert first.status_code == 200 and again.status_code == 200
    assert again.json()["run_id"] == first.json()["run_id"]
    assert first.json()["replayed"] is False and again.json()["replayed"] is True
    assert len(calls) == 1


def test_same_key_with_other_overrides_is_refused(setup):
    client, parent, _calls = setup
    client.post(f"/runs/{parent.id}/replay", json={"overrides": {"top_k": 3}}, headers={"Idempotency-Key": KEY})
    conflict = client.post(f"/runs/{parent.id}/replay", json={"overrides": {"top_k": 9}}, headers={"Idempotency-Key": KEY})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "REPLAY_IDEMPOTENCY_KEY_REUSED"


def test_without_a_key_each_call_is_a_new_replay_as_before(setup):
    client, parent, calls = setup
    a = client.post(f"/runs/{parent.id}/replay", json={"overrides": {}})
    b = client.post(f"/runs/{parent.id}/replay", json={"overrides": {}})
    assert a.json()["run_id"] != b.json()["run_id"]
    assert calls == [None, None]


def test_reconciliation_read_finds_the_replay_a_key_started(setup):
    client, parent, _calls = setup
    started = client.post(f"/runs/{parent.id}/replay", json={"overrides": {}}, headers={"Idempotency-Key": KEY}).json()
    client.post(f"/runs/{parent.id}/replay", json={"overrides": {}})
    found = client.get(f"/runs/{parent.id}/replays", params={"idempotency_key": KEY})
    unknown = client.get(f"/runs/{parent.id}/replays", params={"idempotency_key": "another-key-000000001"})
    assert [item["id"] for item in found.json()["items"]] == [started["run_id"]]
    assert unknown.json()["items"] == []
    assert len(client.get(f"/runs/{parent.id}/replays").json()["items"]) == 2
