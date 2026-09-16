"""Attack tests for server-owned operator Run outcome receipts."""
from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.services.control_policy_snapshot import control_policy_execution_contract
from app.services.outcome.derive import apply_operator_override
from app.services.run_engine.engine import _finalize_run
from app.services.run_outcome_provenance import (
    RUN_OPERATOR_OVERRIDE_RECEIPT_SCHEMA_VERSION,
    RUN_OUTCOME_OVERRIDE_AUDIT_EVENT,
    RUN_RUNTIME_AUTO_ACTOR,
    RUN_RUNTIME_AUTO_AUDIT_EVENT,
    RUN_RUNTIME_AUTO_RECEIPT_SCHEMA_VERSION,
    record_operator_outcome_override,
    record_runtime_auto_outcome,
    run_measurement_provenance,
)


def _record(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"operator-receipt-{uuid4().hex[:10]}",
        name="Operator receipt",
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        status="completed",
        completed_at=datetime.now(UTC).replace(tzinfo=None),
        value_estimated=10.0,
        value_source="auto",
    )
    db_session.add_all([workspace, run])
    db_session.commit()
    apply_operator_override(
        run,
        value=42.75,
        note="confidential commercial note",
    )
    receipt = record_operator_outcome_override(
        run,
        db=db_session,
        actor="operator@example.test",
        previous_value=10.0,
        note="confidential commercial note",
    )
    db_session.commit()
    return workspace, run, receipt


def _audit(db_session, receipt):
    return db_session.query(AuditLog).filter(AuditLog.id == receipt["audit_id"]).one()


def _record_runtime(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"runtime-receipt-{uuid4().hex[:10]}",
        name="Runtime receipt",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Measured System",
        objective="Measure an outcome",
        status="active",
        flow_definition={"nodes": [{"id": "measure"}]},
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Measured policy",
        scope="system",
        target_id=system.id,
    )
    system.control_policy_id = policy.id
    completed_at = datetime.now(UTC).replace(tzinfo=None)
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        completed_at=completed_at,
        value_estimated=23.5,
        value_source="auto",
        input_ref={
            "execution": {
                "flow_sha256": "a" * 64,
                "runtime_revision": "b" * 40,
                "control_policy": control_policy_execution_contract(policy),
            }
        },
    )
    db_session.add_all([workspace, system, policy, run])
    db_session.commit()
    receipt = record_runtime_auto_outcome(run, db=db_session)
    db_session.commit()
    return workspace, system, policy, run, receipt


def test_operator_receipt_is_exact_audit_bound_and_redacted(db_session):
    workspace, run, receipt = _record(db_session)
    audit = _audit(db_session, receipt)

    assert receipt["schema_version"] == RUN_OPERATOR_OVERRIDE_RECEIPT_SCHEMA_VERSION
    assert receipt["audit_id"] == audit.id
    assert receipt["artifact_ref"].startswith("sha256:")
    assert audit.workspace_id == workspace.id
    assert audit.event_type == RUN_OUTCOME_OVERRIDE_AUDIT_EVENT
    assert audit.actor == "operator@example.test"
    assert audit.details == {
        "schema_version": 1,
        "receipt_schema_version": RUN_OPERATOR_OVERRIDE_RECEIPT_SCHEMA_VERSION,
        "source": "operator_override",
        "run_id": run.id,
        "previous_value_sha256": receipt["previous_value_sha256"],
        "value_sha256": receipt["value_sha256"],
        "note_sha256": receipt["note_sha256"],
        "artifact_ref": receipt["artifact_ref"],
    }
    serialized_audit = json.dumps(audit.details, sort_keys=True)
    assert "confidential commercial note" not in serialized_audit
    assert "42.75" not in serialized_audit
    assert "10.0" not in serialized_audit
    assert run_measurement_provenance(run) is None
    assert run_measurement_provenance(run, db=db_session) == {
        "schema_version": 1,
        "source": "operator_override",
        "audit_id": audit.id,
        "actor": "operator@example.test",
        "recorded_at": receipt["recorded_at"],
        "artifact_ref": receipt["artifact_ref"],
    }


def test_operator_receipt_fails_closed_when_exact_audit_is_missing(db_session):
    _workspace, run, receipt = _record(db_session)
    db_session.delete(_audit(db_session, receipt))
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


@pytest.mark.parametrize(
    "mutation",
    [
        "event_type",
        "actor",
        "timestamp",
        "details",
    ],
)
def test_operator_receipt_fails_closed_when_audit_is_tampered(
    db_session,
    mutation,
):
    _workspace, run, receipt = _record(db_session)
    audit = _audit(db_session, receipt)
    if mutation == "event_type":
        audit.event_type = "run.outcome.operator_override.forged"
    elif mutation == "actor":
        audit.actor = "different-actor@example.test"
    elif mutation == "timestamp":
        audit.timestamp = audit.timestamp + timedelta(seconds=1)
    else:
        audit.details = {**dict(audit.details), "unexpected": True}
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


def test_operator_receipt_cannot_resolve_an_audit_from_another_workspace(db_session):
    _workspace, run, receipt = _record(db_session)
    foreign = Workspace(
        id=str(uuid4()),
        slug=f"operator-receipt-foreign-{uuid4().hex[:10]}",
        name="Foreign operator receipt",
    )
    db_session.add(foreign)
    db_session.flush()
    _audit(db_session, receipt).workspace_id = foreign.id
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


@pytest.mark.parametrize("field", ["value", "note"])
def test_operator_receipt_fails_closed_on_run_hash_drift(db_session, field):
    _workspace, run, _receipt = _record(db_session)
    if field == "value":
        run.value_estimated = 43.0
    else:
        run.operator_value_note = "tampered note"

    assert run_measurement_provenance(run, db=db_session) is None


def test_operator_receipt_rejects_embedded_receipt_tampering(db_session):
    _workspace, run, _receipt = _record(db_session)
    output_ref = copy.deepcopy(run.output_ref)
    output_ref["operator_value_overrides"][-1]["actor"] = "forged@example.test"
    run.output_ref = output_ref

    assert run_measurement_provenance(run, db=db_session) is None


def test_runtime_auto_receipt_is_exact_audit_bound(db_session):
    workspace, system, policy, run, receipt = _record_runtime(db_session)
    audit = _audit(db_session, receipt)

    assert receipt["schema_version"] == RUN_RUNTIME_AUTO_RECEIPT_SCHEMA_VERSION
    assert receipt["workspace_id"] == workspace.id
    assert receipt["system_id"] == system.id
    assert receipt["control_policy"] == control_policy_execution_contract(policy)
    assert receipt["actor"] == RUN_RUNTIME_AUTO_ACTOR
    assert audit.event_type == RUN_RUNTIME_AUTO_AUDIT_EVENT
    assert audit.actor == RUN_RUNTIME_AUTO_ACTOR
    assert audit.workspace_id == workspace.id
    assert set(audit.details) == {
        "schema_version",
        "receipt_schema_version",
        "source",
        "run_id",
        "workspace_id",
        "system_id",
        "flow_sha256",
        "runtime_revision",
        "control_policy",
        "value_sha256",
        "completed_at",
        "artifact_ref",
    }
    assert run_measurement_provenance(run) is None
    assert run_measurement_provenance(run, db=db_session) == {
        "schema_version": 1,
        "source": "runtime_auto",
        "audit_id": audit.id,
        "actor": RUN_RUNTIME_AUTO_ACTOR,
        "recorded_at": receipt["recorded_at"],
        "artifact_ref": receipt["artifact_ref"],
    }


def test_runtime_auto_legacy_mutable_json_is_unavailable(db_session):
    _workspace, _system, _policy, run, _receipt = _record_runtime(db_session)
    input_ref = copy.deepcopy(run.input_ref)
    input_ref["execution"].pop("outcome_receipt")
    run.input_ref = input_ref
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


def test_runtime_auto_receipt_is_unavailable_when_exact_audit_is_missing(db_session):
    _workspace, _system, _policy, run, receipt = _record_runtime(db_session)
    db_session.delete(_audit(db_session, receipt))
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("flow_sha256", "not-a-digest"),
        ("runtime_revision", ""),
        ("control_policy", {"schema_version": 1, "state": "not_configured"}),
    ],
)
def test_runtime_auto_writer_rejects_invalid_execution_identity(
    db_session,
    field,
    value,
):
    _workspace, _system, _policy, run, receipt = _record_runtime(db_session)
    db_session.delete(_audit(db_session, receipt))
    input_ref = copy.deepcopy(run.input_ref)
    input_ref["execution"].pop("outcome_receipt")
    input_ref["execution"][field] = value
    run.input_ref = input_ref
    db_session.commit()

    with pytest.raises(ValueError, match="provenance is incomplete"):
        record_runtime_auto_outcome(run, db=db_session)


@pytest.mark.parametrize("mutation", ["event_type", "actor", "timestamp", "details"])
def test_runtime_auto_receipt_fails_closed_on_audit_tamper(db_session, mutation):
    _workspace, _system, _policy, run, receipt = _record_runtime(db_session)
    audit = _audit(db_session, receipt)
    if mutation == "event_type":
        audit.event_type = "run.outcome.runtime_auto.forged"
    elif mutation == "actor":
        audit.actor = "forged-runtime"
    elif mutation == "timestamp":
        audit.timestamp = audit.timestamp + timedelta(microseconds=1)
    else:
        audit.details = {**dict(audit.details), "unexpected": True}
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("flow_sha256", "c" * 64),
        ("runtime_revision", "c" * 40),
        ("actor", "forged-runtime"),
        ("workspace_id", "foreign-workspace"),
    ],
)
def test_runtime_auto_receipt_rejects_embedded_tamper(
    db_session,
    field,
    value,
):
    _workspace, _system, _policy, run, _receipt = _record_runtime(db_session)
    input_ref = copy.deepcopy(run.input_ref)
    input_ref["execution"]["outcome_receipt"][field] = value
    run.input_ref = input_ref
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


def test_runtime_auto_receipt_cannot_resolve_cross_tenant_audit(db_session):
    _workspace, _system, _policy, run, receipt = _record_runtime(db_session)
    foreign = Workspace(
        id=str(uuid4()),
        slug=f"runtime-receipt-foreign-{uuid4().hex[:10]}",
        name="Foreign runtime receipt",
    )
    db_session.add(foreign)
    db_session.flush()
    _audit(db_session, receipt).workspace_id = foreign.id
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


@pytest.mark.parametrize("field", ["value", "completed_at", "execution_policy"])
def test_runtime_auto_receipt_rejects_run_or_execution_drift(db_session, field):
    _workspace, _system, _policy, run, _receipt = _record_runtime(db_session)
    if field == "value":
        run.value_estimated = 99.0
    elif field == "completed_at":
        run.completed_at = run.completed_at + timedelta(seconds=1)
    else:
        input_ref = copy.deepcopy(run.input_ref)
        input_ref["execution"]["control_policy"]["sha256"] = "d" * 64
        run.input_ref = input_ref
    db_session.commit()

    assert run_measurement_provenance(run, db=db_session) is None


def _running_engine_run(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"runtime-finalize-{uuid4().hex[:10]}",
        name="Runtime finalizer",
    )
    capability = Capability(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=f"runtime-finalize-{uuid4().hex[:10]}",
        name="Measured capability",
        value_per_outcome=12.0,
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Runtime finalizer System",
        objective="Finalize atomically",
        status="active",
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Runtime finalizer policy",
        scope="system",
        target_id=system.id,
    )
    system.control_policy_id = policy.id
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=capability.id,
        status="running",
        input_ref={
            "execution": {
                "flow_sha256": "e" * 64,
                "runtime_revision": "f" * 40,
                "control_policy": control_policy_execution_contract(policy),
            }
        },
    )
    db_session.add_all([workspace, capability, system, policy, run])
    db_session.commit()
    return system, capability, policy, run


def test_engine_finalizer_writes_runtime_receipt_and_audit_atomically(
    db_session,
    monkeypatch,
):
    system, capability, policy, run = _running_engine_run(db_session)
    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.schedule_eval",
        lambda _run_id: None,
    )

    _finalize_run(
        db_session,
        run,
        system=system,
        capability=capability,
        control=policy,
        invocations=[],
        duration_ms=1.0,
        last_output={"answer": "done"},
    )

    provenance = run_measurement_provenance(run, db=db_session)
    assert provenance is not None
    assert provenance["source"] == "runtime_auto"
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.id == provenance["audit_id"],
            AuditLog.event_type == RUN_RUNTIME_AUTO_AUDIT_EVENT,
        )
        .count()
        == 1
    )


def test_answer_capability_fails_when_retrieval_succeeds_but_answer_is_missing(
    db_session,
    monkeypatch,
):
    system, capability, policy, run = _running_engine_run(db_session)
    capability.output_unit = "answer"
    answer = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="llm_rag_answer_v1",
        status="failed",
        error="provider credentials rejected",
        output_ref={},
    )
    retrieval = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="semantic_search_v1",
        status="completed",
        output_ref={"results": [{"content": "diagnostic evidence"}]},
    )
    db_session.add_all([answer, retrieval])
    db_session.commit()
    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.schedule_eval",
        lambda _run_id: None,
    )

    result = _finalize_run(
        db_session,
        run,
        system=system,
        capability=capability,
        control=policy,
        invocations=[answer, retrieval],
        duration_ms=10.0,
        last_output=retrieval.output_ref,
    )

    assert result["status"] == "failed"
    assert result["outcome"]["decision"] == "blocked"
    assert result["outcome"]["confidence"] == 0.0
    assert run.error == "required_output_missing:answer:llm_rag_answer_v1"
    assert run.output_ref == {
        "error": {
            "code": "required_output_missing",
            "message": "The System did not produce its required answer.",
            "output_unit": "answer",
        }
    }


def test_answer_capability_can_complete_when_answer_exists_and_audit_fails(
    db_session,
    monkeypatch,
):
    system, capability, policy, run = _running_engine_run(db_session)
    capability.output_unit = "answer"
    answer = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="llm_rag_answer_v1",
        status="completed",
        output_ref={"answer": "Grounded answer", "citations": []},
    )
    audit = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="audit_log_v1",
        status="failed",
        error="audit sidecar unavailable",
        output_ref={},
    )
    db_session.add_all([answer, audit])
    db_session.commit()
    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.schedule_eval",
        lambda _run_id: None,
    )

    result = _finalize_run(
        db_session,
        run,
        system=system,
        capability=capability,
        control=policy,
        invocations=[answer, audit],
        duration_ms=10.0,
        last_output=answer.output_ref,
    )

    assert result["status"] == "completed"
    assert run.output_ref == answer.output_ref


def test_engine_finalizer_rolls_back_completion_when_runtime_audit_flush_fails(
    db_session,
    monkeypatch,
):
    system, capability, policy, run = _running_engine_run(db_session)
    real_flush = db_session.flush

    def fail_runtime_audit_flush(*args, **kwargs):
        if any(
            isinstance(row, AuditLog)
            and row.event_type == RUN_RUNTIME_AUTO_AUDIT_EVENT
            for row in db_session.new
        ):
            raise RuntimeError("audit authority unavailable")
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_runtime_audit_flush)
    with pytest.raises(RuntimeError, match="audit authority unavailable"):
        _finalize_run(
            db_session,
            run,
            system=system,
            capability=capability,
            control=policy,
            invocations=[],
            duration_ms=1.0,
            last_output={"answer": "must not commit"},
        )
    db_session.rollback()
    db_session.expire_all()

    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert persisted.status == "running"
    assert persisted.completed_at is None
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == RUN_RUNTIME_AUTO_AUDIT_EVENT)
        .count()
        == 0
    )


def test_classic_chat_completion_uses_the_same_runtime_receipt(
    db_session,
):
    from app.api.v1.endpoints.chat import _persist_chat_run

    system, _capability, _policy, _run = _running_engine_run(db_session)
    now = datetime.now(UTC).replace(tzinfo=None)
    run_id = _persist_chat_run(
        db_session,
        workspace_id=system.workspace_id,
        system_id=system.id,
        query="What changed?",
        response_text="A measured answer.",
        sources=[],
        reasoning_trace=None,
        started_at=now,
        completed_at=now,
        duration_ms=1.0,
        schedule=False,
    )

    assert run_id is not None
    chat_run = db_session.query(Run).filter(Run.id == run_id).one()
    provenance = run_measurement_provenance(chat_run, db=db_session)
    assert provenance is not None
    assert provenance["source"] == "runtime_auto"
    assert provenance["actor"] == RUN_RUNTIME_AUTO_ACTOR
