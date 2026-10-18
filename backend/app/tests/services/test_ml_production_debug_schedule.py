"""The scheduled monitoring cycle stages production debugging, never depends on it."""

import pytest

from app.core.config import settings
from app.models.ml_explanations import MLProductionExplanation
from app.models.workspace_job import WorkspaceJob
from app.services import ml_production_debug, ml_retraining, tabular_monitoring
from app.tests.services.test_ml_retraining import case as monitor_case  # noqa: F401
from app.tests.services.test_ml_retraining import enabled, fire, store  # noqa: F401


@pytest.fixture(name="case")
def _case(request):
    return request.getfixturevalue("monitor_case")


def _scheduled(db, case, monkeypatch):
    monkeypatch.setattr(tabular_monitoring, "report", lambda *args, **kwargs: {"badge": "ok"})
    run = fire(db, case, monkeypatch)
    run.flow_snapshot = ml_retraining._flow(case.model.id)
    db.commit()
    return run


def test_a_cycle_stages_one_analysis_and_dispatches_it_after_commit(db_session, case, monkeypatch):
    run = _scheduled(db_session, case, monkeypatch)
    dispatched = []

    def dispatch(db, report_id):
        # Committed before dispatch: a fresh read sees the staged row.
        assert db.query(MLProductionExplanation).filter_by(id=report_id).count() == 1
        dispatched.append(report_id)

    monkeypatch.setattr(ml_production_debug, "dispatch", dispatch)
    first = ml_retraining.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    snapshot = db_session.get(WorkspaceJob, first["snapshot_id"])
    staged = snapshot.result["production_debug"]
    assert dispatched == [staged["report_id"]]
    report = db_session.get(MLProductionExplanation, staged["report_id"])
    assert (report.trigger, report.status, report.model_id) == (
        "scheduled",
        "queued",
        case.model.id,
    )

    # A replayed cycle neither stages nor dispatches a second analysis.
    ml_retraining.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    assert dispatched == [staged["report_id"]]
    assert db_session.query(MLProductionExplanation).count() == 1


def test_a_staging_failure_leaves_the_monitoring_result_intact(db_session, case, monkeypatch):
    run = _scheduled(db_session, case, monkeypatch)

    def broken(db, **kwargs):
        db.add(MLProductionExplanation(id="half-written"))  # rolled back with its savepoint
        raise RuntimeError("stage failed")

    monkeypatch.setattr(ml_production_debug, "stage_scheduled", broken)
    result = ml_retraining.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    assert result["badge"] == "ok"
    snapshot = db_session.get(WorkspaceJob, result["snapshot_id"])
    assert snapshot.result["production_debug"] == {"skipped": "ML_PRODUCTION_DEBUG_STAGE_FAILED"}
    assert db_session.query(MLProductionExplanation).count() == 0


def test_the_interval_setting_throttles_cycles(db_session, case, monkeypatch):
    monkeypatch.setattr(settings, "ml_production_debug_interval_minutes", 60)
    run = _scheduled(db_session, case, monkeypatch)
    monkeypatch.setattr(ml_production_debug, "dispatch", lambda db, report_id: None)
    ml_retraining.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    staged = db_session.query(MLProductionExplanation).one()
    staged.status = "completed"
    db_session.commit()
    second = fire(db_session, case, monkeypatch)
    second.flow_snapshot = ml_retraining._flow(case.model.id)
    db_session.commit()
    result = ml_retraining.monitor_cycle(db_session, model_id=case.model.id, run_id=second.id)
    snapshot = db_session.get(WorkspaceJob, result["snapshot_id"])
    assert snapshot.result["production_debug"] == {"skipped": "no_new_labels"}
