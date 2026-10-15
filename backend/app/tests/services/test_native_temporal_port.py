"""Native candidate: real ledgers, materialization and delivery; provider doubled."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import polars as pl
import pytest

from app.core.config import settings
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system_version import SystemVersion
from app.services import service_promises as promises
from app.services.execution.contracts import ExecutionPolicy
from app.services.execution.runtimes import native_port as port
from app.services.execution.runtimes.native_profile import (
    freeze_profile,
    profile_digest,
    request_for_run,
)
from app.services.flow_contracts import compile_execution_contract
from app.services.run_engine import engine
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.tests.services.test_service_contracts import review_snapshot
from app.tests.services.test_service_contracts import setup as service_setup


@pytest.fixture
def candidate(db_session, tmp_path, monkeypatch, request):
    s = service_setup.__wrapped__(db_session, tmp_path, monkeypatch)
    db = s.db
    monkeypatch.setattr(settings, "agentium_image_revision", "candidate-revision")
    monkeypatch.setattr(settings, "dataops_enabled", True)
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    from app.services.tabular_datasets import register_frame

    dataset = register_frame(
        db, workspace_id=s.workspace.id, name="Source", frame=pl.DataFrame({"value": [1, 2]})
    )
    options = getattr(request, "param", "agent_data_agent")
    options = options if isinstance(options, dict) else {"composition": options}
    composition = options["composition"]
    skills = []
    for slug in ("azure_llm_v1", "data_prep_v1", "evaluate_v2"):
        row = Skill(
            id=str(uuid4()),
            slug=slug,
            workspace_id=s.workspace.id,
            name=slug,
            input_schema=(
                {
                    "type": "object",
                    "required": ["dataset_id"],
                    "properties": {"dataset_id": {"type": "string"}},
                }
                if composition == "data_agent_delivery" and slug == "azure_llm_v1"
                else {"type": "object"}
            ),
            output_schema={"type": "object"},
        )
        db.add(row)
        skills.append(row)
    db.flush()
    flow = {
        "nodes": [
            {
                "id": "source",
                "kind": "source",
                "config": {"ingress_kind": "schedule", "input_schema": {"type": "object"}},
            },
            {"id": "plan", "kind": "task", "config": {"skill_slug": "azure_llm_v1"}},
            {
                "id": "prepare",
                "kind": "task",
                "config": {
                    "skill_slug": "data_prep_v1",
                    "data_prep": {
                        "spec": {
                            "version": 1,
                            "operation": "prepare",
                            "steps": [],
                            "outputs": [{"name": "Native result", "port": "out"}],
                        },
                        "inputs": {"in": {"dataset_id": dataset.id}},
                    },
                },
            },
            {"id": "explain", "kind": "task", "config": {"skill_slug": "azure_llm_v1"}},
            {
                "id": "review",
                "kind": "hitl",
                "config": {"prompt": "Review exact delivery in Work/services"},
            },
            {"id": "delivery", "kind": "sink"},
        ],
        "edges": [
            {"from": a, "to": b, "kind": "control" if b == "prepare" else "data"}
            for a, b in zip(
                ["source", "plan", "prepare", "explain", "review"],
                ["plan", "prepare", "explain", "review", "delivery"],
            )
        ],
    }
    from hashlib import sha256

    evidence_text = "The source contains two rows."
    evidence = [
        {
            "id": "source-proof",
            "text": evidence_text,
            "sha256": sha256(evidence_text.encode()).hexdigest(),
        }
    ]
    if composition == "data_agent_delivery":
        flow["nodes"] = [n for n in flow["nodes"] if n["id"] != "plan"]
        flow["nodes"].insert(
            -2,
            {
                "id": "judge",
                "kind": "task",
                "config": {
                    "skill_slug": "evaluate_v2",
                    "typed_evaluation": {
                        "rubric_id": "native-qualification",
                        "rubric_version": "1",
                        "subject_ref": "source@v1",
                        "questions": [
                            {
                                "key": "complete",
                                "question": "Does the source contain two rows?",
                                "type": "boolean",
                                "acceptable_values": [True],
                            }
                        ],
                        "budget": {"max_calls": 1, "max_tokens": 10000, "max_cost_usd": 1},
                        "tariff": {
                            "provider": "openai",
                            "model": "judge-test",
                            "input_per_million": 1,
                            "output_per_million": 2,
                            "currency": "USD",
                            "reference": "local-test-double",
                        },
                    },
                },
            },
        )
        flow["edges"] = [
            {"from": a, "to": b, "kind": "control" if b == "prepare" else "data"}
            for a, b in zip(
                ["source", "prepare", "explain", "judge", "review"],
                ["prepare", "explain", "judge", "review", "delivery"],
            )
        ]
    if options.get("explicit_output_port"):
        prepare = next(n for n in flow["nodes"] if n["id"] == "prepare")
        spec = prepare["config"]["data_prep"]["spec"]
        spec.update(operation="split", params={"keys": ["value"], "ratios": [0.5, 0.5]})
        spec["outputs"].append({"name": "Selected result", "port": "selected"})
        next(e for e in flow["edges"] if e["from"] == "prepare")["from_port"] = "selected"
    contract = compile_execution_contract(
        db, flow=flow, workspace_id=s.workspace.id, runtime_mode="dag_overlay"
    )
    s.system.flow_definition, s.system.skill_ids = flow, [row.id for row in skills]
    version = SystemVersion(
        id=str(uuid4()),
        system_id=s.system.id,
        workspace_id=s.workspace.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        execution_contract=contract,
        release_kind="publish",
    )
    db.add(version)
    db.flush()
    s.system.published_flow_version_id = version.id
    run = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        system_id=s.system.id,
        status="pending",
        initiated_by_user_id=s.owner.id,
        flow_snapshot=flow,
        published_flow_version_id=version.id,
        flow_version_id=version.id,
        flow_sha256=version.flow_sha256,
        execution_contract=contract,
        input_ref={"query": "Prepare the governed dataset", "evidence": evidence},
    )
    db.add(run)
    roles = {
        "data_prepare": "prepare",
        "agent_explain": "explain",
        "review": "review",
        "delivery": "delivery",
    }
    roles.update(
        {"agent_plan": "plan"} if composition == "agent_data_agent" else {"judge": "judge"}
    )
    profile = freeze_profile(
        run,
        {
            "composition": composition,
            "role_nodes": roles,
            "poll_interval_s": 1,
            "output_port": "selected" if options.get("explicit_output_port") else None,
        },
    )
    run.execution_policy = ExecutionPolicy(
        engine="temporal",
        runtime_revision=settings.agentium_image_revision,
        deadline_at=datetime.now(UTC) + timedelta(hours=1),
        attempt_timeout_s=3600,
        native_profile=profile,
        native_profile_digest=profile_digest(profile),
    ).model_dump(mode="json")
    now = datetime.utcnow()
    c = promises.create_contract(
        db,
        s.workspace.id,
        s.system.id,
        s.owner.id,
        {"starts_on": now.date().isoformat(), "deadline": "23:59"},
        created_by=s.owner.id,
    )
    promises.publish_contract(db, s.workspace.id, c.id, user_id=s.owner.id, now=now)
    window = promises.tick(db, now, workspace_id=s.workspace.id)[0]
    window.input_snapshot_json = {
        "payload": {},
        "refs": [],
        "qualifications": {},
        "qualification_requirements": {},
    }
    promises.claim_window(
        db, s.workspace.id, window.id, worker_id="native", run_id=run.id, lease_seconds=120, now=now
    )
    db.commit()
    calls = []
    real_resolver = engine.resolve_skill

    async def provider_double(payload, ctx):
        calls.append(ctx["_skill_node_id"])
        return {
            "summary": "Provider is doubled in this local qualification",
            **payload,
            "evidence": evidence,
        }

    monkeypatch.setattr(
        engine,
        "resolve_skill",
        lambda slug: provider_double if slug == "azure_llm_v1" else real_resolver(slug),
    )
    from app.services.model_plane import execution

    monkeypatch.setattr(
        execution,
        "resolve_skill_model_execution",
        lambda *args, **kwargs: (
            execution.ModelExecution("openai", "judge-test", "workspace", "workspace")
            if kwargs.get("slug") == "evaluate_v2"
            else None
        ),
    )

    class JudgeProviderDouble:
        async def generate(self, **kwargs):
            import json

            calls.append("judge-provider")
            return {
                "model": "judge-test",
                "usage": {"prompt_tokens": 20, "completion_tokens": 20, "total_tokens": 40},
                "content": json.dumps(
                    {
                        "answers": {
                            "complete": {
                                "status": "answered",
                                "value": True,
                                "reason": None,
                                "explanation": "The supplied evidence states two rows.",
                                "evidence": [
                                    {
                                        "evidence_id": "source-proof",
                                        "start": 0,
                                        "end": len(evidence_text),
                                        "quote": evidence_text,
                                    }
                                ],
                            }
                        }
                    }
                ),
            }

    monkeypatch.setattr(
        execution, "build_model_client", lambda *args, **kwargs: JudgeProviderDouble()
    )
    return SimpleNamespace(
        **vars(s),
        run=run,
        window=window,
        profile=profile,
        request=request_for_run(db, run),
        calls=calls,
    )


def submit(s, role):
    return asyncio.run(port.submit(s.db, s.request, role))


def test_real_materialization_review_and_receipt_are_distinct_authorities(candidate):
    s = candidate
    assert port.begin(s.db, s.request)["roles"][-2:] == ["review", "delivery"]
    assert submit(s, "agent_plan")["status"] == "succeeded"
    first = submit(s, "agent_plan")
    assert first["status"] == "succeeded" and s.calls == ["plan"]
    prepared = submit(s, "data_prepare")
    assert prepared["status"] == "succeeded"
    assert submit(s, "agent_explain")["status"] == "succeeded"
    assert submit(s, "review")["status"] == "waiting"
    assert port.observe(s.db, s.request, "review")["status"] == "waiting"
    with pytest.raises(ValueError, match="DECISION_REQUIRED"):
        submit(s, "delivery")
    decision = promises.review_delivery(
        s.db,
        s.workspace.id,
        s.window.id,
        reviewer_user_id=s.owner.id,
        accept=True,
        qualify_candidate=True,
        note="Reviewed the actual two-row output",
        **review_snapshot(s, s.window),
    )
    s.db.commit()
    assert port.observe(s.db, s.request, "review")["reference"] == {
        "kind": "decision",
        "id": decision.id,
    }
    result = submit(s, "delivery")
    assert result["status"] == "succeeded" and result["reference"]["kind"] == "delivery_receipt"
    s.db.refresh(s.run)
    assert (
        s.run.status == "completed"
        and s.run.output_ref["delivery_receipt_id"] == result["reference"]["id"]
    )
    assert port.uncertain(s.db, s.request, "delivery") == result
    from app.models.recipe import RecipeExecution

    assert s.db.query(RecipeExecution).filter_by(run_id=s.run.id).count() == 1
    assert s.db.query(SkillInvocation).filter_by(run_id=s.run.id).count() == 3


def test_scope_revision_membership_and_signals_never_authorize(candidate, monkeypatch):
    s = candidate
    with pytest.raises(ValueError, match="SCOPE"):
        port.begin(s.db, {**s.request, "workspace_id": s.foreign.id})
    with pytest.raises(ValueError, match="REQUEST"):
        port.begin(s.db, {**s.request, "profile_digest": "f" * 64})
    monkeypatch.setattr(settings, "agentium_image_revision", "new-revision")
    with pytest.raises(ValueError, match="VERSION_UNAVAILABLE"):
        port.begin(s.db, s.request)
    port.authorize(s.db, s.request, enforce_revision=False)  # transport only
    monkeypatch.setattr(settings, "agentium_image_revision", "candidate-revision")
    s.owner.is_active = False
    s.db.commit()
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        port.begin(s.db, s.request)
    assert not s.db.query(SkillInvocation).filter_by(run_id=s.run.id).count()


def test_unknown_invocation_is_never_reexecuted(candidate):
    s = candidate
    port.begin(s.db, s.request)
    submit(s, "agent_plan")
    row = s.db.get(SkillInvocation, port.invocation_id(s.run, "plan"))
    row.status, row.output_ref = "running", {}
    s.db.commit()
    assert submit(s, "agent_plan")["status"] == "running"
    assert s.calls == ["plan"]
    assert port.uncertain(s.db, s.request, "agent_plan")["status"] == "failed"
    s.db.refresh(row)
    assert row.status == "lost" and "RECONCILIATION" in row.error


def test_profile_rejects_hidden_executable_and_nonpublished_input(candidate):
    s = candidate
    original = deepcopy(s.run.flow_snapshot)
    s.run.flow_snapshot = {
        **original,
        "nodes": [
            *original["nodes"],
            {"id": "hidden", "kind": "task", "config": {"skill_slug": "azure_llm_v1"}},
        ],
    }
    s.run.flow_sha256 = canonical_flow_sha256(s.run.flow_snapshot)
    with pytest.raises(ValueError, match="UNBOUND_EXECUTION"):
        freeze_profile(s.run, s.profile)
    s.run.published_flow_version_id = None
    with pytest.raises(ValueError, match="PUBLISHED_FLOW_REQUIRED"):
        freeze_profile(s.run, s.profile)


@pytest.mark.parametrize("candidate", ["data_agent_delivery"], indirect=True)
def test_second_composition_uses_actual_typed_judge_and_gates_delivery(candidate):
    s = candidate
    port.begin(s.db, s.request)
    for role in ("data_prepare", "agent_explain", "judge"):
        result = submit(s, role)
        row = s.db.get(SkillInvocation, result["reference"]["id"])
        assert result["status"] == "succeeded", row.error
    assert s.calls == ["explain", "judge-provider"]
    judged = s.db.get(SkillInvocation, port.invocation_id(s.run, "judge"))
    assert judged.output_ref["answers"]["complete"]["value"] is True
    assert judged.output_ref["disposition"] == "review"
    assert submit(s, "review")["status"] == "waiting"
    with pytest.raises(ValueError, match="DECISION_REQUIRED"):
        submit(s, "delivery")


def test_compute_submission_returns_without_waiting_for_worker(candidate, monkeypatch):
    s = candidate
    port.begin(s.db, s.request)
    submit(s, "agent_plan")
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(
        celery_app, "send_task", lambda *args, **kwargs: SimpleNamespace(id=kwargs["task_id"])
    )
    result = submit(s, "data_prepare")
    assert result["status"] == "waiting"
    invocation = s.db.get(SkillInvocation, result["reference"]["id"])
    assert invocation.output_ref == {} and invocation.completed_at is None
    assert port.observe(s.db, s.request, "data_prepare")["status"] == "waiting"
    from app.services.dataops.preparation import run_preparation

    run_preparation(invocation.trace["native_reference"]["id"])
    assert port.observe(s.db, s.request, "data_prepare")["status"] == "succeeded"


def test_late_provider_cannot_overwrite_unknown_or_publish_output(candidate, monkeypatch):
    s = candidate
    port.begin(s.db, s.request)
    from app.db.base import SessionLocal

    async def late(payload, ctx):
        with SessionLocal() as db:
            port.uncertain(db, s.request, "agent_plan")
        ctx["_provider_usage_v1"] = {"calls": [], "note": "late"}
        return {"answer": "too late"}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: late)
    # The normal cancellation membrane may win before publication; both paths
    # must retain the unknown ledger and discard this late output.
    try:
        submit(s, "agent_plan")
    except asyncio.CancelledError:
        pass
    s.db.expire_all()
    row = s.db.get(SkillInvocation, port.invocation_id(s.run, "plan"))
    assert row.status == "lost" and row.output_ref == {}
    assert row.trace["native_late_response"] is True


def test_revocation_during_provider_call_prevents_output_publication(candidate, monkeypatch):
    s = candidate
    port.begin(s.db, s.request)
    from app.db.base import SessionLocal
    from app.models.user import User

    async def revoked(payload, ctx):
        with SessionLocal() as db:
            db.get(User, s.owner.id).is_active = False
            db.commit()
        return {"answer": "must never be published"}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: revoked)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        submit(s, "agent_plan")
    s.db.expire_all()
    row = s.db.get(SkillInvocation, port.invocation_id(s.run, "plan"))
    assert row.status == "failed" and row.output_ref == {}
    assert row.error == "NATIVE_PUBLICATION_AUTHORITY_REVOKED"


def test_parent_cancel_after_compute_completion_cannot_publish_it(candidate, monkeypatch):
    s = candidate
    port.begin(s.db, s.request)
    submit(s, "agent_plan")
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(
        celery_app, "send_task", lambda *args, **kwargs: SimpleNamespace(id=kwargs["task_id"])
    )
    response = submit(s, "data_prepare")
    row = s.db.get(SkillInvocation, response["reference"]["id"])
    from app.services.dataops.preparation import run_preparation

    run_preparation(row.trace["native_reference"]["id"])
    from app.services.execution.control import request_run_cancel

    request_run_cancel(s.db, s.run)
    with pytest.raises(ValueError, match="CANCELLED"):
        port.observe(s.db, s.request, "data_prepare")
    assert row.output_ref == {}
    port.settle_failed_run(s.db, s.run)
    s.db.commit()
    s.db.refresh(row)
    assert row.status == "cancelled"


@pytest.mark.parametrize("enabled", [True, False])
def test_real_service_tick_stages_only_temporal_and_refusal_rolls_back(
    candidate, monkeypatch, enabled
):
    s = candidate
    from app.models.execution_control import ExecutionDispatch
    from app.models.run_dispatch_outbox import RunDispatchOutbox
    from app.models.service_contract import ServiceAttempt, ServiceWindow
    from app.services.service_engine import service_tick

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(settings, "execution_temporal_enabled", enabled)
    monkeypatch.setattr(settings, "execution_durable_dispatch_enabled", True)
    monkeypatch.setattr(settings, "execution_canary_workspaces", s.workspace.id)
    s.workspace.settings = {"features": {"service_contracts": True, "flow_publication_v1": True}}
    s.system.execution_profile = {"orchestration": {"engine": "temporal", **s.profile}}
    now = datetime.utcnow()
    c = promises.create_contract(
        s.db,
        s.workspace.id,
        s.system.id,
        s.owner.id,
        {"starts_on": now.date().isoformat(), "deadline": "23:59"},
        created_by=s.owner.id,
        logical_key="native-scheduled",
    )
    promises.publish_contract(s.db, s.workspace.id, c.id, user_id=s.owner.id, now=now)
    s.db.commit()
    before = s.db.query(Run).count()
    stats = service_tick(now=now)
    s.db.expire_all()
    assert stats["fired"] == int(enabled)
    assert s.db.query(Run).count() == before + int(enabled)
    window = s.db.query(ServiceWindow).filter_by(contract_id=c.id).one()
    if enabled:
        attempt = s.db.query(ServiceAttempt).filter_by(window_id=window.id).one()
        run = s.db.get(Run, attempt.run_id)
        intent = s.db.query(ExecutionDispatch).filter_by(entity_kind="run", entity_id=run.id).one()
        assert intent.task_name == "agentium.execution_temporal_start"
        assert s.db.query(RunDispatchOutbox).filter_by(run_id=run.id).count() == 0
        assert port.begin(s.db, request_for_run(s.db, run))["roles"] == list(
            port.COMPOSITIONS[s.profile["composition"]]
        )
    else:
        assert s.db.query(ServiceAttempt).filter_by(window_id=window.id).count() == 0


@pytest.mark.parametrize("controlled", [False, True])
def test_compute_deadline_is_bounded_by_parent_before_queueing(candidate, monkeypatch, controlled):
    s = candidate
    from app.models.execution_control import ExecutionDispatch
    from app.models.recipe import RecipeExecution

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(settings, "execution_control_enabled", controlled)
    monkeypatch.setattr(settings, "execution_durable_dispatch_enabled", True)
    monkeypatch.setattr(settings, "connector_framework_enabled", False)
    monkeypatch.setattr(settings, "execution_canary_workspaces", s.workspace.id)
    deadline = datetime.now(UTC) + timedelta(seconds=25)
    s.run.execution_policy = {**s.run.execution_policy, "deadline_at": deadline.isoformat()}
    s.db.commit()
    port.begin(s.db, s.request)
    submit(s, "agent_plan")
    result = submit(s, "data_prepare")
    assert result["status"] == "waiting"
    row = s.db.query(RecipeExecution).filter_by(run_id=s.run.id).one()
    intent = (
        s.db.query(ExecutionDispatch)
        .filter_by(entity_kind="recipe_execution", entity_id=row.id)
        .one()
    )
    assert row.deadline_at <= deadline.replace(tzinfo=None)
    assert intent.deadline_at <= deadline.replace(tzinfo=None)
    assert row.timeout_s <= 25
    if not controlled:
        from app.services.dataops import compute_registry

        monkeypatch.setattr(
            compute_registry.runs,
            "utcnow",
            lambda: deadline.replace(tzinfo=None) + timedelta(seconds=1),
        )
        assert not compute_registry.start(s.db, row)
        assert row.status == "timed_out"


@pytest.mark.parametrize(
    "candidate",
    [
        {"composition": "data_agent_delivery"},
        {"composition": "data_agent_delivery", "explicit_output_port": True},
    ],
    indirect=True,
)
def test_native_agent_receives_the_selected_dataset_output(candidate):
    s = candidate
    port.begin(s.db, s.request)
    assert submit(s, "data_prepare")["status"] == "succeeded"
    prepared = s.db.get(SkillInvocation, port.invocation_id(s.run, "prepare"))
    selected = "selected" if "selected" in prepared.output_ref["outputs"] else "out"
    assert submit(s, "agent_explain")["status"] == "succeeded"
    agent = s.db.get(SkillInvocation, port.invocation_id(s.run, "explain"))
    assert agent.input_ref["dataset_id"] == prepared.output_ref["outputs"][selected]["dataset_id"]
    assert "outputs" not in agent.input_ref
    assert agent.output_ref["dataset_id"] == agent.input_ref["dataset_id"]
    if selected == "selected":
        with pytest.raises(ValueError, match="NATIVE_OUTPUT_PORT_REQUIRED"):
            freeze_profile(s.run, {**s.profile, "output_port": None})
        with pytest.raises(ValueError, match="NATIVE_OUTPUT_PORT_UNKNOWN"):
            freeze_profile(s.run, {**s.profile, "output_port": "missing"})
    assert submit(s, "judge")["status"] == "succeeded"
    assert submit(s, "review")["status"] == "waiting"
    assert s.run.output_ref["dataset_id"] == agent.input_ref["dataset_id"]
    promises.review_delivery(
        s.db,
        s.workspace.id,
        s.window.id,
        reviewer_user_id=s.owner.id,
        accept=True,
        qualify_candidate=True,
        note="Reviewed the selected output port",
        **review_snapshot(s, s.window),
    )
    s.db.commit()
    assert submit(s, "delivery")["reference"]["kind"] == "delivery_receipt"
