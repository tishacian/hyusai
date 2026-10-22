"""Composed Judges keep separate contracts and cumulative, trusted node budgets."""

from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services import service_engine
from app.services.evaluation import typed_judge
from app.services.model_plane import execution, typesafe
from app.services.model_plane.execution import ModelExecution
from app.services.skills_registry.wrappers.skills import _evaluate_v2


@pytest.fixture()
def setup(db_session, monkeypatch):
    user = User(id=str(uuid4()), username="judge-" + uuid4().hex, role="user", is_active=True)
    workspace = Workspace(
        id=str(uuid4()), name="Composed Judges", slug="judge-" + uuid4().hex, is_active=True
    )
    db_session.add_all([user, workspace])
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member"))
    text = "The customer requests a shipping investigation."
    evidence = [{"id": "source", "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}]
    calls = []

    def new_run():
        run = Run(
            id=str(uuid4()),
            workspace_id=workspace.id,
            initiated_by_user_id=user.id,
            status="running",
            input_ref={"evidence": copy.deepcopy(evidence)},
        )
        db_session.add(run)
        db_session.commit()
        return run

    async def native(**kwargs):
        calls.append(("typesafe", kwargs["model"]))
        return typesafe.normalize_response(
            {
                "model": kwargs["model"],
                "answers": {"investigation": {"type": "noul", "noul": 0.98}},
                "usage": {"input_tokens": 120, "output_tokens": 20},
            },
            questions=kwargs["questions"],
        )

    class Provider:
        async def generate(self, *, model, prompt, **options):
            calls.append(("openai", model))
            return {
                "model": model,
                "content": json.dumps(
                    {
                        "answers": {
                            "investigation": {
                                "status": "answered",
                                "value": True,
                                "reason": None,
                                "explanation": "The customer requests an investigation.",
                                "evidence": [],
                            }
                        }
                    }
                ),
                "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            }

    monkeypatch.setattr(typesafe, "evaluate", native)
    monkeypatch.setattr(execution, "build_model_client", lambda *args, **kwargs: Provider())
    return SimpleNamespace(
        db=db_session,
        user=user,
        workspace=workspace,
        evidence=evidence,
        calls=calls,
        new_run=new_run,
        run=new_run(),
    )


def request(setup, node_id, *, provider="openai", model="gpt-test", max_calls=1, run=None):
    config = {
        "rubric_id": "investigation",
        "rubric_version": "1",
        "questions": [
            {
                "key": "investigation",
                "question": "Does the customer request an investigation?",
                "type": "boolean",
                "requires_evidence": False,
                "acceptable_values": [True],
            }
        ],
        "budget": {"max_calls": max_calls, "max_tokens": 100000, "max_cost_usd": 1.0},
        "tariff": {
            "provider": provider,
            "model": model,
            "input_per_million": 1.0,
            "output_per_million": 2.0,
            "reference": "test-only",
        },
    }
    payload = {
        "_typed_evaluation": {"node_id": node_id, "typed_evaluation": config},
        "subject_ref": "case-1",
        "evidence": copy.deepcopy(setup.evidence),
    }
    ctx = {
        "workspace_id": setup.workspace.id,
        "user_id": setup.user.id,
        "run_id": (run or setup.run).id,
        "_skill_node_id": node_id,
        "_model_execution": ModelExecution(
            provider, model, "workspace", "published_graph", _api_key="test-key"
        ),
        "_model_policy_check": lambda candidate: None,
    }
    return payload, ctx


async def test_same_run_composes_native_and_generative_judges_with_independent_contracts(setup):
    native = request(setup, "native-judge", provider="typesafe", model="jev-test", max_calls=2)
    generative = request(setup, "generative-judge")

    first = await _evaluate_v2(*native)
    second = await _evaluate_v2(*generative)
    assert first["status"] == second["status"] == "completed"
    assert first["quality_status"] == second["quality_status"] == "passed"
    assert first["evaluation_id"] != second["evaluation_id"]
    assert setup.calls == [("typesafe", "jev-test"), ("openai", "gpt-test")]

    jobs = setup.db.query(WorkspaceJob).filter_by(kind=typed_judge.KIND).all()
    assert len(jobs) == 2
    assert {job.result["calls"] for job in jobs} == {1}
    assert {job.input_ref["contract"]["budget"]["max_calls"] for job in jobs} == {1, 2}
    assert {job.input_ref["contract"]["tariff"]["provider"] for job in jobs} == {
        "typesafe",
        "openai",
    }
    for args, original in ((native, first), (generative, second)):
        cached = await _evaluate_v2(*args)
        assert cached["cached"] and cached["evaluation_id"] == original["evaluation_id"]
    assert len(setup.calls) == 2


async def test_same_node_accumulates_across_runs_in_service_window(setup, monkeypatch):
    window = SimpleNamespace(id=str(uuid4()))
    monkeypatch.setattr(service_engine, "window_for_run", lambda *args: window)
    first = await _evaluate_v2(*request(setup, "judge"))
    second = await _evaluate_v2(*request(setup, "judge", run=setup.new_run()))

    assert first["status"] == "completed"
    assert second["status"] == "failed" and second["reason"] == "JUDGE_BUDGET_EXHAUSTED"
    assert len(setup.calls) == 1
    job = setup.db.query(WorkspaceJob).filter_by(kind=typed_judge.KIND).one()
    assert job.result["calls"] == 1


async def test_caller_cannot_change_batch_scope_or_request_identity(setup):
    payload, ctx = request(setup, "judge")
    first = await _evaluate_v2(payload, ctx)
    payload.update(batch_key="fresh-budget", request_key="fresh-call", _skill_node_id="other")
    payload["_typed_evaluation"]["typed_evaluation"].update(
        batch_key="another-budget", request_key="another-call"
    )
    again = await _evaluate_v2(payload, ctx)
    assert again["cached"] and again["evaluation_id"] == first["evaluation_id"]
    assert len(setup.calls) == 1

    payload["_typed_evaluation"]["node_id"] = "other"
    with pytest.raises(ValueError, match="TYPED_EVALUATION_NODE_SCOPE_MISMATCH"):
        await _evaluate_v2(payload, ctx)
    assert len(setup.calls) == 1


async def test_same_node_cannot_reset_budget_by_changing_its_contract(setup):
    payload, ctx = request(setup, "judge")
    assert (await _evaluate_v2(payload, ctx))["status"] == "completed"
    payload["_typed_evaluation"]["typed_evaluation"]["budget"]["max_calls"] = 2
    with pytest.raises(typed_judge.TypedEvaluationError, match="JUDGE_BATCH_CONTRACT_CHANGED"):
        await _evaluate_v2(payload, ctx)
    assert len(setup.calls) == 1


async def test_context_without_engine_node_preserves_legacy_batch_scope(setup, monkeypatch):
    payload, ctx = request(setup, "judge")
    ctx.pop("_skill_node_id")
    captured = []

    async def evaluate(config, context):
        captured.append(config["batch_key"])
        return {}

    monkeypatch.setattr(typed_judge, "typed_evaluate", evaluate)
    await _evaluate_v2(payload, ctx)
    window = SimpleNamespace(id=str(uuid4()))
    monkeypatch.setattr(service_engine, "window_for_run", lambda *args: window)
    await _evaluate_v2(payload, ctx)
    assert captured == [setup.run.id, window.id]
