"""The no-code training plane: catalog, refusals, worker lifecycle, harness.

Three postures, on purpose.

The **catalog and the refusals** are pure functions over a dataset's profile, so
they are asserted directly: every refusal here is one the training form renders
inline, which means each one has to name the field that caused it.

The **worker lifecycle** runs against a stubbed harness that writes the model
directory and the summary a real one would. That keeps the interesting
assertions — which row status, what gets promoted, whether an artifact is
published at all — deterministic and sklearn-free.

The **harness contract** does fit a real model, once, because the properties
that matter cannot be stubbed: that the evidence block has the shape the model
card reads, that the artifact loads back through ``mlflow.pyfunc``, and that a
row with a missing value still scores against the signature training wrote.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.tabular import MLModel, TabularDataset
from app.models.workspace import Workspace
from app.services import tabular_ml
from app.services.recipe_executions import SupervisedRun
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import (
    ALGO_BY_KEY,
    ALGOS,
    CLASSIFICATION,
    REGRESSION,
    TRAIN_STEPS,
    catalog_payload,
    estimator_params,
    get_model,
    harness_path,
    infer_task,
    run_training,
    set_champion,
    submit_training,
    validate_training,
)

pl = pytest.importorskip("polars")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="ml plane",
        slug=f"ml-plane-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    return tmp_path / "store"


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "ml_train_min_rows", 10)


def _frame(rows: int = 60):
    """A small churn-shaped frame: a text id, two categoricals, three numerics."""

    return pl.DataFrame(
        {
            "msisdn": [f"2126{index:07d}" for index in range(rows)],
            "plan": ["prepaid" if index % 3 else "postpaid" for index in range(rows)],
            "region": ["casablanca", "rabat", "tanger"] * (rows // 3),
            "tenure_months": [1 + (index * 7) % 90 for index in range(rows)],
            "arpu": [30.0 + (index % 17) * 4.5 for index in range(rows)],
            "support_tickets": [index % 4 for index in range(rows)],
            "churn": [1 if index % 4 == 0 else 0 for index in range(rows)],
        }
    )


@pytest.fixture()
def dataset(db_session, workspace, store) -> TabularDataset:
    from app.services.tabular_datasets import register_frame

    row = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Churn features",
        frame=_frame(),
        source="upload",
    )
    db_session.commit()
    return row


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_the_catalog_is_task_neutral_and_every_estimator_it_offers_instantiates():
    import importlib

    payload = catalog_payload()
    assert payload["tasks"] == [CLASSIFICATION, REGRESSION]
    # Task neutrality is the property that lets a form switch churn → ARPU
    # without resetting the algorithm the author picked.
    for entry in payload["algos"]:
        assert set(entry["tasks"]) == {CLASSIFICATION, REGRESSION}, entry["key"]

    for algo in ALGOS:
        for task, dotted in algo.estimators.items():
            module_name, _, class_name = dotted.rpartition(".")
            factory = getattr(importlib.import_module(module_name), class_name)
            # Every knob the catalog offers has to be an argument the estimator
            # actually takes, or the form would build an unfittable request.
            factory(**estimator_params(algo, task, algo.resolve({})))


def test_a_knob_out_of_bounds_is_clamped_and_the_auto_sentinel_becomes_none():
    forest = ALGO_BY_KEY["random_forest"]

    resolved = forest.resolve({"n_estimators": 100_000, "max_depth": 0})
    assert resolved["n_estimators"] == 600  # the declared ceiling
    # 0 is the "let the trees grow" sentinel, which sklearn spells None.
    assert resolved["max_depth"] is None
    assert forest.resolve({"n_estimators": "not a number"})["n_estimators"] == 200


def test_the_shared_alpha_knob_is_inverted_for_a_logistic_regression():
    linear = ALGO_BY_KEY["linear"]

    # One vocabulary in the form ("regularization"), two spellings in sklearn.
    strong = estimator_params(linear, CLASSIFICATION, linear.resolve({"alpha": 10.0}))
    weak = estimator_params(linear, CLASSIFICATION, linear.resolve({"alpha": 0.1}))
    assert strong["C"] < weak["C"]
    assert "alpha" not in strong

    ridge = estimator_params(linear, REGRESSION, linear.resolve({"alpha": 10.0}))
    assert ridge["alpha"] == 10.0 and "C" not in ridge


def test_an_unseeded_estimator_is_not_handed_a_random_state():
    knn = ALGO_BY_KEY["knn"]
    assert "random_state" not in estimator_params(
        knn, CLASSIFICATION, knn.resolve({})
    )


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


def test_the_task_is_inferred_from_the_target_so_the_form_opens_on_the_right_one(
    dataset,
):
    # A 0/1 integer column is a classification; a continuous one is not.
    assert infer_task(dataset, "churn") == CLASSIFICATION
    assert infer_task(dataset, "arpu") == REGRESSION
    assert infer_task(dataset, "plan") == CLASSIFICATION


def test_features_default_to_every_column_but_the_target(dataset, enabled):
    spec = validate_training(dataset, task=None, target="churn")

    assert spec.task == CLASSIFICATION
    assert "churn" not in spec.features
    assert spec.features == [
        "msisdn",
        "plan",
        "region",
        "tenure_months",
        "arpu",
        "support_tickets",
    ]
    assert spec.algo.key == ALGOS[0].key
    assert spec.name == "Churn features · churn"
    # An explicit selection that includes the target still drops it: a model
    # cannot be handed its own answer.
    narrowed = validate_training(
        dataset, task=None, target="churn", features=["arpu", "churn", "arpu"]
    )
    assert narrowed.features == ["arpu"]


def test_an_identifier_like_feature_warns_instead_of_being_refused(dataset, enabled):
    spec = validate_training(dataset, task=None, target="churn")

    # An MSISDN trains fine and generalizes not at all. Refusing it would be
    # wrong (it is a legitimate join key elsewhere); staying silent would be too.
    assert [warning["feature"] for warning in spec.warnings] == ["msisdn"]
    assert spec.warnings[0]["code"] == "ML_FEATURE_IDENTIFIER"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"target": ""}, "ML_TARGET_REQUIRED"),
        ({"target": "nope"}, "ML_TARGET_UNKNOWN"),
        ({"target": "churn", "task": "clustering"}, "ML_TASK_UNKNOWN"),
        ({"target": "plan", "task": REGRESSION}, "ML_TARGET_NOT_NUMERIC"),
        ({"target": "msisdn", "task": CLASSIFICATION}, "ML_TARGET_TOO_MANY_CLASSES"),
        ({"target": "churn", "features": ["ghost"]}, "ML_FEATURE_UNKNOWN"),
        ({"target": "churn", "algo": "deep_learning"}, "ML_ALGO_UNKNOWN"),
    ],
)
def test_every_shape_a_fit_could_only_discover_the_expensive_way_is_refused(
    dataset, enabled, kwargs, code
):
    with pytest.raises(TabularError) as exc:
        validate_training(dataset, task=kwargs.pop("task", None), **kwargs)
    assert exc.value.code == code
    # A refusal the form renders inline has to name what to fix.
    assert exc.value.message


def test_a_target_that_leaves_no_feature_is_refused(db_session, workspace, store, enabled):
    from app.services.tabular_datasets import register_frame

    lonely = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="One column",
        frame=pl.DataFrame({"churn": [0, 1] * 10}),
        source="upload",
    )
    db_session.commit()

    with pytest.raises(TabularError) as exc:
        validate_training(lonely, task=None, target="churn")
    assert exc.value.code == "ML_FEATURES_REQUIRED"


def test_a_dataset_below_the_row_floor_is_refused_with_both_numbers(
    db_session, workspace, store, enabled, monkeypatch
):
    from app.services.tabular_datasets import register_frame

    monkeypatch.setattr(settings, "ml_train_min_rows", 500)
    small = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Too small",
        frame=_frame(30),
        source="upload",
    )
    db_session.commit()

    with pytest.raises(TabularError) as exc:
        validate_training(small, task=None, target="churn")
    assert exc.value.code == "ML_ROWS_INSUFFICIENT"
    assert "30" in exc.value.message and "500" in exc.value.message


def test_a_test_split_outside_the_usable_band_is_clamped(dataset, enabled):
    assert validate_training(dataset, task=None, target="churn", test_size=0.9).test_size == 0.5
    assert validate_training(dataset, task=None, target="churn", test_size=0.0).test_size == 0.05
    # Fewer than two folds is not cross-validation; it is off.
    assert validate_training(dataset, task=None, target="churn", cross_validation=1).cross_validation == 0
    assert validate_training(dataset, task=None, target="churn", cross_validation=99).cross_validation == 10


def test_training_refuses_while_the_plane_is_disabled(dataset, monkeypatch):
    monkeypatch.setattr(settings, "ml_train_enabled", False)
    with pytest.raises(TabularError) as exc:
        validate_training(dataset, task=None, target="churn")
    assert exc.value.code == "ML_TRAIN_DISABLED"


def test_an_unready_dataset_cannot_be_trained_on(dataset, enabled, db_session):
    dataset.status = "ingesting"
    db_session.commit()
    with pytest.raises(TabularError) as exc:
        validate_training(dataset, task=None, target="churn")
    assert exc.value.code == "DATASET_NOT_READY"


# ---------------------------------------------------------------------------
# Worker lifecycle (stubbed harness)
# ---------------------------------------------------------------------------


def _summary(**overrides) -> dict:
    body = {
        "metrics": {
            "task": "classification",
            "primary": {"key": "roc_auc", "value": 0.91},
            "scores": [{"key": "roc_auc", "value": 0.91}],
            "confusion": {"labels": ["0", "1"], "matrix": [[30, 2], [3, 10]]},
            "curves": {"roc": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]},
            "rows": {"total": 60, "train": 45, "test": 15},
            "columns": {"used": ["arpu"], "dropped": []},
            "importances": [{"feature": "arpu", "value": 0.2}],
            "target": {"name": "churn", "classes": ["0", "1"], "positive": "1"},
        },
        "signature": {
            "inputs": [{"name": "arpu", "type": "double", "kind": "number"}],
            "output": {"task": "classification", "target": "churn"},
        },
        "classes": ["0", "1"],
        "input_example": [{"arpu": 42.0}],
        "duration_ms": 1234.5,
    }
    body.update(overrides)
    return body


def _stub_harness(
    monkeypatch,
    *,
    exit_code=0,
    summary=None,
    status=None,
    files=None,
    progress=(),
    observe=None,
):
    """Stand in for the training subprocess: write what a real harness would.

    ``progress`` names the steps the stubbed child claims. Each is appended to
    the manifest's progress file and followed by the supervisor's own poll tick,
    which is how the worker republishes a step onto the polled row. ``observe``
    is read after each tick, so a caller can assert what the row said *while* the
    run was in flight rather than only once it settled.
    """

    captured: dict = {}

    def fake(argv, **kwargs):
        captured["argv"] = list(argv)
        captured.update(kwargs)
        manifest = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        captured["manifest"] = manifest
        observed: list[str | None] = []
        for step in progress:
            with open(manifest["progress_path"], "a", encoding="utf-8") as handle:
                handle.write(f"{step}\n")
            if kwargs.get("on_poll") is not None:
                kwargs["on_poll"]()
            if observe is not None:
                observed.append(observe())
        captured["observed"] = observed
        result_path = Path(argv[3])
        if exit_code == 0 and status is None:
            model_dir = Path(manifest["model_dir"])
            model_dir.mkdir(parents=True, exist_ok=True)
            for name, content in (files or {"MLmodel": "flavors: {}\n"}).items():
                target = model_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            result_path.write_text(
                json.dumps(summary if summary is not None else _summary()),
                encoding="utf-8",
            )
        return SupervisedRun(
            status=status,
            error=None,
            exit_code=exit_code,
            stdout_tail="fitting",
            stderr_tail="" if exit_code == 0 else "ml_fit_failed: ValueError: nope",
        )

    monkeypatch.setattr(tabular_ml, "supervise_harness", fake)
    return captured


def test_a_training_run_publishes_the_artifact_and_folds_the_evidence_into_the_row(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    _stub_harness(
        monkeypatch,
        files={
            "MLmodel": "flavors:\n  sklearn: {}\n",
            "model.skops": "x" * 2048,
            "requirements.txt": "scikit-learn\n",
        },
    )

    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
        algo="gradient_boosting",
        cross_validation=3,
    )

    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "ready", row.error
    assert row.task == CLASSIFICATION and row.algo == "gradient_boosting"
    assert row.version == 1 and row.slug == "churn-features-churn"
    # The row is the read model of the card: one SELECT renders it.
    assert row.metrics_json["primary"] == {"key": "roc_auc", "value": 0.91}
    assert row.signature_json["inputs"][0]["name"] == "arpu"
    assert row.classes_json == ["0", "1"]
    assert row.input_example_json == [{"arpu": 42.0}]
    assert row.row_count == 60
    assert row.trained_at is not None and row.train_duration_ms > 0
    # The artifact is an MLflow directory in the store, addressable by prefix.
    assert row.artifact_bytes == len("flavors:\n  sklearn: {}\n") + 2048 + len(
        "scikit-learn\n"
    )
    from app.services.object_store import get_object_store

    keys = get_object_store().list_keys(row.model_uri)
    assert sorted(Path(key).name for key in keys) == [
        "MLmodel",
        "model.skops",
        "requirements.txt",
    ]
    # And the manifest the harness received carries the resolved estimator, not
    # a catalog key the harness would have to interpret.
    assert row.params_json["estimator"].endswith("HistGradientBoostingClassifier")


def test_the_first_trained_version_serves_and_a_retrain_does_not_take_over(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    _stub_harness(monkeypatch)

    first = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )
    second = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )

    db_session.expire_all()
    assert db_session.query(MLModel).filter_by(id=first.id).one().is_champion is True
    # Deciding what serves is the operator's call, not the trainer's: v2 does
    # not silently start answering because it is newer.
    retrained = db_session.query(MLModel).filter_by(id=second.id).one()
    assert retrained.version == 2 and retrained.is_champion is False
    assert retrained.slug == first.slug


def test_promoting_a_version_demotes_the_one_that_was_serving(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    _stub_harness(monkeypatch)
    first = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )
    second = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )

    set_champion(db_session, get_model(db_session, model_id=second.id, workspace_id=workspace.id))

    db_session.expire_all()
    assert db_session.query(MLModel).filter_by(id=first.id).one().is_champion is False
    assert db_session.query(MLModel).filter_by(id=second.id).one().is_champion is True
    assert (
        tabular_ml.champion_for(db_session, workspace_id=workspace.id, slug=second.slug).id
        == second.id
    )


def test_an_untrained_version_cannot_be_promoted(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    _stub_harness(monkeypatch, exit_code=1)
    failed = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )
    with pytest.raises(TabularError) as exc:
        set_champion(db_session, failed)
    assert exc.value.code == "ML_MODEL_NOT_READY"


@pytest.mark.parametrize(
    ("exit_code", "code"),
    [
        (1, "ML_FIT_FAILED"),
        (2, "ML_TARGET_UNUSABLE"),
        (3, "ML_ROWS_INSUFFICIENT"),
        (4, "ML_ARTIFACT_UNWRITABLE"),
        (5, "ML_HARNESS_ERROR"),
    ],
)
def test_a_harness_exit_code_becomes_the_coded_error_with_its_own_last_line(
    db_session, workspace, dataset, enabled, monkeypatch, store, exit_code, code
):
    _stub_harness(monkeypatch, exit_code=exit_code)

    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )

    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "failed"
    assert row.error.startswith(code)
    assert "ValueError: nope" in row.error
    assert row.model_uri is None and row.is_champion is False


def test_a_timeout_says_so_rather_than_naming_an_exit_code(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    _stub_harness(monkeypatch, status="timed_out", exit_code=None)

    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )

    db_session.expire_all()
    assert db_session.query(MLModel).filter_by(id=model.id).one().error.startswith(
        "ML_TIMEOUT"
    )


def test_a_cancelled_run_settles_cancelled_and_publishes_nothing(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    _stub_harness(monkeypatch, status="cancelled", exit_code=None)

    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )

    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "cancelled" and row.error == "cancel_requested"
    assert row.model_uri is None


def test_a_cancel_asked_before_the_worker_claims_it_never_fits(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    calls: list = []
    monkeypatch.setattr(
        tabular_ml,
        "supervise_harness",
        lambda *args, **kwargs: calls.append(args) or SupervisedRun(None, None, 0, "", ""),
    )
    from app.services.tabular_ml import create_model, request_cancel

    spec = validate_training(dataset, task=None, target="churn")
    model = create_model(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    request_cancel(db_session, model)

    assert run_training(model.id)["status"] == "cancelled"
    assert not calls


def test_a_redelivered_task_that_finds_the_row_training_fails_closed(
    db_session, workspace, dataset, enabled, store
):
    from app.services.tabular_ml import create_model

    spec = validate_training(dataset, task=None, target="churn")
    model = create_model(db_session, workspace_id=workspace.id, spec=spec)
    model.status = "training"
    db_session.commit()

    # A replay could publish a second artifact for one version, so it must not.
    assert run_training(model.id)["status"] == "failed"
    db_session.expire_all()
    assert (
        db_session.query(MLModel).filter_by(id=model.id).one().error
        == "ml_worker_lost_after_claim"
    )


def test_a_run_whose_dataset_disappeared_fails_instead_of_crashing(
    db_session, workspace, dataset, enabled, store
):
    from app.services.tabular_ml import create_model

    spec = validate_training(dataset, task=None, target="churn")
    model = create_model(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    dataset.status = "deleted"
    db_session.commit()

    assert run_training(model.id)["status"] == "failed"
    db_session.expire_all()
    assert db_session.query(MLModel).filter_by(id=model.id).one().error.startswith(
        "ML_DATASET_UNAVAILABLE"
    )


def test_the_fit_runs_on_the_application_interpreter_under_its_own_budgets(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    monkeypatch.setattr(settings, "ml_train_memory_limit_mb", 5000)
    monkeypatch.setattr(settings, "ml_train_cpu_limit_s", 1234)
    monkeypatch.setattr(settings, "ml_train_artifact_limit_mb", 256)
    monkeypatch.setattr(settings, "ml_train_threads", 3)
    captured = _stub_harness(monkeypatch)

    submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )

    # Not a managed venv: the serving path deserializes what training
    # serialized, so both sides must be the same install.
    assert captured["argv"][0] == sys.executable
    assert captured["argv"][1] == str(harness_path())
    assert captured["memory_limit_mb"] == 5000
    assert captured["cpu_limit_s"] == 1234
    # A fitted forest is megabytes: the default 64 MB file ceiling would refuse
    # the artifact the harness itself writes.
    assert captured["fsize_limit_mb"] == 256
    # A BLAS pool per process is how a fit dies before it starts under RLIMIT_AS.
    assert captured["extra_env"]["OMP_NUM_THREADS"] == "3"
    assert captured["extra_env"]["OPENBLAS_NUM_THREADS"] == "3"


def test_the_manifest_carries_the_resolved_spec_and_not_the_catalog_vocabulary(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    captured = _stub_harness(monkeypatch)

    submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="arpu",
        task=REGRESSION,
        algo="linear",
        features=["plan", "tenure_months", "churn"],
        test_size=0.3,
    )

    manifest = captured["manifest"]
    assert manifest["task"] == REGRESSION
    assert manifest["target"] == "arpu"
    assert manifest["features"] == ["plan", "tenure_months", "churn"]
    assert manifest["estimator"] == "sklearn.linear_model.Ridge"
    assert manifest["params"]["alpha"] == 1.0
    # A linear model reads magnitudes as importance, so it asks for scaling; a
    # tree would not.
    assert manifest["scale"] is True
    assert manifest["test_size"] == 0.3


# ---------------------------------------------------------------------------
# Progress: what the row says while a fit runs
# ---------------------------------------------------------------------------


def test_a_run_publishes_step_codes_and_never_a_sentence(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    """The row is polled by a French page and an English one, so what it carries
    while it works has to be a code both can name — never a worker's sentence."""

    from app.services.tabular_ml import create_model

    def observe() -> str | None:
        db_session.expire_all()
        return db_session.query(MLModel).filter_by(id=model.id).one().status_detail

    captured = _stub_harness(
        monkeypatch,
        progress=("reading", "fitting", "scoring"),
        observe=observe,
    )
    spec = validate_training(dataset, task=None, target="churn")
    model = create_model(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    # Queued, before the worker has claimed anything: a step, not a spinner.
    assert model.status_detail == "queued"
    assert model.status_detail in TRAIN_STEPS

    run_training(model.id)

    # The harness owns the steps inside the fit, and the worker republished each
    # one as the child claimed it.
    assert captured["observed"] == ["reading", "fitting", "scoring"]
    assert captured["manifest"]["progress_path"].endswith("progress.txt")
    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "ready", row.error
    # A settled run has no step left to be on.
    assert row.status_detail is None


def test_a_step_the_worker_cannot_name_is_not_published(tmp_path):
    """A progress file is written by a subprocess, so it can be caught truncated
    or carry a line from a harness this deployment does not know. Either becomes
    no step rather than a status no surface can translate."""

    from app.services.tabular_ml import read_progress

    assert read_progress(tmp_path) is None, "no file yet is no step"
    progress = tmp_path / "progress.txt"
    progress.write_text("reading\nfitting\nsomething-else\n", encoding="utf-8")
    assert read_progress(tmp_path) == "fitting", "the last step it can name"
    progress.write_text("wat\n", encoding="utf-8")
    assert read_progress(tmp_path) is None


def test_republishing_the_same_step_does_not_write(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    """The worker reads the progress file once a second for the length of a fit.
    Committing the unchanged step each time would be a write per second for
    nothing, so `mark_step` is a no-op when the step has not moved."""

    from app.services.tabular_ml import create_model

    spec = validate_training(dataset, task=None, target="churn")
    model = create_model(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    tabular_ml.mark_step(db_session, model, "fitting")
    stamped = model.updated_at
    tabular_ml.mark_step(db_session, model, "fitting")
    assert model.updated_at == stamped
    tabular_ml.mark_step(db_session, model, "scoring")
    assert model.updated_at != stamped


def test_deleting_a_version_takes_its_bytes_with_it(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    from app.services.object_store import get_object_store
    from app.services.tabular_ml import delete_model, model_prefix

    _stub_harness(monkeypatch)
    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
    )
    prefix = model_prefix(workspace.id, model.id)
    assert get_object_store().list_keys(prefix)

    delete_model(db_session, model)

    assert db_session.query(MLModel).filter_by(id=model.id).first() is None
    assert not get_object_store().list_keys(prefix)


# ---------------------------------------------------------------------------
# Harness contract (a real fit, once)
# ---------------------------------------------------------------------------


def _run_harness(tmp_path: Path, manifest: dict) -> tuple[int, dict, str]:
    import subprocess

    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / "manifest.json"
    result_path = tmp_path / "result.json"
    manifest.setdefault("progress_path", str(tmp_path / "progress.txt"))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    completed = subprocess.run(  # noqa: S603 - our interpreter, our harness
        [sys.executable, str(harness_path()), str(manifest_path), str(result_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=900,
    )
    summary = (
        json.loads(result_path.read_text(encoding="utf-8"))
        if result_path.exists()
        else {}
    )
    return completed.returncode, summary, completed.stderr


@pytest.fixture()
def churn_parquet(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("skrub")
    pytest.importorskip("mlflow.sklearn")
    numpy = pytest.importorskip("numpy")

    rng = numpy.random.default_rng(3)
    rows = 400
    frame = pd.DataFrame(
        {
            "plan": rng.choice(["prepaid", "postpaid", "hybrid"], rows),
            "region": rng.choice(["casablanca", "rabat", "tanger"], rows),
            "tenure_months": rng.integers(1, 96, rows),
            "arpu": rng.normal(85, 25, rows).round(2),
            "support_tickets": rng.poisson(0.9, rows),
            "constant": 1,
        }
    )
    logit = (
        -1.0
        + 0.05 * (60 - frame["tenure_months"]).clip(lower=0)
        + 1.1 * frame["support_tickets"]
        - 0.03 * frame["arpu"]
    )
    frame["churn"] = (rng.random(rows) < 1 / (1 + numpy.exp(-logit))).astype(int)
    path = tmp_path / "churn.parquet"
    frame.to_parquet(path)
    return path


def _manifest_for(churn_parquet: Path, tmp_path: Path, **overrides) -> dict:
    manifest = {
        "data_path": str(churn_parquet),
        "model_dir": str(tmp_path / "model"),
        "task": "classification",
        "target": "churn",
        "features": [
            "plan",
            "region",
            "tenure_months",
            "arpu",
            "support_tickets",
            "constant",
        ],
        "estimator": "sklearn.ensemble.HistGradientBoostingClassifier",
        "params": {"max_iter": 40, "learning_rate": 0.2, "random_state": 42},
        "scale": False,
        "test_size": 0.25,
        "cv": 0,
        "random_state": 42,
        "min_rows": 40,
        "max_classes": 24,
        "curve_points": 40,
        "importance_rows": 120,
    }
    manifest.update(overrides)
    return manifest


@pytest.mark.slow
def test_the_harness_writes_the_evidence_the_model_card_reads(churn_parquet, tmp_path):
    code, summary, stderr = _run_harness(
        tmp_path / "run", _manifest_for(churn_parquet, tmp_path)
    )
    assert code == 0, stderr

    metrics = summary["metrics"]
    assert metrics["task"] == "classification"
    assert metrics["rows"]["train"] + metrics["rows"]["test"] == metrics["rows"]["total"]
    # Every run computes the same set, or a model card would only sometimes be
    # a model card.
    assert metrics["primary"]["key"] == "roc_auc"
    assert {score["key"] for score in metrics["scores"]} >= {
        "roc_auc",
        "accuracy",
        "balanced_accuracy",
        "precision",
        "recall",
        "f1",
    }
    assert metrics["confusion"]["labels"] == ["0", "1"]
    assert len(metrics["confusion"]["matrix"]) == 2
    assert 2 <= len(metrics["curves"]["roc"]) <= 40
    assert 0 < metrics["curves"]["baseline"] < 1
    assert metrics["target"]["positive"] == "1"
    assert sum(entry["count"] for entry in metrics["target"]["balance"]) == 400
    # A column with one value cannot separate anything; the card says so rather
    # than showing it with a zero importance.
    assert metrics["columns"]["dropped"] == [{"name": "constant", "reason": "constant"}]
    assert "constant" not in metrics["columns"]["used"]
    assert metrics["importances"][0]["feature"] in metrics["columns"]["used"]

    # The input contract is what a prediction form is built from: a categorical
    # carries its choices, a numeric its range.
    fields = {field["name"]: field for field in summary["signature"]["inputs"]}
    assert fields["plan"]["kind"] == "category"
    assert set(fields["plan"]["choices"]) == {"prepaid", "postpaid", "hybrid"}
    assert fields["arpu"]["kind"] == "number"
    assert fields["arpu"]["min"] < fields["arpu"]["default"] < fields["arpu"]["max"]
    # An integer column would refuse a hole at predict time, so it is a double.
    assert fields["tenure_months"]["type"] == "double"
    assert summary["classes"] == ["0", "1"]
    assert summary["input_example"]
    # JSON that Postgres will accept: no NaN, no Infinity anywhere.
    json.dumps(summary, allow_nan=False)

    # Only this process knows when the reading ends and the fitting begins, so
    # it claims each step for the worker to republish onto the polled row.
    claimed = (tmp_path / "run" / "progress.txt").read_text(encoding="utf-8").split()
    assert claimed == ["reading", "fitting", "scoring", "saving"]
    assert set(claimed) <= set(TRAIN_STEPS)


@pytest.mark.slow
def test_the_artifact_loads_back_and_scores_a_row_with_a_hole(churn_parquet, tmp_path):
    pytest.importorskip("mlflow.pyfunc")
    import pandas as pd

    code, summary, stderr = _run_harness(
        tmp_path / "run", _manifest_for(churn_parquet, tmp_path)
    )
    assert code == 0, stderr

    model_dir = tmp_path / "model"
    assert (model_dir / "MLmodel").exists()
    # skops, not pickle: loading is bounded by the allowlist the fit computed.
    assert "skops" in (model_dir / "MLmodel").read_text()
    assert summary["trusted_types"]
    assert all(
        entry.startswith(("sklearn.", "skrub.", "numpy.", "scipy.", "pandas.", "builtins.", "collections."))
        for entry in summary["trusted_types"]
    )

    import mlflow.pyfunc

    loaded = mlflow.pyfunc.load_model(str(model_dir))
    example = pd.DataFrame(summary["input_example"])
    assert len(loaded.predict(example)) == len(example)
    # The signature enforces the contract at predict time, and a production row
    # with a missing numeric must still score.
    holed = example.copy()
    holed.loc[holed.index[0], "arpu"] = None
    assert len(loaded.predict(holed)) == len(holed)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"target": "constant"}, 2),
        ({"min_rows": 100_000}, 3),
        ({"estimator": "os.system"}, 5),
        ({"features": ["constant"]}, 2),
    ],
)
def test_the_harness_exit_codes_name_the_author_mistake(
    churn_parquet, tmp_path, overrides, code
):
    exit_code, _summary, stderr = _run_harness(
        tmp_path / "run", _manifest_for(churn_parquet, tmp_path, **overrides)
    )
    assert exit_code == code, stderr


@pytest.mark.slow
def test_the_harness_regresses_a_continuous_target_with_a_scaled_pipeline(
    churn_parquet, tmp_path
):
    code, summary, stderr = _run_harness(
        tmp_path / "run",
        _manifest_for(
            churn_parquet,
            tmp_path,
            task="regression",
            target="arpu",
            features=["plan", "region", "tenure_months", "support_tickets", "churn"],
            estimator="sklearn.linear_model.Ridge",
            params={"alpha": 1.0, "random_state": 42},
            scale=True,
        ),
    )
    assert code == 0, stderr

    metrics = summary["metrics"]
    assert metrics["primary"]["key"] == "r2"
    assert {score["key"] for score in metrics["scores"]} >= {"r2", "mae", "rmse"}
    # The regression equivalent of a ROC: predicted against actual, plus the
    # line a perfect model would sit on.
    assert metrics["curves"]["fit"] and len(metrics["curves"]["ideal"]) == 2
    assert metrics["target"]["min"] < metrics["target"]["mean"] < metrics["target"]["max"]
    assert summary["classes"] == []


# ---------------------------------------------------------------------------
# Node wrapper + DAG contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_wrapper_refuses_a_payload_without_graph_configuration():
    from app.services.skills_registry.wrappers import _ml_train_sklearn_v1

    with pytest.raises(ValueError, match="train_config_missing"):
        await _ml_train_sklearn_v1({"dataset_id": "x"}, {"workspace_id": "w"})


@pytest.mark.asyncio
async def test_the_wrapper_requires_a_workspace_scope():
    from app.services.skills_registry.wrappers import _ml_train_sklearn_v1

    with pytest.raises(ValueError, match="train_workspace_required"):
        await _ml_train_sklearn_v1({"_train": {"target": "churn"}}, {})


@pytest.mark.asyncio
async def test_an_unwired_training_node_says_what_to_connect(workspace, enabled):
    from app.services.skills_registry.wrappers import _ml_train_sklearn_v1

    with pytest.raises(ValueError, match="ML_NO_DATASET"):
        await _ml_train_sklearn_v1(
            {"_train": {"target": "churn"}}, {"workspace_id": workspace.id}
        )


@pytest.mark.asyncio
async def test_the_wrapper_trains_and_returns_a_model_reference(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    from app.services.skills_registry.wrappers import _ml_train_sklearn_v1

    _stub_harness(monkeypatch)

    result = await _ml_train_sklearn_v1(
        {
            "input": {"dataset_id": dataset.id, "slug": dataset.slug},
            "_train": {
                "target": "churn",
                "algo": "gradient_boosting",
                "model_name": "Churn risk",
                "node_id": "train.1",
            },
        },
        {"workspace_id": workspace.id, "run_id": "run-42"},
    )

    # By reference, never by value: a model is megabytes, and the predict node
    # downstream resolves the id.
    assert result["slug"] == "churn-risk" and result["version"] == 1
    assert result["task"] == CLASSIFICATION
    assert result["metric"] == {"key": "roc_auc", "value": 0.91}
    assert result["is_champion"] is True
    assert "signature" not in result

    row = db_session.query(MLModel).filter_by(id=result["model_id"]).one()
    assert row.run_id == "run-42" and row.node_id == "train.1"


@pytest.mark.asyncio
async def test_a_failed_fit_fails_the_node_so_nothing_flows_downstream(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    from app.services.skills_registry.wrappers import _ml_train_sklearn_v1

    _stub_harness(monkeypatch, exit_code=1)

    with pytest.raises(RuntimeError, match="ml_train_failed"):
        await _ml_train_sklearn_v1(
            {
                "input": {"dataset_id": dataset.id},
                "_train": {"target": "churn"},
            },
            {"workspace_id": workspace.id},
        )


@pytest.mark.asyncio
async def test_a_pin_on_the_node_wins_over_the_dataset_on_the_wire(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    from app.services.skills_registry.wrappers import _ml_train_sklearn_v1
    from app.services.tabular_datasets import register_frame

    other = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Other features",
        frame=_frame(),
        source="upload",
    )
    db_session.commit()
    _stub_harness(monkeypatch)

    result = await _ml_train_sklearn_v1(
        {
            "input": {"dataset_id": dataset.id},
            "_train": {
                "target": "churn",
                "sources": [{"dataset_id": other.id}],
            },
        },
        {"workspace_id": workspace.id},
    )

    # A pin is the author saying "this one"; an upstream envelope is a default.
    row = db_session.query(MLModel).filter_by(id=result["model_id"]).one()
    assert row.dataset_id == other.id


@pytest.mark.asyncio
async def test_a_pin_by_lineage_is_honoured_the_way_the_builder_writes_it(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    """A slug pin follows the lineage, and `dataset_slug` is how it is spelled.

    The workshop writes `dataset_slug` so the node fits on whatever the latest
    ready version of that lineage is. A resolver that only read `slug` accepted
    the node, ignored the pin and trained on the wire instead — the shape of bug
    that produces a plausible model of the wrong table.
    """
    from app.services.skills_registry.wrappers import _ml_train_sklearn_v1
    from app.services.tabular_datasets import register_frame

    pinned = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Pinned features",
        frame=_frame(),
        source="upload",
    )
    db_session.commit()
    _stub_harness(monkeypatch)

    result = await _ml_train_sklearn_v1(
        {
            "input": {"dataset_id": dataset.id},
            "_train": {
                "target": "churn",
                "sources": [{"dataset_slug": pinned.slug}],
            },
        },
        {"workspace_id": workspace.id},
    )

    row = db_session.query(MLModel).filter_by(id=result["model_id"]).one()
    assert row.dataset_id == pinned.id


def test_the_dag_projects_the_training_spec_as_graph_configuration():
    from app.services.run_engine.dag import DagNode, _apply_train_node_config

    node = DagNode(
        id="train.1",
        type="task",
        kind="task",
        label="Train",
        config={
            "skill_slug": "ml_train_sklearn_v1",
            "params": {
                "task": "classification",
                "target": "churn",
                "features": ["arpu", "plan"],
                "algo": "gradient_boosting",
                "knobs": {"max_iter": 200},
                "test_size": 0.3,
                "cross_validation": 5,
                "model_name": "Churn risk",
            },
        },
        skill_slug="ml_train_sklearn_v1",
        data={},
    )
    node_input = {
        "dataset_id": "abc",
        # A hostile payload trying to retarget the model.
        "target": "salary",
        "features": ["everything"],
        "_train": {"target": "salary"},
    }

    _apply_train_node_config(node, node_input)

    train = node_input["_train"]
    assert train["target"] == "churn"
    assert train["features"] == ["arpu", "plan"]
    assert train["knobs"] == {"max_iter": 200}
    assert train["cross_validation"] == 5
    assert train["node_id"] == "train.1"
    assert "target" not in node_input and "features" not in node_input
    assert node_input["dataset_id"] == "abc"


def test_the_reserved_training_key_is_stripped_on_every_other_node():
    from app.services.run_engine.dag import (
        DagNode,
        _apply_train_node_config,
        _passthrough_without_recipe,
    )

    node = DagNode(
        id="answer",
        type="task",
        kind="task",
        label="Answer",
        config={"skill_slug": "llm_rag_answer_v1"},
        skill_slug="llm_rag_answer_v1",
        data={},
    )
    node_input = {"question": "why?", "_train": {"target": "salary"}}
    _apply_train_node_config(node, node_input)
    assert "_train" not in node_input

    # Nor does a training spec ride a failure envelope into run outputs.
    assert _passthrough_without_recipe(
        {"dataset_id": "d", "_train": {"target": "churn"}, "_transform": {}}
    ) == {"dataset_id": "d"}


def test_the_skill_is_registered_bound_and_claimed_by_a_universal_capability():
    from app.services.skills_registry import wrappers
    from app.services.skills_registry.seed import (
        SEED_CAPABILITIES,
        SEED_SKILLS,
        SKILL_CATEGORIES,
    )

    handler, module, binding = wrappers._REGISTRY["ml_train_sklearn_v1"]
    assert binding == "bound" and module == "app.services.tabular_ml"
    assert handler is wrappers._ml_train_sklearn_v1

    seed = next(row for row in SEED_SKILLS if row["slug"] == "ml_train_sklearn_v1")
    assert seed["execution"]["mode"] == "async"
    assert "`" not in seed["description"]  # rendered verbatim in the catalog

    claiming = [
        row
        for row in SEED_CAPABILITIES
        if "ml_train_sklearn_v1" in (row.get("skill_slugs") or [])
    ]
    assert [row["slug"] for row in claiming] == ["tabular_models"]
    assert claiming[0]["tier"] == "universal"
    # Its own section in the palette, not a corner of Analysis: a training run
    # produces a model, it does not characterise material in hand.
    assert SKILL_CATEGORIES["ml_train_sklearn_v1"] == "Models"
