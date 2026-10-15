"""A monitoring result and its alert share one transaction and one source id."""

import pytest

from app.core.config import settings
from app.models.ml_operations import MLAlert, MLAlertState
from app.models.workspace_job import WorkspaceJob
from app.services import ml_alerts, ml_retraining, tabular_monitoring
from app.tests.services.test_ml_retraining import case as monitor_case  # noqa: F401
from app.tests.services.test_ml_retraining import enabled, fire, store  # noqa: F401


@pytest.fixture(name="case")
def _case(request):
    return request.getfixturevalue("monitor_case")


def scheduled(db, case, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "ml_alerts_enabled", True)
    monkeypatch.setattr(tabular_monitoring, "report", lambda *args, **kwargs: {"badge": "watch"})
    run = fire(db, case, monkeypatch)
    run.flow_snapshot = ml_retraining._flow(case.model.id)
    db.commit()
    return run


def test_new_snapshot_emits_one_transition_and_replay_is_quiet(db_session, case, monkeypatch):
    run = scheduled(db_session, case, monkeypatch)
    calls = []
    actual = ml_alerts.monitor_transition

    def observe(db, **kwargs):
        calls.append(kwargs["source_id"])
        return actual(db, **kwargs)

    monkeypatch.setattr(ml_alerts, "monitor_transition", observe)
    first = ml_retraining.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    replay = ml_retraining.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    assert first["snapshot_id"] == replay["snapshot_id"]
    assert calls == [first["snapshot_id"]]
    alert = db_session.query(MLAlert).one()
    assert alert.state == "watch" and alert.event_type == "monitor_transition"
    state = db_session.get(MLAlertState, case.model.id)
    assert state.source_id == first["snapshot_id"]


def test_snapshot_and_transition_roll_back_together(db_session, case, monkeypatch):
    run = scheduled(db_session, case, monkeypatch)
    actual = ml_alerts.monitor_transition

    def fail_after_alert(db, **kwargs):
        actual(db, **kwargs)
        raise RuntimeError("abort snapshot transaction")

    monkeypatch.setattr(ml_alerts, "monitor_transition", fail_after_alert)
    with pytest.raises(RuntimeError, match="abort snapshot"):
        ml_retraining.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    db_session.rollback()
    assert db_session.query(WorkspaceJob).filter_by(kind=ml_retraining.SNAPSHOT_KIND).count() == 0
    assert db_session.query(MLAlert).count() == db_session.query(MLAlertState).count() == 0
