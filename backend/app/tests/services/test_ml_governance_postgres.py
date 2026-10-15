"""Real PostgreSQL proves multi-process admission and exposure serialization."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_governance import MLAdmissionCounter
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.ml_governance import admit
from app.services.tabular_datasets import TabularError
from app.services.tabular_predict import mint_api_key
from app.tests.services.test_activity_observability_postgres import pg as pg


def model(db, slug):
    row = MLModel(
        id=str(uuid4()),
        workspace_id="pg-activity-ws",
        name=slug,
        slug=slug,
        task="regression",
        target="y",
        algo="ridge",
        status="ready",
    )
    db.add(row)
    db.commit()
    return row.id


def test_postgres_parallel_model_and_key_budget_is_exact(pg, monkeypatch):
    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 5)
    with Session(pg) as db:
        identifier = model(db, "concurrent")

    def reserve(_):
        with Session(pg) as db:
            try:
                admit(
                    db,
                    db.get(MLModel, identifier),
                    rows=3,
                    key_id="same-key",
                    now=datetime(2026, 10, 15, 12, 0),
                )
                return True
            except TabularError as exc:
                assert exc.code == "ML_RATE_LIMITED"
                return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve, range(20)))
    assert sum(outcomes) == 5
    with Session(pg) as db:
        counters = db.query(MLAdmissionCounter).all()
        assert len(counters) == 2
        assert {(row.requests, row.rows) for row in counters} == {(5, 15)}


def test_postgres_exposure_quota_has_one_winner(pg, monkeypatch):
    monkeypatch.setattr(settings, "ml_max_exposed_models", 1)
    with Session(pg) as db:
        identifiers = [model(db, "first"), model(db, "second")]

    def expose(identifier):
        with Session(pg) as db:
            try:
                mint_api_key(db, model=db.get(MLModel, identifier))
                return True
            except TabularError as exc:
                assert exc.code == "ML_EXPOSURE_QUOTA_EXCEEDED"
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(expose, identifiers)) == [False, True]


@pytest.mark.parametrize("operation", ["promotion", "exposure"])
def test_postgres_policy_reader_refreshes_after_waiting_for_policy_api(pg, monkeypatch, operation):
    from app.api.v1.endpoints import ml_governance as api
    from app.services.ml_governance import MLPolicy
    from app.services.ml_promotion import request

    monkeypatch.setattr(settings, "ml_rbac_enforced", True)
    with Session(pg) as db:
        actor = User(
            id=str(uuid4()),
            username=uuid4().hex,
            email=uuid4().hex + "@example.invalid",
            role="user",
            is_active=True,
        )
        db.add(actor)
        db.flush()
        db.add(
            WorkspaceMember(
                workspace_id="pg-activity-ws",
                user_id=actor.id,
                role="admin",
                role_template="workspace_admin",
            )
        )
        db.commit()
        actor_id = actor.id
        already_exposed = model(db, "already-exposed")
        candidate = model(db, "candidate")
        mint_api_key(db, model=db.get(MLModel, already_exposed), created_by=actor_id)

    writer_locked, release_writer, reader_started = Event(), Event(), Event()
    reader_pid = []
    actual_lock = api.lock_workspace

    def hold_real_policy_lock(db, workspace_id):
        actual_lock(db, workspace_id)
        writer_locked.set()
        assert release_writer.wait(8), "reader never reached the lock wait"

    monkeypatch.setattr(api, "lock_workspace", hold_real_policy_lock)

    def update_policy():
        with Session(pg) as db:
            return api.configure_policy(
                body=MLPolicy(promotion_requires_approval=True, max_exposed_models=1),
                workspace=db.get(Workspace, "pg-activity-ws"),
                user=db.get(User, actor_id),
                db=db,
            )

    def consume_policy():
        assert writer_locked.wait(5)
        with Session(pg) as db:
            # Hold the ORM identity that ordinary authentication loaded while
            # the previous policy is still committed. This is the stale object.
            workspace = db.get(Workspace, "pg-activity-ws")
            assert not (workspace.settings or {}).get("ml", {}).get("promotion_requires_approval")
            actor = db.get(User, actor_id)
            candidate_row = db.get(MLModel, candidate)
            reader_pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            reader_started.set()
            if operation == "promotion":
                _, decision = request(db, model=candidate_row, workspace=workspace, user=actor)
                assert decision is not None and decision["status"] == "proposed"
                assert not db.get(MLModel, candidate).is_champion
                return "awaiting_review"
            with pytest.raises(TabularError) as error:
                mint_api_key(db, model=candidate_row, created_by=actor_id)
            assert error.value.code == "ML_EXPOSURE_QUOTA_EXCEEDED"
            return "exposure_refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(update_policy)
        reader = pool.submit(consume_policy)
        try:
            assert writer_locked.wait(5) and reader_started.wait(5)
            with pg.connect() as connection:
                deadline = monotonic() + 3
                waiting = None
                while monotonic() < deadline:
                    waiting = connection.execute(
                        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                        {"pid": reader_pid[0]},
                    ).scalar()
                    connection.commit()
                    if waiting == "Lock":
                        break
                    sleep(0.01)
                assert waiting == "Lock", "must prove contention, not merely thread scheduling"
            assert not reader.done()
        finally:
            release_writer.set()
        assert writer.result(timeout=8)["policy"]["promotion_requires_approval"] is True
        assert reader.result(timeout=8) == (
            "awaiting_review" if operation == "promotion" else "exposure_refused"
        )
