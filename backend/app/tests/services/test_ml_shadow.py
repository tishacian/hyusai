"""Shadow scoring cannot change service or escape its durable work budget."""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.db.base import SessionLocal
from app.models.tabular import MLModel, MLPrediction
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services import ml_shadow as shadow, tabular_predict
from app.services.tabular_datasets import TabularError


@pytest.fixture
def pair(db_session):
    workspace = Workspace(id=str(uuid4()), slug="shadow-" + uuid4().hex, name="Shadow", settings={})
    db_session.add(workspace)
    models = []
    for version in (1, 2):
        model = MLModel(id=str(uuid4()), workspace_id=workspace.id, slug="classifier", name="Classifier",
            version=version, task="classification", target="label", family="tabular", algo="gradient_boosting",
            status="ready", is_champion=version == 1, model_uri="artifact/" + str(version),
            classes_json=["a", "b"], signature_json={"inputs": [{"name": "x", "type": "double"}]},
            metrics_json={"primary": {"key": "roc_auc", "value": .8}, "target": {"positive": "b"}},
            params_json={}, trained_at=datetime(2026, 1, version))
        db_session.add(model)
        models.append(model)
    db_session.commit()
    shadow.configure(db_session, model=models[0], config=shadow.ShadowConfig(enabled=True, sample_percent=100))
    return workspace, *models


def enqueue(db, pair, *, rows=None, answers=None):
    _, primary, _ = pair
    prediction_id = tabular_predict.journal_call(db, requested=primary, served=primary, caller="session",
        rows=rows or [{"x": 1}], answers=answers or [{"prediction": "a"}], duration_ms=2)
    job = db.query(WorkspaceJob).filter_by(kind=shadow.KIND, workspace_id=pair[0].id).order_by(WorkspaceJob.created_at.desc()).first()
    return db.get(MLPrediction, prediction_id), job


def fake_score(model, rows, **kwargs):
    return {"predictions": [{"prediction": "b"} for _ in rows], "duration_ms": 3.0, "load_ms": 5.0}


def test_shadow_is_off_without_explicit_configuration(db_session, pair):
    _, primary, _ = pair
    primary.params_json = {}
    db_session.commit()
    row, job = enqueue(db_session, pair)
    assert job is None and "shadow" not in row.scores_json
    block = shadow.summary(db_session, model=primary)
    assert block["config"] == {"enabled": False, "sample_percent": 10, "timeout_s": 15}
    assert block["comparison"]["agreement"] is None


def test_staging_failure_rolls_back_only_shadow_savepoint(db_session, pair, monkeypatch):
    def fail(db, **kwargs):
        db.add(WorkspaceJob(workspace_id=pair[0].id, kind=shadow.KIND, title="Bad", status="invalid"))
        db.flush()
    monkeypatch.setattr(shadow, "stage", fail)
    row, job = enqueue(db_session, pair)
    assert row.id and job is None
    assert db_session.query(MLPrediction).filter_by(workspace_id=pair[0].id).count() == 1


def test_dispatch_failure_is_recoverable_and_duplicate_delivery_is_idempotent(db_session, pair, monkeypatch):
    row, job = enqueue(db_session, pair)
    job.updated_at = datetime.utcnow() - timedelta(minutes=2)
    db_session.commit()
    monkeypatch.setattr(shadow, "_dispatch", lambda _: (_ for _ in ()).throw(ConnectionError("broker down")))
    assert shadow.recover() == {"dispatched": 0, "deferred": 1}
    seen = []
    monkeypatch.setattr(shadow, "_dispatch", seen.append)
    assert shadow.recover()["dispatched"] == 1
    assert seen == [job.id]
    calls = []
    def score(*args, **kwargs):
        calls.append(args[0].id)
        return fake_score(*args, **kwargs)
    monkeypatch.setattr(shadow, "_score_isolated", score)
    assert shadow.run_shadow(job.id)["status"] == "completed"
    assert shadow.run_shadow(job.id)["status"] == "not_claimed"
    assert calls == [pair[2].id]
    db_session.expire_all()
    assert db_session.query(MLPrediction).filter_by(workspace_id=pair[0].id).count() == 1
    assert pair[1].predict_count == pair[2].predict_count == 0


def test_shadow_keeps_its_pinned_versions_after_promotion(db_session, pair, monkeypatch):
    _, incumbent, challenger = pair
    row, job = enqueue(db_session, pair)
    incumbent.is_champion, challenger.is_champion = False, True
    db_session.commit()
    calls = []
    def score(model, *args, **kwargs):
        calls.append(model.id)
        return fake_score(model, *args, **kwargs)
    monkeypatch.setattr(shadow, "_score_isolated", score)
    assert shadow.run_shadow(job.id)["status"] == "completed"
    assert calls == [challenger.id]
    db_session.expire_all()
    assert row.served_id == incumbent.id and row.output_json == [{"prediction": "a"}]
    assert job.input_ref["served_id"] == incumbent.id and job.input_ref["challenger_id"] == challenger.id


@pytest.mark.parametrize("change,code", [("artifact", "ML_SHADOW_MODEL_CHANGED"), ("disable", "ML_SHADOW_DISABLED"),
                                        ("workspace", "ML_SHADOW_SOURCE_UNAVAILABLE")])
def test_stale_or_disabled_work_never_scores(db_session, pair, monkeypatch, change, code):
    row, job = enqueue(db_session, pair)
    if change == "artifact":
        pair[2].model_uri = "changed"
    elif change == "disable":
        pair[1].params_json = {}
    else:
        pair[0].is_active = False
    db_session.commit()
    monkeypatch.setattr(shadow, "_score_isolated", lambda *a, **k: pytest.fail("must not score"))
    result = shadow.run_shadow(job.id)
    assert result["error"] == code and result["status"] == "cancelled"


def test_expired_lease_retries_only_up_to_the_durable_attempt_limit(db_session, pair, monkeypatch):
    row, job = enqueue(db_session, pair)
    with SessionLocal() as other:
        first, token = shadow._claim(other, job.id, datetime.utcnow())
        assert first.result["attempts"] == 1
    assert shadow.run_shadow(job.id)["status"] == "not_claimed"
    db_session.refresh(job)
    job.updated_at = datetime.utcnow() - timedelta(seconds=shadow.LEASE_SECONDS + 1)
    db_session.commit()
    with SessionLocal() as other:
        second, _ = shadow._claim(other, job.id, datetime.utcnow())
        assert second.result["attempts"] == 2 and second.result["lease_token"] != token
    db_session.refresh(job)
    job.updated_at = datetime.utcnow() - timedelta(seconds=shadow.LEASE_SECONDS + 1)
    db_session.commit()
    monkeypatch.setattr(shadow, "_dispatch", lambda _: pytest.fail("retry limit must not publish"))
    shadow.recover()
    db_session.refresh(job)
    assert job.status == "failed" and job.error == "ML_SHADOW_RETRY_LIMIT"


def test_backlog_and_payload_limits_keep_primary_journals(db_session, pair, monkeypatch):
    monkeypatch.setattr(shadow, "MAX_PENDING", 1)
    first, _ = enqueue(db_session, pair)
    second, _ = enqueue(db_session, pair)
    assert second.scores_json["shadow"]["error"] == "ML_SHADOW_BACKLOG_FULL"
    assert db_session.query(WorkspaceJob).filter_by(workspace_id=pair[0].id).count() == 1
    assert db_session.query(MLPrediction).filter_by(workspace_id=pair[0].id).count() == 2
    oversized, _ = enqueue(db_session, pair, rows=[{"x": "s" * shadow.MAX_PAYLOAD_BYTES}])
    assert oversized.scores_json["shadow"]["error"] == "ML_SHADOW_PAYLOAD_TOO_LARGE"


def test_sample_is_stable_and_rows_are_capped(db_session, pair):
    row, job = enqueue(db_session, pair, rows=[{"x": i} for i in range(90)], answers=[{"prediction": "a"}] * 90)
    assert len(row.payload_json) == job.input_ref["rows"] == shadow.MAX_ROWS
    pair[1].params_json = {"mlops": {"shadow": {"enabled": True, "sample_percent": 1}}}
    db_session.commit()
    skipped = 0
    for _ in range(20):
        row, _ = enqueue(db_session, pair)
        skipped += "shadow" not in row.scores_json
    assert skipped > 0


def test_different_columns_or_classes_are_explicitly_skipped(db_session, pair):
    pair[2].signature_json = {"inputs": [{"name": "new_required", "type": "double"}]}
    db_session.commit()
    row, job = enqueue(db_session, pair)
    assert job is None and row.scores_json["shadow"]["error"] == "ML_SHADOW_INCOMPATIBLE"


def test_feedback_quality_uses_only_the_first_row_and_current_pair(db_session, pair, monkeypatch):
    row, job = enqueue(db_session, pair, rows=[{"x": 1}, {"x": 2}], answers=[{"prediction": "a"}, {"prediction": "b"}])
    row.label = "b"
    db_session.commit()
    monkeypatch.setattr(shadow, "_score_isolated", fake_score)
    shadow.run_shadow(job.id)
    db_session.expire_all()
    block = shadow.summary(db_session, model=pair[1])
    assert block["window"]["compared_rows"] == 2 and block["window"]["labeled_pairs"] == 1
    assert block["comparison"]["agreement"] == .5
    assert block["comparison"]["champion_accuracy"] == 0
    assert block["comparison"]["challenger_accuracy"] == 1
    assert block["latencies"]["primary_ms"] == 2 and block["latencies"]["shadow_ms"] == 3
    assert block["latencies"]["shadow_load_ms"] == 5
    pair[2].metrics_json = {"primary": {"key": "roc_auc", "value": None}}
    db_session.commit()
    assert shadow.summary(db_session, model=pair[1])["comparison"]["agreement"] is None


def test_regression_quality_is_measured_mae_not_latency_as_cost(db_session, pair, monkeypatch):
    for model in pair[1:]:
        model.task, model.classes_json = "regression", []
        model.metrics_json = {"primary": {"key": "rmse", "value": 2}}
    db_session.commit()
    row, job = enqueue(db_session, pair, rows=[{"x": 1}, {"x": 2}], answers=[{"prediction": 4.0}, {"prediction": 10.0}])
    row.label = "7"
    db_session.commit()
    monkeypatch.setattr(shadow, "_score_isolated", lambda *a, **k: {"predictions": [{"prediction": 6.0}, {"prediction": 15.0}], "duration_ms": 1})
    shadow.run_shadow(job.id)
    db_session.expire_all()
    block = shadow.summary(db_session, model=pair[1])
    assert block["comparison"]["mean_absolute_difference"] == 3.5
    assert block["comparison"]["champion_mae"] == 3
    assert block["comparison"]["challenger_mae"] == 1
    assert block["window"]["labeled_pairs"] == 1
    assert "cost" not in str(block)


def test_worker_failure_is_safe_and_does_not_modify_primary(db_session, pair, monkeypatch):
    row, job = enqueue(db_session, pair)
    def timeout(*args, **kwargs):
        raise TabularError(code="ML_SHADOW_TIMEOUT", message="timeout")
    monkeypatch.setattr(shadow, "_score_isolated", timeout)
    assert shadow.run_shadow(job.id)["error"] == "ML_SHADOW_TIMEOUT"
    db_session.expire_all()
    assert row.output_json == [{"prediction": "a"}]
    block = shadow.summary(db_session, model=pair[1])
    assert block["window"]["failed"] == 1 and block["comparison"]["agreement"] is None


def test_cross_workspace_reference_is_refused_even_if_job_points_to_it(db_session, pair, monkeypatch):
    row, job = enqueue(db_session, pair)
    other = Workspace(id=str(uuid4()), slug=uuid4().hex, name="Other")
    db_session.add(other)
    db_session.flush()
    pair[2].workspace_id = other.id
    db_session.commit()
    monkeypatch.setattr(shadow, "_score_isolated", lambda *a, **k: pytest.fail("cross-workspace model"))
    assert shadow.run_shadow(job.id)["error"] == "ML_SHADOW_SOURCE_UNAVAILABLE"

def test_live_worker_lease_excludes_a_concurrent_delivery(db_session, pair, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    row, job = enqueue(db_session, pair)
    entered, release = Event(), Event()
    calls = []
    def score(*args, **kwargs):
        calls.append(args[0].id)
        entered.set()
        assert release.wait(5)
        return fake_score(*args, **kwargs)
    monkeypatch.setattr(shadow, "_score_isolated", score)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(shadow.run_shadow, job.id)
        assert entered.wait(5)
        try:
            assert shadow.run_shadow(job.id)["status"] == "not_claimed"
        finally:
            release.set()
        assert first.result(timeout=5)["status"] == "completed"
    assert calls == [pair[2].id]


def test_reclaimed_worker_cannot_overwrite_new_owner_result(db_session, pair, monkeypatch):
    row, job = enqueue(db_session, pair)
    def score(*args, **kwargs):
        with SessionLocal() as other:
            claimed = other.get(WorkspaceJob, job.id)
            claimed.updated_at = datetime.utcnow() + timedelta(seconds=1)
            claimed.result = {"attempts": 2, "lease_token": "new-owner", "predictions": [{"prediction": "new"}]}
            other.commit()
        return fake_score(*args, **kwargs)
    monkeypatch.setattr(shadow, "_score_isolated", score)
    assert shadow.run_shadow(job.id)["status"] == "lease_lost"
    db_session.refresh(job)
    assert job.result["lease_token"] == "new-owner"
    assert job.result["predictions"] == [{"prediction": "new"}]
