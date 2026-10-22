"""Native decisions retain Judge governance, provenance and honest uncertainty."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.typed_evaluation import TypedEvaluationInput, compile_typed_output_schema
from app.services.evaluation import typed_judge as judge
from app.services.evaluation.typesafe_judge import canonical_answers, compile_request
from app.services.model_plane import typesafe
from app.services.model_plane.execution import ModelExecution


@pytest.fixture()
def payload():
    text = "The customer asks for a shipping investigation. No refund has been approved."
    return {
        "batch_key": "typed-decisions-test",
        "request_key": "case-1",
        "subject_ref": "case-1@v1",
        "rubric_id": "triage",
        "rubric_version": "1",
        "questions": [
            {
                "key": "investigation",
                "question": "Does the customer ask for an investigation?",
                "type": "boolean",
                "requires_evidence": False,
                "acceptable_values": [True],
            },
            {
                "key": "department",
                "question": "Which department should handle the request?",
                "type": "choice",
                "choices": ["shipping", "billing"],
                "requires_evidence": False,
                "acceptable_values": ["shipping"],
            },
            {
                "key": "priority",
                "question": "Rate priority from 1 (low) to 3 (high).",
                "type": "score",
                "minimum": 1.0,
                "maximum": 3.0,
                "requires_evidence": False,
                "accept_minimum": 1.0,
            },
            {
                "key": "refund",
                "question": "Has a refund been approved?",
                "type": "probability",
                "requires_evidence": False,
                "accept_maximum": 0.1,
            },
        ],
        "evidence": [
            {"id": "source", "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        ],
        "budget": {"max_calls": 2, "max_tokens": 100000, "max_cost_usd": 1.0},
        "tariff": {
            "provider": "typesafe",
            "model": "jev-test",
            "input_per_million": 1.0,
            "output_per_million": 2.0,
            "currency": "USD",
            "reference": "test-only-tariff",
        },
    }


def response(questions):
    return {
        "model": "jev-test",
        "answers": {
            "investigation": {"type": "noul", "noul": 0.98},
            "department": {
                "type": "choice",
                "choice": "option_0",
                "confidence": 0.8,
                "probabilities": {"option_0": 0.9, "option_1": 0.1},
            },
            "priority": {
                "type": "score",
                "score": 1.4,
                "confidence": 0.3,
                "probabilities": {"0": 0.0, "1": 0.6, "2": 0.4},
                "legend": {
                    str(i): label for i, label in enumerate(questions["priority"]["criteria"])
                },
            },
            "refund": {"type": "noul", "noul": 0.01},
        },
        "usage": {"input_tokens": 120, "output_tokens": 20},
    }


@pytest.fixture()
def context(db_session, payload):
    user = User(id=str(uuid4()), username="typesafe-" + uuid4().hex, role="user", is_active=True)
    workspace = Workspace(
        id=str(uuid4()), name="Typed decisions", slug="typesafe-" + uuid4().hex, is_active=True
    )
    db_session.add_all([user, workspace])
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member"))
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        status="running",
        input_ref={"evidence": copy.deepcopy(payload["evidence"])},
    )
    db_session.add(run)
    db_session.commit()
    return {
        "workspace_id": workspace.id,
        "user_id": user.id,
        "run_id": run.id,
        "_model_execution": ModelExecution(
            "typesafe", "jev-test", "workspace", "published_graph", _api_key="test-key"
        ),
        "_model_policy_check": lambda candidate: None,
    }


def test_native_answers_keep_values_and_provider_confidence_separate(payload):
    spec = TypedEvaluationInput.model_validate(payload)
    state, questions = compile_request(spec)
    assert payload["evidence"][0]["text"] in state
    answers, metadata = canonical_answers(spec, response(questions)["answers"])
    assert [a["value"] for a in answers.values()] == [True, "shipping", 2.4, 0.01]
    assert all(a["confidence"] is None and a["evidence"] == [] for a in answers.values())
    assert metadata["answers"]["department"]["confidence"] == 0.8
    assert metadata["confidence_is_calibrated_for_rubric"] is False
    assert judge._quality(spec, answers) == "passed"


def test_ties_abstain_and_probability_criteria_remain_business_defined(payload):
    spec = TypedEvaluationInput.model_validate(payload)
    _, questions = compile_request(spec)
    native = response(questions)["answers"]
    native["investigation"]["noul"] = 0.5
    native["department"]["probabilities"] = {"option_0": 0.5, "option_1": 0.5}
    answers, _ = canonical_answers(spec, native)
    assert answers["investigation"]["status"] == answers["department"]["status"] == "abstained"
    assert judge._quality(spec, answers) == "unassessed"
    native["refund"]["noul"] = 0.3
    answers, _ = canonical_answers(spec, native)
    assert judge._quality(spec, answers) == "failed"


@pytest.mark.parametrize(
    "kind", ["citations", "multi_choice", "wide_score", "fractional_score", "image"]
)
def test_unsupported_contracts_are_refused_without_weakening_requirements(payload, kind):
    if kind == "citations":
        payload["questions"][0]["requires_evidence"] = True
    elif kind == "multi_choice":
        payload["questions"][1]["type"] = "multi_choice"
    elif kind == "wide_score":
        payload["questions"][2]["maximum"] = 20.0
    elif kind == "fractional_score":
        payload["questions"][2]["minimum"] = 0.5
    else:
        payload["evidence"][0]["kind"] = "image"
    with pytest.raises(ValueError):
        compile_request(TypedEvaluationInput.model_validate(payload))


async def test_real_judge_persists_native_decisions_and_reuses_paid_result(
    payload, context, monkeypatch, db_session
):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        return typesafe.normalize_response(
            response(kwargs["questions"]), questions=kwargs["questions"]
        )

    monkeypatch.setattr(typesafe, "evaluate", evaluate)
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "completed" and result["quality_status"] == "passed"
    assert result["disposition"] == "review" and result["confidence"] is None
    assert result["usage"]["total_tokens"] == 140
    assert result["cost"]["amount"] == pytest.approx(0.00016)
    assert result["typed_decisions"]["answers"]["department"]["confidence"] == 0.8
    Draft202012Validator(compile_typed_output_schema(payload["questions"])).validate(result)
    again = await judge.typed_evaluate(payload, context)
    assert len(calls) == 1 and again["evaluation_id"] == result["evaluation_id"]
    db_session.expire_all()
    saved = db_session.get(EvaluationScore, result["evaluation_id"])
    assert saved.metadata_["typed_evaluation"]["typed_decisions"] == result["typed_decisions"]


async def test_citation_requirement_blocks_before_dispatch(payload, context, monkeypatch):
    payload["questions"][0]["requires_evidence"] = True

    async def forbidden(**kwargs):
        pytest.fail("Unsupported evidence contract must not dispatch")

    monkeypatch.setattr(typesafe, "evaluate", forbidden)
    with pytest.raises(judge.TypedEvaluationError, match="JUDGE_TYPESAFE_CONTRACT_UNSUPPORTED"):
        await judge.typed_evaluate(payload, context)


async def test_invalid_provider_response_keeps_measured_spend(payload, context, monkeypatch):
    async def invalid(**kwargs):
        raise typesafe.TypeSafeError(
            "TYPESAFE_RESPONSE_INVALID",
            usage={"input_tokens": 120, "output_tokens": 20},
            returned_model="jev-test",
        )

    monkeypatch.setattr(typesafe, "evaluate", invalid)
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "failed" and result["quality_status"] == "unassessed"
    assert result["reason"] == "TYPESAFE_RESPONSE_INVALID"
    assert result["usage"]["total_tokens"] == 140 and result["cost"]["amount"] is not None
    assert "typed_decisions" not in result


async def test_missing_usage_stays_unknown_and_keeps_reservation(payload, context, monkeypatch):
    async def unmeasured(**kwargs):
        body = response(kwargs["questions"])
        body.pop("usage")
        return typesafe.normalize_response(body, questions=kwargs["questions"])

    monkeypatch.setattr(typesafe, "evaluate", unmeasured)
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "completed"
    assert result["cost"]["amount"] is None
    assert result["budget"]["includes_unsettled_reservations"] is True
    assert result["budget"]["unsettled_units"] == 1


async def test_pinned_judge_reserves_full_input_context_and_labels_local_output_provision(
    payload, context, monkeypatch, db_session
):
    from app.models.workspace_job import WorkspaceJob

    payload["tariff"].update(model="jev-1.13.0", input_per_million=0.042, output_per_million=0)
    context["_model_execution"] = replace(context["_model_execution"], model="jev-1.13.0")

    async def evaluate(**kwargs):
        body = response(kwargs["questions"])
        body["model"] = "jev-1.13.0"
        return typesafe.normalize_response(body, questions=kwargs["questions"])

    monkeypatch.setattr(typesafe, "evaluate", evaluate)
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "completed"
    assert result["generation_contract"]["input_token_reservation"] == 65536
    assert result["generation_contract"]["output_token_provision_scope"] == (
        "local_judge_not_provider_cap"
    )
    db_session.expire_all()
    job = db_session.query(WorkspaceJob).filter_by(workspace_id=context["workspace_id"]).one()
    unit = next(iter(job.result["units"].values()))
    assert unit["reserved_tokens"] == 65536 + 2048
    assert Decimal(unit["reserved_cost_usd"]) == Decimal("0.002752512")
    assert result["usage"]["total_tokens"] == 140
    assert result["cost"]["amount"] == pytest.approx(0.00000504)
    assert result["budget"]["charged_tokens"] == 140
    assert result["disposition"] == "review"


async def test_pinned_judge_refuses_local_budget_below_context_before_sending(
    payload, context, monkeypatch
):
    payload["tariff"].update(model="jev-1.13.0", input_per_million=0.042, output_per_million=0)
    payload["budget"]["max_tokens"] = 65535
    context["_model_execution"] = replace(context["_model_execution"], model="jev-1.13.0")

    async def forbidden(**kwargs):
        pytest.fail("Insufficient local Judge reservation must refuse before send")

    monkeypatch.setattr(typesafe, "evaluate", forbidden)
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "failed"
    assert result["reason"] == "JUDGE_BUDGET_EXHAUSTED"
    assert result["budget"]["calls"] == 0
    assert result["budget"]["charged_tokens"] == 0
    assert result["budget"]["includes_unsettled_reservations"] is False


@pytest.mark.parametrize("returned_model", ["jev-other", None, "jev-1.13.0"])
async def test_pinned_judge_never_prices_a_mismatched_or_unverified_model(
    payload, context, monkeypatch, db_session, returned_model
):
    from app.models.workspace_job import WorkspaceJob

    payload["tariff"].update(model="jev-1.13.0", input_per_million=0.042, output_per_million=0)
    context["_model_execution"] = replace(context["_model_execution"], model="jev-1.13.0")

    async def invalid(**kwargs):
        raise typesafe.TypeSafeError(
            "TYPESAFE_RETURNED_MODEL_MISMATCH"
            if returned_model and returned_model != "jev-1.13.0"
            else "TYPESAFE_RESPONSE_INVALID",
            usage={"input_tokens": 120, "output_tokens": 20},
            returned_model=returned_model,
        )

    monkeypatch.setattr(typesafe, "evaluate", invalid)
    result = await judge.typed_evaluate(payload, context)
    assert result["status"] == "failed"
    assert result["usage"]["total_tokens"] == 140
    assert result["budget"]["charged_tokens"] == 140
    assert "typed_decisions" not in result
    db_session.expire_all()
    job = db_session.query(WorkspaceJob).filter_by(workspace_id=context["workspace_id"]).one()
    unit = next(iter(job.result["units"].values()))
    if returned_model != "jev-1.13.0":
        assert result["cost"]["amount"] is None
        assert result["cost"]["measurement_coverage"] == "unavailable"
        assert result["budget"]["charged_cost_usd"] == pytest.approx(0.002752512)
        assert result["budget"]["includes_unsettled_reservations"] is True
        assert unit["needs_reconciliation"] is True
    else:
        # Invalid decisions from the admitted model still incur their real
        # measured usage, so a parse failure alone is not a pricing refusal.
        assert result["cost"]["amount"] == pytest.approx(0.00000504)
        assert result["budget"]["includes_unsettled_reservations"] is False
        assert unit["needs_reconciliation"] is False


@pytest.mark.parametrize("requires_citations", [False, True])
def test_publication_checks_native_engine_capabilities(payload, db_session, requires_citations):
    from app.models.skill import Skill
    from app.services.flow_contracts import FlowContractError, compile_execution_contract
    from app.services.skills_registry.seed import SEED_SKILLS

    definition = next(skill for skill in SEED_SKILLS if skill["slug"] == "evaluate_v2")
    db_session.add(Skill(**copy.deepcopy(definition)))
    db_session.flush()
    payload["questions"][0]["requires_evidence"] = requires_citations
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "kind": "source"},
            {
                "id": "judge",
                "kind": "task",
                "config": {"skill_slug": "evaluate_v2", "typed_evaluation": payload},
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "source", "to": "judge"}, {"from": "judge", "to": "sink"}],
    }
    if requires_citations:
        with pytest.raises(FlowContractError, match="TypeSafe does not return citations") as caught:
            compile_execution_contract(
                db_session, flow=flow, workspace_id=None, runtime_mode="dag_overlay"
            )
        assert caught.value.code == "typed_questions_invalid"
    else:
        contract = compile_execution_contract(
            db_session, flow=flow, workspace_id=None, runtime_mode="dag_overlay"
        )
        assert contract["nodes"]["judge"]["output_schema"]["properties"]["schema_version"] == {
            "const": 2
        }
