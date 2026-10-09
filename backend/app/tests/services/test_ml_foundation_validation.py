"""The API rejects options and budgets the frozen model does not support."""
from types import SimpleNamespace
import pytest
from app.services.ml.families.base import SpecInvalid
from app.services.ml.families.forecasting_deep import FORECASTING_DEEP, validate_foundation
from app.services.tabular_datasets import TabularError


@pytest.mark.parametrize("raw,field", [
    ({"calendar": True}, "calendar"), ({"exog": {"promo": "future"}}, "exog"),
    ({"lags": [1, 7]}, "lags"), ({"tuning": "budget"}, "tuning"),
    ({"strategy": "recursive"}, "strategy"), ({"fill": "interpolate"}, "fill"),
    ({"horizon": 65}, "horizon"), ({"interval_level": .99}, "interval_level"),
    ({"shape": "multivariate"}, "shape"), ({"backtest_folds": 6}, "backtest_folds"),
])
def test_inapplicable_and_unbounded_settings_refused(raw, field):
    with pytest.raises(SpecInvalid) as caught:
        FORECASTING_DEEP.parse_spec({"time_column": "date", "horizon": 7, **raw})
    assert caught.value.field == field


def test_defaults_never_invent_regressor_options():
    parsed = FORECASTING_DEEP.parse_spec({"time_column": "date", "horizon": 7})
    assert parsed == {"time_column": "date", "horizon": 7, "shape": "single", "frequency": "auto",
                      "interval_level": .8, "backtest_folds": 3, "fill": "refuse"}


def test_family_preserves_forecasting_task_and_rejects_features():
    data = SimpleNamespace(name="History", row_count=200,
                           schema_json=[{"name": "date", "kind": "datetime"}, {"name": "value", "kind": "float"}],
                           stats_json={"date": {"distinct": 200}})
    request = dict(task="forecasting", target="value", features=[], algo="chronos_zero_shot", knobs={},
                   test_size=None, cross_validation=None, name=None,
                   spec=FORECASTING_DEEP.parse_spec({"time_column": "date", "horizon": 7}))
    validated = validate_foundation(data, **request)
    assert validated.task == "forecasting" and validated.family == "forecasting_deep"
    assert "strategy" not in validated.spec and validated.features == []
    with pytest.raises(TabularError):
        validate_foundation(data, **{**request, "features": ["date"]})


def test_catalog_family_and_algorithm_stay_unavailable_without_local_weights(monkeypatch):
    from app.services import tabular_ml
    from app.services.ml import runtime
    monkeypatch.setattr(tabular_ml, "family_availability", lambda *args, **kwargs: (True, None))
    monkeypatch.setattr(runtime, "model_availability", lambda *args, **kwargs: (False, "ML_DEEP_MODEL_MISSING"))
    catalog = tabular_ml.catalog_payload()
    family = next(item for item in catalog["families"] if item["key"] == "forecasting_deep")
    algo = next(item for item in catalog["algos"] if item["key"] == "chronos_zero_shot")
    assert family["available"] is False and algo["available"] is False
    assert family["reason"] == "ML_DEEP_MODEL_MISSING"


def test_deep_worker_does_not_offer_models_requiring_the_ts_runtime(monkeypatch):
    from app.services import tabular_ml
    from app.services.ml import runtime
    monkeypatch.setattr(tabular_ml, "family_availability",
                        lambda family, *args, **kwargs: (family.key != "forecasting", None))
    monkeypatch.setattr(runtime, "model_availability", lambda *args, **kwargs: (True, None))
    catalog = tabular_ml.catalog_payload()
    algos = {item["key"]: item for item in catalog["algos"]}
    assert algos["chronos_zero_shot"]["tasks"] == ["forecasting"]
    assert algos["chronos_zero_shot"]["available"] is True
    assert "forecasting" not in algos["gradient_boosting"]["tasks"]
    assert "classification" in algos["gradient_boosting"]["tasks"]
    assert "regression" in algos["gradient_boosting"]["tasks"]
    assert "forecasting" not in algos["ets"]["tasks"]


def test_frozen_model_rejects_knobs_before_loading_any_weights():
    with pytest.raises(TabularError) as caught:
        validate_foundation(None, task="forecasting", target="value", features=[],
                            algo="chronos_zero_shot", knobs={"learning_rate": .1},
                            test_size=None, cross_validation=None, name=None, spec={})
    assert caught.value.details["field"] == "knobs"
