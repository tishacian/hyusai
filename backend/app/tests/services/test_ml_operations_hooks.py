"""Runtime hooks count produced rows and persist monitor transitions atomically."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.db import base
from app.services import ml_permissions, tabular_predict
from app.services.ml_inference_cost import InferenceCostCollector, install_collector
from app.services.skill_invocation_snapshot import SkillInvocationCostEvidence
from app.services.skills_registry.wrappers import skills


@pytest.fixture
def runtime(monkeypatch):
    row = SimpleNamespace(
        id="output",
        workspace_id="workspace",
        name="Output",
        slug="output",
        version=1,
        row_count=6,
        column_count=2,
        schema_json=[],
        status="ready",
        error=None,
        lineage_json={},
    )
    db = SimpleNamespace(
        query=lambda *args: SimpleNamespace(filter=lambda *args: SimpleNamespace(first=lambda: row))
    )
    monkeypatch.setattr(base, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(ml_permissions, "require_context", lambda *args: None)
    monkeypatch.setattr(
        skills, "_resolve_model", lambda *args: SimpleNamespace(id="model", signature_json={})
    )
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    tariff = SkillInvocationCostEvidence(
        0.25, True, {"unit": "per_prediction", "currency": "USD", "state": "calculated"}
    )
    collector = InferenceCostCollector(tariff)
    ctx = {"workspace_id": "workspace"}
    install_collector(ctx, collector)
    fallback = SkillInvocationCostEvidence(0, False, {"state": "not_measured"})
    return SimpleNamespace(row=row, ctx=ctx, cost=lambda: collector.settle(fallback))


async def test_predict_counts_produced_answers_not_caller_claims(runtime, monkeypatch):
    monkeypatch.setattr(
        tabular_predict,
        "predict_rows",
        lambda *args, **kwargs: {"predictions": [{"prediction": 1}, {"prediction": 2}]},
    )
    await skills._ml_predict_v1(
        {"rows": [{"x": 1}] * 8, "scored_rows": 999, "_predict": {"model_id": "model"}}, runtime.ctx
    )
    assert runtime.cost().cost == 0.5
    assert runtime.cost().evidence["observed_rows"] == 2


async def test_predict_failure_does_not_report_successful_rows(runtime, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("local inference failed")

    monkeypatch.setattr(tabular_predict, "predict_rows", fail)
    with pytest.raises(RuntimeError):
        await skills._ml_predict_v1(
            {"rows": [{"x": 1}], "_predict": {"model_id": "model"}}, runtime.ctx
        )
    assert runtime.cost().cost_measured is False


@pytest.mark.parametrize("streaming", [False, True])
async def test_score_counts_runner_result_not_input_envelope(runtime, monkeypatch, streaming):
    from app.services import tabular_datasets
    from app.services.dataops import rollout, scoring

    monkeypatch.setattr(rollout, "enabled", lambda *args: streaming)
    monkeypatch.setattr(
        tabular_datasets, "resolve_dataset_ref", lambda *args, **kwargs: runtime.row
    )
    result = {"dataset_id": "output", "scored_rows": 7, "rows": 777}
    monkeypatch.setattr(tabular_predict, "score_dataset", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        scoring, "submit_score", lambda *args, **kwargs: SimpleNamespace(id="execution")
    )

    async def settled(*args, **kwargs):
        return "succeeded", result, None, None

    monkeypatch.setattr(skills, "_await_managed_execution", settled)
    answer = await skills._ml_batch_score_v1(
        {"upstream": {"dataset_id": "input", "rows": 123456}, "_predict": {"model_id": "model"}},
        runtime.ctx,
    )
    assert answer["dataset_id"] == "output"
    assert runtime.cost().evidence["observed_rows"] == 7


async def test_deferred_score_has_no_quantity_before_completion(runtime, monkeypatch):
    from app.services.dataops import rollout, scoring
    from app.services.execution.runtimes.deferred import DeferredNativeExecution

    monkeypatch.setattr(rollout, "enabled", lambda *args: True)
    monkeypatch.setattr(
        scoring, "submit_score", lambda *args, **kwargs: SimpleNamespace(id="execution")
    )
    runtime.ctx["_native_submission_only"] = True
    answer = await skills._ml_batch_score_v1(
        {"dataset": {"dataset_id": "input", "rows": 999}, "_predict": {"model_id": "model"}},
        runtime.ctx,
    )
    assert isinstance(answer, DeferredNativeExecution)
    assert runtime.cost().cost_measured is False


@pytest.mark.parametrize("row_count", [6, None])
async def test_forecast_counts_ready_output_dataset_not_horizon_claim(
    runtime, monkeypatch, row_count
):
    from app.services.ml import forecast_serving

    runtime.row.row_count = row_count
    monkeypatch.setattr(
        forecast_serving,
        "submit_forecast_dataset",
        lambda *args, **kwargs: SimpleNamespace(id="output"),
    )
    await skills._ml_forecast_v1(
        {"rows": 9999, "_forecast": {"model_id": "model", "horizon": 200}}, runtime.ctx
    )
    assert runtime.cost().cost_measured is (row_count is not None)
    if row_count is not None:
        assert runtime.cost().evidence["observed_rows"] == 6


async def test_streaming_score_checks_actor_before_submission(runtime, monkeypatch):
    from app.services.dataops import rollout, scoring

    monkeypatch.setattr(rollout, "enabled", lambda *args: True)

    def deny(*args):
        raise PermissionError("score denied")

    monkeypatch.setattr(ml_permissions, "require_context", deny)
    submitted = []
    monkeypatch.setattr(scoring, "submit_score", lambda *args, **kwargs: submitted.append(True))
    with pytest.raises(PermissionError):
        await skills._ml_batch_score_v1(
            {"dataset": {"dataset_id": "input"}, "_predict": {"model_id": "model"}}, runtime.ctx
        )
    assert submitted == []
    assert runtime.cost().cost_measured is False


async def test_failed_stream_does_not_report_partial_output_as_success(runtime, monkeypatch):
    from app.services.dataops import rollout, scoring

    monkeypatch.setattr(rollout, "enabled", lambda *args: True)
    monkeypatch.setattr(
        scoring, "submit_score", lambda *args, **kwargs: SimpleNamespace(id="execution")
    )

    async def failed(*args, **kwargs):
        return "failed", {"scored_rows": 999}, "ML_SCORE_FAILED", None

    monkeypatch.setattr(skills, "_await_managed_execution", failed)
    with pytest.raises(ValueError, match="ML_SCORE_FAILED"):
        await skills._ml_batch_score_v1(
            {"dataset": {"dataset_id": "input"}, "_predict": {"model_id": "model"}}, runtime.ctx
        )
    assert runtime.cost().cost_measured is False
