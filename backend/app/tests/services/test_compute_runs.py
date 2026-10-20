"""Durable registry invariants; no external broker or database driver required."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.compute_run import ComputeRun
from app.models.connector_connection import ConnectorConnection
from app.models.workspace import Workspace
from app.services import compute_runs as runs


@pytest.fixture
def registered(db_session, monkeypatch):
    monkeypatch.setattr(settings, "connector_framework_enabled", True)
    workspace = Workspace(id=str(uuid4()), name="compute fixture", slug=str(uuid4()), settings={})
    db_session.add(workspace)
    db_session.flush()
    connection = ConnectorConnection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="sql",
        profile_key="postgresql",
        profile_version=1,
        values={},
        secret_refs={},
        access="read",
        created_by="fixture",
    )
    db_session.add(connection)
    db_session.commit()
    return workspace, connection


def submit(db, registered, **changes):
    workspace, connection = registered
    row = runs.create_run(
        db,
        workspace_id=workspace.id,
        user_id="fixture",
        connection_id=connection.id,
        operation="preview",
        **changes,
    )
    db.commit()
    return row


def start(db, row):
    token = runs.claim_run(db, row.id)
    assert token
    assert runs.advance_run(db, row.id, token, "launching")
    assert runs.advance_run(db, row.id, token, "running")
    return token


def test_queue_deadline_expires_as_busy_not_network_failure(db_session, registered):
    row = submit(db_session, registered)
    assert runs.claim_run(db_session, row.id, now=row.deadline_at) is None
    db_session.refresh(row)
    assert (row.status, row.error_code) == ("timed_out", "CONNECTOR_BUSY")
    assert row.started_at is None


def test_claim_is_single_and_redelivery_never_restarts_live_work(db_session, registered):
    row = submit(db_session, registered)
    token = start(db_session, row)
    assert runs.claim_run(db_session, row.id) is None
    db_session.refresh(row)
    assert row.lease_token == token
    assert row.status == "running"


def test_expired_lease_cannot_be_renewed_or_succeed(db_session, registered):
    row = submit(db_session, registered)
    token = start(db_session, row)
    db_session.refresh(row)
    future = row.lease_expires_at + timedelta(seconds=1)
    assert not runs.heartbeat(db_session, row.id, token, now=future)
    assert runs.reap_runs(db_session, now=future) == 1
    assert not runs.finish_run(db_session, row.id, token, status="succeeded", output={"rows": 1})
    db_session.refresh(row)
    assert row.output_json is None
    assert row.status in {"lost", "timed_out"}


def test_cancel_pending_never_claims(db_session, registered):
    row = submit(db_session, registered)
    runs.request_cancel(db_session, row)
    assert runs.claim_run(db_session, row.id) is None
    assert row.status == "cancelled"


def test_cancel_wins_race_with_success_and_no_output(db_session, registered):
    row = submit(db_session, registered)
    token = start(db_session, row)
    runs.request_cancel(db_session, row)
    assert not runs.heartbeat(db_session, row.id, token)
    runs.finish_run(
        db_session, row.id, token, status="succeeded", output={"secret": "not-published"}
    )
    assert row.status == "cancelled"
    assert row.output_json is None


def test_lost_write_is_unknown_and_never_replayed(db_session, registered):
    row = submit(db_session, registered)
    token = runs.claim_run(db_session, row.id)
    assert runs.advance_run(db_session, row.id, token, "launching")
    assert runs.advance_run(db_session, row.id, token, "running", write_started=True)
    db_session.refresh(row)
    runs.reap_runs(db_session, now=row.lease_expires_at + timedelta(seconds=1))
    db_session.refresh(row)
    assert (row.status, row.error_code, row.outcome_unknown) == (
        "lost",
        "CONNECTOR_WRITE_OUTCOME_UNKNOWN",
        True,
    )
    assert runs.claim_run(db_session, row.id) is None


def test_cancel_after_write_starts_does_not_claim_no_side_effect(db_session, registered):
    row = submit(db_session, registered)
    token = runs.claim_run(db_session, row.id)
    runs.advance_run(db_session, row.id, token, "launching")
    runs.advance_run(db_session, row.id, token, "running", write_started=True)
    runs.request_cancel(db_session, row)
    runs.finish_run(db_session, row.id, token, status="cancelled")
    assert row.outcome_unknown
    assert row.status == "lost"


def test_stale_token_cannot_mutate_run(db_session, registered):
    row = submit(db_session, registered)
    start(db_session, row)
    assert not runs.heartbeat(db_session, row.id, "wrong")
    assert not runs.advance_run(db_session, row.id, "wrong", "committing")
    assert not runs.finish_run(db_session, row.id, "wrong", status="succeeded")


def test_queue_reserves_daily_core_budget(db_session, registered, monkeypatch):
    monkeypatch.setattr(settings, "connector_max_core_hours_per_day", 0.01)
    submit(db_session, registered)
    with pytest.raises(runs.ComputeRunError, match="QUOTA_EXCEEDED"):
        submit(db_session, registered)
    db_session.rollback()


def test_tenant_cannot_raise_operator_quota(db_session, registered, monkeypatch):
    monkeypatch.setattr(settings, "connector_max_pending_runs", 1)
    registered[0].settings = {"dataops": {"max_pending_runs": 1000000}}
    db_session.commit()
    submit(db_session, registered)
    with pytest.raises(runs.ComputeRunError, match="QUOTA_EXCEEDED"):
        submit(db_session, registered)
    db_session.rollback()


def test_admission_limit_keeps_next_run_unclaimed(db_session, registered, monkeypatch):
    monkeypatch.setattr(settings, "connector_max_concurrent_runs", 1)
    first, second = submit(db_session, registered), submit(db_session, registered)
    start(db_session, first)
    with pytest.raises(runs.ComputeRunError, match="CONNECTOR_BUSY"):
        runs.claim_run(db_session, second.id)
    db_session.rollback()
    db_session.refresh(second)
    assert second.status == "queued"
    assert second.lease_token is None


def test_real_sqlite_concurrent_admission_cannot_double_claim(db_session, registered):
    row = submit(db_session, registered)
    identifier = row.id
    barrier = Barrier(2)

    def claim():
        with SessionLocal() as db:
            barrier.wait()
            return runs.claim_run(db, identifier)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(lambda _: claim(), range(2)))
    assert sum(token is not None for token in tokens) == 1


def test_real_sqlite_concurrent_creation_cannot_exceed_quota(db_session, registered, monkeypatch):
    monkeypatch.setattr(settings, "connector_max_pending_runs", 1)
    workspace_id, connection_id = registered[0].id, registered[1].id
    barrier = Barrier(2)

    def create():
        with SessionLocal() as db:
            barrier.wait()
            try:
                runs.create_run(
                    db,
                    workspace_id=workspace_id,
                    user_id="fixture",
                    connection_id=connection_id,
                    operation="preview",
                )
                db.commit()
                return "created"
            except runs.ComputeRunError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert sorted(results) == ["CONNECTOR_QUOTA_EXCEEDED", "created"]


def test_other_workspace_cannot_read_run(db_session, registered):
    row = submit(db_session, registered)
    with pytest.raises(runs.ComputeRunError, match="RUN_NOT_FOUND"):
        runs.get_run(db_session, "other", row.id)


@pytest.mark.parametrize(
    "parameters", [{"password": "x"}, {"nested": {"access_token": "x"}}, {"a": float("nan")}]
)
def test_secrets_and_non_json_never_enter_registry(db_session, registered, parameters):
    with pytest.raises(runs.ComputeRunError):
        submit(db_session, registered, parameters=parameters)
    assert db_session.query(ComputeRun).filter_by(workspace_id=registered[0].id).count() == 0


def test_broker_message_only_contains_id_and_correct_queue(db_session, registered, monkeypatch):
    from app.workers.celery_connectors import celery_connectors

    calls = []
    monkeypatch.setattr(celery_connectors, "send_task", lambda *a, **kw: calls.append((a, kw)))
    row = submit(db_session, registered, parameters={"table": "orders"})
    runs.dispatch_run(db_session, row)
    assert calls[0][1]["args"] == [row.id]
    assert calls[0][1]["queue"] == settings.celery_connectors_interactive_queue
    assert "orders" not in str(calls)


def test_dispatch_failure_preserves_closed_durable_evidence(db_session, registered, monkeypatch):
    from app.workers.celery_connectors import celery_connectors

    def fail(*args, **kwargs):
        raise RuntimeError("credential-from-broker")

    monkeypatch.setattr(celery_connectors, "send_task", fail)
    row = submit(db_session, registered)
    with pytest.raises(runs.ComputeRunError, match="DISPATCH_FAILED"):
        runs.dispatch_run(db_session, row)
    db_session.refresh(row)
    assert row.status == "failed"
    assert "credential" not in str(runs.serialize_run(row))


def test_measured_core_hours_do_not_invent_free_money(db_session, registered, monkeypatch):
    monkeypatch.setattr(settings, "dataops_core_hour_usd", None)
    monkeypatch.setattr(settings, "dataops_gb_hour_usd", None)
    row = submit(db_session, registered)
    token = start(db_session, row)
    now = row.started_at + timedelta(seconds=10)
    runs.finish_run(db_session, row.id, token, status="succeeded", now=now)
    assert row.core_hours == pytest.approx(10 / 3600)
    assert row.cost_usd is None


def test_publication_failure_rolls_back_dataset_transaction(db_session, registered):
    row = submit(db_session, registered)
    token = start(db_session, row)
    runs.advance_run(db_session, row.id, token, "committing")
    original = registered[0].name

    def publish():
        registered[0].name = "must-not-commit"
        db_session.flush()
        raise ValueError("driver-secret")

    runs.finish_run(db_session, row.id, token, status="succeeded", publish=publish)
    db_session.refresh(registered[0])
    assert registered[0].name == original
    assert row.status == "failed"
    assert row.error_code == "CONNECTOR_PUBLICATION_FAILED"


def test_cancelled_run_never_invokes_publisher(db_session, registered):
    row = submit(db_session, registered)
    token = start(db_session, row)
    runs.request_cancel(db_session, row)
    runs.finish_run(
        db_session,
        row.id,
        token,
        status="succeeded",
        publish=lambda: pytest.fail("must not publish"),
    )
    assert row.status == "cancelled"


def test_runner_uses_private_ephemeral_file_not_argv_environment_or_broker(
    db_session, registered, monkeypatch
):
    import json
    import stat
    from pathlib import Path

    from app.services import recipe_executions
    from app.workers import tasks_connectors as worker

    row = submit(db_session, registered)
    monkeypatch.setattr(
        worker,
        "_load_spec",
        lambda db, row: {"credentials": {"password": "private-password"}, "network_grants": []},
    )
    monkeypatch.setattr(worker, "_grants_snapshot", lambda db, workspace: [])
    monkeypatch.setattr(worker, "_authorization_snapshot", lambda db, row: ())
    paths = []

    def supervise(argv, **kwargs):
        spec_path, result_path = Path(argv[-2]), Path(argv[-1])
        paths.append(spec_path)
        assert stat.S_IMODE(spec_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(spec_path.parent.stat().st_mode) == 0o700
        assert "private-password" not in str(argv) + str(kwargs["extra_env"])
        assert json.loads(spec_path.read_text())["credentials"]["password"] == "private-password"
        assert kwargs["should_cancel"]() is False
        result_path.write_text(json.dumps({"ok": True, "output": {"rows": [[1]]}}))
        return SimpleNamespace(status=None, exit_code=0)

    monkeypatch.setattr(recipe_executions, "supervise_harness", supervise)
    outcome = worker.execute_run(row.id)
    assert outcome["status"] == "succeeded"
    assert not paths[0].exists()
    db_session.refresh(row)
    assert "private-password" not in str(runs.serialize_run(row))


def test_atomic_publication_can_exceed_heartbeat_lease_before_absolute_deadline(
    db_session, registered, monkeypatch
):
    row = submit(db_session, registered)
    now = runs.utcnow()
    row.deadline_at = now + timedelta(seconds=120)
    db_session.commit()
    token = start(db_session, row)
    db_session.refresh(row)
    old_lease = row.lease_expires_at
    clock = [now]
    monkeypatch.setattr(runs, "utcnow", lambda: clock[0])

    def publish():
        assert row.lease_expires_at == row.deadline_at
        clock[0] = old_lease + timedelta(seconds=2)
        return {"dataset_id": "published-before-deadline"}

    assert runs.finish_run(db_session, row.id, token, status="succeeded", publish=publish)
    assert row.status == "succeeded"
    assert row.output_json == {"dataset_id": "published-before-deadline"}


def test_atomic_publication_still_rolls_back_after_absolute_deadline(
    db_session, registered, monkeypatch
):
    row = submit(db_session, registered)
    token = start(db_session, row)
    clock = [runs.utcnow()]
    monkeypatch.setattr(runs, "utcnow", lambda: clock[0])

    def publish():
        clock[0] = row.deadline_at + timedelta(seconds=1)
        return {"must_not_publish": True}

    runs.finish_run(db_session, row.id, token, status="succeeded", publish=publish)
    assert row.status == "timed_out"
    assert row.output_json is None
