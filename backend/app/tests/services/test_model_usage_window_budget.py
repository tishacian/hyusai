"""Native window reservations commit in the same transaction as shared caps."""

import pytest

from app.models.model_usage import UsageReservation
from app.services import model_usage as usage
from app.services import window_budget
from app.tests.services.test_window_budget import service
from app.tests.services.test_window_budget import setup as setup


def test_native_window_and_shared_reservations_roll_back_together(setup, monkeypatch):
    s = setup
    window = service(s).window
    monkeypatch.setattr(usage, "budget_readiness", lambda ws: {"ready": True})
    usage.save_budget(
        s.db,
        s.workspace,
        s.user,
        scope="workspace",
        enabled=True,
        max_tokens=10000,
        expected_revision=0,
    )
    context = usage.UsageContext(s.workspace.id, run_id=s.run.id)

    def reserve_then_fail(db, call):
        window_budget.reserve_in_transaction(
            db, s.ctx, stage="judge", key="native", cost=2, tokens=100, seconds=10
        )
        db.flush()
        assert db.query(UsageReservation).count() == 1
        raise RuntimeError("rollback after native reservation")

    with pytest.raises(RuntimeError, match="rollback after native"):
        usage.prepare_call(
            context,
            request_key="atomic",
            provider="openai",
            model="test",
            input_token_bound=100,
            output_token_bound=100,
            admission_qualified=True,
            admission_hook=reserve_then_fail,
        )
    s.db.expire_all()
    assert s.db.query(UsageReservation).count() == 0
    assert window_budget.summary(s.db, s.workspace.id, window.id, run_id=s.run.id) is None

    def reserve(db, call):
        window_budget.reserve_in_transaction(
            db, s.ctx, stage="judge", key="native", cost=2, tokens=100, seconds=10
        )

    usage.prepare_call(
        context,
        request_key="committed",
        provider="openai",
        model="test",
        input_token_bound=100,
        output_token_bound=100,
        admission_qualified=True,
        admission_hook=reserve,
    )
    s.db.expire_all()
    assert s.db.query(UsageReservation).count() == 1
    assert window_budget.summary(s.db, s.workspace.id, window.id, run_id=s.run.id)["entries"] == 1
