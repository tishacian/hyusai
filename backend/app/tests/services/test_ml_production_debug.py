"""Model debugging in production (M5): what is measured, counted, alerted, kept.

A real churn model serves real calls through ``predict_rows``; labels are then
attached per sample as M2 feedback. The planted defects live in the *served
answers* (the journal) or in the labels, never in a re-prediction, because the
report must measure what production actually received.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.ml_explanations import MLProductionExplanation
from app.models.ml_feedback import MLPredictionFeedback
from app.models.ml_operations import MLAlert
from app.models.run import Run
from app.models.tabular import MLModel, MLPrediction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import ml_feedback, ml_production_debug, tabular_predict
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import delete_model, upload_model_dir
from app.tests.ml_artifacts import CHURN_FEATURES, churn_frame, fit_churn_artifact

pytest.importorskip("polars")
pytest.importorskip("skrub")
pytest.importorskip("mlflow.sklearn")

FEATURES = CHURN_FEATURES


@pytest.fixture(scope="module")
def churn_artifact(tmp_path_factory):
    return fit_churn_artifact(tmp_path_factory.mktemp("prod-debug"))


@pytest.fixture(scope="module")
def arpu_artifact(tmp_path_factory):
    return fit_churn_artifact(
        tmp_path_factory.mktemp("prod-debug-arpu"), task="regression", target="arpu"
    )


def _user(db_session, workspace, role_template):
    user = User(
        id=str(uuid4()),
        username="debug-" + uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    if role_template:
        db_session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role="member",
                role_template=role_template,
            )
        )
    db_session.commit()
    return user


@pytest.fixture()
def workspace(db_session):
    row = Workspace(id=uuid4().hex, name="Debug", slug=f"debug-{uuid4().hex[:8]}", settings={})
    db_session.add(row)
    db_session.commit()
    actor = _user(db_session, row, "workspace_contributor")
    db_session.add(Run(id=row.id, workspace_id=row.id, initiated_by_user_id=actor.id))
    db_session.commit()
    return SimpleNamespace(row=row, contributor=actor)


@pytest.fixture(autouse=True)
def serving(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 10_000)
    monkeypatch.setattr(settings, "ml_predict_rows_per_minute", 1_000_000)
    tabular_predict.reset_cache()
    yield
    tabular_predict.reset_cache()


def _register(
    db_session,
    workspace,
    artifact,
    *,
    task="classification",
    target="churn",
    slug=None,
    version=1,
    fairness=("plan",),
    family="tabular",
):
    directory, summary = artifact
    model = MLModel(
        id=uuid4().hex,
        workspace_id=workspace.row.id,
        name="Debugged",
        slug=slug or f"debugged-{uuid4().hex[:6]}",
        version=version,
        task=task,
        family=family,
        algo="gradient_boosting",
        target=target,
        features=[spec["name"] for spec in summary["signature"]["inputs"]],
        params_json={},
        spec_json={"fairness_columns": list(fairness)} if fairness else {},
        status="ready",
        row_count=240,
        metrics_json=summary["metrics"],
        signature_json=summary["signature"],
        input_example_json=summary["input_example"],
        classes_json=summary["classes"],
        is_champion=version == 1,
    )
    db_session.add(model)
    db_session.flush()
    uri, size = upload_model_dir(directory, workspace_id=workspace.row.id, model_id=model.id)
    model.model_uri, model.artifact_bytes = uri, size
    model.trained_at = datetime(2026, 9, 1, 9, 30)
    db_session.commit()
    return model


def _serve(db_session, model, records, *, store=True, version=None, at=None):
    """Serve real calls in chunks under the journal's per-call cap."""

    served = []
    for start in range(0, len(records), 60):
        chunk = records[start : start + 60]
        answer = tabular_predict.predict_rows(
            db_session, model, chunk, store=store, version=version
        )
        row = db_session.get(MLPrediction, answer["prediction_id"])
        if at is not None:
            row.created_at = at
        for index, (record, prediction) in enumerate(zip(chunk, answer["predictions"])):
            served.append((row, index, record, prediction["prediction"]))
    db_session.commit()
    return served


def _label(db_session, served, rule):
    now = datetime.utcnow()
    for row, index, record, prediction in served:
        db_session.add(
            MLPredictionFeedback(
                sample_id=ml_feedback.sample_id(row, index),
                prediction_id=row.id,
                workspace_id=row.workspace_id,
                sample_index=index,
                label=str(rule(record, prediction)),
                labeled_at=now,
            )
        )
    db_session.commit()


def _flip(value):
    return "0" if str(value) == "1" else "1"


def _records(rows=240):
    return churn_frame(rows)[FEATURES].to_dict(orient="records")


def _rewrite_served(db_session, served, predicate):
    """Plant a defect in what production was *served*, not in the model."""

    rows = {}
    for row, index, record, _ in served:
        if predicate(record):
            outputs = rows.setdefault(row.id, (row, [dict(item) for item in row.output_json]))[1]
            outputs[index]["prediction"] = _flip(outputs[index]["prediction"])
    for row, outputs in rows.values():
        row.output_json = outputs
    db_session.commit()


def _analyse(db_session, workspace, model, **window):
    report = ml_production_debug.request_manual(
        db_session,
        model=model,
        workspace=workspace.row,
        user=workspace.contributor,
        **window,
    )
    db_session.expire_all()
    return db_session.get(MLProductionExplanation, report.id)


def _hybrid(record):
    return record["plan"] == "hybrid"


# ---------------------------------------------------------------------------
# What is measured
# ---------------------------------------------------------------------------


def test_a_planted_error_zone_in_served_answers_appears_in_the_tree(
    db_session, workspace, churn_artifact
):
    model = _register(db_session, workspace, churn_artifact)
    served = _serve(db_session, model, _records())
    # Labels agree with what the model would answer today; the journal says
    # the hybrid customers were served the opposite. A re-prediction would see
    # no error at all, so finding the zone proves the served answer is measured.
    _label(db_session, served, lambda record, prediction: prediction)
    _rewrite_served(db_session, served, _hybrid)

    report = _analyse(db_session, workspace, model)

    assert report.status == "completed", report.error_code
    assert report.trigger == "manual" and report.version == 1
    assert (report.labeled_count, report.used_count) == (240, 240)
    assert report.excluded_json == {}
    hybrids = sum(1 for _, _, record, _ in served if _hybrid(record))
    assert report.metrics_json["accuracy"] == pytest.approx(1 - hybrids / 240, abs=1e-6)
    tree = report.report_json["error_tree"]
    assert report.report_json["error_measure"] == "served_answer_vs_label"
    worst = tree["rules"][0]
    assert worst["error"] == 1.0 and worst["rows"] == hybrids
    assert worst["rule"] == [{"feature": "plan_hybrid", "op": ">", "value": 0.5, "missing": False}]
    # Drawable with the training-time chart: nodes, measured rows and errors.
    assert tree["tree"]["nodes"][0]["rows"] == 240
    # Aggregated only: rules, node counts and group metrics, never a row.
    assert set(report.report_json) == {"error_measure", "rows", "error_tree", "fairness"}
    stored = json.dumps(report.report_json)
    assert "payload" not in stored and len(stored) <= settings.ml_production_debug_max_report_bytes
    arpus = {f"{record['arpu']:.2f}" for _, _, record, _ in served}
    assert not any(f'"{value}"' in stored for value in arpus)


def test_a_planted_group_bias_is_measured_and_alerted_once(
    db_session, workspace, churn_artifact, monkeypatch
):
    monkeypatch.setattr(settings, "ml_alerts_enabled", True)
    model = _register(db_session, workspace, churn_artifact)
    served = _serve(db_session, model, _records())
    _label(db_session, served, lambda record, prediction: prediction)
    _rewrite_served(db_session, served, _hybrid)

    first = _analyse(db_session, workspace, model)
    fairness = first.report_json["fairness"]
    gap = next(item for item in fairness["gaps"] if item["column"] == "plan")
    assert gap["metric"] == "equalized_odds_difference"
    assert gap["gap"] >= settings.ml_fairness_alert_gap
    assert first.fairness_badge == "alert" and fairness["badge"] == "alert"
    groups = {group["group"]: group for group in fairness["columns"][0]["groups"]}
    assert groups["hybrid"]["accuracy"] == 0.0 and groups["prepaid"]["accuracy"] == 1.0
    alerts = db_session.query(MLAlert).all()
    assert [(a.event_type, a.state, a.source_id) for a in alerts] == [
        ("fairness_gap", "alert", first.id)
    ]

    # Same badge again: no transition, no second alert.
    second = _analyse(db_session, workspace, model)
    assert second.fairness_badge == "alert"
    assert db_session.query(MLAlert).count() == 1

    # Back to fair: a transition to ok, alerted once more.
    db_session.query(MLPredictionFeedback).delete()
    db_session.commit()
    _rewrite_served(db_session, served, _hybrid)  # restore the served answers
    _label(db_session, served, lambda record, prediction: prediction)
    third = _analyse(db_session, workspace, model)
    assert third.fairness_badge == "ok"
    assert sorted(a.state for a in db_session.query(MLAlert).all()) == ["alert", "ok"]


def test_no_alert_is_raised_when_m3_alerts_are_off(
    db_session, workspace, churn_artifact, monkeypatch
):
    monkeypatch.setattr(settings, "ml_alerts_enabled", False)
    model = _register(db_session, workspace, churn_artifact)
    served = _serve(db_session, model, _records())
    _label(db_session, served, lambda record, prediction: prediction)
    _rewrite_served(db_session, served, _hybrid)
    report = _analyse(db_session, workspace, model)
    assert report.fairness_badge == "alert"
    assert db_session.query(MLAlert).count() == 0


def test_a_regression_report_measures_error_and_relative_mae_gap(
    db_session, workspace, arpu_artifact
):
    model = _register(db_session, workspace, arpu_artifact, task="regression", target="arpu")
    records = churn_frame()[[name for name in FEATURES if name != "arpu"]].to_dict(orient="records")
    served = _serve(db_session, model, records)
    _label(
        db_session,
        served,
        lambda record, prediction: prediction + (40.0 if _hybrid(record) else 1.0),
    )
    report = _analyse(db_session, workspace, model)
    assert report.status == "completed"
    assert report.metrics_json["mae"] > 1.0
    worst = report.report_json["error_tree"]["rules"][0]
    assert worst["rule"][0]["feature"] == "plan_hybrid" and worst["error"] == pytest.approx(40.0)
    gap = report.report_json["fairness"]["gaps"][0]
    assert gap["metric"] == "mae_gap_ratio" and report.fairness_badge == "alert"


# ---------------------------------------------------------------------------
# What is counted, and what is left out
# ---------------------------------------------------------------------------


def test_labels_without_retained_inputs_are_excluded_and_counted(
    db_session, workspace, churn_artifact
):
    model = _register(db_session, workspace, churn_artifact)
    retained = _serve(db_session, model, _records()[:180])
    _label(db_session, retained, lambda record, prediction: prediction)
    # store=false calls keep no payload. Their labels cannot be posted through
    # the API (ML_FEEDBACK_NOT_STORED); rows labelled before that rule, or a
    # legacy one-row label, still exist and must be excluded, not guessed.
    unretained = _serve(db_session, model, _records()[180:240], store=False)
    _label(db_session, unretained, lambda record, prediction: prediction)
    db_session.add(
        MLPrediction(
            id=str(uuid4()),
            workspace_id=model.workspace_id,
            model_id=model.id,
            served_id=model.id,
            served_version=1,
            slug=model.slug,
            caller="session",
            row_count=1,
            payload_json=[],
            input_storage_allowed=False,
            output_json=[{"prediction": "1"}],
            scores_json={},
            label="0",
            labeled_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    report = _analyse(db_session, workspace, model)
    assert report.labeled_count == 241
    assert report.used_count == 180
    assert report.excluded_json == {"inputs_not_retained": 61}


def test_too_few_labels_is_insufficient_data_with_counts(db_session, workspace, churn_artifact):
    model = _register(db_session, workspace, churn_artifact)
    served = _serve(db_session, model, _records()[:20])
    _label(db_session, served, lambda record, prediction: prediction)
    report = _analyse(db_session, workspace, model)
    assert report.status == "insufficient_data"
    assert (report.labeled_count, report.used_count) == (20, 20)
    assert report.report_json == {"minimum": settings.ml_production_debug_min_rows}
    assert report.fairness_badge is None


def test_only_samples_served_by_this_exact_version_count(db_session, workspace, churn_artifact):
    v1 = _register(db_session, workspace, churn_artifact, slug="lineage")
    v2 = _register(db_session, workspace, churn_artifact, slug="lineage", version=2)
    _label(db_session, _serve(db_session, v1, _records()[:60]), lambda r, p: p)
    _label(db_session, _serve(db_session, v1, _records()[60:120], version=2), lambda r, p: p)
    report = _analyse(db_session, workspace, v1)
    assert report.labeled_count == 60
    other = _analyse(db_session, workspace, v2)
    assert other.labeled_count == 60
    assert {report.model_id, other.model_id} == {v1.id, v2.id}


def test_the_ceiling_keeps_the_most_recent_samples_deterministically(
    db_session, workspace, churn_artifact, monkeypatch
):
    monkeypatch.setattr(settings, "ml_production_debug_max_rows", 100)
    model = _register(db_session, workspace, churn_artifact)
    old = _serve(db_session, model, _records()[:120], at=datetime.utcnow() - timedelta(days=3))
    _label(db_session, old, lambda record, prediction: _flip(prediction))
    recent = _serve(db_session, model, _records()[120:240])
    _label(db_session, recent, lambda record, prediction: prediction)

    first = _analyse(db_session, workspace, model)
    second = _analyse(db_session, workspace, model)
    assert first.used_count == 100
    assert first.excluded_json == {"beyond_max_rows": 140}
    # Only recent, correctly served samples were read.
    assert first.metrics_json["accuracy"] == 1.0
    assert first.report_json == second.report_json


def test_a_time_window_bounds_the_samples(db_session, workspace, churn_artifact):
    model = _register(db_session, workspace, churn_artifact)
    long_ago = datetime.utcnow() - timedelta(days=30)
    _label(db_session, _serve(db_session, model, _records()[:120], at=long_ago), lambda r, p: p)
    _label(db_session, _serve(db_session, model, _records()[120:]), lambda r, p: p)
    report = _analyse(db_session, workspace, model, since=datetime.utcnow() - timedelta(days=1))
    assert report.labeled_count == 120
    assert report.window_from is not None and report.window_until is None
    with pytest.raises(TabularError) as raised:
        _analyse(db_session, workspace, model, since=datetime.utcnow(), until=long_ago)
    assert raised.value.code == "ML_PRODUCTION_DEBUG_WINDOW_INVALID"


def test_fairness_is_absent_with_its_reason(db_session, workspace, churn_artifact):
    none = _register(db_session, workspace, churn_artifact, fairness=())
    _label(db_session, _serve(db_session, none, _records()[:60]), lambda r, p: p)
    report = _analyse(db_session, workspace, none)
    assert report.report_json["fairness"] == {"reason": "no_sensitive_columns"}
    assert report.fairness_badge is None

    elsewhere = _register(db_session, workspace, churn_artifact, fairness=("gender",))
    _label(db_session, _serve(db_session, elsewhere, _records()[:60]), lambda r, p: p)
    report = _analyse(db_session, workspace, elsewhere)
    assert report.report_json["fairness"]["columns"] == [
        {"column": "gender", "error": "not_in_inputs"}
    ]
    assert report.fairness_badge is None


def test_badges_follow_the_thresholds(monkeypatch):
    monkeypatch.setattr(settings, "ml_fairness_watch_gap", 0.05)
    monkeypatch.setattr(settings, "ml_fairness_alert_gap", 0.10)
    assert [ml_production_debug.badge_for(gap) for gap in (None, 0.0, 0.05, 0.09, 0.10)] == [
        None,
        "ok",
        "watch",
        "watch",
        "alert",
    ]
    monkeypatch.setattr(settings, "ml_fairness_min_group_rows", 30)
    gaps, badge = ml_production_debug.fairness_gaps(
        [
            {
                "column": "plan",
                "groups": [
                    {"group": "a", "n": 100, "accuracy": 0.9},
                    {"group": "b", "n": 100, "accuracy": 0.83},
                    {"group": "tiny", "n": 3, "accuracy": 0.0},
                ],
            }
        ],
        task="classification",
        binary=False,
        overall={},
    )
    # The three-row group is reported but cannot set the gap.
    assert gaps == [
        {
            "column": "plan",
            "groups": 3,
            "small_groups": 1,
            "metric": "accuracy_gap",
            "gap": 0.07,
            "badge": "watch",
        }
    ]
    assert badge == "watch"


# ---------------------------------------------------------------------------
# Scheduling, refusal, audit, lifecycle
# ---------------------------------------------------------------------------


def test_the_scheduled_trigger_is_throttled_idempotent_and_waits_for_labels(
    db_session, workspace, churn_artifact
):
    model = _register(db_session, workspace, churn_artifact)
    assert ml_production_debug.stage_scheduled(db_session, model=model) == {"skipped": "no_labels"}
    _label(db_session, _serve(db_session, model, _records()[:60]), lambda r, p: p)

    staged = ml_production_debug.stage_scheduled(db_session, model=model)
    db_session.commit()
    assert set(staged) == {"report_id"}
    assert ml_production_debug.stage_scheduled(db_session, model=model) == {
        "skipped": "in_progress"
    }
    ml_production_debug.dispatch(db_session, staged["report_id"])
    db_session.expire_all()
    first = db_session.get(MLProductionExplanation, staged["report_id"])
    assert first.status == "completed" and first.trigger == "scheduled"

    # Nothing new: nothing to analyse, even long after.
    later = datetime.utcnow() + timedelta(days=30)
    assert ml_production_debug.stage_scheduled(db_session, model=model, now=later) == {
        "skipped": "no_new_labels"
    }
    # New labels inside the interval: throttled.
    _label(db_session, _serve(db_session, model, _records()[60:120]), lambda r, p: p)
    assert ml_production_debug.stage_scheduled(db_session, model=model) == {"skipped": "throttled"}
    # Past the interval: a new analysis, under a new deterministic id.
    after = datetime.utcnow() + timedelta(minutes=settings.ml_production_debug_interval_minutes + 1)
    again = ml_production_debug.stage_scheduled(db_session, model=model, now=after)
    db_session.commit()
    assert again["report_id"] != staged["report_id"]
    # A replayed cycle with the same watermark stages nothing more.
    ml_production_debug.dispatch(db_session, again["report_id"])
    db_session.expire_all()
    assert ml_production_debug.stage_scheduled(
        db_session, model=model, now=after + timedelta(days=2)
    ) == {"skipped": "no_new_labels"}
    assert db_session.query(MLProductionExplanation).count() == 2


def test_a_refused_dispatch_is_recorded_and_retried_later(
    db_session, workspace, churn_artifact, monkeypatch
):
    from app.workers.celery_app import celery_app

    model = _register(db_session, workspace, churn_artifact)
    _label(db_session, _serve(db_session, model, _records()[:60]), lambda r, p: p)
    monkeypatch.setattr(settings, "worker_eager_mode", False)

    def refuse(*args, **kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(celery_app, "send_task", refuse)
    staged = ml_production_debug.stage_scheduled(db_session, model=model)
    db_session.commit()
    ml_production_debug.dispatch(db_session, staged["report_id"])
    db_session.expire_all()
    row = db_session.get(MLProductionExplanation, staged["report_id"])
    assert (row.status, row.error_code) == ("failed", "ML_PRODUCTION_DEBUG_DISPATCH_FAILED")

    sent = []
    monkeypatch.setattr(celery_app, "send_task", lambda name, args, **kw: sent.append((name, args)))
    after = datetime.utcnow() + timedelta(minutes=settings.ml_production_debug_interval_minutes + 1)
    retried = ml_production_debug.stage_scheduled(db_session, model=model, now=after)
    db_session.commit()
    assert retried == staged
    ml_production_debug.dispatch(db_session, retried["report_id"])
    assert sent == [("agentium.ml_production_debug", [staged["report_id"]])]
    assert db_session.get(MLProductionExplanation, staged["report_id"]).status == "queued"


def test_an_analysis_in_flight_refuses_a_second(db_session, workspace, churn_artifact):
    model = _register(db_session, workspace, churn_artifact)
    db_session.add(
        MLProductionExplanation(
            id=str(uuid4()),
            workspace_id=model.workspace_id,
            model_id=model.id,
            version=1,
            trigger="manual",
            status="running",
            excluded_json={},
            metrics_json={},
            report_json={},
            created_at=datetime.utcnow(),
            started_at=datetime.utcnow(),
        )
    )
    db_session.commit()
    with pytest.raises(TabularError) as raised:
        _analyse(db_session, workspace, model)
    assert raised.value.code == "ML_PRODUCTION_DEBUG_RUNNING"


def test_a_lost_analysis_expires_instead_of_blocking(db_session, workspace, churn_artifact):
    model = _register(db_session, workspace, churn_artifact)
    long_ago = datetime.utcnow() - timedelta(hours=3)
    db_session.add(
        MLProductionExplanation(
            id="lost",
            workspace_id=model.workspace_id,
            model_id=model.id,
            version=1,
            trigger="manual",
            status="running",
            excluded_json={},
            metrics_json={},
            report_json={},
            created_at=long_ago,
            started_at=long_ago,
        )
    )
    db_session.commit()
    report = _analyse(db_session, workspace, model)
    assert report.status == "insufficient_data"
    assert db_session.get(MLProductionExplanation, "lost").error_code == "ML_PRODUCTION_DEBUG_STALE"


def test_an_audit_failure_queues_nothing(db_session, workspace, churn_artifact, monkeypatch):
    from app.services import ml_permissions

    model = _register(db_session, workspace, churn_artifact)
    monkeypatch.setattr(ml_permissions, "emit_audit_event", lambda **kwargs: None)
    with pytest.raises(TabularError) as raised:
        _analyse(db_session, workspace, model)
    assert raised.value.code == "ML_AUDIT_UNAVAILABLE"
    db_session.rollback()
    assert db_session.query(MLProductionExplanation).count() == 0


def test_a_manual_analysis_is_audited(db_session, workspace, churn_artifact):
    model = _register(db_session, workspace, churn_artifact)
    report = _analyse(db_session, workspace, model)
    audit = db_session.query(AuditLog).filter_by(event_type="ml.model.production_debug").one()
    assert audit.details["after"]["report_id"] == report.id
    assert audit.actor == workspace.contributor.id


def test_unsupported_families_are_refused(db_session, workspace, churn_artifact):
    model = _register(db_session, workspace, churn_artifact, family="tabular_deep")
    with pytest.raises(TabularError) as raised:
        _analyse(db_session, workspace, model)
    assert raised.value.code == "ML_PRODUCTION_DEBUG_UNSUPPORTED"


def test_reports_are_deleted_with_their_model(db_session, workspace, churn_artifact):
    model = _register(db_session, workspace, churn_artifact)
    _analyse(db_session, workspace, model)
    assert db_session.query(MLProductionExplanation).count() == 1
    delete_model(db_session, model)
    assert db_session.query(MLProductionExplanation).count() == 0


def test_history_is_bounded(db_session, workspace, churn_artifact, monkeypatch):
    monkeypatch.setattr(settings, "ml_production_debug_history", 2)
    model = _register(db_session, workspace, churn_artifact)
    for _ in range(3):
        _analyse(db_session, workspace, model)
    assert db_session.query(MLProductionExplanation).count() == 2
    view = ml_production_debug.view(db_session, model)
    assert view["latest"]["status"] == "insufficient_data"
    assert view["limits"]["min_rows"] == settings.ml_production_debug_min_rows


# ---------------------------------------------------------------------------
# Rights, through HTTP
# ---------------------------------------------------------------------------


@pytest.fixture()
def api(db_session, monkeypatch):
    from app.api.v1.endpoints import ml_explanations

    monkeypatch.setattr(settings, "ml_rbac_enforced", True)
    app = FastAPI()
    app.include_router(ml_explanations.router, prefix="/ml-models")
    app.dependency_overrides[ml_explanations.get_db] = lambda: db_session

    def client(workspace, user):
        app.dependency_overrides[ml_explanations.get_current_workspace] = lambda: workspace
        app.dependency_overrides[ml_explanations.get_current_user] = lambda: user
        return TestClient(app)

    return client


def test_reading_needs_read_and_running_needs_a_write_role(
    db_session, workspace, churn_artifact, api
):
    model = _register(db_session, workspace, churn_artifact)
    viewer = _user(db_session, workspace.row, "workspace_viewer")

    read = api(workspace.row, viewer).get(f"/ml-models/{model.id}/production-debug")
    assert read.status_code == 200
    assert read.json()["latest"] is None and read.json()["supported"] is True

    refused = api(workspace.row, viewer).post(f"/ml-models/{model.id}/production-debug", json={})
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "ML_FORBIDDEN_ACTION"
    assert db_session.query(MLProductionExplanation).count() == 0

    ran = api(workspace.row, workspace.contributor).post(
        f"/ml-models/{model.id}/production-debug",
        json={"since": "2026-01-01T00:00:00Z"},
    )
    assert ran.status_code == 202, ran.text
    body = ran.json()
    assert body["report"]["trigger"] == "manual"
    assert body["report"]["window"]["from"] == "2026-01-01T00:00:00"
    assert body["latest"]["id"] == body["report"]["id"]

    outsider = _user(db_session, workspace.row, None)
    hidden = api(workspace.row, outsider).get(f"/ml-models/{model.id}/production-debug")
    assert hidden.status_code == 403
