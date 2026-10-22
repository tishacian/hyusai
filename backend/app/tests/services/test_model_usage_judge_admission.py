"""Real Judge + durable admission, with only the provider transport replaced."""

from app.models.model_usage import ModelUsageCall, UsageBudgetBucket, UsageReservation
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services import model_usage
from app.services.evaluation import typed_judge
from app.tests.services import test_typed_judge as fixtures

payload = fixtures.payload
context = fixtures.context
provider = fixtures.provider


def budget(db, context, monkeypatch, *, tokens):
    monkeypatch.setattr(model_usage, "budget_readiness", lambda ws: {"ready": True})
    return model_usage.save_budget(
        db,
        db.get(Workspace, context["workspace_id"]),
        db.get(User, context["user_id"]),
        scope="workspace",
        enabled=True,
        max_tokens=tokens,
        currency_limits={},
        expected_revision=0,
    )


async def test_global_refusal_leaves_no_native_judge_reservation(
    db_session, payload, context, provider, monkeypatch
):
    budget(db_session, context, monkeypatch, tokens=1)
    result = await typed_judge.typed_evaluate(payload, context)
    assert result["reason"] == "USAGE_BUDGET_EXHAUSTED"
    assert not provider.calls
    db_session.expire_all()
    job = db_session.query(WorkspaceJob).filter_by(kind=typed_judge.KIND).one()
    assert job.result["calls"] == 0 and job.result["charged_tokens"] == 0
    assert db_session.query(UsageReservation).count() == 0
    assert db_session.query(ModelUsageCall).one().status == "blocked"


async def test_native_judge_refusal_rolls_back_global_reservation(
    db_session, payload, context, provider, monkeypatch
):
    budget(db_session, context, monkeypatch, tokens=1_000_000)
    payload["budget"]["max_calls"] = 1
    first = await typed_judge.typed_evaluate(payload, context)
    assert first["status"] == "completed"
    payload["request_key"] = "second-unit"
    second = await typed_judge.typed_evaluate(payload, context)
    assert second["reason"] == "JUDGE_BUDGET_EXHAUSTED"
    assert len(provider.calls) == 1
    db_session.expire_all()
    bucket = db_session.query(UsageBudgetBucket).one()
    assert bucket.reserved_tokens == 0 and bucket.consumed_tokens == 200
    assert db_session.query(ModelUsageCall).count() == 1
    assert db_session.query(UsageReservation).count() == 1
    job = db_session.query(WorkspaceJob).filter_by(kind=typed_judge.KIND).one()
    assert job.result["calls"] == 1
