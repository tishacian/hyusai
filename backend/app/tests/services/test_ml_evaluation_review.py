"""Agent proposals read development evidence, with existing workspace scoping."""

import copy

import pytest

from app.services.ml_evaluation_review import review
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_comparison import two_fits  # noqa: F401
from app.tests.services.test_ml_training import dataset, enabled, store, workspace  # noqa: F401


def evidence():
    return {
        "evaluation": {"schema": 1, "status": "stored", "dataset": {"id": "data", "version": 1}},
        "diagnostics": {
            "schema": 1,
            "engine": "skore",
            "role": "development",
            "scope": "development_base_estimator",
            "served_model": False,
            "status": "completed",
            "checks": [
                {"code": "SKD001", "section": "issue"},
                {"code": "SKD002", "section": "error"},
                {"code": "SKD004", "section": "passed"},
            ],
        },
    }


def test_review_is_read_only_and_does_not_use_final_test_scores(db_session, two_fits):
    model, _ = two_fits
    model.metrics_json = {**model.metrics_json, **evidence()}
    db_session.commit()
    before = copy.deepcopy(model.metrics_json), model.is_champion
    result = review(db_session, model_id=model.id, workspace_id=model.workspace_id)
    assert result["mode"] == "proposal_only"
    assert [row["code"] for row in result["proposals"]] == ["SKD001"]
    assert result["proposals"][0]["requires"] == [
        "review_flow_plan",
        "explicit_training",
        "independent_evaluation",
        "explicit_promotion",
    ]
    assert before == (model.metrics_json, model.is_champion)
    model.metrics_json = {**model.metrics_json, "scores": [{"key": "f1", "value": 0.001}]}
    assert review(db_session, model_id=model.id, workspace_id=model.workspace_id) == result


@pytest.mark.parametrize(
    "change", [{"role": "final_test"}, {"served_model": True}, {"status": "timed_out"}]
)
def test_invalid_or_partial_scope_cannot_generate_training_proposals(db_session, two_fits, change):
    model, _ = two_fits
    payload = evidence()
    payload["diagnostics"].update(change)
    model.metrics_json = payload
    assert review(db_session, model_id=model.id, workspace_id=model.workspace_id)["proposals"] == []


def test_legacy_and_foreign_models_are_not_actionable(db_session, two_fits):
    model, _ = two_fits
    assert review(db_session, model_id=model.id, workspace_id=model.workspace_id)["proposals"] == []
    with pytest.raises(TabularError) as raised:
        review(db_session, model_id=model.id, workspace_id="another-workspace")
    assert raised.value.code == "ML_MODEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_agent_cannot_supply_its_own_workspace():
    from app.services.skills_registry.wrappers import _ml_evaluation_review_v1

    with pytest.raises(ValueError, match="WORKSPACE_REQUIRED"):
        await _ml_evaluation_review_v1({"workspace_id": "forged", "model_id": "model"})
