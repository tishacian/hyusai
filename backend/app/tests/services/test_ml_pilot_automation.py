"""An experimental family cannot acquire a scheduled retraining path."""

from types import SimpleNamespace

import pytest

from app.models.run_schedule import RunSchedule
from app.models.tabular import MLModel
from app.models.workspace_job import WorkspaceJob
from app.services import ml_retraining
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_training import workspace  # noqa: F401


def test_pilot_policy_cannot_create_schedule_or_retraining_job(db_session, workspace, monkeypatch):
    model = MLModel(
        workspace_id=workspace.id,
        name="Pilot",
        slug="pilot",
        task="classification",
        family="tabular_foundation",
        algo="tabicl",
        target="label",
        status="ready",
    )
    db_session.add(model)
    db_session.commit()
    monkeypatch.setattr(ml_retraining, "can_configure_mlops", lambda *args, **kwargs: True)
    assert ml_retraining.supported(model) is False
    before = (db_session.query(RunSchedule).count(), db_session.query(WorkspaceJob).count())
    with pytest.raises(TabularError, match="ML_PILOT_AUTOMATION_DISABLED"):
        ml_retraining.configure(
            db_session,
            model=model,
            workspace=workspace,
            user=SimpleNamespace(id="admin"),
            body=ml_retraining.MonitoringPolicy(enabled=True, propose_retraining=True),
        )
    assert before == (db_session.query(RunSchedule).count(), db_session.query(WorkspaceJob).count())
    disabled = ml_retraining.configure(
        db_session,
        model=model,
        workspace=workspace,
        user=SimpleNamespace(id="admin"),
        body=ml_retraining.MonitoringPolicy(enabled=False),
    )
    assert disabled["policy"]["enabled"] is False


def test_old_or_forged_pilot_policy_cannot_monitor_or_dispatch_retraining():
    model = SimpleNamespace(
        family="tabular_foundation",
        task="classification",
        params_json={
            "retraining_proposal": "stale-proposal",
            "mlops": {"monitoring": {"enabled": True, "propose_retraining": True}},
        },
    )
    # Refusal precedes any source-table materialization or job/worker lookup.
    with pytest.raises(TabularError, match="ML_PILOT_AUTOMATION_DISABLED"):
        ml_retraining._active(None, model, None)
    with pytest.raises(TabularError, match="ML_PILOT_AUTOMATION_DISABLED"):
        ml_retraining.verify_training(None, model)
