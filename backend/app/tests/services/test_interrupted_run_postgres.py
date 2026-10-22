"""Real PostgreSQL reconciliation: explicit attestation, CAS and writer conflicts."""

from copy import deepcopy

import pytest
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.services.run_engine.interrupted_run import InterruptedRunError, preview, reconcile
from app.tests.services.test_ecommerce_claims_postgres import (
    pg as _owned_pg_fixture,
)

pg = _owned_pg_fixture

IDENTITY = {
    "workspace_id": "claims-ws",
    "run_id": "claims-run",
    "decision_id": "claims-decision",
    "invocation_id": "interrupted-call",
}
ATTESTATION = {
    "operator": "qualified-operator",
    "evidence_ref": "process-stop.txt",
    "evidence_sha256": "b" * 64,
    "confirm_process_stopped": True,
}


def prepare(engine):
    with Session(engine) as db:
        run = db.get(Run, IDENTITY["run_id"])
        run.status = "running"
        run.input_ref = {"claim_id": "RC-1043", "preserve": "input"}
        run.output_ref = {"partial": "evidence remains available"}
        run.checkpoints = [
            {"kind": "hitl_pause", "decision_id": IDENTITY["decision_id"], "node_id": "review"},
            {
                "kind": "hitl_resume_dispatch",
                "decision_id": IDENTITY["decision_id"],
                "plane": "inline",
                "t": "2026-10-21T21:57:51",
            },
            {"kind": "hitl_resume", "node_id": "review", "decision_status": "accepted"},
        ]
        db.add(
            SkillInvocation(
                id=IDENTITY["invocation_id"],
                run_id=run.id,
                skill_slug="external_action_v1",
                status="running",
                input_ref={"amount": "49.90"},
                output_ref={"partial": "unknown"},
                cost=0.0,
                cost_measured=False,
                trace={"node_id": "execute"},
            )
        )
        db.commit()
        return preview(db, **IDENTITY)


def test_reconciliation_preserves_approval_outputs_and_unknown_measurements(pg):
    report = prepare(pg)
    with Session(pg) as db:
        run = db.get(Run, IDENTITY["run_id"])
        invocation = db.get(SkillInvocation, IDENTITY["invocation_id"])
        previous = deepcopy(
            (run.input_ref, run.output_ref, invocation.input_ref, invocation.output_ref)
        )
        checkpoints = deepcopy(run.checkpoints)
        assert preview(db, **IDENTITY) == report
        assert run.status == "running" and db.query(AuditLog).count() == 0
        result = reconcile(
            db, **IDENTITY, **ATTESTATION, expected_state_sha256=report["state_sha256"]
        )
        assert result["external_effect_status"] == "unknown" and result["reexecuted"] is False
        db.commit()
    with Session(pg) as db:
        run = db.get(Run, IDENTITY["run_id"])
        invocation = db.get(SkillInvocation, IDENTITY["invocation_id"])
        assert run.status == invocation.status == "failed"
        assert run.error == "inline_executor_lost_after_approval"
        assert invocation.error == "execution_interrupted_outcome_unknown"
        assert run.cancel_requested is True
        assert (
            run.input_ref,
            run.output_ref,
            invocation.input_ref,
            invocation.output_ref,
        ) == previous
        assert run.checkpoints[:-1] == checkpoints
        assert run.duration_ms is None and invocation.latency_ms is None
        assert invocation.cost == 0.0 and invocation.cost_measured is False
        assert invocation.provider_cost_usd is None
        assert db.get(Decision, IDENTITY["decision_id"]).status == "accepted"
        assert db.query(AuditLog).one().details["physical_stop_attested"] is True
        with pytest.raises(InterruptedRunError, match="RUN_NOT_RUNNING"):
            reconcile(db, **IDENTITY, **ATTESTATION, expected_state_sha256=report["state_sha256"])


@pytest.mark.parametrize(
    "change,reason",
    [
        ("attestation", "ATTESTATION_REQUIRED"),
        ("checkpoint", "STATE_CHANGED"),
        ("invocation", "STATE_CHANGED"),
        ("workspace", "WORKSPACE_NOT_FOUND"),
        ("decision", "HUMAN_APPROVAL_REQUIRED"),
        ("plane", "CHECKPOINT_MISMATCH"),
    ],
)
def test_reconciliation_refuses_missing_authority_or_changed_state(pg, change, reason):
    report = prepare(pg)
    identity, attestation = dict(IDENTITY), dict(ATTESTATION)
    with Session(pg) as db:
        run = db.get(Run, IDENTITY["run_id"])
        if change == "attestation":
            attestation["confirm_process_stopped"] = False
        elif change == "checkpoint":
            run.checkpoints = [*run.checkpoints, {"kind": "new_progress"}]
        elif change == "invocation":
            db.get(SkillInvocation, IDENTITY["invocation_id"]).output_ref = {"new": "progress"}
        elif change == "workspace":
            identity["workspace_id"] = "other-workspace"
        elif change == "decision":
            db.get(Decision, IDENTITY["decision_id"]).status = "rejected"
        elif change == "plane":
            changed = deepcopy(run.checkpoints)
            changed[1]["plane"] = "run_celery"
            run.checkpoints = changed
        db.commit()
        with pytest.raises(InterruptedRunError, match=reason):
            reconcile(db, **identity, **attestation, expected_state_sha256=report["state_sha256"])
        db.rollback()
        assert db.get(Run, IDENTITY["run_id"]).status == "running"
        assert db.get(SkillInvocation, IDENTITY["invocation_id"]).status == "running"
        assert db.query(AuditLog).count() == 0


def test_reconciliation_refuses_a_concurrent_writer_without_waiting(pg):
    report = prepare(pg)
    with Session(pg) as writer, Session(pg) as operator:
        writer.query(Run).filter_by(id=IDENTITY["run_id"]).with_for_update().one()
        with pytest.raises(InterruptedRunError, match="CONCURRENT_WRITER"):
            reconcile(
                operator, **IDENTITY, **ATTESTATION, expected_state_sha256=report["state_sha256"]
            )
        operator.rollback()
        assert operator.get(Run, IDENTITY["run_id"]).status == "running"
        assert operator.query(AuditLog).count() == 0


def test_audit_failure_rolls_back_both_terminal_states(pg, monkeypatch):
    report = prepare(pg)
    with Session(pg) as db:
        original_add = db.add

        def reject_audit(row, **kwargs):
            if isinstance(row, AuditLog):
                raise RuntimeError("audit unavailable")
            original_add(row, **kwargs)

        monkeypatch.setattr(db, "add", reject_audit)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            reconcile(db, **IDENTITY, **ATTESTATION, expected_state_sha256=report["state_sha256"])
        db.rollback()
    with Session(pg) as db:
        assert db.get(Run, IDENTITY["run_id"]).status == "running"
        assert db.get(SkillInvocation, IDENTITY["invocation_id"]).status == "running"
        assert db.query(AuditLog).count() == 0
