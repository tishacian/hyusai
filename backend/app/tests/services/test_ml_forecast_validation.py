"""A forecast request, checked against the dataset profile before any worker runs.

Everything here is refused (or accepted) from the profile alone, so these tests
need neither skforecast nor the ml-ts image: the family is declared available,
and the datasets are real frames registered through the tabular plane, whose
profile is what the validator reads.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from app.core.config import settings
from app.services import tabular_ml
from app.services.ml.families import FORECASTING_FAMILY, family_of_task
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_training import enabled, store, workspace  # noqa: F401

HOURS = 24 * 21


def _cells(cells: int = 1, hours: int = HOURS) -> pl.DataFrame:
    """Hourly cell load: a daily cycle, a region, a covariate known in advance."""

    start = datetime(2026, 8, 1)
    rows = []
    for cell in range(cells):
        for hour in range(hours):
            rows.append(
                {
                    "cell_id": f"CAS-{100 + cell}-L01",
                    "region": "Casablanca" if cell % 2 == 0 else "Rabat",
                    "ts": start + timedelta(hours=hour),
                    "prb_utilization_pct": 40.0 + 15.0 * ((hour % 24) / 24) + cell,
                    "active_users": float(100 + (hour % 24) * 3 + cell),
                    "maintenance": float(hour % 168 == 3),
                    "label": "busy" if hour % 24 > 17 else "calm",
                }
            )
    return pl.DataFrame(rows)


@pytest.fixture()
def available(monkeypatch):
    """A worker of the ml-ts runtime is listening."""

    monkeypatch.setattr(tabular_ml, "family_availability", lambda family, db=None: (True, None))


def _register(db_session, workspace, frame: pl.DataFrame, name: str):
    from app.services.tabular_datasets import register_frame

    row = register_frame(db_session, workspace_id=workspace.id, name=name, frame=frame, source="upload")
    db_session.commit()
    return row


@pytest.fixture()
def single(db_session, workspace, store, enabled, available):  # noqa: F811
    return _register(db_session, workspace, _cells(1), "One cell")


@pytest.fixture()
def panel(db_session, workspace, store, enabled, available):  # noqa: F811
    return _register(db_session, workspace, _cells(3), "Three cells")


def _validate(dataset, **overrides):
    request = {
        "task": "forecasting",
        "target": "prb_utilization_pct",
        "algo": "gradient_boosting",
        "spec": {"time_column": "ts", "horizon": 24},
    }
    spec = dict(request["spec"])
    spec.update(overrides.pop("spec", {}))
    request.update(overrides)
    request["spec"] = spec
    return tabular_ml.validate_training(dataset, **request)


def _refused(dataset, **overrides) -> TabularError:
    with pytest.raises(TabularError) as caught:
        _validate(dataset, **overrides)
    return caught.value


# ---------------------------------------------------------------------------
# Accepted requests
# ---------------------------------------------------------------------------


def test_a_single_series_forecast_becomes_a_forecasting_spec_with_defaults_filled(single):
    spec = _validate(single)

    assert spec.task == "forecasting" and spec.family == "forecasting"
    assert family_of_task(spec.task) is FORECASTING_FAMILY
    assert spec.algo.key == "gradient_boosting"
    assert spec.spec["shape"] == "single" and spec.spec["strategy"] == "recursive"
    assert spec.spec["interval_level"] == 0.8 and spec.spec["backtest_folds"] == 3
    assert spec.spec["fill"] == "refuse" and spec.spec["calendar"] is True
    # Lags the author did not choose are the harness's to pick once it knows
    # the frequency: hourly data wants 24 and 168, not a guess made here.
    assert "lags" not in spec.spec
    assert "series_columns" not in spec.spec
    assert spec.cross_validation == 3
    assert 0 < spec.test_size <= 0.5
    assert spec.name.endswith("+24")


def test_a_panel_names_its_series_and_keeps_a_static_attribute(panel):
    spec = _validate(
        panel,
        spec={"shape": "panel", "series_columns": ["cell_id"], "exog": {"region": "static", "maintenance": "future"}},
    )

    assert spec.spec["series_columns"] == ["cell_id"]
    assert spec.spec["strategy"] == "recursive"
    assert sorted(spec.features) == ["maintenance", "region"]


def test_a_multivariate_forecast_is_direct_whatever_the_form_asked(single):
    spec = _validate(single, spec={"shape": "multivariate", "strategy": "recursive", "exog": {"active_users": "past"}})

    assert spec.spec["strategy"] == "direct"


def test_lags_the_author_chose_are_kept_sorted_and_held_against_the_history(single):
    assert _validate(single, spec={"lags": [24, 1, 168]}).spec["lags"] == [1, 24, 168]

    # 21 days of hours cannot feed a 400-step lag and four 24-step backtests.
    refusal = _refused(single, spec={"lags": [1, 500]})
    assert refusal.code == "ML_TS_HISTORY_TOO_SHORT"
    assert refusal.details["needed"] == 4 * 24 + 500


def test_a_statistical_model_is_offered_for_one_series(single):
    assert _validate(single, algo="ets").algo.key == "ets"
    assert _validate(single, algo="seasonal_naive").algo.key == "seasonal_naive"


# ---------------------------------------------------------------------------
# Refusals the form renders against a field
# ---------------------------------------------------------------------------


def test_the_time_column_must_exist_and_be_a_date(single):
    assert _refused(single, spec={"time_column": "when"}).code == "ML_TS_TIME_COLUMN_REQUIRED"
    refusal = _refused(single, spec={"time_column": "region"})
    assert refusal.code == "ML_TS_TIME_COLUMN_NOT_DATETIME"
    assert refusal.details["field"] == "time_column"


def test_a_text_target_cannot_be_forecast(single):
    assert _refused(single, target="label").code == "ML_TARGET_NOT_NUMERIC"


def test_repeated_dates_without_series_columns_say_it_is_a_panel(panel):
    refusal = _refused(panel)
    assert refusal.code == "ML_TS_DUPLICATE_TIMESTAMPS"
    assert refusal.details["field"] == "series_columns"


def test_a_covariate_role_has_to_fit_the_shape(single, panel):
    assert _refused(single, spec={"exog": {"active_users": "past"}}).code == "ML_TS_PAST_NEEDS_MULTIVARIATE"
    assert _refused(single, spec={"exog": {"region": "static"}}).code == "ML_TS_STATIC_NEEDS_PANEL"
    assert _refused(single, spec={"exog": {"label": "future"}}).code == "ML_TS_EXOG_NOT_NUMERIC"
    assert _refused(single, spec={"shape": "multivariate"}).code == "ML_TS_MULTIVARIATE_NEEDS_SERIES"
    reused = _refused(panel, spec={"shape": "panel", "series_columns": ["cell_id"], "exog": {"ts": "future"}})
    assert reused.code == "ML_TS_COLUMN_REUSED"
    assert _refused(single, spec={"exog": {"nope": "future"}}).code == "ML_FEATURE_UNKNOWN"


def test_an_algorithm_has_to_forecast_and_fit_the_shape(single, panel):
    assert _refused(single, algo="knn").code == "ML_ALGO_TASK_MISMATCH"
    refusal = _refused(panel, algo="arima", spec={"shape": "panel", "series_columns": ["cell_id"]})
    assert refusal.code == "ML_TS_ALGO_SHAPE_MISMATCH"
    assert refusal.details == {"algo": "arima", "shape": "panel"}


def test_a_horizon_the_history_cannot_backtest_is_refused_with_what_it_needs(single):
    refusal = _refused(single, spec={"horizon": 200})
    assert refusal.code == "ML_TS_HISTORY_TOO_SHORT"
    assert refusal.details["history"] == HOURS
    assert refusal.details["needed"] > HOURS


def test_a_panel_above_the_series_ceiling_is_refused(panel, monkeypatch):
    monkeypatch.setattr(settings, "ml_ts_max_series", 2)
    refusal = _refused(panel, spec={"shape": "panel", "series_columns": ["cell_id"]})
    assert refusal.code == "ML_TS_TOO_MANY_SERIES" and refusal.details["series"] == 3


@pytest.mark.parametrize(
    "spec",
    [
        {"horizon": None},
        {"horizon": 0},
        {"horizon": 10_000_000},
        {"shape": "cube"},
        {"lags": [1, "x"]},
        {"interval_level": 1.5},
        {"exog": {"active_users": "sometimes"}},
        {"window": 3},
    ],
)
def test_a_malformed_problem_definition_is_a_spec_refusal(single, spec):
    assert _refused(single, spec=spec).code == "ML_SPEC_INVALID"


def test_a_panel_without_series_columns_is_a_spec_refusal(panel):
    assert _refused(panel, spec={"shape": "panel"}).code == "ML_SPEC_INVALID"


def test_no_listening_worker_refuses_up_front_rather_than_queueing_forever(single, monkeypatch):
    monkeypatch.setattr(tabular_ml, "family_availability", lambda family, db=None: (False, "no_worker"))

    refusal = _refused(single)
    assert refusal.code == "ML_FAMILY_UNAVAILABLE"
    assert refusal.details == {"family": "forecasting", "reason": "no_worker"}


# ---------------------------------------------------------------------------
# Catalog and harness agreement
# ---------------------------------------------------------------------------


def test_the_catalog_describes_the_forecasting_family_the_form_will_render(enabled):  # noqa: F811
    payload = tabular_ml.catalog_payload()

    assert "forecasting" in payload["tasks"]
    family = next(entry for entry in payload["families"] if entry["key"] == "forecasting")
    assert family["runtime"] == "ml-ts" and family["serving"] == "remote"
    fields = {field["key"]: field for field in family["spec_fields"]}
    assert fields["time_column"]["required"] and fields["time_column"]["column_kinds"] == ["datetime"]
    assert fields["horizon"]["max"] == settings.ml_ts_max_horizon
    assert fields["series_columns"]["when"] == {"shape": ["panel"]}
    forecasters = {algo["key"] for algo in payload["algos"] if "forecasting" in algo["tasks"]}
    assert forecasters == {"gradient_boosting", "random_forest", "linear", "ets", "arima", "seasonal_naive"}


def test_the_spec_frequencies_are_the_ones_the_harness_has_seasons_and_lags_for():
    from app.resources import ml_forecast_harness as harness
    from app.services.ml.families.forecasting import FREQUENCIES

    offered = set(FREQUENCIES) - {"auto"}
    assert offered == set(harness.SEASON) == set(harness.DEFAULT_LAGS)
    # pandas spells a frequency several ways; each lands on the spec's name.
    assert harness.frequency_key("h") == "h" and harness.frequency_key("W-SUN") == "W"
    assert harness.frequency_key("MS") == "MS" and harness.frequency_key("QS-OCT") == "QS"
    assert harness.frequency_key("2h") is None and harness.frequency_key("min") is None
    # Defaults are trimmed to what the history can feed, never emptied.
    assert harness.default_lags("h", history=200, reserved=96) == [1, 2, 3, 24]
    assert harness.default_lags("h", history=10, reserved=96) == [1]


def test_the_harness_and_its_model_import_nothing_from_the_application():
    """Both run where the application is not installed: the harness in a
    resource-capped subprocess, the pyfunc wherever MLflow loads the model."""

    import ast
    from pathlib import Path

    resources = Path(tabular_ml.__file__).resolve().parents[1] / "resources"
    for name in ("ml_forecast_harness.py", "ml_forecast_pyfunc.py"):
        tree = ast.parse((resources / name).read_text(encoding="utf-8"))
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not [module for module in imported if module and module.startswith("app")], name
