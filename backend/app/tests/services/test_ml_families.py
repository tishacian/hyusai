"""The family-neutral ML plane: knobs, metric directions, families, runtimes."""

from __future__ import annotations

import ast
import re
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.tabular import MLModel, MLRuntimeHeartbeat
from app.services import tabular_ml
from app.services.ml import families as ml_families
from app.services.ml import metrics as metric_registry
from app.services.ml import runtime as ml_runtime
from app.services.ml.families import TABULAR, Family, SpecField, SpecInvalid, get_family
from app.services.ml.knobs import Knob
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_training import (  # noqa: F401
    _stub_harness,
    _summary,
    dataset,
    enabled,
    store,
    workspace,
)

BACKEND = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Knobs
# ---------------------------------------------------------------------------


def test_numeric_knobs_keep_their_clamp_and_auto_sentinel():
    knob = Knob("max_depth", "int", 0, 0, 40, 1, auto_at=0)
    assert knob.coerce(99) == 40 and knob.coerce("7.6") == 8 and knob.coerce(0) is None
    assert knob.coerce("junk") is None  # falls back to the default, which is auto
    assert set(knob.payload()) == {"key", "kind", "default", "min", "max", "step", "auto_at"}


def test_enum_bool_and_int_list_knobs_coerce_into_their_own_domain():
    encoder = Knob("text_encoder", "enum", "lsa", choices=("lsa", "minhash"))
    assert encoder.coerce("minhash") == "minhash" and encoder.coerce("bert") == "lsa"
    assert encoder.payload() == {"key": "text_encoder", "kind": "enum", "default": "lsa", "choices": ["lsa", "minhash"]}

    toggle = Knob("calibrate", "bool", False)
    assert toggle.coerce(True) is True and toggle.coerce("yes") is True
    assert toggle.coerce("off") is False and toggle.coerce("maybe") is False
    assert toggle.payload() == {"key": "calibrate", "kind": "bool", "default": False}

    lags = Knob("lags", "int_list", (1, 24), 1, 168, max_items=4)
    assert lags.coerce([168, 1, 1, 24.2, 999, True, "x"]) == [1, 24, 168]
    assert lags.coerce([5, 4, 3, 2, 1]) == [1, 2, 3, 4]
    assert lags.coerce("1,2") == [1, 24] and lags.coerce([]) == [1, 24]
    assert lags.payload()["max_items"] == 4 and lags.payload()["default"] == [1, 24]


@pytest.mark.parametrize(
    "build",
    [
        lambda: Knob("k", "text", 1),
        lambda: Knob("k", "int", 50, 0, 10),
        lambda: Knob("k", "enum", "c", choices=("a", "b")),
        lambda: Knob("k", "bool", 1),
        lambda: Knob("k", "int_list", (1, 2, 3), 1, 10, max_items=2),
        lambda: Knob("k", "int_list", (0,), 1, 10, max_items=2),
    ],
)
def test_a_knob_that_contradicts_itself_is_refused_at_declaration(build):
    with pytest.raises(ValueError):
        build()


# ---------------------------------------------------------------------------
# Metric registry
# ---------------------------------------------------------------------------


def test_every_metric_ranks_in_its_own_direction():
    assert metric_registry.rank_value("roc_auc", 0.8) == 0.8
    assert metric_registry.rank_value("rmse", 3.0) == -3.0
    assert metric_registry.rank_value("mase", 0.7) > metric_registry.rank_value("mase", 0.9)
    for unranked in (("coverage", 0.8), ("nonsense", 1.0), ("r2", None), ("r2", True), ("r2", float("nan"))):
        assert metric_registry.rank_value(*unranked) is None


def test_every_metric_the_harness_reports_is_registered():
    tree = ast.parse((BACKEND / "app" / "resources" / "ml_train_harness.py").read_text(encoding="utf-8"))
    card = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_CARD_METRICS" for t in node.targets)
    )
    keys = {element.value for element in ast.walk(card) if isinstance(element, ast.Constant) and isinstance(element.value, str)}
    assert keys and keys <= set(metric_registry.METRIC_BY_KEY)


def test_the_frontend_fallback_agrees_with_the_registry():
    """Until every surface reads the catalog's registry, its offline copy must
    not rank a metric the other way."""

    source = (BACKEND.parent / "frontend-ng/src/app/features/models/models.vm.ts").read_text(encoding="utf-8")
    entries = re.findall(r"^  (\w+): \{[^}]*higherIsBetter: (true|false)", source, re.MULTILINE)
    assert len(entries) >= 12
    for key, higher in entries:
        assert metric_registry.direction(key) == (1 if higher == "true" else -1), key


def _ready(db_session, workspace, *, version, key, value):
    row = MLModel(
        workspace_id=workspace.id,
        name="Load",
        slug="load",
        version=version,
        task="regression",
        algo="linear",
        target="y",
        status="ready",
        metrics_json={"primary": {"key": key, "value": value}},
    )
    db_session.add(row)
    return row


def test_the_challenger_is_the_lowest_error_when_the_primary_is_an_error(db_session, workspace):
    champion = _ready(db_session, workspace, version=1, key="rmse", value=6.0)
    champion.is_champion = True
    _ready(db_session, workspace, version=2, key="rmse", value=9.0)
    better = _ready(db_session, workspace, version=3, key="rmse", value=4.0)
    # Higher is better for r2, but it is not the metric the champion is judged by.
    _ready(db_session, workspace, version=4, key="r2", value=0.99)
    db_session.commit()
    assert tabular_ml.runner_up(db_session, champion).id == better.id


def test_an_unranked_primary_never_nominates_a_challenger(db_session, workspace):
    champion = _ready(db_session, workspace, version=1, key="coverage", value=0.8)
    champion.is_champion = True
    _ready(db_session, workspace, version=2, key="coverage", value=0.95)
    db_session.commit()
    assert tabular_ml.runner_up(db_session, champion) is None


# ---------------------------------------------------------------------------
# Families and their spec
# ---------------------------------------------------------------------------


FORECAST_FIELDS = (
    SpecField("time_column", "column", required=True, column_kinds=("datetime",)),
    SpecField("horizon", "int", required=True, minimum=1, maximum=720),
    SpecField("shape", "enum", default="single", choices=("single", "panel")),
    SpecField("series_columns", "columns", required=True, max_items=3, when=(("shape", ("panel",)),)),
    SpecField("exog", "column_roles", choices=("future", "static"), max_items=8),
)


def _forecasting(**overrides) -> Family:
    base = Family(
        key="forecasting",
        tasks=("forecasting",),
        runtime="ml-ts",
        # An existing setting stands in for the family's own queue setting.
        queue_setting="celery_recipe_queue",
        serving="remote",
        required_modules=("json",),
        harness=Path("/nowhere/ml_forecast_harness.py"),
        spec_fields=FORECAST_FIELDS,
    )
    return replace(base, **overrides)


def test_rows_from_before_families_and_unknown_keys_are_tabular():
    assert get_family(None) is TABULAR and get_family("tabular") is TABULAR
    assert get_family("unheard-of") is TABULAR
    assert ml_families.family_of_task("regression") is TABULAR
    assert ml_families.family_of_task("forecasting") is ml_families.FORECASTING_FAMILY
    assert ml_families.family_of_task("clustering") is None


def test_a_spec_is_parsed_by_its_family_fields():
    family = _forecasting()
    assert family.parse_spec({"time_column": "ts", "horizon": 24}) == {"time_column": "ts", "horizon": 24, "shape": "single"}
    panel = family.parse_spec(
        {"time_column": "ts", "horizon": 24.0, "shape": "panel", "series_columns": ["cell", "cell"], "exog": {"promo": "future"}}
    )
    assert panel["series_columns"] == ["cell"] and panel["exog"] == {"promo": "future"}


# Synthetic fields exercise the extension mechanism without offering options
# before their training effects exist.
TABULAR_TEST_FIELDS = (
    SpecField("regression_only", "bool", default=False, when=(("task", ("regression",)),)),
    SpecField("classification_only", "bool", default=False, when=(("task", ("classification",)),)),
    SpecField("budget", "int", required=True, minimum=1, maximum=10, when=(("mode", ("on",)),)),
    SpecField("mode", "enum", default="off", choices=("off", "on")),
)


def test_tabular_catalog_does_not_offer_options_without_training_effects():
    assert {field.key for field in TABULAR.spec_fields} == {"explain", "fairness_columns"}
    assert TABULAR.parse_spec({}, task="regression") == {"explain": "off"}
    with pytest.raises(SpecInvalid) as error:
        TABULAR.parse_spec({"intervals": "conformal"}, task="regression")
    assert error.value.field == "intervals"


def test_tabular_visibility_uses_resolved_task_and_defaults_without_storing_task():
    family = replace(TABULAR, spec_fields=TABULAR_TEST_FIELDS)
    assert family.parse_spec({}, task="regression") == {"regression_only": False, "mode": "off"}
    assert family.parse_spec({}, task="classification") == {"classification_only": False, "mode": "off"}
    with pytest.raises(SpecInvalid) as error:
        family.parse_spec({"task": "classification"}, task="regression")
    assert error.value.field == "task"


def test_incompatible_tabular_options_are_removed_before_validation_with_a_warning():
    warnings = []
    family = replace(TABULAR, spec_fields=TABULAR_TEST_FIELDS)
    parsed = family.parse_spec(
        {"classification_only": "stale-invalid-value", "budget": "stale-invalid-value"},
        task="regression", warnings=warnings,
    )
    assert parsed == {"regression_only": False, "mode": "off"}
    assert warnings == [
        {"code": "ML_SPEC_FIELD_IGNORED", "field": "classification_only", "task": "regression"},
        {"code": "ML_SPEC_FIELD_IGNORED", "field": "budget", "task": "regression"},
    ]


def test_shown_tabular_options_are_required_and_validated_even_before_their_controller():
    family = replace(TABULAR, spec_fields=TABULAR_TEST_FIELDS)
    for raw in ({"mode": "on"}, {"mode": "on", "budget": 11}):
        with pytest.raises(SpecInvalid) as error:
            family.parse_spec(raw, task="regression")
        assert error.value.field == "budget"
    assert family.parse_spec({"mode": "on", "budget": 3}, task="regression")["budget"] == 3


def test_task_dependent_required_fields_use_the_same_visibility_context():
    family = replace(TABULAR, spec_fields=(
        SpecField("required_number", "int", required=True, when=(("task", ("regression",)),)),
    ))
    assert family.parse_spec({}, task="classification") == {}
    with pytest.raises(SpecInvalid) as error:
        family.parse_spec({}, task="regression")
    assert error.value.field == "required_number"


@pytest.mark.parametrize("kind", ["int", "float"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**400])
def test_spec_numbers_that_cannot_be_stored_as_finite_json_are_coded_refusals(kind, value):
    with pytest.raises(SpecInvalid) as error:
        SpecField("number", kind).parse(value)
    assert error.value.field == "number"


def test_training_plan_resolves_task_before_spec_and_persists_only_visible_options(
    db_session, workspace, dataset, enabled, monkeypatch
):
    monkeypatch.setattr(tabular_ml, "TABULAR", replace(TABULAR, spec_fields=TABULAR_TEST_FIELDS))
    monkeypatch.setattr(tabular_ml, "family_of_task", lambda task: tabular_ml.TABULAR)
    spec = tabular_ml.validate_training(
        dataset, task=None, target="churn", spec={"regression_only": True}, features=["arpu"]
    )
    assert spec.task == "classification"
    assert spec.spec == {"classification_only": False, "mode": "off"}
    assert spec.warnings == [{"code": "ML_SPEC_FIELD_IGNORED", "field": "regression_only", "task": "classification"}]
    model = tabular_ml.create_model(db_session, workspace_id=workspace.id, spec=spec)
    assert model.spec_json == spec.spec
    assert model.params_json["warnings"] == spec.warnings
    with pytest.raises(TabularError) as error:
        tabular_ml.validate_training(dataset, task=None, target="churn", spec={"mode": "on", "budget": 11})
    assert error.value.code == "ML_SPEC_INVALID"
    assert error.value.details == {"field": "budget"}


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        ({"time_column": "ts", "horizon": 24, "lags": [1]}, "lags"),
        ({"horizon": 24}, "time_column"),
        ({"time_column": "ts", "horizon": 0}, "horizon"),
        ({"time_column": "ts", "horizon": 2.5}, "horizon"),
        ({"time_column": "ts", "horizon": True}, "horizon"),
        ({"time_column": "ts", "horizon": 24, "shape": "panel"}, "series_columns"),
        ({"time_column": "ts", "horizon": 24, "exog": {"promo": "past"}}, "exog"),
        ({"time_column": "ts", "horizon": 24, "shape": "panel", "series_columns": ["a", "b", "c", "d"]}, "series_columns"),
        ("not an object", "spec"),
    ],
)
def test_a_spec_the_family_cannot_read_names_the_field(raw, field):
    with pytest.raises(SpecInvalid) as error:
        _forecasting().parse_spec(raw)
    assert error.value.field == field


def test_the_tabular_family_accepts_only_implemented_spec_fields(dataset, enabled):
    assert tabular_ml.validate_training(dataset, task=None, target="churn", spec={}).spec == {"explain": "off"}
    with pytest.raises(TabularError) as error:
        tabular_ml.validate_training(dataset, task=None, target="churn", spec={"horizon": 3})
    assert error.value.code == "ML_SPEC_INVALID" and error.value.details == {"field": "horizon"}


def test_a_family_trains_on_its_own_queue(monkeypatch):
    monkeypatch.setattr(settings, "celery_task_default_queue", "cpu")
    monkeypatch.setattr(settings, "celery_ml_tabular_queue", "")
    assert TABULAR.train_queue() == "cpu"
    monkeypatch.setattr(settings, "celery_ml_tabular_queue", "ml_tabular")
    assert TABULAR.train_queue() == "ml_tabular"
    assert _forecasting(queue_setting="celery_ml_unset_queue").train_queue() == "cpu"


def test_dispatch_sends_the_one_training_task_to_the_family_queue(db_session, workspace, monkeypatch):
    import app.workers.celery_app as celery_module

    sent = {}

    def send_task(name, args=(), queue=None):
        sent.update(name=name, args=args, queue=queue)
        return SimpleNamespace(id="task-1")

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(settings, "celery_ml_tabular_queue", "ml_tabular")
    monkeypatch.setattr(celery_module.celery_app, "send_task", send_task)
    row = MLModel(workspace_id=workspace.id, name="m", slug="m", task="classification", algo="linear", target="y")
    db_session.add(row)
    db_session.commit()
    assert tabular_ml.dispatch_training(db_session, row) == "task-1"
    assert sent == {"name": "agentium.ml_train", "args": (row.id,), "queue": "ml_tabular"}


# ---------------------------------------------------------------------------
# Runtimes
# ---------------------------------------------------------------------------


def test_the_fingerprint_names_the_runtime_and_the_versions_a_load_depends_on():
    identity = ml_runtime.runtime_fingerprint()
    assert set(identity) == {"runtime", "image_revision", "python", "fingerprint", "packages"}
    assert re.fullmatch(r"[0-9a-f]{64}", identity["fingerprint"])
    assert set(identity["packages"]) <= set(ml_runtime.KEY_PACKAGES)


def test_the_general_worker_never_has_to_prove_it_is_there(db_session, monkeypatch):
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    assert ml_runtime.family_availability(TABULAR, db_session) == (True, None)
    assert ml_runtime.family_availability(TABULAR, None) == (True, None)


def test_a_family_image_is_offered_only_while_its_heartbeat_is_fresh(db_session, monkeypatch):
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "celery_recipe_queue", "ml_ts")
    monkeypatch.setattr(settings, "celery_task_default_queue", "cpu")
    monkeypatch.setattr(settings, "ml_runtime_heartbeat_ttl_s", 180.0)
    family = _forecasting()
    assert ml_runtime.family_availability(family, db_session) == (False, "no_worker")

    monkeypatch.setattr(settings, "ml_runtime", "ml-ts")
    now = datetime.utcnow()
    ml_runtime.beat(db_session, queues=["ml_ts_rpc", "ml_ts"], hostname="ts-1", now=now - timedelta(seconds=600))
    db_session.commit()
    assert ml_runtime.family_availability(family, db_session, now=now) == (False, "no_worker")

    ml_runtime.beat(db_session, queues=["ml_ts"], hostname="ts-1", now=now)
    db_session.commit()
    assert db_session.query(MLRuntimeHeartbeat).count() == 1  # upserted, not appended
    assert ml_runtime.family_availability(family, db_session, now=now) == (True, None)
    # Listening on another queue does not count: this one trains on "cpu".
    assert ml_runtime.family_availability(_forecasting(queue_setting="celery_ml_tabular_queue"), db_session, now=now)[0] is False


def test_in_eager_mode_a_family_is_available_when_its_modules_import(monkeypatch):
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    assert ml_runtime.family_availability(_forecasting()) == (True, None)
    assert ml_runtime.family_availability(_forecasting(required_modules=("no_such_module_x",))) == (False, "runtime_missing")


def test_an_unavailable_family_is_refused_before_any_validation(dataset, monkeypatch, enabled):
    family = _forecasting(required_modules=("no_such_module_x",), validator=lambda *a, **k: pytest.fail("validated"))
    monkeypatch.setattr(tabular_ml, "family_of_task", lambda task: family if task == "forecasting" else TABULAR)
    with pytest.raises(TabularError) as error:
        tabular_ml.validate_training(dataset, task="forecasting", target="churn", spec={"time_column": "ts", "horizon": 2})
    assert error.value.code == "ML_FAMILY_UNAVAILABLE" and error.value.status_code == 409


def test_a_non_tabular_family_validates_its_own_request(dataset, monkeypatch, enabled):
    seen = {}
    family = _forecasting(validator=lambda dataset, **kwargs: seen.update(kwargs) or "spec-from-family")
    monkeypatch.setattr(tabular_ml, "family_of_task", lambda task: family if task == "forecasting" else TABULAR)
    result = tabular_ml.validate_training(dataset, task="forecasting", target="churn", spec={"time_column": "ts", "horizon": 2})
    assert result == "spec-from-family"
    assert seen["spec"] == {"time_column": "ts", "horizon": 2, "shape": "single"}
    assert seen["task"] == "forecasting" and seen["target"] == "churn"
    # Without a validator, a family is not trainable yet.
    monkeypatch.setattr(tabular_ml, "family_of_task", lambda task: _forecasting() if task == "forecasting" else TABULAR)
    with pytest.raises(TabularError) as error:
        tabular_ml.validate_training(dataset, task="forecasting", target="churn")
    assert error.value.code == "ML_TASK_UNKNOWN"


# ---------------------------------------------------------------------------
# Lifecycle: the family on the row, the runtime that fitted it
# ---------------------------------------------------------------------------


def test_a_trained_row_records_its_family_and_the_interpreter_that_fitted_it(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    captured = _stub_harness(monkeypatch)
    model = tabular_ml.submit_training(
        db_session, workspace_id=workspace.id, dataset_ref={"dataset_id": dataset.id}, target="churn"
    )
    assert model.status == "ready" and model.family == "tabular" and model.spec_json == {"explain": "off"}
    assert model.runtime_json["fingerprint"] == ml_runtime.runtime_fingerprint()["fingerprint"]
    assert captured["manifest"]["family"] == "tabular" and captured["manifest"]["spec"] == {"explain": "off"}
    detail = tabular_ml.serialize_model(model, include_detail=True)
    assert detail["family"] == "tabular" and detail["runtime"]["runtime"] == settings.ml_runtime


def test_a_task_delivered_to_an_image_without_the_family_stack_fails_closed(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    captured = _stub_harness(monkeypatch)
    monkeypatch.setattr(Family, "missing_modules", lambda self: ["skforecast"])
    model = tabular_ml.submit_training(
        db_session, workspace_id=workspace.id, dataset_ref={"dataset_id": dataset.id}, target="churn"
    )
    assert model.status == "failed" and model.error.startswith("ML_RUNTIME_MISSING: skforecast")
    assert "argv" not in captured  # no fit was attempted


def test_the_family_image_app_registers_the_training_task_and_nothing_else():
    """A family image runs celery_ml: the ML tasks (fit, answer a forecast,
    write one as a dataset), without the RAG or OCR planes."""

    import json
    import subprocess
    import sys

    probe = (
        "import json, sys\n"
        "from app.workers.celery_ml import celery_ml\n"
        "celery_ml.loader.import_default_modules()\n"
        "tasks = sorted(name for name in celery_ml.tasks if name.startswith('agentium.'))\n"
        "heavy = sorted(m for m in sys.modules if m.startswith(('app.services.rag', 'app.services.worker_ingest', 'torch', 'transformers')))\n"
        "print('PROBE ' + json.dumps({'tasks': tasks, 'heavy': heavy}))\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=BACKEND, capture_output=True, text=True, timeout=300)
    lines = [line for line in result.stdout.splitlines() if line.startswith("PROBE ")]
    assert result.returncode == 0 and lines, result.stderr[-2000:]
    report = json.loads(lines[-1].removeprefix("PROBE "))
    assert report["tasks"] == ["agentium.ml_forecast", "agentium.ml_forecast_batch", "agentium.ml_train"]
    assert report["heavy"] == []


def test_the_row_constants_name_every_family_and_task_the_plane_declares():
    from app.models.tabular import MODEL_FAMILIES, MODEL_TASKS

    assert set(MODEL_FAMILIES) == set(ml_families.FAMILY_BY_KEY)
    assert set(MODEL_TASKS) == set(ml_families.all_tasks())
