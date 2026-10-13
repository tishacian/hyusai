"""Typed judgments use a mocked transport, real governance and durable budgets."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.db.base import SessionLocal
from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.schemas.typed_evaluation import (
    TypedEvaluationInput,
    compile_question_schema,
    compile_typed_output_schema,
)
from app.services.evaluation import typed_judge as judge
from app.services.model_plane import execution
from app.services.model_plane.execution import ModelExecution


@pytest.fixture()
def payload():
    text = "The translated segment omits a warning and uses an incorrect technical term."
    return {
        "batch_key": "showcase-2026-10-13", "request_key": "segment-1", "subject_ref": "segment-1@v1",
        "rubric_id": "translation-errors", "rubric_version": "1",
        "questions": [
            {"key": "safe", "question": "Is the warning present?", "type": "boolean", "acceptable_values": [True]},
            {"key": "category", "question": "What is the primary error category?", "type": "choice", "choices": ["WT", "SE", "OM", "SA", "SP", "PE", "ME"]},
            {"key": "categories", "question": "Which categories occur?", "type": "multi_choice", "choices": ["WT", "SE", "OM", "SA", "SP", "PE", "ME"], "acceptable_values": []},
            {"key": "quality", "question": "Rate the translation quality from zero to twenty.", "type": "score", "minimum": 0.0, "maximum": 20.0, "accept_minimum": 18.0},
            {"key": "risk", "question": "What is the probability that the missing warning changes meaning?", "type": "probability", "accept_maximum": 0.1},
        ],
        "evidence": [{"id": "source", "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}],
        "budget": {"max_calls": 3, "max_tokens": 100000, "max_cost_usd": 1.0},
        "tariff": {"provider": "openai", "model": "judge-test", "input_per_million": 1.0,
                   "output_per_million": 2.0, "currency": "USD", "reference": "reviewed-test-tariff"},
    }


@pytest.fixture()
def context(db_session, payload):
    suffix = uuid4().hex
    user = User(id=str(uuid4()), username="judge-" + suffix, role="user", is_active=True)
    workspace = Workspace(id=str(uuid4()), name="Typed judge", slug="typed-" + suffix, is_active=True)
    db_session.add_all([user, workspace])
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member"))
    run = Run(id=str(uuid4()), workspace_id=workspace.id, initiated_by_user_id=user.id,
              status="running", input_ref={"evidence": copy.deepcopy(payload["evidence"])})
    db_session.add(run)
    db_session.commit()
    return {"workspace_id": workspace.id, "user_id": user.id, "run_id": run.id,
            "_model_execution": ModelExecution("openai", "judge-test", "workspace", "workspace"),
            "_model_policy_check": lambda candidate: None}


def answers(payload):
    text = payload["evidence"][0]["text"]
    citation = {"evidence_id": "source", "start": 0, "end": len(text), "quote": text}
    values = [False, "OM", ["WT", "OM"], 9, .95]
    return {"answers": {question["key"]: {"status": "answered", "value": value, "reason": None,
        "explanation": "The supplied segment contains this evidence.", "evidence": [copy.deepcopy(citation)]}
        for question, value in zip(payload["questions"], values)}}


@pytest.fixture()
def provider(monkeypatch, payload):
    class Provider:
        calls = []
        response = answers(payload)
        report_usage = True
        effect = None

        async def generate(self, *, model, prompt, **options):
            self.calls.append({"model": model, "prompt": prompt, "options": options})
            if self.effect:
                value = self.effect()
                if asyncio.iscoroutine(value):
                    await value
            result = {"model": model, "content": self.response if isinstance(self.response, str) else json.dumps(self.response)}
            if self.report_usage:
                result["usage"] = {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200}
            return result

    client = Provider()
    monkeypatch.setattr(execution, "build_model_client", lambda *args, **kwargs: client)
    return client


def job(db_session):
    db_session.expire_all()
    return db_session.query(WorkspaceJob).filter_by(kind=judge.KIND).one()


async def test_questions_are_asked_independently_with_more_than_two_choices(payload, context, provider, db_session):
    result = await judge.typed_evaluate(payload, context)
    assert result["answers"]["category"]["value"] == "OM"  # third choice, not binary projection
    assert result["answers"]["categories"]["value"] == ["WT", "OM"]
    assert result["answers"]["quality"]["value"] == 9
    assert result["answers"]["risk"]["value"] == .95
    assert result["quality_status"] == "failed" and result["disposition"] == "review"
    assert result["confidence"] is None and all(a["confidence"] is None for a in result["answers"].values())
    assert all(q["question"] in provider.calls[0]["prompt"] for q in payload["questions"])
    assert provider.calls[0]["options"]["response_format"]["type"] == "json_schema"
    assert result["usage"]["total_tokens"] == 200
    assert result["cost"]["amount"] == pytest.approx(.00028)
    assert result["cost"]["billed_amount"] is None
    assert job(db_session).result["charged_tokens"] == 200
    score = db_session.get(EvaluationScore, result["evaluation_id"])
    assert score.workspace_id == context["workspace_id"] and score.run_id == context["run_id"]
    assert score.composite_score is None and score.hallucination_rate is None
    assert score.metadata_["source"] == "evaluate_v2"
    Draft202012Validator(compile_typed_output_schema(payload["questions"])).validate(result)


async def test_abstention_is_not_converted_to_zero_or_second_choice(payload, context, provider):
    provider.response["answers"]["category"] = {"status": "abstained", "value": None,
        "reason": "ambiguous", "explanation": "Both supplied categories may apply.", "evidence": []}
    result = await judge.typed_evaluate(payload, context)
    assert result["answers"]["category"]["value"] is None
    assert result["answers"]["category"]["status"] == "abstained"
    assert result["status"] == "partial" and result["coverage"]["questions_answered"] == 4


@pytest.mark.parametrize("change", [
    lambda answer: answer.update(value="invented"),
    lambda answer: answer.update(evidence=[]),
    lambda answer: answer["evidence"][0].update(evidence_id="another-workspace"),
    lambda answer: answer["evidence"][0].update(quote="Fabricated quote"),
    lambda answer: answer.update(status="abstained", reason=None),
])
async def test_invalid_answers_and_fabricated_evidence_never_route(payload, context, provider, change):
    change(provider.response["answers"]["category"])
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "failed" and result["reason"] == "JUDGE_RESPONSE_INVALID"
    assert all(answer["value"] is None for answer in result["answers"].values())
    assert result["disposition"] == "review" and result["cost"]["amount"] > 0


async def test_json_duplicate_keys_and_nonfinite_values_fail(payload, context, provider):
    provider.response = '{"answers": {}, "answers": {"x": NaN}}'
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "failed" and result["reason"] == "JUDGE_RESPONSE_INVALID"


async def test_retry_reuses_result_without_double_counting_usage(payload, context, provider, db_session):
    first = await judge.typed_evaluate(payload, context)
    second = await judge.typed_evaluate(payload, context)
    assert first["evaluation_id"] == second["evaluation_id"] and second["cached"]
    assert len(provider.calls) == 1 and second["usage"]["total_tokens"] == 0
    assert second["original_measurement"]["usage"]["total_tokens"] == 200
    assert second["cost"]["amount"] == 0 and job(db_session).result["calls"] == 1


async def test_idempotency_key_cannot_change_question(payload, context, provider):
    await judge.typed_evaluate(payload, context)
    payload["questions"][0]["question"] = "Different task"
    with pytest.raises(judge.TypedEvaluationError, match="REQUEST_KEY_CONFLICT"):
        await judge.typed_evaluate(payload, context)
    assert len(provider.calls) == 1


async def test_batch_budget_survives_new_request_and_run(payload, context, provider, db_session):
    payload["budget"]["max_calls"] = 1
    await judge.typed_evaluate(payload, context)
    old = db_session.get(Run, context["run_id"])
    replacement = Run(id=str(uuid4()), workspace_id=old.workspace_id, status="running", input_ref=copy.deepcopy(old.input_ref))
    db_session.add(replacement)
    db_session.commit()
    context["run_id"] = replacement.id
    payload["request_key"] = "second-segment"
    result = await judge.typed_evaluate(payload, context)
    assert result["reason"] == "JUDGE_BUDGET_EXHAUSTED" and len(provider.calls) == 1
    assert job(db_session).result["calls"] == 1


async def test_missing_usage_retains_reservation_and_unknown_cost(payload, context, provider, db_session):
    provider.report_usage = False
    result = await judge.typed_evaluate(payload, context)
    assert result["cost"]["amount"] is None and "usage" not in result
    assert result["provider_usage"]["measurement_coverage"] == "unavailable"
    assert result["budget"]["includes_unsettled_reservations"]
    assert job(db_session).result["charged_tokens"] > 200
    assert float(job(db_session).result["charged_cost_usd"]) > 0
    provider.report_usage = True
    payload["request_key"] = "measured-second-segment"
    following = await judge.typed_evaluate(payload, context)
    assert following["cost"]["amount"] is not None
    assert following["budget"]["includes_unsettled_reservations"]
    assert following["budget"]["unsettled_units"] == 1


async def test_cancellation_keeps_paid_reservation_and_cannot_blindly_repeat(payload, context, provider, db_session):
    def cancel():
        raise asyncio.CancelledError
    provider.effect = cancel
    with pytest.raises(asyncio.CancelledError):
        await judge.typed_evaluate(payload, context)
    assert job(db_session).result["calls"] == 1
    assert next(iter(job(db_session).result["units"].values()))["needs_reconciliation"]
    second = await judge.typed_evaluate(payload, context)
    assert second["cached"] and second["status"] == "failed" and len(provider.calls) == 1


async def test_transport_failure_is_charged_without_fallback(payload, context, provider, db_session):
    context["_model_execution"] = ModelExecution("openai", "judge-test", "workspace", "workspace",
        _fallbacks=(ModelExecution("ollama", "unqualified", "local", "local"),))
    def fail():
        raise TimeoutError("private diagnostic with secret=never-report")
    provider.effect = fail
    result = await judge.typed_evaluate(payload, context)
    assert len(provider.calls) == 1 and result["status"] == "failed"
    assert result["cost"]["amount"] is None and job(db_session).result["calls"] == 1
    assert "never-report" not in json.dumps(result)


async def test_pending_reservation_requires_reconciliation(payload, context, provider, db_session):
    await judge.typed_evaluate(payload, context)
    row = job(db_session)
    state = copy.deepcopy(row.result)
    next(iter(state["units"].values()))["status"] = "pending"
    row.result = state
    db_session.commit()
    with pytest.raises(judge.TypedEvaluationError, match="RECONCILIATION_REQUIRED"):
        await judge.typed_evaluate(payload, context)
    assert len(provider.calls) == 1


async def test_asset_resolver_is_required_and_confirms_exact_excerpt(payload, context, provider):
    payload["evidence"][0]["asset_ref"] = {"version_id": "approved-v1", "locator": "page:1"}
    with pytest.raises(judge.TypedEvaluationError, match="ASSET_RESOLVER_REQUIRED"):
        await judge.typed_evaluate(payload, context)
    context["_typed_judge_authorize_evidence"] = lambda evidence, ctx: {e["id"]: e["sha256"] for e in evidence}
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "completed"


async def test_cross_workspace_and_forged_text_are_refused_before_dispatch(payload, context, provider, db_session):
    payload["evidence"][0]["text"] = "A different text"
    with pytest.raises(judge.TypedEvaluationError, match="HASH_MISMATCH"):
        await judge.typed_evaluate(payload, context)
    assert provider.calls == []
    context["workspace_id"] = str(uuid4())
    with pytest.raises(judge.TypedEvaluationError, match="WORKSPACE_UNAVAILABLE"):
        await judge.typed_evaluate(payload, context)


async def test_policy_refusal_prevents_any_provider_work(payload, context, provider):
    def refuse(candidate):
        raise judge.TypedEvaluationError("JUDGE_POLICY_DENIED")
    context["_model_policy_check"] = refuse
    with pytest.raises(judge.TypedEvaluationError, match="POLICY_DENIED"):
        await judge.typed_evaluate(payload, context)
    assert provider.calls == []


async def test_vision_is_explicitly_unexamined_without_paid_text_substitution(payload, context, provider):
    payload["evidence"][0]["kind"] = "image"
    context["_typed_judge_authorize_evidence"] = lambda evidence, ctx: {e["id"]: e["sha256"] for e in evidence}
    result = await judge.typed_evaluate(payload, context)
    assert provider.calls == [] and result["reason"] == "vision_not_supported"
    assert result["coverage"]["images_total"] == 1 and result["coverage"]["images_examined"] == 0
    assert result["disposition"] == "review" and result["answers"]["safe"]["value"] is None


async def test_revocation_during_call_withholds_results_but_keeps_charge(payload, context, provider, db_session):
    def revoke():
        with SessionLocal() as db:
            user = db.get(User, context["user_id"])
            user.is_active = False
            db.commit()
    provider.effect = revoke
    with pytest.raises(judge.TypedEvaluationError, match="ACCESS_REVOKED"):
        await judge.typed_evaluate(payload, context)
    assert job(db_session).result["calls"] == 1
    evaluation_id = next(iter(job(db_session).result["units"].values()))["evaluation_id"]
    saved = db_session.get(EvaluationScore, evaluation_id).metadata_["typed_evaluation"]
    assert saved["status"] == "failed" and saved["cost"]["amount"] > 0
    assert saved["answers"]["safe"]["value"] is None


@pytest.mark.parametrize("mutate", [
    lambda body: body["questions"][0].update(key="category"),
    lambda body: body["questions"][1].update(choices=["WT", "WT"]),
    lambda body: body["questions"][3].update(minimum=30.0),
    lambda body: body["questions"][3].update(accept_minimum=30.0),
    lambda body: body["budget"].update(max_tokens=True),
    lambda body: body["tariff"].update(input_per_million=float("nan")),
])
def test_contract_rejects_ambiguous_or_unbounded_questions(payload, mutate):
    mutate(payload)
    with pytest.raises(ValidationError):
        TypedEvaluationInput.model_validate(payload)


def test_output_schema_freezes_the_seven_category_taxonomy(payload):
    schema = compile_question_schema(payload["questions"])
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["answers"]["properties"]["category"]["properties"]["value"]["anyOf"][0]["enum"] == ["WT", "SE", "OM", "SA", "SP", "PE", "ME"]
